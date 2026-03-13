from __future__ import annotations

import os
import random
import time

import requests


ARXIV_HTTPS = "https://export.arxiv.org/api/query"
ARXIV_HTTP = "http://export.arxiv.org/api/query"
DEFAULT_TIMEOUT = float(os.getenv("ARXIV_TIMEOUT", "45"))
MAX_ATTEMPTS = int(os.getenv("ARXIV_MAX_ATTEMPTS", "6"))
BASE_PAUSE = float(os.getenv("ARXIV_PAUSE", "1.5"))
MAX_SLEEP = float(os.getenv("ARXIV_MAX_SLEEP", "20"))
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
HEADERS = {
    "User-Agent": os.getenv(
        "ARXIV_UA",
        "research-assist/0.1.0 (+https://github.com/zhanglg12/research-assist)",
    ),
    "Accept": "application/atom+xml,application/xml;q=0.9,*/*;q=0.8",
}
SESSION = requests.Session()


def _sleep_backoff(attempt: int) -> None:
    delay = min(BASE_PAUSE * (2 ** (attempt - 1)) + random.uniform(0, 0.5), MAX_SLEEP)
    time.sleep(delay)


def _request_with_retry(base_url: str, params: dict[str, str], timeout: float | None = None) -> requests.Response:
    request_timeout = timeout or DEFAULT_TIMEOUT
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = SESSION.get(base_url, params=params, headers=HEADERS, timeout=request_timeout)
            if response.status_code in RETRYABLE_STATUS:
                raise requests.HTTPError(f"HTTP {response.status_code}", response=response)
            return response
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
        except requests.HTTPError as exc:
            last_error = exc
            status_code = getattr(exc.response, "status_code", None)
            if status_code not in RETRYABLE_STATUS:
                break
        if attempt < MAX_ATTEMPTS:
            _sleep_backoff(attempt)
    if last_error is not None:
        raise last_error
    raise RuntimeError("Unknown arXiv request error")


def fetch_arxiv_feed(
    query: str,
    *,
    start: int = 0,
    max_results: int = 10,
    sort_by: str = "submittedDate",
    sort_order: str = "descending",
) -> str:
    params = {
        "search_query": query,
        "start": str(start),
        "max_results": str(max_results),
        "sortBy": sort_by,
        "sortOrder": sort_order,
    }
    last_error: Exception | None = None
    for base_url in (ARXIV_HTTPS, ARXIV_HTTP):
        try:
            response = _request_with_retry(base_url, params=params, timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
            return response.text
        except Exception as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("Unknown arXiv retrieval failure")

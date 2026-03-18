from __future__ import annotations

import os
import random
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from .client import fetch_arxiv_feed
from .parser import parse_feed
from .query import build_search_query


SUPPORTED_SOURCES = ("arxiv", "openalex", "semantic_scholar")
SOURCE_LABELS = {
    "arxiv": "arXiv",
    "openalex": "OpenAlex",
    "semantic_scholar": "Semantic Scholar",
}
GENERIC_TIMEOUT = float(os.getenv("RESEARCH_ASSIST_SOURCE_TIMEOUT", "45"))
MAX_ATTEMPTS = int(os.getenv("RESEARCH_ASSIST_SOURCE_MAX_ATTEMPTS", "6"))
BASE_PAUSE = float(os.getenv("RESEARCH_ASSIST_SOURCE_PAUSE", "1.5"))
MAX_SLEEP = float(os.getenv("RESEARCH_ASSIST_SOURCE_MAX_SLEEP", "20"))
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
USER_AGENT = os.getenv(
    "RESEARCH_ASSIST_SOURCE_UA",
    "research-assist/0.1.0 (+https://github.com/zhanglg12/research-assist)",
)
SESSION = requests.Session()
SEMANTIC_SCHOLAR_FIELDS = ",".join(
    [
        "title",
        "abstract",
        "authors",
        "year",
        "venue",
        "url",
        "externalIds",
        "openAccessPdf",
    ]
)


def normalize_source_name(value: object) -> str | None:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "s2": "semantic_scholar",
        "semantic": "semantic_scholar",
        "semanticscholar": "semantic_scholar",
    }
    text = aliases.get(text, text)
    return text if text in SUPPORTED_SOURCES else None


def source_label(source: object) -> str:
    normalized = normalize_source_name(source) or "arxiv"
    return SOURCE_LABELS[normalized]


def get_enabled_sources(config: dict[str, Any] | None) -> list[str]:
    if not isinstance(config, dict):
        return ["arxiv"]
    sources_cfg = config.get("literature_sources", {})
    if not isinstance(sources_cfg, dict):
        return ["arxiv"]
    raw_enabled = sources_cfg.get("enabled", ["arxiv"])
    if not isinstance(raw_enabled, list):
        raw_enabled = ["arxiv"]

    enabled: list[str] = []
    for raw in raw_enabled:
        normalized = normalize_source_name(raw)
        if normalized and normalized not in enabled:
            enabled.append(normalized)
    return enabled or ["arxiv"]


def source_config(config: dict[str, Any] | None, source: str) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    sources_cfg = config.get("literature_sources", {})
    if not isinstance(sources_cfg, dict):
        return {}
    raw = sources_cfg.get(source, {})
    return raw if isinstance(raw, dict) else {}


def build_interest_queries(interest: dict[str, Any], defaults: dict[str, Any]) -> dict[str, str]:
    logic = str(interest.get("logic") or defaults.get("logic") or "AND")
    categories = list(interest.get("categories") or defaults.get("categories") or [])
    method_keywords = list(interest.get("method_keywords") or interest.get("keywords") or [])
    query_aliases = list(interest.get("query_aliases") or [])
    keywords = list(dict.fromkeys([*method_keywords, *query_aliases]))[:4]
    exclude_keywords = list(interest.get("exclude_keywords") or defaults.get("exclude_keywords") or [])

    text_terms = [term.strip() for term in keywords if str(term).strip()]
    generic_query = " ".join(_quote_phrase(term) for term in text_terms) if text_terms else str(interest.get("label") or "").strip()
    return {
        "arxiv": build_search_query(categories, text_terms, exclude_keywords, logic),
        "openalex": generic_query,
        "semantic_scholar": generic_query,
    }


def build_free_text_query(source: str, query: str) -> str:
    normalized = normalize_source_name(source) or "arxiv"
    if normalized == "arxiv":
        return build_search_query(categories=[], keywords=[query], exclude_keywords=None, logic="OR")
    return query.strip()


def fetch_items_for_source(
    source: str,
    query_text: str,
    *,
    max_results: int,
    page_size: int,
    since_days: int,
    sort_by: str,
    sort_order: str,
    config: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    normalized = normalize_source_name(source)
    if not normalized or not query_text.strip():
        return []
    if normalized == "arxiv":
        return _fetch_arxiv_items(query_text, max_results=max_results, page_size=page_size, since_days=since_days, sort_by=sort_by, sort_order=sort_order)
    if normalized == "openalex":
        return _fetch_openalex_items(query_text, max_results=max_results, page_size=min(page_size, 100), since_days=since_days, config=config)
    if normalized == "semantic_scholar":
        return _fetch_semantic_scholar_items(query_text, max_results=max_results, page_size=min(page_size, 100), config=config)
    return []


def canonical_paper_key(item: dict[str, Any]) -> str:
    doi = normalize_doi(item.get("doi"))
    arxiv_id = normalize_arxiv_id(item.get("arxiv_id"))

    # arXiv DOIs (10.48550/arxiv.*) should resolve to the arXiv ID key
    # so that the same paper from arXiv and Semantic Scholar deduplicates
    if doi and doi.startswith("10.48550/arxiv."):
        extracted = normalize_arxiv_id(doi.removeprefix("10.48550/arxiv."))
        if extracted:
            return f"arxiv:{extracted}"

    if doi:
        return f"doi:{doi}"

    if arxiv_id:
        return f"arxiv:{arxiv_id}"

    title = normalize_title(item.get("title"))
    year = item.get("year")
    if title and year:
        return f"title:{title}:{year}"
    if title:
        return f"title:{title}"

    openalex_id = str(item.get("openalex_id") or "").strip()
    if openalex_id:
        return f"openalex:{openalex_id.lower()}"

    semantic_id = str(item.get("semantic_scholar_id") or "").strip()
    if semantic_id:
        return f"semantic_scholar:{semantic_id.lower()}"
    return f"fallback:{str(item.get('id') or item.get('provider') or 'item').strip().lower()}"


def merge_source_items(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)

    providers = list(existing.get("source_providers") or [])
    for provider in incoming.get("source_providers") or []:
        if provider not in providers:
            providers.append(provider)
    merged["source_providers"] = providers

    provider_ids = dict(existing.get("provider_ids") or {})
    provider_ids.update(incoming.get("provider_ids") or {})
    merged["provider_ids"] = provider_ids

    source_records = list(existing.get("source_records") or [])
    for record in incoming.get("source_records") or []:
        if record not in source_records:
            source_records.append(record)
    merged["source_records"] = source_records

    for field_name in ("title", "summary", "html_url", "pdf_url", "venue_inferred", "published", "updated", "comments", "journal_ref"):
        current = str(merged.get(field_name) or "")
        candidate = str(incoming.get(field_name) or "")
        if len(candidate.strip()) > len(current.strip()):
            merged[field_name] = incoming.get(field_name)

    if not merged.get("year") and incoming.get("year"):
        merged["year"] = incoming.get("year")

    merged["authors"] = _merge_string_lists(existing.get("authors"), incoming.get("authors"))
    merged["categories"] = _merge_string_lists(existing.get("categories"), incoming.get("categories"))
    merged["code_urls"] = _merge_string_lists(existing.get("code_urls"), incoming.get("code_urls"))
    merged["project_urls"] = _merge_string_lists(existing.get("project_urls"), incoming.get("project_urls"))
    merged["other_urls"] = _merge_string_lists(existing.get("other_urls"), incoming.get("other_urls"))
    merged["source_links"] = _merge_string_lists(existing.get("source_links"), incoming.get("source_links"))

    for field_name in ("doi", "arxiv_id", "openalex_id", "semantic_scholar_id", "abstract_source"):
        if not merged.get(field_name) and incoming.get(field_name):
            merged[field_name] = incoming.get(field_name)

    if _item_quality(incoming) > _item_quality(existing):
        merged["provider"] = incoming.get("provider", merged.get("provider"))
        merged["id"] = incoming.get("id", merged.get("id"))

    return merged


def display_identifier(item: dict[str, Any]) -> str:
    doi = normalize_doi(item.get("doi"))
    if doi:
        return f"DOI {doi}"

    arxiv_id = normalize_arxiv_id(item.get("arxiv_id"))
    if arxiv_id:
        return f"arXiv {arxiv_id}"

    openalex_id = str(item.get("openalex_id") or "").strip()
    if openalex_id:
        return openalex_id.rsplit("/", 1)[-1]

    semantic_id = str(item.get("semantic_scholar_id") or "").strip()
    if semantic_id:
        return semantic_id[:12]

    fallback_id = str(item.get("id") or "").strip()
    return fallback_id.rsplit("/", 1)[-1] if fallback_id else ""


def normalize_doi(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    lowered = text.lower()
    lowered = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", lowered)
    lowered = re.sub(r"^doi:", "", lowered)
    return lowered or None


def normalize_arxiv_id(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    lowered = text.lower()
    lowered = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", lowered)
    lowered = re.sub(r"^arxiv:", "", lowered)
    lowered = lowered.removesuffix(".pdf")
    # Strip version suffix (e.g. "2501.05171v2" → "2501.05171") for stable dedup
    lowered = re.sub(r"v\d+$", "", lowered)
    return lowered or None


def normalize_title(value: object) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _fetch_arxiv_items(
    query_text: str,
    *,
    max_results: int,
    page_size: int,
    since_days: int,
    sort_by: str,
    sort_order: str,
) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(days=since_days) if since_days > 0 else None
    collected: list[dict[str, Any]] = []
    start = 0
    max_pages = max(1, (max_results + max(page_size, 1) - 1) // max(page_size, 1))
    reached_cutoff = False

    for _ in range(max_pages):
        xml_text = fetch_arxiv_feed(query_text, start=start, max_results=page_size, sort_by=sort_by, sort_order=sort_order)
        page_items = parse_feed(xml_text)
        if not page_items:
            break
        for item in page_items:
            item_timestamp = _item_timestamp(item)
            if cutoff and item_timestamp and item_timestamp < cutoff:
                reached_cutoff = True
                break
            item["provider"] = "arxiv"
            item["doi"] = None
            item["openalex_id"] = None
            item["semantic_scholar_id"] = None
            item["year"] = item.get("year")
            item["abstract_source"] = "arxiv_atom"
            item["source_providers"] = ["arxiv"]
            item["provider_ids"] = {"arxiv": str(item.get("id") or item.get("arxiv_id") or "")}
            item["source_records"] = [{"provider": "arxiv", "id": str(item.get("id") or item.get("arxiv_id") or "")}]
            item["source_links"] = _merge_string_lists(item.get("html_url"), item.get("pdf_url"), item.get("code_urls"), item.get("project_urls"), item.get("other_urls"))
            collected.append(item)
            if len(collected) >= max_results:
                break
        if len(collected) >= max_results or reached_cutoff or len(page_items) < page_size:
            break
        start += page_size
    return collected


def _fetch_openalex_items(
    query_text: str,
    *,
    max_results: int,
    page_size: int,
    since_days: int,
    config: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    page = 1
    collected: list[dict[str, Any]] = []
    settings = source_config(config, "openalex")
    params: dict[str, str] = {
        "search": query_text,
        "per_page": str(max(1, min(page_size, 100))),
    }
    mailto = str(settings.get("mailto") or "").strip()
    if mailto:
        params["mailto"] = mailto
    api_key = str(settings.get("api_key") or os.getenv("OPENALEX_API_KEY") or "").strip()
    if api_key:
        params["api_key"] = api_key
    if since_days > 0:
        cutoff_date = datetime.now(UTC).date() - timedelta(days=since_days)
        params["filter"] = f"from_publication_date:{cutoff_date.isoformat()}"

    while len(collected) < max_results:
        params["page"] = str(page)
        payload = _request_json_with_retry("https://api.openalex.org/works", params=params)
        results = payload.get("results", []) if isinstance(payload, dict) else []
        if not results:
            break
        for result in results:
            collected.append(_normalize_openalex_item(result))
            if len(collected) >= max_results:
                break
        if len(results) < int(params["per_page"]):
            break
        page += 1
    return collected


def _fetch_semantic_scholar_items(
    query_text: str,
    *,
    max_results: int,
    page_size: int,
    config: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    offset = 0
    collected: list[dict[str, Any]] = []
    settings = source_config(config, "semantic_scholar")
    headers = {"User-Agent": USER_AGENT}
    api_key = str(settings.get("api_key") or os.getenv("SEMANTIC_SCHOLAR_API_KEY") or "").strip()
    if api_key:
        headers["x-api-key"] = api_key

    while len(collected) < max_results:
        params = {
            "query": query_text,
            "limit": str(max(1, min(page_size, 100))),
            "offset": str(offset),
            "fields": SEMANTIC_SCHOLAR_FIELDS,
        }
        payload = _request_json_with_retry("https://api.semanticscholar.org/graph/v1/paper/search", params=params, headers=headers)
        results = payload.get("data", []) if isinstance(payload, dict) else []
        if not results:
            break
        for result in results:
            collected.append(_normalize_semantic_scholar_item(result))
            if len(collected) >= max_results:
                break
        next_offset = payload.get("next") if isinstance(payload, dict) else None
        if not isinstance(next_offset, int) or len(results) < int(params["limit"]):
            break
        offset = next_offset
    return collected


def _normalize_openalex_item(raw: dict[str, Any]) -> dict[str, Any]:
    ids = raw.get("ids") or {}
    authorships = raw.get("authorships") or []
    authors = [
        str((entry.get("author") or {}).get("display_name") or "").strip()
        for entry in authorships
        if isinstance(entry, dict)
    ]
    authors = [author for author in authors if author]

    primary_location = raw.get("primary_location") or {}
    best_oa_location = raw.get("best_oa_location") or {}
    source_meta = primary_location.get("source") or {}
    published = raw.get("publication_date")
    updated = raw.get("updated_date")
    abstract = _reverse_openalex_abstract(raw.get("abstract_inverted_index"))
    doi = raw.get("doi") or ids.get("doi")
    landing_url = primary_location.get("landing_page_url") or raw.get("id")

    return {
        "id": raw.get("id"),
        "provider": "openalex",
        "title": raw.get("display_name") or "",
        "authors": authors,
        "primary_category": None,
        "categories": [],
        "published": published,
        "updated": updated,
        "year": raw.get("publication_year"),
        "comments": None,
        "journal_ref": None,
        "venue_inferred": source_meta.get("display_name") or raw.get("type"),
        "summary": abstract or "",
        "html_url": landing_url,
        "pdf_url": best_oa_location.get("pdf_url") or None,
        "code_urls": [],
        "project_urls": [],
        "other_urls": _merge_string_lists(landing_url, best_oa_location.get("landing_page_url")),
        "source_links": _merge_string_lists(landing_url, best_oa_location.get("landing_page_url"), best_oa_location.get("pdf_url"), doi),
        "doi": doi,
        "arxiv_id": None,
        "openalex_id": ids.get("openalex") or raw.get("id"),
        "semantic_scholar_id": None,
        "abstract_source": "openalex",
        "source_providers": ["openalex"],
        "provider_ids": {"openalex": str(ids.get("openalex") or raw.get("id") or "")},
        "source_records": [{"provider": "openalex", "id": str(ids.get("openalex") or raw.get("id") or "")}],
    }


def _normalize_semantic_scholar_item(raw: dict[str, Any]) -> dict[str, Any]:
    external_ids = raw.get("externalIds") or {}
    paper_id = str(raw.get("paperId") or "").strip()
    authors = [str(author.get("name") or "").strip() for author in (raw.get("authors") or []) if isinstance(author, dict)]
    authors = [author for author in authors if author]
    pdf_meta = raw.get("openAccessPdf") or {}
    doi = external_ids.get("DOI") or external_ids.get("Doi")
    arxiv_id = external_ids.get("ArXiv") or external_ids.get("Arxiv")
    url = raw.get("url") or (f"https://www.semanticscholar.org/paper/{paper_id}" if paper_id else "")

    return {
        "id": paper_id or url,
        "provider": "semantic_scholar",
        "title": raw.get("title") or "",
        "authors": authors,
        "primary_category": None,
        "categories": [],
        "published": None,
        "updated": None,
        "year": raw.get("year"),
        "comments": None,
        "journal_ref": None,
        "venue_inferred": raw.get("venue") or None,
        "summary": raw.get("abstract") or "",
        "html_url": url,
        "pdf_url": pdf_meta.get("url") or None,
        "code_urls": [],
        "project_urls": [],
        "other_urls": _merge_string_lists(url),
        "source_links": _merge_string_lists(url, pdf_meta.get("url"), doi),
        "doi": doi,
        "arxiv_id": arxiv_id,
        "openalex_id": None,
        "semantic_scholar_id": paper_id or None,
        "abstract_source": "semantic_scholar",
        "source_providers": ["semantic_scholar"],
        "provider_ids": {"semantic_scholar": paper_id},
        "source_records": [{"provider": "semantic_scholar", "id": paper_id}],
    }


def _reverse_openalex_abstract(inverted_index: Any) -> str:
    if not isinstance(inverted_index, dict) or not inverted_index:
        return ""

    positions: dict[int, str] = {}
    for token, token_positions in inverted_index.items():
        if not isinstance(token, str) or not isinstance(token_positions, list):
            continue
        for position in token_positions:
            if isinstance(position, int):
                positions[position] = token
    if not positions:
        return ""
    return " ".join(token for _, token in sorted(positions.items()))


def _item_timestamp(item: dict[str, Any]) -> datetime | None:
    for field_name in ("updated", "published"):
        timestamp = _parse_timestamp(item.get(field_name))
        if timestamp is not None:
            return timestamp

    year_value = item.get("year")
    if isinstance(year_value, int) and 1800 <= year_value <= 3000:
        return datetime(year_value, 1, 1, tzinfo=UTC)
    if isinstance(year_value, str) and year_value.isdigit():
        year_int = int(year_value)
        if 1800 <= year_int <= 3000:
            return datetime(year_int, 1, 1, tzinfo=UTC)
    return None


def _parse_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except Exception:
        return None


def _request_json_with_retry(
    url: str,
    *,
    params: dict[str, str],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    final_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        final_headers.update(headers)

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = SESSION.get(url, params=params, headers=final_headers, timeout=GENERIC_TIMEOUT)
            if response.status_code in RETRYABLE_STATUS:
                retry_after = _retry_after_seconds(response)
                if attempt < MAX_ATTEMPTS:
                    _sleep_backoff(attempt, retry_after=retry_after)
                    continue
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
        except requests.HTTPError as exc:
            last_error = exc
            if getattr(exc.response, "status_code", None) not in RETRYABLE_STATUS:
                break
        if attempt < MAX_ATTEMPTS:
            _sleep_backoff(attempt)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Unknown retrieval failure for {url}")


def _sleep_backoff(attempt: int, *, retry_after: int | None = None) -> None:
    if isinstance(retry_after, int) and retry_after > 0:
        time.sleep(min(retry_after, int(MAX_SLEEP)))
        return
    delay = min(BASE_PAUSE * (2 ** (attempt - 1)) + random.uniform(0, 0.5), MAX_SLEEP)
    time.sleep(delay)


def _retry_after_seconds(response: requests.Response) -> int | None:
    raw = response.headers.get("Retry-After")
    if raw and raw.isdigit():
        return int(raw)
    return None


def _merge_string_lists(*values: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        entries = value if isinstance(value, list) else [value]
        for entry in entries:
            text = str(entry or "").strip()
            if not text:
                continue
            lowered = text.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            merged.append(text)
    return merged


def _item_quality(item: dict[str, Any]) -> int:
    return sum(
        1
        for value in [
            item.get("summary"),
            item.get("doi"),
            item.get("arxiv_id"),
            item.get("pdf_url"),
            item.get("venue_inferred"),
            item.get("published"),
            item.get("updated"),
        ]
        if str(value or "").strip()
    )


def _quote_phrase(value: str) -> str:
    stripped = str(value or "").strip()
    if not stripped:
        return ""
    return f'"{stripped}"' if re.search(r"\s", stripped) else stripped

from __future__ import annotations

import argparse
import json
import re
import tomllib
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from .literature_sources import (
    build_interest_queries,
    canonical_paper_key,
    display_identifier,
    fetch_items_for_source,
    get_enabled_sources,
    merge_source_items,
)
from .profile_contract import normalize_profile_payload


def _load_toml(path: Path) -> dict[str, object]:
    with path.open("rb") as file_handle:
        return tomllib.load(file_handle)


def _load_json(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as file_handle:
        return json.load(file_handle)


def _load_config(path: Path) -> dict[str, object]:
    if path.suffix.lower() == ".json":
        return _load_json(path)
    return _load_toml(path)


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return normalized or "candidate"


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except Exception:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except Exception:
            return None


def _extract_year(item: dict[str, object]) -> int | None:
    year_value = item.get("year")
    if isinstance(year_value, int):
        return year_value
    if isinstance(year_value, str) and year_value.isdigit():
        return int(year_value)
    for field_name in ("updated", "published"):
        timestamp = _parse_timestamp(item.get(field_name))
        if timestamp is not None:
            return timestamp.year
    return None


def _ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _load_seen_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if isinstance(data, dict) and "ids" in data and isinstance(data["ids"], list):
        raw = {value for value in data["ids"] if isinstance(value, str)}
    elif isinstance(data, list):
        raw = {value for value in data if isinstance(value, str)}
    elif isinstance(data, dict):
        raw = {key for key in data.keys() if isinstance(key, str)}
    else:
        return set()
    # Migrate old-format bare arXiv IDs (e.g. "2501.12345") to canonical prefix form
    return {f"arxiv:{v}" if ":" not in v else v for v in raw}


def _write_seen_ids(path: Path, seen_ids: set[str]) -> None:
    _ensure_directory(path.parent)
    payload = {"ids": sorted(seen_ids), "updated_at": datetime.now(UTC).isoformat()}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _render_candidate_markdown(candidate: dict[str, object]) -> str:
    source = candidate["source"]
    paper = candidate["paper"]
    triage = candidate["triage"]
    review = candidate["review"]
    return "\n".join(
        [
            "# Retrieval Candidate Card",
            "",
            "## Candidate Metadata",
            f"- Candidate ID: {candidate['candidate']['candidate_id']}",
            f"- Generated At: {candidate['candidate']['generated_at']}",
            f"- Markdown Path: {candidate['candidate']['markdown_path']}",
            f"- JSON Path: {candidate['candidate']['json_path']}",
            f"- Batch ID: {candidate['candidate'].get('batch_id') or ''}",
            "",
            "## Source Trace",
            f"- Source Kind: {source['kind']}",
            f"- Provider: {source.get('provider') or ''}",
            f"- Providers: {', '.join(source.get('providers') or [])}",
            f"- Collected At: {source['collected_at']}",
            f"- Retrieval Profile ID: {source.get('retrieval_profile_id') or ''}",
            f"- Retrieval Profile Path: {source.get('retrieval_profile_path') or ''}",
            f"- Query Label: {source.get('query_label') or ''}",
            f"- Query Text: {source.get('query_text') or ''}",
            f"- Source Item ID: {source.get('source_item_id') or ''}",
            f"- Source URI: {source.get('source_uri') or ''}",
            f"- Display ID: {paper['identifiers'].get('display') or ''}",
            f"- Raw Text Digest: {source.get('raw_text_digest') or ''}",
            "",
            "## Paper Metadata",
            f"- Title: {paper['title']}",
            f"- Authors: {', '.join(paper['authors'])}",
            f"- Venue / Year: {(paper.get('venue') or '')} / {(paper.get('year') or '')}",
            f"- Primary Category: {paper.get('primary_category') or ''}",
            f"- Categories: {', '.join(paper.get('categories') or [])}",
            f"- Published At: {paper.get('published_at') or ''}",
            f"- Updated At: {paper.get('updated_at') or ''}",
            f"- Comments: {paper.get('comments') or ''}",
            f"- Journal Ref: {paper.get('journal_ref') or ''}",
            f"- DOI: {paper['identifiers'].get('doi') or ''}",
            f"- arXiv ID: {paper['identifiers'].get('arxiv_id') or ''}",
            f"- OpenAlex ID: {paper['identifiers'].get('openalex_id') or ''}",
            f"- Semantic Scholar ID: {paper['identifiers'].get('semantic_scholar_id') or ''}",
            f"- Primary URL: {paper['identifiers'].get('url') or ''}",
            f"- PDF URL: {paper.get('pdf_url') or ''}",
            f"- Additional Source Links: {', '.join(paper.get('source_links') or [])}",
            "",
            "## Abstract",
            f"- Status: `{triage['abstract_status']}`",
            f"- Abstract Source: {paper.get('abstract_source') or ''}",
            f"- Abstract: {paper.get('abstract') or ''}",
            "",
            "## Triager Notes",
            f"- Extraction Confidence: `{triage['extraction_confidence']}`",
            f"- Duplicate Hint: `{triage['duplicate_hint']}`",
            f"- Next Action: `{triage['next_action']}`",
            f"- Matched Interests: {', '.join(triage.get('matched_interest_labels') or [])}",
            f"- Limitations: {'; '.join(triage.get('limitations') or [])}",
            f"- Notes: {'; '.join(triage.get('notes') or [])}",
            "",
            "## Reviewer Working Area",
            f"- Review Status: `{review['review_status']}`",
            f"- Reviewer Summary: {review.get('reviewer_summary') or ''}",
            f"- Zotero Comparison: {review.get('zotero_comparison') or ''}",
            f"- Recommendation: `{review['recommendation']}`",
            f"- Why It Matters: {review.get('why_it_matters') or ''}",
            f"- Quick Takeaways: {'; '.join(review.get('quick_takeaways') or [])}",
            f"- Caveats: {'; '.join(review.get('caveats') or [])}",
        ]
    )


def _build_candidate(
    *,
    item: dict[str, object],
    batch_id: str,
    generated_at: str,
    candidate_root: Path,
    profile_path: Path,
    query_label: str,
    query_text: str,
    write_markdown: bool,
) -> dict[str, object]:
    item_identifier = item.get("arxiv_id") or item.get("id") or item.get("title") or "candidate"
    candidate_id = _slugify(str(item_identifier))
    markdown_path = candidate_root / f"{batch_id}-{candidate_id}.md"
    json_path = candidate_root / f"{batch_id}-{candidate_id}.json"
    source_links: list[str] = []
    for key in ("html_url", "pdf_url"):
        value = item.get(key)
        if isinstance(value, str) and value:
            source_links.append(value)
    for key in ("code_urls", "project_urls", "other_urls"):
        source_links.extend(item.get(key) or [])
    candidate = {
        "schema_version": "1.2.0",
        "candidate": {
            "candidate_id": candidate_id,
            "generated_at": generated_at,
            "markdown_path": markdown_path.as_posix() if write_markdown else None,
            "json_path": json_path.as_posix(),
            "batch_id": batch_id,
        },
        "source": {
            "kind": "literature_query",
            "provider": item.get("provider") or "arxiv",
            "providers": item.get("source_providers") or [item.get("provider") or "arxiv"],
            "collected_at": generated_at,
            "retrieval_profile_id": item.get("profile_id"),
            "retrieval_profile_path": profile_path.as_posix(),
            "query_label": query_label,
            "query_text": query_text,
            "source_item_id": item.get("id"),
            "source_uri": item.get("html_url") or item.get("id"),
            "merged_records": item.get("source_records") or [],
            "subject": None,
            "sender": None,
            "received_at": None,
            "message_id": None,
            "thread_id": None,
            "label_names": [],
            "raw_text_digest": None,
        },
        "paper": {
            "title": item.get("title") or "",
            "authors": item.get("authors") or [],
            "venue": item.get("venue_inferred"),
            "year": _extract_year(item),
            "primary_category": item.get("primary_category"),
            "categories": item.get("categories") or [],
            "published_at": item.get("published"),
            "updated_at": item.get("updated"),
            "comments": item.get("comments"),
            "journal_ref": item.get("journal_ref"),
            "identifiers": {
                "doi": item.get("doi"),
                "arxiv_id": item.get("arxiv_id"),
                "openalex_id": item.get("openalex_id"),
                "semantic_scholar_id": item.get("semantic_scholar_id"),
                "display": display_identifier(item),
                "url": item.get("html_url") or item.get("id"),
            },
            "source_links": list(dict.fromkeys(source_links + list(item.get("source_links") or []))),
            "abstract": item.get("summary"),
            "abstract_source": item.get("abstract_source") or "unknown",
            "pdf_url": item.get("pdf_url"),
        },
        "triage": {
            "extraction_confidence": "high" if item.get("summary") and item.get("title") else "medium",
            "abstract_status": "found" if item.get("summary") else "missing",
            "duplicate_hint": "merged_across_sources" if len(item.get("source_providers") or []) > 1 else "none",
            "next_action": "send_to_reviewer",
            "limitations": [],
            "notes": [],
            "matched_interest_ids": item.get("matched_interest_ids") or [],
            "matched_interest_labels": item.get("matched_interest_labels") or [],
        },
        "review": {
            "review_status": "pending",
            "reviewer_summary": None,
            "zotero_comparison": None,
            "recommendation": "unset",
            "why_it_matters": None,
            "quick_takeaways": [],
            "caveats": [],
            "generation": None,
        },
    }
    if write_markdown:
        markdown_path.write_text(_render_candidate_markdown(candidate), encoding="utf-8")
    json_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
    return candidate


def _collect_items_for_interest(
    *,
    interest: dict[str, object],
    defaults: dict[str, object],
    seen_ids: set[str],
    config: dict[str, object] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    sort_by = str(defaults.get("sort_by") or "lastUpdatedDate")
    sort_order = str(defaults.get("sort_order") or "descending")
    max_results = int(interest.get("max_results") or defaults.get("max_results_per_interest") or 20)
    since_days = int(interest.get("since_days") or defaults.get("since_days") or 7)
    page_size = min(200, max(25, max_results))
    collected: list[dict[str, object]] = []
    query_manifest: list[dict[str, object]] = []
    queries = build_interest_queries(interest, defaults)
    enabled_sources = get_enabled_sources(config)

    for source in enabled_sources:
        provider_query = queries.get(source, "")
        error_message = None
        try:
            items = fetch_items_for_source(
                source,
                provider_query,
                max_results=max_results,
                page_size=page_size,
                since_days=since_days,
                sort_by=sort_by,
                sort_order=sort_order,
                config=config,
            )
        except Exception as exc:
            items = []
            error_message = str(exc)
        query_manifest.append(
            {
                "provider": source,
                "provider_label": source.replace("_", " ").title(),
                "query_text": provider_query,
                "fetched_items": len(items),
                "error": error_message,
            }
        )
        for item in items:
            item_key = canonical_paper_key(item)
            if item_key in seen_ids:
                continue
            collected.append(item)
    return collected, query_manifest


def run_pipeline(
    *,
    config_path: Path,
    profile_path: Path | None = None,
    write_candidate_markdown_override: bool | None = None,
) -> dict[str, object]:
    config = _load_config(config_path)
    resolved_profile_path = profile_path or Path(str(config["profile_path"]))
    profile = normalize_profile_payload(_load_json(resolved_profile_path))
    defaults = dict(profile.get("retrieval_defaults") or {})
    state_path = Path(str(defaults.get("state_path") or ".state/arxiv_profile_seen.json"))
    seen_ids = _load_seen_ids(state_path)
    output_root = Path(str(config.get("output_root") or "reports/generated"))
    artifacts_config = dict(config.get("artifacts") or {})
    write_candidate_markdown = (
        bool(artifacts_config.get("write_candidate_markdown", True))
        if write_candidate_markdown_override is None
        else write_candidate_markdown_override
    )
    batch_id = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
    year = datetime.now(UTC).strftime("%Y")
    month = datetime.now(UTC).strftime("%m")
    retrieval_root = output_root / "retrieval"
    candidate_root = retrieval_root / "candidates" / year / month
    digest_root = retrieval_root / "batches" / year / month
    _ensure_directory(candidate_root)
    _ensure_directory(digest_root)
    generated_at = datetime.now(UTC).isoformat()

    unique_items: dict[str, dict[str, object]] = {}
    query_manifest: list[dict[str, object]] = []
    for interest in profile.get("interests") or []:
        if not interest.get("enabled", True):
            continue
        items, provider_queries = _collect_items_for_interest(
            interest=interest,
            defaults=defaults,
            seen_ids=seen_ids,
            config=config,
        )
        interest_id = str(interest.get("interest_id") or interest.get("id") or interest.get("label") or "interest")
        interest_label = str(interest.get("label") or interest_id)
        for provider_query in provider_queries:
            query_manifest.append(
                {
                    "interest_id": interest_id,
                    "label": interest_label,
                    "provider": provider_query["provider"],
                    "provider_label": provider_query["provider_label"],
                    "query_text": provider_query["query_text"],
                    "fetched_items": provider_query["fetched_items"],
                    "error": provider_query.get("error"),
                }
            )
        for item in items:
            item_key = canonical_paper_key(item)
            if not item_key:
                continue
            existing = unique_items.get(item_key)
            if existing is None:
                item["profile_id"] = profile.get("profile_id")
                item["matched_interest_ids"] = [interest_id]
                item["matched_interest_labels"] = [interest_label]
                unique_items[item_key] = item
            else:
                existing = merge_source_items(existing, item)
                existing_ids = list(existing.get("matched_interest_ids") or [])
                existing_labels = list(existing.get("matched_interest_labels") or [])
                if interest_id not in existing_ids:
                    existing_ids.append(interest_id)
                if interest_label not in existing_labels:
                    existing_labels.append(interest_label)
                existing["matched_interest_ids"] = existing_ids
                existing["matched_interest_labels"] = existing_labels
                unique_items[item_key] = existing

    candidates: list[dict[str, object]] = []
    for item_key, item in unique_items.items():
        candidate = _build_candidate(
            item=item,
            batch_id=batch_id,
            generated_at=generated_at,
            candidate_root=candidate_root,
            profile_path=resolved_profile_path,
            query_label=", ".join(item.get("matched_interest_labels") or []),
            query_text=" | ".join(
                f"{query.get('provider_label')}: {query['query_text']}"
                for query in query_manifest
                if query["interest_id"] in set(item.get("matched_interest_ids") or [])
            ),
            write_markdown=write_candidate_markdown,
        )
        candidates.append(candidate)
        seen_ids.add(item_key)

    digest_markdown_path = digest_root / f"{batch_id}.md"
    digest_json_path = digest_root / f"{batch_id}.json"
    digest_markdown = [
        "# Literature Retrieval Digest",
        "",
        "## Run Metadata",
        f"- Run ID: {batch_id}",
        f"- Generated At: {generated_at}",
        f"- Profile ID: {profile.get('profile_id') or ''}",
        f"- Profile Name: {profile.get('profile_name') or ''}",
        f"- Candidate Count: {len(candidates)}",
        "",
        "## Queries",
    ]
    for query in query_manifest:
        digest_markdown.extend(
            [
                f"- `{query['label']}`",
                f"  - Provider: `{query.get('provider_label') or query.get('provider') or ''}`",
                f"  - Interest ID: `{query['interest_id']}`",
                f"  - Query: `{query['query_text']}`",
                f"  - Retrieved: `{query['fetched_items']}`",
            ]
        )
    digest_markdown.extend(["", "## Candidates"])
    for candidate in candidates:
        paper = candidate["paper"]
        triage = candidate["triage"]
        digest_markdown.extend(
            [
                f"### {paper['title']}",
                f"- Authors: {', '.join(paper['authors'])}",
                f"- Provider: {candidate.get('source', {}).get('provider') or ''}",
                f"- Identifier: {paper['identifiers'].get('display') or ''}",
                f"- URL: {paper['identifiers'].get('url') or ''}",
                f"- Matched Interests: {', '.join(triage.get('matched_interest_labels') or [])}",
                f"- Candidate JSON: {candidate['candidate']['json_path']}",
                "",
            ]
        )
    digest_markdown_path.write_text("\n".join(digest_markdown), encoding="utf-8")

    digest_payload = {
        "schema_version": "1.0.0",
        "run_id": batch_id,
        "generated_at": generated_at,
        "workflow": "retrieval",
        "profile_id": profile.get("profile_id"),
        "profile_name": profile.get("profile_name"),
        "profile_path": resolved_profile_path.as_posix(),
        "query_manifest": query_manifest,
        "candidate_count": len(candidates),
        "candidate_paths": [candidate["candidate"]["json_path"] for candidate in candidates],
        "candidate_markdown_paths": [
            candidate["candidate"]["markdown_path"]
            for candidate in candidates
            if candidate["candidate"].get("markdown_path")
        ],
        "artifact_policy": {
            "candidate_json_authoritative": True,
            "candidate_markdown_enabled": write_candidate_markdown,
        },
    }
    digest_json_path.write_text(json.dumps(digest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_seen_ids(state_path, seen_ids)
    return {
        "digest_markdown_path": digest_markdown_path.as_posix(),
        "digest_json_path": digest_json_path.as_posix(),
        "candidate_count": len(candidates),
        "query_count": len(query_manifest),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the research-assist literature retrieval pipeline")
    parser.add_argument("--config", required=True, help="Path to the pipeline TOML config")
    parser.add_argument("--profile", default=None, help="Override the research-interest profile JSON path")
    parser.add_argument("--with-candidate-markdown", action="store_true", help="Force candidate Markdown debug artifacts on")
    parser.add_argument("--no-candidate-markdown", action="store_true", help="Force candidate Markdown debug artifacts off")
    args = parser.parse_args()

    if args.with_candidate_markdown and args.no_candidate_markdown:
        raise SystemExit("Cannot use both --with-candidate-markdown and --no-candidate-markdown")

    write_candidate_markdown_override = None
    if args.with_candidate_markdown:
        write_candidate_markdown_override = True
    elif args.no_candidate_markdown:
        write_candidate_markdown_override = False

    result = run_pipeline(
        config_path=Path(args.config),
        profile_path=Path(args.profile) if args.profile else None,
        write_candidate_markdown_override=write_candidate_markdown_override,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

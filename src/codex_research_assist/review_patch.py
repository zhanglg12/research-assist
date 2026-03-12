from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _as_string_list(value: Any, *, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} must be a list of strings")
        result.append(item)
    return result


def validate_review_patch(patch: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, dict):
        raise ValueError("review patch must be an object")

    allowed_patch_keys = {"candidate_id", "review"}
    unknown_patch_keys = set(patch.keys()) - allowed_patch_keys
    if unknown_patch_keys:
        unknown = ", ".join(sorted(unknown_patch_keys))
        raise ValueError(f"review patch contains unsupported top-level keys: {unknown}")

    candidate_id = patch.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError("candidate_id must be a non-empty string")

    review = patch.get("review")
    if not isinstance(review, dict):
        raise ValueError("review must be an object")

    allowed_review_keys = {
        "review_status",
        "reviewer_summary",
        "zotero_comparison",
        "recommendation",
        "why_it_matters",
        "selected_for_digest",
        "quick_takeaways",
        "caveats",
        "generation",
    }
    unknown_review_keys = set(review.keys()) - allowed_review_keys
    if unknown_review_keys:
        unknown = ", ".join(sorted(unknown_review_keys))
        raise ValueError(f"review patch contains unsupported review keys: {unknown}")

    review_status = review.get("review_status")
    if review_status not in {"system_generated", "agent_completed"}:
        raise ValueError("review.review_status must be system_generated or agent_completed")

    recommendation = review.get("recommendation")
    allowed_recommendations = {
        "read_first",
        "skim",
        "watch",
        "skip_for_now",
        "archive",
        "watchlist",
        "ignore",
        "unset",
    }
    if recommendation not in allowed_recommendations:
        raise ValueError("review.recommendation has an unsupported value")

    reviewer_summary = review.get("reviewer_summary")
    if reviewer_summary is not None and not isinstance(reviewer_summary, str):
        raise ValueError("review.reviewer_summary must be a string or null")

    why_it_matters = review.get("why_it_matters")
    if why_it_matters is not None and not isinstance(why_it_matters, str):
        raise ValueError("review.why_it_matters must be a string or null")

    selected_for_digest = review.get("selected_for_digest")
    if selected_for_digest is not None and not isinstance(selected_for_digest, bool):
        raise ValueError("review.selected_for_digest must be a boolean or null")

    quick_takeaways = _as_string_list(review.get("quick_takeaways", []), field_name="review.quick_takeaways")
    caveats = _as_string_list(review.get("caveats", []), field_name="review.caveats")

    zotero_comparison = review.get("zotero_comparison")
    if zotero_comparison is not None:
        if not isinstance(zotero_comparison, dict):
            raise ValueError("review.zotero_comparison must be an object or null")
        status = zotero_comparison.get("status")
        if status not in {"not_run", "not_found", "matched", "uncertain"}:
            raise ValueError("review.zotero_comparison.status has an unsupported value")
        summary = zotero_comparison.get("summary")
        if not isinstance(summary, str):
            raise ValueError("review.zotero_comparison.summary must be a string")
        related_items = zotero_comparison.get("related_items")
        if not isinstance(related_items, list):
            raise ValueError("review.zotero_comparison.related_items must be a list")

    generation = review.get("generation")
    if generation is not None:
        if not isinstance(generation, dict):
            raise ValueError("review.generation must be an object or null")
        mode = generation.get("mode")
        if mode not in {"system_profile_only", "agent_zotero_fill"}:
            raise ValueError("review.generation.mode has an unsupported value")
        _as_string_list(generation.get("sources", []), field_name="review.generation.sources")

    return {
        "candidate_id": candidate_id,
        "review": {
            "review_status": review_status,
            "reviewer_summary": reviewer_summary,
            "zotero_comparison": zotero_comparison,
            "recommendation": recommendation,
            "why_it_matters": why_it_matters,
            "selected_for_digest": selected_for_digest,
            "quick_takeaways": quick_takeaways,
            "caveats": caveats,
            "generation": generation,
        },
    }


def merge_review_patch(candidate: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    normalized_patch = validate_review_patch(patch)
    candidate_block = candidate.get("candidate", {})
    candidate_id = candidate_block.get("candidate_id")
    if candidate_id != normalized_patch["candidate_id"]:
        raise ValueError(
            f"candidate_id mismatch: candidate JSON has {candidate_id!r}, patch has {normalized_patch['candidate_id']!r}"
        )

    merged = json.loads(json.dumps(candidate))
    review = merged.get("review")
    if not isinstance(review, dict):
        review = {}
    review.update(normalized_patch["review"])
    merged["review"] = review
    return merged


def apply_review_patch(candidate_path: str | Path, patch_path: str | Path) -> Path:
    candidate_file = Path(candidate_path).expanduser().resolve()
    patch_file = Path(patch_path).expanduser().resolve()
    candidate = json.loads(candidate_file.read_text(encoding="utf-8"))
    patch = json.loads(patch_file.read_text(encoding="utf-8"))
    merged = merge_review_patch(candidate, patch)
    candidate_file.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return candidate_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply a review patch to one candidate JSON artifact")
    parser.add_argument("--candidate", required=True, help="Path to candidate JSON")
    parser.add_argument("--patch", required=True, help="Path to review patch JSON")
    args = parser.parse_args()

    target = apply_review_patch(args.candidate, args.patch)
    print(target.as_posix())


if __name__ == "__main__":
    main()

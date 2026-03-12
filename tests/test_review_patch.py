from __future__ import annotations

import unittest

from codex_research_assist.review_patch import merge_review_patch, validate_review_patch


class ReviewPatchTest(unittest.TestCase):
    def test_validate_review_patch_accepts_agent_completed(self) -> None:
        patch = {
            "candidate_id": "cand-1",
            "review": {
                "review_status": "agent_completed",
                "reviewer_summary": "Short synthesis.",
                "zotero_comparison": {
                    "status": "matched",
                    "summary": "Found one related Zotero item.",
                    "related_items": [
                        {"title": "Related paper", "item_key": "ABCD1234", "relation": "similar method"}
                    ],
                },
                "recommendation": "read_first",
                "why_it_matters": "Strong fit to the active profile.",
                "selected_for_digest": True,
                "quick_takeaways": ["Matches PINN interest", "Recent and novel"],
                "caveats": ["Abstract-first review only."],
                "generation": {
                    "mode": "agent_zotero_fill",
                    "sources": ["profile", "candidate", "zotero_search_items"],
                },
            },
        }
        normalized = validate_review_patch(patch)
        self.assertEqual(normalized["review"]["review_status"], "agent_completed")
        self.assertTrue(normalized["review"]["selected_for_digest"])

    def test_merge_review_patch_updates_candidate_review(self) -> None:
        candidate = {
            "candidate": {"candidate_id": "cand-1"},
            "paper": {"title": "Original title", "abstract": "Original abstract"},
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
        patch = {
            "candidate_id": "cand-1",
            "review": {
                "review_status": "agent_completed",
                "reviewer_summary": "Short synthesis.",
                "zotero_comparison": {
                    "status": "not_found",
                    "summary": "No close Zotero match found.",
                    "related_items": [],
                },
                "recommendation": "watch",
                "why_it_matters": "Useful adjacent paper.",
                "selected_for_digest": False,
                "quick_takeaways": ["Adjacent to current profile"],
                "caveats": ["Evidence is abstract-only."],
                "generation": {
                    "mode": "agent_zotero_fill",
                    "sources": ["profile", "candidate"],
                },
            },
        }
        merged = merge_review_patch(candidate, patch)
        self.assertEqual(merged["review"]["review_status"], "agent_completed")
        self.assertEqual(merged["review"]["recommendation"], "watch")
        self.assertFalse(merged["review"]["selected_for_digest"])
        self.assertEqual(merged["paper"]["title"], "Original title")
        self.assertEqual(merged["paper"]["abstract"], "Original abstract")

    def test_validate_review_patch_rejects_top_level_non_review_fields(self) -> None:
        patch = {
            "candidate_id": "cand-1",
            "paper": {"abstract": "tampered"},
            "review": {
                "review_status": "agent_completed",
                "reviewer_summary": "Short synthesis.",
                "zotero_comparison": {
                    "status": "not_found",
                    "summary": "No close Zotero match found.",
                    "related_items": [],
                },
                "recommendation": "watch",
                "why_it_matters": "Useful adjacent paper.",
                "selected_for_digest": False,
                "quick_takeaways": ["Adjacent to current profile"],
                "caveats": ["Evidence is abstract-only."],
                "generation": {
                    "mode": "agent_zotero_fill",
                    "sources": ["profile", "candidate"],
                },
            },
        }
        with self.assertRaisesRegex(ValueError, "unsupported top-level keys"):
            validate_review_patch(patch)

    def test_validate_review_patch_rejects_unknown_review_fields(self) -> None:
        patch = {
            "candidate_id": "cand-1",
            "review": {
                "review_status": "agent_completed",
                "reviewer_summary": "Short synthesis.",
                "zotero_comparison": {
                    "status": "not_found",
                    "summary": "No close Zotero match found.",
                    "related_items": [],
                },
                "recommendation": "watch",
                "why_it_matters": "Useful adjacent paper.",
                "selected_for_digest": False,
                "quick_takeaways": ["Adjacent to current profile"],
                "caveats": ["Evidence is abstract-only."],
                "generation": {
                    "mode": "agent_zotero_fill",
                    "sources": ["profile", "candidate"],
                },
                "paper_abstract": "tampered",
            },
        }
        with self.assertRaisesRegex(ValueError, "unsupported review keys"):
            validate_review_patch(patch)


if __name__ == "__main__":
    unittest.main()

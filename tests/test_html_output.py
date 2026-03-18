from __future__ import annotations

import unittest

from codex_research_assist.html_fmt import format_digest_html, format_search_html


def _digest_candidate(
    title: str = "Test Paper",
    abstract: str = "Test abstract.",
    recommendation: str = "read_first",
    total: float = 0.8,
    map_match: float = 0.7,
    zotero_semantic: float = 0.6,
    why: str = "Matches profile.",
    interests: list[str] | None = None,
) -> dict:
    return {
        "paper": {
            "title": title,
            "abstract": abstract,
            "authors": ["Alice", "Bob", "Charlie"],
            "identifiers": {"arxiv_id": "2501.12345", "url": "https://arxiv.org/abs/2501.12345"},
        },
        "triage": {"matched_interest_labels": interests or ["PINN"]},
        "_scores": {
            "total": total,
            "map_match": map_match,
            "zotero_semantic": zotero_semantic,
            "semantic_top_title": "Nearest Zotero Paper",
            "semantic_top_item_key": "KEY123",
            "semantic_best_distance": 0.4,
            "semantic_neighbor_count": 2,
            "semantic_neighbors": [
                {"item_key": "KEY123", "title": "Nearest Zotero Paper", "collections": "ML", "distance": 0.4},
            ],
        },
        "review": {
            "recommendation": recommendation,
            "why_it_matters": why,
            "reviewer_summary": "Short synthesis of the paper.",
            "zotero_comparison": {
                "status": "matched",
                "summary": "Close to existing papers.",
                "related_items": [],
            },
            "quick_takeaways": ["Takeaway 1", "Takeaway 2"],
            "caveats": ["Abstract-only review."],
        },
    }


class DigestHtmlStructureTest(unittest.TestCase):
    def test_single_candidate_renders(self) -> None:
        html = format_digest_html([_digest_candidate()], "2026-03-13")
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Test Paper", html)
        self.assertIn("Research Digest", html)

    def test_featured_card_class(self) -> None:
        html = format_digest_html([_digest_candidate(), _digest_candidate(title="Second Paper")], "2026-03-13")
        self.assertIn("featured", html)
        self.assertIn("Second Paper", html)

    def test_scores_displayed(self) -> None:
        html = format_digest_html([_digest_candidate(total=0.85, map_match=0.72, zotero_semantic=0.61)], "2026-03-13")
        self.assertIn("0.85", html)
        self.assertIn("0.72", html)
        self.assertIn("0.61", html)

    def test_recommendation_chips(self) -> None:
        for rec in ["read_first", "skim", "watch", "skip_for_now"]:
            html = format_digest_html([_digest_candidate(recommendation=rec)], "2026-03-13")
            self.assertIn(rec.replace("_", "-"), html)

    def test_review_sections_present(self) -> None:
        html = format_digest_html([_digest_candidate()], "2026-03-13")
        self.assertIn("Paper summary", html)
        self.assertIn("Quick takeaways", html)
        self.assertIn("Caveats", html)
        self.assertIn("Nearest Zotero", html)

    def test_neighbor_list_rendered(self) -> None:
        html = format_digest_html([_digest_candidate()], "2026-03-13")
        self.assertIn("Nearest Zotero Paper", html)

    def test_abstract_in_details_block(self) -> None:
        html = format_digest_html([_digest_candidate(abstract="Detailed abstract content here.")], "2026-03-13")
        self.assertIn("Original abstract", html)
        self.assertIn("Detailed abstract content here.", html)

    def test_empty_candidates_renders(self) -> None:
        html = format_digest_html([], "2026-03-13")
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("0 selected", html)

    def test_overview_band_counts(self) -> None:
        candidates = [
            _digest_candidate(recommendation="read_first"),
            _digest_candidate(title="Paper 2", recommendation="skim"),
            _digest_candidate(title="Paper 3", recommendation="read_first", interests=["MARL"]),
        ]
        html = format_digest_html(candidates, "2026-03-13")
        self.assertIn("3", html)  # 3 selected

    def test_author_truncation(self) -> None:
        html = format_digest_html([_digest_candidate()], "2026-03-13")
        self.assertIn("Alice et al.", html)

    def test_date_display(self) -> None:
        html = format_digest_html([_digest_candidate()], "2026-03-13")
        self.assertIn("03/13", html)


class SearchHtmlTest(unittest.TestCase):
    def test_search_html_renders(self) -> None:
        papers = [
            {
                "title": "Search Hit",
                "authors": ["Eve"],
                "summary": "Some summary.",
                "html_url": "https://arxiv.org/abs/1234",
                "arxiv_id": "1234",
                "provider": "arxiv",
                "paper_id_display": "arXiv 1234",
            },
        ]
        html = format_search_html(papers, "test query")
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Search Hit", html)
        self.assertIn("test query", html)

    def test_search_empty_results(self) -> None:
        html = format_search_html([], "empty query")
        self.assertIn("0 papers", html)


class HtmlEdgeCasesTest(unittest.TestCase):
    def test_xss_prevention_in_title(self) -> None:
        candidate = _digest_candidate(title='<script>alert("xss")</script>')
        html = format_digest_html([candidate], "2026-03-13")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_missing_review_fields(self) -> None:
        candidate = _digest_candidate()
        candidate["review"] = {"recommendation": "unset"}
        html = format_digest_html([candidate], "2026-03-13")
        self.assertIn("<!DOCTYPE html>", html)

    def test_missing_scores(self) -> None:
        candidate = _digest_candidate()
        candidate["_scores"] = {}
        html = format_digest_html([candidate], "2026-03-13")
        self.assertIn("<!DOCTYPE html>", html)


if __name__ == "__main__":
    unittest.main()

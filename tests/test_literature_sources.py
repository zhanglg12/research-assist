from __future__ import annotations

import unittest
from unittest.mock import patch

from codex_research_assist.arxiv_profile_pipeline.literature_sources import (
    build_interest_queries,
    canonical_paper_key,
    get_enabled_sources,
    merge_source_items,
)
from codex_research_assist.arxiv_profile_pipeline.pipeline import _collect_items_for_interest


class LiteratureSourceConfigTest(unittest.TestCase):
    def test_default_sources_fall_back_to_arxiv(self) -> None:
        self.assertEqual(get_enabled_sources({}), ["arxiv"])

    def test_enabled_sources_normalize_aliases(self) -> None:
        config = {"literature_sources": {"enabled": ["arxiv", "OpenAlex", "semantic-scholar", "s2"]}}
        self.assertEqual(get_enabled_sources(config), ["arxiv", "openalex", "semantic_scholar"])


class LiteratureDedupTest(unittest.TestCase):
    def test_canonical_key_prefers_doi_then_arxiv_then_title(self) -> None:
        self.assertEqual(canonical_paper_key({"doi": "https://doi.org/10.1000/Test"}), "doi:10.1000/test")
        self.assertEqual(canonical_paper_key({"arxiv_id": "arXiv:2501.12345"}), "arxiv:2501.12345")
        self.assertEqual(
            canonical_paper_key({"title": "A Test Paper", "year": 2025}),
            "title:a test paper:2025",
        )

    def test_merge_source_items_unions_providers_and_links(self) -> None:
        first = {
            "provider": "arxiv",
            "source_providers": ["arxiv"],
            "provider_ids": {"arxiv": "2501.12345"},
            "source_records": [{"provider": "arxiv", "id": "2501.12345"}],
            "title": "Shared Title",
            "authors": ["Alice"],
            "summary": "short",
            "source_links": ["https://arxiv.org/abs/2501.12345"],
            "arxiv_id": "2501.12345",
            "doi": None,
        }
        second = {
            "provider": "openalex",
            "source_providers": ["openalex"],
            "provider_ids": {"openalex": "https://openalex.org/W123"},
            "source_records": [{"provider": "openalex", "id": "https://openalex.org/W123"}],
            "title": "Shared Title",
            "authors": ["Alice", "Bob"],
            "summary": "longer abstract",
            "source_links": ["https://openalex.org/W123"],
            "arxiv_id": None,
            "doi": "10.1000/test",
        }

        merged = merge_source_items(first, second)
        self.assertEqual(merged["source_providers"], ["arxiv", "openalex"])
        self.assertEqual(merged["doi"], "10.1000/test")
        self.assertIn("https://openalex.org/W123", merged["source_links"])
        self.assertEqual(merged["summary"], "longer abstract")


class InterestCollectionTest(unittest.TestCase):
    def test_interest_queries_keep_arxiv_and_plain_text_variants(self) -> None:
        interest = {
            "label": "Bilevel + PINN",
            "categories": ["cs.LG", "math.NA"],
            "method_keywords": ["Bilevel", "PINN"],
            "query_aliases": ["bilevel optimization", "physics-informed neural network"],
        }
        defaults = {"logic": "AND"}
        queries = build_interest_queries(interest, defaults)
        self.assertIn("ti:Bilevel", queries["arxiv"])
        self.assertIn('"bilevel optimization"', queries["openalex"])
        self.assertIn('"physics-informed neural network"', queries["semantic_scholar"])

    def test_collect_items_for_interest_collects_all_enabled_sources(self) -> None:
        interest = {
            "interest_id": "pinn",
            "label": "PINN",
            "enabled": True,
            "categories": ["cs.LG"],
            "method_keywords": ["PINN"],
            "query_aliases": ["physics-informed neural network"],
        }
        defaults = {
            "logic": "AND",
            "sort_by": "lastUpdatedDate",
            "sort_order": "descending",
            "max_results_per_interest": 5,
            "since_days": 7,
        }
        config = {"literature_sources": {"enabled": ["arxiv", "openalex"]}}

        arxiv_item = {
            "id": "https://arxiv.org/abs/2501.12345",
            "provider": "arxiv",
            "title": "Shared Paper",
            "authors": ["Alice"],
            "summary": "short summary",
            "arxiv_id": "2501.12345",
            "doi": "10.1000/test",
            "source_providers": ["arxiv"],
            "provider_ids": {"arxiv": "2501.12345"},
            "source_records": [{"provider": "arxiv", "id": "2501.12345"}],
        }
        openalex_item = {
            "id": "https://openalex.org/W123",
            "provider": "openalex",
            "title": "Shared Paper",
            "authors": ["Alice", "Bob"],
            "summary": "longer summary",
            "arxiv_id": None,
            "doi": "10.1000/test",
            "source_providers": ["openalex"],
            "provider_ids": {"openalex": "https://openalex.org/W123"},
            "source_records": [{"provider": "openalex", "id": "https://openalex.org/W123"}],
        }

        def _fake_fetch(source, query_text, **kwargs):
            del query_text, kwargs
            if source == "arxiv":
                return [dict(arxiv_item)]
            if source == "openalex":
                return [dict(openalex_item)]
            return []

        with patch("codex_research_assist.arxiv_profile_pipeline.pipeline.fetch_items_for_source", side_effect=_fake_fetch):
            items, manifest = _collect_items_for_interest(
                interest=interest,
                defaults=defaults,
                seen_ids=set(),
                config=config,
            )

        self.assertEqual(len(items), 2)
        self.assertEqual(len(manifest), 2)

    def test_collect_items_for_interest_degrades_when_one_source_fails(self) -> None:
        interest = {
            "interest_id": "pinn",
            "label": "PINN",
            "enabled": True,
            "categories": ["cs.LG"],
            "method_keywords": ["PINN"],
            "query_aliases": ["physics-informed neural network"],
        }
        defaults = {
            "logic": "AND",
            "sort_by": "lastUpdatedDate",
            "sort_order": "descending",
            "max_results_per_interest": 5,
            "since_days": 7,
        }
        config = {"literature_sources": {"enabled": ["arxiv", "semantic_scholar"]}}

        def _fake_fetch(source, query_text, **kwargs):
            del query_text, kwargs
            if source == "semantic_scholar":
                raise RuntimeError("HTTP 429")
            return [{"id": "https://arxiv.org/abs/2501.12345", "provider": "arxiv", "title": "Safe Paper", "source_providers": ["arxiv"]}]

        with patch("codex_research_assist.arxiv_profile_pipeline.pipeline.fetch_items_for_source", side_effect=_fake_fetch):
            items, manifest = _collect_items_for_interest(
                interest=interest,
                defaults=defaults,
                seen_ids=set(),
                config=config,
            )

        self.assertEqual(len(items), 1)
        self.assertEqual(len(manifest), 2)
        self.assertEqual(manifest[1]["error"], "HTTP 429")


if __name__ == "__main__":
    unittest.main()

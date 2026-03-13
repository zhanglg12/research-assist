from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from codex_research_assist.arxiv_profile_pipeline.profile_contract import normalize_profile_payload
from codex_research_assist.profile_refresh_output import parse_profile_refresh_output
from codex_research_assist.zotero_mcp.chroma_client import ChromaClient
from codex_research_assist.zotero_mcp.feedback import (
    build_feedback_note,
    decision_status_tag,
    normalize_feedback_payload,
)
from codex_research_assist.zotero_mcp.profile_evidence import build_profile_evidence_summary
from codex_research_assist.zotero_mcp.server import mcp


class ProfileContractTest(unittest.TestCase):
    def test_normalize_profile_payload_keeps_contract(self) -> None:
        payload = {
            "profile_id": "demo",
            "profile_name": "Demo",
            "maintainer": "someone-else",
            "zotero_basis": {"collections": ["A"], "tags": ["t"]},
            "retrieval_defaults": {"since_days": 7, "max_results_per_interest": 8, "max_pages": 4},
            "interests": [
                {
                    "interest_id": "i1",
                    "label": "PINN",
                    "enabled": True,
                    "categories": ["cs.LG"],
                    "method_keywords": ["PINN", "PINN"],
                    "query_aliases": ["physics-informed neural network", "physics-informed neural network"],
                    "exclude_keywords": [],
                    "logic": "and",
                    "notes": "",
                }
            ],
        }
        normalized = normalize_profile_payload(payload)
        self.assertEqual(normalized["maintainer"], "someone-else")
        self.assertEqual(normalized["interests"][0]["method_keywords"], ["PINN"])
        self.assertEqual(
            normalized["interests"][0]["query_aliases"],
            ["physics-informed neural network"],
        )


class FeedbackPayloadTest(unittest.TestCase):
    def test_normalize_feedback_payload(self) -> None:
        payload = {
            "source": "candidate-review",
            "decisions": [
                {
                    "match": {"doi": "10.1000/ABC"},
                    "decision": "archive",
                    "rationale": "high fit",
                    "add_tags": ["survey", "survey"],
                    "remove_tags": ["old"],
                    "add_collections": ["Queue"],
                    "remove_collections": [],
                    "note_append": "promote to archive",
                }
            ],
        }
        normalized = normalize_feedback_payload(payload)
        self.assertEqual(normalized["decisions"][0]["match"]["doi"], "10.1000/abc")
        self.assertEqual(normalized["decisions"][0]["add_tags"], ["survey"])
        self.assertEqual(decision_status_tag("archive"), "ra-status:archive")
        note = build_feedback_note(normalized["decisions"][0], generated_at="2026-03-11T00:00:00+00:00", source="candidate-review")
        self.assertIn("decision: archive", note)
        self.assertIn("add_tags: survey", note)


class EvidenceSummaryTest(unittest.TestCase):
    def test_build_profile_evidence_summary(self) -> None:
        items = [
            {
                "title": "Physics informed neural network for PINN PDE",
                "tags": ["PINN", "pde"],
                "publication_title": "arXiv",
                "year": "2026",
            },
            {
                "title": "Bilevel optimization with PINN constraints",
                "tags": ["PINN", "bilevel"],
                "publication_title": "NeurIPS",
                "year": "2025",
            },
        ]
        summary = build_profile_evidence_summary(
            items,
            collections=["Current Survey"],
            tags=["PINN"],
            applied_limit=20,
        )
        top_tags = [entry["value"] for entry in summary["summary"]["top_tags"]]
        self.assertIn("PINN", top_tags)
        top_terms = [entry["value"] for entry in summary["summary"]["top_title_terms"]]
        self.assertIn("pinn", top_terms)


class McpRegistrationTest(unittest.TestCase):
    def test_expected_tools_are_registered(self) -> None:
        async def _run() -> set[str]:
            tools = await mcp.list_tools()
            return {tool.name for tool in tools}

        tool_names = asyncio.run(_run())
        self.assertTrue(
            {
                "zotero_status",
                "zotero_list_collections",
                "zotero_get_tags",
                "zotero_profile_evidence",
                "zotero_write_profile",
                "zotero_apply_feedback",
                "zotero_save_papers",
                "zotero_search_items",
                "zotero_batch_update_tags",
                "zotero_create_collection",
                "zotero_update_collection",
                "zotero_move_items_to_collection",
                "zotero_semantic_search",
                "zotero_update_search_database",
                "zotero_get_search_database_status",
            }.issubset(tool_names)
        )


class QwenEmbeddingBackendTest(unittest.TestCase):
    def test_qwen_backend_does_not_require_openai_package_at_init(self) -> None:
        client = ChromaClient.__new__(ChromaClient)
        client.embedding_model = "qwen"
        client.embedding_config = {
            "model_name": "qwen3-embedding:0.6b",
            "base_url": "http://localhost:11434/v1",
            "api_key": "ollama",
        }

        embedding_fn = ChromaClient._create_embedding_function(client)
        self.assertEqual(embedding_fn.name(), "ollama:qwen3-embedding:0.6b:http://localhost:11434/v1")


class ConfigRoundTripTest(unittest.TestCase):
    def test_profile_json_round_trip(self) -> None:
        payload = {
            "profile_id": "demo",
            "profile_name": "Demo",
            "zotero_basis": {"collections": ["A"], "tags": ["pinn"], "notes": ""},
            "retrieval_defaults": {
                "logic": "AND",
                "sort_by": "lastUpdatedDate",
                "sort_order": "descending",
                "since_days": 7,
                "max_results_per_interest": 10,
                "max_pages": 5,
            },
            "interests": [
                {
                    "interest_id": "pinn",
                    "label": "PINN",
                    "enabled": True,
                    "categories": ["cs.LG"],
                    "method_keywords": ["PINN"],
                    "query_aliases": [],
                    "exclude_keywords": [],
                    "logic": "AND",
                    "notes": "",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "profile.json"
            path.write_text(json.dumps(normalize_profile_payload(payload)), encoding="utf-8")
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["profile_id"], "demo")


class ProfileRefreshOutputTest(unittest.TestCase):
    def test_parse_profile_refresh_output_accepts_plain_json_only(self) -> None:
        raw_text = json.dumps(
            {
                "profile_id": "demo",
                "profile_name": "Demo",
                "zotero_basis": {"collections": ["A"], "tags": ["pinn"], "notes": ""},
                "retrieval_defaults": {
                    "logic": "AND",
                    "sort_by": "lastUpdatedDate",
                    "sort_order": "descending",
                    "since_days": 7,
                    "max_results_per_interest": 10,
                    "max_pages": 5,
                },
                "interests": [
                    {
                        "interest_id": "pinn",
                        "label": "PINN",
                        "enabled": True,
                        "categories": ["cs.LG"],
                        "method_keywords": ["PINN"],
                        "query_aliases": ["physics-informed neural network"],
                        "exclude_keywords": [],
                        "logic": "AND",
                        "notes": "",
                    }
                ],
            },
            ensure_ascii=False,
        )
        parsed = parse_profile_refresh_output(raw_text)
        self.assertEqual(parsed["profile_id"], "demo")
        self.assertEqual(parsed["interests"][0]["label"], "PINN")

    def test_parse_profile_refresh_output_rejects_wrapped_prose(self) -> None:
        raw_text = """Here is the JSON you requested:
{"profile_id":"demo","profile_name":"Demo","zotero_basis":{"collections":["A"],"tags":[],"notes":""},"retrieval_defaults":{"logic":"AND","sort_by":"lastUpdatedDate","sort_order":"descending","since_days":7,"max_results_per_interest":10,"max_pages":5},"interests":[{"interest_id":"pinn","label":"PINN","enabled":true,"categories":["cs.LG"],"method_keywords":["PINN"],"query_aliases":[],"exclude_keywords":[],"logic":"AND","notes":""}]}"""
        with self.assertRaisesRegex(ValueError, "must start with"):
            parse_profile_refresh_output(raw_text)

    def test_parse_profile_refresh_output_rejects_code_fences(self) -> None:
        raw_text = """```json
{"profile_id":"demo","profile_name":"Demo","zotero_basis":{"collections":["A"],"tags":[],"notes":""},"retrieval_defaults":{"logic":"AND","sort_by":"lastUpdatedDate","sort_order":"descending","since_days":7,"max_results_per_interest":10,"max_pages":5},"interests":[{"interest_id":"pinn","label":"PINN","enabled":true,"categories":["cs.LG"],"method_keywords":["PINN"],"query_aliases":[],"exclude_keywords":[],"logic":"AND","notes":""}]}
```"""
        with self.assertRaisesRegex(ValueError, "code fences"):
            parse_profile_refresh_output(raw_text)


if __name__ == "__main__":
    unittest.main()

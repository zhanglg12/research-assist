from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from codex_research_assist.openclaw_runner import action_digest
from codex_research_assist.zotero_mcp.chroma_client import OllamaEmbeddingFunction, create_chroma_client


class OllamaEmbeddingBackendTest(unittest.TestCase):
    def test_ollama_embedding_function_uses_openai_compatible_http_api(self) -> None:
        response = Mock()
        response.json.return_value = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
        response.raise_for_status.return_value = None

        with patch("codex_research_assist.zotero_mcp.chroma_client.requests.post", return_value=response) as post:
            fn = OllamaEmbeddingFunction(
                model_name="qwen3-embedding:0.6b",
                api_key="ollama",
                base_url="http://localhost:11434/v1",
            )
            embeddings = fn(["title and abstract"])

        self.assertEqual([list(item) for item in embeddings], [[0.1, 0.2, 0.3]])
        post.assert_called_once_with(
            "http://localhost:11434/v1/embeddings",
            json={"model": "qwen3-embedding:0.6b", "input": ["title and abstract"]},
            headers={"Content-Type": "application/json", "Authorization": "Bearer ollama"},
            timeout=120,
        )

    def test_create_chroma_client_uses_ollama_backend_for_qwen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "profile_path": str(root / "profiles" / "research-interest.json"),
                        "output_root": str(root / "reports"),
                        "semantic_search": {
                            "enabled": True,
                            "zotero_db_path": str(root / "zotero.sqlite"),
                            "persist_directory": str(root / ".semantic-search"),
                            "collection_name": "research_assist_zotero",
                            "embedding_model": "qwen",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (root / "zotero.sqlite").write_text("", encoding="utf-8")

            client = create_chroma_client(config_path)

        self.assertIsInstance(client.embedding_function, OllamaEmbeddingFunction)


class SemanticToggleTest(unittest.TestCase):
    def test_action_digest_skips_semantic_search_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            profile_path = root / "profiles" / "research-interest.json"
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            profile_path.write_text(
                json.dumps({"interests": [], "retrieval_defaults": {"state_path": str(root / "seen.json")}}),
                encoding="utf-8",
            )
            digest_json_path = root / "digest.json"
            digest_json_path.write_text(json.dumps({"candidate_paths": []}), encoding="utf-8")
            config_path = root / "config.json"
            config_path.write_text(json.dumps({"semantic_search": {"enabled": False}}), encoding="utf-8")

            config = {
                "profile_path": str(profile_path),
                "output_root": str(root / "reports"),
                "review_generation": {"fallback_to_system": False},
                "semantic_search": {"enabled": False},
            }
            candidate = {"candidate": {"candidate_id": "cand-1", "json_path": str(root / "cand-1.json")}}

            def _rank(candidates, profile, history_ids, semantic_search_fn=None):
                self.assertIsNone(semantic_search_fn)
                return candidates

            with patch("codex_research_assist.openclaw_runner.evaluate_profile_refresh_policy", return_value={"controller": {"profile_refresh": {"required": False}}}), \
                 patch("codex_research_assist.openclaw_runner.run_pipeline", return_value={"digest_json_path": str(digest_json_path), "candidate_count": 1}), \
                 patch("codex_research_assist.openclaw_runner._load_candidates_from_digest", return_value=[candidate]), \
                 patch("codex_research_assist.openclaw_runner.rank_candidates", side_effect=_rank), \
                 patch("codex_research_assist.openclaw_runner.enrich_candidates_with_system_review", side_effect=AssertionError("system review should stay disabled")), \
                 patch("codex_research_assist.openclaw_runner._persist_ranked_candidate_paths"), \
                 patch("codex_research_assist.openclaw_runner._render_digest_outputs", return_value="ok"), \
                 patch("codex_research_assist.openclaw_runner.create_semantic_search", side_effect=AssertionError("semantic search should not be initialized")):
                result = action_digest(config, config_path=config_path)

        self.assertEqual(result, "ok")


if __name__ == "__main__":
    unittest.main()

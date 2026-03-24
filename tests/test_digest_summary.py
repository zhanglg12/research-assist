from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from codex_research_assist.digest_summary import summary_output_path, write_digest_run_summary
from codex_research_assist.openclaw_runner import _format_digest_email_body
from codex_research_assist.openclaw_runner import _filter_final_digest_candidates, _persist_ranked_candidate_paths
from codex_research_assist.openclaw_runner import _safe_positive_int, create_temp_toml_config


class DigestSummaryTest(unittest.TestCase):
    def test_write_digest_run_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            digest_json = root / "digest-20260312-123456.json"
            digest_json.write_text("{}", encoding="utf-8")
            candidate = root / "candidate-1.json"
            candidate.write_text("{}", encoding="utf-8")
            html_path = root / "digest-2026-03-12.html"
            html_path.write_text("<html></html>", encoding="utf-8")

            summary_path = write_digest_run_summary(
                action="digest",
                digest_json_path=digest_json,
                candidate_paths=[candidate],
                html_path=html_path,
                email_json_path=None,
                telegram_json_path=None,
                output_root=root,
                profile_path=root / "profile.json",
            )

            self.assertEqual(summary_path, summary_output_path(root, digest_json))
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["run"]["action"], "digest")
            self.assertEqual(payload["artifacts"]["candidate_paths"], [candidate.as_posix()])

    def test_persist_ranked_candidate_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            digest_json = root / "digest.json"
            first = root / "a.json"
            second = root / "b.json"
            payload = {
                "candidate_paths": [second.as_posix(), first.as_posix()],
            }
            digest_json.write_text(json.dumps(payload), encoding="utf-8")
            candidates = [
                {"candidate": {"json_path": first.as_posix()}},
                {"candidate": {"json_path": second.as_posix()}},
            ]
            _persist_ranked_candidate_paths(digest_json, candidates)
            loaded = json.loads(digest_json.read_text(encoding="utf-8"))
            self.assertEqual(loaded["candidate_paths"], [first.as_posix(), second.as_posix()])
            self.assertEqual(loaded["selected_candidate_count"], 2)

    def test_filter_final_digest_candidates_prefers_agent_flag(self) -> None:
        candidates = [
            {"candidate": {"candidate_id": "a"}, "review": {"selected_for_digest": False}},
            {"candidate": {"candidate_id": "b"}, "review": {"selected_for_digest": True}},
            {"candidate": {"candidate_id": "c"}, "review": {"selected_for_digest": True}},
        ]
        filtered = _filter_final_digest_candidates(candidates, final_limit=1)
        self.assertEqual([item["candidate"]["candidate_id"] for item in filtered], ["b"])

    def test_digest_email_body_includes_profile_card(self) -> None:
        candidates = [
            {
                "paper": {"title": "A paper"},
                "triage": {"matched_interest_labels": ["GP + PDE"]},
                "review": {"recommendation": "read_first", "why_it_matters": "Worth reading now."},
            }
        ]
        plain, html = _format_digest_email_body(
            candidates,
            date_str="2026-03-12",
            html_path=Path("/tmp/digest.html"),
            profile_summary={
                "labels": ["GP + PDE", "Bilevel + Hyperparameter", "PINN Variants"],
                "updated_at": "2026-03-12T00:00:00+00:00",
                "refresh_days": 60,
            },
        )
        self.assertIn("Profile:", plain)
        self.assertIn("Current profile", html)
        self.assertIn("03/12", html)
        self.assertIn("every 60 days", html)

    def test_safe_positive_int(self) -> None:
        self.assertEqual(_safe_positive_int(15, 7), 15)
        self.assertEqual(_safe_positive_int("30", 7), 30)
        self.assertEqual(_safe_positive_int("0", 7), 7)
        self.assertEqual(_safe_positive_int("bad", 7), 7)
        self.assertEqual(_safe_positive_int(True, 7), 7)

    def test_create_temp_toml_config_handles_invalid_max_age_days(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config = {"retrieval_defaults": {"max_age_days": "invalid"}}
            temp_toml = create_temp_toml_config(
                config,
                profile_path=root / "profiles" / "research-interest.json",
                output_root=root / "reports",
            )
            try:
                text = temp_toml.read_text(encoding="utf-8")
            finally:
                temp_toml.unlink(missing_ok=True)
            self.assertIn("max_age_days = 7", text)


if __name__ == "__main__":
    unittest.main()

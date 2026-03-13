from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import importlib.util
from pathlib import Path


def _load_build():
    module_path = Path("scripts/distribution/build_skill_package.py")
    spec = importlib.util.spec_from_file_location("build_skill_package", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build


build = _load_build()


class DistributionBuildTest(unittest.TestCase):
    def tearDown(self) -> None:
        dist_dir = Path("dist")
        if dist_dir.exists():
            shutil.rmtree(dist_dir)

    def test_build_outputs_portable_skill_package(self) -> None:
        package_root, zip_path, tar_path = build()

        self.assertTrue(package_root.exists())
        self.assertTrue((package_root / "install.sh").exists())
        self.assertTrue((package_root / "config.example.json").exists())
        self.assertTrue((package_root / "profiles" / "research-interest.example.json").exists())
        self.assertTrue((package_root / "references" / "workflow.md").exists())
        self.assertTrue((package_root / "src" / "codex_research_assist" / "openclaw_runner.py").exists())
        self.assertTrue(zip_path.exists())
        self.assertTrue(tar_path.exists())

    def test_install_rewrites_runtime_paths_for_custom_target(self) -> None:
        package_root, _, _ = build()

        with tempfile.TemporaryDirectory() as tmp_dir:
            target_root = Path(tmp_dir) / "custom-skill-root"
            env = dict(os.environ, RUN_UV_SYNC="0")
            subprocess.run([str(package_root / "install.sh"), str(target_root)], check=True, env=env)

            payload = json.loads((target_root / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["profile_path"], str(target_root / "profiles" / "research-interest.json"))
            self.assertEqual(payload["output_root"], str(target_root / "reports"))
            self.assertEqual(
                payload["semantic_search"]["persist_directory"],
                str(target_root / ".semantic-search"),
            )


if __name__ == "__main__":
    unittest.main()

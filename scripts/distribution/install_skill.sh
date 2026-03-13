#!/usr/bin/env bash
set -euo pipefail

SKILL_NAME="research-assist"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TARGET_ROOT="${1:-$HOME/.openclaw/skills/$SKILL_NAME}"
RUN_SYNC="${RUN_UV_SYNC:-1}"

copy_dir() {
  local rel="$1"
  mkdir -p "$TARGET_ROOT/$rel"
  cp -a "$SCRIPT_DIR/$rel/." "$TARGET_ROOT/$rel/"
}

copy_file() {
  local rel="$1"
  mkdir -p "$(dirname "$TARGET_ROOT/$rel")"
  cp -f "$SCRIPT_DIR/$rel" "$TARGET_ROOT/$rel"
}

mkdir -p "$TARGET_ROOT"

copy_file "SKILL.md"
copy_file "config.example.json"
copy_file "pyproject.toml"
copy_file "uv.lock"
copy_dir "src"
copy_dir "references"
copy_dir "reports"
copy_dir "profiles"

# Optional directories — copy only if present in package
[[ -d "$SCRIPT_DIR/automation" ]] && copy_dir "automation"

mkdir -p "$TARGET_ROOT/profiles" "$TARGET_ROOT/reports"

created_config=0
if [[ ! -f "$TARGET_ROOT/config.json" ]]; then
  cp "$TARGET_ROOT/config.example.json" "$TARGET_ROOT/config.json"
  created_config=1
fi

if [[ ! -f "$TARGET_ROOT/profiles/research-interest.json" ]]; then
  cp "$TARGET_ROOT/profiles/research-interest.example.json" \
    "$TARGET_ROOT/profiles/research-interest.json"
fi

if [[ "$created_config" == "1" ]]; then
  python3 - "$TARGET_ROOT/config.json" "$TARGET_ROOT" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
target_root = Path(sys.argv[2]).expanduser().resolve()

payload = json.loads(config_path.read_text(encoding="utf-8"))
payload["profile_path"] = str(target_root / "profiles" / "research-interest.json")
payload["output_root"] = str(target_root / "reports")
semantic_cfg = payload.get("semantic_search")
if isinstance(semantic_cfg, dict):
    semantic_cfg["persist_directory"] = str(target_root / ".semantic-search")

config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
fi

if [[ "$RUN_SYNC" != "0" ]] && command -v uv >/dev/null 2>&1; then
  (
    cd "$TARGET_ROOT"
    uv sync
  )
fi

echo "Installed $SKILL_NAME to $TARGET_ROOT"

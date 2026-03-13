# Distribution Reference

## Goal

Produce one minimal distributable skill package from this repository.

The distributed package is intentionally smaller than the source repository.

## Include

Keep these items in the distributable skill:

- `SKILL.md`
- `config.example.json`
- `references/`
- `automation/prompts/`
- `automation/arxiv-profile-digest.example.toml`
- `profiles/research-interest.example.json`
- `reports/schema/`
- `src/`
- `pyproject.toml`
- `uv.lock`

Add these generated files at packaging time:

- `install.sh` at the package root

## Exclude

Do not include these items in the minimal packaged skill:

- `README.md`
- `README.zh-CN.md`
- `CODEMAP.md`
- `NEXT_PLAN.md`
- `temp/`
- `.state/`
- `automation/*.local.toml`
- `profiles/research-interest.json`
- `reports/generated/`

## Current Scope Decision

The minimal packaged skill currently focuses on:

- `profile_update`
- `retrieval`
- `review`
- `render`
- `delivery`
- bundled Zotero MCP read/write support
- host-side orchestration by OpenClaw rather than repo-local `codex exec` wrappers
- machine-readable digest handoff artifacts for host-side orchestration

Temporarily out of packaged baseline:

- scheduler wiring

These can return later as optional extensions, but they are not part of the current distributable baseline.

## Packaging command

Build the distributable package from the source repo with:

```bash
uv run python scripts/distribution/build_skill_package.py
```

This creates:

- `dist/research-assist-skill-v<version>/`
- `dist/research-assist-skill-v<version>.zip`
- `dist/research-assist-skill-v<version>.tar.gz`

The packaged root includes `install.sh`, which:

- copies runtime files into `~/.openclaw/skills/research-assist`
- creates `config.json` from `config.example.json` if missing
- rewrites freshly created runtime paths (`profile_path`, `output_root`, `semantic_search.persist_directory`) to the actual install target
- creates `profiles/research-interest.json` from the example profile if missing
- runs `uv sync` in the installed skill directory when `uv` is available

After installation, run commands against the installed skill root, for example:

```bash
uv run --directory ~/.openclaw/skills/research-assist \
  research-assist --action digest --config ~/.openclaw/skills/research-assist/config.json
```

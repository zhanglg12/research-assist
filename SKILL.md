---
name: research-assist
description: A lightweight arXiv literature digest skill for OpenClaw, with Zotero-driven interest profiling, research-map plus Zotero-semantic ranking, agent-enriched digest cards, and non-destructive feedback writeback.
---

# Research Assist Skill

An OpenClaw skill that turns Zotero evidence into a profile-driven arXiv digest, then lets the host agent sharpen the final shortlist.

## CLI Usage

```bash
# Full digest: profile check → arXiv retrieval → rank → markdown output
uv run --project ~/.openclaw/skills/research-assist \
  research-assist --action digest --config ~/.openclaw/skills/research-assist/config.json

# Ad-hoc arXiv search
uv run --project ~/.openclaw/skills/research-assist \
  research-assist --action search --query "gaussian process" --top 5

# Check profile refresh status
uv run --project ~/.openclaw/skills/research-assist \
  research-assist --action profile-refresh --config ~/.openclaw/skills/research-assist/config.json

# Zotero MCP server (for profile evidence + feedback writeback)
uv run --project ~/.openclaw/skills/research-assist research-assist-zotero-mcp
```

Or via Python module:

```bash
uv run --project ~/.openclaw/skills/research-assist \
  python -m codex_research_assist --action digest --config ~/.openclaw/skills/research-assist/config.json
```

Default config path: `~/.openclaw/skills/research-assist/config.json`

During install or reconfiguration, do not embed the full setup questionnaire in this file. Use `references/setup-routing.md` as the install-time interaction guide, ask only the questions relevant to the user's goal, then edit `config.json` directly.

## Install-Time Behavior

Installation and reconfiguration are one-time operations.

Hard rules for the host agent:

- use `references/setup-routing.md` only when the user is installing, reconfiguring, or when required config is missing
- once `config.json` is valid, normal digest/search/render/feedback runs must not reopen setup questions
- do not restate dormant install options during regular literature work
- if the user asks for normal runtime work, prefer using the existing config over discussing installation
- when setup selects optional backends or delivery routes, execute the required install/setup commands instead of only listing them
- before leaving setup, run a minimal verification for the selected backend or route and report the result
- only fall back to manual instructions when a step is blocked by missing secrets, missing local services, missing permissions, or a platform limitation

## Config Format

```json
{
  "profile_path": "~/.openclaw/skills/research-assist/profiles/research-interest.json",
  "output_root": "~/.openclaw/skills/research-assist/reports",
  "retrieval_defaults": {
    "max_results_per_interest": 20,
    "since_days": 7,
    "max_age_days": 7
  }
}
```

## Architecture

```
config.json (OpenClaw skill config)
    ↓
openclaw_runner.py (CLI entry, markdown to stdout)
    ├── profile_refresh_policy  → check if profile needs update
    ├── pipeline.py             → arXiv Atom API retrieval
    ├── ranker.py               → two-signal scoring (map_match + zotero_semantic)
    └── format_*_markdown()     → structured markdown output
```

No LLM calls inside the packaged Python pipeline. Retrieval, ranking, and formatting are pure data operations.
Intelligence comes from the calling agent (OpenClaw / Claude Code / Codex CLI).

Profile refresh should be handled by the OpenClaw controller or agent layer, using live Zotero evidence via the bundled Zotero MCP.

## Workflow Stages

### 1. `profile_update`

- read the current Zotero evidence base when refresh is required
- maintain `profiles/research-interest.json`
- preserve the compact contract: `method_keywords`, `query_aliases`, `exclude_keywords`
- keep method labels short and retrieval-friendly
- prefer `zotero_semantic_search` for discovery, then `zotero_search_items` for exact resolution
- use `research-assist-zotero-mcp` for live Zotero reads (no direct API calls)

OpenClaw generation rule:

- treat Zotero like a studio palette, not a flat folder dump
- use collection structure as the sketch of the research map
- use representative papers as the main evidence for what each region actually contains
- use semantic search as the blending layer that connects nearby themes across collections
- write interests that feel like stable method axes, not loose keyword bags
- if collection names and paper content disagree, trust the papers more than the folder label
- if summary terms are frequent but too generic, use them only to refine wording, not to define the map
- the final profile should read like a compact map of the user's research territory: a few clear regions, each with short labels and retrieval-friendly aliases

### 2. `retrieval`

- query arXiv Atom API per interest
- generate structured candidate JSON with full provenance
- deduplicate across interests

### 3. `review`

- rank candidates with two-signal scoring:
  - **map_match** (0.30): how well the paper fits the current research-map slices
  - **zotero_semantic** (0.70): how close the paper is to nearby Zotero literature
- apply the low-map guard:
  - if `map_match < 0.30`, apply the configured penalty to avoid semantic-only false positives
- output ranked markdown to stdout for agent review
- prefer a smaller sharper set over a noisy dump
- stay `abstract-first`

### Digest Enrichment

- OpenClaw should treat agent-filled review as the default digest-enrichment path
- after retrieval, let the host agent enrich the top-ranked candidate JSON files with review patches
- use `review_generation.agent_top_n` to cap how many ranked candidates the host agent needs to inspect
- let the host agent decide the final visible subset by setting `review.selected_for_digest`
- use `review_generation.final_top_n` as the hard upper bound for the final rendered digest
- keep `fallback_to_system` enabled unless the user explicitly wants hard failure instead of fallback text
- after patches are applied, re-render the digest so HTML / Telegram outputs use the enriched review text
- `why_it_matters` should sound like a recommendation, not a provenance report
- `caveats` should capture real uncertainty or scope boundaries, not generic hedging
- the host agent should also fill `review.zotero_comparison`, including nearest-neighbor fallback when candidate-level evidence is missing
- keep nearest-neighbor output compact: usually 1-2 items
- the host agent is not responsible for email / telegram wrapper copy, subjects, or routing

### Delivery Routing

- use one shared delivery path and branch at the end with `delivery.primary_channel`
- default primary channel is `email`; `telegram` is backup or alternate primary
- channel wrappers are system-owned:
  - email subject/body/profile card/stat cards
  - telegram compact message shell
- do not ask the host agent to generate channel-specific wrappers

### Stage 6: `feedback_sync`

After the digest is reviewed and delivered, the host agent may push non-destructive feedback back into Zotero.

Workflow:

1. collect the user's explicit feedback on each digest candidate (keep, drop, archive, watch, etc.)
2. encode feedback as `reports/schema/zotero-feedback.schema.json`
3. call `zotero_apply_feedback` through the bundled Zotero MCP with `dry_run=true` first
4. show the dry-run plan to the user and ask for confirmation before applying
5. only after confirmation, re-run with `dry_run=false`

Allowed feedback decisions:

- `read_first` — high-priority paper, tag and promote in library
- `skim` — worth scanning, tag for later review
- `watch` — track this topic area, add to watchlist collection
- `skip_for_now` — not relevant now, mark but do not remove
- `archive` — reviewed and filed, move to archive collection
- `watchlist` — add to a standing watchlist for periodic check-in
- `ignore` — not relevant, tag to suppress in future runs
- `unset` — no decision yet, skip writeback for this item

What feedback can do (non-destructive only):

- add tags (including `ra-status:*` decision tags)
- add or change collection membership
- append notes to items
- create new collections if needed for organization

What feedback must never do:

- delete Zotero items or collections
- modify item metadata (title, authors, abstract, DOI)
- move or delete attachment files
- rewrite top-level taxonomy without explicit user instruction
- apply changes without showing the dry-run plan first

Matching behavior:

- match items by `item_key` (preferred), `doi`, or `title_contains`
- at least one match field must be provided per decision
- DOI matching is case-insensitive
- `title_contains` uses substring match (not exact)
- if no match is found, the decision is recorded as `not_found` in the plan

Edge cases:

- duplicate tags are deduplicated (case-insensitive)
- previous `ra-status:*` tags are replaced when a new decision is applied
- the `research-assist` system tag is always preserved
- `unset` decisions produce no status tag and no writeback
- empty `add_tags`, `remove_tags`, `add_collections`, `remove_collections` are allowed (no-op for that field)

## Hard Rules

- do not expand concise method labels into long topic sentences
- do not make full text the default review mode
- do not delete Zotero items or collections automatically
- prefer `dry_run=true` for any Zotero writeback
- do not treat scheduler wiring as part of the skill

## Key Runtime Files

- OpenClaw runner: `src/codex_research_assist/openclaw_runner.py`
- Ranker: `src/codex_research_assist/ranker.py`
- Pipeline: `src/codex_research_assist/arxiv_profile_pipeline/pipeline.py`
- Example config: `config.example.json`
- Example profile: `profiles/research-interest.example.json`

## Reference Documents

- `references/workflow.md` — stage order and controller boundary
- `references/contracts.md` — profile contract and review policy
- `references/distribution.md` — packaging include/exclude rules
- `references/setup-routing.md` — install-time route selection and option questions
- `references/review-generation.md` — `system` vs `agent_fill` review contract
- `references/profile-map-generation.md` — how to turn Zotero evidence into a research-map-style profile

## Packaging Boundary

Include in distributable skill:

- `SKILL.md`, `config.example.json`, `pyproject.toml`, `uv.lock`
- `src/`
- `references/`
- `profiles/research-interest.example.json`
- `automation/arxiv-profile-digest.example.toml`
- `automation/prompts/`
- `reports/schema/`
- generated package-root `install.sh`

Exclude:

- generated reports, temporary state
- local secret config
- scheduler wrappers
- repository planning documents (`NEXT_PLAN.md`, `CODEMAP.md`)

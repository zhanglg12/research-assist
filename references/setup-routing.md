# Interactive Agent Setup

Use this document during install or reconfiguration.

Goal:

- let the agent ask a small number of focused setup questions
- let the agent edit `config.json` directly
- avoid dumping the entire config surface into one message or one giant form
- make setup disappear after day 1 unless the user explicitly asks to revisit it

This is an interaction guide for the agent. It is not a script contract.

## Core rule

The agent should route by conversation, not by installer code.

That means:

1. inspect the user's goal
2. decide which option cluster matters
3. ask only the questions needed for that cluster
4. write or update `config.json`
5. summarize what was enabled and what stayed off

Once setup is complete:

- do not reopen the setup questionnaire during normal digest/search/render runs
- do not repeat dormant installation choices unless the user asks to reconfigure
- treat setup as background scaffolding, not as the main interaction surface

---

## Phase 0: Locate the host agent's skill directory and install/update the repo

Before asking any setup questions, the agent should first resolve its own skill root (or the user-requested install location) and ensure `research-assist` is present there.

Resolution rule:

1. Detect the host agent's normal skill/plugin directory if it has one.
2. Prefer an existing host-managed skill root; do not lead by telling the user to create a new one.
3. If the host agent has no standard skill root, ask the user for the install location or use a clearly named local project directory.
4. Treat OpenClaw as one example, not the universal default.

Examples:

- OpenClaw skill root: `~/.openclaw/skills/research-assist`
- Other agents: use that agent's own skill/tool/plugin directory, or a user-provided project path

Required behavior:

1. Resolve the install target first.
2. Check whether the target already exists.
3. Prefer reusing an existing skill root when one is available.
4. Only if the target has been resolved and its parent path is missing should the agent create that parent directory as an implementation detail.
5. If the target exists and is already a git checkout of `research-assist`, use it in place and update it when appropriate.
6. Only after the skill root exists should the agent inspect or write `config.json`.

OpenClaw example commands (after resolving that OpenClaw is the host and `~/.openclaw/skills/research-assist` is the correct target):

```bash
if [ -d ~/.openclaw/skills/research-assist/.git ]; then
  cd ~/.openclaw/skills/research-assist && git pull --ff-only
else
  mkdir -p ~/.openclaw/skills
  git clone https://github.com/zhanglg12/research-assist ~/.openclaw/skills/research-assist
fi
cd ~/.openclaw/skills/research-assist
uv sync
```

If shell access is available, perform the install/update steps for the resolved target instead of only telling the user what to run.

## Pre-check: is config.json already valid?

Before asking any setup questions, check if a valid `config.json` already exists at the expected location (`~/.openclaw/skills/research-assist/config.json` or the path the user provided).

**If config.json exists and is valid JSON with the expected structure:**

Ask the user:

> **research-assist is already configured. What would you like to do?**
>
> 1. **Run with current config** -- skip setup, proceed to the task
> 2. **Reconfigure** -- walk through setup again from the beginning
> 3. **Update specific settings** -- change only the settings you name

If the user chooses 1, exit setup immediately and proceed to their actual task.
If the user chooses 2, continue with Phase 1 below.
If the user chooses 3, jump directly to the relevant option cluster.

**If config.json does not exist or is invalid:** continue with Phase 1.

---

## Phase 1: Foundation

### Step 1.1: Goal selection

This is the single most important question. It determines every follow-up.

Ask the user:

> **What would you like research-assist to do?**
>
> | | Option | What you get | What you miss |
> |---|---|---|---|
> | **A** | **Quick try** | arXiv keyword filtering + local HTML digest | No library-aware ranking, no feedback loop |
> | **B** | **Zotero-powered** (recommended) | Profile auto-built from your library, dual-signal ranking, feedback loop | Requires Zotero API credentials |
>
> Without Zotero, only ~30% of ranking intelligence is available (keyword match only). If you have a Zotero library, **B** is strongly recommended.

Wait for the user's answer before continuing.

**If A:** set `semantic_search.enabled = false`, skip Phase 2 and Phase 5. Go to Step 1.2.
**If B:** go to Step 1.2.

### Step 1.2: Add-ons

Ask the user:

> **Would you like any of these enhancements?**
>
> | | Add-on | What it adds | Requires |
> |---|---|---|---|
> | **C** | **Semantic search** | Find nearest Zotero neighbors for each candidate | Local `zotero.sqlite` + embedding model (requires B) |
> | **D** | **Push delivery** | Digest sent to email or Telegram automatically | SMTP or Telegram bot credentials |
>
> Pick any combination: C, D, both, or neither.
> C is only available if you chose B above.

Wait for the user's answer before continuing.

**If C selected:** continue to Phase 2.
**If D selected:** continue to Phase 3.
**If neither:** skip to Phase 4.

---

## Phase 2: Zotero + Semantic Search

**Skip condition:** user chose A in Step 1.1 and did not select C.

### Step 2.1: Zotero connection (if B selected)

Ask the user:

> **Your Zotero library type?**
>
> 1. **Personal** (`user`) -- your own library
> 2. **Group** (`group`) -- shared team library

Then ask:

> **Your Zotero library ID?**
> Find it at [zotero.org/settings/keys](https://www.zotero.org/settings/keys) -- the numeric "Your userID" value.

Then ask:

> **Your Zotero API key?**
> Create one at the same page. The agent will store it in `zotero.api_key`.
> Or set the `ZOTERO_API_KEY` environment variable instead.

Note: `zotero.profile_collections` and `zotero.profile_tags` can be left empty at setup time. They are populated automatically during the first `profile_update` stage.

### Step 2.2: Semantic search backend (if C selected)

**Skip condition:** user did not select C.

Ask the user:

> **Which embedding backend?**
>
> | | Backend | Speed | Size | Memory | Note |
> |---|---|---|---|---|---|
> | **1** | **Ollama + Qwen3** (recommended) | ~70ms/paper | 639 MB | ~800 MB while running, released after idle | Best quality, zh+en, needs Ollama |
> | **2** | **fastembed** | ~6ms/paper | 33 MB | ~100 MB during embedding | Zero-service fallback, English-focused |
> | **3** | **OpenAI API** | ~200ms/paper | remote | negligible | Highest quality, paid (~$0.02/1M tokens) |
> | **4** | **Gemini API** | ~300ms/paper | remote | negligible | Good quality, free tier available |
>
> All local models only use memory during embedding, released after.

Then ask:

> **Path to your local `zotero.sqlite`?**
> Usually at `~/Zotero/zotero.sqlite` (macOS/Linux) or `%APPDATA%\Zotero\Zotero\zotero.sqlite` (Windows).

Recommendation flow:
1. If user has Ollama -> `"qwen"` (best balance of quality, privacy, and speed)
2. If user wants zero external services -> `"fastembed"` (works everywhere, pure Python)
3. If user already has OpenAI/Gemini API keys -> offer the corresponding backend

### Step 2.3: Fulltext and auto-update (if C selected)

These have sensible defaults. Only mention them briefly:

> **Two quick settings for semantic search:**
>
> - **Fulltext extraction** (default: off) -- index PDF content, not just title+abstract. ~12x slower but deeper matching.  Enable? (y/N)
> - **Auto-update** (default: on) -- keep index fresh automatically with ~100ms overhead per query. Keep on? (Y/n)

---

## Phase 3: Delivery Channel

**Skip condition:** user did not select D.

### Step 3.1: Channel choice

Ask the user:

> **How do you want to receive digests?**
>
> | | Channel | Experience | Best for |
> |---|---|---|---|
> | **1** | **Email** | Full HTML digest in your inbox | Regular reading, team sharing |
> | **2** | **Telegram** | Compact summary pushed to chat | Mobile-first, quick triage |
> | **3** | **Both** | Email primary, Telegram as backup | Never miss a digest |

### Step 3.2: Email details (if email selected)

Ask for each in sequence:

> 1. **Sender address** (e.g. `digest@example.com`)
> 2. **Recipient(s)** (comma-separated)
> 3. **SMTP server** (e.g. `smtp.gmail.com`)
> 4. **SMTP port** (default: `465`)
> 5. **SMTP user** (usually same as sender)
> 6. **SMTP password** (store in config or use env var)

Set `delivery.email.send_enabled = true` when configuring email.

### Step 3.3: Telegram details (if Telegram selected)

> Telegram requires two environment variables:
> - `TELEGRAM_BOT_TOKEN` -- create a bot via [@BotFather](https://t.me/BotFather)
> - `TELEGRAM_CHAT_ID` -- the target chat/channel ID
>
> These are read from env vars at runtime, not stored in `config.json`.

Set `delivery.telegram.send_enabled = true` and `delivery.primary_channel = "telegram"` if Telegram is the sole channel.

---

## Phase 4: Review Settings

These have sensible defaults. Ask briefly:

> **Review enrichment settings** (defaults in parentheses):
>
> - How many top papers should the host agent enrich? (5)
> - How many papers in the final visible digest? (5)
> - Keep system-generated fallback text when agent review is unavailable? (yes)
>
> Press Enter to accept all defaults, or specify changes.

---

## Phase 5: Feedback Writeback

**Skip condition:** user chose A in Step 1.1.

Ask the user:

> **Enable Zotero feedback writeback?**
>
> | With feedback | Without feedback |
> |---|---|
> | Digest decisions saved as Zotero tags | Decisions lost after session |
> | Papers auto-organized into collections | Manual collection management |
> | Structured notes with rationale appended | No trail of why papers were kept/skipped |
> | Next digest run starts from a better library | Library stays the same |
>
> All operations are non-destructive. Dry-run preview is shown before any apply.
>
> 1. **Yes** (recommended) -- enable feedback with dry-run default
> 2. **No** -- skip feedback for now

---

## Phase 6: Confirm and Write

### Step 6.1: Show summary

Before writing anything, display a compact summary:

```
research-assist Configuration Summary
======================================

Foundation:     [Quick try / Zotero-powered]
Zotero:         [library_type=user, library_id=XXXXX / not configured]
Semantic:       [qwen / fastembed / openai / gemini / disabled]
Delivery:       [email / telegram / both / local only]
Review:         agent_top_n=5, final_top_n=5
Feedback:       [enabled (dry-run default) / disabled]

Config path:    ~/.openclaw/skills/research-assist/config.json
```

Ask: **Look good? (Y/n)**

### Step 6.2: Write config.json

Copy `config.example.json` as the starting template, then modify only the fields the user's answers affect. Write to the target path.

### Step 6.3: Create directories and profile

```bash
mkdir -p ~/.openclaw/skills/research-assist/profiles
mkdir -p ~/.openclaw/skills/research-assist/reports
cp profiles/research-interest.example.json \
  ~/.openclaw/skills/research-assist/profiles/research-interest.json
```

---

## Phase 7: Post-setup Execution and Verification

Based on the user's choices, the agent must execute the relevant setup commands itself whenever shell access is available. Do not stop at copy-paste instructions.

If a step is blocked by a missing secret, missing local service, OS limitation, or user approval requirement, say exactly which step is blocked and why. Otherwise, perform it.

| Choice | Command(s) to execute | Verification |
|---|---|---|
| Embedding: `"qwen"` | `ollama pull qwen3-embedding:0.6b` | Confirm model exists via `ollama list` |
| Embedding: `"fastembed"` | `uv sync --extra semantic-fastembed` | Import succeeds |
| Embedding: `"openai"` | (no extra install) | `OPENAI_API_KEY` is set |
| Embedding: `"gemini"` | `uv sync --extra semantic-gemini` | `GEMINI_API_KEY` is set |
| Fulltext extraction | `uv sync --extra semantic-fulltext` | Import succeeds |
| Telegram delivery | (no install) | `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` visible |

### Smoke check

```bash
uv run --project ~/.openclaw/skills/research-assist python - <<'PY'
from codex_research_assist.zotero_mcp.chroma_client import create_chroma_client
client = create_chroma_client("~/.openclaw/skills/research-assist/config.json")
print("Backend:", client.embedding_function.name())
print("Collection:", client.get_collection_info())
PY
```

### Step 7.1: Show completion

```
Setup Complete!
================

CONFIGURED:
  [list each enabled feature and its key setting]

SKIPPED:
  [list each feature that was left off]

BLOCKED (if any):
  [list steps that need user action, e.g. "Ollama not running"]

NEXT STEPS:
  # Run a full digest
  uv run --project ~/.openclaw/skills/research-assist \
    research-assist --action digest \
    --config ~/.openclaw/skills/research-assist/config.json

  # Or do an ad-hoc search
  uv run --project ~/.openclaw/skills/research-assist \
    research-assist --action search --query "your query" --top 5
```

Do not turn the completion summary into another setup round. Once config is written and verified, move to the user's actual task.

---

## Reference: Config Structure

**CRITICAL: Use exactly these field names and nesting.** Do not invent new fields. Copy `config.example.json` as the starting template, then modify only the fields the user's answers affect.

```json
{
  "profile_path": "~/.openclaw/skills/research-assist/profiles/research-interest.json",
  "output_root": "~/.openclaw/skills/research-assist/reports",
  "review_generation": {
    "agent_top_n": 5,
    "final_top_n": 5,
    "fallback_to_system": true
  },
  "delivery": {
    "primary_channel": "email",
    "email": {
      "send_enabled": false,
      "sender": "",
      "recipients": [],
      "smtp_server": "",
      "smtp_port": 465,
      "smtp_user": "",
      "smtp_pass": "",
      "tls_mode": "ssl",
      "timeout": 20,
      "subject_prefix": "[research-assist]",
      "attach_html": true,
      "attach_digest_json": false,
      "write_metadata": true,
      "telegram_fallback_on_failure": true
    },
    "telegram": {
      "send_enabled": false,
      "write_html": true,
      "write_metadata": true
    }
  },
  "zotero": {
    "library_id": "",
    "api_key": "",
    "library_type": "user",
    "profile_collections": [],
    "profile_tags": [],
    "feedback_default_collections": [],
    "feedback_default_tags": ["research-assist"]
  },
  "semantic_search": {
    "enabled": true,
    "zotero_db_path": "",
    "persist_directory": "~/.openclaw/skills/research-assist/.semantic-search",
    "collection_name": "research_assist_zotero",
    "embedding_model": "qwen",
    "local_group_id": null,
    "local_library_id": null,
    "extract_fulltext": false,
    "update_config": {
      "auto_update": true,
      "update_frequency": "daily",
      "last_update": null,
      "update_days": 7
    },
    "extraction": {
      "pdf_max_pages": 10
    }
  },
  "retrieval_defaults": {
    "max_results_per_interest": 20,
    "since_days": 7,
    "max_age_days": 7
  }
}
```

## Reference: Field Mapping

| User choice | Field(s) to change | Value |
|---|---|---|
| Quick try (no Zotero) | `semantic_search.enabled` | `false` |
| Zotero personal library | `zotero.library_type` | `"user"` |
| Zotero group library | `zotero.library_type` | `"group"` |
| Library ID | `zotero.library_id` | user-provided string |
| API key | `zotero.api_key` | user-provided string |
| Embedding: Ollama qwen | `semantic_search.embedding_model` | `"qwen"` |
| Embedding: fastembed | `semantic_search.embedding_model` | `"fastembed"` |
| Embedding: OpenAI | `semantic_search.embedding_model` | `"openai"` |
| Embedding: Gemini | `semantic_search.embedding_model` | `"gemini"` |
| zotero.sqlite path | `semantic_search.zotero_db_path` | user-provided path |
| Enable email delivery | `delivery.email.send_enabled` | `true` |
| | `delivery.email.sender` | user-provided |
| | `delivery.email.recipients` | `["user@example.com"]` |
| | `delivery.email.smtp_server` | user-provided |
| | `delivery.email.smtp_port` | user-provided (default `465`) |
| | `delivery.email.smtp_user` | user-provided |
| | `delivery.email.smtp_pass` | user-provided |
| Enable Telegram delivery | `delivery.telegram.send_enabled` | `true` |
| | `delivery.primary_channel` | `"telegram"` |
| Review: change top N | `review_generation.agent_top_n` | user-provided integer |
| Review: change final N | `review_generation.final_top_n` | user-provided integer |
| Enable fulltext extraction | `semantic_search.extract_fulltext` | `true` |
| Disable semantic search | `semantic_search.enabled` | `false` |

**Do not add fields that don't exist in the reference structure above.** There is no `zotero.enabled`, no `feedback.enabled`, no `delivery.local_output_enabled`, no `zotero.profile_basis`. Feedback writeback is controlled by `zotero.feedback_default_tags` and `zotero.feedback_default_collections` (empty arrays = disabled).

## Reference: Config Targets

Valid values for `delivery.primary_channel`: `"email"` or `"telegram"`. There is no `"local"` value -- local file output is always enabled regardless of this setting. When the user does not want push delivery, keep the default `"email"` and leave both `email.send_enabled` and `telegram.send_enabled` as `false`.

## Reference: CLI Commands

```bash
# Full digest
uv run --project ~/.openclaw/skills/research-assist \
  research-assist --action digest --config ~/.openclaw/skills/research-assist/config.json

# Profile refresh
uv run --project ~/.openclaw/skills/research-assist \
  research-assist --action profile-refresh --config ~/.openclaw/skills/research-assist/config.json

# Ad-hoc search
uv run --project ~/.openclaw/skills/research-assist \
  research-assist --action search --query "your query" --top 5
```

Do not use `python -m research_assist.cli` or `python -m research_assist.main` -- those do not exist.

## Reference: Note on config.example.json

`config.example.json` ships with `semantic_search.enabled: true` and `embedding_model: "qwen"`. This represents the **recommended full configuration**, not a minimal starting point. When the user chooses the minimal path (no Zotero, no semantic search), the agent should set `semantic_search.enabled: false` and leave other semantic search fields at their defaults.

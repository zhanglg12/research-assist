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

## Option clusters

### 1. Minimal digest

Use when the user only wants:

- arXiv retrieval
- profile-based ranking
- local HTML / markdown output

Ask:

1. where `profile_path` should live
2. where `output_root` should live
3. whether push delivery is needed now at all
4. how many top papers the host agent should enrich after retrieval
5. whether system fallback text should still be written before agent patches arrive

#### What the user gets

| Capability | Included | Not included |
|---|---|---|
| arXiv retrieval by research profile | Yes | — |
| Two-signal ranking (map_match + zotero_semantic) | map_match only (no Zotero) | zotero_semantic requires Zotero setup |
| Local HTML digest | Yes | — |
| Agent-filled reviews | Yes (host agent enriches top N) | — |
| Email / Telegram push | No | Enable in cluster 5 or 6 |
| Semantic search over library | No | Enable in cluster 3 |
| Feedback writeback to Zotero | No | Enable in cluster 7 |

This is the fastest path to a working digest. Good for trying the tool before connecting Zotero.

Usually do not ask about:

- Zotero API
- local `zotero.sqlite`
- feedback writeback

### 2. Zotero-backed profile refresh

Use when the user wants:

- profile refresh from live Zotero evidence
- library-scoped retrieval context

Ask:

1. `user` or `group` library
2. library id — find it at [zotero.org/settings/keys](https://www.zotero.org/settings/keys) (the numeric "Your userID" value)
3. API key — create one at the same page; the agent should store it in `zotero.api_key` or suggest setting the `ZOTERO_API_KEY` env var
4. whether profile basis should come from collections, tags, or both

Note: `zotero.profile_collections` and `zotero.profile_tags` can be left empty at setup time. They are populated automatically during the first `profile_update` stage based on the user's library structure. The agent does not need to ask for specific collection or tag names.

#### Impact: with vs without Zotero

Zotero integration is the core differentiator of research-assist. Without it, the tool works but at significantly reduced capability:

| Aspect | Without Zotero | With Zotero |
|---|---|---|
| Profile source | Manual JSON editing | Auto-built from collections, tags, and representative papers |
| Ranking quality | map_match signal only (keyword overlap, weight 0.30) | map_match + zotero_semantic (library-aware affinity, weight 0.70) — **the dominant ranking signal is unavailable without Zotero** |
| Candidate anchors | None — you see scores but no context | Each paper shows nearest Zotero neighbors ("similar to paper X you already collected") |
| Feedback loop | Not available — digest is a dead end | Tags, collections, notes written back → next run starts smarter |
| Profile freshness | Must manually update interests | Auto-refreshes from library changes |

**Bottom line:** Without Zotero, you get ~30% of the ranking intelligence. The tool still works for basic arXiv filtering, but the "your library finds papers for you" experience requires Zotero. If the user has a Zotero library, strongly recommend enabling it.

Ask for API key location only if the user actually wants live Zotero reads now.

### 3. Local semantic search

Use when the user wants:

- semantic search over local Zotero data
- better discovery than exact title/tag search

Ask:

1. local `zotero.sqlite` path
2. embedding backend (see table below)
3. whether semantic search should be enabled by default
4. whether the search should be limited to a specific local group/library id

If the user sets `semantic_search.enabled = false`, the digest should skip local semantic ranking entirely and fall back to `map_match` only.

#### Embedding backend comparison

Show this table to the user so they can choose with full context:

| Backend | Config value | Requirements | Speed (per paper) | Dimensions | Model size | Memory | Best for |
|---|---|---|---|---|---|---|---|
| **Ollama + Qwen3** | `"qwen"` | Ollama running locally with `qwen3-embedding:0.6b` | ~70ms (title+abstract) | 1024 | 639 MB (managed by Ollama) | ~800 MB while running, released after idle | Best quality, multilingual (zh+en), recommended default |
| **fastembed** | `"fastembed"` | `uv sync --extra semantic-fastembed` (no external service) | ~6ms (title+abstract) | 384 | ~33 MB (auto-downloaded) | ~100 MB during embedding, released after | Fast fallback, no GPU/service needed, English-focused |
| **OpenAI** | `"openai"` | `OPENAI_API_KEY` | ~200ms (API call) | 1536 | None (remote) | Negligible | Highest quality, requires paid API (~$0.02/1M tokens) |
| **Gemini** | `"gemini"` | `uv sync --extra semantic-gemini` + `GEMINI_API_KEY` | ~300ms (API call) | 768 | None (remote) | Negligible | Good quality, free tier available |
| **sentence-transformers** | model name (e.g. `"Qwen/Qwen3-Embedding-0.6B"`) | `uv sync --extra semantic-local` + PyTorch | ~50ms (GPU), ~200ms (CPU) | varies | 600 MB–2 GB + PyTorch (~2 GB) | 1–3 GB during embedding | Custom models, research use |

All local models (Ollama, fastembed, sentence-transformers) only occupy memory during embedding operations. Once indexing or search completes, memory is released (Ollama unloads after idle timeout, fastembed/sentence-transformers release on process exit).

**Recommendation flow:**
1. If user has Ollama → `"qwen"` (best balance of quality, privacy, and speed)
2. If user wants zero external services → `"fastembed"` (works everywhere, pure Python)
3. If user already has OpenAI/Gemini API keys → offer the corresponding backend

#### Fulltext extraction impact

| Setting | `extract_fulltext: false` (default) | `extract_fulltext: true` |
|---|---|---|
| Index source | Title + abstract only | Title + abstract + PDF full text |
| Speed (Ollama qwen3) | ~70ms/paper | ~900ms/paper (12x slower) |
| Speed (fastembed) | ~6ms/paper | ~80ms/paper |
| Extra dependencies | None | `uv sync --extra semantic-fulltext` (markitdown, pdfminer) |
| Disk for index | ~1 MB per 100 papers | ~10 MB per 100 papers |
| When to enable | Most use cases — abstract captures the core idea | Deep semantic matching needed, e.g. methodology-level similarity across papers with similar abstracts |

#### Auto-update impact

| Setting | `auto_update: false` | `auto_update: true` (default) |
|---|---|---|
| Index freshness | Manual: call `zotero_update_search_database` | Automatic: checks before each search, incremental |
| Overhead | Zero between manual updates | Small per-query check (~100ms if no new items) |
| When to choose | Large libraries (>10k items) where rebuild cost matters | Most use cases — keeps index in sync with Zotero |

Do not ask these questions if semantic search is not requested.

### 4. Agent-filled review

Use when the user wants:

- `Why it matters`
- recommendation text from the assistant perspective
- review notes that use profile context and later can use Zotero evidence

Ask:

1. how many top papers should be enriched first
2. how many papers may remain in the final visible digest
3. whether fallback to system text should remain enabled when agent review is unavailable

Important:

- agent-filled review is the default host-side behavior for digest enrichment
- the host agent should configure the supporting keys in `config.json`, then honor them in later runs

### 5. Email-first delivery

Use when the user wants direct delivery instead of only local artifacts.

#### Delivery channel comparison

| Channel | What happens | Best for |
|---|---|---|
| **Local file only** (default) | HTML + JSON written to `output_root` | Development, manual review, agent-driven workflows |
| **Email** | HTML digest sent to inbox, local files also written | Regular reading habit, team sharing |
| **Telegram** | Compact summary pushed to chat, local files also written | Mobile-first, quick triage |

Ask:

1. whether email should be the primary channel
2. sender address
3. recipients
4. SMTP host / port / auth method
5. whether HTML should be attached

**Important:** When enabling email delivery, the agent must set `delivery.email.send_enabled = true`. Without this, SMTP credentials are stored but email is never actually sent.

Defaults:

- `delivery.primary_channel = "email"`
- `delivery.email.send_enabled = true` (set this when user wants email delivery)
- keep `attach_digest_json = false` unless the user explicitly wants machine-readable attachments
- keep local HTML and metadata enabled

### 6. Telegram delivery

Use when the user wants push delivery rather than only local files.

Ask:

1. whether direct Telegram sending should be enabled (`delivery.telegram.send_enabled = true`)
2. whether Telegram is the primary route or only a fallback/alternate route
3. whether local HTML and metadata files should still be written

**Credentials:** Telegram requires two environment variables:
- `TELEGRAM_BOT_TOKEN` — create a bot via [@BotFather](https://t.me/BotFather)
- `TELEGRAM_CHAT_ID` — the target chat/channel ID

These are read from env vars at runtime, not stored in `config.json`. The agent should instruct the user to set them in `.env` or their shell profile.

If Telegram is off, keep local artifacts on by default.

### 7. Zotero feedback writeback

Use when the user wants post-review organization or non-destructive writeback.

#### Feedback impact

| With feedback | Without feedback |
|---|---|
| Digest decisions (`read_first`, `archive`, etc.) saved as Zotero tags | Decisions lost after digest session |
| Papers auto-organized into collections | Manual collection management |
| Structured notes with rationale appended | No trail of why a paper was kept/skipped |
| Next digest run starts from a better library | Library stays the same between runs |

All feedback operations are non-destructive: no deletes, no metadata overwrites, dry-run preview before any apply.

Ask:

1. whether feedback writeback should be enabled at all
2. default tags
3. default collections
4. whether dry-run should remain the default behavior

## Question ordering

**Critical: ask one question at a time.** Do not dump all questions into a single message. Each step should be a self-contained card with clear options.

### Interaction style

1. **One question per message.** Present 2–5 options as a compact card. Wait for the user's answer before moving on.
2. **Show impact inline.** Each option should briefly say what it means for the user's experience, not just what it configures.
3. **Use visual structure.** Format options as a lettered list or small table. Bold the recommended choice.
4. **Skip irrelevant questions.** If the user's earlier answers make a question moot, skip it silently.
5. **Confirm at the end.** After all questions, show a single compact summary of what was enabled and what was left off, then write `config.json`.

### Step order

Walk through these steps in order. Skip steps that don't apply based on the user's earlier answers.

1. **Goal selection** — What outcome does the user want? (minimal digest / Zotero-backed / semantic search / push delivery). This determines which follow-up steps to ask.
2. **Zotero connection** — Library type, library ID, API key, profile basis (only if Zotero was selected).
3. **Semantic search backend** — Embedding backend choice, zotero.sqlite path (only if semantic search was selected).
4. **Delivery channel** — Email, Telegram, or local-only (only if push delivery was selected).
5. **Delivery details** — SMTP / Telegram credentials (only for the chosen channel).
6. **Review settings** — How many papers to enrich, how many in final digest (always ask, but can use defaults).
7. **Feedback writeback** — Enable or not, dry-run default (only if Zotero was selected).
8. **Summary and confirm** — Show the full config plan, ask for confirmation, then write `config.json`.

### Example interaction flow

**Step 1 — Foundation:**
> First, do you have a Zotero library you'd like to connect?
>
> | | Mode | What you get | What you miss |
> |---|---|---|---|
> | **A** | **Quick try** | arXiv keyword filtering + local HTML digest | No library-aware ranking, no feedback loop |
> | **B** | **Zotero-powered** ⭐ | Profile auto-built from your library, dual-signal ranking (keyword 0.30 + semantic 0.70), feedback loop | — |
>
> ⚠️ Choosing A means only ~30% of ranking intelligence is available. If you have a Zotero library, B is strongly recommended.

**Step 2 — Add-ons (after Step 1):**
> Want to enhance your setup?
>
> | | Add-on | What it adds | Requires |
> |---|---|---|---|
> | **C** | **Semantic search** | Find nearest Zotero neighbors for each candidate, richer context | Local `zotero.sqlite` + embedding model |
> | **D** | **Push delivery** | Digest sent to email or Telegram automatically | SMTP or Telegram bot credentials |
>
> Pick any combination: C, D, both, or neither. (C requires B from Step 1.)

**Step 3 — Zotero connection (if B selected):**
> Your Zotero library type?
>
> - **A. Personal** (`user`) — your own library
> - **B. Group** (`group`) — shared team library

**Step 4 — Embedding backend (if C selected):**
> Which embedding backend?
>
> | | Backend | Speed | Size | Memory | Note |
> |---|---|---|---|---|---|
> | **A** | **Ollama + Qwen3** ⭐ | ~70ms/paper | 639 MB | ~800 MB while running, released after idle | Best quality, zh+en, needs Ollama running |
> | **B** | fastembed | ~6ms/paper | 33 MB | ~100 MB during embedding, released after | Zero-service fallback, English-focused |
> | **C** | OpenAI API | ~200ms/paper | remote | negligible | Highest quality, paid (~$0.02/1M tokens) |
> | **D** | Gemini API | ~300ms/paper | remote | negligible | Good quality, free tier |
>
> All local models only use memory during embedding, released after.

**Step 5 — Delivery channel (if D selected):**
> How do you want to receive digests?
>
> | | Channel | Experience | Best for |
> |---|---|---|---|
> | **A** | **Email** | Full HTML digest in your inbox | Regular reading, team sharing |
> | **B** | **Telegram** | Compact summary pushed to chat | Mobile-first, quick triage |
> | **C** | **Both** | Email primary, Telegram as backup | Never miss a digest |

(Continue one step at a time until complete.)

## Config targets

Valid values for `delivery.primary_channel`: `"email"` or `"telegram"`. There is no `"local"` value — local file output is always enabled regardless of this setting. When the user does not want push delivery, keep the default `"email"` and leave both `email.send_enabled` and `telegram.send_enabled` as `false`.

### Reference config structure

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

### Field-by-field guide for the agent

| User choice | Field(s) to change | Value |
|---|---|---|
| Quick try (no Zotero) | `semantic_search.enabled` | `false` |
| Zotero personal library | `zotero.library_type` | `"user"` |
| Zotero group library | `zotero.library_type` | `"group"` |
| Library ID | `zotero.library_id` | user-provided string |
| API key | `zotero.api_key` | user-provided string, or `""` if deferred |
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

### Default values to tell users

| Setting | Default |
|---|---|
| `profile_path` | `~/.openclaw/skills/research-assist/profiles/research-interest.json` |
| `output_root` | `~/.openclaw/skills/research-assist/reports` |
| `review_generation.agent_top_n` | `5` |
| `review_generation.final_top_n` | `5` |

### CLI commands

The correct commands to run research-assist are:

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

Do not use `python -m research_assist.cli` or `python -m research_assist.main` — those do not exist.

The agent should usually edit these keys:

- `profile_path`
- `output_root`
- `review_generation.agent_top_n`
- `review_generation.final_top_n`
- `review_generation.fallback_to_system`
- `delivery.primary_channel`
- `delivery.email.*`
- `delivery.telegram.send_enabled`
- `zotero.*`
- `semantic_search.*`

The agent should not invent new config keys when an existing key already expresses the option.

## Output style for the agent

After editing config, the agent should summarize:

- what was enabled
- what stayed disabled
- which values still need secrets or local paths from the user

### Post-setup execution and verification

Based on the user's choices, the agent must execute the relevant dependency or environment setup commands itself whenever shell access is available. Do not stop at copy-paste instructions.

If a step is blocked by a missing secret, missing local service, OS limitation, or user approval requirement, say exactly which step is blocked and why. Otherwise, perform it.

| Choice | Command(s) the agent should execute | Minimum verification before leaving setup |
|---|---|---|
| Embedding: `"qwen"` (Ollama) | `ollama pull qwen3-embedding:0.6b` (if not already pulled) | confirm the model exists via `ollama list` or `ollama show qwen3-embedding:0.6b`, then initialize the backend from `config.json` |
| Embedding: `"fastembed"` | `uv sync --extra semantic-fastembed` | initialize the backend from `config.json` |
| Embedding: `"openai"` | no extra install; require `OPENAI_API_KEY` | initialize the backend from `config.json` using the provided key |
| Embedding: `"gemini"` | `uv sync --extra semantic-gemini` | initialize the backend from `config.json` using the provided key |
| Embedding: sentence-transformers | `uv sync --extra semantic-local` | initialize the backend from `config.json` |
| Fulltext extraction enabled | `uv sync --extra semantic-fulltext` | import the fulltext extraction path or run one extraction smoke check if local PDFs are available |
| Telegram delivery | set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` or shell profile | confirm both env vars are visible to the runtime |

For backend initialization, the default smoke check is:

```bash
uv run python - <<'PY'
from codex_research_assist.zotero_mcp.chroma_client import create_chroma_client
client = create_chroma_client("config.json")
print(client.embedding_function.name())
PY
```

The final setup summary must report:

- what the agent changed in `config.json`
- which install/setup commands were actually executed
- which verification checks passed
- what remains blocked, if anything

If something is not configured yet, say that directly instead of filling placeholders with guessed values.

Do not turn that summary into another setup round. Once the config is in place, move back to the user's actual literature task.

## Note on config.example.json

`config.example.json` ships with `semantic_search.enabled: true` and `embedding_model: "qwen"`. This represents the **recommended full configuration**, not a minimal starting point. When the user chooses the minimal path (no Zotero, no semantic search), the agent should set `semantic_search.enabled: false` and leave other semantic search fields at their defaults.

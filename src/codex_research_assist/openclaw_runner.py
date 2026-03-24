#!/usr/bin/env python3
"""OpenClaw skill CLI entry point for research-assist.

No FastMCP dependency — pure CLI that outputs markdown to stdout.

Usage:
    python3 -m codex_research_assist.openclaw_runner --action digest --config ~/.openclaw/skills/research-assist/config.json
    python3 -m codex_research_assist.openclaw_runner --action search --query "gaussian process" --top 5
    python3 -m codex_research_assist.openclaw_runner --action profile-refresh --config ~/.openclaw/skills/research-assist/config.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .arxiv_profile_pipeline.literature_sources import (
    build_free_text_query,
    canonical_paper_key,
    display_identifier,
    fetch_items_for_source,
    get_enabled_sources,
    source_label,
)
from .arxiv_profile_pipeline.pipeline import run_pipeline
from .controller.profile_refresh_policy import evaluate_profile_refresh_policy
from .digest_summary import write_digest_run_summary
from .email_sender import send_email
from .html_fmt import format_digest_html, format_search_html
from .ranker import rank_candidates
from .review_digest import enrich_candidates_with_system_review
from .telegram_fmt import format_digest_telegram, format_search_telegram
from .telegram_sender import send_digest
from .zotero_mcp.semantic_search import create_semantic_search

LOG = logging.getLogger("openclaw_runner")

DEFAULT_CONFIG_DIR = Path.home() / ".openclaw" / "skills" / "research-assist"
DEFAULT_CONFIG = DEFAULT_CONFIG_DIR / "config.json"


def _config_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _review_fallback_to_system(config: dict) -> bool:
    review_cfg = config.get("review_generation", {})
    if not isinstance(review_cfg, dict):
        return True
    return _config_bool(review_cfg.get("fallback_to_system", True), True)


def _semantic_search_enabled(config: dict) -> bool:
    semantic_cfg = config.get("semantic_search", {})
    if not isinstance(semantic_cfg, dict):
        return True
    return _config_bool(semantic_cfg.get("enabled", True), True)


def _telegram_send_enabled(config: dict) -> bool:
    delivery_cfg = config.get("delivery", {})
    if not isinstance(delivery_cfg, dict):
        return False
    telegram_cfg = delivery_cfg.get("telegram", {})
    if not isinstance(telegram_cfg, dict):
        return False
    return _config_bool(telegram_cfg.get("send_enabled", False), False)


def _email_config(config: dict) -> dict:
    delivery_cfg = config.get("delivery", {})
    if not isinstance(delivery_cfg, dict):
        return {}
    email_cfg = delivery_cfg.get("email", {})
    if not isinstance(email_cfg, dict):
        return {}
    return email_cfg


def _email_send_enabled(config: dict) -> bool:
    return _config_bool(_email_config(config).get("send_enabled", False), False)


def _primary_delivery_channel(config: dict) -> str:
    delivery_cfg = config.get("delivery", {})
    if not isinstance(delivery_cfg, dict):
        return "email"
    value = str(delivery_cfg.get("primary_channel", "email")).strip().lower()
    if value in {"email", "telegram"}:
        return value
    return "email"


def _telegram_fallback_on_failure(config: dict) -> bool:
    return _config_bool(_email_config(config).get("telegram_fallback_on_failure", True), True)


def _email_write_metadata(config: dict) -> bool:
    return _config_bool(_email_config(config).get("write_metadata", True), True)


def _email_subject(config: dict, *, action_name: str, date_str: str) -> str:
    email_cfg = _email_config(config)
    prefix = str(email_cfg.get("subject_prefix", "[research-assist]")).strip() or "[research-assist]"
    action_label = "Research Digest" if action_name in {"digest", "render-digest"} else "Search Results"
    return f"{prefix} {action_label} {date_str}"


def _digest_email_subject(config: dict, *, date_str: str, candidates: list[dict]) -> str:
    prefix = str(_email_config(config).get("subject_prefix", "[research-assist]")).strip() or "[research-assist]"
    short_date = _display_date(date_str)
    read_first_count = sum(
        1
        for candidate in candidates
        if str((candidate.get("review") or {}).get("recommendation") or "").strip() == "read_first"
    )
    if candidates:
        lead_title = str(candidates[0].get("paper", {}).get("title") or "top picks").strip()
        if len(lead_title) > 48:
            lead_title = lead_title[:47].rstrip() + "..."
    else:
        lead_title = "digest ready"
    return f"{prefix} {read_first_count} read-first picks | {lead_title} | {short_date}"


def _search_email_subject(config: dict, *, date_str: str, query: str, paper_count: int) -> str:
    prefix = str(_email_config(config).get("subject_prefix", "[research-assist]")).strip() or "[research-assist]"
    short_date = _display_date(date_str)
    short_query = query.strip()
    if len(short_query) > 42:
        short_query = short_query[:41].rstrip() + "..."
    return f"{prefix} {paper_count} search results | {short_query} | {short_date}"


def _email_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _display_date(date_str: str) -> str:
    if len(date_str) >= 10 and date_str[4] == "-" and date_str[7] == "-":
        return f"{date_str[5:7]}/{date_str[8:10]}"
    return date_str


def _load_profile_summary(profile_path: Path | None, config: dict) -> dict[str, object]:
    profile_labels: list[str] = []
    updated_at = ""
    if profile_path is not None and profile_path.exists():
        try:
            payload = json.loads(profile_path.read_text(encoding="utf-8"))
            updated_at = str(payload.get("updated_at") or payload.get("generated_at") or "").strip()
            for interest in payload.get("interests", []):
                if not isinstance(interest, dict):
                    continue
                if interest.get("enabled", True) is False:
                    continue
                label = str(interest.get("label") or interest.get("interest_label") or "").strip()
                if label:
                    profile_labels.append(label)
        except Exception as exc:
            LOG.warning("Failed to load profile summary from %s: %s", profile_path, exc)

    retrieval_defaults = config.get("retrieval_defaults", {})
    refresh_days = None
    if isinstance(retrieval_defaults, dict):
        value = retrieval_defaults.get("max_age_days")
        if isinstance(value, int) and value > 0:
            refresh_days = value
        elif isinstance(value, str) and value.strip().isdigit():
            refresh_days = int(value.strip())

    return {
        "labels": profile_labels[:6],
        "updated_at": updated_at,
        "refresh_days": refresh_days,
    }


def _format_digest_email_body(
    candidates: list[dict],
    *,
    date_str: str,
    html_path: Path,
    profile_summary: dict[str, object] | None = None,
) -> tuple[str, str]:
    read_first_count = sum(
        1
        for candidate in candidates
        if str((candidate.get("review") or {}).get("recommendation") or "").strip() == "read_first"
    )
    skim_count = sum(
        1
        for candidate in candidates
        if str((candidate.get("review") or {}).get("recommendation") or "").strip() == "skim"
    )
    themes = sorted(
        {
            str(tag)
            for candidate in candidates
            for tag in ((candidate.get("triage") or {}).get("matched_interest_labels") or [])
            if str(tag).strip()
        }
    )
    lead_title = str(candidates[0].get("paper", {}).get("title") or "Digest attached").strip() if candidates else "Digest attached"
    lead_reason = ""
    if candidates:
        lead_reason = str((candidates[0].get("review") or {}).get("why_it_matters") or "").strip()
    if len(lead_reason) > 140:
        lead_reason = lead_reason[:139].rstrip() + "..."
    theme_line = ", ".join(themes[:3]) if themes else "No strong theme labels"
    short_date = _display_date(date_str)
    profile_summary = profile_summary or {}
    profile_labels = [str(label) for label in (profile_summary.get("labels") or []) if str(label).strip()]
    profile_updated_at = _display_date(str(profile_summary.get("updated_at") or "")[:10]) if profile_summary.get("updated_at") else "unknown"
    refresh_days = profile_summary.get("refresh_days")
    refresh_text = f"every {refresh_days} days" if isinstance(refresh_days, int) and refresh_days > 0 else "manual"
    profile_line = ", ".join(profile_labels[:4]) if profile_labels else "No active profile labels"

    plain = "\n".join(
        [
            f"Research Digest | {short_date}",
            "",
            f"Selected papers: {len(candidates)}",
            f"Read first: {read_first_count}",
            f"Skim: {skim_count}",
            f"Themes: {theme_line}",
            "",
            f"Profile: {profile_line}",
            f"Profile updated: {profile_updated_at}",
            f"Refresh cadence: {refresh_text}",
            "",
            f"Lead paper: {lead_title}",
            lead_reason or "The attached HTML digest contains the full reading cards.",
            "",
            f"Attachment: {html_path.name}",
            "Open the attached HTML file in a browser for the full styled digest.",
        ]
    )

    html = f"""\
<html>
  <body style="margin:0;padding:0;background:#f6ede1;color:#2f241d;font-family:Arial,'Helvetica Neue',sans-serif;">
    <div style="max-width:640px;margin:0 auto;padding:24px 18px;">
      <div style="background:#fffaf3;border:1px solid #e6d6c4;border-radius:18px;padding:24px 22px;">
        <div style="font-size:12px;letter-spacing:1.4px;text-transform:uppercase;color:#8f4b2e;font-weight:700;margin-bottom:12px;">Research Assist Digest</div>
        <h1 style="margin:0 0 10px;font-size:30px;line-height:1.1;color:#2f241d;">Your digest is ready</h1>
        <p style="margin:0 0 18px;font-size:15px;line-height:1.6;color:#5a4a3e;">Quick triage here. Open the attached HTML file for the full card view.</p>
        <div style="border-radius:16px;background:#f9f2e8;border:1px solid #ecd8c3;padding:16px 16px 14px;margin:0 0 18px;">
          <div style="font-size:12px;letter-spacing:1.2px;text-transform:uppercase;color:#8f4b2e;font-weight:700;margin-bottom:8px;">Current profile</div>
          <div style="font-size:14px;line-height:1.6;color:#2f241d;font-weight:600;margin-bottom:10px;">{_email_escape(profile_line)}</div>
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%;">
            <tr>
              <td style="width:50%;padding:0 8px 0 0;vertical-align:top;">
                <div style="font-size:11px;letter-spacing:1.1px;text-transform:uppercase;color:#8a7465;margin-bottom:4px;">Updated</div>
                <div style="font-size:15px;line-height:1.35;color:#2f241d;font-weight:700;">{_email_escape(profile_updated_at)}</div>
              </td>
              <td style="width:50%;padding:0 0 0 8px;vertical-align:top;">
                <div style="font-size:11px;letter-spacing:1.1px;text-transform:uppercase;color:#8a7465;margin-bottom:4px;">Refresh</div>
                <div style="font-size:15px;line-height:1.35;color:#2f241d;font-weight:700;">{_email_escape(refresh_text)}</div>
              </td>
            </tr>
          </table>
        </div>
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%;margin:0 0 18px;">
          <tr>
            <td style="width:50%;padding:0 8px 8px 0;">
              <div style="border-radius:14px;background:#f7eee3;padding:14px 16px;border:1px solid #ecd8c3;min-height:96px;">
                <div style="font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:#8a7465;">Selected</div>
                <div style="font-size:28px;line-height:1.05;color:#2f241d;font-weight:700;">{len(candidates)}</div>
                <div style="font-size:12px;line-height:1.35;color:#5a4a3e;margin-top:6px;">Kept picks</div>
              </div>
            </td>
            <td style="width:50%;padding:0 0 8px 8px;">
              <div style="border-radius:14px;background:#f4e7dc;padding:14px 16px;border:1px solid #ecd8c3;min-height:96px;">
                <div style="font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:#8a7465;">Read First</div>
                <div style="font-size:28px;line-height:1.05;color:#8f4b2e;font-weight:700;">{read_first_count}</div>
                <div style="font-size:12px;line-height:1.35;color:#5a4a3e;margin-top:6px;">Start here</div>
              </div>
            </td>
          </tr>
          <tr>
            <td style="width:50%;padding:8px 8px 0 0;">
              <div style="border-radius:14px;background:#f5f3ec;padding:14px 16px;border:1px solid #e2ddd2;min-height:96px;">
                <div style="font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:#8a7465;">Skim</div>
                <div style="font-size:28px;line-height:1.05;color:#6a664e;font-weight:700;">{skim_count}</div>
                <div style="font-size:12px;line-height:1.35;color:#5a4a3e;margin-top:6px;">Fast scan</div>
              </div>
            </td>
            <td style="width:50%;padding:8px 0 0 8px;">
              <div style="border-radius:14px;background:#faf5ee;padding:14px 16px;border:1px solid #ecd8c3;min-height:96px;">
                <div style="font-size:11px;letter-spacing:1.2px;text-transform:uppercase;color:#8a7465;">Themes</div>
                <div style="font-size:28px;line-height:1.05;color:#2f241d;font-weight:700;">{len(themes) if themes else 0}</div>
                <div style="font-size:12px;line-height:1.35;color:#5a4a3e;margin-top:6px;">Map lanes</div>
              </div>
            </td>
          </tr>
        </table>
        <div style="border-left:3px solid #bd6a42;padding-left:14px;margin:0 0 18px;">
          <div style="font-size:12px;letter-spacing:1.2px;text-transform:uppercase;color:#8f4b2e;font-weight:700;margin-bottom:6px;">Lead paper</div>
          <div style="font-size:20px;line-height:1.25;color:#2f241d;font-weight:700;margin-bottom:6px;">{_email_escape(lead_title)}</div>
          <div style="font-size:14px;line-height:1.6;color:#5a4a3e;">{_email_escape(lead_reason or 'Open the attached HTML digest for the full reading cards and rationale.')}</div>
        </div>
        <div style="font-size:14px;line-height:1.65;color:#5a4a3e;margin-bottom:8px;">Themes touched in this batch: {_email_escape(theme_line)}.</div>
        <div style="font-size:14px;line-height:1.65;color:#5a4a3e;">Attachment: <strong>{_email_escape(html_path.name)}</strong>. Open it in a browser for the full styled digest.</div>
      </div>
    </div>
  </body>
</html>"""
    return plain, html


def _format_search_email_body(*, query: str, papers: list[dict], date_str: str, html_path: Path) -> tuple[str, str]:
    top_title = str(papers[0].get("title") or "Search results attached").strip() if papers else "Search results attached"
    short_date = _display_date(date_str)
    plain = "\n".join(
        [
            f"Search Results | {short_date}",
            "",
            f"Query: {query}",
            f"Results: {len(papers)}",
            f"Top hit: {top_title}",
            "",
            f"Attachment: {html_path.name}",
            "Open the attached HTML file in a browser for the full styled results.",
        ]
    )
    html = f"""\
<html>
  <body style="margin:0;padding:0;background:#f6ede1;color:#2f241d;font-family:Arial,'Helvetica Neue',sans-serif;">
    <div style="max-width:640px;margin:0 auto;padding:24px 18px;">
      <div style="background:#fffaf3;border:1px solid #e6d6c4;border-radius:18px;padding:24px 22px;">
        <div style="font-size:12px;letter-spacing:1.4px;text-transform:uppercase;color:#8f4b2e;font-weight:700;margin-bottom:12px;">Research Assist Search</div>
        <h1 style="margin:0 0 10px;font-size:30px;line-height:1.1;color:#2f241d;">Search results are ready</h1>
        <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#5a4a3e;">Query: <strong>{_email_escape(query)}</strong></p>
        <p style="margin:0 0 10px;font-size:14px;line-height:1.65;color:#5a4a3e;">Found <strong>{len(papers)}</strong> results. Top hit: <strong>{_email_escape(top_title)}</strong>.</p>
        <p style="margin:0;font-size:14px;line-height:1.65;color:#5a4a3e;">Attachment: <strong>{_email_escape(html_path.name)}</strong>. Open it in a browser for the full styled results.</p>
      </div>
    </div>
  </body>
</html>"""
    return plain, html


def _send_email_delivery(
    *,
    config: dict,
    subject: str,
    body_text: str,
    body_html: str | None,
    html_path: Path,
    output_json_path: Path | None,
    extra_attachments: list[Path] | None = None,
) -> tuple[str, Path | None]:
    if not _email_send_enabled(config):
        return "disabled by config", None

    email_cfg = _email_config(config)
    attachments = []
    if _config_bool(email_cfg.get("attach_html", True), True):
        attachments.append(html_path)
    if extra_attachments:
        attachments.extend(extra_attachments)

    result = send_email(
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        sender=str(email_cfg.get("sender", "")).strip(),
        recipients=email_cfg.get("recipients", []),
        smtp_server=str(email_cfg.get("smtp_server", "")).strip(),
        smtp_port=int(email_cfg.get("smtp_port", 465)),
        smtp_user=str(email_cfg.get("smtp_user", "")).strip(),
        smtp_pass=str(email_cfg.get("smtp_pass", "")).strip(),
        tls_mode=str(email_cfg.get("tls_mode", "ssl")).strip(),
        timeout=int(email_cfg.get("timeout", 20)),
        attachments=attachments,
    )

    email_json_path = None
    if output_json_path is not None and _email_write_metadata(config):
        metadata = {
            "subject": result["subject"],
            "sender": result["sender"],
            "recipients": result["recipients"],
            "attachments": result["attachments"],
        }
        output_json_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        email_json_path = output_json_path

    return "sent ✓", email_json_path


def _send_telegram_delivery(
    *,
    config: dict,
    summary_text: str,
    html_path: Path,
    output_json_path: Path | None,
) -> tuple[str, Path | None]:
    if not _telegram_send_enabled(config):
        return "disabled by config", None

    telegram_json_path = None
    if output_json_path is not None:
        output_json_path.write_text(
            json.dumps(
                {
                    "summary": summary_text,
                    "html_path": html_path.as_posix(),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        telegram_json_path = output_json_path

    send_digest(summary_text, html_path)
    return "sent ✓", telegram_json_path


def _deliver_report(
    *,
    config: dict,
    preferred_channel: str,
    subject: str,
    summary_text: str,
    email_body_text: str,
    email_body_html: str | None,
    html_path: Path,
    email_json_path: Path | None,
    telegram_json_path: Path | None,
    extra_email_attachments: list[Path] | None = None,
) -> tuple[str, Path | None, str, Path | None]:
    email_status = "not attempted"
    telegram_status = "not attempted"
    final_email_json_path = None
    final_telegram_json_path = None

    if preferred_channel == "telegram":
        try:
            telegram_status, final_telegram_json_path = _send_telegram_delivery(
                config=config,
                summary_text=summary_text,
                html_path=html_path,
                output_json_path=telegram_json_path,
            )
        except Exception as exc:
            LOG.warning("Failed to send via Telegram: %s", exc)
            telegram_status = f"failed — {exc}"
        if telegram_status == "disabled by config" and _email_send_enabled(config):
            try:
                email_status, final_email_json_path = _send_email_delivery(
                    config=config,
                    subject=subject,
                    body_text=email_body_text,
                    body_html=email_body_html,
                    html_path=html_path,
                    output_json_path=email_json_path,
                    extra_attachments=extra_email_attachments,
                )
            except Exception as exc:
                LOG.warning("Failed to send via email: %s", exc)
                email_status = f"failed — {exc}"
        return email_status, final_email_json_path, telegram_status, final_telegram_json_path

    try:
        email_status, final_email_json_path = _send_email_delivery(
            config=config,
            subject=subject,
            body_text=email_body_text,
            body_html=email_body_html,
            html_path=html_path,
            output_json_path=email_json_path,
            extra_attachments=extra_email_attachments,
        )
    except Exception as exc:
        LOG.warning("Failed to send via email: %s", exc)
        email_status = f"failed — {exc}"

    should_fallback = (email_status.startswith("failed") and _telegram_fallback_on_failure(config)) or (
        email_status == "disabled by config" and _telegram_send_enabled(config)
    )
    should_use_telegram_primary = preferred_channel == "telegram"
    if should_use_telegram_primary or should_fallback:
        try:
            telegram_status, final_telegram_json_path = _send_telegram_delivery(
                config=config,
                summary_text=summary_text,
                html_path=html_path,
                output_json_path=telegram_json_path,
            )
        except Exception as exc:
            LOG.warning("Failed to send via Telegram: %s", exc)
            telegram_status = f"failed — {exc}"
    else:
        if _telegram_send_enabled(config):
            telegram_status = "backup not used"
        else:
            telegram_status = "disabled by config"

    return email_status, final_email_json_path, telegram_status, final_telegram_json_path


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def expand_path(path_str: str) -> Path:
    return Path(path_str).expanduser().resolve()


def get_profile_path(config: dict) -> Path:
    profile_path_str = config.get("profile_path", "~/.openclaw/skills/research-assist/profiles/research-interest.json")
    return expand_path(profile_path_str)


def get_output_root(config: dict) -> Path:
    output_root_str = config.get("output_root", "~/.openclaw/skills/research-assist/reports")
    return expand_path(output_root_str)


def _toml_quote(value: str) -> str:
    """Escape a string for TOML double-quoted value."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _safe_positive_int(value: object, default: int) -> int:
    """Best-effort conversion for integer-like config values."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value if value > 0 else default
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            parsed = int(stripped)
            return parsed if parsed > 0 else default
    return default


def create_temp_toml_config(config: dict, profile_path: Path, output_root: Path) -> Path:
    """Write a minimal TOML config consumed by run_pipeline / evaluate_profile_refresh_policy."""
    retrieval_defaults = config.get("retrieval_defaults", {})
    max_age_days = _safe_positive_int(
        retrieval_defaults.get("max_age_days", 7) if isinstance(retrieval_defaults, dict) else 7,
        7,
    )

    toml_lines = [
        f"profile_path = {_toml_quote(profile_path.as_posix())}",
        f"output_root = {_toml_quote(output_root.as_posix())}",
        "",
        "[artifacts]",
        "write_candidate_markdown = false",
        "",
        "[controller]",
        'mode = "internal-staged"',
        "",
        "[controller.profile_refresh]",
        "enabled = true",
        f"max_age_days = {max_age_days}",
        "refresh_if_missing = true",
        "",
    ]

    # Forward literature_sources so non-CLI callers get multi-source behaviour
    lit_sources = config.get("literature_sources")
    if isinstance(lit_sources, dict):
        enabled = lit_sources.get("enabled", ["arxiv"])
        if isinstance(enabled, list):
            enabled_str = ", ".join(_toml_quote(str(s)) for s in enabled)
            toml_lines.append("[literature_sources]")
            toml_lines.append(f"enabled = [{enabled_str}]")
            toml_lines.append("")
            for provider in ("openalex", "semantic_scholar"):
                pcfg = lit_sources.get(provider)
                if isinstance(pcfg, dict):
                    toml_lines.append(f"[literature_sources.{provider}]")
                    for k, v in pcfg.items():
                        toml_lines.append(f"{k} = {_toml_quote(str(v or ''))}")
                    toml_lines.append("")

    toml_text = "\n".join(toml_lines)

    temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".toml", encoding="utf-8", delete=False)
    temp_file.write(toml_text)
    temp_file.close()
    return Path(temp_file.name)


def _load_candidates_from_digest(digest_json_path: Path) -> list[dict]:
    digest_data = json.loads(digest_json_path.read_text(encoding="utf-8"))
    candidate_paths = digest_data.get("candidate_paths", [])
    candidates = []
    for candidate_path in candidate_paths:
        try:
            candidate_data = json.loads(Path(candidate_path).read_text(encoding="utf-8"))
            candidates.append(candidate_data)
        except Exception as exc:
            LOG.warning("Failed to load candidate %s: %s", candidate_path, exc)
    return candidates


def _digest_date_str(candidates: list[dict]) -> str:
    for candidate in candidates:
        generated_at = str(candidate.get("candidate", {}).get("generated_at") or "").strip()
        if len(generated_at) >= 10:
            return generated_at[:10]
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _nearest_zotero_lines(candidate: dict) -> list[str]:
    scores = candidate.get("_scores", {})
    review = candidate.get("review", {})
    neighbors = scores.get("semantic_neighbors") if isinstance(scores, dict) else None
    titles: list[str] = []
    if isinstance(neighbors, list) and neighbors:
        cleaned = [str(item.get("title") or "").strip() for item in neighbors if isinstance(item, dict)]
        cleaned = [title for title in cleaned if title]
        if len(cleaned) >= 2 and len(cleaned[0]) + len(cleaned[1]) <= 72:
            titles = cleaned[:2]
        elif cleaned:
            titles = cleaned[:1]
    if not titles:
        top_title = str((scores or {}).get("semantic_top_title") or "").strip()
        if top_title:
            titles = [top_title]
    if not titles and isinstance(review, dict):
        zotero_comparison = review.get("zotero_comparison")
        if isinstance(zotero_comparison, dict):
            related_items = zotero_comparison.get("related_items")
            if isinstance(related_items, list):
                cleaned = [str(item.get("title") or "").strip() for item in related_items if isinstance(item, dict)]
                cleaned = [title for title in cleaned if title]
                if len(cleaned) >= 2 and len(cleaned[0]) + len(cleaned[1]) <= 72:
                    titles = cleaned[:2]
                elif cleaned:
                    titles = cleaned[:1]
            summary = str(zotero_comparison.get("summary") or "").strip()
            if titles:
                return [f"**Nearest Zotero:** {'; '.join(titles)}"]
            if summary:
                return [f"**Nearest Zotero:** {summary}"]
    if titles:
        return [f"**Nearest Zotero:** {'; '.join(titles)}"]
    return []


def _candidate_json_paths(candidates: list[dict]) -> list[Path]:
    paths: list[Path] = []
    for candidate in candidates:
        json_path = candidate.get("candidate", {}).get("json_path")
        if isinstance(json_path, str) and json_path:
            paths.append(Path(json_path).expanduser().resolve())
    return paths


def _persist_ranked_candidate_paths(digest_json_path: Path, candidates: list[dict]) -> None:
    payload = json.loads(digest_json_path.read_text(encoding="utf-8"))
    payload.setdefault("retrieved_candidate_count", payload.get("candidate_count"))
    payload["selected_candidate_count"] = len(candidates)
    payload["candidate_paths"] = [path.as_posix() for path in _candidate_json_paths(candidates)]
    digest_json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _selected_candidate_limit(config: dict) -> int | None:
    review_cfg = config.get("review_generation", {})
    if not isinstance(review_cfg, dict):
        return None
    value = review_cfg.get("agent_top_n")
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        limit = int(value.strip())
        if limit > 0:
            return limit
    return None


def _final_digest_limit(config: dict) -> int | None:
    review_cfg = config.get("review_generation", {})
    if not isinstance(review_cfg, dict):
        return 5
    value = review_cfg.get("final_top_n", 5)
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        limit = int(value.strip())
        if limit > 0:
            return limit
    return 5


def _filter_final_digest_candidates(candidates: list[dict], *, final_limit: int | None) -> list[dict]:
    selected = [
        candidate
        for candidate in candidates
        if isinstance(candidate.get("review"), dict) and candidate["review"].get("selected_for_digest") is True
    ]
    if selected:
        if final_limit is not None and len(selected) > final_limit:
            return selected[:final_limit]
        return selected
    return candidates


def _render_digest_outputs(
    digest_json_path: Path,
    candidates: list[dict],
    output_root: Path,
    fmt: str,
    config: dict,
    *,
    action_name: str,
    profile_path: Path | None,
) -> str:
    date_str = _digest_date_str(candidates)

    html_content = format_digest_html(candidates, date_str)
    html_path = output_root / f"digest-{date_str}.html"
    html_path.write_text(html_content, encoding="utf-8")
    LOG.info("Wrote HTML digest to %s", html_path)

    email_json_path: Path | None = None
    telegram_json_path: Path | None = None

    if fmt in {"telegram", "delivery"}:
        telegram_summary = format_digest_telegram(candidates, date_str)
        profile_summary = _load_profile_summary(profile_path, config)
        email_body_text, email_body_html = _format_digest_email_body(
            candidates,
            date_str=date_str,
            html_path=html_path,
            profile_summary=profile_summary,
        )
        email_json_path = output_root / f"digest-{date_str}.email.json"
        telegram_json_path = output_root / f"digest-{date_str}.telegram.json"
        email_status, email_json_path, telegram_status, telegram_json_path = _deliver_report(
            config=config,
            preferred_channel=_primary_delivery_channel(config),
            subject=_digest_email_subject(config, date_str=date_str, candidates=candidates),
            summary_text=telegram_summary,
            email_body_text=email_body_text,
            email_body_html=email_body_html,
            html_path=html_path,
            email_json_path=email_json_path,
            telegram_json_path=telegram_json_path,
            extra_email_attachments=[digest_json_path] if _config_bool(_email_config(config).get("attach_digest_json", False), False) else None,
        )

        lines = [f"Found {len(candidates)} papers, top 5:"]
        for i, candidate in enumerate(candidates[:5], 1):
            paper = candidate.get("paper", {})
            title = paper.get("title", "Untitled")
            arxiv_id = paper.get("identifiers", {}).get("arxiv_id", "")
            scores = candidate.get("_scores", {})
            score = scores.get("total", 0.0)
            lines.append(f"{i}. [{score:.2f}] {title[:60]}... ({arxiv_id})")
        file_names = [html_path.name]
        if email_json_path is not None:
            file_names.append(email_json_path.name)
        if telegram_json_path is not None:
            file_names.append(telegram_json_path.name)
        lines.append(f"Files: {', '.join(file_names)}")
        summary_path = write_digest_run_summary(
            action=action_name,
            digest_json_path=digest_json_path,
            candidate_paths=_candidate_json_paths(candidates),
            html_path=html_path,
            email_json_path=email_json_path,
            telegram_json_path=telegram_json_path,
            output_root=output_root,
            profile_path=profile_path,
        )
        lines.append(f"Summary: {summary_path.name}")
        lines.append(f"Primary channel: {_primary_delivery_channel(config)}")
        lines.append(f"Email: {email_status}")
        lines.append(f"Telegram: {telegram_status}")
        return "\n".join(lines)

    summary_path = write_digest_run_summary(
        action=action_name,
        digest_json_path=digest_json_path,
        candidate_paths=_candidate_json_paths(candidates),
        html_path=html_path,
        email_json_path=None,
        telegram_json_path=None,
        output_root=output_root,
        profile_path=profile_path,
    )
    LOG.info("Wrote digest run summary to %s", summary_path)
    return format_digest_markdown(digest_json_path, candidates)


def format_digest_markdown(digest_json_path: Path, candidates: list[dict]) -> str:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"# Research Digest {date_str}", ""]

    if not candidates:
        lines.append("No new papers found matching your research interests.")
        return "\n".join(lines)

    lines.append(f"Found {len(candidates)} new papers:")
    lines.append("")

    for i, candidate in enumerate(candidates, 1):
        paper = candidate.get("paper", {})
        triage = candidate.get("triage", {})
        review = candidate.get("review", {})
        title = paper.get("title", "Untitled")
        authors = paper.get("authors", [])
        provider = source_label(candidate.get("source", {}).get("provider"))
        display_id = paper.get("identifiers", {}).get("display", "")
        url = paper.get("identifiers", {}).get("url", "")
        abstract = paper.get("abstract", "")
        matched_interests = triage.get("matched_interest_labels", [])

        author_str = ", ".join(authors[:3])
        if len(authors) > 3:
            author_str += " et al."

        lines.append(f"## {i}. {title}")
        if author_str:
            lines.append(f"**Authors:** {author_str}")
        lines.append(f"**Source:** {provider}")
        if display_id:
            lines.append(f"**Identifier:** {display_id}")
        if url:
            lines.append(f"**URL:** {url}")
        if matched_interests:
            lines.append(f"**Matched Interests:** {', '.join(matched_interests)}")
        scores = candidate.get("_scores")
        if scores:
            lines.append(
                f"**Score:** {scores['total']:.2f} "
                f"(map={scores.get('map_match', 0.0):.2f} zotero={scores.get('zotero_semantic', 0.0):.2f})"
            )
        if review.get("recommendation"):
            lines.append(f"**Recommendation:** {review['recommendation']}")
        if review.get("why_it_matters"):
            lines.append(f"**Why It Matters:** {review['why_it_matters']}")
        if review.get("quick_takeaways"):
            lines.append(f"**Quick Takeaways:** {'; '.join(review['quick_takeaways'])}")
        if review.get("caveats"):
            lines.append(f"**Caveats:** {'; '.join(review['caveats'])}")
        lines.extend(_nearest_zotero_lines(candidate))
        if abstract:
            abstract_preview = abstract[:300] + ("..." if len(abstract) > 300 else "")
            lines.append(f"\n**Original Abstract:** {abstract_preview}")
        lines.append("")

    lines.append("---")
    lines.append(f"Full digest: {digest_json_path.as_posix()}")
    return "\n".join(lines)


def format_search_markdown(papers: list[dict], query: str) -> str:
    lines = [f"# Literature Search: \"{query}\"", ""]

    if not papers:
        lines.append("No results found.")
        return "\n".join(lines)

    lines.append(f"Found {len(papers)} results:")
    lines.append("")

    for i, paper in enumerate(papers, 1):
        title = paper.get("title", "Untitled")
        authors = paper.get("authors", [])
        provider = source_label(paper.get("provider"))
        display_id = paper.get("paper_id_display") or display_identifier(paper)
        url = paper.get("html_url", "")
        abstract = paper.get("summary", "")

        author_str = ", ".join(authors[:3])
        if len(authors) > 3:
            author_str += " et al."

        lines.append(f"## {i}. {title}")
        if author_str:
            lines.append(f"**Authors:** {author_str}")
        lines.append(f"**Source:** {provider}")
        if display_id:
            lines.append(f"**Identifier:** {display_id}")
        if url:
            lines.append(f"**URL:** {url}")
        if abstract:
            abstract_preview = abstract[:250] + ("..." if len(abstract) > 250 else "")
            lines.append(f"\n**Original Abstract:** {abstract_preview}")
        lines.append("")

    return "\n".join(lines)


def format_profile_refresh_markdown(policy_result: dict) -> str:
    lines = ["# Profile Refresh Status", ""]
    profile_path = policy_result.get("profile_path", "")
    profile_exists = policy_result.get("profile_exists", False)
    profile_age_days = policy_result.get("profile_age_days")
    refresh_info = policy_result.get("controller", {}).get("profile_refresh", {})
    required = refresh_info.get("required", False)
    reason = refresh_info.get("reason", "unknown")

    lines.append(f"**Profile Path:** {profile_path}")
    lines.append(f"**Profile Exists:** {profile_exists}")
    if profile_age_days is not None:
        lines.append(f"**Profile Age:** {profile_age_days:.1f} days")
    lines.append(f"**Refresh Required:** {required}")
    lines.append(f"**Reason:** {reason}")
    lines.append("")
    if required:
        lines.append("The profile needs to be refreshed.")
        lines.append("")
        lines.append("Use the OpenClaw controller or agent workflow to regenerate the live profile from Zotero evidence.")
    else:
        lines.append("The profile is up to date.")
    return "\n".join(lines)


def action_digest(config: dict, fmt: str = "markdown", *, config_path: Path | None = None) -> str:
    profile_path = get_profile_path(config)
    output_root = get_output_root(config)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    temp_toml_path = create_temp_toml_config(config, profile_path, output_root)
    profile: dict | None = None

    try:
        LOG.info("Checking profile refresh policy...")
        policy_result = evaluate_profile_refresh_policy(config_path=temp_toml_path, profile_override=None)
        refresh_required = policy_result.get("controller", {}).get("profile_refresh", {}).get("required", False)
        if refresh_required:
            reason = policy_result.get("controller", {}).get("profile_refresh", {}).get("reason", "unknown")
            LOG.warning("Profile refresh required: %s", reason)
            LOG.warning("Proceeding with retrieval using existing profile (if available)")

        LOG.info("Running literature retrieval pipeline...")
        pipeline_config_path = config_path or temp_toml_path
        result = run_pipeline(config_path=pipeline_config_path, profile_path=profile_path, write_candidate_markdown_override=False)
        digest_json_path = Path(result["digest_json_path"])
        candidate_count = result["candidate_count"]
        LOG.info("Retrieved %d candidates", candidate_count)

        candidates = _load_candidates_from_digest(digest_json_path)

        # Rank candidates using the profile
        if candidates and profile_path.exists():
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            # Load seen IDs from the same state path the pipeline uses
            profile_defaults = profile.get("retrieval_defaults", {})
            state_path_str = profile_defaults.get("state_path", ".state/arxiv_profile_seen.json")
            state_path = Path(state_path_str)
            if not state_path.is_absolute():
                state_path = Path.cwd() / state_path
            history_ids: set[str] = set()
            if state_path.exists():
                try:
                    seen_data = json.loads(state_path.read_text(encoding="utf-8"))
                    history_ids = set(seen_data.get("ids", []))
                except Exception:
                    pass
            semantic_search_fn = None
            if config_path is not None and _semantic_search_enabled(config):
                try:
                    semantic_search = create_semantic_search(config_path=config_path)

                    def _search(query_text: str, limit: int) -> dict:
                        return semantic_search.search(query=query_text, limit=limit)

                    semantic_search_fn = _search
                except Exception as exc:
                    LOG.warning("Semantic ranking unavailable: %s", exc)

            candidates = rank_candidates(
                candidates,
                profile,
                history_ids,
                semantic_search_fn=semantic_search_fn,
            )
            LOG.info("Ranked %d candidates", len(candidates))

        selected_limit = _selected_candidate_limit(config)
        if selected_limit is not None and len(candidates) > selected_limit:
            candidates = candidates[:selected_limit]
            LOG.info("Trimmed ranked candidates to top %d", len(candidates))

        if candidates and _review_fallback_to_system(config):
            candidates = enrich_candidates_with_system_review(candidates, profile, persist_json=True)
            LOG.info("Enriched %d candidates with system review notes", len(candidates))
        if candidates:
            _persist_ranked_candidate_paths(digest_json_path, candidates)
        return _render_digest_outputs(
            digest_json_path,
            candidates,
            output_root,
            fmt,
            config,
            action_name="digest",
            profile_path=profile_path,
        )
    finally:
        try:
            temp_toml_path.unlink()
        except Exception:
            pass


def action_search(query: str, top: int = 5, fmt: str = "markdown", config: dict | None = None) -> str:
    config = config or {}
    enabled_sources = get_enabled_sources(config)
    LOG.info("Searching literature for %s via %s", query, ", ".join(enabled_sources))
    unique_papers: dict[str, dict] = {}
    for source in enabled_sources:
        provider_query = build_free_text_query(source, query)
        try:
            papers = fetch_items_for_source(
                source,
                provider_query,
                max_results=top,
                page_size=max(10, top),
                since_days=0,
                sort_by="relevance",
                sort_order="descending",
                config=config,
            )
        except Exception as exc:
            LOG.warning("Search source %s unavailable: %s", source, exc)
            continue
        for paper in papers:
            item_key = canonical_paper_key(paper)
            if item_key in unique_papers:
                continue
            paper["paper_id_display"] = display_identifier(paper)
            unique_papers[item_key] = paper
    papers = list(unique_papers.values())
    LOG.info("Found %d results", len(papers))

    papers_subset = papers[:top]

    if fmt in {"telegram", "delivery"}:
        telegram_summary = format_search_telegram(papers_subset, query)
        html_content = format_search_html(papers_subset, query)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        search_output_dir = Path.home() / ".openclaw" / "skills" / "research-assist" / "reports" / "search"
        search_output_dir.mkdir(parents=True, exist_ok=True)

        html_path = search_output_dir / f"search-{date_str}.html"
        html_path.write_text(html_content, encoding="utf-8")
        LOG.info("Wrote HTML search results to %s", html_path)

        telegram_json_path = search_output_dir / f"search-{date_str}.telegram.json"
        email_json_path = search_output_dir / f"search-{date_str}.email.json"
        email_body_text, email_body_html = _format_search_email_body(query=query, papers=papers_subset, date_str=date_str, html_path=html_path)
        email_status, email_json_path, telegram_status, telegram_json_path = _deliver_report(
            config=config or {},
            preferred_channel=_primary_delivery_channel(config or {}),
            subject=_search_email_subject(config or {}, date_str=date_str, query=query, paper_count=len(papers_subset)),
            summary_text=format_search_markdown(papers_subset, query),
            email_body_text=email_body_text,
            email_body_html=email_body_html,
            html_path=html_path,
            email_json_path=email_json_path,
            telegram_json_path=telegram_json_path,
            extra_email_attachments=None,
        )

        lines = [f"Found {len(papers_subset)} results for \"{query}\":"]
        for i, paper in enumerate(papers_subset, 1):
            title = paper.get("title", "Untitled")
            display_id = paper.get("paper_id_display") or display_identifier(paper)
            provider = source_label(paper.get("provider"))
            suffix = f"{provider} | {display_id}" if display_id else provider
            lines.append(f"{i}. {title[:60]}... ({suffix})")
        file_names = [html_path.name]
        if email_json_path is not None:
            file_names.append(email_json_path.name)
        if telegram_json_path is not None:
            file_names.append(telegram_json_path.name)
        lines.append(f"Files: {', '.join(file_names)}")
        lines.append(f"Primary channel: {_primary_delivery_channel(config or {})}")
        lines.append(f"Email: {email_status}")
        lines.append(f"Telegram: {telegram_status}")
        return "\n".join(lines)

    return format_search_markdown(papers_subset, query)


def action_render_digest(config: dict, digest_json: Path, fmt: str = "markdown") -> str:
    output_root = get_output_root(config)
    output_root.mkdir(parents=True, exist_ok=True)
    digest_json_path = digest_json.expanduser().resolve()
    candidates = _load_candidates_from_digest(digest_json_path)
    candidates = _filter_final_digest_candidates(candidates, final_limit=_final_digest_limit(config))
    profile_path = get_profile_path(config)
    return _render_digest_outputs(
        digest_json_path,
        candidates,
        output_root,
        fmt,
        config,
        action_name="render-digest",
        profile_path=profile_path,
    )


def action_profile_refresh(config: dict) -> str:
    profile_path = get_profile_path(config)
    output_root = get_output_root(config)
    temp_toml_path = create_temp_toml_config(config, profile_path, output_root)

    try:
        LOG.info("Evaluating profile refresh policy...")
        policy_result = evaluate_profile_refresh_policy(config_path=temp_toml_path, profile_override=None)
        return format_profile_refresh_markdown(policy_result)
    finally:
        try:
            temp_toml_path.unlink()
        except Exception:
            pass


def action_sync_index(config: dict, *, config_path: Path | None = None, force_rebuild: bool = False) -> str:
    """Sync Zotero items into the semantic search index via API."""
    LOG.info("Syncing Zotero items into semantic search index via API...")
    if not _semantic_search_enabled(config):
        return "Semantic search is disabled in config. Set semantic_search.enabled=true first."
    try:
        semantic_search = create_semantic_search(config_path=config_path)
    except Exception as exc:
        return f"Failed to initialize semantic search: {exc}"

    zotero_cfg = config.get("zotero", {})
    scope = str(zotero_cfg.get("scope_collection") or "").strip()
    collection_names = [scope] if scope else None

    result = semantic_search.sync_from_api(
        collection_names=collection_names,
        force_rebuild=force_rebuild,
    )
    lines = [
        "Sync complete",
        f"  Source: {result.get('source', 'api')}",
        f"  Items fetched: {result.get('total_items', 0)}",
        f"  Items indexed: {result.get('processed_items', 0)}",
        f"  Scope: {', '.join(result.get('scope_collections', ['all']))}",
        f"  Embedding model: {result.get('embedding_model', 'unknown')}",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Codex Research Assist OpenClaw Runner")
    parser.add_argument("--action", required=True, choices=["digest", "search", "profile-refresh", "render-digest", "sync-index"], help="Action to perform")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Path to config.json")
    parser.add_argument("--query", type=str, default="", help="Search query (for search action)")
    parser.add_argument("--digest-json", type=Path, default=None, help="Path to digest manifest JSON (for render-digest action)")
    parser.add_argument("--top", type=int, default=5, help="Number of results (for search action)")
    parser.add_argument("--format", choices=["markdown", "telegram", "delivery"], default="markdown", help="Output format (default: markdown)")
    parser.add_argument("--force-rebuild", action="store_true", help="Force rebuild semantic index (for sync-index action)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(name)s %(levelname)s: %(message)s", stream=sys.stderr)

    try:
        if args.action == "digest":
            config = load_config(args.config)
            output = action_digest(config, fmt=args.format, config_path=args.config)
        elif args.action == "search":
            if not args.query:
                parser.error("--query required for search action")
            config = load_config(args.config) if args.config.exists() else {}
            output = action_search(args.query, args.top, fmt=args.format, config=config)
        elif args.action == "render-digest":
            if args.digest_json is None:
                parser.error("--digest-json required for render-digest action")
            config = load_config(args.config)
            output = action_render_digest(config, args.digest_json, fmt=args.format)
        elif args.action == "profile-refresh":
            config = load_config(args.config)
            output = action_profile_refresh(config)
        elif args.action == "sync-index":
            config = load_config(args.config)
            output = action_sync_index(config, config_path=args.config, force_rebuild=args.force_rebuild)
        else:
            parser.error(f"Unknown action: {args.action}")
        print(output)
    except Exception as exc:
        LOG.error("Error: %s", exc, exc_info=args.verbose)
        sys.exit(1)


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


DEFAULT_SKILL_ROOT = Path.home() / ".openclaw" / "skills" / "research-assist"
DEFAULT_CONFIG_PATH = DEFAULT_SKILL_ROOT / "config.json"
DEFAULT_ENV_PATH = DEFAULT_SKILL_ROOT / ".env"


def _expand_path(path_text: str, *, base_dir: Path | None = None) -> Path:
    path = Path(path_text).expanduser()
    if path.is_absolute():
        return path.resolve()
    if base_dir is not None:
        return (base_dir / path).resolve()
    return path.resolve()


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
            if text:
                items.append(text)
    return items


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


@dataclass(frozen=True)
class ZoteroMcpConfig:
    config_path: Path
    profile_path: Path
    library_id: str
    api_key: str
    library_type: str
    enforce_library_id: str | None
    enforce_library_type: str | None
    scope_collection: str
    profile_collections: tuple[str, ...]
    profile_tags: tuple[str, ...]
    feedback_default_collections: tuple[str, ...]
    feedback_default_tags: tuple[str, ...]
    semantic_enabled: bool
    semantic_zotero_db_path: Path | None
    semantic_persist_directory: Path
    semantic_collection_name: str
    semantic_embedding_model: str
    semantic_extract_fulltext: bool
    semantic_embedding_config: dict[str, Any]
    semantic_local_group_id: int | None
    semantic_local_library_id: int | None


def load_skill_config(config_path: str | Path | None = None) -> dict[str, Any]:
    resolved = _expand_path(str(config_path or DEFAULT_CONFIG_PATH))
    if not resolved.exists():
        return {}
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"skill config must be a JSON object: {resolved}")
    return payload


def load_zotero_config(config_path: str | Path | None = None) -> ZoteroMcpConfig:
    resolved_config_path = _expand_path(str(config_path or DEFAULT_CONFIG_PATH))
    config_dir = resolved_config_path.parent

    env_path = DEFAULT_ENV_PATH
    if config_dir != DEFAULT_SKILL_ROOT and (config_dir / ".env").exists():
        env_path = config_dir / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    payload = load_skill_config(resolved_config_path)
    zotero_cfg = payload.get("zotero") if isinstance(payload.get("zotero"), dict) else {}

    profile_path_text = str(
        payload.get("profile_path")
        or DEFAULT_SKILL_ROOT / "profiles" / "research-interest.json"
    )
    profile_path = _expand_path(profile_path_text, base_dir=config_dir)

    library_id = str(
        zotero_cfg.get("library_id")
        or os.environ.get("ZOTERO_LIBRARY_ID")
        or ""
    ).strip()
    api_key = str(
        zotero_cfg.get("api_key")
        or os.environ.get("ZOTERO_API_KEY")
        or ""
    ).strip()
    library_type = str(
        zotero_cfg.get("library_type")
        or os.environ.get("ZOTERO_LIBRARY_TYPE")
        or "user"
    ).strip() or "user"
    enforce_library_id = str(zotero_cfg.get("enforce_library_id") or "").strip() or None
    enforce_library_type = str(zotero_cfg.get("enforce_library_type") or "").strip() or None
    scope_collection = str(zotero_cfg.get("scope_collection") or "").strip()
    semantic_cfg = payload.get("semantic_search") if isinstance(payload.get("semantic_search"), dict) else {}
    semantic_db_path_text = str(
        semantic_cfg.get("zotero_db_path")
        or os.environ.get("ZOTERO_DB_PATH")
        or ""
    ).strip()
    semantic_db_path = (
        _expand_path(semantic_db_path_text, base_dir=config_dir)
        if semantic_db_path_text
        else None
    )
    semantic_persist_directory = _expand_path(
        str(
            semantic_cfg.get("persist_directory")
            or DEFAULT_SKILL_ROOT / ".semantic-search"
        ),
        base_dir=config_dir,
    )
    semantic_collection_name = str(
        semantic_cfg.get("collection_name") or "research_assist_zotero"
    ).strip() or "research_assist_zotero"
    semantic_embedding_model = str(
        semantic_cfg.get("embedding_model") or "default"
    ).strip() or "default"
    semantic_embedding_config: dict[str, Any] = {}
    if isinstance(semantic_cfg.get("embedding_config"), dict):
        semantic_embedding_config = semantic_cfg["embedding_config"]
    semantic_local_group_id = semantic_cfg.get("local_group_id")
    if isinstance(semantic_local_group_id, str) and semantic_local_group_id.strip().isdigit():
        semantic_local_group_id = int(semantic_local_group_id.strip())
    if not isinstance(semantic_local_group_id, int):
        semantic_local_group_id = None

    semantic_local_library_id = semantic_cfg.get("local_library_id")
    if isinstance(semantic_local_library_id, str) and semantic_local_library_id.strip().isdigit():
        semantic_local_library_id = int(semantic_local_library_id.strip())
    if not isinstance(semantic_local_library_id, int):
        semantic_local_library_id = None

    return ZoteroMcpConfig(
        config_path=resolved_config_path,
        profile_path=profile_path,
        library_id=library_id,
        api_key=api_key,
        library_type=library_type,
        enforce_library_id=enforce_library_id,
        enforce_library_type=enforce_library_type,
        scope_collection=scope_collection,
        profile_collections=tuple(_as_string_list(zotero_cfg.get("profile_collections"))),
        profile_tags=tuple(_as_string_list(zotero_cfg.get("profile_tags"))),
        feedback_default_collections=tuple(_as_string_list(zotero_cfg.get("feedback_default_collections"))),
        feedback_default_tags=tuple(_as_string_list(zotero_cfg.get("feedback_default_tags"))),
        semantic_enabled=_as_bool(semantic_cfg.get("enabled"), True),
        semantic_zotero_db_path=semantic_db_path,
        semantic_persist_directory=semantic_persist_directory,
        semantic_collection_name=semantic_collection_name,
        semantic_embedding_model=semantic_embedding_model,
        semantic_embedding_config=semantic_embedding_config,
        semantic_extract_fulltext=_as_bool(semantic_cfg.get("extract_fulltext"), False),
        semantic_local_group_id=semantic_local_group_id,
        semantic_local_library_id=semantic_local_library_id,
    )

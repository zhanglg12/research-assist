"""FastMCP server exposing Zotero-backed profile and feedback tools."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from ..arxiv_profile_pipeline.profile_contract import normalize_profile_payload
from .client import ZoteroClient
from .config import load_zotero_config
from .feedback import normalize_feedback_payload
from .profile_evidence import build_profile_evidence_summary
from .semantic_search import create_semantic_search


logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
LOG = logging.getLogger("research-assist.zotero-mcp")

mcp = FastMCP("research-assist-zotero")


def _client(config_path: str | None = None) -> tuple[ZoteroClient, Any]:
    cfg = load_zotero_config(config_path)
    if cfg.enforce_library_type and cfg.library_type != cfg.enforce_library_type:
        raise PermissionError(
            f"Zotero library_type is restricted to '{cfg.enforce_library_type}', got '{cfg.library_type}'."
        )
    if cfg.enforce_library_id and cfg.library_id != cfg.enforce_library_id:
        raise PermissionError(
            f"Zotero library_id is restricted to '{cfg.enforce_library_id}', got '{cfg.library_id}'."
        )
    client = ZoteroClient(cfg.library_id, cfg.api_key, cfg.library_type)
    return client, cfg


def _semantic_search(config_path: str | None = None):
    return create_semantic_search(config_path=config_path)


def _scoped_collections(cfg, explicit: list[str] | None, fallback: tuple[str, ...]) -> list[str]:
    """Resolve effective collection list: explicit > config fallback > scope_collection."""
    if explicit is not None:
        return explicit
    if fallback:
        return list(fallback)
    if cfg.scope_collection:
        return [cfg.scope_collection]
    return []


@mcp.tool()
def zotero_status(config_path: str | None = None) -> dict[str, Any]:
    """Return Zotero MCP configuration and whether the skill can read/write the library."""
    cfg = load_zotero_config(config_path)
    result = {
        "config_path": cfg.config_path.as_posix(),
        "profile_path": cfg.profile_path.as_posix(),
        "library_type": cfg.library_type,
        "zotero_configured": bool(cfg.library_id and cfg.api_key),
        "enforce_library_id": cfg.enforce_library_id,
        "enforce_library_type": cfg.enforce_library_type,
        "scope_collection": cfg.scope_collection or None,
        "profile_collections": list(cfg.profile_collections),
        "profile_tags": list(cfg.profile_tags),
        "feedback_default_collections": list(cfg.feedback_default_collections),
        "feedback_default_tags": list(cfg.feedback_default_tags),
    }
    if not result["zotero_configured"]:
        result["setup_hint"] = (
            "Set `ZOTERO_LIBRARY_ID` and `ZOTERO_API_KEY`, or place them in the "
            "skill config `zotero` block / `.env` before using the Zotero MCP."
        )
    return result


@mcp.tool()
def zotero_list_collections(config_path: str | None = None) -> list[dict[str, Any]]:
    """List Zotero collections with stable keys and human-readable paths."""
    client, _cfg = _client(config_path)
    return client.list_collections()


@mcp.tool()
def zotero_list_local_groups(config_path: str | None = None) -> list[dict[str, Any]]:
    """List group libraries visible in the local zotero.sqlite database."""
    cfg = load_zotero_config(config_path)
    if not cfg.semantic_zotero_db_path:
        raise FileNotFoundError("semantic_search.zotero_db_path is not configured")
    from .local_db import LocalZoteroReader

    with LocalZoteroReader(db_path=cfg.semantic_zotero_db_path.as_posix()) as reader:
        return reader.get_groups()


@mcp.tool()
def zotero_get_tags(config_path: str | None = None, limit: int = 500) -> list[str]:
    """List distinct tags observed in the Zotero library."""
    client, _cfg = _client(config_path)
    return client.list_tags(limit=max(1, min(limit, 2000)))


@mcp.tool()
def zotero_profile_evidence(
    config_path: str | None = None,
    collection_names: list[str] | None = None,
    tags: list[str] | None = None,
    limit: int = 50,
    include_children: bool = True,
) -> dict[str, Any]:
    """Read Zotero items used to build the research-interest profile."""
    client, cfg = _client(config_path)
    effective_collections = _scoped_collections(cfg, collection_names, cfg.profile_collections)
    effective_tags = tags if tags is not None else list(cfg.profile_tags)
    items, collection_map = client.get_profile_items(
        collection_names=effective_collections,
        tags=effective_tags,
        limit=max(1, min(limit, 200)),
        include_children=include_children,
    )
    evidence = build_profile_evidence_summary(
        items,
        collections=list(collection_map.keys()),
        tags=effective_tags,
        applied_limit=max(1, min(limit, 200)),
    )
    evidence["requested"] = {
        "collections": effective_collections,
        "tags": effective_tags,
        "include_children": include_children,
    }
    return evidence


@mcp.tool()
def zotero_search_items(
    query: str,
    config_path: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search Zotero items by title, DOI, creators, or tags."""
    client, _cfg = _client(config_path)
    return client.search_items(query=query, limit=max(1, min(limit, 100)))


@mcp.tool()
def zotero_batch_update_tags(
    query: str,
    config_path: str | None = None,
    add_tags: list[str] | None = None,
    remove_tags: list[str] | None = None,
    limit: int = 50,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Batch add/remove tags on items matched by a simple search query."""
    client, cfg = _client(config_path)
    # Scope guard: restrict matched items to scope collection
    restrict_keys: set[str] | None = None
    if cfg.scope_collection:
        resolved = client.resolve_collection_keys([cfg.scope_collection], include_children=True)
        if resolved:
            restrict_keys = set(resolved.values())
    return client.batch_update_tags(
        query=query,
        add_tags=add_tags,
        remove_tags=remove_tags,
        limit=max(1, min(limit, 500)),
        dry_run=dry_run,
        restrict_to_collection_keys=restrict_keys,
    )


@mcp.tool()
def zotero_write_profile(
    profile_payload: dict[str, Any],
    target_path: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Normalize and write the live research-interest profile JSON."""
    cfg = load_zotero_config(config_path)
    normalized = normalize_profile_payload(profile_payload)
    resolved_path = Path(target_path).expanduser().resolve() if target_path else cfg.profile_path
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "profile_path": resolved_path.as_posix(),
        "interest_count": len(normalized["interests"]),
        "profile_id": normalized["profile_id"],
        "profile_name": normalized["profile_name"],
    }


@mcp.tool()
def zotero_save_papers(
    papers: list[dict[str, Any]],
    config_path: str | None = None,
    collection_names: list[str] | None = None,
    tags: list[str] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Save newly selected papers into Zotero without deleting existing items."""
    client, cfg = _client(config_path)
    effective_collections = _scoped_collections(cfg, collection_names, cfg.feedback_default_collections)
    effective_tags = tags if tags is not None else list(cfg.feedback_default_tags)
    return client.save_papers(
        papers,
        default_collections=effective_collections,
        default_tags=effective_tags,
        dry_run=dry_run,
    )


@mcp.tool()
def zotero_create_collection(
    name: str,
    config_path: str | None = None,
    parent_ref: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Create a collection, optionally nested under an existing parent collection."""
    client, _cfg = _client(config_path)
    return client.create_collection(name=name, parent_ref=parent_ref, dry_run=dry_run)


@mcp.tool()
def zotero_update_collection(
    collection_ref: str,
    config_path: str | None = None,
    name: str | None = None,
    parent_ref: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Rename a collection or change its parent collection."""
    client, _cfg = _client(config_path)
    return client.update_collection(
        collection_ref=collection_ref,
        name=name,
        parent_ref=parent_ref,
        dry_run=dry_run,
    )


@mcp.tool()
def zotero_move_items_to_collection(
    item_keys: list[str],
    collection_ref: str,
    config_path: str | None = None,
    action: str = "add",
    dry_run: bool = True,
) -> dict[str, Any]:
    """Add items to a collection or remove them from one existing collection."""
    client, cfg = _client(config_path)
    # Scope guard: restrict items to scope collection
    if cfg.scope_collection:
        resolved = client.resolve_collection_keys([cfg.scope_collection], include_children=True)
        if resolved:
            scope_keys = set(resolved.values())
            # Verify each item_key belongs to scope before allowing modification
            filtered_keys: list[str] = []
            for ik in item_keys:
                entry = client._find_raw_item(item_key=ik)
                if entry and set(entry["data"].get("collections", [])).intersection(scope_keys):
                    filtered_keys.append(ik)
            item_keys = filtered_keys
    return client.move_items_to_collection(
        item_keys=item_keys,
        collection_ref=collection_ref,
        action=action,
        dry_run=dry_run,
    )


@mcp.tool()
def zotero_apply_feedback(
    feedback_payload: dict[str, Any],
    config_path: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Apply a non-destructive Zotero feedback report to existing library items."""
    client, cfg = _client(config_path)
    normalized = normalize_feedback_payload(feedback_payload)
    # Resolve scope guard: only allow modifications to items inside scope collection
    restrict_keys: set[str] | None = None
    if cfg.scope_collection:
        resolved = client.resolve_collection_keys([cfg.scope_collection], include_children=True)
        if resolved:
            restrict_keys = set(resolved.values())
    return client.apply_feedback(normalized, dry_run=dry_run, restrict_to_collection_keys=restrict_keys)


@mcp.tool()
def zotero_semantic_search(
    query: str,
    config_path: str | None = None,
    limit: int = 10,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Perform semantic search over the locally indexed Zotero library."""
    search = _semantic_search(config_path)
    return search.search(query=query, limit=max(1, min(limit, 50)), filters=filters)


@mcp.tool()
def zotero_update_search_database(
    config_path: str | None = None,
    force_rebuild: bool = False,
    limit: int | None = 500,
    extract_fulltext: bool | None = None,
) -> dict[str, Any]:
    """Rebuild or incrementally refresh the local semantic search index."""
    search = _semantic_search(config_path)
    return search.update_database(
        force_rebuild=force_rebuild,
        limit=limit,
        extract_fulltext=extract_fulltext,
    )


@mcp.tool()
def zotero_get_search_database_status(config_path: str | None = None) -> dict[str, Any]:
    """Return semantic search index status and current configuration."""
    search = _semantic_search(config_path)
    return search.status()


@mcp.tool()
def zotero_sync_index(
    config_path: str | None = None,
    collection_names: list[str] | None = None,
    limit: int = 500,
    force_rebuild: bool = False,
) -> dict[str, Any]:
    """Sync items from Zotero API into the local semantic search index.

    Works without a local zotero.sqlite — fetches items via the Web API,
    embeds them, and upserts into ChromaDB.  Respects scope_collection
    when collection_names is not provided.
    """
    search = _semantic_search(config_path)
    return search.sync_from_api(
        collection_names=collection_names,
        limit=limit,
        force_rebuild=force_rebuild,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the research-assist Zotero MCP server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()

    if args.transport == "http":
        mcp.run(transport="http", host=args.host, port=args.port)
        return
    mcp.run()


if __name__ == "__main__":
    main()

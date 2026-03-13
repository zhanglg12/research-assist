from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from .feedback import SYSTEM_TAG, build_feedback_note, decision_status_tag

try:
    from pyzotero import zotero
except ImportError:
    zotero = None  # type: ignore[assignment]


LOG = logging.getLogger("research_assist.zotero_mcp")

BLOCKED_ITEM_TYPES = {"attachment", "note", "annotation"}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _creator_name(creator: dict[str, Any]) -> str:
    if creator.get("name"):
        return str(creator["name"]).strip()
    first = str(creator.get("firstName") or "").strip()
    last = str(creator.get("lastName") or "").strip()
    return " ".join(part for part in [first, last] if part).strip()


class ZoteroClient:
    def __init__(self, library_id: str, api_key: str, library_type: str = "user"):
        if zotero is None:
            raise ImportError("pyzotero is not installed. Run `uv sync` to install project dependencies.")
        if not library_id or not api_key:
            raise ValueError("ZOTERO_LIBRARY_ID and ZOTERO_API_KEY must be configured before using the Zotero MCP.")
        self.zot = zotero.Zotero(library_id, library_type, api_key)
        self._collections_cache: list[dict[str, Any]] | None = None

    def _everything(self, call_result: Any) -> list[dict]:
        if hasattr(self.zot, "everything"):
            return list(self.zot.everything(call_result))
        if isinstance(call_result, list):
            return call_result
        return list(call_result or [])

    def _load_collections(self) -> list[dict[str, Any]]:
        if self._collections_cache is None:
            self._collections_cache = self._everything(self.zot.collections())
        return self._collections_cache

    def list_collections(self) -> list[dict[str, str | None]]:
        collections = self._load_collections()
        by_key = {
            coll.get("data", {}).get("key"): coll.get("data", {})
            for coll in collections
        }
        result: list[dict[str, str | None]] = []
        for coll in collections:
            data = coll.get("data", {})
            parent_key = data.get("parentCollection")
            path_parts = [data.get("name", "")]
            cursor = parent_key
            while cursor:
                parent = by_key.get(cursor)
                if not parent:
                    break
                path_parts.append(parent.get("name", ""))
                cursor = parent.get("parentCollection")
            result.append(
                {
                    "key": data.get("key"),
                    "name": data.get("name"),
                    "parent_key": parent_key,
                    "path": " / ".join(reversed([part for part in path_parts if part])),
                }
            )
        result.sort(key=lambda item: (str(item.get("path") or ""), str(item.get("key") or "")))
        return result

    def _collection_descendants(self, root_keys: set[str]) -> set[str]:
        collections = self._load_collections()
        children: dict[str, list[str]] = {}
        for coll in collections:
            data = coll.get("data", {})
            parent = data.get("parentCollection")
            key = data.get("key")
            if not parent or not key:
                continue
            children.setdefault(parent, []).append(key)

        resolved = set(root_keys)
        queue = list(root_keys)
        while queue:
            current = queue.pop(0)
            for child_key in children.get(current, []):
                if child_key in resolved:
                    continue
                resolved.add(child_key)
                queue.append(child_key)
        return resolved

    def resolve_collection_keys(self, names: Iterable[str], *, include_children: bool = True) -> dict[str, str]:
        requested = {name.strip().lower(): name.strip() for name in names if name and name.strip()}
        if not requested:
            return {}
        matched: dict[str, str] = {}
        seed_keys: set[str] = set()
        for coll in self._load_collections():
            data = coll.get("data", {})
            name = str(data.get("name") or "").strip()
            key = str(data.get("key") or "").strip()
            lowered = name.lower()
            if lowered in requested and key:
                matched[name] = key
                seed_keys.add(key)
        if include_children and seed_keys:
            expanded = self._collection_descendants(seed_keys)
            by_key = {
                str(coll.get("data", {}).get("key") or ""): str(coll.get("data", {}).get("name") or "")
                for coll in self._load_collections()
            }
            for key in expanded:
                name = by_key.get(key)
                if name:
                    matched[name] = key
        return matched

    def resolve_existing_collection_keys(self, names: Iterable[str]) -> dict[str, str]:
        return self.resolve_collection_keys(names, include_children=False)

    def _filter_items(self, entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for entry in entries:
            data = entry.get("data", {})
            item_type = str(data.get("itemType") or "").strip()
            if item_type in BLOCKED_ITEM_TYPES:
                continue
            result.append(entry)
        return result

    def _item_summary(self, entry: dict[str, Any]) -> dict[str, Any]:
        data = entry.get("data", {})
        tags = [tag.get("tag", "").strip() for tag in data.get("tags", []) if tag.get("tag")]
        creators = [_creator_name(creator) for creator in data.get("creators", []) if _creator_name(creator)]
        year = ""
        date_text = _as_text(data.get("date"))
        if len(date_text) >= 4 and date_text[:4].isdigit():
            year = date_text[:4]
        return {
            "item_key": data.get("key"),
            "version": data.get("version"),
            "item_type": data.get("itemType"),
            "title": _as_text(data.get("title")),
            "doi": _as_text(data.get("DOI")).lower() or None,
            "year": year or None,
            "date": date_text or None,
            "publication_title": _as_text(data.get("publicationTitle")) or None,
            "abstract": _as_text(data.get("abstractNote")) or None,
            "url": _as_text(data.get("url")) or None,
            "tags": tags,
            "collections": list(data.get("collections", [])),
            "creators": creators,
            "extra": _as_text(data.get("extra")) or None,
        }

    def get_items_raw(
        self,
        *,
        collection_names: list[str] | None = None,
        limit: int = 500,
        include_children: bool = True,
    ) -> list[dict[str, Any]]:
        """Return raw API entries, optionally scoped to collections."""
        if collection_names:
            collection_map = self.resolve_collection_keys(collection_names, include_children=include_children)
            if collection_map:
                seen_keys: set[str] = set()
                items: list[dict[str, Any]] = []
                for collection_key in collection_map.values():
                    entries = self._filter_items(self._everything(self.zot.collection_items(collection_key)))
                    for entry in entries:
                        key = str(entry.get("data", {}).get("key") or "")
                        if not key or key in seen_keys:
                            continue
                        seen_keys.add(key)
                        items.append(entry)
                        if len(items) >= limit:
                            return items
                return items
        return self._filter_items(self._everything(self.zot.top()))[:limit]

    def get_profile_items(
        self,
        *,
        collection_names: list[str] | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
        include_children: bool = True,
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        effective_tags = {tag.strip().lower() for tag in (tags or []) if tag and tag.strip()}
        items: list[dict[str, Any]] = []
        collection_map = self.resolve_collection_keys(collection_names or [], include_children=include_children)

        if collection_map:
            seen_keys: set[str] = set()
            for collection_key in collection_map.values():
                entries = self._filter_items(self._everything(self.zot.collection_items(collection_key)))
                for entry in entries:
                    key = str(entry.get("data", {}).get("key") or "")
                    if not key or key in seen_keys:
                        continue
                    seen_keys.add(key)
                    items.append(entry)
        else:
            items = self._filter_items(self._everything(self.zot.top()))

        filtered: list[dict[str, Any]] = []
        for entry in items:
            summary = self._item_summary(entry)
            if effective_tags:
                item_tags = {tag.lower() for tag in summary["tags"]}
                if not effective_tags.intersection(item_tags):
                    continue
            filtered.append(summary)
            if len(filtered) >= limit:
                break

        return filtered, collection_map

    def search_items(self, *, query: str = "", limit: int = 20) -> list[dict[str, Any]]:
        query_text = query.strip().lower()
        items = self._filter_items(self._everything(self.zot.top()))
        results: list[dict[str, Any]] = []
        for entry in items:
            summary = self._item_summary(entry)
            haystack = " ".join(
                [
                    str(summary.get("title") or ""),
                    str(summary.get("doi") or ""),
                    " ".join(summary.get("creators") or []),
                    " ".join(summary.get("tags") or []),
                ]
            ).lower()
            if query_text and query_text not in haystack:
                continue
            results.append(summary)
            if len(results) >= limit:
                break
        return results

    def _find_raw_item(
        self,
        *,
        item_key: str | None = None,
        doi: str | None = None,
        title_contains: str | None = None,
    ) -> dict[str, Any] | None:
        if item_key:
            try:
                item = self.zot.item(item_key)
                if item and item.get("data"):
                    return item
            except Exception:
                pass

        title_match = (title_contains or "").strip().lower()
        doi_match = (doi or "").strip().lower()
        for entry in self._filter_items(self._everything(self.zot.top())):
            summary = self._item_summary(entry)
            if doi_match and summary.get("doi") == doi_match:
                return entry
            if title_match and title_match in str(summary.get("title") or "").lower():
                return entry
        return None

    def _top_entries(self) -> list[dict[str, Any]]:
        return self._filter_items(self._everything(self.zot.top()))

    def _match_raw_items(self, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
        query_text = query.strip().lower()
        if not query_text:
            return []
        results: list[dict[str, Any]] = []
        for entry in self._top_entries():
            summary = self._item_summary(entry)
            haystack = " ".join(
                [
                    str(summary.get("title") or ""),
                    str(summary.get("doi") or ""),
                    " ".join(summary.get("creators") or []),
                    " ".join(summary.get("tags") or []),
                ]
            ).lower()
            if query_text not in haystack:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    def _tag_payload(self, tags: list[str]) -> list[dict[str, str]]:
        unique: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            lowered = tag.strip().lower()
            if not lowered or lowered in seen:
                continue
            seen.add(lowered)
            unique.append(tag.strip())
        return [{"tag": tag} for tag in unique]

    def get_or_create_collection(self, name: str) -> str:
        for collection in self.list_collections():
            if str(collection.get("name") or "").strip().lower() == name.strip().lower():
                return str(collection.get("key") or "")

        payload = [{"name": name}]
        response = self.zot.create_collections(payload)
        if isinstance(response, dict):
            for _idx, item in response.get("successful", {}).items():
                data = item.get("data", item)
                key = str(data.get("key") or "").strip()
                if key:
                    self._collections_cache = None
                    return key
        self._collections_cache = None
        resolved = self.resolve_collection_keys([name], include_children=False)
        for key in resolved.values():
            return key
        raise RuntimeError(f"failed to create or resolve Zotero collection: {name}")

    def resolve_collection_ref(self, ref: str, *, create_if_missing: bool = False) -> str:
        text = ref.strip()
        if not text:
            raise ValueError("collection reference must be non-empty")
        for collection in self.list_collections():
            if text == str(collection.get("key") or ""):
                return text
            if text.lower() == str(collection.get("name") or "").strip().lower():
                return str(collection.get("key") or "")
            if text.lower() == str(collection.get("path") or "").strip().lower():
                return str(collection.get("key") or "")
        if create_if_missing:
            return self.get_or_create_collection(text)
        raise KeyError(f"collection not found: {text}")

    def list_tags(self, *, limit: int = 500) -> list[str]:
        tags: list[str] = []
        seen: set[str] = set()
        for entry in self._top_entries():
            for tag in self._item_summary(entry).get("tags", []):
                lowered = tag.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                tags.append(tag)
                if len(tags) >= limit:
                    return sorted(tags, key=str.lower)
        return sorted(tags, key=str.lower)

    def save_papers(
        self,
        papers: list[dict[str, Any]],
        *,
        default_collections: list[str] | None = None,
        default_tags: list[str] | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        requested_collections = list(default_collections or [])
        requested_tags = list(default_tags or [])
        resolved_collection_keys = [
            self.get_or_create_collection(name)
            for name in requested_collections
        ]

        planned: list[dict[str, Any]] = []
        items_to_create: list[dict[str, Any]] = []
        for index, paper in enumerate(papers):
            title = _as_text(paper.get("title"))
            if not title:
                raise ValueError(f"papers[{index}].title is required")
            doi = _as_text(paper.get("doi")).lower()
            if doi:
                existing = self._find_raw_item(doi=doi)
                if existing is not None:
                    planned.append(
                        {
                            "status": "exists",
                            "title": title,
                            "doi": doi,
                            "item_key": existing.get("data", {}).get("key"),
                        }
                    )
                    continue

            template = self.zot.item_template("journalArticle")
            template["title"] = title
            template["DOI"] = doi
            template["url"] = _as_text(paper.get("url"))
            template["abstractNote"] = _as_text(paper.get("abstract"))
            template["publicationTitle"] = _as_text(paper.get("publication_title") or paper.get("venue"))
            template["date"] = _as_text(paper.get("date") or paper.get("year"))
            creators: list[dict[str, str]] = []
            for author in paper.get("authors", []):
                author_text = _as_text(author)
                if not author_text:
                    continue
                parts = author_text.split()
                if len(parts) >= 2:
                    creators.append(
                        {
                            "creatorType": "author",
                            "firstName": " ".join(parts[:-1]),
                            "lastName": parts[-1],
                        }
                    )
                else:
                    creators.append({"creatorType": "author", "name": author_text})
            if creators:
                template["creators"] = creators

            item_tags = list(requested_tags)
            for tag in paper.get("topic_tags", []):
                text = _as_text(tag)
                if text:
                    item_tags.append(text)
            item_tags.append(SYSTEM_TAG)
            template["tags"] = self._tag_payload(item_tags)
            if resolved_collection_keys:
                template["collections"] = resolved_collection_keys

            items_to_create.append(template)
            planned.append(
                {
                    "status": "create",
                    "title": title,
                    "doi": doi or None,
                    "collections": requested_collections,
                    "tags": sorted({tag for tag in item_tags if tag}),
                }
            )

        if dry_run or not items_to_create:
            return {"dry_run": dry_run, "planned": planned, "created": []}

        response = self.zot.create_items(items_to_create)
        created: list[dict[str, Any]] = []
        if isinstance(response, dict):
            for _idx, item in response.get("successful", {}).items():
                data = item.get("data", item)
                created.append({"item_key": data.get("key"), "title": data.get("title")})
        return {"dry_run": False, "planned": planned, "created": created}

    def batch_update_tags(
        self,
        *,
        query: str,
        add_tags: list[str] | None = None,
        remove_tags: list[str] | None = None,
        limit: int = 50,
        dry_run: bool = True,
        restrict_to_collection_keys: set[str] | None = None,
    ) -> dict[str, Any]:
        add_tags = [tag.strip() for tag in (add_tags or []) if tag and tag.strip()]
        remove_tags = [tag.strip() for tag in (remove_tags or []) if tag and tag.strip()]
        if not add_tags and not remove_tags:
            raise ValueError("must specify add_tags and/or remove_tags")

        matched = self._match_raw_items(query, limit=limit)
        planned: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []
        for entry in matched:
            data = entry["data"]
            # Scope guard
            if restrict_to_collection_keys is not None:
                item_collections = set(data.get("collections", []))
                if not item_collections.intersection(restrict_to_collection_keys):
                    planned.append({
                        "item_key": data.get("key"),
                        "title": data.get("title"),
                        "status": "out_of_scope",
                    })
                    continue
            current_tags = [tag.get("tag", "").strip() for tag in data.get("tags", []) if tag.get("tag")]
            next_tags = [tag for tag in current_tags if tag.lower() not in {name.lower() for name in remove_tags}]
            for tag in add_tags:
                if tag.lower() not in {name.lower() for name in next_tags}:
                    next_tags.append(tag)
            plan = {
                "item_key": data.get("key"),
                "title": data.get("title"),
                "before_tags": current_tags,
                "after_tags": next_tags,
            }
            planned.append(plan)
            if dry_run or current_tags == next_tags:
                continue
            data["tags"] = self._tag_payload(next_tags)
            self.zot.update_item(entry)
            updated.append({"item_key": data.get("key"), "title": data.get("title")})
        return {
            "dry_run": dry_run,
            "query": query,
            "matched_count": len(matched),
            "planned": planned,
            "updated": updated,
        }

    def create_collection(
        self,
        *,
        name: str,
        parent_ref: str | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": name.strip()}
        parent_key = None
        if parent_ref:
            parent_key = self.resolve_collection_ref(parent_ref, create_if_missing=False)
            payload["parentCollection"] = parent_key
        if dry_run:
            return {"dry_run": True, "planned": payload}
        response = self.zot.create_collections([payload])
        created = response.get("successful", {}) if isinstance(response, dict) else {}
        created_key = None
        for item in created.values():
            data = item.get("data", item)
            created_key = data.get("key")
            break
        self._collections_cache = None
        return {"dry_run": False, "created_key": created_key, "payload": payload}

    def update_collection(
        self,
        *,
        collection_ref: str,
        name: str | None = None,
        parent_ref: str | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        collection_key = self.resolve_collection_ref(collection_ref, create_if_missing=False)
        collections = self._load_collections()
        target = next(
            (coll for coll in collections if coll.get("data", {}).get("key") == collection_key),
            None,
        )
        if target is None:
            raise KeyError(f"collection not found: {collection_ref}")
        data = dict(target.get("data", {}))
        before = {"name": data.get("name"), "parentCollection": data.get("parentCollection")}
        if name is not None:
            data["name"] = name
        if parent_ref is not None:
            data["parentCollection"] = (
                self.resolve_collection_ref(parent_ref, create_if_missing=False)
                if parent_ref.strip()
                else False
            )
        after = {"name": data.get("name"), "parentCollection": data.get("parentCollection")}
        if dry_run:
            return {"dry_run": True, "collection_key": collection_key, "before": before, "after": after}
        target["data"] = data
        self.zot.update_collection(target)
        self._collections_cache = None
        return {"dry_run": False, "collection_key": collection_key, "before": before, "after": after}

    def move_items_to_collection(
        self,
        *,
        item_keys: list[str],
        collection_ref: str,
        action: str = "add",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        if action not in {"add", "remove"}:
            raise ValueError("action must be 'add' or 'remove'")
        collection_key = self.resolve_collection_ref(
            collection_ref,
            create_if_missing=(action == "add"),
        )
        planned: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []
        for item_key in item_keys:
            entry = self._find_raw_item(item_key=item_key)
            if entry is None:
                planned.append({"item_key": item_key, "status": "not_found"})
                continue
            data = entry["data"]
            current = list(data.get("collections", []))
            next_collections = list(current)
            if action == "add" and collection_key not in next_collections:
                next_collections.append(collection_key)
            if action == "remove":
                next_collections = [key for key in next_collections if key != collection_key]
            planned.append(
                {
                    "item_key": item_key,
                    "title": data.get("title"),
                    "before_collections": current,
                    "after_collections": next_collections,
                }
            )
            if dry_run or current == next_collections:
                continue
            data["collections"] = next_collections
            self.zot.update_item(entry)
            updated.append({"item_key": item_key, "title": data.get("title")})
        return {
            "dry_run": dry_run,
            "action": action,
            "collection_key": collection_key,
            "planned": planned,
            "updated": updated,
        }

    def apply_feedback(self, payload: dict[str, Any], *, dry_run: bool = True, restrict_to_collection_keys: set[str] | None = None) -> dict[str, Any]:
        decisions = payload["decisions"]
        planned: list[dict[str, Any]] = []
        applied: list[dict[str, Any]] = []

        for decision in decisions:
            match = decision["match"]
            entry = self._find_raw_item(
                item_key=match.get("item_key"),
                doi=match.get("doi"),
                title_contains=match.get("title_contains"),
            )
            if entry is None:
                planned.append(
                    {
                        "status": "not_found",
                        "match": match,
                        "decision": decision["decision"],
                    }
                )
                continue

            data = entry["data"]

            # Scope guard: skip items outside the allowed collections
            if restrict_to_collection_keys is not None:
                item_collections = set(data.get("collections", []))
                if not item_collections.intersection(restrict_to_collection_keys):
                    planned.append(
                        {
                            "status": "out_of_scope",
                            "item_key": data.get("key"),
                            "title": data.get("title"),
                            "decision": decision["decision"],
                            "note_created": False,
                        }
                    )
                    continue
            if decision["decision"] == "unset":
                planned.append(
                    {
                        "status": "skipped_unset",
                        "item_key": data.get("key"),
                        "title": data.get("title"),
                        "decision": decision["decision"],
                        "note_created": False,
                    }
                )
                continue

            current_tags = [tag.get("tag", "").strip() for tag in data.get("tags", []) if tag.get("tag")]
            next_tags = [
                tag
                for tag in current_tags
                if tag.strip().lower() not in {name.lower() for name in decision["remove_tags"]}
                and not tag.strip().lower().startswith("ra-status:")
            ]
            next_tags.extend(decision["add_tags"])
            status_tag = decision_status_tag(decision["decision"])
            if status_tag:
                next_tags.append(status_tag)
            next_tags.append(SYSTEM_TAG)

            current_collection_keys = list(data.get("collections", []))
            next_collection_keys = list(current_collection_keys)
            existing_add_collection_keys = {
                name.strip().lower(): key
                for name, key in self.resolve_existing_collection_keys(decision["add_collections"]).items()
            }
            collections_to_create: list[str] = []
            for collection_name in decision["add_collections"]:
                key = existing_add_collection_keys.get(collection_name.strip().lower())
                if not key:
                    if dry_run:
                        collections_to_create.append(collection_name)
                        continue
                    key = self.get_or_create_collection(collection_name)
                if key not in next_collection_keys:
                    next_collection_keys.append(key)
            remove_keys = set(
                self.resolve_existing_collection_keys(decision["remove_collections"]).values()
            )
            next_collection_keys = [key for key in next_collection_keys if key not in remove_keys]

            note_text = build_feedback_note(
                decision,
                generated_at=payload["generated_at"],
                source=payload["source"],
            )
            plan = {
                "status": "planned",
                "item_key": data.get("key"),
                "title": data.get("title"),
                "decision": decision["decision"],
                "add_tags": decision["add_tags"],
                "remove_tags": decision["remove_tags"],
                "add_collections": decision["add_collections"],
                "remove_collections": decision["remove_collections"],
                "collections_to_create": collections_to_create,
                "final_tags": sorted({tag for tag in next_tags if tag}),
                "final_collection_keys": next_collection_keys,
                "note_created": True,
            }
            planned.append(plan)

            if dry_run:
                continue

            data["tags"] = self._tag_payload(next_tags)
            data["collections"] = next_collection_keys
            self.zot.update_item(entry)

            note_template = self.zot.item_template("note")
            note_template["parentItem"] = data.get("key")
            note_template["note"] = note_text
            self.zot.create_items([note_template])
            applied.append(
                {
                    "item_key": data.get("key"),
                    "title": data.get("title"),
                    "decision": decision["decision"],
                }
            )

        return {
            "dry_run": dry_run,
            "generated_at": payload["generated_at"],
            "source": payload["source"],
            "planned": planned,
            "applied": applied,
        }

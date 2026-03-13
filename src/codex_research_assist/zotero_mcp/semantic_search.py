from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .chroma_client import ChromaClient, create_chroma_client
from .config import load_zotero_config
from .local_db import LocalZoteroReader


LOG = logging.getLogger(__name__)


@contextmanager
def suppress_stdout():
    with open(os.devnull, "w") as devnull:
        old_stdout = sys.stdout
        sys.stdout = devnull
        try:
            yield
        finally:
            sys.stdout = old_stdout


class ResearchAssistSemanticSearch:
    def __init__(
        self,
        chroma_client: ChromaClient | None = None,
        config_path: str | Path | None = None,
        db_path: str | Path | None = None,
    ):
        self.cfg = load_zotero_config(config_path)
        self.chroma_client = chroma_client or create_chroma_client(config_path)
        self.config_path = str(config_path) if config_path is not None else None
        self.db_path = str(db_path) if db_path is not None else None
        self.update_config = self._load_update_config()

    def _load_update_config(self) -> dict[str, Any]:
        config = {
            "auto_update": False,
            "update_frequency": "manual",
            "last_update": None,
            "update_days": 7,
        }
        if self.config_path and os.path.exists(self.config_path):
            try:
                with open(self.config_path, encoding="utf-8") as handle:
                    file_config = json.load(handle)
                config.update(file_config.get("semantic_search", {}).get("update_config", {}))
            except Exception as exc:
                LOG.warning("Error loading update config: %s", exc)
        return config

    def _save_update_config(self) -> None:
        if not self.config_path:
            return
        config_dir = Path(self.config_path).parent
        config_dir.mkdir(parents=True, exist_ok=True)
        full_config: dict[str, Any] = {}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, encoding="utf-8") as handle:
                    full_config = json.load(handle)
            except Exception:
                pass
        full_config.setdefault("semantic_search", {})
        full_config["semantic_search"]["update_config"] = self.update_config
        with open(self.config_path, "w", encoding="utf-8") as handle:
            json.dump(full_config, handle, ensure_ascii=False, indent=2)

    def _resolve_db_path(self) -> str:
        explicit = self.db_path
        if explicit:
            return str(Path(explicit).expanduser().resolve())
        cfg_path = self.cfg.semantic_zotero_db_path
        if cfg_path:
            return cfg_path.as_posix()
        raise FileNotFoundError(
            "semantic search requires a local zotero.sqlite path. "
            "Set `semantic_search.zotero_db_path` in config first."
        )

    def _require_local_db(self) -> None:
        db_path = Path(self._resolve_db_path())
        if not db_path.exists():
            raise FileNotFoundError(
                f"local Zotero database not found: {db_path}. "
                "Download/sync `zotero.sqlite` first, then retry semantic search."
            )

    def _safe_db_path(self) -> str | None:
        """Return the local zotero.sqlite path, or None when not configured."""
        try:
            return self._resolve_db_path()
        except FileNotFoundError:
            return None

    def should_update_database(self) -> bool:
        if not self.update_config.get("auto_update", False):
            return False
        frequency = self.update_config.get("update_frequency", "manual")
        if frequency == "manual":
            return False
        if frequency == "startup":
            return True
        if frequency == "daily":
            last_update = self.update_config.get("last_update")
            if not last_update:
                return True
            return datetime.now() - datetime.fromisoformat(last_update) >= timedelta(days=1)
        if frequency.startswith("every_"):
            try:
                days = int(frequency.split("_")[1])
                last_update = self.update_config.get("last_update")
                if not last_update:
                    return True
                return datetime.now() - datetime.fromisoformat(last_update) >= timedelta(days=days)
            except Exception:
                return False
        return False

    def _create_document_text(self, item: dict[str, Any]) -> str:
        data = item.get("data", {})
        title = data.get("title", "")
        abstract = data.get("abstractNote", "")
        creators = data.get("creators", [])
        creators_text = "; ".join(
            ", ".join(part for part in [creator.get("lastName"), creator.get("firstName")] if part).strip()
            or creator.get("name", "")
            for creator in creators
            if creator
        )
        extra_fields: list[str] = []
        if publication := data.get("publicationTitle"):
            extra_fields.append(publication)
        if tags := data.get("tags"):
            extra_fields.append(" ".join(tag.get("tag", "") for tag in tags))
        if note := data.get("note"):
            import re

            extra_fields.append(re.sub(r"<[^>]+>", "", note))
        if notes := data.get("notes"):
            extra_fields.append(str(notes))
        if fulltext := data.get("fulltext"):
            extra_fields.append(str(fulltext))
        parts = [title, creators_text, abstract] + extra_fields
        return " ".join(part for part in parts if part)

    def _create_metadata(self, item: dict[str, Any]) -> dict[str, Any]:
        data = item.get("data", {})
        metadata: dict[str, Any] = {
            "item_key": item.get("key", ""),
            "item_type": data.get("itemType", ""),
            "title": data.get("title", ""),
            "date": data.get("date", ""),
            "date_added": data.get("dateAdded", ""),
            "date_modified": data.get("dateModified", ""),
            "creators": "; ".join(
                ", ".join(part for part in [creator.get("lastName"), creator.get("firstName")] if part).strip()
                or creator.get("name", "")
                for creator in data.get("creators", [])
                if creator
            ),
            "publication": data.get("publicationTitle", ""),
            "url": data.get("url", ""),
            "doi": data.get("DOI", ""),
        }
        if data.get("fulltext"):
            metadata["has_fulltext"] = True
            if data.get("fulltextSource"):
                metadata["fulltext_source"] = data.get("fulltextSource")
        if tags := data.get("tags"):
            metadata["tags"] = " ".join(tag.get("tag", "") for tag in tags)
        else:
            metadata["tags"] = ""
        if collections := data.get("collections"):
            metadata["collections"] = " ".join(collections)
        else:
            metadata["collections"] = ""
        return metadata

    def _parse_creators_string(self, creators_str: str) -> list[dict[str, str]]:
        if not creators_str:
            return []
        creators = []
        for creator in creators_str.split(";"):
            creator = creator.strip()
            if not creator:
                continue
            if "," in creator:
                last, first = creator.split(",", 1)
                creators.append({"creatorType": "author", "firstName": first.strip(), "lastName": last.strip()})
            else:
                creators.append({"creatorType": "author", "name": creator})
        return creators

    def _get_items_from_local_db(
        self,
        limit: int | None = None,
        *,
        extract_fulltext: bool = False,
        force_rebuild: bool = False,
    ) -> list[dict[str, Any]]:
        self._require_local_db()
        LOG.info("Fetching items from local Zotero database...")
        pdf_max_pages = None
        zotero_db_path = self.db_path
        try:
            if self.config_path and os.path.exists(self.config_path):
                with open(self.config_path, encoding="utf-8") as handle:
                    config = json.load(handle)
                semantic_cfg = config.get("semantic_search", {})
                pdf_max_pages = semantic_cfg.get("extraction", {}).get("pdf_max_pages")
                if not zotero_db_path:
                    zotero_db_path = semantic_cfg.get("zotero_db_path")
        except Exception:
            pass

        local_group_id = self.cfg.semantic_local_group_id
        local_library_id = self.cfg.semantic_local_library_id

        with suppress_stdout(), LocalZoteroReader(db_path=zotero_db_path, pdf_max_pages=pdf_max_pages) as reader:
            # Enforce local scope: prefer explicit local_library_id, otherwise resolve from group id.
            scoped_library_id = local_library_id
            if scoped_library_id is None and local_group_id is not None:
                scoped_library_id = reader.resolve_library_id_for_group(local_group_id)

            local_items = reader.get_items_with_text(
                limit=limit,
                include_fulltext=extract_fulltext,
                library_id=scoped_library_id,
                collection_names=[self.cfg.scope_collection] if self.cfg.scope_collection else None,
            )
            api_items: list[dict[str, Any]] = []
            for item in local_items:
                api_items.append(
                    {
                        "key": item.key,
                        "version": 0,
                        "data": {
                            "key": item.key,
                            "itemType": item.item_type or "journalArticle",
                            "title": item.title or "",
                            "abstractNote": item.abstract or "",
                            "extra": item.extra or "",
                            "fulltext": item.fulltext or "",
                            "fulltextSource": item.fulltext_source or "",
                            "dateAdded": item.date_added,
                            "dateModified": item.date_modified,
                            "creators": self._parse_creators_string(item.creators) if item.creators else [],
                            "DOI": item.doi or "",
                            "notes": item.notes or "",
                            "tags": [{"tag": tag} for tag in item.tags],
                            "collections": item.collections,
                        },
                    }
                )
            return api_items

    def sync_from_api(
        self,
        *,
        collection_names: list[str] | None = None,
        limit: int = 500,
        force_rebuild: bool = False,
    ) -> dict[str, Any]:
        """Fetch items from Zotero API and index into ChromaDB.

        Works without a local zotero.sqlite — items are pulled via the
        Zotero Web API and embedded directly into the vector store.
        """
        if force_rebuild:
            self.chroma_client.reset_collection()

        from .client import ZoteroClient

        client = ZoteroClient(self.cfg.library_id, self.cfg.api_key, self.cfg.library_type)

        effective_collections = list(collection_names or [])
        if not effective_collections and self.cfg.scope_collection:
            effective_collections = [self.cfg.scope_collection]

        items = client.get_items_raw(
            collection_names=effective_collections if effective_collections else None,
            limit=limit,
        )
        if not items:
            return {
                "total_items": 0,
                "processed_items": 0,
                "source": "api",
                "scope_collections": effective_collections or ["all"],
            }

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []
        for item in items:
            key = item.get("key") or item.get("data", {}).get("key", "")
            if not key:
                continue
            ids.append(key)
            documents.append(self._create_document_text(item))
            metadatas.append(self._create_metadata(item))

        self.chroma_client.upsert_documents(documents=documents, metadatas=metadatas, ids=ids)
        self.update_config["last_update"] = datetime.now().isoformat()
        self._save_update_config()

        return {
            "total_items": len(items),
            "processed_items": len(ids),
            "source": "api",
            "scope_collections": effective_collections or ["all"],
            "embedding_model": self.chroma_client.embedding_model,
        }

    def update_database(
        self,
        *,
        force_rebuild: bool = False,
        limit: int | None = 500,
        extract_fulltext: bool = False,
    ) -> dict[str, Any]:
        if force_rebuild:
            self.chroma_client.reset_collection()

        items = self._get_items_from_local_db(
            limit=limit,
            extract_fulltext=extract_fulltext,
            force_rebuild=force_rebuild,
        )
        if not items:
            return {
                "total_items": 0,
                "processed_items": 0,
                "added_items": 0,
                "updated_items": 0,
                "skipped_items": 0,
                "errors": 0,
            }

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []
        for item in items:
            ids.append(item.get("key", ""))
            documents.append(self._create_document_text(item))
            metadatas.append(self._create_metadata(item))

        self.chroma_client.upsert_documents(documents=documents, metadatas=metadatas, ids=ids)
        self.update_config["last_update"] = datetime.now().isoformat()
        self._save_update_config()
        return {
            "total_items": len(items),
            "processed_items": len(items),
            "added_items": len(items) if force_rebuild else 0,
            "updated_items": 0 if force_rebuild else len(items),
            "skipped_items": 0,
            "errors": 0,
            "embedding_model": self.chroma_client.embedding_model,
        }

    def _enrich_search_results(self, chroma_results: dict[str, Any], query: str) -> list[dict[str, Any]]:
        ids = chroma_results.get("ids", [[]])[0]
        metadatas = chroma_results.get("metadatas", [[]])[0]
        documents = chroma_results.get("documents", [[]])[0]
        distances = chroma_results.get("distances", [[]])[0]
        enriched: list[dict[str, Any]] = []
        for index, item_key in enumerate(ids):
            metadata = metadatas[index] if index < len(metadatas) else {}
            matched_text = documents[index] if index < len(documents) else ""
            distance = distances[index] if index < len(distances) else None
            similarity_score = None
            if isinstance(distance, (int, float)):
                similarity_score = max(0.0, 1.0 - float(distance))
            enriched.append(
                {
                    "item_key": item_key,
                    "similarity_score": similarity_score,
                    "distance": distance,
                    "matched_text": matched_text,
                    "metadata": metadata,
                }
            )
        return enriched

    def search(
        self,
        *,
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        where = None
        if filters:
            if "itemType" in filters and "item_type" not in filters:
                filters = dict(filters)
                filters["item_type"] = filters.pop("itemType")
            where_clauses = []
            for field in ["item_type", "item_key", "doi", "has_fulltext"]:
                if field in filters:
                    where_clauses.append({field: {"$eq": filters[field]}})
            if len(where_clauses) == 1:
                where = where_clauses[0]
            elif where_clauses:
                where = {"$and": where_clauses}

        results = self.chroma_client.search(
            query_texts=[query],
            n_results=max(1, min(limit * 5, 100)),
            where=where,
        )
        enriched = self._enrich_search_results(results, query)

        post_filters = {}
        if filters:
            for field in ["tags", "collections", "title", "creators"]:
                text = str(filters.get(field) or "").strip()
                if text:
                    post_filters[field] = text.lower()
        if post_filters:
            filtered = []
            for item in enriched:
                metadata = item.get("metadata") or {}
                keep = True
                for field, expected in post_filters.items():
                    if expected not in str(metadata.get(field) or "").lower():
                        keep = False
                        break
                if keep:
                    filtered.append(item)
            enriched = filtered

        enriched = enriched[: max(1, min(limit, 50))]
        return {"query": query, "count": len(enriched), "results": enriched}

    def get_database_status(self) -> dict[str, Any]:
        return {
            "collection_info": self.chroma_client.get_collection_info(),
            "update_config": self.update_config,
        }

    def status(self) -> dict[str, Any]:
        db_status = self.get_database_status()
        collection_info = db_status.get("collection_info", {})
        return {
            "enabled": True,
            "collection_name": collection_info.get("name"),
            "document_count": collection_info.get("count", 0),
            "persist_directory": collection_info.get("persist_directory"),
            "embedding_model": collection_info.get("embedding_model"),
            "error": collection_info.get("error"),
            "update_config": db_status.get("update_config"),
            "zotero_db_path": self._safe_db_path(),
        }


def create_semantic_search(
    config_path: str | Path | None = None,
    db_path: str | Path | None = None,
) -> ResearchAssistSemanticSearch:
    return ResearchAssistSemanticSearch(config_path=config_path, db_path=db_path)

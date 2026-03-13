from __future__ import annotations

import logging
import os
import platform
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .semantic_utils import is_local_mode


LOG = logging.getLogger(__name__)


@dataclass
class IndexedZoteroItem:
    item_id: int
    key: str
    item_type_id: int
    item_type: str | None = None
    doi: str | None = None
    title: str | None = None
    abstract: str | None = None
    creators: str | None = None
    fulltext: str | None = None
    fulltext_source: str | None = None
    notes: str | None = None
    extra: str | None = None
    date_added: str | None = None
    date_modified: str | None = None
    tags: list[str] | None = None
    collections: list[str] | None = None

    def searchable_text(self) -> str:
        parts: list[str] = []
        if self.title:
            parts.append(f"Title: {self.title}")
        if self.creators:
            parts.append(f"Authors: {self.creators}")
        if self.abstract:
            parts.append(f"Abstract: {self.abstract}")
        if self.extra:
            parts.append(f"Extra: {self.extra}")
        if self.notes:
            parts.append(f"Notes: {self.notes}")
        if self.tags:
            parts.append(f"Tags: {' '.join(self.tags)}")
        if self.collections:
            parts.append(f"Collections: {' '.join(self.collections)}")
        if self.fulltext:
            truncated = self.fulltext[:5000] + "..." if len(self.fulltext) > 5000 else self.fulltext
            parts.append(f"Content: {truncated}")
        return "\n\n".join(parts)


class LocalZoteroReader:
    def __init__(self, db_path: str | None = None, pdf_max_pages: int | None = None):
        self.db_path = db_path or self._find_zotero_db()
        self._connection: sqlite3.Connection | None = None
        self.pdf_max_pages = pdf_max_pages
        try:
            logging.getLogger("pdfminer").setLevel(logging.ERROR)
        except Exception:
            pass

    def _find_zotero_db(self) -> str:
        system = platform.system()
        if system == "Darwin":
            db_path = Path.home() / "Zotero" / "zotero.sqlite"
        elif system == "Windows":
            db_path = Path.home() / "Zotero" / "zotero.sqlite"
            if not db_path.exists():
                db_path = Path(os.path.expanduser("~/Documents and Settings")) / os.getenv("USERNAME", "") / "Zotero" / "zotero.sqlite"
        else:
            db_path = Path.home() / "Zotero" / "zotero.sqlite"

        if not db_path.exists():
            raise FileNotFoundError(
                f"Zotero database not found at {db_path}. "
                "Please ensure Zotero is installed and has been run at least once."
            )
        return str(db_path)

    def _get_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            uri = f"file:{self.db_path}?immutable=1"
            self._connection = sqlite3.connect(uri, uri=True)
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def _get_storage_dir(self) -> Path:
        return Path(self.db_path).parent / "storage"

    def _iter_parent_attachments(self, parent_item_id: int):
        conn = self._get_connection()
        query = """
            SELECT ia.itemID as attachmentItemID,
                   ia.parentItemID as parentItemID,
                   ia.path as path,
                   ia.contentType as contentType,
                   att.key as attachmentKey
            FROM itemAttachments ia
            JOIN items att ON att.itemID = ia.itemID
            WHERE ia.parentItemID = ?
        """
        for row in conn.execute(query, (parent_item_id,)):
            yield row["attachmentKey"], row["path"], row["contentType"]

    def _resolve_attachment_path(self, attachment_key: str, zotero_path: str) -> Path | None:
        if not zotero_path:
            return None
        storage_dir = self._get_storage_dir()
        if zotero_path.startswith("storage:"):
            rel = zotero_path.split(":", 1)[1]
            parts = [part for part in rel.split("/") if part]
            return storage_dir / attachment_key / Path(*parts)
        return None

    def _extract_text_from_pdf(self, file_path: Path) -> str:
        try:
            from pdfminer.high_level import extract_text  # type: ignore

            if isinstance(self.pdf_max_pages, int) and self.pdf_max_pages > 0:
                maxpages = self.pdf_max_pages
            else:
                max_pages_env = os.getenv("ZOTERO_PDF_MAXPAGES")
                try:
                    maxpages = int(max_pages_env) if max_pages_env else 10
                except ValueError:
                    maxpages = 10
            text = extract_text(str(file_path), maxpages=maxpages)
            return text or ""
        except Exception:
            return ""

    def _extract_text_from_html(self, file_path: Path) -> str:
        try:
            from markitdown import MarkItDown

            md = MarkItDown()
            result = md.convert(str(file_path))
            return result.text_content or ""
        except Exception:
            pass
        try:
            from bs4 import BeautifulSoup  # type: ignore

            html = file_path.read_text(errors="ignore")
            return BeautifulSoup(html, "html.parser").get_text(" ")
        except Exception:
            return ""

    def _extract_text_from_file(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            return self._extract_text_from_pdf(file_path)
        if suffix in {".html", ".htm"}:
            return self._extract_text_from_html(file_path)
        try:
            return file_path.read_text(errors="ignore")
        except Exception:
            return ""

    def get_fulltext_meta_for_item(self, item_id: int):
        meta = []
        for key, path, ctype in self._iter_parent_attachments(item_id):
            meta.append([key, path, ctype])
        return meta

    def extract_fulltext_for_item(self, item_id: int) -> tuple[str, str] | None:
        best_pdf = None
        best_html = None
        for key, path, ctype in self._iter_parent_attachments(item_id):
            resolved = self._resolve_attachment_path(key, path or "")
            if not resolved or not resolved.exists():
                continue
            if ctype == "application/pdf" and best_pdf is None:
                best_pdf = resolved
            elif (ctype or "").startswith("text/html") and best_html is None:
                best_html = resolved
        target = best_pdf or best_html
        if not target:
            return None
        text = self._extract_text_from_file(target)
        if not text:
            return None
        source = "pdf" if target.suffix.lower() == ".pdf" else ("html" if target.suffix.lower() in {".html", ".htm"} else "file")
        return text[:10000], source

    def close(self):
        if self._connection:
            self._connection.close()
            self._connection = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def get_item_count(self) -> int:
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT COUNT(*)
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            WHERE it.typeName NOT IN ('attachment', 'note', 'annotation')
            """
        )
        return cursor.fetchone()[0]

    def get_groups(self) -> list[dict[str, Any]]:
        """Return group libraries with their libraryID mapping."""
        conn = self._get_connection()
        rows = conn.execute(
            """
            SELECT g.groupID, g.libraryID, g.name, g.description
            FROM groups g
            ORDER BY g.name
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def resolve_library_id_for_group(self, group_id: int) -> int:
        for row in self.get_groups():
            if int(row.get("groupID") or -1) == int(group_id):
                return int(row.get("libraryID"))
        raise KeyError(f"groupID not found in local Zotero database: {group_id}")

    def _resolve_collection_ids(
        self, names: list[str], *, library_id: int | None = None,
    ) -> list[int]:
        """Resolve collection names to IDs including all descendant collections."""
        conn = self._get_connection()
        lowered = {n.strip().lower() for n in names if n.strip()}
        if not lowered:
            return []
        # Find seed collections matching by name
        lib_clause = "AND c.libraryID = ?" if library_id is not None else ""
        lib_params: list[Any] = [library_id] if library_id is not None else []
        seeds: list[int] = []
        for row in conn.execute(
            f"SELECT c.collectionID, c.collectionName FROM collections c WHERE 1=1 {lib_clause}",
            lib_params,
        ):
            if row["collectionName"].strip().lower() in lowered:
                seeds.append(row["collectionID"])
        if not seeds:
            return []
        # Expand to include all descendants
        resolved = set(seeds)
        queue = list(seeds)
        while queue:
            current = queue.pop(0)
            for row in conn.execute(
                "SELECT collectionID FROM collections WHERE parentCollectionID = ?",
                (current,),
            ):
                child = row["collectionID"]
                if child not in resolved:
                    resolved.add(child)
                    queue.append(child)
        return sorted(resolved)

    def get_items_with_text(
        self,
        limit: int | None = None,
        include_fulltext: bool = False,
        *,
        library_id: int | None = None,
        collection_names: list[str] | None = None,
    ) -> list[IndexedZoteroItem]:
        conn = self._get_connection()
        query = """
        SELECT
            i.itemID,
            i.key,
            i.itemTypeID,
            it.typeName as item_type,
            i.dateAdded,
            i.dateModified,
            title_val.value as title,
            abstract_val.value as abstract,
            extra_val.value as extra,
            doi_val.value as doi,
            (
                SELECT GROUP_CONCAT(n.note, ' ')
                FROM itemNotes n
                WHERE i.itemID = n.parentItemID OR i.itemID = n.itemID
            ) as notes,
            (
                SELECT GROUP_CONCAT(
                    CASE
                        WHEN c.firstName IS NOT NULL AND c.lastName IS NOT NULL
                        THEN c.lastName || ', ' || c.firstName
                        WHEN c.lastName IS NOT NULL
                        THEN c.lastName
                        ELSE NULL
                    END, '; '
                )
                FROM itemCreators ic
                JOIN creators c ON ic.creatorID = c.creatorID
                WHERE ic.itemID = i.itemID
            ) as creators,
            (
                SELECT GROUP_CONCAT(t.name, '||')
                FROM itemTags itg
                JOIN tags t ON t.tagID = itg.tagID
                WHERE itg.itemID = i.itemID
            ) as tags,
            (
                SELECT GROUP_CONCAT(c.collectionName, '||')
                FROM collectionItems ci
                JOIN collections c ON c.collectionID = ci.collectionID
                WHERE ci.itemID = i.itemID
            ) as collections
        FROM items i
        JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
        LEFT JOIN itemData title_data ON i.itemID = title_data.itemID AND title_data.fieldID = 1
        LEFT JOIN itemDataValues title_val ON title_data.valueID = title_val.valueID
        LEFT JOIN itemData abstract_data ON i.itemID = abstract_data.itemID AND abstract_data.fieldID = 2
        LEFT JOIN itemDataValues abstract_val ON abstract_data.valueID = abstract_val.valueID
        LEFT JOIN itemData extra_data ON i.itemID = extra_data.itemID AND extra_data.fieldID = 16
        LEFT JOIN itemDataValues extra_val ON extra_data.valueID = extra_val.valueID
        LEFT JOIN fields doi_f ON doi_f.fieldName = 'DOI'
        LEFT JOIN itemData doi_data ON i.itemID = doi_data.itemID AND doi_data.fieldID = doi_f.fieldID
        LEFT JOIN itemDataValues doi_val ON doi_data.valueID = doi_val.valueID
        WHERE it.typeName NOT IN ('attachment', 'note', 'annotation')
        ORDER BY i.dateModified DESC
        """
        params: list[Any] = []
        if library_id is not None:
            query = query.replace(
                "WHERE it.typeName NOT IN ('attachment', 'note', 'annotation')",
                "WHERE it.typeName NOT IN ('attachment', 'note', 'annotation') AND i.libraryID = ?",
            )
            params.append(int(library_id))
        if collection_names:
            # Resolve collection IDs (including children) then filter items
            coll_ids = self._resolve_collection_ids(collection_names, library_id=library_id)
            if coll_ids:
                placeholders = ",".join("?" for _ in coll_ids)
                query = query.replace(
                    "ORDER BY i.dateModified DESC",
                    f"AND i.itemID IN (SELECT ci.itemID FROM collectionItems ci WHERE ci.collectionID IN ({placeholders})) ORDER BY i.dateModified DESC",
                )
                params.extend(coll_ids)
            else:
                # No matching collections found — return empty
                return []
        if limit:
            query += f" LIMIT {int(limit)}"

        items: list[IndexedZoteroItem] = []
        for row in conn.execute(query, params):
            extracted = self.extract_fulltext_for_item(row["itemID"]) if include_fulltext else None
            fulltext = extracted[0] if extracted else None
            fulltext_source = extracted[1] if extracted else None
            items.append(
                IndexedZoteroItem(
                    item_id=row["itemID"],
                    key=row["key"],
                    item_type_id=row["itemTypeID"],
                    item_type=row["item_type"],
                    doi=row["doi"],
                    title=row["title"],
                    abstract=row["abstract"],
                    creators=row["creators"],
                    fulltext=fulltext,
                    fulltext_source=fulltext_source,
                    notes=row["notes"],
                    extra=row["extra"],
                    date_added=row["dateAdded"],
                    date_modified=row["dateModified"],
                    tags=[tag for tag in str(row["tags"] or "").split("||") if tag],
                    collections=[name for name in str(row["collections"] or "").split("||") if name],
                )
            )
        return items


def get_local_zotero_reader() -> LocalZoteroReader | None:
    if not is_local_mode():
        return None
    try:
        return LocalZoteroReader()
    except FileNotFoundError:
        return None

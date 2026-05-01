from __future__ import annotations

import builtins
import json
import re
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from memory_mini.embeddings import (
    Embedder,
    cosine_similarity,
    pack_vector,
    require_numpy,
    unpack_vector,
)
from memory_mini.lifecycle import cleanup_cutoff, from_iso, iso_now, to_iso
from memory_mini.namespace import normalize_namespace
from memory_mini.types import Entry, EntryStatus


class Store:
    def __init__(
        self,
        path: str | Path = ":memory:",
        *,
        default_namespace: str = "default",
    ) -> None:
        self.path = str(path)
        self.default_namespace = normalize_namespace(default_namespace)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._fts_enabled = False
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY,
                key TEXT NOT NULL,
                namespace TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                content TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_accessed_at TEXT,
                expires_at TEXT,
                embedding BLOB,
                embedding_model TEXT,
                embedding_dims INTEGER,
                UNIQUE(namespace, key)
            )
            """
        )
        try:
            self.conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts
                USING fts5(key, namespace, content)
                """
            )
            self._fts_enabled = True
        except sqlite3.OperationalError:
            self._fts_enabled = False
        self.conn.commit()

    def _sync_fts(self, rowid: int, key: str, namespace: str, content: str) -> None:
        if not self._fts_enabled:
            return
        self.conn.execute("DELETE FROM entries_fts WHERE rowid = ?", (rowid,))
        self.conn.execute(
            "INSERT INTO entries_fts(rowid, key, namespace, content) VALUES (?, ?, ?, ?)",
            (rowid, key, namespace, content),
        )

    def _entry_from_row(self, row: sqlite3.Row) -> Entry:
        return Entry(
            key=str(row["key"]),
            value=str(row["content"]),
            namespace=str(row["namespace"]),
            status=EntryStatus(str(row["status"])),
            metadata=json.loads(str(row["metadata"])),
            created_at=from_iso(row["created_at"]),
            updated_at=from_iso(row["updated_at"]),
            last_accessed_at=from_iso(row["last_accessed_at"]),
            expires_at=from_iso(row["expires_at"]),
            embedding_model=row["embedding_model"],
            embedding_dims=row["embedding_dims"],
        )

    def store(
        self,
        key: str,
        value: str,
        ns: str | None = None,
        *,
        upsert: bool = True,
        metadata: dict[str, Any] | None = None,
        expires_at: datetime | str | None = None,
        embedding: Iterable[float] | None = None,
        embedding_model: str | None = None,
    ) -> Entry:
        namespace = normalize_namespace(ns or self.default_namespace)
        now = iso_now()
        metadata_json = json.dumps(metadata or {}, sort_keys=True)
        expires_iso = to_iso(expires_at)
        embedding_blob = None
        embedding_dims = None
        if embedding is not None:
            embedding_blob, embedding_dims = pack_vector(embedding)

        if upsert:
            self.conn.execute(
                """
                INSERT INTO entries (
                    key, namespace, status, content, metadata, created_at, updated_at, expires_at,
                    embedding, embedding_model, embedding_dims
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(namespace, key) DO UPDATE SET
                    status = excluded.status,
                    content = excluded.content,
                    metadata = excluded.metadata,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at,
                    embedding = excluded.embedding,
                    embedding_model = excluded.embedding_model,
                    embedding_dims = excluded.embedding_dims
                """,
                (
                    key,
                    namespace,
                    EntryStatus.ACTIVE.value,
                    value,
                    metadata_json,
                    now,
                    now,
                    expires_iso,
                    embedding_blob,
                    embedding_model,
                    embedding_dims,
                ),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO entries (
                    key, namespace, status, content, metadata, created_at, updated_at, expires_at,
                    embedding, embedding_model, embedding_dims
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    namespace,
                    EntryStatus.ACTIVE.value,
                    value,
                    metadata_json,
                    now,
                    now,
                    expires_iso,
                    embedding_blob,
                    embedding_model,
                    embedding_dims,
                ),
            )
        row = self.conn.execute(
            "SELECT id FROM entries WHERE namespace = ? AND key = ?", (namespace, key)
        ).fetchone()
        if row is None:
            raise RuntimeError("stored entry row was not found")
        self._sync_fts(int(row["id"]), key, namespace, value)
        self.conn.commit()
        result = self.get(key, namespace, include_deleted=True)
        if result is None:
            raise RuntimeError("stored entry could not be read back")
        return result

    def get(
        self,
        key: str,
        ns: str | None = None,
        *,
        include_deleted: bool = False,
    ) -> Entry | None:
        namespace = normalize_namespace(ns or self.default_namespace)
        row = self.conn.execute(
            "SELECT * FROM entries WHERE namespace = ? AND key = ?", (namespace, key)
        ).fetchone()
        if row is None:
            return None
        entry = self._entry_from_row(row)
        if self._is_expired(entry):
            self._mark_expired(namespace, key)
            if include_deleted:
                expired_row = self.conn.execute(
                    "SELECT * FROM entries WHERE namespace = ? AND key = ?", (namespace, key)
                ).fetchone()
                if expired_row is None:
                    return None
                return self._entry_from_row(expired_row)
            return None
        if not include_deleted and entry.status is not EntryStatus.ACTIVE:
            return None
        self.conn.execute(
            "UPDATE entries SET last_accessed_at = ? WHERE namespace = ? AND key = ?",
            (iso_now(), namespace, key),
        )
        self.conn.commit()
        updated_row = self.conn.execute(
            "SELECT * FROM entries WHERE namespace = ? AND key = ?", (namespace, key)
        )
        updated = updated_row.fetchone()
        if updated is None:
            return None
        return self._entry_from_row(updated)

    def list(
        self, ns: str | None = None, *, include_deleted: bool = False
    ) -> builtins.list[Entry]:
        params: builtins.list[Any] = []
        where = []
        if ns is not None:
            where.append("namespace = ?")
            params.append(normalize_namespace(ns))
        if not include_deleted:
            where.append("status = ?")
            params.append(EntryStatus.ACTIVE.value)
        sql = "SELECT * FROM entries"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY namespace, key"
        rows = self.conn.execute(sql, params).fetchall()
        entries = [self._entry_from_row(row) for row in rows]
        return [entry for entry in entries if include_deleted or not self._is_expired(entry)]

    def search(
        self,
        text: str,
        ns: str | None = None,
        *,
        mode: str = "prefix",
        include_deleted: bool = False,
        limit: int = 20,
    ) -> builtins.list[Entry]:
        if mode == "prefix":
            matches = [
                entry
                for entry in self.list(ns, include_deleted=include_deleted)
                if entry.key.startswith(text)
            ]
            return matches[:limit]
        if mode == "regex":
            pattern = re.compile(text)
            return [
                entry
                for entry in self.list(ns, include_deleted=include_deleted)
                if pattern.search(entry.key) or pattern.search(entry.value)
            ][:limit]
        if mode == "fts":
            return self._search_fts(text, ns, include_deleted, limit)
        raise ValueError(f"unknown search mode: {mode}")

    def _search_fts(
        self, text: str, ns: str | None, include_deleted: bool, limit: int
    ) -> builtins.list[Entry]:
        if not self._fts_enabled:
            return [
                entry
                for entry in self.list(ns, include_deleted=include_deleted)
                if text.lower() in entry.value.lower() or text.lower() in entry.key.lower()
            ][:limit]
        namespace = normalize_namespace(ns) if ns is not None else None
        params: builtins.list[Any] = [text]
        sql = """
            SELECT entries.* FROM entries_fts
            JOIN entries ON entries_fts.rowid = entries.id
            WHERE entries_fts MATCH ?
        """
        if namespace is not None:
            sql += " AND entries.namespace = ?"
            params.append(namespace)
        if not include_deleted:
            sql += " AND entries.status = ?"
            params.append(EntryStatus.ACTIVE.value)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        return [self._entry_from_row(row) for row in self.conn.execute(sql, params).fetchall()]

    def soft_delete(self, key: str, ns: str | None = None) -> bool:
        namespace = normalize_namespace(ns or self.default_namespace)
        cursor = self.conn.execute(
            "UPDATE entries SET status = ?, updated_at = ? WHERE namespace = ? AND key = ?",
            (EntryStatus.SOFT_DELETED.value, iso_now(), namespace, key),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def cleanup(
        self,
        *,
        retention: timedelta | None = timedelta(days=30),
        all_deleted: bool = False,
    ) -> int:
        params: builtins.list[Any] = [EntryStatus.SOFT_DELETED.value]
        sql = "DELETE FROM entries WHERE status = ?"
        cutoff = cleanup_cutoff(retention)
        if not all_deleted and cutoff is not None:
            sql += " AND updated_at < ?"
            params.append(cutoff)
        cursor = self.conn.execute(sql, params)
        self.conn.commit()
        return cursor.rowcount

    def stats(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS count FROM entries GROUP BY status"
        ).fetchall()
        result = {status.value: 0 for status in EntryStatus}
        for row in rows:
            result[str(row["status"])] = int(row["count"])
        result["total"] = sum(result.values())
        return result

    def namespaces(self) -> builtins.list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT namespace FROM entries ORDER BY namespace"
        ).fetchall()
        return [str(row["namespace"]) for row in rows]

    def vector_search(  # pragma: no cover
        self,
        vector: Iterable[float],
        *,
        ns: str | None = None,
        k: int = 5,
        include_deleted: bool = False,
    ) -> builtins.list[tuple[Entry, float]]:
        require_numpy()
        query = [float(value) for value in vector]
        namespace = normalize_namespace(ns) if ns is not None else None
        params: builtins.list[Any] = []
        sql = "SELECT * FROM entries WHERE embedding IS NOT NULL"
        if namespace is not None:
            sql += " AND namespace = ?"
            params.append(namespace)
        if not include_deleted:
            sql += " AND status = ?"
            params.append(EntryStatus.ACTIVE.value)
        rows = self.conn.execute(sql, params).fetchall()
        scored: builtins.list[tuple[Entry, float]] = []
        for row in rows:
            dims = int(row["embedding_dims"])
            if dims != len(query):
                continue
            score = cosine_similarity(query, unpack_vector(row["embedding"], dims))
            scored.append((self._entry_from_row(row), score))
        return sorted(scored, key=lambda item: item[1], reverse=True)[:k]

    def embed_and_store(
        self,
        key: str,
        value: str,
        embedder: Embedder,
        ns: str | None = None,
        *,
        model: str = "custom",
        metadata: dict[str, Any] | None = None,
    ) -> Entry:
        return self.store(
            key,
            value,
            ns,
            metadata=metadata,
            embedding=embedder(value),
            embedding_model=model,
        )

    def embed_and_search(  # pragma: no cover
        self,
        text: str,
        embedder: Embedder,
        *,
        ns: str | None = None,
        k: int = 5,
    ) -> builtins.list[tuple[Entry, float]]:
        return self.vector_search(embedder(text), ns=ns, k=k)

    def _is_expired(self, entry: Entry) -> bool:
        return entry.expires_at is not None and entry.expires_at <= datetime.now(
            entry.expires_at.tzinfo
        )

    def _mark_expired(self, namespace: str, key: str) -> None:
        self.conn.execute(
            "UPDATE entries SET status = ?, updated_at = ? WHERE namespace = ? AND key = ?",
            (EntryStatus.EXPIRED.value, iso_now(), namespace, key),
        )
        self.conn.commit()

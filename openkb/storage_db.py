"""SQLite-backed storage engine for OpenKB.

Optional replacement for file-based wiki storage. Stores pages, hashes,
and metadata in a SQLite database for better scalability with large
knowledge bases.

Enabled by setting `storage_engine: sqlite` in `.openkb/config.yaml`.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class StorageDB:
    """SQLite database for wiki storage."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def init_schema(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS pages (
                path TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS hashes (
                hash TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                pages INTEGER DEFAULT 0,
                indexed_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS concepts (
                slug TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                brief TEXT NOT NULL DEFAULT '',
                parent TEXT REFERENCES concepts(slug),
                sources TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_concepts_parent ON concepts(parent);
            CREATE INDEX IF NOT EXISTS idx_pages_updated ON pages(updated_at);
        """)
        self.conn.commit()

    def write_page(self, path: str, content: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO pages (path, content, updated_at) VALUES (?, ?, datetime('now'))",
            (path, content),
        )
        self.conn.commit()

    def read_page(self, path: str) -> str | None:
        row = self.conn.execute("SELECT content FROM pages WHERE path = ?", (path,)).fetchone()
        return row["content"] if row else None

    def delete_page(self, path: str) -> bool:
        cur = self.conn.execute("DELETE FROM pages WHERE path = ?", (path,))
        self.conn.commit()
        return cur.rowcount > 0

    def list_pages(self, prefix: str = "") -> list[str]:
        if prefix:
            rows = self.conn.execute(
                "SELECT path FROM pages WHERE path LIKE ? ORDER BY path",
                (prefix + "%",),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT path FROM pages ORDER BY path").fetchall()
        return [r["path"] for r in rows]

    def page_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]

    def search_pages(self, pattern: str, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT path, content FROM pages WHERE content LIKE ? LIMIT ?",
            (f"%{pattern}%", limit),
        ).fetchall()
        results = []
        for r in rows:
            content = r["content"]
            idx = content.lower().find(pattern.lower())
            start = max(0, idx - 40)
            snippet = content[start:idx + len(pattern) + 60]
            results.append({"path": r["path"], "snippet": snippet})
        return results

    def add_hash(self, file_hash: str, name: str, doc_type: str, pages: int = 0) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO hashes (hash, name, type, pages, indexed_at) VALUES (?, ?, ?, ?, datetime('now'))",
            (file_hash, name, doc_type, pages),
        )
        self.conn.commit()

    def is_known_hash(self, file_hash: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM hashes WHERE hash = ?", (file_hash,)).fetchone()
        return row is not None

    def get_hashes(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM hashes ORDER BY indexed_at DESC").fetchall()
        return [dict(r) for r in rows]

    def upsert_concept(self, slug: str, title: str, brief: str = "", parent: str | None = None, sources: list[str] | None = None) -> None:
        existing = self.conn.execute("SELECT 1 FROM concepts WHERE slug = ?", (slug,)).fetchone()
        if existing:
            self.conn.execute(
                "UPDATE concepts SET title = ?, brief = ?, parent = ?, sources = ?, updated_at = datetime('now') WHERE slug = ?",
                (title, brief, parent, json.dumps(sources or []), slug),
            )
        else:
            self.conn.execute(
                "INSERT INTO concepts (slug, title, brief, parent, sources) VALUES (?, ?, ?, ?, ?)",
                (slug, title, brief, parent, json.dumps(sources or [])),
            )
        self.conn.commit()

    def get_concept(self, slug: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM concepts WHERE slug = ?", (slug,)).fetchone()
        if row:
            r = dict(row)
            r["sources"] = json.loads(r["sources"])
            return r
        return None

    def list_concepts(self, parent: str | None = None) -> list[dict]:
        if parent is not None:
            rows = self.conn.execute(
                "SELECT * FROM concepts WHERE parent = ? ORDER BY title", (parent,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM concepts ORDER BY title").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["sources"] = json.loads(d["sources"])
            d["children"] = self.conn.execute(
                "SELECT COUNT(*) FROM concepts WHERE parent = ?", (d["slug"],)
            ).fetchone()[0]
            result.append(d)
        return result

    def concept_tree(self) -> list[dict]:
        """Return full concept hierarchy as nested tree."""
        rows = self.conn.execute(
            "SELECT * FROM concepts WHERE parent IS NULL ORDER BY title"
        ).fetchall()
        tree = []
        for r in rows:
            node = dict(r)
            node["sources"] = json.loads(node["sources"])
            node["children"] = self._get_child_concepts(node["slug"])
            tree.append(node)
        return tree

    def _get_child_concepts(self, parent_slug: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM concepts WHERE parent = ? ORDER BY title", (parent_slug,)
        ).fetchall()
        return [
            {**dict(r), "sources": json.loads(dict(r)["sources"]),
             "children": self._get_child_concepts(dict(r)["slug"])}
            for r in rows
        ]

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, value)
        )
        self.conn.commit()

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


def get_storage(kb_dir: Path) -> StorageDB | None:
    """Return StorageDB if SQLite storage is enabled in config."""
    from openkb.config import load_config
    config = load_config(kb_dir / ".openkb" / "config.yaml")
    if config.get("storage_engine") == "sqlite":
        db_path = kb_dir / ".openkb" / "openkb.db"
        db = StorageDB(db_path)
        db.init_schema()
        return db
    return None

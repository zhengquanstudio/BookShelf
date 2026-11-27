"""系列/套书仓储。"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..connection import Database
from . import utc_now

_WRITABLE = {"name", "author_id", "total_volumes", "locked"}


class SeriesRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, series_id: int) -> sqlite3.Row | None:
        return self.db.query_one("SELECT * FROM series WHERE id = ?", (series_id,))

    def find(self, name: str, author_id: int | None = None) -> sqlite3.Row | None:
        if author_id is None:
            return self.db.query_one(
                "SELECT * FROM series WHERE name = ? AND author_id IS NULL", (name,)
            )
        return self.db.query_one(
            "SELECT * FROM series WHERE name = ? AND author_id = ?", (name, author_id)
        )

    def create(self, name: str, **fields: Any) -> int:
        if not (name or "").strip():
            raise ValueError("系列名不能为空")
        data = {k: v for k, v in fields.items() if k in _WRITABLE}
        data["name"] = name.strip()
        data.setdefault("locked", 0)
        now = utc_now()
        data["created_at"] = now
        data["updated_at"] = now
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        return self.db.execute(
            f"INSERT INTO series ({cols}) VALUES ({marks})", tuple(data.values())
        )

    def ensure(self, name: str, author_id: int | None = None, **fields: Any) -> int:
        row = self.find(name, author_id)
        if row is not None:
            return int(row["id"])
        try:
            return self.create(name, author_id=author_id, **fields)
        except sqlite3.IntegrityError:
            row = self.find(name, author_id)
            if row is None:
                raise
            return int(row["id"])

    def update(self, series_id: int, **fields: Any) -> int:
        data = {k: v for k, v in fields.items() if k in _WRITABLE}
        if not data:
            return 0
        data["updated_at"] = utc_now()
        sets = ", ".join(f"{key} = ?" for key in data)
        with self.db.transaction() as conn:
            cur = conn.execute(
                f"UPDATE series SET {sets} WHERE id = ?", (*data.values(), series_id)
            )
            return cur.rowcount

    def list(self, author_id: int | None = None) -> list[sqlite3.Row]:
        sql = (
            "SELECT s.*, a.name_zh AS author_name FROM series AS s "
            "LEFT JOIN authors AS a ON a.id = s.author_id"
        )
        params: tuple[int, ...] = ()
        if author_id is not None:
            sql += " WHERE s.author_id = ?"
            params = (author_id,)
        return self.db.query(sql + " ORDER BY s.name", params)

    def delete(self, series_id: int) -> int:
        with self.db.transaction() as conn:
            cur = conn.execute("DELETE FROM series WHERE id = ?", (series_id,))
            return cur.rowcount

    def volumes(self, series_id: int) -> list[sqlite3.Row]:
        """系列内各卷（按卷号排序）。"""
        return self.db.query(
            "SELECT * FROM books WHERE series_id = ? ORDER BY volume, id", (series_id,)
        )

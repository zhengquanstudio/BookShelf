"""作者仓储：中文名/原文/国别唯一定位，别名合并。"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..connection import Database
from . import utc_now

_WRITABLE = {
    "name_zh",
    "name_orig",
    "country",
    "country_code",
    "is_chinese",
    "alias_json",
    "locked",
}


class AuthorRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, author_id: int) -> sqlite3.Row | None:
        return self.db.query_one("SELECT * FROM authors WHERE id = ?", (author_id,))

    def find(
        self, name_zh: str, name_orig: str | None = None, country: str | None = None
    ) -> sqlite3.Row | None:
        """按唯一键（中文名, 原文, 国别）查询。"""
        return self.db.query_one(
            "SELECT * FROM authors WHERE name_zh = ? "
            "AND IFNULL(name_orig, '') = IFNULL(?, '') "
            "AND IFNULL(country, '') = IFNULL(?, '')",
            (name_zh, name_orig, country),
        )

    def create(self, name_zh: str, **fields: Any) -> int:
        if not (name_zh or "").strip():
            raise ValueError("作者中文名不能为空")
        data = {k: v for k, v in fields.items() if k in _WRITABLE}
        data["name_zh"] = name_zh.strip()
        now = utc_now()
        data.setdefault("alias_json", "[]")
        data.setdefault("is_chinese", 0)
        data.setdefault("locked", 0)
        data["created_at"] = now
        data["updated_at"] = now
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        return self.db.execute(
            f"INSERT INTO authors ({cols}) VALUES ({marks})", tuple(data.values())
        )

    def ensure(self, name_zh: str, **fields: Any) -> int:
        """存在则返回已有 id，不存在则创建。"""
        row = self.find(name_zh, fields.get("name_orig"), fields.get("country"))
        if row is not None:
            return int(row["id"])
        try:
            return self.create(name_zh, **fields)
        except sqlite3.IntegrityError:
            row = self.find(name_zh, fields.get("name_orig"), fields.get("country"))
            if row is None:
                raise
            return int(row["id"])

    def update(self, author_id: int, **fields: Any) -> int:
        data = {k: v for k, v in fields.items() if k in _WRITABLE}
        if not data:
            return 0
        data["updated_at"] = utc_now()
        sets = ", ".join(f"{key} = ?" for key in data)
        with self.db.transaction() as conn:
            cur = conn.execute(
                f"UPDATE authors SET {sets} WHERE id = ?", (*data.values(), author_id)
            )
            return cur.rowcount

    def list(self, search: str | None = None, limit: int = 1000) -> list[sqlite3.Row]:
        if search:
            like = f"%{search.strip()}%"
            return self.db.query(
                "SELECT * FROM authors WHERE name_zh LIKE ? OR name_orig LIKE ? "
                "ORDER BY name_zh LIMIT ?",
                (like, like, limit),
            )
        return self.db.query("SELECT * FROM authors ORDER BY name_zh LIMIT ?", (limit,))

    def list_with_counts(self, search: str | None = None) -> list[sqlite3.Row]:
        """作者目录数据，附带书籍数；筛选在 SQL 层完成。"""
        where = ""
        params: tuple[str, ...] = ()
        if search and search.strip():
            like = f"%{search.strip()}%"
            where = "WHERE a.name_zh LIKE ? OR a.name_orig LIKE ? OR a.country LIKE ?"
            params = (like, like, like)
        return self.db.query(
            "SELECT a.*, COUNT(b.id) AS book_count FROM authors AS a "
            "LEFT JOIN books AS b ON b.author_id = a.id "
            f"{where} GROUP BY a.id ORDER BY a.name_zh",
            params,
        )

    def merge(self, source_id: int, target_id: int) -> int:
        """显式合并作者，保留目标作者并把来源名称写入别名。"""
        if source_id == target_id:
            raise ValueError("不能合并到同一个作者")
        with self.db.transaction() as conn:
            source = conn.execute("SELECT * FROM authors WHERE id = ?", (source_id,)).fetchone()
            target = conn.execute("SELECT * FROM authors WHERE id = ?", (target_id,)).fetchone()
            if source is None or target is None:
                raise ValueError("要合并的作者不存在")
            aliases = json.loads(target["alias_json"] or "[]")
            for value in (
                source["name_zh"], source["name_orig"],
                *json.loads(source["alias_json"] or "[]"),
            ):
                if value and value not in aliases:
                    aliases.append(value)
            now = utc_now()
            moved = conn.execute(
                "UPDATE books SET author_id = ?, updated_at = ? WHERE author_id = ?",
                (target_id, now, source_id),
            ).rowcount
            conn.execute(
                "UPDATE series SET author_id = ?, updated_at = ? WHERE author_id = ?",
                (target_id, now, source_id),
            )
            conn.execute(
                "UPDATE authors SET alias_json = ?, locked = 1, updated_at = ? WHERE id = ?",
                (json.dumps(aliases, ensure_ascii=False), now, target_id),
            )
            conn.execute("DELETE FROM authors WHERE id = ?", (source_id,))
            return int(moved)

    def find_by_alias(self, alias: str) -> sqlite3.Row | None:
        """在 alias_json 数组中查找别名。"""
        try:
            return self.db.query_one(
                "SELECT a.* FROM authors AS a, json_each(a.alias_json) AS j "
                "WHERE j.value = ? LIMIT 1",
                (alias,),
            )
        except sqlite3.OperationalError:  # 未启用 JSON1 时退化为模糊匹配
            return self.db.query_one(
                "SELECT * FROM authors WHERE alias_json LIKE ? LIMIT 1",
                (f'%"{alias}"%',),
            )

    def add_alias(self, author_id: int, alias: str) -> None:
        """把别名加入数组（幂等）。"""
        row = self.get(author_id)
        if row is None:
            raise ValueError(f"作者不存在：{author_id}")
        aliases = json.loads(row["alias_json"] or "[]")
        if alias and alias not in aliases:
            aliases.append(alias)
            self.update(author_id, alias_json=json.dumps(aliases, ensure_ascii=False))

"""书籍仓储：增删改查、分页、状态统计。"""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Iterable, Mapping

from ..connection import Database
from . import utc_now

SOURCE_RANK = {"manual": 3, "metadata": 2, "filename": 1, "embedded": 0}
_RANK_SOURCE = {rank: source for source, rank in SOURCE_RANK.items()}
_NETWORK_SOURCES = {
    "import", "network", "openlibrary", "googlebooks", "douban", "crossref", "kongfz", "pdc"
}


def _source_rank(source: Any) -> int:
    name = str(source or "embedded").strip().lower()
    if name in SOURCE_RANK:
        return SOURCE_RANK[name]
    return SOURCE_RANK["metadata"] if name in _NETWORK_SOURCES else 0


def _richness(value: Any) -> tuple[bool, int, bool]:
    text = str(value or "").strip()
    has_subtitle = any(mark in text for mark in (":", "：", "—", "–", "-"))
    return has_subtitle, len(text), not text.isdigit()


# 允许写入的列白名单，避免外部字段名拼进 SQL。
_WRITABLE = {
    "file_path",
    "quick_hash",
    "full_hash",
    "file_size",
    "file_mtime",
    "format",
    "title",
    "subtitle",
    "author_id",
    "author_raw",
    "isbn",
    "publisher",
    "publish_date",
    "language",
    "series_id",
    "volume",
    "volume_raw",
    "description",
    "cover_path",
    "page_count",
    "meta_source",
    "confidence",
    "status",
    "drm_protected",
    "dup_group_id",
    "dup_of",
}

_SORTABLE = {"id", "title", "publish_date", "added_at", "updated_at", "file_size", "confidence"}

# 书的实际存放位置：整理成功的取归档目标，否则取原始文件路径。
_PHYSICAL_PATH = (
    "COALESCE((SELECT li.target_path FROM library_items AS li "
    "WHERE li.book_id = books.id AND li.result <> 'skipped' "
    "AND IFNULL(li.target_path, '') <> '' ORDER BY li.id DESC LIMIT 1), "
    "books.file_path)"
)


def _like_prefix(folder: str) -> str:
    escaped = folder.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return escaped + os.sep + "%"


class BookRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---- 写 ---------------------------------------------------------
    def create(self, **fields: Any) -> int:
        """插入一本书，返回 id；缺省时间戳自动补齐。"""
        data = {k: v for k, v in fields.items() if k in _WRITABLE}
        if not data.get("file_path"):
            raise ValueError("file_path 不能为空")
        data.setdefault("quick_hash", "")
        data.setdefault("format", "unknown")
        data.setdefault("status", "pending")
        now = utc_now()
        data.setdefault("added_at", now)
        data["updated_at"] = now
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        sql = f"INSERT INTO books ({cols}) VALUES ({marks})"
        try:
            return self.db.execute(sql, tuple(data.values()))
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"书籍路径重复：{data['file_path']}") from exc

    def update(self, book_id: int, **fields: Any) -> int:
        """更新指定列，返回受影响行数。"""
        data = {k: v for k, v in fields.items() if k in _WRITABLE}
        if not data:
            return 0
        data["updated_at"] = utc_now()
        sets = ", ".join(f"{key} = ?" for key in data)
        with self.db.transaction() as conn:
            cur = conn.execute(
                f"UPDATE books SET {sets} WHERE id = ?", (*data.values(), book_id)
            )
            return cur.rowcount

    def merge_meta(
        self, book_id: int, incoming: Mapping[str, Any], source_rank: int
    ) -> int:
        """按来源优先级合并非空元数据，不让低优先级来源降级手填内容。"""
        row = self.get(book_id)
        if row is None:
            return 0
        current_rank = _source_rank(row["meta_source"])
        updates: dict[str, Any] = {}
        for key, value in incoming.items():
            if key not in _WRITABLE or key == "meta_source":
                continue
            if value is None or value == 0 or (isinstance(value, str) and not value.strip()):
                continue
            current = row[key]
            current_empty = current is None or (isinstance(current, str) and not current.strip())
            richer_title = (
                key == "title"
                and source_rank == current_rank
                and _richness(value) > _richness(current)
            )
            if current_empty or source_rank > current_rank or richer_title:
                updates[key] = value
        if updates and source_rank > current_rank:
            updates["meta_source"] = _RANK_SOURCE.get(source_rank, str(source_rank))
        return self.update(book_id, **updates) if updates else 0

    def set_status(self, book_id: int, status: str, **extra: Any) -> int:
        return self.update(book_id, status=status, **extra)

    def delete(self, book_id: int) -> int:
        with self.db.transaction() as conn:
            cur = conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
            return cur.rowcount

    # ---- 读 ---------------------------------------------------------
    def get(self, book_id: int) -> sqlite3.Row | None:
        return self.db.query_one("SELECT * FROM books WHERE id = ?", (book_id,))

    def find_by_path(self, file_path: str) -> sqlite3.Row | None:
        return self.db.query_one("SELECT * FROM books WHERE file_path = ?", (file_path,))

    def find_by_hash(self, quick_hash: str) -> list[sqlite3.Row]:
        return self.db.query(
            "SELECT * FROM books WHERE quick_hash = ? ORDER BY id", (quick_hash,)
        )

    def _where(
        self,
        *,
        status: str | Iterable[str] | None = None,
        formats: Iterable[str] | None = None,
        author_id: int | None = None,
        series_id: int | None = None,
        tag: str | None = None,
        folder: str | None = None,
        search: str | None = None,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            if isinstance(status, str):
                clauses.append("books.status = ?")
                params.append(status)
            else:
                values = list(status)
                if values:
                    clauses.append(f"books.status IN ({', '.join('?' for _ in values)})")
                    params.extend(values)
        if formats:
            values = list(formats)
            if values:
                clauses.append(f"books.format IN ({', '.join('?' for _ in values)})")
                params.extend(values)
        if author_id is not None:
            clauses.append("books.author_id = ?")
            params.append(author_id)
        if series_id is not None:
            clauses.append("books.series_id = ?")
            params.append(series_id)
        if tag:
            clauses.append(
                "EXISTS (SELECT 1 FROM book_tags AS bt JOIN tags AS t ON t.id = bt.tag_id "
                "WHERE bt.book_id = books.id AND t.name = ?)"
            )
            params.append(tag)
        if folder:
            clauses.append(f"{_PHYSICAL_PATH} LIKE ? ESCAPE '!'")
            params.append(_like_prefix(folder))
        if search:
            like = f"%{search.strip()}%"
            clauses.append("(books.title LIKE ? OR books.author_raw LIKE ? OR books.isbn LIKE ?)")
            params.extend([like, like, like])
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, params

    def list(
        self,
        page: int = 1,
        page_size: int = 50,
        *,
        status: str | Iterable[str] | None = None,
        formats: Iterable[str] | None = None,
        author_id: int | None = None,
        series_id: int | None = None,
        tag: str | None = None,
        folder: str | None = None,
        search: str | None = None,
        sort: str = "updated_at",
        desc: bool = True,
    ) -> list[sqlite3.Row]:
        """分页查询，排序与筛选都在 SQL 层完成。"""
        page = max(1, int(page))
        page_size = min(max(1, int(page_size)), 1000)
        column = sort if sort in _SORTABLE else "updated_at"
        direction = "DESC" if desc else "ASC"
        where, params = self._where(
            status=status,
            formats=formats,
            author_id=author_id,
            series_id=series_id,
            tag=tag,
            folder=folder,
            search=search,
        )
        sql = (
            "SELECT books.*, authors.name_zh AS author_name, "
            "authors.country AS country, series.name AS series_name "
            "FROM books "
            "LEFT JOIN authors ON authors.id = books.author_id "
            "LEFT JOIN series ON series.id = books.series_id"
            f"{where} "
            f"ORDER BY books.{column} {direction}, books.id {direction} "
            "LIMIT ? OFFSET ?"
        )
        params.extend([page_size, (page - 1) * page_size])
        return self.db.query(sql, tuple(params))

    def count(
        self,
        *,
        status: str | Iterable[str] | None = None,
        formats: Iterable[str] | None = None,
        author_id: int | None = None,
        series_id: int | None = None,
        tag: str | None = None,
        folder: str | None = None,
        search: str | None = None,
    ) -> int:
        where, params = self._where(
            status=status,
            formats=formats,
            author_id=author_id,
            series_id=series_id,
            tag=tag,
            folder=folder,
            search=search,
        )
        row = self.db.query_one(f"SELECT COUNT(*) AS n FROM books{where}", tuple(params))
        return int(row["n"]) if row else 0

    def count_by_status(self) -> dict[str, int]:
        rows = self.db.query("SELECT status, COUNT(*) AS n FROM books GROUP BY status")
        return {row["status"]: int(row["n"]) for row in rows}

    def duplicates(self) -> list[sqlite3.Row]:
        """按 quick_hash 找出重复书籍（同一内容多个文件）。"""
        return self.db.query(
            "SELECT quick_hash, COUNT(*) AS n FROM books "
            "GROUP BY quick_hash HAVING n > 1 ORDER BY n DESC"
        )

"""本地规范化：作者、卷号、系列；不联网。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core import naming, series
from ..db.connection import Database
from ..db.repositories.book_repo import BookRepository
from .author_service import AuthorService
from .series_service import SeriesService


def normalize_book(db: Database, book_id: int, *, rebuild: bool = False) -> dict[str, Any]:
    """把一本书的作者/卷号/系列补齐，返回最新记录。"""
    books = BookRepository(db)
    book = books.get(book_id)
    if book is None:
        return {}
    fields: dict[str, Any] = {}
    title = str(book["title"] or "")
    stem = Path(str(book["file_path"] or "")).stem

    volume = book["volume"]
    if not volume:
        match = series.extract_volume(title) or series.extract_volume(stem)
        if match:
            fields["volume"] = match.volume
            fields["volume_raw"] = book["volume_raw"] or match.raw
            volume = match.volume

    if not title or title == stem:
        cleaned = naming.clean_text(stem, max_len=120)
        if cleaned and series.extract_volume(cleaned):
            cleaned = series.strip_volume(cleaned) or cleaned
        if cleaned and cleaned != title:
            fields["title"] = cleaned
            title = cleaned

    if fields:
        books.update(book_id, **fields)

    author_id = book["author_id"]
    if not author_id and (book["author_raw"] or book["title"]):
        author_id = AuthorService(db).assign_book(book_id, book["author_raw"] or "")

    if author_id:
        SeriesService(db).assign(
            book_id,
            title=title,
            series_name=None,
            series_index=book["volume_raw"],
            volume=volume,
            author_id=int(author_id),
        )
        if rebuild:
            SeriesService(db).rebuild_for_author(int(author_id))
    return dict(books.get(book_id) or {})


def normalize_library(db: Database, *, limit: int | None = None) -> dict[str, int]:
    """批量规范化现有书库；返回处理的书籍数与归入系列的书籍数。"""
    books = BookRepository(db)
    rows = db.query("SELECT id FROM books ORDER BY id" + (f" LIMIT {int(limit)}" if limit else ""))
    touched = 0
    for row in rows:
        normalize_book(db, int(row["id"]))
        touched += 1
    assigned = SeriesService(db).rebuild_all()
    return {"books": touched, "series_assigned": assigned}

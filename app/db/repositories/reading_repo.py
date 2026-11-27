"""阅读进度、书签与高亮仓储。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from ..connection import Database
from . import utc_now


class ReadingRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---- 进度 -------------------------------------------------------
    def save_progress(
        self,
        book_id: int,
        locator_json: str,
        percent: float,
        seconds_delta: int = 0,
    ) -> None:
        """写入阅读进度；累计阅读时长按增量累加。"""
        now = utc_now()
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO reading_state"
                "(book_id, locator_json, percent, last_read_at, total_seconds) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(book_id) DO UPDATE SET "
                "locator_json=excluded.locator_json, percent=excluded.percent, "
                "last_read_at=excluded.last_read_at, "
                "total_seconds=reading_state.total_seconds + excluded.total_seconds",
                (book_id, locator_json, float(percent), now, max(0, int(seconds_delta))),
            )

    def get_progress(self, book_id: int) -> sqlite3.Row | None:
        return self.db.query_one(
            "SELECT * FROM reading_state WHERE book_id = ?", (book_id,)
        )

    # ---- 阅读会话 ---------------------------------------------------
    def start_session(self, book_id: int, device: str = "desktop") -> int:
        """开始一次阅读会话，返回会话 id；时间按本地时区记录。"""
        started = datetime.now().astimezone().isoformat(timespec="seconds")
        return self.db.execute(
            "INSERT INTO reading_sessions(book_id, started_at, device) VALUES (?, ?, ?)",
            (int(book_id), started, device),
        )

    def add_session_progress(
        self, session_id: int, seconds: int, pages: int = 0
    ) -> None:
        """按增量累加会话阅读秒数与翻页数。"""
        seconds = max(0, int(seconds))
        pages = max(0, int(pages))
        if seconds == 0 and pages == 0:
            return
        self.db.execute(
            "UPDATE reading_sessions SET seconds = seconds + ?, pages = pages + ? "
            "WHERE id = ?",
            (seconds, pages, int(session_id)),
        )

    def end_session(self, session_id: int) -> None:
        """结束会话并记录结束时间。"""
        ended = datetime.now().astimezone().isoformat(timespec="seconds")
        self.db.execute(
            "UPDATE reading_sessions SET ended_at = ? WHERE id = ?",
            (ended, int(session_id)),
        )

    # ---- 书签 / 高亮 ------------------------------------------------
    def add_bookmark(
        self,
        book_id: int,
        locator_json: str,
        *,
        chapter: str | None = None,
        text: str | None = None,
        note: str | None = None,
        color: str = "#ffe08a",
        kind: str = "bookmark",
    ) -> int:
        return self.db.execute(
            "INSERT INTO bookmarks"
            "(book_id, locator_json, chapter, text, note, color, kind, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (book_id, locator_json, chapter, text, note, color, kind, utc_now()),
        )

    def list_bookmarks(self, book_id: int, kind: str | None = None) -> list[Any]:
        if kind:
            return self.db.query(
                "SELECT * FROM bookmarks WHERE book_id = ? AND kind = ? ORDER BY id",
                (book_id, kind),
            )
        return self.db.query(
            "SELECT * FROM bookmarks WHERE book_id = ? ORDER BY id", (book_id,)
        )

    def delete_bookmark(self, bookmark_id: int) -> int:
        with self.db.transaction() as conn:
            cur = conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
            return cur.rowcount

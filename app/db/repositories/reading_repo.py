"""阅读进度、书签与高亮仓储。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
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

    # ---- 阅读统计（T21） ---------------------------------------------
    def reading_dashboard(
        self, *, now: datetime | None = None, months: int = 6, recent_limit: int = 10
    ) -> dict[str, Any]:
        """统计页唯一数据入口；所有聚合与连续天数均在此处计算。"""
        now = now or datetime.now().astimezone()
        total = self.db.query_one(
            "SELECT COALESCE(SUM(total_seconds), 0) AS seconds FROM reading_state"
        )
        month = self.db.query_one(
            "SELECT COALESCE(SUM(seconds), 0) AS seconds FROM reading_sessions "
            "WHERE substr(started_at, 1, 7) = ?",
            (f"{now.year:04d}-{now.month:02d}",),
        )
        finished = self.db.query_one(
            "SELECT COUNT(*) AS count FROM books WHERE read_state = 'finished'"
        )
        days = self.db.query(
            "SELECT DISTINCT substr(started_at, 1, 10) AS day FROM reading_sessions "
            "WHERE seconds > 0 ORDER BY day DESC"
        )
        reading_days = {str(row["day"]) for row in days}
        today = now.date()
        # 今天尚未阅读时，允许从昨天续算；否则刷新页面会把昨天的连续记录清零。
        cursor = today if today.isoformat() in reading_days else today - timedelta(days=1)
        if cursor.isoformat() not in reading_days:
            streak = 0
        else:
            streak = 0
            while cursor.isoformat() in reading_days:
                streak += 1
                cursor -= timedelta(days=1)
        return {
            "summary": {
                "total_seconds": int(total["seconds"] if total else 0),
                "month_seconds": int(month["seconds"] if month else 0),
                "finished_books": int(finished["count"] if finished else 0),
                "streak_days": streak,
            },
            "months": self.monthly_reading(months=months, now=now),
            "recent": self.recent_sessions(limit=recent_limit),
        }

    def monthly_reading(self, *, months: int = 6, now: datetime | None = None) -> list[dict[str, Any]]:
        """返回截至当月的连续 N 个月，缺月补 0，供图表直接绘制。"""
        now = now or datetime.now().astimezone()
        count = max(1, min(24, int(months)))
        month_index = now.year * 12 + now.month - 1
        first_index = month_index - count + 1
        first_year, first_month0 = divmod(first_index, 12)
        first_prefix = f"{first_year:04d}-{first_month0 + 1:02d}"
        current_prefix = f"{now.year:04d}-{now.month:02d}"
        rows = self.db.query(
            "SELECT substr(started_at, 1, 7) AS month, SUM(seconds) AS seconds "
            "FROM reading_sessions WHERE substr(started_at, 1, 7) BETWEEN ? AND ? "
            "GROUP BY substr(started_at, 1, 7)",
            (first_prefix, current_prefix),
        )
        values = {str(row["month"]): int(row["seconds"] or 0) for row in rows}
        result: list[dict[str, Any]] = []
        for offset in range(count):
            year, month0 = divmod(first_index + offset, 12)
            month_number = month0 + 1
            key = f"{year:04d}-{month_number:02d}"
            result.append({"month": key, "label": f"{month_number}月", "seconds": values.get(key, 0)})
        return result

    def recent_sessions(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """最近阅读会话；书名随书库记录实时关联。"""
        count = max(1, min(100, int(limit)))
        rows = self.db.query(
            "SELECT rs.id, rs.book_id, rs.started_at, rs.seconds, rs.pages, "
            "COALESCE(NULLIF(books.title, ''), '未命名') AS title "
            "FROM reading_sessions AS rs JOIN books ON books.id = rs.book_id "
            "ORDER BY rs.started_at DESC, rs.id DESC LIMIT ?",
            (count,),
        )
        return [dict(row) for row in rows]

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

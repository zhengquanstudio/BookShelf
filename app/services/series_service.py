"""系列/套书服务：卷号归一与同作者书名主干归并（文档 F7）。"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from ..core import series
from ..db.connection import Database
from ..db.repositories import utc_now
from ..db.repositories.book_repo import BookRepository
from ..db.repositories.series_repo import SeriesRepository

_SKIP_STATUS = ("failed", "drm", "skipped")


class SeriesService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.books = BookRepository(db)
        self.repo = SeriesRepository(db)

    def assign(
        self,
        book_id: int,
        *,
        title: str | None,
        series_name: str | None = None,
        series_index: Any = None,
        volume: int | None = None,
        author_id: int | None = None,
    ) -> int | None:
        """写入卷号与系列；没有明确系列名时只记录卷号。"""
        parsed = _to_int(series_index)
        volume = volume or parsed
        if not volume and title:
            match = series.extract_volume(title)
            volume = match.volume if match else None
        fields: dict[str, Any] = {}
        if volume:
            fields["volume"] = volume
            fields["volume_raw"] = str(series_index or volume)

        series_id: int | None = None
        name = (series_name or "").strip()
        if name and author_id:
            series_id = self.repo.ensure(name, author_id)
        elif volume and author_id:
            series_id = self._find_series_for(title or "", author_id, exclude=book_id)
        if series_id:
            fields["series_id"] = series_id
        if fields:
            self.books.update(book_id, **fields)
        return series_id

    def list_all(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.repo.list()]

    def create(self, name: str, author_id: int, total_volumes: int | None = None) -> int:
        if not name.strip():
            raise ValueError("系列名不能为空")
        return self.repo.ensure(
            name.strip(), author_id, total_volumes=total_volumes or None, locked=1
        )

    def catalog(self, author_id: int) -> list[dict[str, Any]]:
        """作者名下系列、各卷与缺卷信息。"""
        result: list[dict[str, Any]] = []
        for row in self.repo.list(author_id):
            item = dict(row)
            volumes = [dict(book) for book in self.repo.volumes(int(row["id"]))]
            present = {int(book["volume"]) for book in volumes if book["volume"]}
            expected = int(row["total_volumes"] or max(present, default=0))
            missing = [number for number in range(1, expected + 1) if number not in present]
            item["volumes"] = volumes
            item["volume_count"] = len(volumes)
            item["missing"] = missing
            item["complete"] = bool(volumes) and not missing
            result.append(item)
        return result

    def assign_books(self, book_ids: Sequence[int], series_id: int) -> int:
        target = self.repo.get(series_id)
        if target is None:
            raise ValueError("系列不存在")
        ids = list(dict.fromkeys(int(book_id) for book_id in book_ids))
        if not ids:
            return 0
        marks = ", ".join("?" for _ in ids)
        with self.db.transaction() as conn:
            if target["author_id"] is not None:
                cur = conn.execute(
                    f"UPDATE books SET series_id = ?, author_id = ?, updated_at = ? "
                    f"WHERE id IN ({marks})",
                    (series_id, target["author_id"], utc_now(), *ids),
                )
            else:
                cur = conn.execute(
                    f"UPDATE books SET series_id = ?, updated_at = ? WHERE id IN ({marks})",
                    (series_id, utc_now(), *ids),
                )
            return cur.rowcount

    def set_volume(self, book_id: int, volume: int) -> None:
        if volume < 1:
            raise ValueError("卷号必须大于 0")
        self.books.update(book_id, volume=volume, volume_raw=f"第{volume}卷")

    def add_volume(self, series_id: int, book_id: int, volume: int) -> None:
        if volume < 1:
            raise ValueError("卷号必须大于 0")
        if any(
            int(row["volume"] or 0) == volume and int(row["id"]) != book_id
            for row in self.repo.volumes(series_id)
        ):
            raise ValueError(f"第 {volume} 卷已存在")
        self.assign_books([book_id], series_id)
        self.set_volume(book_id, volume)

    def normalize_volumes(self, series_id: int) -> int:
        rows = self.repo.volumes(series_id)
        with self.db.transaction() as conn:
            changed = 0
            for row in rows:
                volume = int(row["volume"] or 0)
                if volume > 0:
                    conn.execute(
                        "UPDATE books SET volume_raw = ?, updated_at = ? WHERE id = ?",
                        (f"第{volume}卷", utc_now(), row["id"]),
                    )
                    changed += 1
            return changed

    def merge(self, source_id: int, target_id: int) -> int:
        if source_id == target_id:
            raise ValueError("不能合并到同一个系列")
        target = self.repo.get(target_id)
        if target is None or self.repo.get(source_id) is None:
            raise ValueError("要合并的系列不存在")
        with self.db.transaction() as conn:
            cur = conn.execute(
                "UPDATE books SET series_id = ?, author_id = ?, updated_at = ? "
                "WHERE series_id = ?",
                (target_id, target["author_id"], utc_now(), source_id),
            )
            conn.execute("DELETE FROM series WHERE id = ?", (source_id,))
            return cur.rowcount

    def split(self, series_id: int, book_ids: Sequence[int]) -> int:
        ids = list(dict.fromkeys(int(book_id) for book_id in book_ids))
        if not ids:
            return 0
        marks = ", ".join("?" for _ in ids)
        with self.db.transaction() as conn:
            cur = conn.execute(
                f"UPDATE books SET series_id = NULL, updated_at = ? "
                f"WHERE series_id = ? AND id IN ({marks})",
                (utc_now(), series_id, *ids),
            )
            return cur.rowcount

    def export_list(self, series_id: int, path: Path | str) -> int:
        rows = self.repo.volumes(series_id)
        with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["卷号", "书名", "格式", "文件路径"])
            for row in rows:
                writer.writerow([
                    row["volume"] or "", row["title"] or "", row["format"] or "",
                    row["file_path"] or "",
                ])
        return len(rows)

    def _find_series_for(self, title: str, author_id: int, *, exclude: int) -> int | None:
        key = series.title_key(title)
        if not key:
            return None
        rows = self.db.query(
            "SELECT id, title, series_id FROM books "
            "WHERE author_id = ? AND series_id IS NOT NULL AND id != ?",
            (author_id, exclude),
        )
        for row in rows:
            if series.title_key(row["title"]) == key:
                return int(row["series_id"])
        return None

    def rebuild_for_author(self, author_id: int) -> int:
        """把同作者、书名主干相同且卷号不同的多本书归入同一系列。"""
        rows = self.db.query(
            "SELECT b.*, s.name AS series_name, s.locked AS series_locked "
            "FROM books AS b LEFT JOIN series AS s ON s.id = b.series_id "
            "WHERE b.author_id = ? AND b.status NOT IN (?, ?, ?)",
            (author_id, *_SKIP_STATUS),
        )
        groups: dict[str, list[Any]] = {}
        for row in rows:
            key = series.title_key(row["title"])
            if key:
                groups.setdefault(key, []).append(row)

        assigned = 0
        for key, group in groups.items():
            volumes = {int(row["volume"]) for row in group if row["volume"]}
            if len(group) < 2 or len(volumes) < 2:
                continue
            if any(row["series_locked"] for row in group):
                continue
            name = self._series_name(group)
            series_id = self.repo.ensure(name, author_id)
            for row in group:
                fields: dict[str, Any] = {"series_id": series_id}
                if not row["volume"]:
                    match = series.extract_volume(row["title"])
                    if match:
                        fields["volume"] = match.volume
                self.books.update(int(row["id"]), **fields)
                assigned += 1
        return assigned

    @staticmethod
    def _series_name(group: list[Any]) -> str:
        names = Counter(str(row["series_name"]).strip() for row in group if row["series_name"])
        if names:
            return names.most_common(1)[0][0]
        titles = [series.strip_volume(row["title"]) for row in group if row["title"]]
        titles = [title for title in titles if title]
        if not titles:
            return "未命名系列"
        return min(titles, key=len)

    def rebuild_all(self) -> int:
        rows = self.db.query(
            "SELECT DISTINCT author_id FROM books WHERE author_id IS NOT NULL"
        )
        return sum(self.rebuild_for_author(int(row["author_id"])) for row in rows)


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(float(str(value)))
        return number if number > 0 else None
    except (TypeError, ValueError):
        match = series.extract_volume(str(value))
        return match.volume if match else None

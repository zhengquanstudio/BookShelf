"""书库查询服务：为列表、详情和统计提供数据。"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path
from typing import Any, Sequence

from PySide6.QtGui import QPixmap

from .. import config
from ..db.connection import Database
from ..db.repositories import utc_now
from ..db.repositories.book_repo import BookRepository

FAVORITE_TAG = "收藏"

_NAV_STATUS = {
    "all": None,
    "pending": ["pending", "ok", "partial"],
    "partial": ["partial"],
    "archived": ["archived"],
    "failed": ["failed"],
}


class LibraryService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.books = BookRepository(db)

    def query_books(
        self,
        nav_key: str = "all",
        search: str = "",
        format_name: str = "",
        tag: str = "",
        folder: str = "",
        page: int = 1,
        page_size: int = 200,
        sort: str = "added_at",
        desc: bool = True,
        shelf_only: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        """按导航和搜索条件分页查询；排序和筛选均在 SQL 层完成。"""
        status = _NAV_STATUS.get(nav_key)
        formats = [format_name] if format_name else None
        # count() 不接受 sort/desc，筛选条件单独一组避免透传。
        filter_kwargs = {
            "status": status,
            "formats": formats,
            "search": search or None,
            "shelf_only": shelf_only,
            "tag": tag or None,
            "folder": folder or None,
        }
        rows = self.books.list(
            page=page, page_size=page_size, sort=sort, desc=desc, **filter_kwargs
        )
        total = self.books.count(**filter_kwargs)
        return [dict(row) for row in rows], total

    def tag_counts(self) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT t.name, t.color, COUNT(bt.book_id) AS count "
            "FROM tags AS t LEFT JOIN book_tags AS bt ON bt.tag_id = t.id "
            "GROUP BY t.id ORDER BY count DESC, t.name"
        )
        return [dict(row) for row in rows]

    def folders(self) -> list[dict[str, Any]]:
        """按书实际所在目录聚合（整理成功的书算归档目录）。"""
        rows = self.db.query(
            "SELECT books.id, books.status, "
            "COALESCE((SELECT li.target_path FROM library_items AS li "
            "WHERE li.book_id = books.id AND li.result <> 'skipped' "
            "AND IFNULL(li.target_path, '') <> '' ORDER BY li.id DESC LIMIT 1), "
            "books.file_path) AS physical_path FROM books"
        )
        groups: dict[str, dict[str, Any]] = {}
        for row in rows:
            path = str(row["physical_path"] or "")
            if not path:
                continue
            parent = str(Path(path).parent)
            group = groups.setdefault(parent, {"path": parent, "count": 0, "archived": 0})
            group["count"] += 1
            if row["status"] == "archived":
                group["archived"] += 1
        return sorted(groups.values(), key=lambda item: (-item["count"], item["path"]))

    def statistics(self) -> dict[str, int]:
        counts = self.books.count_by_status()
        return {
            "total": sum(counts.values()),
            "pending": sum(
                counts.get(key, 0) for key in ("pending", "ok", "partial")
            ),
            "ok": counts.get("ok", 0),
            "partial": counts.get("partial", 0),
            "failed": counts.get("failed", 0),
            "archived": counts.get("archived", 0),
        }

    def set_status(self, book_ids: Sequence[int], status: str) -> int:
        ids = list(dict.fromkeys(int(book_id) for book_id in book_ids))
        if not ids:
            return 0
        marks = ", ".join("?" for _ in ids)
        with self.db.transaction() as conn:
            cur = conn.execute(
                f"UPDATE books SET status = ?, updated_at = ? WHERE id IN ({marks})",
                (status, utc_now(), *ids),
            )
            return cur.rowcount

    def remove_books(self, book_ids: Sequence[int]) -> int:
        """只移除数据库记录，不触碰原始文件。"""
        ids = list(dict.fromkeys(int(book_id) for book_id in book_ids))
        if not ids:
            return 0
        marks = ", ".join("?" for _ in ids)
        with self.db.transaction() as conn:
            conn.execute(f"DELETE FROM book_tags WHERE book_id IN ({marks})", tuple(ids))
            cur = conn.execute(f"DELETE FROM books WHERE id IN ({marks})", tuple(ids))
            return cur.rowcount

    def set_tags(self, book_ids: Sequence[int], names: Sequence[str]) -> int:
        """用给定标签替换所选书籍的标签，单事务完成。"""
        ids = list(dict.fromkeys(int(book_id) for book_id in book_ids))
        clean_names = list(dict.fromkeys(name.strip() for name in names if name.strip()))
        if not ids:
            return 0
        book_marks = ", ".join("?" for _ in ids)
        with self.db.transaction() as conn:
            conn.execute(f"DELETE FROM book_tags WHERE book_id IN ({book_marks})", tuple(ids))
            for name in clean_names:
                conn.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (name,))
                tag_id = int(conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()["id"])
                conn.executemany(
                    "INSERT OR IGNORE INTO book_tags(book_id, tag_id) VALUES (?, ?)",
                    [(book_id, tag_id) for book_id in ids],
                )
            return len(ids)

    def add_favorite(self, book_ids: Sequence[int]) -> int:
        ids = list(dict.fromkeys(int(book_id) for book_id in book_ids))
        if not ids:
            return 0
        with self.db.transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO tags(name, color) VALUES ('收藏', '#e8b04b')")
            tag_id = int(conn.execute("SELECT id FROM tags WHERE name = '收藏'").fetchone()["id"])
            conn.executemany(
                "INSERT OR IGNORE INTO book_tags(book_id, tag_id) VALUES (?, ?)",
                [(book_id, tag_id) for book_id in ids],
            )
            return len(ids)

    def tags_for(self, book_id: int) -> list[str]:
        rows = self.db.query(
            "SELECT t.name FROM tags AS t JOIN book_tags AS bt ON bt.tag_id = t.id "
            "WHERE bt.book_id = ? ORDER BY t.name",
            (book_id,),
        )
        return [str(row["name"]) for row in rows]

    def archive_path(self, book_id: int) -> str:
        """返回最近一次非跳过整理的归档目标路径；从未整理则为空串（仅展示用）。"""
        rows = self.db.query(
            "SELECT target_path FROM library_items "
            "WHERE book_id = ? AND result <> 'skipped' "
            "AND IFNULL(target_path, '') <> '' ORDER BY id DESC LIMIT 1",
            (int(book_id),),
        )
        return str(rows[0]["target_path"]) if rows else ""

    # ---- 批量操作（T6） ---------------------------------------------
    def move_books_to(
        self, book_ids: Sequence[int], target_dir: str | Path
    ) -> tuple[int, list[str]]:
        """把所选书的物理文件移动到 target_dir，更新 file_path 并记录归档项。

        单本失败不中断批处理，错误信息收集后返回；不触碰识别/整理核心逻辑。
        """
        target = Path(target_dir).expanduser()
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return 0, [f"无法创建目标目录：{exc}"]
        ids = list(dict.fromkeys(int(book_id) for book_id in book_ids))
        moved = 0
        errors: list[str] = []
        for book_id in ids:
            row = self.db.query_one(
                "SELECT file_path FROM books WHERE id = ?", (book_id,)
            )
            if row is None or not row["file_path"]:
                errors.append(f"#{book_id} 缺少文件路径")
                continue
            archive = self.archive_path(book_id)
            source = (
                Path(archive)
                if archive and Path(archive).exists()
                else Path(str(row["file_path"]))
            )
            if not source.exists():
                errors.append(f"{source.name}：源文件不存在")
                continue
            destination = target / source.name
            if destination.exists():
                stem, suffix = source.stem, source.suffix
                index = 1
                while True:
                    candidate = target / f"{stem}_{index}{suffix}"
                    if not candidate.exists():
                        destination = candidate
                        break
                    index += 1
            try:
                shutil.move(str(source), str(destination))
            except OSError as exc:
                errors.append(f"{source.name}：{exc}")
                continue
            try:
                with self.db.transaction() as conn:
                    conn.execute(
                        "UPDATE books SET file_path = ?, updated_at = ? WHERE id = ?",
                        (str(destination), utc_now(), book_id),
                    )
                    conn.execute(
                        "INSERT INTO library_items"
                        "(book_id, source_path, target_dir, target_name, "
                        "target_path, action, result, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            book_id,
                            str(source),
                            str(target),
                            destination.name,
                            str(destination),
                            "move",
                            "moved",
                            utc_now(),
                        ),
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{source.name}：写入失败 {exc}")
                continue
            moved += 1
        return moved, errors

    def export_list(self, book_ids: Sequence[int], path: str | Path) -> int:
        """导出所选书清单为 UTF-8-BOM CSV，Excel 可直接打开。"""
        ids = list(dict.fromkeys(int(book_id) for book_id in book_ids))
        if not ids:
            return 0
        marks = ", ".join("?" for _ in ids)
        rows = self.db.query(
            "SELECT id, title, author_raw, format, isbn, status, file_path "
            f"FROM books WHERE id IN ({marks}) ORDER BY id",
            tuple(ids),
        )
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["书名", "作者", "格式", "ISBN", "状态", "文件路径", "归档路径"])
            for row in rows:
                writer.writerow(
                    [
                        row["title"] or "",
                        row["author_raw"] or "",
                        row["format"] or "",
                        row["isbn"] or "",
                        row["status"] or "",
                        row["file_path"] or "",
                        self.archive_path(int(row["id"])),
                    ]
                )
        return len(rows)

    # ---- 标签管理（M7） ---------------------------------------------
    def rename_tag(self, old_name: str, new_name: str) -> int:
        """重命名标签；新名已存在时合并到同名标签，返回受影响书籍数。"""
        old = (old_name or "").strip()
        new = (new_name or "").strip()
        if not old or not new or old == new or old == FAVORITE_TAG:
            return 0
        with self.db.transaction() as conn:
            old_row = conn.execute("SELECT id FROM tags WHERE name = ?", (old,)).fetchone()
            if old_row is None:
                return 0
            old_id = int(old_row["id"])
            affected = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM book_tags WHERE tag_id = ?", (old_id,)
                ).fetchone()["n"]
            )
            new_row = conn.execute("SELECT id FROM tags WHERE name = ?", (new,)).fetchone()
            if new_row is None:
                conn.execute("UPDATE tags SET name = ? WHERE id = ?", (new, old_id))
                return affected
            new_id = int(new_row["id"])
            conn.execute(
                "INSERT OR IGNORE INTO book_tags(book_id, tag_id) "
                "SELECT book_id, ? FROM book_tags WHERE tag_id = ?",
                (new_id, old_id),
            )
            conn.execute("DELETE FROM book_tags WHERE tag_id = ?", (old_id,))
            conn.execute("DELETE FROM tags WHERE id = ?", (old_id,))
            return affected

    def delete_tag(self, name: str) -> int:
        """删除标签及其书籍关联（不删除书籍），返回受影响书籍数。"""
        clean = (name or "").strip()
        if not clean or clean == FAVORITE_TAG:
            return 0
        with self.db.transaction() as conn:
            row = conn.execute("SELECT id FROM tags WHERE name = ?", (clean,)).fetchone()
            if row is None:
                return 0
            tag_id = int(row["id"])
            affected = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM book_tags WHERE tag_id = ?", (tag_id,)
                ).fetchone()["n"]
            )
            conn.execute("DELETE FROM book_tags WHERE tag_id = ?", (tag_id,))
            conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
            return affected

    # ---- 导入待整理清单（M7） ---------------------------------------
    def import_pending(
        self,
        paths: Sequence[str | Path],
        *,
        base_dir: Path | None = None,
    ) -> dict[str, int]:
        """按文本清单逐行导入书籍记录，状态置为待整理。

        相对路径以清单文件所在目录为基准；跳过空行、注释、
        不支持的格式、不存在的文件和已在库中的路径。
        """
        result = {"added": 0, "existing": 0, "invalid": 0}
        for raw in paths:
            text = str(raw).strip().strip('"').strip("'").strip()
            if not text or text.startswith("#"):
                continue
            path = Path(text).expanduser()
            if not path.is_absolute() and base_dir is not None:
                path = base_dir / path
            try:
                path = path.resolve()
            except OSError:
                pass
            if path.suffix.lower() not in config.SUPPORTED_EXTENSIONS or not path.is_file():
                result["invalid"] += 1
                continue
            if self.books.find_by_path(str(path)) is not None:
                result["existing"] += 1
                continue
            try:
                self.books.create(
                    file_path=str(path),
                    format=path.suffix.lower().lstrip("."),
                    title=path.stem,
                    status="pending",
                    meta_source="import",
                )
            except ValueError:
                result["existing"] += 1
                continue
            result["added"] += 1
        return result

    @staticmethod
    def cover_for(book: dict[str, Any]) -> QPixmap | None:
        """读取已生成的封面缩略图；没有封面时返回 None。"""
        path = str(book.get("cover_path") or "")
        if not path or not Path(path).is_file():
            return None
        pixmap = QPixmap(path)
        return None if pixmap.isNull() else pixmap

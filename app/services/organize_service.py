"""整理预览与执行（F8/F9，文档 10.6）。

设计要点：
- preview 是纯计算：只读数据库与目标目录，不写盘、不改库；
- execute 逐条执行、失败不中断，每条结果写 library_items + task_log；
- undo 只支持复制动作且本次未覆盖已有文件。
"""

from __future__ import annotations

import csv
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..core import authors as author_tools
from ..core import naming, series
from ..core.naming import NamingRules
from ..db.connection import Database
from ..errors import OrganizeError
from ..logger import get_logger
from .settings_service import SettingsService

log = get_logger("organize")

STATUS_SYMBOL = {"ready": "✓", "conflict": "⟳", "skip": "✕", "failed": "✕"}
ACTION_LABEL = {"copy": "复制", "move": "移动", "skip": "跳过", "rename": "重命名"}
_HAN = re.compile(r"[\u3400-\u9fff]")

_RECORD_SELECT = (
    "SELECT books.id, books.file_path, books.title, books.subtitle, "
    "books.format, books.file_size, books.volume, books.volume_raw, "
    "books.isbn, books.publisher, books.publish_date, "
    "books.status, books.dup_group_id, books.drm_protected, "
    "books.author_id, authors.name_zh AS author_name, "
    "authors.country_code AS country_code, authors.country AS country, "
    "authors.is_chinese AS is_chinese, authors.locked AS author_locked, "
    "series.name AS series_name "
    "FROM books "
    "LEFT JOIN authors ON authors.id = books.author_id "
    "LEFT JOIN series ON series.id = books.series_id "
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PreviewRow:
    """一条整理预览记录（可被界面手动修改目标文件名）。"""

    book_id: int
    title: str
    author: str
    country: str
    volume: str
    source_path: str
    format: str
    action: str
    status: str
    message: str
    target_dir: str
    target_name: str
    target_path: str
    size: int = 0
    author_id: int | None = None
    series_name: str = ""
    volume_num: int = 0
    relative_path: str = ""
    confirmed: bool = False
    edited: bool = False
    conflict_kinds: list[str] = field(default_factory=list)

    @property
    def display_status(self) -> str:
        return STATUS_SYMBOL.get(self.status, "·")

    @property
    def action_label(self) -> str:
        return ACTION_LABEL.get(self.action, self.action)

    @property
    def blocking(self) -> bool:
        """执行时是否应跳过：跳过/失败行，或作者译名尚未确认。"""
        if self.status in {"skip", "failed"}:
            return True
        return "author" in self.conflict_kinds and not self.confirmed

    def rename(self, name: str) -> None:
        """手动修改目标文件名，保留扩展名并清理非法字符。"""
        value = naming.clean_text(name, drop_noise=False)
        if not value:
            return
        old_suffix = Path(self.target_name).suffix
        if not Path(value).suffix and old_suffix:
            value = f"{value}{old_suffix}"
        self.target_name = value
        self.target_path = str(Path(self.target_dir) / value)
        self.edited = True
        if "文件名已手动修改" not in self.message:
            self.message = "；".join(part for part in (self.message, "文件名已手动修改") if part)
            self.status = "conflict" if self.status == "ready" else self.status


@dataclass
class PreviewSummary:
    rows: list[PreviewRow]
    total: int = 0
    ready: int = 0
    conflict: int = 0
    skip: int = 0
    failed: int = 0
    total_bytes: int = 0
    dirs: int = 0
    disk_free: int = 0
    disk_shortage: bool = False
    root: str = ""


@dataclass
class ExecuteResult:
    batch_id: str
    copied: int = 0
    moved: int = 0
    renamed: int = 0
    overwritten: int = 0
    skipped: int = 0
    conflicts: int = 0
    failed: int = 0
    dirs_created: int = 0
    total_bytes: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> int:
        return self.copied + self.moved + self.renamed + self.overwritten

    def summary(self) -> str:
        return f"成功 {self.success} / 冲突 {self.conflicts} / 失败 {self.failed}"


@dataclass
class UndoResult:
    batch_id: str
    removed: int = 0
    missing: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return f"还原/删除 {self.removed} 个文件，缺失 {self.missing} 个"


class OrganizeService:
    """整理预览、执行、撤销与记录查询。"""

    def __init__(self, db: Database, settings: SettingsService) -> None:
        self.db = db
        self.settings = settings
        self._created_dirs: dict[str, set[str]] = {}

    # ---- 规则 -------------------------------------------------------
    def rules(self, policy: str | None = None, action: str | None = None) -> NamingRules:
        rules = NamingRules.from_config(self.settings.data)
        if policy:
            rules.conflict_policy = policy
        if action:
            rules.action = action
        return rules

    def _root(self) -> Path:
        return Path(str(self.settings.data.get("library_root") or ""))

    # ---- 预览（F8） -------------------------------------------------
    def preview(
        self,
        *,
        only_recognized: bool = False,
        policy: str | None = None,
        action: str | None = None,
    ) -> PreviewSummary:
        """计算全部目标路径；不创建目录、不复制文件。"""
        rules = self.rules(policy=policy, action=action)
        root = self._root()
        records = self._records(only_recognized=only_recognized)

        first = [self._plan_one(record, rules, root, None) for record in records]
        existing: set[str] = set()
        if str(root) and root.is_dir():
            for item in self._scan_existing(
                Path(row.target_dir) for row in first if row.target_dir
            ):
                try:
                    existing.add(str(Path(item).relative_to(root)).casefold())
                except ValueError:
                    continue
        planned: set[str] = set(existing)
        rows: list[PreviewRow] = []
        seen_dirs: dict[str, tuple[str, str]] = {}
        series_volumes: dict[tuple[str, int], int] = {}
        for record, base in zip(records, first):
            row = self._plan_one(
                record, rules, root, planned if planned else None
            )
            if row.relative_path:
                planned.add(row.relative_path.casefold())
            self._check_volume(row, record, rules, series_volumes)
            self._check_directory(row, seen_dirs)
            rows.append(row)
        rows.sort(key=_sort_key)

        summary = PreviewSummary(rows=rows, root=str(root) if str(root) else "")
        summary.total = len(rows)
        for row in rows:
            if row.status == "ready":
                summary.ready += 1
            elif row.status == "conflict":
                summary.conflict += 1
            elif row.status == "skip":
                summary.skip += 1
            else:
                summary.failed += 1
            if row.status in {"ready", "conflict"}:
                summary.total_bytes += row.size
        summary.dirs = len(
            {row.target_dir for row in rows if row.status in {"ready", "conflict"}}
        )
        if str(root) and root.is_dir():
            try:
                summary.disk_free = shutil.disk_usage(root).free
            except OSError:
                summary.disk_free = 0
        summary.disk_shortage = bool(
            summary.disk_free and summary.total_bytes > summary.disk_free
        )
        log.info(
            "整理预览完成：%s 条（就绪 %s / 冲突 %s / 跳过 %s / 失败 %s）",
            summary.total,
            summary.ready,
            summary.conflict,
            summary.skip,
            summary.failed,
        )
        return summary

    def _records(self, *, only_recognized: bool) -> list[Mapping[str, Any]]:
        statuses = ("ok",) if only_recognized else ("ok", "partial")
        marks = ", ".join("?" for _ in statuses)
        return self._query_records(
            f"WHERE books.status IN ({marks}) ORDER BY books.title, books.id",
            statuses,
        )

    def _records_by_ids(self, book_ids: Sequence[int]) -> list[Mapping[str, Any]]:
        ids = [int(book_id) for book_id in book_ids]
        if not ids:
            return []
        marks = ", ".join("?" for _ in ids)
        return self._query_records(
            f"WHERE books.id IN ({marks}) ORDER BY books.title, books.id", ids
        )

    def _query_records(
        self, where: str, params: Sequence[Any]
    ) -> list[Mapping[str, Any]]:
        return [dict(row) for row in self.db.query(f"{_RECORD_SELECT} {where}", params)]

    def _plan_one(
        self,
        record: Mapping[str, Any],
        rules: NamingRules,
        root: Path,
        existing: Iterable[str | Path] | None,
    ) -> PreviewRow:
        book = dict(record)
        author_name = str(book.get("author_name") or "")
        code = str(book.get("country_code") or "")
        info = author_tools.normalize_author(author_name, code or book.get("country"))
        # 库里已有中文译名（即使带中点或缩写字母）视为已确认；
        # 只有纯外文显示名才按“译名待确认”阻止整理。
        book["author_needs_confirm"] = (
            bool(info.needs_confirm)
            and not bool(book.get("author_locked"))
            and not _HAN.search(author_name)
        )
        plan = naming.plan_target(book, rules, existing=existing)
        relative = plan.target_path
        absolute = (root / relative) if str(root) and str(relative) else relative
        volume_num = _int_or_none(book.get("volume")) or 0
        row = PreviewRow(
            book_id=int(book["id"]),
            title=str(book.get("title") or Path(str(book.get("file_path") or "")).stem),
            author=author_name,
            country=str(book.get("country_code") or getattr(info, "country_code", "") or ""),
            volume=series.volume_text(volume_num or None, rules.volume_style),
            source_path=str(book.get("file_path") or ""),
            format=str(book.get("format") or ""),
            action=plan.action,
            status=plan.status,
            message=plan.message,
            target_dir=str(absolute.parent) if str(absolute) else "",
            target_name=plan.target_name,
            target_path=str(absolute) if str(absolute) else "",
            size=int(book.get("file_size") or 0),
            author_id=int(book["author_id"]) if book.get("author_id") else None,
            series_name=str(book.get("series_name") or ""),
            volume_num=volume_num,
            relative_path=str(relative) if str(relative) else "",
        )
        if plan.status == "failed":
            row.conflict_kinds.append("failed")
        elif plan.status == "conflict":
            if "作者译名待确认" in plan.message:
                row.conflict_kinds.append("author")
            if "目标已存在" in plan.message:
                row.conflict_kinds.append("exists")
        elif plan.status == "skip":
            row.conflict_kinds.append("skip")
        return row

    @staticmethod
    def _check_volume(
        row: PreviewRow,
        record: Mapping[str, Any],
        rules: NamingRules,
        seen: dict[tuple[str, int], int],
    ) -> None:
        if row.status in {"skip", "failed"}:
            return
        volume = _int_or_none(record.get("volume"))
        if not volume:
            return
        series_name = str(record.get("series_name") or "")
        if not series_name:
            _mark_conflict(row, "volume", "卷号未归入系列，待确认")
            return
        key = (series_name, volume)
        if key in seen:
            _mark_conflict(row, "volume", f"系列内卷号重复（第{volume}卷）")
        else:
            seen[key] = row.book_id

    @staticmethod
    def _check_directory(
        row: PreviewRow, seen: dict[str, tuple[str, str]]
    ) -> None:
        if row.status in {"skip", "failed"} or not row.target_dir:
            return
        identity = (row.author, row.country)
        previous = seen.get(row.target_dir.casefold())
        if previous is None:
            seen[row.target_dir.casefold()] = identity
        elif previous != identity:
            _mark_conflict(row, "dir", "目标作者目录与其他作者同名")

    @staticmethod
    def _scan_existing(directories: Iterable[Path]) -> set[str]:
        """扫描目标目录下已有文件，供冲突检测使用。"""
        paths: set[str] = set()
        for directory in {Path(item) for item in directories}:
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        try:
                            if entry.is_file():
                                paths.add(str(Path(directory) / entry.name).casefold())
                        except OSError:
                            continue
            except OSError:
                continue
        return paths

    # ---- 执行（F9） -------------------------------------------------
    def execute(
        self,
        rows: Sequence[PreviewRow],
        *,
        action: str | None = None,
        overwrite: bool | None = None,
    ) -> ExecuteResult:
        """执行整理；单条失败不中断整批。"""
        root = self._root()
        if not str(root) or not root.is_dir():
            raise OrganizeError("请先选择书库根目录")
        rules = self.rules(action=action)
        action = action or rules.action
        if overwrite is None:
            overwrite = rules.conflict_policy == "overwrite"
        payload = [row for row in rows if row.status in {"ready", "conflict"}]
        needed = sum(row.size for row in payload)
        try:
            free = shutil.disk_usage(root).free
        except OSError:
            free = 0
        if free and needed > free:
            raise OrganizeError("磁盘空间不足，已取消整理")

        batch_id = datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
        result = ExecuteResult(batch_id=batch_id)
        created_dirs: set[str] = set()
        source_dirs_before = self._source_dir_counts(payload) if action == "move" else {}

        for row in payload:
            if row.blocking:
                result.skipped += 1
                self._record(row, batch_id, "skipped", "作者译名待确认，已跳过")
                continue
            source = Path(row.source_path)
            target = Path(row.target_path)
            if not row.target_path or not row.target_name:
                result.failed += 1
                result.errors.append(f"{row.title}：没有有效目标路径")
                self._record(row, batch_id, "failed", "没有有效目标路径")
                continue
            if not source.is_file():
                result.failed += 1
                result.errors.append(f"{source}：源文件不存在")
                self._record(row, batch_id, "failed", "源文件不存在")
                continue
            overwritten = target.exists()
            if overwritten and not overwrite:
                result.conflicts += 1
                self._record(row, batch_id, "conflict", "目标已存在，未覆盖")
                continue
            try:
                created_dirs.update(self._ensure_dir(target.parent))
                shutil.copy2(source, target)
                if action == "move":
                    source.unlink()
                    if not overwritten:
                        result.moved += 1
                    final_action = "move"
                else:
                    if not overwritten:
                        result.copied += 1
                    final_action = "copy"
                if overwritten:
                    result.overwritten += 1
                result.total_bytes += row.size
                extra = "已覆盖原有文件" if overwritten else ""
                self._record(row, batch_id, "overwritten" if overwritten else final_action, extra)
                self._mark_archived(row.book_id, target if action == "move" else None)
            except OSError as exc:
                result.failed += 1
                message = f"{type(exc).__name__}: {exc}"
                result.errors.append(f"{row.target_name}：{message}")
                self._record(row, batch_id, "failed", message)
                log.error("整理失败 %s：%s", target, exc)

        result.dirs_created = len(created_dirs)
        self._created_dirs[batch_id] = created_dirs
        if action == "move":
            result.skipped += 0
            self._cleanup_empty_dirs(source_dirs_before, batch_id)
        self._write_task_log(
            batch_id,
            f"整理完成：{result.summary()}，新建目录 {result.dirs_created} 个",
        )
        log.info("整理执行完成 %s：%s", batch_id, result.summary())
        return result

    # ---- 只重命名（N6） --------------------------------------------
    def rename_only(self, book_ids: Sequence[int]) -> ExecuteResult:
        """只改文件名、不跨目录；冲突追加 (2)/(3)，失败整批回滚。

        与 execute 的区别：不创建目录、不复制/移动文件，只在原目录内 os.replace，
        因此不会把书挪到别处；数据库 file_path 与文件系统同步更新。
        """
        ids = [int(book_id) for book_id in book_ids]
        if not ids:
            raise OrganizeError("请先选择要重命名的书籍")
        rules = self.rules(action="copy")
        records = self._records_by_ids(ids)
        if not records:
            raise OrganizeError("没有可重命名的书籍")

        batch_id = datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
        result = ExecuteResult(batch_id=batch_id)
        plans: list[tuple[PreviewRow, Path, Path]] = []
        reserved: dict[Path, set[str]] = {}
        for record in records:
            row = self._plan_one(record, rules, Path(""), None)
            row.action = "rename"
            old = Path(row.source_path)
            if row.status in {"failed", "skip"}:
                result.failed += 1
                result.errors.append(f"{row.title}：无法生成文件名")
                self._record(row, batch_id, "failed", "无法生成文件名")
                continue
            if not old.is_file():
                result.failed += 1
                result.errors.append(f"{old}：源文件不存在")
                continue
            if not row.target_name:
                result.failed += 1
                result.errors.append(f"{row.title}：目标文件名为空")
                continue
            if row.target_name.casefold() == old.name.casefold():
                result.skipped += 1
                row.target_dir = str(old.parent)
                row.target_path = str(old)
                self._record(row, batch_id, "skipped", "文件名已符合模板")
                continue
            folder = old.parent
            known = reserved.get(folder)
            if known is None:
                known = _folder_entries(folder)
                reserved[folder] = known
            name = naming.unique_name(row.target_name, folder, known)
            new = folder / name
            known.add(str(new).casefold())
            row.target_dir = str(folder)
            row.target_name = name
            row.target_path = str(new)
            plans.append((row, old, new))

        if not plans:
            self._write_task_log(batch_id, f"只重命名：无需处理（跳过 {result.skipped}）")
            return result

        # 规范要求：先写日志再动文件。
        for row, _old, _new in plans:
            self._record(row, batch_id, "pending", "等待重命名")
        done: list[tuple[PreviewRow, Path, Path]] = []
        try:
            for row, old, new in plans:
                os.replace(old, new)
                done.append((row, old, new))
        except OSError as exc:
            self._rollback_renames(batch_id, done)
            self._write_task_log(batch_id, f"重命名失败，已整批回滚：{exc}")
            log.error("只重命名失败，已回滚：%s", exc)
            raise OrganizeError(f"重命名失败，已整批回滚：{exc}") from exc

        try:
            with self.db.transaction() as conn:
                for row, _old, new in done:
                    conn.execute(
                        "UPDATE books SET file_path = ?, updated_at = ? WHERE id = ?",
                        (str(new), _utc_now(), row.book_id),
                    )
                    conn.execute(
                        "UPDATE library_items SET result = 'renamed', message = '' "
                        "WHERE batch_id = ? AND book_id = ?",
                        (batch_id, row.book_id),
                    )
        except Exception as exc:
            self._rollback_renames(batch_id, done)
            raise OrganizeError(f"重命名后写入数据库失败，已回滚：{exc}") from exc

        result.renamed = len(done)
        self._write_task_log(
            batch_id, f"只重命名完成：{result.renamed} 个文件，跳过 {result.skipped}"
        )
        log.info("只重命名完成 %s：%s", batch_id, result.summary())
        return result

    def _rollback_renames(
        self, batch_id: str, done: Sequence[tuple[PreviewRow, Path, Path]]
    ) -> None:
        for _row, old, new in reversed(done):
            try:
                if new.exists() and not old.exists():
                    os.replace(new, old)
            except OSError as exc:  # 回滚失败只记录，不掩盖原始错误
                log.error("回滚重命名失败 %s：%s", new, exc)
        self.db.execute(
            "UPDATE library_items SET result = 'rolled_back' "
            "WHERE batch_id = ? AND result = 'pending'",
            (batch_id,),
        )

    def _ensure_dir(self, directory: Path) -> list[str]:
        created: list[str] = []
        missing: list[Path] = []
        node = directory
        while node and not node.exists():
            missing.append(node)
            parent = node.parent
            if parent == node:
                break
            node = parent
        for item in reversed(missing):
            try:
                item.mkdir(exist_ok=True)
                created.append(str(item))
            except OSError as exc:
                raise OrganizeError(f"无法创建目录 {item}：{exc}") from exc
        return created

    def _mark_archived(self, book_id: int, new_path: Path | None) -> None:
        if new_path is None:
            self.db.execute(
                "UPDATE books SET status = 'archived', updated_at = ? WHERE id = ?",
                (_utc_now(), book_id),
            )
        else:
            self.db.execute(
                "UPDATE books SET status = 'archived', file_path = ?, updated_at = ? "
                "WHERE id = ?",
                (str(new_path), _utc_now(), book_id),
            )

    def _record(
        self,
        row: PreviewRow,
        batch_id: str,
        result: str,
        message: str = "",
    ) -> None:
        self.db.execute(
            "INSERT INTO library_items(book_id, source_path, target_dir, target_name, "
            "target_path, action, result, message, batch_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row.book_id,
                row.source_path,
                row.target_dir,
                row.target_name,
                row.target_path,
                row.action,
                result,
                message,
                batch_id,
                _utc_now(),
            ),
        )
        self._write_task_log(
            batch_id, f"{row.title} → {row.target_path}（{result}）"
        )

    def _write_task_log(self, batch_id: str, message: str) -> None:
        self.db.execute(
            "INSERT INTO task_log(ts, level, action, book_id, message) "
            "VALUES (?, 'INFO', 'organize', NULL, ?)",
            (_utc_now(), f"[{batch_id}] {message}"),
        )

    def _source_dir_counts(self, rows: Sequence[PreviewRow]) -> dict[Path, int]:
        """记录源目录整理前的直接文件数，避免误删用户目录。"""
        counts: dict[Path, int] = {}
        for row in rows:
            folder = Path(row.source_path).parent
            if folder in counts:
                continue
            try:
                counts[folder] = sum(1 for item in folder.iterdir() if item.is_file())
            except OSError:
                counts[folder] = 0
        return counts

    def _cleanup_empty_dirs(
        self, counts: Mapping[Path, int], batch_id: str
    ) -> None:
        if not bool(self.settings.data.get("organize", {}).get("delete_empty_dirs", True)):
            return
        roots = {
            Path(str(item)).expanduser().resolve()
            for item in self.settings.data.get("source_dirs", [])
        }
        for folder, before in counts.items():
            if before <= 0:
                continue
            try:
                resolved = folder.resolve()
            except OSError:
                continue
            if resolved in roots or not any(
                root in resolved.parents for root in roots
            ):
                continue
            try:
                if any(resolved.iterdir()):
                    continue
                resolved.rmdir()
                self._write_task_log(batch_id, f"清理空目录：{resolved}")
            except OSError:
                continue

    # ---- 撤销 / 记录 ------------------------------------------------
    def latest_batch(self) -> str:
        row = self.db.query_one(
            "SELECT batch_id FROM library_items WHERE batch_id IS NOT NULL "
            "ORDER BY id DESC LIMIT 1"
        )
        return str(row["batch_id"]) if row else ""

    def records(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT library_items.*, books.title FROM library_items "
            "LEFT JOIN books ON books.id = library_items.book_id "
            "ORDER BY library_items.id DESC LIMIT ?",
            (int(limit),),
        )
        return [dict(row) for row in rows]

    def undo(self, batch_id: str | None = None) -> UndoResult:
        """撤销一次复制整理：只删除本次新建文件，不动原有文件。"""
        batch_id = batch_id or self.latest_batch()
        if not batch_id:
            raise OrganizeError("没有可撤销的整理记录")
        rows = self.db.query(
            "SELECT * FROM library_items WHERE batch_id = ? ORDER BY id DESC",
            (batch_id,),
        )
        if not rows:
            raise OrganizeError("找不到该批次的整理记录")
        actions = {str(row["action"]) for row in rows}
        if actions == {"rename"}:
            return self._undo_rename(batch_id, rows)
        if any(str(row["action"]) != "copy" for row in rows):
            raise OrganizeError("只有复制或重命名模式支持撤销")
        if any(str(row["result"]) == "overwritten" for row in rows):
            raise OrganizeError("本次整理覆盖了已有文件，无法自动撤销")

        result = UndoResult(batch_id=batch_id)
        root = self._root()
        for row in rows:
            if str(row["result"]) != "copy":
                continue
            path = Path(str(row["target_path"]))
            try:
                if path.is_file():
                    _assert_inside(path, root)
                    path.unlink()
                    result.removed += 1
                else:
                    result.missing += 1
                self.db.execute(
                    "UPDATE library_items SET result = 'undone' WHERE id = ?",
                    (row["id"],),
                )
                self.db.execute(
                    "UPDATE books SET status = 'ok', updated_at = ? "
                    "WHERE id = ? AND status = 'archived'",
                    (_utc_now(), row["book_id"]),
                )
            except (OSError, OrganizeError) as exc:
                result.errors.append(f"{path}：{exc}")
        self._prune_empty_dirs(root, self._created_dirs.get(batch_id, set()))
        self._write_task_log(
            batch_id, f"撤销完成：删除 {result.removed} 个文件，缺失 {result.missing} 个"
        )
        log.info("撤销整理 %s：删除 %s 个", batch_id, result.removed)
        return result

    def _undo_rename(self, batch_id: str, rows: Sequence[Mapping[str, Any]]) -> UndoResult:
        """撤销只重命名批次：把文件改回原路径并还原 file_path。"""
        result = UndoResult(batch_id=batch_id)
        for row in rows:
            if str(row["result"]) != "renamed":
                continue
            source = Path(str(row["source_path"] or ""))
            target = Path(str(row["target_path"] or ""))
            if not str(source) or not target.is_file():
                result.missing += 1
                continue
            if source.exists():
                result.errors.append(f"{source}：原路径已被占用")
                continue
            try:
                os.replace(target, source)
            except OSError as exc:
                result.errors.append(f"{target}：{exc}")
                continue
            self.db.execute(
                "UPDATE books SET file_path = ?, updated_at = ? WHERE id = ?",
                (str(source), _utc_now(), row["book_id"]),
            )
            self.db.execute(
                "UPDATE library_items SET result = 'undone' WHERE id = ?",
                (row["id"],),
            )
            result.removed += 1
        self._write_task_log(batch_id, f"撤销只重命名：{result.summary()}")
        log.info("撤销只重命名 %s：%s", batch_id, result.summary())
        return result

    @staticmethod
    def _prune_empty_dirs(root: Path, created_dirs: Iterable[str]) -> None:
        """只清理本批新建目录；重新启动后没有记录时宁可保留目录。"""
        if not str(root) or not root.is_dir():
            return
        directories = sorted(
            (Path(item) for item in created_dirs),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in directories:
            try:
                _assert_inside(directory, root)
                if directory.is_dir() and not any(directory.iterdir()):
                    directory.rmdir()
            except (OSError, OrganizeError):
                continue

    # ---- 导出（F8） -------------------------------------------------
    @staticmethod
    def export_csv(rows: Sequence[PreviewRow], path: Path | str) -> Path:
        """导出预览为 UTF-8-BOM CSV，Excel 可直接打开。"""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["状态", "原文件", "目标目录", "目标文件名", "动作", "备注"]
            )
            for row in rows:
                writer.writerow(
                    [
                        row.status,
                        row.source_path,
                        row.target_dir,
                        row.target_name,
                        row.action,
                        row.message,
                    ]
                )
        return target


def _folder_entries(folder: Path) -> set[str]:
    """目录内已有条目（文件与子目录）的 casefold 集合，用于避免重名。"""
    try:
        return {str(item).casefold() for item in folder.iterdir()}
    except OSError:
        return set()


def _assert_inside(path: Path, root: Path) -> None:
    if not str(root):
        raise OrganizeError("书库根目录未设置")
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError) as exc:
        raise OrganizeError("目标文件不在书库目录内，拒绝删除") from exc


def _mark_conflict(row: PreviewRow, kind: str, message: str) -> None:
    if kind not in row.conflict_kinds:
        row.conflict_kinds.append(kind)
    if row.status not in {"skip", "failed"}:
        row.status = "conflict"
    if message not in row.message:
        row.message = "；".join(part for part in (row.message, message) if part)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _sort_key(row: PreviewRow) -> tuple[str, str, int, str]:
    return (row.author, row.series_name, row.volume_num, row.title)


__all__ = [
    "OrganizeService",
    "PreviewRow",
    "PreviewSummary",
    "ExecuteResult",
    "UndoResult",
    "STATUS_SYMBOL",
]

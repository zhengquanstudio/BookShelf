"""扫描编排：线程池、增量判定、元数据落库、批量进度信号。"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThreadPool, Qt, Signal
from PySide6.QtGui import QImage

from .. import config
from ..core.filename_meta import parse_name
from ..core.hashing import quick_hash
from ..core.metadata import extract_metadata
from ..core.scanner import ScannedFile
from ..db.connection import Database
from ..db.repositories import utc_now
from ..db.repositories.book_repo import BookRepository
from ..logger import get_logger, log_ok
from ..workers.scan_worker import DiscoveryWorker, FileWorker
from .normalization import normalize_book
from .series_service import SeriesService

log = get_logger("scan")
_DUPLICATE_WRITE_LOCK = threading.Lock()


def _save_cover(data: bytes, book_id: int) -> str | None:
    """把内嵌封面缩放到 320px 宽并缓存；失败不影响书籍入库。"""
    if not data:
        return None
    image = QImage.fromData(data)
    if image.isNull():
        return None
    if image.width() > 320:
        image = image.scaledToWidth(320, Qt.SmoothTransformation)
    config.COVERS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.COVERS_DIR / f"{book_id}.jpg"
    if image.hasAlphaChannel():
        image = image.convertToFormat(QImage.Format_RGB32)
    return str(path) if image.save(str(path), "JPEG", 85) else None


def _record_duplicate(
    books: BookRepository,
    candidate: ScannedFile,
    digest: str,
    existing: Any,
    result: dict[str, Any],
    duplicates: list[Any],
) -> dict[str, Any]:
    group_id = duplicates[0]["dup_group_id"] or duplicates[0]["id"]
    for row in duplicates:
        if not row["dup_group_id"]:
            books.update(row["id"], dup_group_id=group_id)
    fields = {
        "file_path": str(candidate.path),
        "quick_hash": digest,
        "file_size": candidate.size,
        "file_mtime": candidate.mtime,
        "format": candidate.format,
        "status": "skipped",
        "dup_group_id": group_id,
        "dup_of": group_id,
    }
    book_id = (
        existing["id"]
        if existing
        else books.create(**fields, title=candidate.path.stem, meta_source="embedded")
    )
    if existing:
        books.update(book_id, **fields)
    result.update(
        book_id=book_id,
        status="skipped",
        message=f"内容重复，重复组 #{group_id}",
        duplicate=True,
    )
    log.warning("%s 内容重复，归入重复组 %s", candidate.path.name, group_id)
    return result


def process_scan_file(
    db: Database,
    candidate: ScannedFile,
    incremental: bool = True,
) -> dict[str, Any]:
    """处理单个文件，供 FileWorker 调用；数据库连接按线程隔离。"""
    books = BookRepository(db)
    path_text = str(candidate.path)
    result: dict[str, Any] = {
        "path": path_text,
        "file_name": candidate.path.name,
        "format": candidate.format,
        "size": candidate.size,
        "title": candidate.path.stem,
        "status": "pending",
        "message": "",
        "duplicate": False,
        "unchanged": False,
    }
    existing = books.find_by_path(path_text)

    if candidate.too_small:
        message = f"文件小于 {candidate.size / 1024:.1f}KB，已跳过"
        fields = {
            "file_path": path_text,
            "quick_hash": "",
            "file_size": candidate.size,
            "file_mtime": candidate.mtime,
            "format": candidate.format,
            "title": candidate.path.stem,
            "status": "skipped",
            "meta_source": "embedded",
        }
        book_id = existing["id"] if existing else books.create(**fields)
        if existing:
            books.update(book_id, **fields)
        result.update(book_id=book_id, status="skipped", message=message)
        log.warning("%s %s", candidate.path.name, message)
        return result

    digest = quick_hash(candidate.path)
    if (
        incremental
        and existing
        and existing["quick_hash"] == digest
        and existing["file_size"] == candidate.size
        and abs(float(existing["file_mtime"] or 0) - candidate.mtime) < 0.0001
    ):
        result.update(
            book_id=existing["id"],
            title=existing["title"] or candidate.path.stem,
            status=existing["status"],
            message="未变更，增量跳过",
            unchanged=True,
        )
        return result

    duplicates = [
        row for row in books.find_by_hash(digest) if row["file_path"] != path_text
    ]
    if duplicates:
        return _record_duplicate(books, candidate, digest, existing, result, duplicates)

    metadata = extract_metadata(candidate.path)
    # L0 文件名解析：永远先做，成本为零；内嵌字段只补空，不覆盖。
    name_meta = parse_name(candidate.path.stem)
    embedded_authors = [
        str(item).strip()
        for item in (metadata.get("authors") or [])
        if str(item).strip()
    ]
    authors = list(embedded_authors)
    embedded_title = str(metadata.get("title") or "").strip()
    title = embedded_title
    publisher = str(metadata.get("publisher") or "").strip()
    isbn_value = str(metadata.get("isbn") or "").strip()
    series_index = str(metadata.get("series_index") or "").strip()
    used_filename = False
    if not authors and name_meta.get("authors"):
        authors = [str(item) for item in name_meta["authors"]]
        used_filename = True
    if not title and name_meta.get("title"):
        title = str(name_meta["title"])
        used_filename = True
    if not publisher and name_meta.get("publisher"):
        publisher = str(name_meta["publisher"])
    if not isbn_value and name_meta.get("isbn"):
        isbn_value = str(name_meta["isbn"])
    if not series_index and name_meta.get("series_index"):
        series_index = str(name_meta["series_index"])
    publish_date = str(metadata.get("date") or "").strip() or str(
        name_meta.get("year") or ""
    )
    title = title or candidate.path.stem
    if metadata.get("ok") and (embedded_title or embedded_authors):
        meta_source = "embedded"
    elif used_filename:
        meta_source = "filename"
    else:
        meta_source = "embedded"
    if metadata.get("drm"):
        status = "drm"
        message = "受 DRM 保护，仅记录信息"
    elif not metadata.get("ok"):
        # 内嵌解析失败：文件名 L0 已给出书名/作者的记 partial（待补全），
        # 只有连书名都取不到时才判 failed，避免“有名字的书被当成全废”。
        if used_filename:
            status = "partial"
            message = "内嵌元数据不可用，暂用文件名识别，待联网补全"
        else:
            status = "failed"
            message = metadata.get("reason") or "元数据解析失败"
    elif metadata.get("scanned"):
        status = "partial"
        message = "疑似扫描件，需手动补信息"
    elif title and authors:
        if meta_source == "embedded":
            status = "ok"
            message = "内嵌元数据完整"
        else:
            status = "partial"
            message = "仅从文件名识别，待人工确认"
    else:
        status = "partial"
        message = "缺少作者或书名，待联网检索"

    try:
        volume = int(float(series_index)) if series_index else None
    except ValueError:
        volume = None
    if status == "ok":
        confidence = 95.0 if isbn_value else 70.0
    elif status == "partial":
        confidence = 40.0 if meta_source == "filename" else 50.0
    else:
        confidence = 0.0
    fields = {
        "file_path": path_text,
        "quick_hash": digest,
        "file_size": candidate.size,
        "file_mtime": candidate.mtime,
        "format": candidate.format,
        "title": title,
        "subtitle": metadata.get("subtitle"),
        "author_raw": "、".join(authors),
        "isbn": isbn_value,
        "publisher": publisher,
        "publish_date": publish_date,
        "language": metadata.get("language"),
        "volume": volume,
        "volume_raw": series_index or None,
        "description": metadata.get("description"),
        "page_count": metadata.get("page_count"),
        "meta_source": meta_source,
        "confidence": confidence,
        "status": status,
        "drm_protected": 1 if metadata.get("drm") else 0,
    }
    # 相同内容可能同时完成解析；入库前在短锁内再次检查，避免并发漏判重复。
    with _DUPLICATE_WRITE_LOCK:
        duplicates = [
            row for row in books.find_by_hash(digest) if row["file_path"] != path_text
        ]
        if duplicates:
            return _record_duplicate(books, candidate, digest, existing, result, duplicates)
        book_id = existing["id"] if existing else books.create(**fields)
        if existing:
            books.update(book_id, **fields)
    cover_path = _save_cover(metadata.get("cover_bytes") or b"", book_id)
    if cover_path:
        books.update(book_id, cover_path=cover_path)
    try:
        normalized = normalize_book(db, book_id)
        title = str(normalized.get("title") or title)
    except Exception as exc:  # 规范化失败不影响入库
        log.warning("[id=%s] 作者/系列规范化失败：%s", book_id, exc)
    result.update(
        book_id=book_id,
        title=title,
        status=status,
        message=message,
        cover_path=cover_path,
    )
    if status == "ok":
        log_ok(log, "[id=%s] %s %s", book_id, candidate.path.name, message)
    elif status in {"failed", "drm"}:
        log.warning("[id=%s] %s %s", book_id, candidate.path.name, message)
    return result


class ScanService(QObject):
    """一次扫描对应一组 QRunnable，进度最多每 200ms 推送一次。"""

    started = Signal(object)
    progress = Signal(object)
    files_updated = Signal(list)
    finished = Signal(object)
    running_changed = Signal(bool)

    def __init__(self, db: Database, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.pool = QThreadPool(self)
        self.cancel_event = threading.Event()
        self._running = False
        self._workers: list[object] = []
        self._last_emit = 0.0
        self._reset_stats()

    @property
    def is_running(self) -> bool:
        return self._running

    def _reset_stats(self) -> None:
        self._total = 0
        self._completed = 0
        self._scanned = 0
        self._success = 0
        self._need_network = 0
        self._failed = 0
        self._dup = 0
        self._unchanged = 0
        self._file_buffer: list[dict[str, Any]] = []
        self._current_file = ""
        self._discovery_error = ""

    def start(self, directories: list[str], options: dict[str, Any]) -> bool:
        if self._running:
            return False
        self.cancel_event.clear()
        self._reset_stats()
        self._incremental = bool(options.get("incremental", True))
        self._running = True
        self.pool.setMaxThreadCount(min(8, max(1, int(options.get("workers", 4)))))
        self.running_changed.emit(True)
        self.started.emit({"total": 0, "format_counts": {}})
        log.info("开始扫描 %s", "、".join(directories))
        worker = DiscoveryWorker(directories, options, self.cancel_event)
        worker.signals.discovered.connect(self._on_discovered)
        worker.signals.failed.connect(self._on_discovery_failed)
        self._workers.append(worker)
        self.pool.start(worker)
        return True

    def cancel(self) -> None:
        if self._running:
            self.cancel_event.set()
            log.warning("用户请求停止扫描，已入库数据保留")

    def _on_discovery_failed(self, text: str) -> None:
        self._discovery_error = text
        log.error("%s", text)

    def _on_discovered(self, files: list[ScannedFile]) -> None:
        if self.cancel_event.is_set():
            self._finish()
            return
        self._total = len(files)
        counts: dict[str, int] = {}
        for item in files:
            counts[item.format] = counts.get(item.format, 0) + 1
        self.started.emit({"total": self._total, "format_counts": counts})
        if not files:
            self._finish()
            return
        for candidate in files:
            worker = FileWorker(
                candidate,
                bool(self._incremental),
                self.cancel_event,
                lambda item, incremental: process_scan_file(self.db, item, incremental),
            )
            worker.signals.processed.connect(self._on_file_done)
            self._workers.append(worker)
            self.pool.start(worker)

    def _on_file_done(self, result: dict[str, Any]) -> None:
        self._completed += 1
        self._current_file = str(result.get("file_name") or "")
        if result.get("cancelled"):
            self._emit_progress(force=self._completed == self._total)
            return
        self._scanned += 1
        status = result.get("status")
        if result.get("unchanged"):
            self._unchanged += 1
        elif result.get("duplicate"):
            self._dup += 1
        elif status == "ok":
            self._success += 1
        elif status == "partial":
            self._need_network += 1
        elif status == "failed":
            self._failed += 1
        self._file_buffer.append(result)
        self._emit_progress(force=self._completed == self._total)

    def _emit_progress(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_emit < 0.2:
            return
        self._last_emit = now
        snapshot = {
            "scanned": self._scanned,
            "completed": self._completed,
            "total": self._total,
            "current_file": self._current_file,
            "success": self._success,
            "need_network": self._need_network,
            "failed": self._failed,
            "dup": self._dup,
            "unchanged": self._unchanged,
            "library_total": BookRepository(self.db).count(),
        }
        self.progress.emit(snapshot)
        if self._file_buffer:
            batch = self._file_buffer
            self._file_buffer = []
            self.files_updated.emit(batch)
        if self._completed >= self._total:
            self._finish()

    def _finish(self) -> None:
        if not self._running:
            return
        cancelled = self.cancel_event.is_set()
        self._running = False
        if self._discovery_error:
            message = self._discovery_error
        else:
            message = (
                f"扫描{'已取消' if cancelled else '完成'}：发现 {self._total}，"
                f"处理 {self._scanned}，识别 {self._success}，"
                f"待补全 {self._need_network}，失败 {self._failed}，重复 {self._dup}"
            )
        level = "error" if self._discovery_error else "warn" if cancelled else "ok"
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO task_log(ts, level, action, message) VALUES (?, ?, 'scan', ?)",
                (utc_now(), level, message),
            )
        if not self._discovery_error:
            if cancelled:
                log.warning(message)
            else:
                log_ok(log, message)
        try:
            SeriesService(self.db).rebuild_all()
        except Exception as exc:  # 系列归并失败不影响扫描结果
            log.warning("系列归并失败：%s", exc)
        result = {
            "cancelled": cancelled,
            "error": self._discovery_error or None,
            "total": self._total,
            "scanned": self._scanned,
            "success": self._success,
            "need_network": self._need_network,
            "failed": self._failed,
            "dup": self._dup,
            "unchanged": self._unchanged,
            "library_total": BookRepository(self.db).count(),
            "message": message,
        }
        self._workers.clear()
        self.running_changed.emit(False)
        self.finished.emit(result)

    def shutdown(self) -> None:
        self.cancel()
        self.pool.waitForDone(2000)

    def set_incremental(self, enabled: bool) -> None:
        self._incremental = enabled

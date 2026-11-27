"""联网检索/批量补全的后台任务，避免阻塞 UI。"""

from __future__ import annotations

import threading
from typing import Any, Mapping, Sequence

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from ..logger import get_logger
from ..services.metadata_service import MetadataService

log = get_logger("meta-worker")


class SearchSignals(QObject):
    finished = Signal(list)
    failed = Signal(str)


class SearchWorker(QRunnable):
    """对单本书执行 F5 检索，结果按匹配度排序返回。"""

    def __init__(self, service: MetadataService, book: Mapping[str, Any]) -> None:
        super().__init__()
        self.service = service
        self.book = dict(book)
        self.signals = SearchSignals()

    @Slot()
    def run(self) -> None:
        try:
            candidates = self.service.find_candidates(self.book)
            self.signals.finished.emit(candidates)
        except Exception as exc:  # 网络层异常统一转为提示
            log.warning("检索失败：%s", exc)
            self.signals.failed.emit(str(exc))


class CoverSignals(QObject):
    finished = Signal(bytes)
    failed = Signal(str)


class CoverWorker(QRunnable):
    """候选封面缩略图下载，避免在 UI 线程发网络请求。"""

    def __init__(self, service: MetadataService, url: str) -> None:
        super().__init__()
        self.service = service
        self.url = str(url or "")
        self.signals = CoverSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.finished.emit(self.service.cover_bytes(self.url))
        except Exception as exc:  # 封面失败不影响候选展示
            self.signals.failed.emit(str(exc))


class EnrichSignals(QObject):
    progress = Signal(int, int, str)
    finished = Signal(dict)
    failed = Signal(str)


class EnrichWorker(QRunnable):
    """批量重识别：串行逐本，每本独立子线程 + 超时，分批处理，可取消。

    - 网络全部不可用时，每本最多阻塞 per_book_timeout 秒即跳过，不卡死队列；
    - 每本在 daemon 子线程执行 enrich_book，超时仅放弃等待，子线程随网络
      自身超时结束，不阻塞后续书目；数据库连接按线程隔离，子线程写库安全；
    - force=True 强制联网，partial（待补全）允许被新结果覆盖。
    """

    def __init__(
        self,
        service: MetadataService,
        book_ids: Sequence[int],
        *,
        batch_size: int = 50,
        per_book_timeout: float = 8.0,
    ) -> None:
        super().__init__()
        self.service = service
        self.book_ids = [int(book_id) for book_id in book_ids]
        self.batch_size = max(1, int(batch_size))
        self.per_book_timeout = float(per_book_timeout)
        self.signals = EnrichSignals()
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def _enrich_one(self, book_id: int) -> dict[str, Any]:
        """子线程跑 enrich_book，超过 per_book_timeout 仍未结束则记为 timeout。"""
        box: dict[str, Any] = {}

        def target() -> None:
            try:
                box["result"] = self.service.enrich_book(book_id, force=True)
            except Exception as exc:  # 单本异常不中断整批
                box["error"] = str(exc)

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(self.per_book_timeout)
        if thread.is_alive():
            log.warning("[id=%s] 重识别超过 %.0fs，跳过", book_id, self.per_book_timeout)
            return {"book_id": book_id, "status": "timeout",
                    "message": f"超过 {self.per_book_timeout:.0f}s 未响应，已跳过"}
        if "error" in box:
            return {"book_id": book_id, "status": "failed", "message": str(box["error"])}
        return box.get("result") or {"book_id": book_id, "status": "other", "message": ""}

    @Slot()
    def run(self) -> None:
        counts = {"ok": 0, "partial": 0, "failed": 0, "timeout": 0, "other": 0}
        try:
            total = len(self.book_ids)
            done = 0
            for start in range(0, total, self.batch_size):
                if self._cancel_event.is_set():
                    break
                batch = self.book_ids[start:start + self.batch_size]
                for book_id in batch:
                    if self._cancel_event.is_set():
                        break
                    result = self._enrich_one(book_id)
                    done += 1
                    status = str(result.get("status") or "other")
                    counts[status if status in counts else "other"] += 1
                    self.signals.progress.emit(done, total, str(result.get("message") or ""))
            self.signals.finished.emit({
                "total": total,
                "completed": done,
                "cancelled": self._cancel_event.is_set(),
                **counts,
            })
        except Exception as exc:
            log.warning("批量重识别失败：%s", exc)
            self.signals.failed.emit(str(exc))

"""扫描 QRunnable：目录发现与单文件处理均在非 UI 线程执行。"""

from __future__ import annotations

import threading
from typing import Any, Callable, Iterable

from PySide6.QtCore import QObject, QRunnable, Signal

from ..core.scanner import ScannedFile, discover_files


class DiscoverySignals(QObject):
    discovered = Signal(object)
    failed = Signal(str)


class DiscoveryWorker(QRunnable):
    def __init__(
        self,
        directories: Iterable[str],
        options: dict[str, Any],
        cancel_event: threading.Event,
    ) -> None:
        super().__init__()
        self.directories = list(directories)
        self.options = options
        self.cancel_event = cancel_event
        self.signals = DiscoverySignals()

    def run(self) -> None:
        try:
            files = discover_files(
                self.directories,
                self.options["formats"],
                recursive=self.options["recursive"],
                ignore_hidden=self.options["ignore_hidden"],
                min_size_kb=self.options["min_size_kb"],
                max_depth=self.options["max_depth"],
                cancel_check=self.cancel_event.is_set,
            )
            self.signals.discovered.emit(files)
        except Exception as exc:  # worker 边界统一兜底，防止线程静默退出
            self.signals.failed.emit(f"目录扫描失败：{exc}")
            self.signals.discovered.emit([])


class FileSignals(QObject):
    processed = Signal(object)


class FileWorker(QRunnable):
    def __init__(
        self,
        candidate: ScannedFile,
        incremental: bool,
        cancel_event: threading.Event,
        processor: Callable[[ScannedFile, bool], dict[str, Any]],
    ) -> None:
        super().__init__()
        self.candidate = candidate
        self.incremental = incremental
        self.cancel_event = cancel_event
        self.processor = processor
        self.signals = FileSignals()

    def run(self) -> None:
        if self.cancel_event.is_set():
            self.signals.processed.emit(self._cancelled())
            return
        try:
            result = self.processor(self.candidate, self.incremental)
        except Exception as exc:  # 单本异常不能中断整批
            result = {
                "path": str(self.candidate.path),
                "file_name": self.candidate.path.name,
                "format": self.candidate.format,
                "size": self.candidate.size,
                "status": "failed",
                "title": self.candidate.path.stem,
                "message": f"处理失败：{exc}",
            }
        result["cancelled"] = False
        self.signals.processed.emit(result)

    def _cancelled(self) -> dict[str, Any]:
        return {
            "path": str(self.candidate.path),
            "file_name": self.candidate.path.name,
            "format": self.candidate.format,
            "size": self.candidate.size,
            "status": "cancelled",
            "title": self.candidate.path.stem,
            "message": "已取消",
            "cancelled": True,
        }

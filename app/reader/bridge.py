"""QWebChannel 桥：JS 与 Python 之间的进度、书签、高亮、搜索回调。"""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..db.connection import Database
from ..db.repositories.reading_repo import ReadingRepository
from ..logger import get_logger

log = get_logger("reader")

# 需求 3.5：翻页防抖 800ms 落库。
_SAVE_DELAY_MS = 800


class ReaderBridge(QObject):
    """注册到 QWebChannel 的 `bridge` 对象。"""

    frontendReady = Signal()
    renderingFinished = Signal(int)
    progressSaved = Signal(int, float)
    tocReady = Signal(int, str)
    locationChanged = Signal(int, str)
    bookmarkAdded = Signal(int)
    highlightAdded = Signal(int)
    externalRequested = Signal(str)
    failed = Signal(str)
    logged = Signal(str)
    escapeRequested = Signal()
    bookmarkRequested = Signal()
    searchRequested = Signal()
    searchFinished = Signal(int, int)
    chromeToggleRequested = Signal()
    spreadChanged = Signal(int, bool)  # (book_id, 摊开是否生效)

    def __init__(self, db: Database, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.repo = ReadingRepository(db)
        self._pending: tuple[int, str, float] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_SAVE_DELAY_MS)
        self._timer.timeout.connect(self.flush)
        self._session: dict[int, float] = {}

    # ---- JS → Python -------------------------------------------------
    @Slot()
    def ready(self) -> None:  # noqa: A003 - 与前端约定同名
        self.frontendReady.emit()

    @Slot(int, str, float)
    def saveProgress(self, book_id: int, locator_json: str, percent: float) -> None:
        self._pending = (int(book_id), str(locator_json), float(percent))
        self._timer.start()

    @Slot(int, str)
    def toc(self, book_id: int, payload: str) -> None:
        self.tocReady.emit(int(book_id), payload)

    @Slot(int, str)
    def location(self, book_id: int, payload: str) -> None:
        self.locationChanged.emit(int(book_id), payload)

    @Slot(int, str, str, str, result=int)
    def addBookmark(
        self, book_id: int, locator_json: str, label: str, text: str
    ) -> int:
        try:
            bookmark_id = self.repo.add_bookmark(
                int(book_id),
                str(locator_json),
                chapter=label or None,
                text=text or None,
            )
        except Exception as exc:  # 数据库异常不应导致阅读器崩溃
            log.warning("添加书签失败：%s", exc)
            return -1
        self.bookmarkAdded.emit(int(book_id))
        return bookmark_id

    @Slot(int, str, str, str, str, result=int)
    def addHighlight(
        self, book_id: int, locator_json: str, color: str, text: str, note: str
    ) -> int:
        try:
            highlight_id = self.repo.add_bookmark(
                int(book_id),
                str(locator_json),
                text=text or None,
                note=note or None,
                color=color or "#ffe08a",
                kind="highlight",
            )
        except Exception as exc:
            log.warning("添加高亮失败：%s", exc)
            return -1
        self.highlightAdded.emit(int(book_id))
        return highlight_id

    @Slot(int, result=str)
    def getProgress(self, book_id: int) -> str:
        row = self.repo.get_progress(int(book_id))
        return str(row["locator_json"] or "") if row else ""

    @Slot(str)
    def copyText(self, text: str) -> None:
        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(str(text))

    @Slot(str)
    def openExternal(self, path: str) -> None:
        self.externalRequested.emit(str(path))

    @Slot(int)
    def rendered(self, book_id: int) -> None:
        self.renderingFinished.emit(int(book_id))

    @Slot(str)
    def reportError(self, message: str) -> None:
        log.warning("阅读器前端错误：%s", message)
        self.failed.emit(str(message))

    @Slot(str)
    def log(self, message: str) -> None:
        log.info("阅读器：%s", message)
        self.logged.emit(str(message))

    @Slot()
    def escape(self) -> None:
        self.escapeRequested.emit()

    @Slot()
    def requestBookmark(self) -> None:
        self.bookmarkRequested.emit()

    @Slot()
    def requestSearch(self) -> None:
        self.searchRequested.emit()

    @Slot()
    def toggleChrome(self) -> None:
        self.chromeToggleRequested.emit()

    @Slot(int, int)
    def searchResult(self, total: int, current: int) -> None:
        self.searchFinished.emit(int(total), int(current))

    @Slot(int, bool)
    def reportSpread(self, book_id: int, active: bool) -> None:
        """JS 报告当前摊开模式是否真正生效（窗口太窄会临时回落单页）。"""
        self.spreadChanged.emit(int(book_id), bool(active))

    @Slot(str, result=str)
    def askNote(self, selected_text: str) -> str:
        """正文笔记输入（模态对话框，JS 侧同步等待）。"""
        from PySide6.QtWidgets import QInputDialog

        note, accepted = QInputDialog.getMultiLineText(
            None, "添加笔记", f"选中文字：{selected_text[:80]}", ""
        )
        return note.strip() if accepted else ""

    # ---- 落库 --------------------------------------------------------
    def flush(self) -> None:
        """立即写入待保存的进度（退出/切书/关闭窗口时调用）。"""
        self._timer.stop()
        if self._pending is None:
            return
        book_id, locator_json, percent = self._pending
        self._pending = None
        now = time.monotonic()
        elapsed = int(now - self._session.get(book_id, now))
        self._session[book_id] = now
        try:
            self.repo.save_progress(book_id, locator_json, percent, seconds_delta=elapsed)
        except Exception as exc:
            log.warning("保存阅读进度失败：%s", exc)
            return
        self.progressSaved.emit(book_id, percent)

    def begin_session(self, book_id: int) -> None:
        self._session[int(book_id)] = time.monotonic()

    def progress_of(self, book_id: int) -> dict[str, Any] | None:
        row = self.repo.get_progress(int(book_id))
        return dict(row) if row else None

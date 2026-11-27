"""独立阅读窗口：双击书籍时以单独窗口打开阅读器，类似 Calibre 的阅读窗口。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow

from ..db.connection import Database
from ..services.settings_service import SettingsService
from .pages.reader_container import ReaderContainer


class ReaderWindow(QMainWindow):
    """承载 ReaderContainer 的独立顶层窗口，关闭时保存阅读进度。"""

    def __init__(
        self,
        db: Database,
        settings: SettingsService,
        book_id: int,
        title: str,
        *,
        stylesheet: str = "",
    ) -> None:
        super().__init__(None, Qt.Window)
        self.setObjectName("ReaderWindow")
        self.book_id = int(book_id)
        self.setWindowTitle(f"{title} · 阅读")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        if stylesheet:
            self.setStyleSheet(stylesheet)
        self.reader = ReaderContainer(db, settings, parent=self)
        self.reader.back_requested.connect(self.close)
        self.setCentralWidget(self.reader)
        self.setMinimumSize(1000, 700)
        self.resize(1360, 920)
        self.reader.open_book(self.book_id)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.reader.close_book()
        super().closeEvent(event)

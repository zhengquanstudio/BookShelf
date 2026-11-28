"""阅读器左侧栏顶部的封面卡（图 05 · 阅读原型 v3）。

56×78 书封（书脊阴影 + 内描边 + 右上朱红印章）+ 书名 14.5px +
作者/出版社 + 「在读」胶囊 + 3px 进度条 + 百分比 + 圆 i。
颜色跟随阅读器主题（reader_container 通过 _reader_qss + set_theme 注入）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme_tokens import ReaderPalette


class _CoverArt(QWidget):
    """56×78 书封：缩放封面 + 左侧书脊阴影 + 内描边 + 右上朱红印章。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(56, 78)
        self._pix: QPixmap | None = None
        self._palette: ReaderPalette | None = None

    def set_pixmap(self, pix: QPixmap | None) -> None:
        self._pix = pix
        self.update()

    def set_palette(self, palette: ReaderPalette) -> None:  # type: ignore[override]
        self._palette = palette
        self.update()

    def paintEvent(self, _event: Any) -> None:  # noqa: N802 - Qt 命名
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        rect = self.rect()
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        p.setClipPath(path)

        bg = QColor(self._palette.panel) if self._palette else QColor("#ddd8cd")
        p.fillRect(rect, bg)
        if self._pix is not None and not self._pix.isNull():
            scaled = self._pix.scaled(
                rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            x = max(0, (scaled.width() - rect.width()) // 2)
            y = max(0, (scaled.height() - rect.height()) // 2)
            p.drawPixmap(rect, scaled, scaled.rect().adjusted(x, y, x + rect.width(), y + rect.height()))

        # 左侧书脊阴影。
        grad = QLinearGradient(0, 0, 6, 0)
        grad.setColorAt(0, QColor(0, 0, 0, 70))
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(0, 0, 6, rect.height(), grad)

        # 右上朱红印章。
        seal = QLinearGradient(rect.width() - 20, 7, rect.width() - 7, 20)
        seal.setColorAt(0, QColor("#c1483a"))
        seal.setColorAt(1, QColor("#8e2a20"))
        p.setOpacity(0.85)
        p.fillRect(rect.width() - 7 - 13, 7, 13, 13, seal)
        p.setOpacity(1.0)
        p.setClipping(False)

        # 内描边。
        p.setPen(QColor(0, 0, 0, 45))
        p.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 6, 6)
        p.end()


class ReaderCoverCard(QFrame):
    """侧栏封面卡；点圆 i 发出 detail_requested（复用 R3 详情浮层同一实例）。"""

    detail_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ReaderCoverCard")
        self.setCursor(Qt.PointingHandCursor)
        self._palette: ReaderPalette | None = None
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(11)

        self.cover = _CoverArt()
        layout.addWidget(self.cover)

        info = QVBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(1)
        self.title_label = QLabel()
        self.title_label.setObjectName("ReaderCoverTitle")
        self.title_label.setTextFormat(Qt.PlainText)
        self.title_label.setSizePolicy(
            self.title_label.sizePolicy().horizontalPolicy(),
            self.title_label.sizePolicy().verticalPolicy(),
        )
        info.addWidget(self.title_label)
        self.author_label = QLabel()
        self.author_label.setObjectName("ReaderCoverAuthor")
        self.author_label.setTextFormat(Qt.PlainText)
        info.addWidget(self.author_label)

        meta = QHBoxLayout()
        meta.setContentsMargins(0, 5, 0, 0)
        meta.setSpacing(6)
        self.status_pill = QLabel("在读")
        self.status_pill.setObjectName("ReaderCoverPill")
        self.status_pill.setAlignment(Qt.AlignCenter)
        meta.addWidget(self.status_pill)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("ReaderCoverProgress")
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(3)
        meta.addWidget(self.progress_bar, 1)
        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("ReaderCoverPercent")
        meta.addWidget(self.percent_label)
        info.addLayout(meta)
        layout.addLayout(info, 1)

        self.info_button = QPushButton("i")
        self.info_button.setObjectName("ReaderCoverInfo")
        self.info_button.setFixedSize(22, 22)
        self.info_button.setCursor(Qt.PointingHandCursor)
        self.info_button.setToolTip("书籍详情")
        layout.addWidget(self.info_button)
        self.info_button.clicked.connect(self.detail_requested)

    def set_book(self, book: dict[str, Any]) -> None:
        title = str(book.get("title") or "未命名")
        author = str(book.get("author_name") or book.get("author_raw") or "")
        publisher = str(book.get("publisher") or "")
        self.title_label.setText(title)
        self.title_label.setToolTip(title)
        ba = " · ".join(part for part in (author, publisher) if part) or "作者未知"
        self.author_label.setText(ba)
        self.author_label.setToolTip(ba)

    def set_cover_pixmap(self, pix: QPixmap | None) -> None:
        self.cover.set_pixmap(pix)

    def set_progress(self, percent: float) -> None:
        pct = max(0.0, min(1.0, float(percent or 0.0)))
        self.progress_bar.setValue(int(round(pct * 1000)))
        self.percent_label.setText(f"{int(round(pct * 100))}%")
        self.status_pill.setText("已读完" if pct >= 1.0 else "在读")

    def set_theme(self, palette: ReaderPalette) -> None:
        self._palette = palette
        self.cover.set_palette(palette)

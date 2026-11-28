"""T20：我的书架网格视图，复用书库的 BookTableModel。"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ..theme import chrome_tokens
from ..widgets.book_detail_overlay import BookDetailOverlay
from ..widgets.book_table import BookTableModel


class ShelfCardDelegate(QStyledItemDelegate):
    """绘制 132×176 封面卡片；只读模型，不持有书籍查询。"""

    COVER_W = 132
    COVER_H = 176
    CARD_H = 282
    GAP = 14

    def __init__(self, parent: QListView) -> None:
        super().__init__(parent)
        self._theme = "night"
        self._accent = "blue"
        self._cover_cache: dict[str, QPixmap | None] = {}

    def set_theme(self, theme: str, accent: str = "blue") -> None:
        self._theme = theme
        self._accent = accent

    @staticmethod
    def placeholder_text(book: dict[str, Any]) -> str:
        title = str(book.get("title") or "").strip()
        return title[:1] if title else "书"

    @staticmethod
    def info_rect(card_rect: QRect) -> QRect:
        return QRect(card_rect.right() - 29, card_rect.top() + 6, 24, 24)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        view = option.widget
        if isinstance(view, QListView) and view.gridSize().isValid():
            return view.gridSize()
        return QSize(156, self.CARD_H)

    def _cover(self, path: str) -> QPixmap | None:
        if not path:
            return None
        if path not in self._cover_cache:
            pixmap = QPixmap(path)
            self._cover_cache[path] = None if pixmap.isNull() else pixmap
            if len(self._cover_cache) > 128:
                self._cover_cache.pop(next(iter(self._cover_cache)))
        return self._cover_cache[path]

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: N802
        model = index.model()
        book = model.row_data(index.row()) if hasattr(model, "row_data") else None
        book = book or {}
        tokens = chrome_tokens(self._theme, self._accent)
        selected = bool(option.state & QStyle.State_Selected)
        card = option.rect.adjusted(2, 2, -2, -2)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(tokens["accent"] if selected else tokens["line"]), 1))
        painter.setBrush(QColor(tokens["panel"]))
        painter.drawRoundedRect(card, 12, 12)

        cover_rect = QRect(
            card.center().x() - self.COVER_W // 2,
            card.top() + 12,
            self.COVER_W,
            self.COVER_H,
        )
        clip = QPainterPath()
        clip.addRoundedRect(cover_rect, 8, 8)
        painter.save()
        painter.setClipPath(clip)
        cover = self._cover(str(book.get("cover_path") or ""))
        if cover is None:
            gradient = QLinearGradient(cover_rect.topLeft(), cover_rect.bottomRight())
            gradient.setColorAt(0, QColor("#f2e6d2"))
            gradient.setColorAt(1, QColor("#d9c8ae"))
            painter.fillRect(cover_rect, gradient)
            font = QFont(option.font)
            font.setPointSize(42)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#6c5f4b"))
            painter.drawText(cover_rect, int(Qt.AlignCenter), self.placeholder_text(book))
        else:
            scaled = cover.scaled(
                cover_rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            source = scaled.copy(
                max(0, (scaled.width() - self.COVER_W) // 2),
                max(0, (scaled.height() - self.COVER_H) // 2),
                self.COVER_W,
                self.COVER_H,
            )
            painter.drawPixmap(cover_rect, source)
        painter.restore()

        title_font = QFont(option.font)
        title_font.setPointSizeF(12.5)
        title_font.setBold(True)
        title_rect = QRect(card.left() + 12, cover_rect.bottom() + 8, card.width() - 24, 40)
        self._draw_title(painter, str(book.get("title") or "未命名"), title_rect, title_font, tokens["ink"])

        meta_font = QFont(option.font)
        meta_font.setPointSizeF(10.5)
        painter.setFont(meta_font)
        painter.setPen(QColor(tokens["muted"]))
        meta_rect = QRect(card.left() + 12, title_rect.bottom() + 2, card.width() - 24, 18)
        author = str(book.get("author_name") or book.get("author_raw") or "作者未知")
        painter.drawText(meta_rect, int(Qt.AlignLeft | Qt.AlignVCenter), QFontMetrics(meta_font).elidedText(author, Qt.ElideRight, meta_rect.width() - 22))
        painter.setPen(QColor(tokens["warn"]))
        painter.drawText(meta_rect, int(Qt.AlignRight | Qt.AlignVCenter), "★" if book.get("favorite") else "☆")

        info = self.info_rect(card)
        painter.setPen(QPen(QColor(tokens["line2"]), 1))
        painter.setBrush(QColor(tokens["panel2"]))
        painter.drawEllipse(info)
        painter.setPen(QColor(tokens["muted"]))
        painter.drawText(info, int(Qt.AlignCenter), "i")

        progress = max(0.0, min(1.0, float(book.get("progress") or 0.0)))
        bar = QRect(card.left() + 12, card.bottom() - 12, card.width() - 24, 5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(tokens["panel2"]))
        painter.drawRoundedRect(bar, 2.5, 2.5)
        if progress > 0:
            fill = QRect(bar.left(), bar.top(), max(3, round(bar.width() * progress)), bar.height())
            painter.setBrush(QColor(tokens["accent"]))
            painter.drawRoundedRect(fill, 2.5, 2.5)
        painter.restore()

    @staticmethod
    def _draw_title(painter: QPainter, text: str, rect: QRect, font: QFont, color: str) -> None:
        painter.setFont(font)
        painter.setPen(QColor(color))
        metrics = QFontMetrics(font)
        if metrics.horizontalAdvance(text) <= rect.width():
            painter.drawText(rect, int(Qt.AlignLeft | Qt.AlignTop), text)
            return
        split = len(text)
        while split > 1:
            if (
                metrics.horizontalAdvance(text[:split]) <= rect.width()
                and metrics.horizontalAdvance(text[split:]) <= rect.width()
            ):
                break
            split -= 1
        first = text[:split]
        second = metrics.elidedText(text[split:], Qt.ElideRight, rect.width())
        line_height = metrics.lineSpacing()
        painter.drawText(QRect(rect.left(), rect.top(), rect.width(), line_height), int(Qt.AlignLeft), first)
        painter.drawText(QRect(rect.left(), rect.top() + line_height, rect.width(), line_height), int(Qt.AlignLeft), second)


class ShelfPage(QWidget):
    """我的书架：有阅读记录或已收藏的书，共用书库模型与筛选状态。"""

    open_requested = Signal(int)
    go_library_requested = Signal()
    query_changed = Signal(str, str, bool)

    SORTS = (
        ("按阅读进度", "progress"),
        ("按添加时间", "added_at"),
        ("按书名", "title"),
        ("按作者", "author"),
        ("按文件大小", "file_size"),
    )

    def __init__(self, model: BookTableModel, library: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = model
        self.library = library
        self.total = 0
        self._desc = True
        self._format_name = ""
        self._tag_filter = ""
        self._folder_filter = ""
        self.setObjectName("ShelfPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 18)
        root.setSpacing(12)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("搜索书架中的书名 / 作者 / ISBN")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setFixedWidth(240)
        toolbar.addWidget(self.search_box)
        toolbar.addStretch(1)
        self.sort_combo = QComboBox()
        self.sort_combo.setObjectName("ShelfSort")
        for label, key in self.SORTS:
            self.sort_combo.addItem(label, key)
        toolbar.addWidget(self.sort_combo)
        self.order_button = QPushButton("降序 ↓")
        self.order_button.setObjectName("GhostButton")
        toolbar.addWidget(self.order_button)
        root.addLayout(toolbar)

        self.stack = QStackedWidget()
        self.list = QListView()
        self.list.setObjectName("ShelfGrid")
        self.list.setModel(self.model)
        self.list.setViewMode(QListView.IconMode)
        self.list.setMovement(QListView.Static)
        self.list.setResizeMode(QListView.Adjust)
        self.list.setUniformItemSizes(True)
        self.list.setSpacing(ShelfCardDelegate.GAP)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setWordWrap(True)
        self.delegate = ShelfCardDelegate(self.list)
        self.list.setItemDelegate(self.delegate)
        self.stack.addWidget(self.list)

        self.empty_page = QFrame()
        self.empty_page.setObjectName("ShelfEmpty")
        empty = QVBoxLayout(self.empty_page)
        empty.setContentsMargins(30, 60, 30, 60)
        empty.setSpacing(12)
        empty.addStretch(1)
        skeleton = QLabel("▦")
        skeleton.setObjectName("ShelfEmptySkeleton")
        skeleton.setAlignment(Qt.AlignCenter)
        empty.addWidget(skeleton)
        self.empty_title = QLabel("暂无数据")
        self.empty_title.setObjectName("PageTitle")
        self.empty_title.setAlignment(Qt.AlignCenter)
        empty.addWidget(self.empty_title)
        self.empty_hint = QLabel("书架还空着，去书库挑一本")
        self.empty_hint.setObjectName("DetailSub")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        empty.addWidget(self.empty_hint)
        self.go_library_button = QPushButton("去书库")
        self.go_library_button.setObjectName("PrimaryButton")
        self.go_library_button.clicked.connect(self.go_library_requested)
        empty.addWidget(self.go_library_button, 0, Qt.AlignCenter)
        empty.addStretch(1)
        self.stack.addWidget(self.empty_page)
        root.addWidget(self.stack, 1)

        self.detail_overlay = BookDetailOverlay(
            self,
            on_close=self._hide_details,
            on_reveal=self._hide_details,
            on_rename=self._hide_details,
            library=self.library,
            compact=True,
        )

        self.search_box.textChanged.connect(self._on_query_changed)
        self.sort_combo.currentIndexChanged.connect(self._on_query_changed)
        self.order_button.clicked.connect(self._toggle_order)
        self.list.clicked.connect(self._on_card_clicked)
        self.list.doubleClicked.connect(self._on_card_opened)
        self._update_grid()

    @property
    def card_count(self) -> int:
        return self.model.rowCount()

    def set_filters(self, *, format_name: str = "", tag: str = "", folder: str = "") -> None:
        self._format_name = format_name
        self._tag_filter = tag
        self._folder_filter = folder

    def set_query(self, *, search: str, sort: str, desc: bool) -> None:
        for widget in (self.search_box, self.sort_combo):
            widget.blockSignals(True)
        self.search_box.setText(search)
        index = self.sort_combo.findData(sort)
        self.sort_combo.setCurrentIndex(index if index >= 0 else 0)
        for widget in (self.search_box, self.sort_combo):
            widget.blockSignals(False)
        self._desc = bool(desc)
        self._update_order_button()

    def set_theme(self, theme: str, accent: str = "blue") -> None:
        self.delegate.set_theme(theme, accent)
        self.list.viewport().update()

    def refresh(self) -> None:
        rows, total = self.library.query_books(
            nav_key="all",
            search=self.search_box.text(),
            format_name=self._format_name,
            tag=self._tag_filter,
            folder=self._folder_filter,
            page=1,
            page_size=1000,
            sort=str(self.sort_combo.currentData() or "progress"),
            desc=self._desc,
            shelf_only=True,
        )
        self.model.set_rows(rows)
        self.total = total
        self.stack.setCurrentWidget(self.list if rows else self.empty_page)
        self._update_grid()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_grid()
        if self.detail_overlay.isVisible():
            self._position_details()

    def _update_grid(self) -> None:
        width = max(1, self.list.viewport().width())
        columns = max(3, width // (ShelfCardDelegate.COVER_W + 24))
        available = width - ShelfCardDelegate.GAP * (columns - 1)
        cell_width = max(156, available // columns)
        self.list.setGridSize(QSize(cell_width, ShelfCardDelegate.CARD_H))
        self.list.doItemsLayout()

    def _on_query_changed(self, *_args) -> None:
        self.query_changed.emit(
            self.search_box.text(), str(self.sort_combo.currentData() or "progress"), self._desc
        )
        self.refresh()

    def _toggle_order(self) -> None:
        self._desc = not self._desc
        self._update_order_button()
        self._on_query_changed()

    def _update_order_button(self) -> None:
        self.order_button.setText("降序 ↓" if self._desc else "升序 ↑")

    def _on_card_clicked(self, index) -> None:
        book = self.model.row_data(index.row())
        if not book:
            return
        rect = self.list.visualRect(index)
        card = rect.adjusted(2, 2, -2, -2)
        pos = self.list.mapFromGlobal(self.list.cursor().pos())
        if ShelfCardDelegate.info_rect(card).contains(pos):
            self.detail_overlay.show_for(int(book["id"]))
            self._position_details()

    def _on_card_opened(self, index) -> None:
        book_id = self.model.book_id(index.row())
        if book_id is not None:
            self.open_requested.emit(int(book_id))

    def _position_details(self) -> None:
        self.detail_overlay.setMaximumHeight(min(600, max(320, self.height() - 24)))
        self.detail_overlay.adjustSize()
        x = self.width() - self.detail_overlay.width() - 12
        self.detail_overlay.move(max(12, x), 12)
        self.detail_overlay.raise_()

    def _hide_details(self) -> None:
        self.detail_overlay.hide()


__all__ = ["ShelfCardDelegate", "ShelfPage"]

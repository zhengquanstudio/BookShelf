"""T22：笔记 / 高亮 / 书签聚合页，复用 bookmarks 仓储与阅读器跳转。"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...db.repositories.reading_repo import ReadingRepository
from ..theme import is_light_theme
from ..theme_tokens import resolve_highlight_color


class NoteRow(QFrame):
    """单条标注；点击打开位置，删除按钮不触发位置跳转。"""

    open_requested = Signal(dict)
    delete_requested = Signal(dict)

    def __init__(self, row: dict[str, Any], *, dark: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.row_data = row
        self._dark = dark
        self.setObjectName("NoteRow")
        self.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        text_column = QVBoxLayout()
        text_column.setSpacing(4)
        primary = str(row.get("text") or row.get("chapter") or row.get("note") or "书签")
        self.text_label = QLabel(primary)
        self.text_label.setObjectName("NoteText")
        self.text_label.setWordWrap(True)
        text_column.addWidget(self.text_label)
        note = str(row.get("note") or "").strip()
        if note and note != primary:
            self.note_label = QLabel(note)
            self.note_label.setObjectName("NoteComment")
            self.note_label.setWordWrap(True)
            text_column.addWidget(self.note_label)
        else:
            self.note_label = None
        meta = " · ".join(
            part
            for part in (str(row.get("chapter") or "").strip(), str(row.get("created_at") or "")[:16])
            if part
        )
        self.meta_label = QLabel(meta)
        self.meta_label.setObjectName("NoteMeta")
        text_column.addWidget(self.meta_label)
        layout.addLayout(text_column, 1)

        self.color_dot = QLabel()
        self.color_dot.setObjectName("NoteColorDot")
        self.color_dot.setFixedSize(12, 12)
        layout.addWidget(self.color_dot, 0, Qt.AlignVCenter)
        self.delete_button = QPushButton("删除")
        self.delete_button.setObjectName("GhostButton")
        self.delete_button.setCursor(Qt.PointingHandCursor)
        self.delete_button.clicked.connect(lambda: self.delete_requested.emit(self.row_data))
        layout.addWidget(self.delete_button, 0, Qt.AlignVCenter)
        self.set_dark(dark)

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        color = resolve_highlight_color(self.row_data.get("color"), dark=dark)
        self.color_dot.setStyleSheet(f"background: {color}; border-radius: 6px; border: none;")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.open_requested.emit(self.row_data)
            event.accept()
            return
        super().mousePressEvent(event)


class NotesPage(QWidget):
    """三类互斥过滤，搜索正文/想法，按书分组并支持折叠。"""

    CATEGORIES = (("note", "笔记"), ("highlight", "高亮"), ("bookmark", "书签"))
    EMPTY_TEXT = {
        "note": "还没有笔记",
        "highlight": "还没有高亮，选中正文即可标记",
        "bookmark": "还没有书签，按 Ctrl+D 添加",
    }

    open_locator_requested = Signal(int, str)
    go_shelf_requested = Signal()
    toast_requested = Signal(str)

    def __init__(self, db: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo = ReadingRepository(db)
        self.category = "note"
        self.rows: list[dict[str, Any]] = []
        self.row_widgets: list[NoteRow] = []
        self._dark = True
        self.setObjectName("NotesPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 18)
        root.setSpacing(12)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        self.tab_buttons: dict[str, QPushButton] = {}
        for key, label in self.CATEGORIES:
            button = QPushButton(label)
            button.setObjectName("SegButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setChecked(key == self.category)
            button.clicked.connect(lambda _checked=False, value=key: self.set_category(value))
            self._tab_group.addButton(button)
            self.tab_buttons[key] = button
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("搜索笔记与正文")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setFixedWidth(240)
        self.search_box.textChanged.connect(self.refresh)
        toolbar.addWidget(self.search_box)
        root.addLayout(toolbar)

        self.stack = QStackedWidget()
        self.tree = QTreeWidget()
        self.tree.setObjectName("NotesTree")
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setItemsExpandable(True)
        self.tree.setIndentation(18)
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tree.setFrameShape(QFrame.NoFrame)
        self.stack.addWidget(self.tree)

        self.empty_page = QFrame()
        self.empty_page.setObjectName("NotesEmpty")
        empty = QVBoxLayout(self.empty_page)
        empty.setContentsMargins(30, 60, 30, 60)
        empty.setSpacing(12)
        empty.addStretch(1)
        self.empty_skeleton = QLabel("✎")
        self.empty_skeleton.setObjectName("NotesEmptySkeleton")
        self.empty_skeleton.setAlignment(Qt.AlignCenter)
        empty.addWidget(self.empty_skeleton)
        self.empty_title = QLabel("暂无数据")
        self.empty_title.setObjectName("PageTitle")
        self.empty_title.setAlignment(Qt.AlignCenter)
        empty.addWidget(self.empty_title)
        self.empty_hint = QLabel(self.EMPTY_TEXT[self.category])
        self.empty_hint.setObjectName("DetailSub")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setWordWrap(True)
        empty.addWidget(self.empty_hint)
        self.go_shelf_button = QPushButton("去书架")
        self.go_shelf_button.setObjectName("PrimaryButton")
        self.go_shelf_button.clicked.connect(self.go_shelf_requested)
        empty.addWidget(self.go_shelf_button, 0, Qt.AlignCenter)
        empty.addStretch(1)
        self.stack.addWidget(self.empty_page)
        root.addWidget(self.stack, 1)
        self.refresh()

    @property
    def visible_count(self) -> int:
        return len(self.rows)

    def set_category(self, category: str) -> None:
        if category not in self.EMPTY_TEXT:
            return
        self.category = category
        self.tab_buttons[category].setChecked(True)
        self.empty_skeleton.setText({"note": "✎", "highlight": "▨", "bookmark": "▮"}[category])
        self.refresh()

    def set_theme(self, theme: str, _accent: str = "blue") -> None:
        self._dark = not is_light_theme(theme)
        for row in self.row_widgets:
            row.set_dark(self._dark)

    def refresh(self, *_args) -> None:
        self.rows = self.repo.list_annotations(self.category, search=self.search_box.text())
        self.tree.clear()
        self.row_widgets.clear()
        groups: dict[int, QTreeWidgetItem] = {}
        for row in self.rows:
            book_id = int(row["book_id"])
            group = groups.get(book_id)
            if group is None:
                group = QTreeWidgetItem([f"{row['book_title']}  ·  1"])
                group.setData(0, Qt.UserRole, book_id)
                self.tree.addTopLevelItem(group)
                groups[book_id] = group
            else:
                group.setText(0, f"{row['book_title']}  ·  {group.childCount() + 1}")
            child = QTreeWidgetItem(group)
            child.setData(0, Qt.UserRole, int(row["id"]))
            widget = NoteRow(row, dark=self._dark)
            widget.open_requested.connect(self._open_row)
            widget.delete_requested.connect(self._delete_row)
            self.tree.setItemWidget(child, 0, widget)
            child.setSizeHint(0, widget.sizeHint())
            self.row_widgets.append(widget)
        self.tree.expandAll()
        self.empty_hint.setText(self.EMPTY_TEXT[self.category])
        self.stack.setCurrentWidget(self.tree if self.rows else self.empty_page)

    def _open_row(self, row: dict[str, Any]) -> None:
        self.open_locator_requested.emit(int(row["book_id"]), str(row["locator_json"] or ""))

    def _delete_row(self, row: dict[str, Any]) -> None:
        if self.repo.delete_bookmark(int(row["id"])):
            self.toast_requested.emit("已删除")
        self.refresh()


__all__ = ["NoteRow", "NotesPage"]

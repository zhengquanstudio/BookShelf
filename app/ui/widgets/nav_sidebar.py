"""左侧导航（图 01）：分组 + 数量角标。"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

_LIBRARY_ITEMS = [
    ("all", "全部书籍"),
    ("pending", "待整理"),
    ("partial", "◐ 待补全"),
    ("archived", "已归档"),
    ("failed", "○ 识别失败"),
]
_CATEGORY_ITEMS = [
    ("authors", "作者目录"),
    ("series", "套书系列"),
    ("folders", "文件夹视图"),
    ("tags", "标签"),
    ("favorites", "收藏"),
]
_BASE_TEXT_ROLE = Qt.UserRole + 1


class NavSidebar(QWidget):
    """书库 / 分类两组导航，选中项带主色条。"""

    nav_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NavSidebar")
        self.setFixedWidth(220)
        self._list = QListWidget()
        self._list.setObjectName("NavList")
        self._list.setFrameShape(QFrame.NoFrame)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(0)
        layout.addWidget(self._list)

        self._add_group("书库")
        for key, text in _LIBRARY_ITEMS:
            self._add_item(key, text, indent=False)
        self._add_group("分类")
        for key, text in _CATEGORY_ITEMS:
            self._add_item(key, text, indent=True)
        self._add_group("")
        self._add_item("settings", "设置", indent=False)
        self._add_item("help", "帮助", indent=False)

        self._list.currentItemChanged.connect(self._on_changed)
        self.set_current("all")

    def _add_group(self, text: str) -> None:
        if not text:
            spacer = QListWidgetItem("")
            spacer.setFlags(Qt.NoItemFlags)
            spacer.setSizeHint(QSize(0, 14))
            self._list.addItem(spacer)
            return
        item = QListWidgetItem(text)
        item.setFlags(Qt.NoItemFlags)
        item.setData(Qt.UserRole, "group")
        font = item.font()
        font.setPointSizeF(9.5)
        item.setFont(font)
        item.setSizeHint(QSize(0, 30))
        self._list.addItem(item)

    def _add_item(self, key: str, text: str, indent: bool) -> None:
        label = ("    " if indent else "  ") + text
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, key)
        item.setData(_BASE_TEXT_ROLE, label)
        item.setSizeHint(QSize(0, 34))
        self._list.addItem(item)

    def _on_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        key = current.data(Qt.UserRole)
        if key and key != "group":
            self.nav_changed.emit(str(key))

    def set_current(self, key: str) -> None:
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.data(Qt.UserRole) == key:
                self._list.setCurrentItem(item)
                return

    def set_current_silent(self, key: str) -> None:
        """只移动选中项，不触发 nav_changed（用于从子页面返回）。"""
        blocked = self._list.blockSignals(True)
        try:
            self.set_current(key)
        finally:
            self._list.blockSignals(blocked)

    def current_key(self) -> str:
        item = self._list.currentItem()
        if item is None:
            return ""
        key = item.data(Qt.UserRole)
        return str(key) if key and key != "group" else ""

    def set_badge(self, key: str, count: int) -> None:
        """在导航项右侧显示数量，例如“全部书籍   135”。"""
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.data(Qt.UserRole) != key:
                continue
            label = str(item.data(_BASE_TEXT_ROLE) or item.text())
            item.setText(f"{label}   {count}" if count else label)
            return

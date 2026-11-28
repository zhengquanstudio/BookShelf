"""左侧导航（图 01）：四组 + 数量角标 + 3px 选中条（自定义项，对齐 v4 原型）。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

_LIBRARY_ITEMS = [
    ("all", "全部书籍", "▤"),
    ("pending", "待整理", "◷"),
    ("partial", "待补全", "◐"),
    ("archived", "已归档", "✓"),
    ("failed", "识别失败", "!"),
]
_CATEGORY_ITEMS = [
    ("authors", "作者", "◍"),
    ("series", "系列", "❏"),
    ("folders", "文件夹", "▣"),
    ("tags", "标签", "#"),
    ("favorites", "收藏", "★"),
]
_READING_ITEMS = [
    ("shelf", "我的书架", "▦"),
    ("stats", "阅读统计", "◔"),
    ("notes", "笔记与高亮", "✎"),
]
_OTHER_ITEMS = [
    ("settings", "设置", "⚙"),
    ("help", "帮助", "?"),
]


class _NavItem(QPushButton):
    """单个导航项：3px 左条 + 图标 + 标题 + 右对齐计数。"""

    def __init__(self, key: str, text: str, icon: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName("NavItem")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(32)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(9)

        self._bar = QLabel()
        self._bar.setObjectName("NavBar")
        self._bar.setFixedWidth(3)
        self._bar.setVisible(False)
        lay.addWidget(self._bar)

        self._icon = QLabel(icon)
        self._icon.setObjectName("NavIcon")
        self._icon.setFixedWidth(16)
        self._icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._icon)

        self._title = QLabel(text)
        self._title.setObjectName("NavTitle")
        lay.addWidget(self._title)

        lay.addStretch(1)

        self._count = QLabel()
        self._count.setObjectName("NavCount")
        self._count.setVisible(False)
        lay.addWidget(self._count)

        self.toggled.connect(self._on_toggled)

    def set_count(self, count: int) -> None:
        if count:
            self._count.setText(str(count))
            self._count.setVisible(True)
        else:
            self._count.setVisible(False)

    def _on_toggled(self, checked: bool) -> None:
        self._bar.setVisible(checked)
        # 触发 QSS 重算（:checked 下的子控件颜色）
        self.style().unpolish(self)
        self.style().polish(self)


class NavSidebar(QWidget):
    """四组导航（书库 / 分类 / 阅读 / 其他），选中项带主色 3px 左条。"""

    nav_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NavSidebar")
        self.setFixedWidth(236)
        self._items: dict[str, _NavItem] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._current = "all"

        scroll = QScrollArea()
        scroll.setObjectName("NavScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        container.setObjectName("NavContainer")
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(10, 12, 10, 12)
        self._layout.setSpacing(0)

        self._add_group("书库")
        for key, text, icon in _LIBRARY_ITEMS:
            self._add_item(key, text, icon)
        self._add_group("分类")
        for key, text, icon in _CATEGORY_ITEMS:
            self._add_item(key, text, icon)
        self._add_group("阅读")
        for key, text, icon in _READING_ITEMS:
            self._add_item(key, text, icon)
        self._add_group("其他")
        for key, text, icon in _OTHER_ITEMS:
            self._add_item(key, text, icon)
        self._layout.addStretch(1)

        scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll)

        self.set_current("all")

    def _add_group(self, text: str) -> None:
        label = QLabel(text)
        label.setObjectName("NavLabel")
        self._layout.addWidget(label)

    def _add_item(self, key: str, text: str, icon: str) -> None:
        item = _NavItem(key, text, icon)
        item.clicked.connect(lambda _=False, k=key: self.set_current(k))
        self._group.addButton(item)
        self._items[key] = item
        self._layout.addWidget(item)

    def keys(self) -> list[str]:
        return list(self._items.keys())

    def set_current(self, key: str) -> None:
        self._select(key, emit=True)

    def set_current_silent(self, key: str) -> None:
        """只移动选中项，不触发 nav_changed（用于从子页面返回）。"""
        self._select(key, emit=False)

    def _select(self, key: str, emit: bool) -> None:
        item = self._items.get(key)
        if item is None:
            return
        changed = key != self._current
        self._current = key
        item.setChecked(True)
        if emit and changed:
            self.nav_changed.emit(key)

    def current_key(self) -> str:
        return self._current

    def set_badge(self, key: str, count: int) -> None:
        """在导航项右侧显示数量。"""
        item = self._items.get(key)
        if item is not None:
            item.set_count(count)

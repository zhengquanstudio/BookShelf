"""M7 通用筛选对话框：按标签或文件夹挑选一个筛选值。"""

from __future__ import annotations

from typing import Any, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class FilterDialog(QDialog):
    """展示“名称 + 数量”列表，选中后返回对应值。"""

    def __init__(
        self,
        title: str,
        hint: str,
        entries: Sequence[dict[str, Any]],
        parent: QWidget | None = None,
        *,
        value_key: str = "name",
        label_key: str = "name",
        searchable: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FilterDialog")
        self.setWindowTitle(title)
        self.resize(560, 540)
        self.selected_value: str = ""
        self._value_key = value_key
        self._label_key = label_key

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        layout.addWidget(QLabel(hint))

        self._search = QLineEdit()
        self._search.setObjectName("SearchBox")
        self._search.setPlaceholderText("搜索…")
        self._search.setClearButtonEnabled(True)
        self._search.setVisible(searchable)
        self._search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._search)

        self._list = QListWidget()
        for entry in entries:
            label = str(entry.get(self._label_key) or "")
            item = QListWidgetItem(f"{label}    {int(entry.get('count') or 0)} 本")
            item.setData(Qt.UserRole, label)
            item.setToolTip(label)
            self._list.addItem(item)
        self._list.itemDoubleClicked.connect(lambda _item: self._accept())
        layout.addWidget(self._list, 1)

        buttons = QHBoxLayout()
        clear_button = QPushButton("清除筛选")
        clear_button.setObjectName("GhostButton")
        clear_button.clicked.connect(self._clear)
        cancel_button = QPushButton("取消")
        cancel_button.setObjectName("GhostButton")
        cancel_button.clicked.connect(self.reject)
        apply_button = QPushButton("应用")
        apply_button.setObjectName("PrimaryButton")
        apply_button.clicked.connect(self._accept)
        buttons.addWidget(clear_button)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(apply_button)
        layout.addLayout(buttons)

        if self._list.count():
            self._list.setCurrentRow(0)

    def _apply_filter(self, text: str) -> None:
        keyword = text.strip().lower()
        first_visible: QListWidgetItem | None = None
        for index in range(self._list.count()):
            item = self._list.item(index)
            hidden = bool(keyword) and keyword not in item.text().lower()
            item.setHidden(hidden)
            if not hidden and first_visible is None:
                first_visible = item
        if first_visible is not None:
            self._list.setCurrentItem(first_visible)

    def _accept(self) -> None:
        item = self._list.currentItem()
        if item is None or item.isHidden():
            item = next(
                (
                    self._list.item(index)
                    for index in range(self._list.count())
                    if not self._list.item(index).isHidden()
                ),
                None,
            )
        if item is None:
            return
        self.selected_value = str(item.data(Qt.UserRole) or "")
        if self.selected_value:
            self.accept()

    def _clear(self) -> None:
        self.selected_value = ""
        self.accept()

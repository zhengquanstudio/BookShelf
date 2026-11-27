"""M7 标签管理：筛选、重命名、合并与删除。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...services.library_service import FAVORITE_TAG, LibraryService


class TagManagerDialog(QDialog):
    """标签列表 + 管理按钮；应用筛选时把标签名写入 selected_value。"""

    def __init__(self, library: LibraryService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.library = library
        self.selected_value = ""
        self.setObjectName("TagManagerDialog")
        self.setWindowTitle("标签管理")
        self.resize(600, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        layout.addWidget(
            QLabel(
                "双击标签按它筛选书库；重命名到已有名称时会自动合并两个标签。"
                "「收藏」是内置标签，不能重命名或删除。"
            )
        )

        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("搜索标签…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._filter_items)
        layout.addWidget(self.search_box)

        self.tag_list = QListWidget()
        self.tag_list.itemDoubleClicked.connect(lambda _item: self._apply())
        layout.addWidget(self.tag_list, 1)

        buttons = QHBoxLayout()
        for text, handler in (
            ("重命名", self._rename),
            ("合并到…", self._merge),
            ("删除", self._delete),
        ):
            button = QPushButton(text)
            button.setObjectName("GhostButton")
            button.clicked.connect(handler)
            buttons.addWidget(button)
        buttons.addStretch(1)
        cancel_button = QPushButton("关闭")
        cancel_button.setObjectName("GhostButton")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)
        apply_button = QPushButton("按此标签筛选")
        apply_button.setObjectName("PrimaryButton")
        apply_button.clicked.connect(self._apply)
        buttons.addWidget(apply_button)
        layout.addLayout(buttons)

        self._refresh()

    # ---- 数据 -------------------------------------------------------
    def _refresh(self, select: str | None = None) -> None:
        entries = self.library.tag_counts()
        current = select or self._current_name()
        self.tag_list.blockSignals(True)
        self.tag_list.clear()
        target_row = -1
        for index, entry in enumerate(entries):
            name = str(entry["name"])
            suffix = "（内置）" if name == FAVORITE_TAG else ""
            item = QListWidgetItem(f"{name}    {int(entry.get('count') or 0)} 本{suffix}")
            item.setData(Qt.UserRole, name)
            item.setToolTip(name)
            self.tag_list.addItem(item)
            if name == current:
                target_row = index
        self.tag_list.blockSignals(False)
        self._filter_items(self.search_box.text())
        if entries:
            self.tag_list.setCurrentRow(max(0, target_row))

    def _names(self) -> list[str]:
        return [
            str(self.tag_list.item(index).data(Qt.UserRole))
            for index in range(self.tag_list.count())
        ]

    def _current_name(self) -> str:
        item = self.tag_list.currentItem()
        return str(item.data(Qt.UserRole) or "") if item is not None else ""

    def _filter_items(self, text: str) -> None:
        keyword = text.strip().lower()
        for index in range(self.tag_list.count()):
            item = self.tag_list.item(index)
            item.setHidden(bool(keyword) and keyword not in item.text().lower())

    # ---- 操作 -------------------------------------------------------
    def _ensure_editable(self, name: str) -> bool:
        if name == FAVORITE_TAG:
            QMessageBox.information(
                self, "标签管理", "「收藏」是内置标签，不能重命名、合并或删除。"
            )
            return False
        return True

    def _apply(self) -> None:
        name = self._current_name()
        if not name:
            return
        self.selected_value = name
        self.accept()

    def _rename(self) -> None:
        name = self._current_name()
        if not name or not self._ensure_editable(name):
            return
        new_name, ok = QInputDialog.getText(
            self, "重命名标签", "新名称：", text=name
        )
        new_name = (new_name or "").strip()
        if not ok or not new_name or new_name == name:
            return
        count = self.library.rename_tag(name, new_name)
        if new_name in self._names():
            message = f"已合并到「{new_name}」，涉及 {count} 本书。"
        else:
            message = f"已重命名为「{new_name}」，涉及 {count} 本书。"
        self._refresh(select=new_name)
        QMessageBox.information(self, "标签管理", message)

    def _merge(self) -> None:
        name = self._current_name()
        if not name or not self._ensure_editable(name):
            return
        others = [item for item in self._names() if item != name]
        if not others:
            QMessageBox.information(self, "合并标签", "请先选择来源标签，并确保还有另一个标签。")
            return
        target, ok = QInputDialog.getItem(
            self, "合并标签", f"把「{name}」合并到：", others, 0, False
        )
        if not ok or not target:
            return
        count = self.library.rename_tag(name, target)
        self._refresh(select=target)
        QMessageBox.information(self, "合并标签", f"已合并，涉及 {count} 本书。")

    def _delete(self) -> None:
        name = self._current_name()
        if not name or not self._ensure_editable(name):
            return
        answer = QMessageBox.question(
            self,
            "删除标签",
            f"将删除标签「{name}」及其书籍关联（书籍本身不会删除），是否继续？",
        )
        if answer != QMessageBox.Yes:
            return
        count = self.library.delete_tag(name)
        self._refresh()
        QMessageBox.information(self, "标签管理", f"已删除标签，涉及 {count} 本书。")


__all__ = ["TagManagerDialog"]

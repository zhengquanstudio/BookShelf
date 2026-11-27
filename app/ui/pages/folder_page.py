"""M7 文件夹树视图：按实际存放目录聚合，选中后联动筛选书库。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...services.library_service import LibraryService


def build_folder_tree(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """把「目录 → 数量」条目折叠成层级树，total 包含所有子目录。"""
    roots: dict[str, dict[str, Any]] = {}

    for entry in entries:
        path_text = str(entry.get("path") or "")
        if not path_text:
            continue
        parts = Path(path_text).parts
        level = roots
        current = ""
        node: dict[str, Any] | None = None
        for part in parts:
            current = part if not current else str(Path(current) / part)
            node = level.setdefault(
                part,
                {"name": part, "path": current, "count": 0, "children": {}},
            )
            level = node["children"]
        if node is not None:
            node["count"] += int(entry.get("count") or 0)

    def to_list(nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for node in nodes.values():
            children = to_list(node["children"])
            result.append(
                {
                    "name": node["name"],
                    "path": node["path"],
                    "count": node["count"],
                    "total": node["count"] + sum(child["total"] for child in children),
                    "children": children,
                }
            )
        result.sort(key=lambda item: item["name"].lower())
        return result

    return to_list(roots)


class FolderPage(QWidget):
    """只读目录树；选中文件夹后由主窗口切回书库并应用筛选。"""

    back_requested = Signal()
    folder_selected = Signal(str)

    def __init__(self, library: LibraryService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FolderPage")
        self.library = library
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        for text, handler in (
            ("返回书库", lambda: self.back_requested.emit()),
            ("刷新", self.refresh),
            ("筛选所选文件夹", self._apply_current),
            ("展开全部", lambda: self.tree.expandAll()),
            ("收起全部", lambda: self.tree.collapseAll()),
        ):
            button = QPushButton(text)
            button.setObjectName("GhostButton")
            button.clicked.connect(handler)
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("搜索目录…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setFixedWidth(240)
        self.search_box.textChanged.connect(self._filter_items)
        toolbar.addWidget(self.search_box)
        layout.addLayout(toolbar)

        hint = QLabel(
            "目录按书籍的实际存放位置聚合：已归档的书显示归档目录，其余显示原始目录。"
            "选中父目录会包含其下所有子目录中的书籍。"
        )
        hint.setObjectName("DetailSub")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.tree = QTreeWidget()
        self.tree.setObjectName("FolderTree")
        self.tree.setHeaderLabels(["目录", "书籍"])
        self.tree.setColumnWidth(0, 620)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.tree.itemDoubleClicked.connect(lambda _item, _column: self._apply_current())
        layout.addWidget(self.tree, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("DetailSub")
        layout.addWidget(self.status_label)

    def refresh(self, *_args) -> None:
        entries = self.library.folders()
        self.tree.clear()
        nodes = build_folder_tree(entries)
        for node in nodes:
            self._add_node(None, node)
        self.tree.expandToDepth(1)
        book_total = sum(int(entry.get("count") or 0) for entry in entries)
        self.status_label.setText(
            f"共 {len(entries)} 个目录，{book_total} 本书。双击目录可直接筛选。"
        )
        self._filter_items(self.search_box.text())

    def _add_node(self, parent: QTreeWidgetItem | None, node: dict[str, Any]) -> None:
        item = QTreeWidgetItem([node["name"], f"{node['total']} 本"])
        item.setData(0, Qt.UserRole, node["path"])
        item.setToolTip(0, node["path"])
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        for child in node["children"]:
            self._add_node(item, child)

    def _filter_items(self, text: str) -> None:
        keyword = text.strip().lower()

        def visit(item: QTreeWidgetItem) -> bool:
            child_visible = False
            for index in range(item.childCount()):
                if visit(item.child(index)):
                    child_visible = True
            visible = bool(keyword) and keyword in item.text(0).lower() or child_visible
            if not keyword:
                visible = True
            item.setHidden(not visible)
            if keyword and visible:
                item.setExpanded(True)
            return visible

        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))

    def _apply_current(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        path = str(item.data(0, Qt.UserRole) or "")
        if path:
            self.folder_selected.emit(path)


__all__ = ["FolderPage", "build_folder_tree"]

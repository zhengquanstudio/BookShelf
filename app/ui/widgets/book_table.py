"""书籍列表模型（图 01 中间表格，9 列虚拟滚动）。"""

from __future__ import annotations

from typing import Any, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

HEADERS = [
    ("", 28, "check"),
    ("书名", 210, "title"),
    ("作者", 130, "author"),
    ("国家", 62, "country"),
    ("格式", 70, "format"),
    ("卷号", 56, "volume"),
    ("ISBN", 112, "isbn"),
    ("识别状态", 88, "status"),
    ("整理状态", 88, "organize_status"),
]

_FORMAT_COLORS = {
    "epub": "#4f8cf7",
    "pdf": "#e0645d",
    "mobi": "#e8b04b",
    "azw3": "#a78bfa",
}
_STATUS_TEXT = {
    "pending": "待整理",
    "ok": "已识别",
    "partial": "待补全",
    "failed": "识别失败",
    "drm": "受保护",
    "archived": "已归档",
    "skipped": "跳过",
}


class BookTableModel(QAbstractTableModel):
    """把仓储返回的行数据映射为表格；不持有 UI 控件。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._checked: set[int] = set()

    def set_rows(self, rows: Sequence[Any]) -> None:
        self.beginResetModel()
        self._rows = [self._to_dict(row) for row in rows]
        visible_ids = {int(row["id"]) for row in self._rows if row.get("id") is not None}
        self._checked.intersection_update(visible_ids)
        self.endResetModel()

    def append_rows(self, rows: Sequence[Any]) -> None:
        """追加下一页数据，保留当前选择和勾选状态。"""
        new_rows = [self._to_dict(row) for row in rows]
        if not new_rows:
            return
        first = len(self._rows)
        self.beginInsertRows(QModelIndex(), first, first + len(new_rows) - 1)
        self._rows.extend(new_rows)
        self.endInsertRows()

    def checked_ids(self) -> list[int]:
        return sorted(self._checked)

    def flags(self, index: QModelIndex):
        flags = super().flags(index)
        if index.isValid() and index.column() == 0:
            flags |= Qt.ItemIsUserCheckable
        return flags

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.EditRole):  # noqa: N802
        if not index.isValid() or index.column() != 0 or role != Qt.CheckStateRole:
            return False
        book_id = self.book_id(index.row())
        if book_id is None:
            return False
        if Qt.CheckState(value) == Qt.Checked:
            self._checked.add(int(book_id))
        else:
            self._checked.discard(int(book_id))
        self.dataChanged.emit(index, index, [Qt.CheckStateRole])
        return True

    @staticmethod
    def _to_dict(row: Any) -> dict[str, Any]:
        if isinstance(row, dict):
            return row
        return {key: row[key] for key in row.keys()}

    def book_id(self, row: int) -> int | None:
        if 0 <= row < len(self._rows):
            return self._rows[row].get("id")
        return None

    def row_data(self, row: int) -> dict[str, Any] | None:
        """返回整行数据，供详情面板使用。"""
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section: int, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(HEADERS):
            return HEADERS[section][0]
        return section + 1

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        key = HEADERS[index.column()][2]
        if role == Qt.CheckStateRole and key == "check":
            book_id = row.get("id")
            return Qt.Checked if book_id in self._checked else Qt.Unchecked
        if role == Qt.DisplayRole:
            return self._display(row, key)
        if role == Qt.ForegroundRole and key == "format":
            return QColor(_FORMAT_COLORS.get(str(row.get("format") or ""), "#a3a9b4"))
        if role == Qt.TextAlignmentRole and key in {"volume", "check"}:
            return int(Qt.AlignCenter)
        if role == Qt.ToolTipRole:
            return str(row.get("file_path") or "")
        return None

    @staticmethod
    def _display(row: dict[str, Any], key: str) -> str:
        if key == "check":
            return ""
        if key == "author":
            return str(row.get("author_name") or row.get("author_raw") or "")
        if key == "country":
            return str(row.get("country") or "")
        if key == "format":
            return str(row.get("format") or "").upper()
        if key == "volume":
            volume = row.get("volume")
            return f"第{volume}卷" if volume else ""
        if key == "status":
            return _STATUS_TEXT.get(str(row.get("status") or ""), str(row.get("status") or ""))
        if key == "organize_status":
            return "已整理" if row.get("status") == "archived" else "未整理"
        value = row.get(key)
        return "" if value is None else str(value)

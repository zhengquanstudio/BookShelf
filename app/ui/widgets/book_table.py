"""书籍列表模型（书库中间表格，8 列 + 服务端排序 + 行内缩略图/进度）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate

from ..theme import chrome_tokens, is_light_theme

HEADERS = [
    ("", 34, "check"),
    ("书名 / 作者", 380, "title"),
    ("格式", 74, "format"),
    ("ISBN", 132, "isbn"),
    ("进度", 104, "progress"),
    ("大小", 96, "size"),
    ("添加时间", 112, "added"),
    ("状态", 96, "status"),
]

# 表头可点排序列 → 仓储层排序键（状态列原型不可排序）。
_SORTABLE_COLS = {
    1: "title",
    2: "format",
    3: "isbn",
    4: "progress",
    5: "file_size",
    6: "added_at",
}

_FORMAT_COLORS = {
    "epub": "#4f8cf7",
    "pdf": "#e0645d",
    "mobi": "#e8b04b",
    "azw3": "#a78bfa",
}
_FORMAT_BADGE = {
    "epub": "epub",
    "pdf": "pdf",
    "mobi": "warn",
    "azw3": "ok",
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
_STATUS_BADGE = {
    "pending": "wait",
    "partial": "wait",
    "ok": "ok",
    "archived": "ok",
    "failed": "fail",
    "drm": "fail",
    "skipped": "faint",
}


# ---- 显示格式化 -------------------------------------------------------
def _human_size(size: Any) -> str:
    try:
        n = float(size)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    for label, factor in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if n >= factor:
            value = n / factor
            return f"{value:.1f} {label}" if value < 100 else f"{value:.0f} {label}"
    return f"{int(n)} B"


def _format_added(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:16]
    return dt.astimezone().strftime("%m-%d %H:%M")


def _progress_label(percent: Any) -> tuple[str, int]:
    """返回 (显示文案, 0-100 的百分比整数)。"""
    try:
        pct = float(percent)
    except (TypeError, ValueError):
        return "未读", 0
    if pct <= 0:
        return "未读", 0
    if pct >= 100:
        return "已读完", 100
    return f"{int(round(pct))}%", int(round(pct))


def _subtitle(row: dict[str, Any]) -> str:
    parts = [
        str(row.get("author_name") or row.get("author_raw") or "").strip(),
        str(row.get("publisher") or "").strip(),
        str(row.get("publish_date") or "").strip()[:4],
    ]
    return " · ".join(p for p in parts if p)


def _palette(theme: str, accent: str = "blue") -> dict[str, QColor]:
    """内联绘制用的主题色板（QSS 字符串替换覆盖不到 Python 内的颜色）。"""
    tokens = chrome_tokens(theme, accent)
    dark = not is_light_theme(theme)
    if dark:
        accent_bg = QColor(tokens["accent"])
        accent_bg.setAlpha(40)
    else:
        accent_bg = QColor(tokens["accent_soft"])
    return {
        "text": QColor(tokens["ink"]),
        "muted": QColor(tokens["muted"]),
        "faint": QColor(tokens["faint"]),
        "accent": QColor(tokens["accent"]),
        "panel2": QColor(tokens["panel2"]),
        "line": QColor(tokens["line"]),
        "epub_bg": accent_bg,
        "epub_fg": QColor(tokens["accent_ink"]),
        "pdf_bg": QColor(224, 100, 93, 40) if dark else QColor("#fbeae8"),
        "pdf_fg": QColor("#e8a49e") if dark else QColor("#b83c33"),
        "ok_bg": QColor(80, 180, 120, 40) if dark else QColor("#e3f1e3"),
        "ok_fg": QColor("#7cc98e") if dark else QColor("#2f7d32"),
        "warn_bg": QColor(232, 176, 75, 40) if dark else QColor("#fbf0e0"),
        "warn_fg": QColor("#e8c074") if dark else QColor("#a86d1f"),
        "fail_bg": QColor(224, 100, 93, 46) if dark else QColor("#fbe6e4"),
        "fail_fg": QColor("#e8a49e") if dark else QColor("#b83c33"),
        "faint_bg": QColor(255, 255, 255, 18) if dark else QColor("#eef1f5"),
        "faint_fg": QColor(tokens["faint"]),
    }


class BookTableModel(QAbstractTableModel):
    """把仓储返回的行数据映射为表格；排序交给服务端，模型不持有 UI 控件。"""

    sort_changed = Signal(str, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._checked: set[int] = set()
        self._theme = "dark"
        self._accent = "blue"

    def set_theme(self, theme: str, accent: str = "blue") -> None:
        self._theme = str(theme or "dark")
        self._accent = str(accent or "blue")

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

    def clear_checked(self) -> None:
        """清空所有勾选，并通知视图刷新复选框列。"""
        self._checked.clear()
        if self._rows:
            top_left = self.index(0, 0)
            bottom_right = self.index(len(self._rows) - 1, 0)
            self.dataChanged.emit(top_left, bottom_right, [Qt.CheckStateRole])

    def sort(self, column: int, order: Qt.SortOrder = Qt.DescendingOrder) -> None:  # noqa: N802
        """表头点击触发：不在内存里重排（分页只加载了一部分），通知主窗重读。"""
        key = _SORTABLE_COLS.get(column)
        if key is None:
            return
        self.sort_changed.emit(key, order == Qt.DescendingOrder)

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
        """返回整行数据，供详情面板与委托绘制使用。"""
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
        if role == Qt.ForegroundRole:
            if key in {"isbn", "size", "added"}:
                return _palette(self._theme)["muted"]
            if key == "format":
                return QColor(_FORMAT_COLORS.get(str(row.get("format") or ""), "#a3a9b4"))
            return None
        if role == Qt.TextAlignmentRole:
            if key == "check":
                return int(Qt.AlignCenter)
            if key in {"isbn", "size", "added", "progress"}:
                return int(Qt.AlignVCenter | Qt.AlignRight)
            return int(Qt.AlignVCenter | Qt.AlignLeft)
        if role == Qt.ToolTipRole:
            if key == "isbn":
                return str(row.get("isbn") or "")
            return str(row.get("file_path") or "")
        return None

    @staticmethod
    def _display(row: dict[str, Any], key: str) -> str:
        if key == "check":
            return ""
        if key == "title":
            return str(row.get("title") or "")
        if key == "format":
            return str(row.get("format") or "").upper()
        if key == "isbn":
            value = str(row.get("isbn") or "").strip()
            return value if value else "—"
        if key == "progress":
            return _progress_label(row.get("progress"))[0]
        if key == "size":
            return _human_size(row.get("file_size"))
        if key == "added":
            return _format_added(row.get("added_at"))
        if key == "status":
            return _STATUS_TEXT.get(str(row.get("status") or ""), str(row.get("status") or ""))
        value = row.get(key)
        return "" if value is None else str(value)


class BookCellDelegate(QStyledItemDelegate):
    """渲染书名缩略图、进度条与格式/状态胶囊；其余列走默认绘制。"""

    THUMB_W, THUMB_H = 28, 38
    BAR_W, BAR_H = 78, 5

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._theme = "dark"
        self._accent = "blue"
        self._cover_cache: dict[str, QPixmap | None] = {}

    def set_theme(self, theme: str, accent: str = "blue") -> None:
        self._theme = str(theme or "dark")
        self._accent = str(accent or "blue")

    def sizeHint(self, option, index):  # noqa: N802
        hint = super().sizeHint(option, index)
        return QSize(hint.width(), 56)

    # ---- 封面缓存（仅缓存可见行，避免大图反复解码） ----------------
    def _cover(self, path: str) -> QPixmap | None:
        if not path:
            return None
        if path in self._cover_cache:
            return self._cover_cache[path]
        pixmap = QPixmap(path)
        value = None if pixmap.isNull() else pixmap
        if len(self._cover_cache) > 256:
            self._cover_cache.pop(next(iter(self._cover_cache)))
        self._cover_cache[path] = value
        return value

    # ---- 绘制入口 ---------------------------------------------------
    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:  # noqa: N802
        key = HEADERS[index.column()][2]
        pal = _palette(self._theme, self._accent)
        if key == "title":
            self._paint_title(painter, option, index, pal)
        elif key == "progress":
            self._paint_progress(painter, option, index, pal)
        elif key == "format":
            self._paint_format_badge(painter, option, index, pal)
        elif key == "status":
            self._paint_status_badge(painter, option, index, pal)
        else:
            super().paint(painter, option, index)

    @staticmethod
    def _draw_panel(painter: QPainter, option) -> None:
        widget = option.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawPrimitive(QStyle.PE_PanelItemViewItem, option, painter, widget)

    def _row(self, index: QModelIndex) -> dict[str, Any]:
        model = index.model()
        data = model.row_data(index.row()) if hasattr(model, "row_data") else None
        return data or {}

    def _paint_title(self, painter, option, index, pal):
        self._draw_panel(painter, option)
        row = self._row(index)
        rect = option.rect
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        thumb_x = rect.left() + 8
        thumb_y = rect.top() + (rect.height() - self.THUMB_H) // 2
        thumb_rect = QRect(thumb_x, thumb_y, self.THUMB_W, self.THUMB_H)
        cover = self._cover(str(row.get("cover_path") or ""))
        clip = QPainterPath()
        clip.addRoundedRect(thumb_rect, 3, 3)
        painter.setClipPath(clip)
        if cover is not None:
            scaled = cover.scaled(
                self.THUMB_W, self.THUMB_H,
                Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation,
            )
            painter.drawPixmap(thumb_rect, scaled)
        else:
            painter.fillRect(thumb_rect, pal["panel2"])
            painter.setPen(QPen(pal["line"], 1))
            painter.drawRoundedRect(thumb_rect.adjusted(0, 0, -1, -1), 3, 3)
            glyph = str(row.get("title") or "").strip()[:2]
            if glyph:
                serif = QFont("Georgia", 10)
                serif.setBold(True)
                painter.setFont(serif)
                painter.setPen(pal["muted"])
                painter.drawText(thumb_rect, Qt.AlignCenter, glyph)
        painter.setClipping(False)

        title = str(row.get("title") or "")
        subtitle = _subtitle(row)
        title_font = QFont(option.font)
        title_font.setBold(True)
        title_fm = QFontMetrics(title_font)
        sub_font = QFont(option.font)
        if sub_font.pointSize() > 0:
            sub_font.setPointSize(sub_font.pointSize() - 1)
        elif sub_font.pixelSize() > 0:
            sub_font.setPixelSize(max(8, sub_font.pixelSize() - 2))
        sub_fm = QFontMetrics(sub_font)
        title_h = title_fm.height()
        sub_h = sub_fm.height() if subtitle else 0
        gap = 4 if subtitle else 0
        block_h = title_h + gap + sub_h
        block_top = rect.top() + max(0, (rect.height() - block_h) // 2)
        text_x = thumb_rect.right() + 10
        text_w = max(0, rect.right() - text_x - 8)

        painter.setFont(title_font)
        painter.setPen(pal["text"])
        painter.drawText(
            QRect(text_x, block_top, text_w, title_h),
            Qt.AlignVCenter | Qt.AlignLeft,
            title_fm.elidedText(title, Qt.ElideRight, text_w),
        )
        if subtitle:
            painter.setFont(sub_font)
            painter.setPen(pal["muted"])
            painter.drawText(
                QRect(text_x, block_top + title_h + gap, text_w, sub_h),
                Qt.AlignVCenter | Qt.AlignLeft,
                sub_fm.elidedText(subtitle, Qt.ElideRight, text_w),
            )
        painter.restore()

    def _paint_progress(self, painter, option, index, pal):
        self._draw_panel(painter, option)
        row = self._row(index)
        label, pct = _progress_label(row.get("progress"))
        rect = option.rect
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        label_w = option.fontMetrics.horizontalAdvance(label)
        total = self.BAR_W + 6 + label_w
        bar_x = rect.right() - 8 - total
        bar_rect = QRect(
            bar_x, rect.center().y() - self.BAR_H // 2, self.BAR_W, self.BAR_H
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(pal["line"])
        painter.drawRoundedRect(bar_rect, self.BAR_H / 2, self.BAR_H / 2)
        fill_w = max(0, min(self.BAR_W, int(self.BAR_W * pct / 100)))
        if fill_w > 0:
            painter.setBrush(pal["accent"])
            painter.drawRoundedRect(
                QRect(bar_rect.x(), bar_rect.y(), fill_w, self.BAR_H),
                self.BAR_H / 2, self.BAR_H / 2,
            )
        text_x = bar_rect.right() + 6
        painter.setPen(pal["muted"])
        painter.setFont(option.font)
        painter.drawText(
            QRect(text_x, rect.top(), rect.right() - text_x - 4, rect.height()),
            Qt.AlignVCenter | Qt.AlignLeft, label,
        )
        painter.restore()

    def _paint_format_badge(self, painter, option, index, pal):
        row = self._row(index)
        fmt = str(row.get("format") or "").lower()
        kind = _FORMAT_BADGE.get(fmt, "faint")
        self._draw_badge(painter, option, pal, kind, str(row.get("format") or "").upper())

    def _paint_status_badge(self, painter, option, index, pal):
        row = self._row(index)
        status = str(row.get("status") or "")
        kind = _STATUS_BADGE.get(status, "faint")
        self._draw_badge(painter, option, pal, kind, _STATUS_TEXT.get(status, status))

    def _draw_badge(self, painter, option, pal, kind: str, text: str):
        self._draw_panel(painter, option)
        if not text:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        bg = pal.get(f"{kind}_bg", pal["faint_bg"])
        fg = pal.get(f"{kind}_fg", pal["faint_fg"])
        fm = option.fontMetrics
        pad_x, pad_y = 6, 1
        text_w = fm.horizontalAdvance(text)
        badge_w = text_w + pad_x * 2
        badge_h = max(fm.height() + pad_y * 2 - 2, 16)
        rect = option.rect
        x = rect.left() + (rect.width() - badge_w) // 2
        y = rect.top() + (rect.height() - badge_h) // 2
        badge_rect = QRect(x, y, badge_w, badge_h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(badge_rect, 5, 5)
        font = QFont(option.font)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(fg)
        painter.drawText(badge_rect, Qt.AlignCenter, text)
        painter.restore()

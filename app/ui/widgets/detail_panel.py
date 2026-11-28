"""右侧详情面板（书库 v4 原型）：封面、元数据、路径、简介与操作。"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
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
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import chrome_tokens, is_light_theme

_STATUS_TEXT = {
    "pending": "待整理",
    "ok": "已识别",
    "partial": "待补全",
    "failed": "识别失败",
    "drm": "受 DRM 保护",
    "archived": "已归档",
    "skipped": "已跳过",
}
_FORMAT_BADGE = {"epub": "epub", "pdf": "pdf", "mobi": "warn", "azw3": "ok"}
_STATUS_BADGE = {
    "pending": "wait", "partial": "wait", "ok": "ok", "archived": "ok",
    "failed": "fail", "drm": "fail", "skipped": "faint",
}

_COVER_W, _COVER_H = 76, 106
_KV_LABELS = ["出版社", "出版日期", "语言", "页数", "ISBN", "文件大小", "系列", "阅读进度"]


def _is_light(theme: str) -> bool:
    return is_light_theme(theme)


def _rgba(color: QColor) -> str:
    return f"rgba({color.red()},{color.green()},{color.blue()},{color.alpha() / 255:.2f})"


def _chip_palette(theme: str, accent: str = "blue") -> dict[str, tuple[QColor, QColor]]:
    tokens = chrome_tokens(theme, accent)
    dark = not is_light_theme(theme)
    if dark:
        accent_bg = QColor(tokens["accent"])
        accent_bg.setAlpha(40)
    else:
        accent_bg = QColor(tokens["accent_soft"])
    accent_fg = QColor(tokens["accent_ink"])
    if not dark:
        return {
            "epub": (accent_bg, accent_fg),
            "pdf": (QColor("#fbeae8"), QColor("#b83c33")),
            "ok": (QColor("#e3f1e3"), QColor("#2f7d32")),
            "warn": (QColor("#fbf0e0"), QColor("#a86d1f")),
            "fail": (QColor("#fbe6e4"), QColor("#b83c33")),
            "faint": (QColor("#eef1f5"), QColor(tokens["faint"])),
            "tag": (accent_bg, accent_fg),
        }
    return {
        "epub": (accent_bg, accent_fg),
        "pdf": (QColor(224, 100, 93, 40), QColor("#e8a49e")),
        "ok": (QColor(80, 180, 120, 40), QColor("#7cc98e")),
        "warn": (QColor(232, 176, 75, 40), QColor("#e8c074")),
        "fail": (QColor(224, 100, 93, 46), QColor("#e8a49e")),
        "faint": (QColor(255, 255, 255, 18), QColor(tokens["faint"])),
        "tag": (accent_bg, accent_fg),
    }


def _cover_palette(theme: str) -> tuple[QColor, QColor, QColor, QColor]:
    if _is_light(theme):
        return QColor("#f4e7d3"), QColor("#dbc9ae"), QColor("#d8c7a8"), QColor("#7a6a55")
    return QColor("#3a352c"), QColor("#26221c"), QColor("#4a4236"), QColor("#c8b896")


def _progress_text(percent: Any) -> str:
    try:
        pct = float(percent)
    except (TypeError, ValueError):
        return "未读"
    if pct <= 0:
        return "未读"
    if pct >= 100:
        return "已读完"
    return f"{int(round(pct))}%"


class DetailPanel(QWidget):
    """展示当前选中书籍；不包含数据库或文件扫描操作。"""

    edit_requested = Signal()
    research_requested = Signal()
    open_folder_requested = Signal()
    favorite_requested = Signal()
    read_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DetailPanel")
        self.setFixedWidth(384)
        self._theme = "dark"
        self._accent = "blue"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("DetailScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._build_top(layout)
        self._build_meta(layout)
        self._build_paths(layout)
        self._build_intro(layout)
        self._build_actions(layout)
        layout.addStretch(1)

        self._intro_full = ""
        self._intro_expanded = False
        self._source_path = "—"
        self._target_path = ""
        self.clear()

    # ---- 构建 -------------------------------------------------------
    def _build_top(self, layout: QVBoxLayout) -> None:
        top = QFrame()
        top.setObjectName("DetailTop")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(16, 16, 16, 12)
        top_layout.setSpacing(12)

        self._cover = QLabel()
        self._cover.setObjectName("CoverBox")
        self._cover.setFixedSize(_COVER_W, _COVER_H)
        self._cover.setAlignment(Qt.AlignCenter)
        top_layout.addWidget(self._cover)

        meta = QVBoxLayout()
        meta.setSpacing(4)
        self._title = QLabel("未选择书籍")
        self._title.setObjectName("DetailTitle")
        self._title.setWordWrap(True)
        self._author = QLabel("从中间列表选择一本书查看详情")
        self._author.setObjectName("DetailSub")
        self._author.setWordWrap(True)
        meta.addWidget(self._title)
        meta.addWidget(self._author)
        meta.addStretch(1)

        chips = QHBoxLayout()
        chips.setSpacing(5)
        self._chip_format = QLabel()
        self._chip_format.setObjectName("ChipFormat")
        self._chip_status = QLabel()
        self._chip_status.setObjectName("ChipStatus")
        self._chip_tag = QLabel()
        self._chip_tag.setObjectName("ChipTag")
        for chip in (self._chip_format, self._chip_status, self._chip_tag):
            chip.setAlignment(Qt.AlignCenter)
            chip.setFixedHeight(20)
            chips.addWidget(chip)
        chips.addStretch(1)
        meta.addLayout(chips)
        top_layout.addLayout(meta, 1)
        layout.addWidget(top)

    def _build_meta(self, layout: QVBoxLayout) -> None:
        section = self._section("元数据", layout)
        grid = QGridLayout()
        grid.setContentsMargins(16, 0, 16, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        self._kv_values: dict[str, QLabel] = {}
        for row, key in enumerate(_KV_LABELS):
            label = QLabel(key)
            label.setObjectName("KvLabel")
            label.setFixedWidth(76)
            value = QLabel("—")
            value.setObjectName("KvValue")
            value.setWordWrap(True)
            grid.addWidget(label, row, 0, Qt.AlignTop)
            grid.addWidget(value, row, 1)
            self._kv_values[key] = value
        section.layout().addLayout(grid)

    def _build_paths(self, layout: QVBoxLayout) -> None:
        section = self._section("文件路径", layout)
        box = QFrame()
        box.setObjectName("PathBox")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(10, 8, 10, 8)
        box_layout.setSpacing(4)

        self._source_row = self._path_row("数据文件")
        self._target_row = self._path_row("归档路径")
        box_layout.addLayout(self._source_row)
        box_layout.addLayout(self._target_row)
        wrap = QHBoxLayout()
        wrap.setContentsMargins(16, 0, 16, 12)
        wrap.addWidget(box)
        section.layout().addLayout(wrap)

    def _path_row(self, caption: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        cap = QLabel(caption)
        cap.setObjectName("PathCaption")
        cap.setFixedWidth(56)
        value = QLabel("—")
        value.setObjectName("PathValue")
        value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(cap)
        row.addWidget(value, 1)
        return row

    def _build_intro(self, layout: QVBoxLayout) -> None:
        section = self._section("简介", layout)
        self._intro = QLabel("暂无简介")
        self._intro.setObjectName("DetailIntro")
        self._intro.setWordWrap(True)
        self._intro.setAlignment(Qt.AlignTop)
        wrap = QVBoxLayout()
        wrap.setContentsMargins(16, 0, 16, 12)
        wrap.setSpacing(4)
        wrap.addWidget(self._intro)
        self._intro_toggle = QPushButton("展开")
        self._intro_toggle.setObjectName("LinkButton")
        self._intro_toggle.setCursor(Qt.PointingHandCursor)
        self._intro_toggle.clicked.connect(self._toggle_intro)
        self._intro_toggle.setVisible(False)
        wrap.addWidget(self._intro_toggle, 0, Qt.AlignLeft)
        section.layout().addLayout(wrap)

    def _build_actions(self, layout: QVBoxLayout) -> None:
        actions = QFrame()
        actions.setObjectName("DetailActions")
        grid = QGridLayout(actions)
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        self._primary = QPushButton("在新窗口阅读")
        self._primary.setObjectName("PrimaryButton")
        self._primary.setFixedHeight(34)
        self._primary.clicked.connect(self.read_requested)
        grid.addWidget(self._primary, 0, 0, 1, 2)

        self._edit_button = QPushButton("编辑元数据")
        self._edit_button.setObjectName("GhostButton")
        self._edit_button.clicked.connect(self.edit_requested)
        self._research_button = QPushButton("重新检索")
        self._research_button.setObjectName("GhostButton")
        self._research_button.clicked.connect(self.research_requested)
        grid.addWidget(self._edit_button, 1, 0)
        grid.addWidget(self._research_button, 1, 1)

        self._folder_button = QPushButton("打开所在文件夹")
        self._folder_button.setObjectName("GhostButton")
        self._folder_button.clicked.connect(self.open_folder_requested)
        self._favorite_button = QPushButton("加入收藏")
        self._favorite_button.setObjectName("GhostButton")
        self._favorite_button.clicked.connect(self.favorite_requested)
        grid.addWidget(self._folder_button, 2, 0)
        grid.addWidget(self._favorite_button, 2, 1)
        layout.addWidget(actions)

    def _section(self, title: str, parent_layout: QVBoxLayout) -> QFrame:
        section = QFrame()
        section.setObjectName("DetailSection")
        v = QVBoxLayout(section)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QLabel(title)
        head.setObjectName("DetailSectionTitle")
        head_layout = QHBoxLayout()
        head_layout.setContentsMargins(16, 12, 16, 8)
        head_layout.addWidget(head)
        head_layout.addStretch(1)
        v.addLayout(head_layout)
        parent_layout.addWidget(section)
        return section

    # ---- 主题 -------------------------------------------------------
    def set_theme(self, theme: str, accent: str = "blue") -> None:
        self._theme = str(theme or "dark")
        self._accent = str(accent or "blue")
        # 当前若没有真实封面，重绘占位渐变。
        if not getattr(self, "_has_cover", False):
            self._cover.setPixmap(self._render_placeholder(self._current_title()))
        self._apply_chip_styles()
        self._refresh_path_style()

    def _current_title(self) -> str:
        return self._title.text() if self._title.text() != "未选择书籍" else ""

    # ---- 数据展示 ---------------------------------------------------
    def clear(self) -> None:
        self._has_cover = False
        self._cover.setPixmap(self._render_placeholder(""))
        self._title.setText("未选择书籍")
        self._author.setText("从中间列表选择一本书查看详情")
        self._chip_format.clear()
        self._chip_format.setVisible(False)
        self._chip_status.clear()
        self._chip_status.setVisible(False)
        self._chip_tag.clear()
        self._chip_tag.setVisible(False)
        for value in self._kv_values.values():
            value.setText("—")
        self._source_path = "—"
        self._target_path = ""
        self._refresh_path_text()
        self._refresh_path_style()
        self._intro_full = ""
        self._intro_expanded = False
        self._intro.setText("暂无简介")
        self._intro_toggle.setVisible(False)
        self._intro_toggle.setText("展开")

    def show_book(self, book: dict[str, Any], cover: QPixmap | None = None) -> None:
        title = str(book.get("title") or book.get("file_path") or "未命名")
        self._title.setText(title)
        authors = book.get("author_name") or book.get("author_raw") or ""
        publisher = str(book.get("publisher") or "").strip()
        year = str(book.get("publish_date") or "").strip()[:4]
        parts = [str(authors).strip()] if authors else []
        if publisher:
            parts.append(publisher)
        if year:
            parts.append(year)
        self._author.setText(" · ".join(parts) if parts else "作者未知")

        # 封面
        self._has_cover = cover is not None and not cover.isNull()
        if self._has_cover:
            self._cover.setPixmap(self._render_cover(cover))
        else:
            self._cover.setPixmap(self._render_placeholder(title))

        # 胶囊：格式 / 状态 / 首个标签
        fmt = str(book.get("format") or "").lower()
        self._set_chip(self._chip_format, _FORMAT_BADGE.get(fmt, "faint"),
                       str(book.get("format") or "").upper())
        status = str(book.get("status") or "")
        self._set_chip(self._chip_status, _STATUS_BADGE.get(status, "faint"),
                       _STATUS_TEXT.get(status, status or "未知"))
        tags = book.get("tags") or []
        if tags:
            self._set_chip(self._chip_tag, "tag", str(tags[0]))
        else:
            self._chip_tag.setVisible(False)

        # 元数据
        values = {
            "出版社": book.get("publisher"),
            "出版日期": book.get("publish_date"),
            "语言": book.get("language"),
            "页数": book.get("page_count"),
            "ISBN": book.get("isbn"),
            "文件大小": self._format_size(book.get("file_size")),
            "系列": book.get("series_name"),
            "阅读进度": _progress_text(book.get("progress")),
        }
        for key, value in values.items():
            text = value if value not in (None, "") else "—"
            self._kv_values[key].setText(str(text))

        # 路径
        self._source_path = str(book.get("file_path") or "—")
        self._target_path = str(book.get("target_path") or "")
        self._refresh_path_text()
        self._refresh_path_style()

        # 简介
        self._intro_full = str(book.get("description") or "").strip()
        self._intro_expanded = False
        self._intro_toggle.setText("展开")
        self._intro.setText(self._intro_full or "暂无简介")
        self._refresh_intro()

    # ---- 封面渲染 ---------------------------------------------------
    def _render_placeholder(self, title: str) -> QPixmap:
        grad_a, grad_b, border, text_color = _cover_palette(self._theme)
        pm = QPixmap(_COVER_W, _COVER_H)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        gradient = QLinearGradient(0, 0, _COVER_W, _COVER_H)
        gradient.setColorAt(0, grad_a)
        gradient.setColorAt(1, grad_b)
        painter.setBrush(gradient)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(pm.rect().adjusted(0, 0, -1, -1), 6, 6)
        text = str(title or "").strip()
        if text:
            font = QFont("Georgia", 10)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(text_color)
            painter.drawText(
                pm.rect().adjusted(8, 8, -8, -8),
                Qt.AlignCenter | Qt.TextWordWrap, text,
            )
        painter.end()
        return pm

    def _render_cover(self, cover: QPixmap) -> QPixmap:
        pm = QPixmap(_COVER_W, _COVER_H)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(pm.rect(), 6, 6)
        painter.setClipPath(clip)
        scaled = cover.scaled(
            _COVER_W, _COVER_H, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        painter.drawPixmap(pm.rect(), scaled)
        painter.end()
        return pm

    # ---- 胶囊 / 路径 / 简介 -----------------------------------------
    def _set_chip(self, label: QLabel, kind: str, text: str) -> None:
        if not text:
            label.setVisible(False)
            return
        label.setText(text)
        label.setProperty("kind", kind)
        label.setVisible(True)
        bg, fg = _chip_palette(self._theme, self._accent).get(
            kind, _chip_palette(self._theme, self._accent)["faint"]
        )
        label.setStyleSheet(
            f"background-color:{_rgba(bg)};color:{_rgba(fg)};"
            "border-radius:10px;padding:1px 8px;font-size:11px;font-weight:600;"
        )

    def _apply_chip_styles(self) -> None:
        # 主题切换时按当前文本重设胶囊配色（文本仍在，可见性不变）。
        if self._chip_format.isVisible():
            self._set_chip(self._chip_format, self._chip_format.property("kind") or "faint",
                           self._chip_format.text())
        if self._chip_status.isVisible():
            self._set_chip(self._chip_status, self._chip_status.property("kind") or "faint",
                           self._chip_status.text())
        if self._chip_tag.isVisible():
            self._set_chip(self._chip_tag, "tag", self._chip_tag.text())

    def _refresh_path_text(self) -> None:
        source_value = self._source_row.itemAt(1).widget()
        target_value = self._target_row.itemAt(1).widget()
        metrics = QFontMetrics(source_value.font())
        available = max(80, self.width() - 56 - 16 * 2 - 6 - 20)
        source_value.setText(metrics.elidedText(self._source_path, Qt.ElideMiddle, available))
        target_value.setText(metrics.elidedText(self._target_path or "尚未整理", Qt.ElideMiddle, available))

    def _refresh_path_style(self) -> None:
        target_value = self._target_row.itemAt(1).widget()
        palette = _chip_palette(self._theme, self._accent)
        if self._target_path:
            _, fg = palette["tag"]
            target_value.setStyleSheet(f"color:{_rgba(fg)};")
        else:
            muted = QColor("#5b6470") if _is_light(self._theme) else QColor("#a3a9b4")
            target_value.setStyleSheet(f"color:{_rgba(muted)};")

    def _toggle_intro(self) -> None:
        self._intro_expanded = not self._intro_expanded
        self._intro.setMaximumHeight(16777215 if self._intro_expanded else 66)
        self._intro_toggle.setText("收起" if self._intro_expanded else "展开")

    def _refresh_intro(self) -> None:
        collapsed = 66
        self._intro.setMaximumHeight(collapsed)
        if not self._intro_full:
            self._intro_toggle.setVisible(False)
            return
        width = self._intro.width()
        if width > 0:
            need = self._intro.heightForWidth(width) > collapsed + 2
        else:
            need = len(self._intro_full) > 60
        self._intro_toggle.setVisible(need)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh_path_text()
        self._refresh_intro()

    @staticmethod
    def _format_size(value: Any) -> str | None:
        if value in (None, ""):
            return None
        size = int(value)
        if size >= 1024 * 1024:
            return f"{size / 1024 / 1024:.1f} MB"
        return f"{size / 1024:.1f} KB"

"""R3a：阅读器内 404px 只读书籍详情浮层。

组件只负责展示；数据库与文件操作由 ReaderContainer 注入回调，R3b/R3c
的编辑、重新识别和 OPF 回写入口在此仅保留占位并禁用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
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

_READ_STATE_TEXT = {
    "unread": "未读",
    "reading": "在读",
    "finished": "已读",
}


def _format_size(value: Any) -> str:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return "—"
    if size < 0:
        return "—"
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    return f"{size / 1024:.1f} KB"


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else "—"


class BookDetailOverlay(QFrame):
    """404px 只读详情浮层；宿主控制显隐、锚点与所有动作。"""

    WIDTH = 404

    def __init__(
        self,
        parent: QWidget,
        *,
        on_close: Callable[[], None],
        on_reveal: Callable[[], None],
        on_rename: Callable[[], None],
        on_back: Callable[[], None] | None = None,
        on_note: Callable[[], None] | None = None,
        on_bookmark: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ReaderDetailOverlay")
        self.setFixedWidth(self.WIDTH)
        self.setMaximumHeight(600)
        self.hide()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(self._build_header())
        root.addWidget(self._build_body(), 1)
        root.addWidget(self._build_actions(on_back, on_note, on_bookmark))
        self.reveal_button.clicked.connect(on_reveal)
        self.rename_button.clicked.connect(on_rename)
        self.close_button.clicked.connect(on_close)
        self.description_toggle.clicked.connect(self._toggle_description)

    def _build_header(self) -> QHBoxLayout:
        head = QHBoxLayout()
        head.setContentsMargins(16, 16, 10, 10)
        head.setSpacing(14)
        self.d_cover = QLabel("封面")
        self.d_cover.setObjectName("ReaderDetailCover")
        self.d_cover.setFixedSize(96, 134)
        self.d_cover.setAlignment(Qt.AlignCenter)
        head.addWidget(self.d_cover, 0, Qt.AlignTop)

        right = QVBoxLayout()
        right.setSpacing(6)
        title_row = QHBoxLayout()
        title_row.setSpacing(4)
        self.d_title = QLabel("未命名")
        self.d_title.setObjectName("ReaderDetailTitle")
        self.d_title.setWordWrap(True)
        self.d_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title_row.addWidget(self.d_title, 1)
        self.close_button = QPushButton("✕")
        self.close_button.setObjectName("ReaderDetailClose")
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setFocusPolicy(Qt.NoFocus)
        self.close_button.setFixedSize(26, 26)
        title_row.addWidget(self.close_button, 0, Qt.AlignTop)
        right.addLayout(title_row)
        self.d_author = QLabel("作者未知")
        self.d_author.setObjectName("ReaderDetailAuthor")
        self.d_author.setWordWrap(True)
        right.addWidget(self.d_author)
        self.d_tags = QLabel("标签：—")
        self.d_tags.setObjectName("ReaderDetailTags")
        self.d_tags.setWordWrap(True)
        right.addWidget(self.d_tags)
        right.addStretch(1)
        head.addLayout(right, 1)
        return head

    def _build_body(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("ReaderDetailScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("ReaderDetailBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 4, 16, 12)
        layout.setSpacing(7)

        section = QLabel("元数据")
        section.setObjectName("ReaderDetailSection")
        layout.addWidget(section)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        fields = (
            ("d_language", "语言"),
            ("d_pages", "页数"),
            ("d_publish_date", "出版日期"),
            ("d_isbn", "ISBN"),
            ("d_meta", "格式"),
            ("d_series", "系列"),
            ("d_progress", "阅读进度"),
        )
        for row, (attribute, title) in enumerate(fields):
            key = QLabel(title)
            key.setObjectName("ReaderDetailKey")
            value = QLabel("—")
            value.setObjectName("ReaderDetailRow")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value.setWordWrap(True)
            grid.addWidget(key, row, 0, Qt.AlignTop)
            grid.addWidget(value, row, 1)
            setattr(self, attribute, value)
        layout.addLayout(grid)

        layout.addWidget(self._section("数据文件路径"))
        self.d_path = self._path_label()
        layout.addWidget(self.d_path)
        layout.addWidget(self._section("归档路径"))
        self.d_archive_state = QLabel("状态：—")
        self.d_archive_state.setObjectName("ReaderDetailArchiveState")
        layout.addWidget(self.d_archive_state)
        self.d_archive_path = self._path_label()
        layout.addWidget(self.d_archive_path)

        layout.addWidget(self._section("简介"))
        self.d_description = QLabel("—")
        self.d_description.setObjectName("ReaderDetailDescription")
        self.d_description.setWordWrap(True)
        self.d_description.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.d_description)
        self.description_toggle = QPushButton("展开")
        self.description_toggle.setObjectName("ReaderDetailDescriptionToggle")
        self.description_toggle.setCursor(Qt.PointingHandCursor)
        self.description_toggle.setFlat(True)
        layout.addWidget(self.description_toggle, 0, Qt.AlignLeft)
        scroll.setWidget(body)
        return scroll

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("ReaderDetailSection")
        return label

    @staticmethod
    def _path_label() -> QLabel:
        label = QLabel("—")
        label.setObjectName("ReaderDetailPath")
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        label.setMinimumWidth(0)
        return label

    def _build_actions(
        self,
        on_back: Callable[[], None] | None,
        on_note: Callable[[], None] | None,
        on_bookmark: Callable[[], None] | None,
    ) -> QFrame:
        panel = QFrame()
        panel.setObjectName("ReaderDetailActions")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(7)

        self.status_label = QLabel("")
        self.status_label.setObjectName("ReaderDetailStatus")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        layout.addWidget(self.status_label)

        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        self.reveal_button = self._action("📂 打开文件夹")
        self.rename_button = self._action("⟲ 按命名模板重算")
        path_row.addWidget(self.reveal_button, 1)
        path_row.addWidget(self.rename_button, 1)
        layout.addLayout(path_row)

        primary = QGridLayout()
        primary.setHorizontalSpacing(6)
        primary.setVerticalSpacing(6)
        self.back_button = self._action("← 返回书库")
        self.tag_button = self._action("◇ 添加标签", enabled=False)
        self.note_button = self._action("✎ 插入笔记", enabled=on_note is not None)
        self.bookmark_button = self._action("▮ 添加书签", enabled=on_bookmark is not None)
        self.highlight_button = self._action("▨ 标注此页", enabled=False)
        self.translate_button = self._action("⇄ 翻译（未开放）", enabled=False)
        self.translate_button.setObjectName("ReaderDetailGhost")
        for index, button in enumerate(
            (
                self.back_button,
                self.tag_button,
                self.note_button,
                self.bookmark_button,
                self.highlight_button,
                self.translate_button,
            )
        ):
            primary.addWidget(button, index // 3, index % 3)
        layout.addLayout(primary)
        if on_back is not None:
            self.back_button.clicked.connect(on_back)
        else:
            self.back_button.setEnabled(False)
        if on_note is not None:
            self.note_button.clicked.connect(on_note)
        if on_bookmark is not None:
            self.bookmark_button.clicked.connect(on_bookmark)

        secondary = QGridLayout()
        secondary.setHorizontalSpacing(6)
        self.edit_button = self._action("✎ 编辑元数据", enabled=False)
        self.research_button = self._action("⇩ 重新识别", enabled=False)
        self.restore_button = self._action("⟲ 恢复内嵌元数据", enabled=False)
        for button, tooltip in (
            (self.edit_button, "R3b 编辑模式尚未开放"),
            (self.research_button, "将在编辑元数据阶段开放"),
            (self.restore_button, "R3c 内嵌元数据回写尚未开放"),
        ):
            button.setToolTip(tooltip)
        for index, button in enumerate(
            (self.edit_button, self.research_button, self.restore_button)
        ):
            secondary.addWidget(button, 0, index)
        layout.addLayout(secondary)
        return panel

    @staticmethod
    def _action(text: str, *, enabled: bool = True) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("ReaderDetailAction")
        button.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        button.setEnabled(enabled)
        button.setMinimumHeight(30)
        return button

    def populate(
        self,
        book: dict[str, Any],
        *,
        tags: list[str] | None = None,
        progress: dict[str, Any] | None = None,
        archive_path: str = "",
        cover: QPixmap | None = None,
        current_page: int = 0,
        total_pages: int = 0,
    ) -> None:
        title = str(
            book.get("title") or Path(str(book.get("file_path") or "")).stem or "未命名"
        )
        self.d_title.setText(title)
        author = str(book.get("author_name") or book.get("author_raw") or "作者未知")
        year = str(book.get("publish_date") or "").strip()
        publisher = str(book.get("publisher") or "").strip()
        self.d_author.setText(" · ".join(part for part in (author, year, publisher) if part))

        state = _READ_STATE_TEXT.get(str(book.get("read_state") or "unread"), "未读")
        tag_list = [str(tag).strip() for tag in (tags or []) if str(tag).strip()]
        markers = tag_list + [state]
        if book.get("favorite"):
            markers.append("★ 喜爱")
        self.d_tags.setText("标签：" + ("、".join(markers) if markers else "—"))

        self.d_language.setText(_text(book.get("language")))
        pages = book.get("page_count")
        self.d_pages.setText(f"{pages} 页" if pages not in (None, "") else "—")
        self.d_publish_date.setText(_text(book.get("publish_date")))
        self.d_isbn.setText(_text(book.get("isbn")))
        drm = "有 DRM" if book.get("drm_protected") else "无 DRM"
        self.d_meta.setText(
            f"{str(book.get('format') or '—').upper()} · {drm} · "
            f"{_format_size(book.get('file_size'))}"
        )
        series = str(book.get("series_name") or "").strip() or "—"
        volume = book.get("volume")
        if series != "—" and volume not in (None, ""):
            series += f" · 第 {volume} 卷"
        self.d_series.setText(series)

        progress = progress or {}
        percent = max(0.0, min(1.0, float(progress.get("percent") or 0.0)))
        percent_text = f"{percent * 100:.0f}%"
        if current_page > 0 and total_pages > 0:
            self.d_progress.setText(f"{current_page} / {total_pages} · {percent_text} · {state}")
        else:
            self.d_progress.setText(f"{percent_text} · {state}")

        self._set_path(self.d_path, str(book.get("file_path") or "—"))
        archive = archive_path or "—"
        self._set_path(self.d_archive_path, archive)
        matched = archive != "—" and Path(archive) == Path(str(book.get("file_path") or ""))
        self.d_archive_state.setText("状态：已归档" if matched else "状态：待归档")
        self.d_archive_state.setProperty("state", "ok" if matched else "pending")
        self.d_archive_state.style().unpolish(self.d_archive_state)
        self.d_archive_state.style().polish(self.d_archive_state)

        description = str(book.get("description") or "").strip() or "—"
        self.d_description.setText(description)
        self.description_toggle.setVisible(description != "—")
        self.description_toggle.setText("展开")
        self.d_description.setMaximumHeight(self.d_description.fontMetrics().lineSpacing() * 4)
        self._render_cover(cover, title)
        self._elide_paths()

    def _render_cover(self, cover: QPixmap | None, title: str) -> None:
        if cover is None or cover.isNull():
            self.d_cover.setPixmap(QPixmap())
            self.d_cover.setText(title[:1] or "封")
            return
        scaled = cover.scaled(
            96, 134, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        self.d_cover.setText("")
        self.d_cover.setPixmap(
            scaled.copy(
                max(0, (scaled.width() - 96) // 2),
                max(0, (scaled.height() - 134) // 2),
                96,
                134,
            )
        )

    @staticmethod
    def _set_path(label: QLabel, path: str) -> None:
        label.setToolTip(path)
        label.setText(path)

    def _elide_paths(self) -> None:
        for label in (self.d_path, self.d_archive_path):
            path = label.toolTip() or "—"
            label.setText(
                label.fontMetrics().elidedText(
                    path, Qt.ElideMiddle, max(80, label.width() - 2)
                )
            )

    def _toggle_description(self) -> None:
        expanded = self.description_toggle.text() == "收起"
        self.description_toggle.setText("展开" if expanded else "收起")
        self.d_description.setMaximumHeight(
            self.d_description.fontMetrics().lineSpacing() * 4
            if expanded
            else 16777215
        )

    def show_status(self, message: str, *, error: bool = False) -> None:
        self.status_label.setText(message)
        self.status_label.setProperty("error", error)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_label.setVisible(bool(message))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide_paths()

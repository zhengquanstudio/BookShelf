"""右侧详情面板（图 01）：真实书籍元数据与封面。"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

_STATUS_TEXT = {
    "pending": "待整理",
    "ok": "已识别",
    "partial": "待补全",
    "failed": "识别失败",
    "drm": "受 DRM 保护",
    "archived": "已归档",
    "skipped": "已跳过",
}


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
        self.setFixedWidth(376)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._cover = QLabel("暂无\n封面")
        self._cover.setObjectName("CoverBox")
        self._cover.setAlignment(Qt.AlignCenter)
        self._cover.setFixedSize(104, 146)

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(self._cover)

        meta = QVBoxLayout()
        meta.setSpacing(4)
        self._title = QLabel("未选择书籍")
        self._title.setObjectName("DetailTitle")
        self._title.setWordWrap(True)
        self._author = QLabel("从中间列表选择一本书查看详情")
        self._author.setObjectName("DetailSub")
        self._author.setWordWrap(True)
        self._status = QLabel("—")
        self._status.setObjectName("StatusPill")
        self._status.setFixedHeight(22)
        meta.addWidget(self._title)
        meta.addWidget(self._author)
        meta.addWidget(self._status, alignment=Qt.AlignLeft)
        meta.addStretch(1)
        head.addLayout(meta, 1)
        layout.addLayout(head)

        self._kv = QFrame()
        self._kv.setObjectName("KvBox")
        kv_layout = QVBoxLayout(self._kv)
        kv_layout.setContentsMargins(12, 12, 12, 12)
        kv_layout.setSpacing(8)
        self._kv_rows: dict[str, QLabel] = {}
        for key in ("出版社", "出版日期", "语言", "页数", "文件大小", "ISBN"):
            row = QLabel(f"{key}：—")
            row.setObjectName("KvRow")
            row.setWordWrap(True)
            row.setMinimumHeight(22)
            row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            kv_layout.addWidget(row)
            self._kv_rows[key] = row
        # 元数据区按内容高度固定，避免被上下拉伸布局压扁导致文字被裁切
        self._kv.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._kv.setMinimumHeight(6 * 22 + 5 * 8 + 24)
        layout.addWidget(self._kv)

        path_title = QLabel("文件路径 / 归档路径")
        path_title.setObjectName("SectionTitle")
        layout.addWidget(path_title)
        self._path = QLabel("原：—\n新：—")
        self._path.setObjectName("PathBox")
        self._path.setWordWrap(False)
        self._path.setMinimumHeight(52)
        self._source_path = "—"
        self._target_path = "—"
        layout.addWidget(self._path)

        layout.addStretch(1)
        self._primary = QPushButton("在新窗口阅读（双击进入）")
        self._primary.setObjectName("PrimaryButton")
        self._primary.clicked.connect(self.read_requested)
        layout.addWidget(self._primary)
        row = QHBoxLayout()
        self._edit_button = QPushButton("编辑元数据")
        self._edit_button.setObjectName("GhostButton")
        self._edit_button.clicked.connect(self.edit_requested)
        self._research_button = QPushButton("重新检索")
        self._research_button.setObjectName("GhostButton")
        self._research_button.clicked.connect(self.research_requested)
        row.addWidget(self._edit_button)
        row.addWidget(self._research_button)
        layout.addLayout(row)
        row2 = QHBoxLayout()
        self._folder_button = QPushButton("打开所在文件夹")
        self._folder_button.setObjectName("GhostButton")
        self._folder_button.clicked.connect(self.open_folder_requested)
        self._favorite_button = QPushButton("加入收藏")
        self._favorite_button.setObjectName("GhostButton")
        self._favorite_button.clicked.connect(self.favorite_requested)
        row2.addWidget(self._folder_button)
        row2.addWidget(self._favorite_button)
        layout.addLayout(row2)

    def clear(self) -> None:
        """清空选择状态。"""
        self._cover.clear()
        self._cover.setText("暂无\n封面")
        self._title.setText("未选择书籍")
        self._author.setText("从中间列表选择一本书查看详情")
        self._status.setText("—")
        for key, label in self._kv_rows.items():
            label.setText(f"{key}：—")
        self._source_path = "—"
        self._target_path = "—"
        self._refresh_path_text()
        self._path.setToolTip("")

    def show_book(self, book: dict[str, Any], cover: QPixmap | None = None) -> None:
        """显示一本书记录；缺失字段统一以破折号表示。"""
        self._title.setText(str(book.get("title") or book.get("file_path") or "未命名"))
        authors = book.get("author_name") or book.get("author_raw") or "作者未知"
        country = book.get("country")
        self._author.setText(f"{authors}  [{country}]" if country else str(authors))
        status = str(book.get("status") or "")
        self._status.setText(_STATUS_TEXT.get(status, status or "未知"))

        if cover is not None and not cover.isNull():
            pixmap = cover.scaled(
                self._cover.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self._cover.setText("")
            self._cover.setPixmap(pixmap)
        else:
            self._cover.clear()
            self._cover.setText("暂无\n封面")

        values = {
            "出版社": book.get("publisher"),
            "出版日期": book.get("publish_date"),
            "语言": book.get("language"),
            "页数": book.get("page_count"),
            "文件大小": self._format_size(book.get("file_size")),
            "ISBN": book.get("isbn"),
        }
        for key, value in values.items():
            self._kv_rows[key].setText(f"{key}：{value if value not in (None, '') else '—'}")

        self._source_path = str(book.get("file_path") or "—")
        self._target_path = str(book.get("target_path") or "尚未整理")
        self._refresh_path_text()
        self._path.setToolTip(f"{self._source_path}\n{self._target_path}")

    def _refresh_path_text(self) -> None:
        metrics: QFontMetrics = self._path.fontMetrics()
        width = max(80, self._path.width() - metrics.horizontalAdvance("原：") - 8)
        source = metrics.elidedText(self._source_path, Qt.ElideMiddle, width)
        target = metrics.elidedText(self._target_path, Qt.ElideMiddle, width)
        self._path.setText(f"原：{source}\n新：{target}")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh_path_text()

    @staticmethod
    def _format_size(value: Any) -> str | None:
        if value in (None, ""):
            return None
        size = int(value)
        if size >= 1024 * 1024:
            return f"{size / 1024 / 1024:.1f} MB"
        return f"{size / 1024:.1f} KB"

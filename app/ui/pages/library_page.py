"""书库空态引导与不入库的静态示例预览。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class EmptyLibraryPage(QWidget):
    scan_requested = Signal()
    sample_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("EmptyLibraryPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 48, 40, 48)
        layout.setSpacing(16)
        layout.addStretch(1)

        title = QLabel("从第一个文件夹开始")
        title.setObjectName("PageTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        explanation = QLabel(
            "BookShelf 会按作者 / 系列 / 卷号归档。\n"
            "选择存放电子书的文件夹，扫描后即可在这里统一浏览和阅读。"
        )
        explanation.setObjectName("DetailSub")
        explanation.setWordWrap(True)
        explanation.setAlignment(Qt.AlignCenter)
        self.explanation = explanation
        layout.addWidget(explanation)

        self.scan_button = QPushButton("选择文件夹扫描")
        self.scan_button.setObjectName("PrimaryButton")
        self.scan_button.setMinimumWidth(220)
        self.scan_button.clicked.connect(self.scan_requested)
        layout.addWidget(self.scan_button, 0, Qt.AlignCenter)

        self.sample_link = QLabel('<a href="sample">先看看示例书库</a>')
        self.sample_link.setObjectName("EmptyLibraryLink")
        self.sample_link.setAlignment(Qt.AlignCenter)
        self.sample_link.setCursor(Qt.PointingHandCursor)
        self.sample_link.linkActivated.connect(self.sample_requested)
        layout.addWidget(self.sample_link)

        note = QLabel("扫描仅登记文件路径，不会移动或删除原文件；整理时默认复制入库。")
        note.setObjectName("DetailSub")
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignCenter)
        layout.addWidget(note)
        layout.addStretch(1)


class SampleLibraryDialog(QDialog):
    """纯静态示例，不持有数据库、设置或真实书库路径。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SampleLibraryDialog")
        self.setWindowTitle("示例书库")
        self.resize(760, 390)
        self.setMinimumSize(640, 330)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        title = QLabel("整理后的书库示例")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        hint = QLabel("以下内容仅用于预览，不会写入当前书库，也不会创建或修改任何书籍文件。")
        hint.setObjectName("DetailSub")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(3, 5)
        self.table.setHorizontalHeaderLabels(["书名", "作者", "系列", "卷号", "格式"])
        rows = (
            ("三体", "刘慈欣", "地球往事", "第1卷", "EPUB"),
            ("黑暗森林", "刘慈欣", "地球往事", "第2卷", "EPUB"),
            ("人类简史", "尤瓦尔·赫拉利", "", "", "PDF"),
        )
        for row_index, values in enumerate(rows):
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(value))
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setShowGrid(False)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = QPushButton("关闭示例")
        close_button.setObjectName("GhostButton")
        close_button.clicked.connect(self.close)
        footer.addWidget(close_button)
        layout.addLayout(footer)


__all__ = ["EmptyLibraryPage", "SampleLibraryDialog"]

"""T6：批量浮动条——表格多选后从底部浮出，提供归档/移动/重识别/导出。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


class BatchBar(QFrame):
    archive_requested = Signal()
    move_requested = Signal()
    reidentify_requested = Signal()
    export_requested = Signal()
    clear_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("BatchBar")
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 10, 7)
        layout.setSpacing(8)

        self._count = QLabel("已选 0 本")
        self._count.setObjectName("BatchCount")
        layout.addWidget(self._count)

        self._archive = self._make_button("批量归档")
        self._move = self._make_button("移动到…")
        self._reidentify = self._make_button("重新识别")
        self._export = self._make_button("导出清单", ghost=True)
        self._clear = QPushButton("✕")
        self._clear.setObjectName("BatchClear")
        self._clear.setFixedWidth(26)
        self._clear.setCursor(Qt.PointingHandCursor)

        for button in (self._archive, self._move, self._reidentify, self._export, self._clear):
            layout.addWidget(button)

        self._archive.clicked.connect(self.archive_requested)
        self._move.clicked.connect(self.move_requested)
        self._reidentify.clicked.connect(self.reidentify_requested)
        self._export.clicked.connect(self.export_requested)
        self._clear.clicked.connect(self.clear_requested)

        self.adjustSize()

    @staticmethod
    def _make_button(text: str, *, ghost: bool = False) -> QPushButton:
        button = QPushButton(text)
        if ghost:
            button.setObjectName("GhostButton")
        button.setCursor(Qt.PointingHandCursor)
        return button

    def set_count(self, count: int) -> None:
        self._count.setText(f"已选 {int(count)} 本")

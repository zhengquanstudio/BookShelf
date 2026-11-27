"""底部日志面板：轮询 logger 的内存队列并以颜色区分级别。"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QLabel, QTextEdit, QVBoxLayout, QWidget

from ...logger import drain_ui_logs

_COLORS = {
    "DEBUG": "#6f7681",
    "INFO": "#8fb4f5",
    "OK": "#46c07f",
    "WARNING": "#e8b04b",
    "ERROR": "#e0645d",
    "CRITICAL": "#e0645d",
}
_MAX_BLOCKS = 500


class LogPanel(QWidget):
    """操作日志；每 250ms 取一次新日志，避免刷屏卡顿。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LogPanel")
        self._view = QTextEdit()
        self._view.setObjectName("LogView")
        self._view.setReadOnly(True)
        self._view.setFrameShape(QFrame.NoFrame)
        self._view.document().setMaximumBlockCount(_MAX_BLOCKS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(4)
        header = QLabel("操作日志")
        header.setObjectName("SectionTitle")
        layout.addWidget(header)
        layout.addWidget(self._view, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._flush)
        self._timer.start()

    def _flush(self) -> None:
        items = drain_ui_logs()
        if not items:
            return
        for item in items:
            color = _COLORS.get(item["level"].upper(), "#a3a9b4")
            text = (
                f'<span style="color:#6f7681">{item["ts"][11:23]}</span> '
                f'<span style="color:{color}">[{item["level"]}]</span> '
                f'{item["message"]}'
            )
            self._view.append(text)
        bar = self._view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def append_line(self, text: str, level: str = "INFO") -> None:
        color = _COLORS.get(level.upper(), "#a3a9b4")
        self._view.append(f'<span style="color:{color}">{text}</span>')

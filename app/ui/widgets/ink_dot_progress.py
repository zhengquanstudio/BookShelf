"""24 段墨点进度条（自绘，可点击 / 拖动 seek）。

与阅读器其余部分约定一致：range 固定 0–1000，拖动时只发 valueChanged 做页码
预览，松手发 sliderReleased 由外部真正跳转。外观对齐 v3 原型的 .blocks：
24 个圆角小方块，已读段填强调色，当前段用更深色 + 柔光描边，未读段为 muted
低透明。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

if TYPE_CHECKING:
    from ..theme_tokens import ReaderPalette


class InkDotProgress(QWidget):
    SEGMENTS = 24
    GAP = 3
    SEG_H = 8
    MAX_W = 520

    valueChanged = Signal(int)
    sliderReleased = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ReaderProgress")
        self._value = 0
        self._dragging = False
        self.setFixedHeight(20)
        self.setCursor(Qt.PointingHandCursor)
        self._accent = QColor("#3f6fa8")
        self._accent_soft = QColor("#d8e2f0")
        self._accent_ink = QColor("#2c4f78")
        self._muted = QColor("#8b9099")

    # ---- 与 QSlider 兼容的最小接口 ---------------------------------
    def minimum(self) -> int:  # noqa: D401
        return 0

    def maximum(self) -> int:  # noqa: D401
        return 1000

    def setRange(self, _min: int, _max: int) -> None:
        """range 固定 0–1000，忽略外部传入。"""

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        value = max(0, min(1000, int(value)))
        if value != self._value:
            self._value = value
            self.update()
            self.valueChanged.emit(value)

    def apply_palette(self, palette: "ReaderPalette") -> None:
        from ..theme_tokens import mix

        self._accent = QColor(palette.accent)
        self._muted = QColor(palette.muted)
        self._accent_soft = QColor(mix(palette.accent, palette.page, 0.82))
        self._accent_ink = QColor(mix(palette.accent, palette.ink, 0.45))
        self.update()

    # ---- 绘制 -------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        width = self.width()
        block_w = min(self.MAX_W, width)
        x0 = (width - block_w) / 2.0
        seg = (block_w - self.GAP * (self.SEGMENTS - 1)) / self.SEGMENTS
        seg = max(1.0, seg)
        y = (self.height() - self.SEG_H) / 2.0

        ratio = self._value / 1000.0
        filled = int(ratio * self.SEGMENTS)
        cur = min(self.SEGMENTS - 1, filled) if ratio > 0 else -1

        empty = QColor(self._muted)
        empty.setAlpha(56)
        for i in range(self.SEGMENTS):
            x = x0 + i * (seg + self.GAP)
            if i < filled:
                fill = self._accent
            elif i == cur:
                fill = self._accent_ink
            else:
                fill = empty
            painter.setPen(Qt.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(x, y, seg, self.SEG_H, 2, 2)
            if i == cur:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(self._accent_soft, 2))
                painter.drawRoundedRect(x - 1, y - 1, seg + 2, self.SEG_H + 2, 3, 3)
        painter.end()

    # ---- 鼠标：点击 / 拖动 seek ------------------------------------
    def _set_from_x(self, x: float) -> None:
        block_w = min(self.MAX_W, self.width())
        x0 = (self.width() - block_w) / 2.0
        if block_w <= 0:
            ratio = 0.0
        else:
            ratio = min(1.0, max(0.0, (x - x0) / block_w))
        self.setValue(round(ratio * 1000))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._set_from_x(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._dragging and event.buttons() & Qt.LeftButton:
            self._set_from_x(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._dragging and event.button() == Qt.LeftButton:
            self._dragging = False
            self._set_from_x(event.position().x())
            self.sliderReleased.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

"""带 10% 刻度的底栏进度条。

自绘 4px 轨道 + 12px 手柄，每 10% 画一条 3px 竖线（muted 30% 透明）。
拖动过程只发 valueChanged 给页码预览，松手才由外部 seek。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QSlider, QWidget

if TYPE_CHECKING:  # 仅用于类型提示，避免运行时循环依赖
    from ..theme_tokens import ReaderPalette


class SegmentedProgress(QSlider):
    """range 固定 0–1000 的分段刻度进度条。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Horizontal, parent)
        self.setObjectName("ReaderProgress")
        self.setRange(0, 1000)
        self.setFixedHeight(20)
        self.setCursor(Qt.PointingHandCursor)
        self._border = QColor("#ddd8cd")
        self._accent = QColor("#3f6fa8")
        self._muted = QColor("#8b9099")
        self._dragging = False

    # ---- 主题 -------------------------------------------------------
    def apply_palette(self, palette: "ReaderPalette") -> None:
        self._border = QColor(palette.border)
        self._accent = QColor(palette.accent)
        self._muted = QColor(palette.muted)
        self.update()

    # ---- 绘制 -------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        width = float(self.width())
        height = float(self.height())
        track = 4.0
        radius = track / 2
        top = (height - track) / 2

        painter.setPen(Qt.NoPen)
        painter.setBrush(self._border)
        painter.drawRoundedRect(QRectF(0, top, width, track), radius, radius)

        span = max(1, self.maximum() - self.minimum())
        ratio = (self.value() - self.minimum()) / span
        ratio = min(1.0, max(0.0, ratio))
        handle_x = 6 + ratio * max(0.0, width - 12)

        painter.setBrush(self._accent)
        painter.drawRoundedRect(QRectF(0, top, handle_x, track), radius, radius)

        # 每 10% 一条 3px 竖线，叠在轨道上方，深浅主题都保持克制。
        tick = QColor(self._muted)
        tick.setAlpha(76)
        painter.setPen(QPen(tick, 1))
        for step in range(1, 10):
            x = width * step / 10
            painter.drawLine(QPointF(x, top - 2), QPointF(x, top + track + 2))

        painter.setPen(Qt.NoPen)
        painter.setBrush(self._accent)
        painter.drawEllipse(QPointF(handle_x, height / 2), 6, 6)

    # ---- 鼠标：拖动只预览，松手才 seek -------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._set_from_position(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._dragging and event.buttons() & Qt.LeftButton:
            self._set_from_position(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._dragging and event.button() == Qt.LeftButton:
            self._dragging = False
            self._set_from_position(event.position().x())
            self.sliderReleased.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _set_from_position(self, x: float) -> None:
        width = max(1, self.width())
        ratio = min(1.0, max(0.0, float(x) / width))
        value = round(self.minimum() + ratio * (self.maximum() - self.minimum()))
        if value != self.value():
            self.setValue(value)
            self.sliderMoved.emit(value)

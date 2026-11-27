"""阅读设置里的 − [值] + 步进控件。

字号、行距、段距、页边距共用同一套控件，避免 QSpinBox 箭头与自绘按钮混用。
值只读，支持长按连发（400ms 后每 90ms 一次）与滚轮调节。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class Stepper(QWidget):
    """− [ 19 ] + 的三段式步进器，值范围与步进由构造参数决定。"""

    changed = Signal(float)

    def __init__(
        self,
        minimum: float,
        maximum: float,
        step: float,
        value: float,
        *,
        decimals: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._minimum = float(minimum)
        self._maximum = float(maximum)
        self._step = abs(float(step)) or 1.0
        self._decimals = max(0, int(decimals))
        self._value = self._clamp(value)
        self.setObjectName("Stepper")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.minus_button = self._make_button("−", "−")
        self.value_label = QLabel(self._format(self._value))
        self.value_label.setObjectName("StepValue")
        self.value_label.setAlignment(Qt.AlignCenter)
        self.value_label.setFixedWidth(44)
        self.plus_button = self._make_button("+", "+")

        layout.addStretch(1)
        layout.addWidget(self.minus_button)
        layout.addWidget(self.value_label)
        layout.addWidget(self.plus_button)
        layout.addStretch(1)

        self.minus_button.clicked.connect(lambda: self.step_by(-1))
        self.plus_button.clicked.connect(lambda: self.step_by(1))
        self._update_buttons()

    # ---- 对外接口 ---------------------------------------------------
    def value(self) -> float:
        return self._value

    def set_value(self, value: float, *, emit: bool = False) -> None:
        """写入数值；默认不触发 changed，供外部同步界面状态。"""
        clamped = self._clamp(value)
        changed = abs(clamped - self._value) > 1e-9
        self._value = clamped
        self.value_label.setText(self._format(clamped))
        self._update_buttons()
        if emit and changed:
            self.changed.emit(clamped)

    def step_by(self, direction: int) -> None:
        self.set_value(self._value + direction * self._step, emit=True)

    # ---- 内部 -------------------------------------------------------
    def _make_button(self, text: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("StepBtn")
        button.setFixedSize(34, 30)
        button.setToolTip(tip)
        button.setCursor(Qt.PointingHandCursor)
        button.setFocusPolicy(Qt.NoFocus)
        button.setAutoRepeat(True)
        button.setAutoRepeatDelay(400)
        button.setAutoRepeatInterval(90)
        return button

    def _clamp(self, value: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = self._minimum
        number = min(self._maximum, max(self._minimum, number))
        return round(number, self._decimals + 2)

    def _format(self, value: float) -> str:
        if self._decimals <= 0:
            return str(int(round(value)))
        return f"{value:.{self._decimals}f}"

    def _update_buttons(self) -> None:
        self.minus_button.setEnabled(self._value > self._minimum + 1e-9)
        self.plus_button.setEnabled(self._value < self._maximum - 1e-9)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if not delta:
            delta = event.pixelDelta().y()
        if not delta:
            event.ignore()
            return
        self.step_by(1 if delta > 0 else -1)
        event.accept()

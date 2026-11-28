"""T21：阅读统计页；数据全部由 ReadingRepository.reading_dashboard 提供。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...db.repositories.reading_repo import ReadingRepository
from ..theme import chrome_tokens


def format_duration(seconds: int) -> str:
    """空态显示 0；非零不足一分钟不四舍五入成 0.0 小时。"""
    seconds = max(0, int(seconds or 0))
    if seconds == 0:
        return "0"
    if seconds < 60:
        return "不足 1 分钟"
    if seconds < 3600:
        return f"{max(1, seconds // 60)} 分钟"
    return f"{seconds / 3600:.1f} 小时"


class MonthlyBarChart(QWidget):
    """近 6 个月阅读时长柱状图，QPainter 自绘，无第三方依赖。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ReadingMonthChart")
        self.setMinimumHeight(230)
        self._data: list[dict[str, Any]] = []
        self._theme = "night"
        self._accent = "blue"

    def set_theme(self, theme: str, accent: str = "blue") -> None:
        self._theme = theme
        self._accent = accent
        self.update()

    def set_data(self, data: list[dict[str, Any]]) -> None:
        self._data = list(data)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        tokens = chrome_tokens(self._theme, self._accent)
        width = max(1, self.width())
        height = max(1, self.height())
        left, right, top, bottom = 48, 18, 20, 34
        plot = QRect(left, top, max(1, width - left - right), max(1, height - top - bottom))
        peak = max((int(item.get("seconds") or 0) for item in self._data), default=0)
        scale_seconds = peak or 3600
        number_font = QFont("Consolas")
        number_font.setPointSize(9)
        painter.setFont(number_font)

        # 0 / 50% / 100% 三条坐标线，空库也保留。
        for ratio in (0.0, 0.5, 1.0):
            y = round(plot.bottom() - plot.height() * ratio)
            painter.setPen(QPen(QColor(tokens["line2"]), 1))
            painter.drawLine(plot.left(), y, plot.right(), y)
            label = f"{scale_seconds * ratio / 3600:.1f}"
            painter.setPen(QColor(tokens["muted"]))
            painter.drawText(
                QRect(0, y - 9, left - 8, 18), int(Qt.AlignRight | Qt.AlignVCenter), label
            )

        if not self._data:
            painter.end()
            return
        gap = 14
        slot_width = max(12, (plot.width() - gap * (len(self._data) - 1)) // len(self._data))
        for index, item in enumerate(self._data):
            x = plot.left() + index * (slot_width + gap)
            slot = QRect(x, plot.top(), slot_width, plot.height())
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(tokens["panel2"]))
            painter.drawRoundedRect(slot, 6, 6)
            seconds = max(0, int(item.get("seconds") or 0))
            if seconds:
                bar_height = max(3, round(plot.height() * seconds / scale_seconds))
                bar = QRect(x, plot.bottom() - bar_height, slot_width, bar_height)
                painter.setBrush(QColor(tokens["accent"]))
                painter.drawRoundedRect(bar, 6, 6)
                painter.setPen(QColor(tokens["muted"]))
                painter.drawText(
                    QRect(x - 8, max(0, bar.top() - 19), slot_width + 16, 16),
                    int(Qt.AlignCenter),
                    f"{seconds / 3600:.1f}",
                )
            painter.setPen(QColor(tokens["muted"]))
            painter.drawText(
                QRect(x - 8, plot.bottom() + 7, slot_width + 16, 20),
                int(Qt.AlignCenter),
                str(item.get("label") or ""),
            )
        painter.end()


class StatsPage(QWidget):
    """四张指标卡 + 近 6 个月图表 + 最近 10 次阅读记录。"""

    go_shelf_requested = Signal()

    def __init__(self, db: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo = ReadingRepository(db)
        self.dashboard: dict[str, Any] = {}
        self._theme = "night"
        self._accent = "blue"
        self.setObjectName("StatsPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("StatsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 14, 18, 18)
        layout.setSpacing(14)

        heading = QLabel("阅读统计")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.metric_values: dict[str, QLabel] = {}
        self.metric_subtitles: dict[str, QLabel] = {}
        for key, title, subtitle in (
            ("total_seconds", "累计阅读时长", "所有书籍累计"),
            ("month_seconds", "本月阅读时长", ""),
            ("finished_books", "已读书籍数", "标记为已读"),
            ("streak_days", "连续阅读天数", "按自然日计算"),
        ):
            card = QFrame()
            card.setObjectName("StatsMetricCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            card_layout.setSpacing(4)
            label = QLabel(title)
            label.setObjectName("StatsMetricLabel")
            value = QLabel("0")
            value.setObjectName("StatsMetricValue")
            sub = QLabel(subtitle)
            sub.setObjectName("StatsMetricSub")
            card_layout.addWidget(label)
            card_layout.addWidget(value)
            card_layout.addWidget(sub)
            cards.addWidget(card, 1)
            self.metric_values[key] = value
            self.metric_subtitles[key] = sub
        layout.addLayout(cards)

        chart_panel = QFrame()
        chart_panel.setObjectName("StatsPanelBox")
        chart_layout = QVBoxLayout(chart_panel)
        chart_layout.setContentsMargins(14, 12, 14, 12)
        chart_title = QLabel("近 6 个月阅读时长（小时）")
        chart_title.setObjectName("SectionTitle")
        chart_layout.addWidget(chart_title)
        self.chart = MonthlyBarChart()
        chart_layout.addWidget(self.chart)
        layout.addWidget(chart_panel)

        recent_panel = QFrame()
        recent_panel.setObjectName("StatsPanelBox")
        recent_layout = QVBoxLayout(recent_panel)
        recent_layout.setContentsMargins(14, 12, 14, 12)
        recent_title = QLabel("最近阅读记录")
        recent_title.setObjectName("SectionTitle")
        recent_layout.addWidget(recent_title)
        self.recent_layout = QVBoxLayout()
        self.recent_layout.setSpacing(8)
        recent_layout.addLayout(self.recent_layout)
        layout.addWidget(recent_panel)
        layout.addStretch(1)
        self.empty_label: QLabel | None = None
        self.go_shelf_button: QPushButton | None = None
        self.refresh()

    def set_theme(self, theme: str, accent: str = "blue") -> None:
        self._theme = theme
        self._accent = accent
        self.chart.set_theme(theme, accent)

    def refresh(self, *, now: datetime | None = None) -> None:
        self.dashboard = self.repo.reading_dashboard(now=now)
        summary = self.dashboard["summary"]
        self.metric_values["total_seconds"].setText(format_duration(summary["total_seconds"]))
        self.metric_values["month_seconds"].setText(format_duration(summary["month_seconds"]))
        self.metric_values["finished_books"].setText(str(summary["finished_books"]))
        self.metric_values["streak_days"].setText(str(summary["streak_days"]))
        current = now or datetime.now().astimezone()
        self.metric_subtitles["month_seconds"].setText(f"{current.year} 年 {current.month} 月")
        self.chart.set_data(self.dashboard["months"])
        self._rebuild_recent(self.dashboard["recent"])

    def _rebuild_recent(self, rows: list[dict[str, Any]]) -> None:
        while self.recent_layout.count():
            item = self.recent_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.empty_label = None
        self.go_shelf_button = None
        if not rows:
            self.empty_label = QLabel("暂无阅读记录，去读几本书吧")
            self.empty_label.setObjectName("DetailSub")
            self.empty_label.setAlignment(Qt.AlignCenter)
            self.recent_layout.addWidget(self.empty_label)
            self.go_shelf_button = QPushButton("去书架")
            self.go_shelf_button.setObjectName("PrimaryButton")
            self.go_shelf_button.clicked.connect(self.go_shelf_requested)
            self.recent_layout.addWidget(self.go_shelf_button, 0, Qt.AlignCenter)
            return
        for row in rows:
            frame = QFrame()
            frame.setObjectName("StatsSessionRow")
            layout = QHBoxLayout(frame)
            layout.setContentsMargins(10, 8, 10, 8)
            title = QLabel(str(row["title"]))
            title.setObjectName("StatsSessionTitle")
            layout.addWidget(title, 1)
            detail = QLabel(
                f"{str(row['started_at'])[:10]}  ·  {format_duration(row['seconds'])}  ·  "
                f"{int(row['pages'] or 0)} 页"
            )
            detail.setObjectName("StatsSessionMeta")
            layout.addWidget(detail)
            self.recent_layout.addWidget(frame)


__all__ = ["MonthlyBarChart", "StatsPage", "format_duration"]

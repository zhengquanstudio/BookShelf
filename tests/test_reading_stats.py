# -*- coding: utf-8 -*-
"""T21：阅读统计聚合、跨月/连续天数与统计页空态。"""

from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.db.repositories.book_repo import BookRepository
from app.db.repositories.reading_repo import ReadingRepository
from app.services.settings_service import SettingsService
from app.ui.main_window import MainWindow
from app.ui.pages.stats_page import StatsPage, format_duration


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def _book(db, key: str = "stats", title: str = "统计测试书") -> int:
    return BookRepository(db).create(
        file_path=f"C:/books/{key}.epub",
        quick_hash=key,
        format="epub",
        title=title,
        status="ok",
    )


def _session(db, book_id: int, started_at: str, seconds: int, pages: int = 0) -> None:
    db.execute(
        "INSERT INTO reading_sessions(book_id, started_at, seconds, pages) VALUES (?, ?, ?, ?)",
        (book_id, started_at, seconds, pages),
    )


def test_empty_dashboard_returns_zero_without_exceptions(db):
    now = datetime(2026, 3, 15, 12, tzinfo=timezone.utc)
    data = ReadingRepository(db).reading_dashboard(now=now)
    assert data["summary"] == {
        "total_seconds": 0,
        "month_seconds": 0,
        "finished_books": 0,
        "streak_days": 0,
    }
    assert len(data["months"]) == 6
    assert [item["month"] for item in data["months"]] == [
        "2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03"
    ]
    assert all(item["seconds"] == 0 for item in data["months"])
    assert data["recent"] == []


def test_three_consecutive_days_produce_streak_three(db):
    book_id = _book(db)
    for started_at, seconds in (
        ("2026-11-26T20:00:00+08:00", 60),
        ("2026-11-27T08:00:00+08:00", 90),
        ("2026-11-27T22:00:00+08:00", 30),
        ("2026-11-28T09:00:00+08:00", 120),
    ):
        _session(db, book_id, started_at, seconds)
    now = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)
    summary = ReadingRepository(db).reading_dashboard(now=now)["summary"]
    assert summary["streak_days"] == 3
    assert summary["month_seconds"] == 300


def test_cross_month_aggregation_fills_months_and_excludes_out_of_range(db):
    book_id = _book(db)
    _session(db, book_id, "2025-07-31T23:00:00+08:00", 999)
    _session(db, book_id, "2025-12-31T23:00:00+08:00", 120)
    _session(db, book_id, "2026-01-01T00:30:00+08:00", 60)
    now = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
    data = ReadingRepository(db).reading_dashboard(now=now)
    months = {item["month"]: item["seconds"] for item in data["months"]}
    assert months["2025-12"] == 120
    assert months["2026-01"] == 60
    assert "2025-07" not in months
    assert data["summary"]["month_seconds"] == 60


def test_recent_sessions_returns_ten_with_book_titles(db):
    book_id = _book(db, title="最近阅读")
    for day in range(1, 13):
        _session(db, book_id, f"2026-01-{day:02d}T08:00:00+08:00", day * 10, day)
    recent = ReadingRepository(db).recent_sessions()
    assert len(recent) == 10
    assert recent[0]["title"] == "最近阅读"
    assert recent[0]["pages"] == 12
    assert recent[-1]["pages"] == 3


def test_duration_format_never_shows_zero_hours():
    assert format_duration(0) == "0"
    assert format_duration(30) == "不足 1 分钟"
    assert format_duration(60) == "1 分钟"
    assert format_duration(3600) == "1.0 小时"


def test_stats_page_empty_keeps_axes_slots_and_real_shelf_button(db, qapp):
    page = StatsPage(db)
    page.resize(1100, 760)
    page.show()
    try:
        page.refresh(now=datetime(2026, 3, 15, 12, tzinfo=timezone.utc))
        qapp.processEvents()
        assert all(label.text() == "0" for label in page.metric_values.values())
        assert len(page.chart._data) == 6
        assert all(item["seconds"] == 0 for item in page.chart._data)
        assert page.empty_label.text() == "暂无阅读记录，去读几本书吧"
        clicked = []
        page.go_shelf_requested.connect(lambda: clicked.append(True))
        page.go_shelf_button.click()
        assert clicked == [True]
        assert not page.grab().isNull()
    finally:
        page.close()


def test_main_window_stats_navigation_and_empty_button_go_to_shelf(
    db, tmp_path, qapp, qt_settings
):
    settings = SettingsService(tmp_path / "config.json")
    settings.set_library_root(str(tmp_path))
    window = MainWindow(db=db, settings=settings, qt_settings=qt_settings)
    window.show()
    try:
        window._on_nav("stats")
        qapp.processEvents()
        assert window.content_stack.currentWidget() is window.stats_page
        assert not window.vertical.widget(1).isVisible()
        window.stats_page.go_shelf_button.click()
        assert window.content_stack.currentWidget() is window.shelf_page
        assert not window.vertical.widget(1).isVisible()
    finally:
        window.close()

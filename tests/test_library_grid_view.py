# -*- coding: utf-8 -*-
"""T23：书库表格/网格切换、同一实例复用与 QSettings 持久化。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.db.repositories.book_repo import BookRepository
from app.db.repositories.reading_repo import ReadingRepository
from app.services.settings_service import SettingsService
from app.ui.main_window import MainWindow


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def _book(db, key: str, title: str) -> int:
    return BookRepository(db).create(
        file_path=f"C:/books/{key}.epub",
        quick_hash=key,
        format="epub",
        title=title,
        status="ok",
    )


def _make_window(db, tmp_path, qt_settings):
    settings = SettingsService(tmp_path / "config.json")
    settings.set_library_root(str(tmp_path))
    window = MainWindow(db=db, settings=settings, qt_settings=qt_settings)
    window.show()
    return window


def test_grid_list_toggle_twice_reuses_one_shelf_widget(db, tmp_path, qapp, qt_settings):
    _book(db, "a", "Alpha")
    _book(db, "b", "Beta")
    window = _make_window(db, tmp_path, qt_settings)
    try:
        grid_instance = window.shelf_page
        window._view_grid_btn.click()
        qapp.processEvents()
        assert window._library_view_mode == "grid"
        assert window.table_stack.currentWidget() is grid_instance
        assert window.shelf_page.card_count == 2
        assert not window.shelf_page._shelf_only
        assert qt_settings.value("ui.library_view") == "grid"

        window._view_list_btn.click()
        assert window.table_stack.currentWidget() is window.table
        assert window._view_list_btn.isChecked()
        window._view_grid_btn.click()
        assert window.table_stack.currentWidget() is grid_instance
        assert window.shelf_page.card_count == 2
        assert window._view_grid_btn.isChecked()
    finally:
        window.close()


def test_library_view_is_restored_after_restart(db, tmp_path, qapp, qt_settings):
    _book(db, "persist", "持久化")
    first = _make_window(db, tmp_path, qt_settings)
    first._set_library_view("grid")
    first.close()
    qapp.processEvents()

    restored_settings = QSettings(qt_settings.fileName(), QSettings.IniFormat)
    second = _make_window(db, tmp_path, restored_settings)
    try:
        assert second._library_view_mode == "grid"
        assert second.table_stack.currentWidget() is second.shelf_page
        assert second._view_grid_btn.isChecked()
        assert not second._view_list_btn.isChecked()
        assert second.shelf_page.card_count == 1
    finally:
        second.close()


def test_library_grid_shows_all_but_shelf_keeps_saved_filter(db, tmp_path, qapp, qt_settings):
    _book(db, "plain", "普通书")
    read_id = _book(db, "read", "在读图书")
    ReadingRepository(db).save_progress(read_id, "{}", 0.35)
    window = _make_window(db, tmp_path, qt_settings)
    try:
        window._set_library_view("grid")
        assert window.shelf_page.card_count == 2
        window._on_nav("shelf")
        qapp.processEvents()
        assert window.content_stack.currentWidget() is window.shelf_page
        assert window.shelf_page._shelf_only
        assert window.shelf_page.card_count == 1
        assert window.shelf_page.model.row_data(0)["title"] == "在读图书"

        window._on_nav("all")
        assert window.content_stack.currentWidget() is window.content_splitter
        assert window.table_stack.currentWidget() is window.shelf_page
        assert not window.shelf_page._shelf_only
        assert window.shelf_page.card_count == 2
    finally:
        window.close()

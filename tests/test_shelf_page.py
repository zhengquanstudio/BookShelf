# -*- coding: utf-8 -*-
"""T20：书架网格、共享模型/筛选、无封面占位与真实空态跳转。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from app.db.repositories.book_repo import BookRepository
from app.db.repositories.reading_repo import ReadingRepository
from app.services.library_service import LibraryService
from app.services.settings_service import SettingsService
from app.ui.main_window import MainWindow
from app.ui.pages.shelf_page import ShelfCardDelegate, ShelfPage
from app.ui.widgets.book_table import BookTableModel


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
        author_raw="测试作者",
        status="ok",
    )


def _page(db, qapp):
    library = LibraryService(db)
    model = BookTableModel()
    page = ShelfPage(model, library)
    page.resize(960, 720)
    page.show()
    qapp.processEvents()
    return page


def test_shelf_cards_match_query_and_only_include_saved_or_favorite(db, qapp):
    read_id = _book(db, "read", "正在阅读")
    favorite_id = _book(db, "favorite", "收藏图书")
    _book(db, "plain", "普通图书")
    ReadingRepository(db).save_progress(read_id, "{}", 0.42)
    db.execute("UPDATE books SET favorite = 1 WHERE id = ?", (favorite_id,))

    page = _page(db, qapp)
    try:
        page.refresh()
        titles = {page.model.row_data(row)["title"] for row in range(page.card_count)}
        assert titles == {"正在阅读", "收藏图书"}
        assert page.card_count == page.total == 2
        assert page.stack.currentWidget() is page.list

        page.search_box.setText("收藏")
        qapp.processEvents()
        assert page.card_count == page.total == 1
        assert page.model.row_data(0)["title"] == "收藏图书"
    finally:
        page.close()


def test_missing_cover_uses_first_character_and_paints_without_crashing(db, qapp):
    book_id = _book(db, "coverless", "情绪操控术")
    ReadingRepository(db).save_progress(book_id, "{}", 0.25)
    page = _page(db, qapp)
    try:
        page.refresh()
        book = page.model.row_data(0)
        assert ShelfCardDelegate.placeholder_text(book) == "情"
        assert book["cover_path"] is None
        pixmap = page.list.viewport().grab()
        assert not pixmap.isNull()
        assert page.delegate.sizeHint(QStyleOptionViewItem(), page.model.index(0, 0)).height() == 282
    finally:
        page.close()


def test_empty_state_has_real_library_button(db, qapp):
    page = _page(db, qapp)
    try:
        page.refresh()
        assert page.stack.currentWidget() is page.empty_page
        assert page.empty_title.text() == "暂无数据"
        assert page.empty_hint.text() == "书架还空着，去书库挑一本"
        assert page.go_library_button.isEnabled()
        clicked = []
        page.go_library_requested.connect(lambda: clicked.append(True))
        page.go_library_button.click()
        assert clicked == [True]
    finally:
        page.close()


def test_main_window_shelf_navigation_shares_search_and_hides_bottom_stats(
    db, tmp_path, qapp, qt_settings
):
    book_id = _book(db, "main", "书架集成")
    ReadingRepository(db).save_progress(book_id, "{}", 0.1)
    settings = SettingsService(tmp_path / "config.json")
    settings.set_library_root(str(tmp_path))
    window = MainWindow(db=db, settings=settings, qt_settings=qt_settings)
    window.show()
    qapp.processEvents()
    try:
        window._on_nav("shelf")
        qapp.processEvents()
        assert window.content_stack.currentWidget() is window.shelf_page
        assert not window.vertical.widget(1).isVisible()
        assert window.shelf_page.card_count == 1

        window.shelf_page.search_box.setText("集成")
        assert window.search_box.text() == "集成"
        assert window.shelf_page.card_count == 1

        window.shelf_page.go_library_button.click()
        assert window.content_stack.currentWidget() is window.content_splitter
        assert window.vertical.widget(1).isVisible()
        assert window.search_box.text() == "集成"
    finally:
        window.close()


def test_book_detail_overlay_show_for_reuses_library_data(db, qapp):
    book_id = _book(db, "detail", "详情浮层")
    ReadingRepository(db).save_progress(book_id, "{}", 0.5)
    page = _page(db, qapp)
    try:
        page.refresh()
        assert page.detail_overlay.show_for(book_id)
        assert page.detail_overlay.isVisible()
        assert page.detail_overlay.d_title.text() == "详情浮层"
        assert page.detail_overlay.d_progress.text().startswith("50%")
        assert page.detail_overlay.view_actions.isHidden()
    finally:
        page.close()

# -*- coding: utf-8 -*-
"""T22：笔记/高亮/书签互斥过滤、搜索、删除、空态与位置跳转。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.db.repositories.book_repo import BookRepository
from app.db.repositories.reading_repo import ReadingRepository
from app.services.settings_service import SettingsService
from app.ui.main_window import MainWindow
from app.ui.pages.notes_page import NotesPage
from app.ui.pages.reader_container import ReaderContainer
from app.ui.theme_tokens import resolve_highlight_color


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def _book(db, key: str = "notes", title: str = "笔记测试书") -> int:
    return BookRepository(db).create(
        file_path=f"C:/books/{key}.epub",
        quick_hash=key,
        format="epub",
        title=title,
        status="ok",
    )


def _seed(db):
    book_id = _book(db)
    repo = ReadingRepository(db)
    highlight_id = repo.add_bookmark(
        book_id, '{"type":"epub","cfi":"epubcfi(/1)"}',
        chapter="第一章", text="普通高亮", color="green", kind="highlight",
    )
    note_highlight_id = repo.add_bookmark(
        book_id, '{"type":"epub","cfi":"epubcfi(/2)"}',
        chapter="第二章", text="笔记正文关键字", note="独特想法", color="pink", kind="highlight",
    )
    note_id = repo.add_bookmark(
        book_id, '{"type":"epub","cfi":"epubcfi(/3)"}',
        chapter="第三章", text="另一段", note="笔记说明", color="blue", kind="note",
    )
    bookmark_id = repo.add_bookmark(
        book_id, '{"type":"pdf","page":7}',
        chapter="第七章", text="", color="amber", kind="bookmark",
    )
    return book_id, {
        "highlight": highlight_id,
        "note_highlight": note_highlight_id,
        "note": note_id,
        "bookmark": bookmark_id,
    }


def _page(db, qapp):
    page = NotesPage(db)
    page.resize(1080, 760)
    page.show()
    qapp.processEvents()
    return page


def _ids(page):
    return {int(row["id"]) for row in page.rows}


def test_three_categories_are_mutually_exclusive(db, qapp):
    _seed(db)
    page = _page(db, qapp)
    try:
        assert _ids(page) == {2, 3}
        page.set_category("highlight")
        assert _ids(page) == {1}
        page.set_category("bookmark")
        assert _ids(page) == {4}
        page.set_category("note")
        assert _ids(page).isdisjoint({1, 4})
    finally:
        page.close()


def test_search_matches_both_text_and_note(db, qapp):
    _seed(db)
    page = _page(db, qapp)
    try:
        page.search_box.setText("正文关键字")
        assert _ids(page) == {2}
        page.search_box.setText("独特想法")
        assert _ids(page) == {2}
        page.search_box.setText("不存在的词")
        assert page.visible_count == 0
        assert page.stack.currentWidget() is page.empty_page
    finally:
        page.close()


def test_delete_refreshes_count_and_database_and_emits_toast(db, qapp):
    _seed(db)
    page = _page(db, qapp)
    try:
        assert page.visible_count == 2
        row = page.row_widgets[0]
        deleted_id = int(row.row_data["id"])
        messages = []
        page.toast_requested.connect(messages.append)
        row.delete_button.click()
        assert page.visible_count == 1
        assert db.query_one("SELECT id FROM bookmarks WHERE id = ?", (deleted_id,)) is None
        assert messages == ["已删除"]
    finally:
        page.close()


def test_clicking_row_emits_existing_book_and_raw_locator(db, qapp):
    _seed(db)
    page = _page(db, qapp)
    try:
        opened = []
        page.open_locator_requested.connect(lambda book_id, locator: opened.append((book_id, locator)))
        row = page.row_widgets[0]
        QTest.mouseClick(row, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))
        assert opened
        assert opened[0][0] == row.row_data["book_id"]
        assert opened[0][1] == row.row_data["locator_json"]
        expected_color = resolve_highlight_color(row.row_data["color"], dark=True)
        assert expected_color in row.color_dot.styleSheet()
    finally:
        page.close()


def test_each_category_has_specific_empty_text_and_working_button(db, qapp):
    page = _page(db, qapp)
    try:
        clicked = []
        page.go_shelf_requested.connect(lambda: clicked.append(True))
        for category, expected in NotesPage.EMPTY_TEXT.items():
            page.set_category(category)
            assert page.stack.currentWidget() is page.empty_page
            assert page.empty_title.text() == "暂无数据"
            assert page.empty_hint.text() == expected
            assert page.go_shelf_button.isEnabled()
        page.go_shelf_button.click()
        assert clicked == [True]
    finally:
        page.close()


def test_reader_reuses_go_to_for_pdf_and_defers_until_rendered(db, qapp, tmp_path):
    settings = SettingsService(tmp_path / "config.json")
    reader = ReaderContainer(db, settings, web_enabled=False)

    class FakeWeb:
        def __init__(self):
            self.targets = []

        def go_to(self, target):
            self.targets.append(target)

    fake = FakeWeb()
    try:
        reader.web = fake
        reader._web_enabled = True
        reader.loading_overlay.show()
        reader.go_to_locator('{"type":"pdf","page":7}')
        assert fake.targets == []
        reader.loading_overlay.hide()
        reader._apply_pending_locator()
        assert fake.targets == [{"page": 7}]
        reader.go_to_locator('{"type":"epub","cfi":"epubcfi(/2)"}')
        assert fake.targets[-1] == "epubcfi(/2)"
    finally:
        reader._web_enabled = False
        reader.close_book()
        reader.close()


def test_main_window_notes_navigation_hides_bottom_stats(db, tmp_path, qapp, qt_settings):
    _seed(db)
    settings = SettingsService(tmp_path / "config.json")
    settings.set_library_root(str(tmp_path))
    window = MainWindow(db=db, settings=settings, qt_settings=qt_settings)
    window.show()
    try:
        window._on_nav("notes")
        qapp.processEvents()
        assert window.content_stack.currentWidget() is window.notes_page
        assert not window.vertical.widget(1).isVisible()
        assert window.notes_page.visible_count == 2
        window.notes_page.set_category("highlight")
        assert window.notes_page.visible_count == 1
    finally:
        window.close()

"""R1：52px 顶栏、封面/作者、工具按钮与顶底栏自动隐藏。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from app.db.repositories.book_repo import BookRepository
from app.services.settings_service import SettingsService
from app.ui.pages.reader_container import ReaderContainer


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture()
def settings(tmp_path):
    return SettingsService(tmp_path / "config.json")


@pytest.fixture()
def reader(qapp, db, settings):
    return ReaderContainer(db, settings, web_enabled=False)


def _loaded_reader(reader):
    reader._book_id = 1
    reader._book = {}
    reader._sidebar_visible = False
    reader.resize(1200, 800)
    return reader


def test_r1_topbar_matches_prototype(reader):
    assert reader.topbar.minimumHeight() == 52
    assert reader.topbar.maximumHeight() == 52
    assert reader.cover_label.width() == 26
    assert reader.cover_label.height() == 36
    assert reader.author_label.objectName() == "ReaderSub"
    assert reader.toc_button.icon_name() == "toc"
    assert reader.info_button.icon_name() == "info"
    assert reader.bookmark_button.isCheckable()
    assert reader.pin_button.isChecked()
    assert [action.text() for action in reader.more_menu.actions()] == [
        "全屏（F11）",
        "返回书库",
        "快捷键",
        "",
        "收藏",
    ]


def test_r1_update_header_sets_author_and_cover(reader):
    reader._book_id = 7
    reader._book = {
        "title": "我的书",
        "author_name": "某某",
        "format": "epub",
        "cover_path": "",
    }
    reader._book_path = "x"
    reader._update_header()
    assert reader.author_label.text() == "某某"
    assert reader.cover_label.pixmap() is not None
    assert not reader.cover_label.pixmap().isNull()

    reader._book["author_name"] = ""
    reader._update_header()
    assert reader.author_label.text() == "作者未知"


def test_r1_favorite_action_toggles_db(reader, db, tmp_path):
    path = tmp_path / "b.epub"
    path.write_text("x", encoding="utf-8")
    book_id = BookRepository(db).create(
        file_path=str(path), quick_hash="b", format="epub", title="B", status="ok"
    )
    reader._book_id = book_id
    reader._book = {"favorite": 0}

    reader.favorite_button.trigger()
    row = db.query_one("SELECT favorite FROM books WHERE id = ?", (book_id,))
    assert row["favorite"] == 1
    assert reader.favorite_button.isChecked()

    reader.favorite_button.trigger()
    row = db.query_one("SELECT favorite FROM books WHERE id = ?", (book_id,))
    assert row["favorite"] == 0
    assert not reader.favorite_button.isChecked()


def test_r1_autohide_moves_both_bars_without_moving_body(reader):
    reader = _loaded_reader(reader)
    body_geometry = reader.splitter.geometry()

    reader._hide_chrome()
    assert reader._chrome_visible is False
    assert reader.topbar.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert reader.bottombar.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert reader._chrome_pos_anims["top"].endValue() == QPoint(0, -52)
    assert reader._chrome_pos_anims["bottom"].endValue() == QPoint(0, 800)
    assert reader._chrome_opacity_anims["top"].endValue() == pytest.approx(0.0)
    assert reader._chrome_opacity_anims["bottom"].endValue() == pytest.approx(0.0)
    assert reader.splitter.geometry() == body_geometry

    reader._show_chrome()
    assert reader._chrome_visible is True
    assert not reader.topbar.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert not reader.bottombar.testAttribute(Qt.WA_TransparentForMouseEvents)
    assert reader._chrome_pos_anims["top"].endValue() == QPoint(0, 0)
    assert reader._chrome_pos_anims["bottom"].endValue() == QPoint(0, 760)
    assert reader._chrome_hide_timer.interval() == 1600
    assert reader.splitter.geometry() == body_geometry


def test_r1_only_cursor_edges_restore_chrome(reader):
    reader = _loaded_reader(reader)
    reader._hide_chrome()

    top = reader.mapToGlobal(QPoint(200, 20))
    reader._last_cursor = top - QPoint(12, 0)
    with patch("app.ui.pages.reader_container.QCursor.pos", return_value=top):
        reader._poll_cursor()
    assert reader._chrome_visible is True

    reader._hide_chrome()
    middle = reader.mapToGlobal(QPoint(500, 400))
    reader._last_cursor = middle - QPoint(12, 0)
    with patch("app.ui.pages.reader_container.QCursor.pos", return_value=middle):
        reader._poll_cursor()
    assert reader._chrome_visible is False

    bottom = reader.mapToGlobal(QPoint(200, 780))
    reader._last_cursor = bottom - QPoint(12, 0)
    with patch("app.ui.pages.reader_container.QCursor.pos", return_value=bottom):
        reader._poll_cursor()
    assert reader._chrome_visible is True


def test_r1_autohide_blocked_by_sidebar_or_without_book(reader):
    reader._book_id = 1
    reader._book = {}
    reader._sidebar_visible = True
    reader._hide_chrome()
    assert reader._chrome_visible is True

    reader._sidebar_visible = False
    reader._book_id = None
    reader._hide_chrome()
    assert reader._chrome_visible is True

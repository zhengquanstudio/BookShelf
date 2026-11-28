"""T13：高亮荧光笔 4 色 —— 语义名存库、按纸面解析、老 hex 兼容。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.db.repositories.book_repo import BookRepository
from app.db.repositories.reading_repo import ReadingRepository
from app.reader.bridge import ReaderBridge
from app.services.settings_service import SettingsService
from app.ui.pages.reader_container import ReaderContainer
from app.ui.theme_tokens import (
    HIGHLIGHT_COLORS,
    HIGHLIGHT_LIGHT,
    HIGHLIGHT_NIGHT,
    normalize_highlight_name,
    resolve_highlight_color,
)


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


def _add_book(db, path) -> int:
    return BookRepository(db).create(
        file_path=str(path),
        quick_hash=path.stem,
        format=path.suffix.lstrip("."),
        title="测试书",
        author_raw="测试作者",
        status="ok",
    )


# ---- 纯函数：归一化与解析 ----
def test_four_semantic_colors_and_defaults():
    assert HIGHLIGHT_COLORS == ("blue", "amber", "green", "pink")
    assert normalize_highlight_name(None) == "blue"
    for name in HIGHLIGHT_COLORS:
        assert normalize_highlight_name(name) == name
        assert normalize_highlight_name(name.upper()) == name


def test_legacy_hex_maps_to_semantic_name():
    assert normalize_highlight_name("#ffe08a") == "amber"
    assert normalize_highlight_name("#b7e1a1") == "green"
    assert normalize_highlight_name("#a8d8f0") == "blue"
    assert normalize_highlight_name("#f5b7c4") == "pink"
    assert normalize_highlight_name("#f2c14e") == "amber"


def test_unknown_color_falls_back_to_blue():
    assert normalize_highlight_name("purple") == "blue"
    assert normalize_highlight_name("") == "blue"
    assert normalize_highlight_name(123) == "blue"


def test_resolve_light_uses_design_hex():
    assert resolve_highlight_color("blue", dark=False) == "#CFE3F3"
    assert resolve_highlight_color("amber", dark=False) == "#F5D9A8"
    assert resolve_highlight_color("green", dark=False) == "#D8E8C2"
    assert resolve_highlight_color("pink", dark=False) == "#ECCFD8"


def test_resolve_dark_uses_darkened_hex():
    assert resolve_highlight_color("blue", dark=True) == "#2C4257"
    assert resolve_highlight_color("amber", dark=True) == "#4A3B22"
    assert resolve_highlight_color("green", dark=True) == "#31412A"
    assert resolve_highlight_color("pink", dark=True) == "#45303A"


def test_resolve_unknown_falls_back_to_blue_palette():
    assert resolve_highlight_color("nope", dark=False) == HIGHLIGHT_LIGHT["blue"]
    assert resolve_highlight_color("nope", dark=True) == HIGHLIGHT_NIGHT["blue"]


# ---- 偏好默认值 ----
def test_prefs_default_highlight_color_is_blue(reader):
    assert reader._reader_prefs()["highlight_color"] == "blue"


def test_prefs_highlight_color_persists_name(reader, settings):
    settings.data["reader"]["highlight_color"] = "green"
    assert reader._reader_prefs()["highlight_color"] == "green"


def test_prefs_highlight_color_normalizes_legacy_hex(reader, settings):
    settings.data["reader"]["highlight_color"] = "#ffe08a"
    assert reader._reader_prefs()["highlight_color"] == "amber"


# ---- 落库归一化 ----
def test_bridge_stores_semantic_name_not_hex(qapp, db, tmp_path):
    book_id = _add_book(db, tmp_path / "hl.epub")
    bridge = ReaderBridge(db)
    bridge.addHighlight(book_id, '{"type":"epub","cfiRange":"x"}', "#ffe08a", "t", "")
    rows = ReadingRepository(db).list_bookmarks(book_id, kind="highlight")
    assert rows[0]["color"] == "amber"

    bridge.addHighlight(book_id, '{"type":"epub","cfiRange":"y"}', "pink", "t", "")
    rows = ReadingRepository(db).list_bookmarks(book_id, kind="highlight")
    assert {r["color"] for r in rows} == {"amber", "pink"}

    bridge.addHighlight(book_id, '{"type":"epub","cfiRange":"z"}', "purple", "t", "")
    rows = ReadingRepository(db).list_bookmarks(book_id, kind="highlight")
    assert any(r["color"] == "blue" for r in rows)


def test_saved_highlights_send_normalized_name(reader, db, tmp_path):
    book_id = _add_book(db, tmp_path / "saved.epub")
    ReadingRepository(db).add_bookmark(
        book_id,
        '{"type":"epub","cfiRange":"epubcfi(/6/4!/2/1)"}',
        text="t",
        color="#b7e1a1",
        kind="highlight",
    )
    reader._book_id = book_id
    marks = reader._saved_highlights()
    assert len(marks) == 1
    assert marks[0]["color"] == "green"

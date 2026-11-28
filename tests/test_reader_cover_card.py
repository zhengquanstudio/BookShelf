"""T9：阅读器侧栏封面卡（56×78 书封 + 书名/作者 + 进度 + 圆 i）。"""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.services.settings_service import SettingsService
from app.ui.pages.reader_container import ReaderContainer, _reader_qss
from app.ui.theme_tokens import palette_for
from app.ui.widgets.reader_cover_card import ReaderCoverCard


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


def test_qss_includes_cover_card_rules() -> None:
    qss = _reader_qss(palette_for("dark"))
    for token in (
        "#ReaderCoverCard",
        "#ReaderCoverTitle",
        "#ReaderCoverAuthor",
        "#ReaderCoverPill",
        "ReaderCoverProgress",
        "ReaderCoverInfo",
    ):
        assert token in qss


def test_cover_card_layout_and_defaults(qapp) -> None:
    card = ReaderCoverCard()
    assert card.objectName() == "ReaderCoverCard"
    assert (card.cover.width(), card.cover.height()) == (56, 78)
    assert card.percent_label.text() == "0%"
    assert card.progress_bar.maximum() == 1000
    assert card.status_pill.text() == "在读"


def test_cover_card_set_book_and_progress(qapp) -> None:
    card = ReaderCoverCard()
    card.set_book(
        {"title": "三体", "author_name": "刘慈欣", "publisher": "重庆出版社"}
    )
    assert card.title_label.text() == "三体"
    assert "刘慈欣" in card.author_label.text()
    assert "重庆出版社" in card.author_label.text()
    assert " · " in card.author_label.text()

    # 缺出版社时只显示作者，不出现多余分隔符。
    card.set_book({"title": "x", "author_raw": "A"})
    assert card.author_label.text() == "A"

    card.set_progress(0.42)
    assert card.progress_bar.value() == 420
    assert card.percent_label.text() == "42%"
    assert card.status_pill.text() == "在读"

    card.set_progress(1.0)
    assert card.status_pill.text() == "已读完"
    assert card.percent_label.text() == "100%"

    # 越界钳制。
    card.set_progress(-5)
    assert card.progress_bar.value() == 0
    card.set_progress(9)
    assert card.percent_label.text() == "100%"


def test_cover_card_info_button_emits_detail_requested(qapp) -> None:
    card = ReaderCoverCard()
    fired: list[int] = []
    card.detail_requested.connect(lambda: fired.append(1))
    card.info_button.click()
    assert fired == [1]


def test_cover_card_paints_with_palette(qapp) -> None:
    card = ReaderCoverCard()
    card.set_theme(palette_for("light"))
    card.set_book({"title": "测试"})
    pix = card.cover.grab()
    assert pix.width() == 56


def test_reader_wires_cover_card_from_location(reader) -> None:
    reader._book = {
        "title": "集成书",
        "author_name": "集成作者",
        "publisher": "集成社",
    }
    reader._book_id = 0
    reader._render_cover_thumb()
    assert reader.cover_card.title_label.text() == "集成书"
    assert "集成社" in reader.cover_card.author_label.text()

    reader._on_location(
        0,
        json.dumps(
            {
                "label": "序章",
                "href": "c1.xhtml",
                "page": 3,
                "total": 10,
                "percent": 0.3,
                "sectionSeconds": 0,
            }
        ),
    )
    assert reader.cover_card.percent_label.text() == "30%"

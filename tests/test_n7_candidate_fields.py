"""候选面板（N7）：匹配依据、待确认置顶、字段级勾选。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox

from app.services.metadata_service import MetadataService
from app.services.settings_service import SettingsService
from app.ui.dialogs.edit_book_dialog import EditBookDialog


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def _dialog(db, tmp_path) -> EditBookDialog:
    settings = SettingsService(tmp_path / "config.json")
    service = MetadataService(db, settings, sources=[])
    return EditBookDialog(db, settings, service=service)


def _high() -> dict:
    return {
        "source": "douban",
        "title": "红楼梦",
        "subtitle": "脂评汇校本",
        "authors": ["曹雪芹", "高鹗"],
        "isbn": "9787020002207",
        "publisher": "人民文学出版社",
        "date": "1982",
        "language": "zh",
        "series": "",
        "series_index": "",
        "description": "简介",
        "cover_url": "",
        "score": 96,
        "why": ["isbn:equal", "title:100", "author:hit", "source:douban"],
    }


def _pending() -> dict:
    return {
        "source": "kongfz",
        "title": "红楼梦",
        "authors": ["曹雪芹"],
        "isbn": "",
        "publisher": "某旧书店",
        "date": "1980",
        "score": 70,
        "why": ["title:100", "author:hit"],
    }


def test_default_fields_are_conservative_for_pending_candidates(db, tmp_path, qapp) -> None:
    dialog = _dialog(db, tmp_path)

    high = dialog._default_fields(_high())
    assert {"title", "authors", "isbn", "publisher"} <= high
    assert "description" not in high

    assert dialog._default_fields(_pending()) == {"title", "authors"}
    dialog.close()


def test_pending_candidate_is_pinned_and_rejected_hidden(db, tmp_path, qapp) -> None:
    dialog = _dialog(db, tmp_path)
    rejected = dict(_pending(), rejected="isbn:conflict", score=0)
    dialog._candidates = [_high(), _pending(), rejected]

    visible = dialog._visible_candidates()

    assert len(visible) == 2
    assert visible[0]["score"] == 70
    assert visible[1]["score"] == 96
    dialog.close()


def test_apply_only_checked_fields(db, tmp_path, qapp) -> None:
    dialog = _dialog(db, tmp_path)

    dialog._apply_candidate(_high(), fields={"title"})

    assert dialog._title.text() == "红楼梦"
    assert dialog._publisher.text() == ""
    assert dialog._isbn.text() == ""
    assert "勾选" in dialog._message.text()
    dialog.close()


def test_apply_with_no_checked_field_changes_nothing(db, tmp_path, qapp) -> None:
    dialog = _dialog(db, tmp_path)

    dialog._apply_candidate(_high(), fields=set())

    assert dialog._title.text() == ""
    assert dialog._publisher.text() == ""
    assert "未勾选" in dialog._message.text()
    dialog.close()


def test_result_card_renders_checkbox_per_field(db, tmp_path, qapp) -> None:
    dialog = _dialog(db, tmp_path)

    card = dialog._result_card(_high())
    boxes = card.findChildren(QCheckBox)

    labels = {box.text() for box in boxes}
    assert {"书名", "作者", "ISBN", "出版社", "简介"} <= labels
    assert len(boxes) == 8
    assert sum(1 for box in boxes if not box.isChecked()) == 1
    dialog.close()

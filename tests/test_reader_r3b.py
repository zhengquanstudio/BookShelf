"""R3b：详情浮层编辑九个字段，校验、保存链路与失败回滚。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from app.db.repositories.book_repo import BookRepository
from app.errors import OrganizeError
from app.services.normalization import normalize_book
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


def _add_book(db, tmp_path, **overrides):
    path = tmp_path / "source" / "old.epub"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * 256)
    fields = {
        "file_path": str(path),
        "quick_hash": "r3b",
        "format": "epub",
        "title": "旧书名",
        "author_raw": "旧作者",
        "publisher": "旧出版社",
        "publish_date": "2001",
        "language": "zh",
        "isbn": "9787532127320",
        "page_count": 100,
        "file_size": 256,
        "status": "ok",
    }
    fields.update(overrides)
    book_id = BookRepository(db).create(**fields)
    return book_id, path


def _open_editor(reader, db, book_id):
    normalize_book(db, book_id)
    row = db.query_one(
        "SELECT books.*, authors.name_zh AS author_name, authors.country AS country, "
        "series.name AS series_name FROM books "
        "LEFT JOIN authors ON authors.id = books.author_id "
        "LEFT JOIN series ON series.id = books.series_id WHERE books.id = ?",
        (book_id,),
    )
    reader._book_id = book_id
    reader._book = dict(row)
    reader._book_path = str(row["file_path"])
    reader._update_header()
    reader._show_book_detail()
    reader.detail_panel.begin_edit()


def test_r3b_edit_mode_prefills_and_toggles(reader, db, tmp_path):
    book_id, _path = _add_book(db, tmp_path)
    _open_editor(reader, db, book_id)
    panel = reader.detail_panel

    assert panel.is_editing()
    assert panel.view_container.isHidden()
    assert not panel.edit_container.isHidden()
    assert not panel.edit_actions.isHidden()
    assert panel.e_title.text() == "旧书名"
    assert panel.e_author.text() == "旧作者"
    assert panel.e_publisher.text() == "旧出版社"
    assert panel.e_pages.text() == "100"
    assert panel.e_isbn.text() == "9787532127320"

    panel.edit_cancel_button.click()
    assert not panel.is_editing()
    assert not panel.view_container.isHidden()
    assert panel.edit_actions.isHidden()


def test_r3b_save_updates_db_header_and_tags(reader, db, tmp_path):
    book_id, _path = _add_book(db, tmp_path)
    _open_editor(reader, db, book_id)
    panel = reader.detail_panel
    changed: list[int] = []
    reader.book_changed.connect(changed.append)

    panel.e_title.setText("新书名")
    panel.e_author.setText("新作者")
    panel.e_publisher.setText("新出版社")
    panel.e_date.setText("2020-05")
    panel.e_pages.setText("456")
    panel.e_language.setText("zh-CN")
    panel.e_isbn.setText("9787532127320")
    panel.e_series.setText("新系列")
    panel.e_tags.setText("小说，经典")
    panel.edit_save_button.click()

    row = db.query_one("SELECT * FROM books WHERE id = ?", (book_id,))
    assert row["title"] == "新书名"
    assert row["publisher"] == "新出版社"
    assert row["publish_date"] == "2020-05"
    assert row["page_count"] == 456
    assert row["language"] == "zh-CN"
    assert row["isbn"] == "9787532127320"
    author = db.query_one("SELECT name_zh FROM authors WHERE id = ?", (row["author_id"],))
    assert author["name_zh"] == "新作者"
    series = db.query_one("SELECT name FROM series WHERE id = ?", (row["series_id"],))
    assert series["name"] == "新系列"
    tags = [
        r["name"]
        for r in db.query(
            "SELECT t.name FROM tags t JOIN book_tags bt ON bt.tag_id = t.id "
            "WHERE bt.book_id = ? ORDER BY t.name",
            (book_id,),
        )
    ]
    assert tags == ["小说", "经典"]

    assert reader._book["title"] == "新书名"
    assert "新书名" in reader.window().windowTitle()
    assert not panel.is_editing()
    assert "已保存" in panel.status_label.text()
    assert changed == [book_id]


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    (
        ("e_title", "   ", "书名不能为空"),
        ("e_isbn", "12345", "ISBN"),
        ("e_pages", "abc", "页数"),
        ("e_pages", "0", "页数"),
    ),
)
def test_r3b_validation_rejects_and_keeps_data(
    reader, db, tmp_path, field, value, expected
):
    book_id, path = _add_book(db, tmp_path)
    _open_editor(reader, db, book_id)
    panel = reader.detail_panel
    getattr(panel, field).setText(value)
    panel.edit_save_button.click()

    assert expected in panel.status_label.text()
    assert panel.is_editing()
    row = db.query_one("SELECT title, isbn, page_count FROM books WHERE id = ?", (book_id,))
    assert row["title"] == "旧书名"
    assert row["isbn"] == "9787532127320"
    assert row["page_count"] == 100
    assert path.is_file()


def test_r3b_save_without_library_root_does_not_move(reader, db, tmp_path):
    book_id, path = _add_book(db, tmp_path)
    _open_editor(reader, db, book_id)
    panel = reader.detail_panel
    panel.e_title.setText("改名后")
    panel.edit_save_button.click()

    row = db.query_one("SELECT title, file_path FROM books WHERE id = ?", (book_id,))
    assert row["title"] == "改名后"
    assert row["file_path"] == str(path)
    assert path.is_file()
    assert "未设置书库根目录" in panel.status_label.text()


def test_r3b_save_moves_file_to_archive(reader, db, tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    reader.settings.data["library_root"] = str(library)
    reader.settings.data["naming"] = {
        **reader.settings.data.get("naming", {}),
        "author_dir_template": "{作者}",
        "file_template": "{作者} - {书名}.{扩展名}",
        "conflict_policy": "suffix",
    }
    reader.settings.save()

    book_id, old_path = _add_book(db, tmp_path)
    _open_editor(reader, db, book_id)
    panel = reader.detail_panel
    panel.e_title.setText("呐喊")
    panel.edit_save_button.click()

    row = db.query_one("SELECT title, file_path, status FROM books WHERE id = ?", (book_id,))
    new_path = Path(row["file_path"])
    assert row["title"] == "呐喊"
    assert new_path != old_path
    assert new_path.is_file()
    assert not old_path.exists()
    assert new_path.is_relative_to(library)
    assert "已归档" in panel.status_label.text()
    item = db.query_one(
        "SELECT action, result, source_path FROM library_items WHERE book_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (book_id,),
    )
    assert item["action"] == "move"
    assert item["result"] == "move"
    assert item["source_path"] == str(old_path)


def test_r3b_move_failure_rolls_back_metadata(reader, db, tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    reader.settings.data["library_root"] = str(library)
    reader.settings.data["naming"] = {
        **reader.settings.data.get("naming", {}),
        "author_dir_template": "{作者}",
        "file_template": "{作者} - {书名}.{扩展名}",
    }
    reader.settings.save()

    book_id, path = _add_book(db, tmp_path)
    _open_editor(reader, db, book_id)
    panel = reader.detail_panel
    panel.e_tags.setText("新标签")

    def refuse(*_args, **_kwargs):
        raise OrganizeError("文件被占用")

    monkeypatch.setattr(
        "app.services.organize_service.OrganizeService.execute", refuse
    )
    panel.e_title.setText("不应保留")
    panel.edit_save_button.click()

    row = db.query_one("SELECT title, file_path FROM books WHERE id = ?", (book_id,))
    assert row["title"] == "旧书名"
    assert row["file_path"] == str(path)
    assert path.is_file()
    tags = [
        r["name"]
        for r in db.query(
            "SELECT t.name FROM tags t JOIN book_tags bt ON bt.tag_id = t.id "
            "WHERE bt.book_id = ?",
            (book_id,),
        )
    ]
    assert tags == []
    assert "已回滚" in panel.status_label.text()
    assert "文件被占用" in panel.status_label.text()

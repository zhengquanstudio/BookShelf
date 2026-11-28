"""R3a：404px 只读详情、双路径、简介与安全的模板重算。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

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


@pytest.fixture(autouse=True)
def confirm_rename(monkeypatch):
    """定向测试默认确认预览，个别用例可再覆盖为取消。"""
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)


def _book_dict(**overrides):
    base = {
        "title": "我的书",
        "author_name": "某某",
        "publisher": "某出版社",
        "publish_date": "2020",
        "language": "zh-CN",
        "isbn": "9787000000000",
        "format": "epub",
        "file_path": r"C:\library\author\我的书.epub",
        "file_size": 2048,
        "page_count": 320,
        "series_name": "测试丛书",
        "volume": 2,
        "description": "第一行\n第二行\n第三行\n第四行\n第五行",
        "read_state": "reading",
        "favorite": 1,
    }
    base.update(overrides)
    return base


def test_r3a_overlay_matches_prototype(reader):
    assert reader.detail_panel.width() == 404
    assert reader.detail_panel.isHidden()
    assert reader.detail_panel.d_cover.width() == 96
    assert reader.detail_panel.d_cover.height() == 134
    assert reader.detail_panel.reveal_button.text() == "📂 打开文件夹"
    assert reader.detail_panel.rename_button.text() == "⟲ 按命名模板重算"
    assert not reader.detail_panel.translate_button.isEnabled()
    assert reader.detail_panel.edit_button.isEnabled()
    assert not reader.detail_panel.restore_button.isEnabled()


def test_r3a_show_populates_metadata(reader):
    reader._book_id = 1
    reader._book = _book_dict()
    reader._show_book_detail()

    panel = reader.detail_panel
    assert not panel.isHidden()
    assert panel.d_title.text() == "我的书"
    assert "某某" in panel.d_author.text()
    assert "某出版社" in panel.d_author.text()
    assert "2020" in panel.d_author.text()
    assert panel.d_isbn.text() == "9787000000000"
    assert panel.d_language.text() == "zh-CN"
    assert panel.d_pages.text() == "320 页"
    assert "在读" in panel.d_progress.text()
    assert "在读" in panel.d_tags.text()
    assert "★ 喜爱" in panel.d_tags.text()
    assert "2.0 KB" in panel.d_meta.text()
    assert "EPUB" in panel.d_meta.text()
    assert "无 DRM" in panel.d_meta.text()
    assert "测试丛书" in panel.d_series.text()
    assert "第 2 卷" in panel.d_series.text()
    assert panel.d_path.toolTip() == r"C:\library\author\我的书.epub"


def test_r3a_missing_fields_show_dash(reader):
    reader._book_id = 1
    reader._book = {"title": "", "file_path": ""}
    reader._show_book_detail()
    panel = reader.detail_panel
    assert panel.d_isbn.text() == "—"
    assert "标签：未读" == panel.d_tags.text()
    assert panel.d_path.toolTip() == "—"
    assert panel.d_archive_path.toolTip() == "—"


def test_r3a_book_tags_query(reader, db, tmp_path):
    path = tmp_path / "t.epub"
    path.write_text("x", encoding="utf-8")
    book_id = BookRepository(db).create(
        file_path=str(path), quick_hash="t", format="epub", title="T", status="ok"
    )
    db.execute("INSERT INTO tags(name) VALUES (?)", ("小说",))
    db.execute("INSERT INTO tags(name) VALUES (?)", ("经典",))
    tag_rows = db.query("SELECT id, name FROM tags ORDER BY name")
    for row in tag_rows:
        db.execute(
            "INSERT INTO book_tags(book_id, tag_id) VALUES (?, ?)",
            (book_id, row["id"]),
        )
    reader._book_id = book_id
    reader._book = _book_dict(file_path=str(path))
    reader._show_book_detail()
    assert "小说" in reader.detail_panel.d_tags.text()
    assert "经典" in reader.detail_panel.d_tags.text()


def test_r3a_all_detail_entries_toggle(reader):
    reader._book_id = 1
    reader._book = _book_dict()
    reader.cover_card.info_button.click()
    assert not reader.detail_panel.isHidden()
    reader.cover_card.info_button.click()
    assert reader.detail_panel.isHidden()

    reader.title_label.clicked.emit()
    assert not reader.detail_panel.isHidden()
    reader.title_label.clicked.emit()
    assert reader.detail_panel.isHidden()


def test_r3a_escape_and_close_button_hide_overlay(reader):
    reader._book_id = 1
    reader._book = _book_dict()
    reader._show_book_detail()
    reader._on_escape()
    assert reader.detail_panel.isHidden()

    reader._show_book_detail()
    reader.detail_panel.close_button.click()
    assert reader.detail_panel.isHidden()


def test_r3a_detail_blocks_chrome_autohide(reader):
    reader._book_id = 1
    reader._book = _book_dict()
    reader._sidebar_visible = False
    reader._show_book_detail()
    reader._hide_chrome()
    assert reader._chrome_visible is True

    reader._hide_book_detail()
    reader._hide_chrome()
    assert reader._chrome_visible is False


def test_r3a_description_expands_and_collapses(reader):
    reader._book_id = 1
    reader._book = _book_dict()
    reader._show_book_detail()
    panel = reader.detail_panel
    collapsed_height = panel.d_description.maximumHeight()
    panel.description_toggle.click()
    assert panel.description_toggle.text() == "收起"
    assert panel.d_description.maximumHeight() > collapsed_height
    panel.description_toggle.click()
    assert panel.description_toggle.text() == "展开"
    assert panel.d_description.maximumHeight() == collapsed_height


def test_r3a_reveal_button_opens_parent_folder(reader, tmp_path, monkeypatch):
    folder = tmp_path / "sub"
    folder.mkdir()
    reader._book_id = 1
    reader._book = _book_dict(file_path=str(folder / "book.epub"))
    reader._book_path = str(folder / "book.epub")
    reader._show_book_detail()

    called = {}

    def fake_open(url):
        called["url"] = url
        return True

    monkeypatch.setattr(
        "app.ui.pages.reader_container.QDesktopServices.openUrl", fake_open
    )
    reader.detail_panel.reveal_button.click()
    assert Path(called["url"].toLocalFile()) == folder


def _rename_book(reader, db, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    reader.settings.data["library_root"] = str(tmp_path / "library")
    reader.settings.data["source_dirs"] = [str(source)]
    reader.settings.data["naming"] = {
        **reader.settings.data.get("naming", {}),
        "file_template": "{作者} - {书名}{卷号} ({年份}).{扩展名}",
        "country_style": "short",
        "conflict_policy": "suffix",
    }
    reader.settings.save()
    old = source / "oldname.epub"
    old.write_bytes(b"x" * 128)
    book_id = BookRepository(db).create(
        file_path=str(old),
        quick_hash="h",
        format="epub",
        title="了不起的盖茨比",
        author_raw="F.S. Fitzgerald",
        publish_date="1925",
        file_size=128,
        status="ok",
    )
    from app.services.normalization import normalize_book

    normalize_book(db, book_id)
    db.execute(
        "UPDATE books SET volume = NULL, volume_raw = NULL WHERE id = ?", (book_id,)
    )
    reader._book_id = book_id
    reader._book = dict(db.query_one("SELECT * FROM books WHERE id = ?", (book_id,)))
    reader._book_path = str(old)
    return book_id, old


def test_r3a_rename_previews_and_recomputes_filename(reader, db, tmp_path, monkeypatch):
    book_id, old = _rename_book(reader, db, tmp_path)
    prompts = []

    def confirm(*args):
        prompts.append(args[2])
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    changed = []
    reader.book_changed.connect(changed.append)
    reader._show_book_detail()
    reader.detail_panel.rename_button.click()

    new_path = Path(BookRepository(db).get(book_id)["file_path"])
    assert len(prompts) == 1
    assert "原目录" in prompts[0]
    assert new_path != old
    assert new_path.parent == old.parent
    assert new_path.is_file()
    assert not old.exists()
    assert reader._book["file_path"] == str(new_path)
    assert reader._book_path == str(new_path)
    assert reader.detail_panel.d_path.toolTip() == str(new_path)
    assert changed == [book_id]


def test_r3a_rename_cancel_does_not_touch_file(reader, db, tmp_path, monkeypatch):
    book_id, old = _rename_book(reader, db, tmp_path)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.No)
    reader._show_book_detail()
    reader.detail_panel.rename_button.click()
    assert old.is_file()
    assert Path(BookRepository(db).get(book_id)["file_path"]) == old
    assert reader._book_path == str(old)

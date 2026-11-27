"""R3c：EPUB OPF 回写、备份、失败保留与阅读器集成。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest
from PySide6.QtWidgets import QApplication

from app.core.metadata.opf_write import backup_path, write_embedded_metadata
from app.db.repositories.book_repo import BookRepository
from app.errors import ExtractError
from app.services.normalization import normalize_book
from app.services.settings_service import SettingsService
from app.ui.pages.reader_container import ReaderContainer

CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

NAV = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><nav epub:type="toc"
xmlns:epub="http://www.idpf.org/2007/ops"><ol><li>第一章</li></ol></nav></body></html>
"""


def _opf(title: str = "旧书名", author: str = "旧作者") -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:publisher>旧出版社</dc:publisher>
    <dc:date>2001</dc:date>
    <dc:language>zh</dc:language>
    <dc:identifier id="bookid">urn:uuid:1234</dc:identifier>
    <meta property="schema:numberOfPages">100</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine/>
</package>
"""


def _make_epub(path: Path, *, title: str = "旧书名", author: str = "旧作者") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = zipfile.ZIP_STORED
        archive.writestr(mimetype, "application/epub+zip")
        archive.writestr("META-INF/container.xml", CONTAINER)
        archive.writestr("OEBPS/content.opf", _opf(title, author))
        archive.writestr("OEBPS/nav.xhtml", NAV)
    return path


def _read_opf(path: Path) -> ElementTree.Element:
    with zipfile.ZipFile(path) as archive:
        return ElementTree.fromstring(archive.read("OEBPS/content.opf"))


def _meta_text(root: ElementTree.Element, local: str) -> str:
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] == local:
            return (node.text or "").strip()
    return ""


def test_r3c_write_updates_dc_fields_and_page_count(tmp_path):
    path = _make_epub(tmp_path / "book.epub")
    original = path.read_bytes()

    backup = write_embedded_metadata(
        path,
        {
            "title": "新书名",
            "author": "新作者",
            "publisher": "新出版社",
            "publish_date": "2020-05",
            "language": "zh-CN",
            "isbn": "9787532127320",
        },
        page_count=456,
    )

    assert backup == backup_path(path)
    assert backup.read_bytes() == original
    root = _read_opf(path)
    assert _meta_text(root, "title") == "新书名"
    assert _meta_text(root, "creator") == "新作者"
    assert _meta_text(root, "publisher") == "新出版社"
    assert _meta_text(root, "date") == "2020-05"
    assert _meta_text(root, "language") == "zh-CN"
    assert _meta_text(root, "identifier") == "9787532127320"
    assert _meta_text(root, "meta") == "456"
    raw = path.read_bytes()
    assert b"dc:title" in raw
    assert b"ns0:" not in raw


def test_r3c_write_keeps_entry_order_and_compression(tmp_path):
    path = _make_epub(tmp_path / "book.epub")
    with zipfile.ZipFile(path) as before:
        names = before.namelist()
        nav = before.read("OEBPS/nav.xhtml")

    write_embedded_metadata(path, {"title": "只改书名"})

    with zipfile.ZipFile(path) as after:
        assert after.namelist() == names
        first = after.infolist()[0]
        assert first.filename == "mimetype"
        assert first.compress_type == zipfile.ZIP_STORED
        assert after.read("OEBPS/nav.xhtml") == nav
        assert after.read("mimetype") == b"application/epub+zip"


def test_r3c_write_missing_file_raises(tmp_path):
    with pytest.raises(ExtractError):
        write_embedded_metadata(tmp_path / "missing.epub", {"title": "x"})
    assert not backup_path(tmp_path / "missing.epub").exists()


def test_r3c_write_corrupt_epub_keeps_original(tmp_path):
    path = tmp_path / "broken.epub"
    path.write_bytes(b"not a zip")
    with pytest.raises((ExtractError, zipfile.BadZipFile)):
        write_embedded_metadata(path, {"title": "x"})
    assert path.read_bytes() == b"not a zip"
    assert backup_path(path).read_bytes() == b"not a zip"
    assert not list(tmp_path.glob(".*.tmp"))


def test_r3c_write_invalid_opf_keeps_original(tmp_path):
    path = tmp_path / "badopf.epub"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", CONTAINER)
        archive.writestr("OEBPS/content.opf", "<package><metadata>")
    original = path.read_bytes()
    with pytest.raises(ExtractError):
        write_embedded_metadata(path, {"title": "x"})
    assert path.read_bytes() == original
    assert backup_path(path).exists()


# ---- 阅读器集成 -----------------------------------------------------


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


def _add_book(db, path: Path, **overrides):
    fields = {
        "file_path": str(path),
        "quick_hash": "r3c",
        "format": "epub",
        "title": "旧书名",
        "author_raw": "旧作者",
        "file_size": path.stat().st_size if path.exists() else 0,
        "status": "ok",
    }
    fields.update(overrides)
    return BookRepository(db).create(**fields)


def _open_detail(reader, db, book_id):
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


def test_r3c_save_writes_opf_and_keeps_backup(reader, db, tmp_path):
    path = _make_epub(tmp_path / "book.epub")
    book_id = _add_book(db, path)
    _open_detail(reader, db, book_id)
    panel = reader.detail_panel
    panel.e_title.setText("新书名")
    panel.e_author.setText("新作者")
    panel.e_pages.setText("456")
    panel.edit_save_button.click()

    assert db.query_one("SELECT title FROM books WHERE id = ?", (book_id,))["title"] == "新书名"
    root = _read_opf(path)
    assert _meta_text(root, "title") == "新书名"
    assert _meta_text(root, "creator") == "新作者"
    assert _meta_text(root, "meta") == "456"
    assert backup_path(path).exists()
    assert "已写入 EPUB 内嵌元数据" in panel.status_label.text()


def test_r3c_save_writes_opf_after_move(reader, db, tmp_path):
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

    old_path = _make_epub(tmp_path / "source" / "book.epub")
    book_id = _add_book(db, old_path)
    _open_detail(reader, db, book_id)
    panel = reader.detail_panel
    panel.e_title.setText("呐喊")
    panel.edit_save_button.click()

    new_path = Path(
        db.query_one("SELECT file_path FROM books WHERE id = ?", (book_id,))["file_path"]
    )
    assert new_path != old_path
    assert new_path.is_relative_to(library)
    assert new_path.is_file()
    assert _meta_text(_read_opf(new_path), "title") == "呐喊"
    assert backup_path(new_path).exists()
    assert not backup_path(old_path).exists()


def test_r3c_opf_failure_reports_backup_without_rollback(reader, db, tmp_path):
    path = tmp_path / "broken.epub"
    path.write_bytes(b"not a zip")
    book_id = _add_book(db, path)
    _open_detail(reader, db, book_id)
    panel = reader.detail_panel
    panel.e_title.setText("仍然保存")
    panel.edit_save_button.click()

    assert db.query_one("SELECT title FROM books WHERE id = ?", (book_id,))["title"] == "仍然保存"
    assert "OPF 未写入" in panel.status_label.text()
    assert "已保留备份" in panel.status_label.text()
    assert backup_path(path).exists()


def test_r3c_non_epub_skips_opf_and_disables_restore(reader, db, tmp_path):
    path = tmp_path / "book.pdf"
    path.write_bytes(b"%PDF-1.4")
    book_id = _add_book(db, path, format="pdf", title="PDF 书")
    _open_detail(reader, db, book_id)
    panel = reader.detail_panel
    assert not panel.restore_button.isEnabled()
    panel.e_title.setText("PDF 新名")
    panel.edit_save_button.click()

    assert "不支持回写内嵌元数据" in panel.status_label.text()
    assert db.query_one("SELECT title FROM books WHERE id = ?", (book_id,))["title"] == "PDF 新名"
    assert path.read_bytes() == b"%PDF-1.4"


def test_r3c_restore_embedded_metadata(reader, db, tmp_path):
    path = _make_epub(tmp_path / "book.epub", title="内嵌书名")
    book_id = _add_book(db, path, title="手工书名")
    _open_detail(reader, db, book_id)
    panel = reader.detail_panel
    assert panel.restore_button.isEnabled()

    panel.restore_button.click()

    assert db.query_one("SELECT title FROM books WHERE id = ?", (book_id,))["title"] == "内嵌书名"
    assert reader._book["title"] == "内嵌书名"
    assert "已恢复" in panel.status_label.text()

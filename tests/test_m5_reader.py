"""M5 内嵌阅读器：格式准备、转换、桥与容器（不加载 WebEngine）。"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from pypdf import PdfWriter
from PySide6.QtWidgets import QApplication

from app.db.repositories.book_repo import BookRepository
from app.db.repositories.reading_repo import ReadingRepository
from app.reader import mobi
from app.reader.bridge import ReaderBridge
from app.reader.converter import convert_mobi, pdf_outline, prepare_book
from app.services.settings_service import SettingsService
from app.ui.pages.reader_container import ReaderContainer

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"


# ---- 测试用夹具构造 -------------------------------------------------
def make_epub(path: Path, *, drm: bool = False, chapters: int = 3) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        items = "".join(
            f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>'
            for i in range(1, chapters + 1)
        )
        spine = "".join(f'<itemref idref="c{i}"/>' for i in range(1, chapters + 1))
        archive.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
            'version="3.0" unique-identifier="id"><metadata '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">'
            "urn:test</dc:identifier><dc:title>测试书</dc:title>"
            "<dc:language>zh</dc:language></metadata><manifest>"
            f'<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
            f'properties="nav"/>{items}</manifest><spine>{spine}</spine></package>',
        )
        nav = "".join(
            f'<li><a href="c{i}.xhtml">第 {i} 章</a></li>'
            for i in range(1, chapters + 1)
        )
        archive.writestr(
            "OEBPS/nav.xhtml",
            '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops"><body><nav epub:type="toc">'
            f"<ol>{nav}</ol></nav></body></html>",
        )
        for i in range(1, chapters + 1):
            archive.writestr(
                f"OEBPS/c{i}.xhtml",
                '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml">'
                f"<body><h1>第 {i} 章</h1><p>这是第 {i} 章的正文内容。</p></body></html>",
            )
        if drm:
            archive.writestr(
                "META-INF/encryption.xml",
                '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                '<EncryptedData><CipherData><CipherReference URI="OEBPS/c1.xhtml"/>'
                "</CipherData></EncryptedData></encryption>",
            )
    return path


def make_pdf(path: Path, pages: int = 12) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    with path.open("wb") as stream:
        writer.write(stream)
    return path


def _palm_record(_unused_text: bytes, records: list[bytes]) -> bytes:
    header = bytearray(78)
    header[0:8] = b"TESTBOOK"
    header[60:64] = b"BOOK"
    header[64:68] = b"MOBI"
    header[76:78] = len(records).to_bytes(2, "big")
    offset = 78 + len(records) * 8 + 2
    table = bytearray()
    for record in records:
        table += offset.to_bytes(4, "big") + b"\x00\x00\x00\x00"
        offset += len(record)
    return bytes(header + table + b"\x00\x00") + b"".join(records)


def _mobi_record(
    text: bytes,
    *,
    encryption: int = 0,
    first_image: int = 0,
    exth: bytes = b"",
    flags: int = 0,
    title: str = "测试 MOBI",
) -> bytes:
    palm = bytearray(16)
    palm[0:2] = (1).to_bytes(2, "big")  # 不压缩
    palm[4:8] = len(text).to_bytes(4, "big")
    palm[8:10] = (1).to_bytes(2, "big")
    palm[10:12] = (4096).to_bytes(2, "big")
    palm[12:14] = encryption.to_bytes(2, "big")

    mobi_header = bytearray(232)
    mobi_header[0:4] = b"MOBI"
    mobi_header[4:8] = (232).to_bytes(4, "big")
    mobi_header[8:12] = (2).to_bytes(4, "big")
    mobi_header[12:16] = (65001).to_bytes(4, "big")
    encoded_title = title.encode("utf-8")
    name_offset = 16 + 232 + len(exth)
    mobi_header[68:72] = name_offset.to_bytes(4, "big")
    mobi_header[72:76] = len(encoded_title).to_bytes(4, "big")
    mobi_header[92:96] = first_image.to_bytes(4, "big")
    mobi_header[112:116] = flags.to_bytes(4, "big")
    return bytes(palm + mobi_header + exth + encoded_title)


def _exth(kind: int, payload: bytes) -> bytes:
    body = kind.to_bytes(4, "big") + (8 + len(payload)).to_bytes(4, "big") + payload
    return body


def make_mobi(path: Path, *, encryption: int = 0, image: bool = False) -> Path:
    text = (
        "<html><body><h1>第一章</h1><p>第一段文字</p>"
        '<img recindex="00001"/>'
        "<mbp:pagebreak/>"
        "<h1>第二章</h1><p>第二段文字</p></body></html>"
    ).encode("utf-8")
    record0 = _mobi_record(
        text, encryption=encryption, first_image=3 if image else 0
    )
    records = [record0, text]
    if image:
        records.append(b"\x00" * 8)  # 占位，保证图片记录序号为 3
    records.append(JPEG)
    path.write_bytes(_palm_record(text, records))
    return path


def make_azw3(path: Path) -> Path:
    stub = b"<html><body>stub</body></html>"
    kf8_text = (
        "<html><body><h1>KF8 第一章</h1><p>来自 AZW3 的正文</p>"
        "<mbp:pagebreak/><h1>KF8 第二章</h1><p>第二部分</p></body></html>"
    ).encode("utf-8")
    exth_body = _exth(121, (2).to_bytes(4, "big"))
    exth = (
        b"EXTH"
        + (12 + len(exth_body)).to_bytes(4, "big")
        + (1).to_bytes(4, "big")
        + exth_body
    )
    record0 = _mobi_record(stub, exth=exth, flags=0x40, title="AZW3 测试")
    kf8_record = _mobi_record(kf8_text, title="AZW3 测试")
    path.write_bytes(_palm_record(stub, [record0, stub, kf8_record, kf8_text]))
    return path


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture()
def settings(tmp_path):
    service = SettingsService(tmp_path / "config.json")
    return service


# ---- 格式准备 -------------------------------------------------------
def test_prepare_epub_ok(tmp_path):
    path = make_epub(tmp_path / "book.epub")
    prepared = prepare_book(path)
    assert prepared.ok and prepared.kind == "epub"
    assert prepared.path == path


def test_prepare_epub_drm(tmp_path):
    path = make_epub(tmp_path / "drm.epub", drm=True)
    prepared = prepare_book(path)
    assert prepared.drm and not prepared.ok
    assert "DRM" in prepared.error


def test_prepare_pdf_ok_and_outline(tmp_path):
    path = make_pdf(tmp_path / "book.pdf", pages=12)
    prepared = prepare_book(path)
    assert prepared.ok and prepared.kind == "pdf"
    outline = pdf_outline(path)
    assert outline["total"] == 12
    assert outline["items"][0]["label"] == "第 1-10 页"
    assert outline["items"][1]["page"] == 11


def test_prepare_unsupported(tmp_path):
    path = tmp_path / "book.txt"
    path.write_text("x", encoding="utf-8")
    prepared = prepare_book(path)
    assert not prepared.ok and "暂不支持" in prepared.error


def test_mobi_convert_and_reuse_cache(tmp_path):
    path = make_mobi(tmp_path / "book.mobi", image=True)
    converted_dir = tmp_path / "converted"
    prepared = prepare_book(path, converted_dir)
    assert prepared.ok and prepared.kind == "epub" and prepared.converted
    with zipfile.ZipFile(prepared.path) as archive:
        names = archive.namelist()
        assert names[0] == "mimetype"
        assert archive.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        nav = archive.read("OEBPS/nav.xhtml").decode("utf-8")
        assert "第二章" in nav
        chapter = archive.read("OEBPS/text/ch001.html").decode("utf-8")
        assert "../images/img00001.jpg" in chapter
        assert "OEBPS/images/img00001.jpg" in names
    again = convert_mobi(path, converted_dir)
    assert again == prepared.path


def test_mobi_drm(tmp_path):
    path = make_mobi(tmp_path / "drm.mobi", encryption=1)
    prepared = prepare_book(path, tmp_path / "converted")
    assert prepared.drm and "DRM" in prepared.error


def test_azw3_uses_kf8_section(tmp_path):
    path = make_azw3(tmp_path / "book.azw3")
    prepared = prepare_book(path, tmp_path / "converted")
    assert prepared.ok
    with zipfile.ZipFile(prepared.path) as archive:
        chapter = archive.read("OEBPS/text/ch001.html").decode("utf-8")
        assert "KF8 第一章" in chapter


def test_mobi_huff_unsupported(tmp_path):
    text = b"<html><body>x</body></html>"
    record0 = bytearray(_mobi_record(text))
    record0[0:2] = (17480).to_bytes(2, "big")
    path = tmp_path / "huff.mobi"
    path.write_bytes(_palm_record(text, [bytes(record0), text]))
    with pytest.raises(mobi.MobiError):
        mobi.parse(path)


# ---- 进度 / 书签 ----------------------------------------------------
def test_repository_progress_roundtrip(db, tmp_path):
    repo = ReadingRepository(db)
    book_id = _add_book(db, tmp_path / "progress.epub")
    repo.save_progress(book_id, '{"type":"pdf","page":5}', 0.25, seconds_delta=30)
    repo.save_progress(book_id, '{"type":"pdf","page":6}', 0.3, seconds_delta=15)
    row = repo.get_progress(book_id)
    assert json.loads(row["locator_json"])["page"] == 6
    assert abs(float(row["percent"]) - 0.3) < 1e-6
    assert int(row["total_seconds"]) == 45


def test_bridge_saves_progress_bookmark_and_highlight(qapp, db, tmp_path):
    book_id = _add_book(db, tmp_path / "bridge.epub")
    bridge = ReaderBridge(db)
    rendered: list[int] = []
    bridge.renderingFinished.connect(rendered.append)
    bridge.rendered(book_id)
    assert rendered == [book_id]
    bridge.saveProgress(book_id, '{"type":"epub","cfi":"epubcfi(/6/4)","page":3}', 0.12)
    bridge.flush()
    row = ReadingRepository(db).get_progress(book_id)
    assert json.loads(row["locator_json"])["page"] == 3

    bookmark_id = bridge.addBookmark(
        book_id, '{"type":"epub","cfi":"epubcfi(/6/4)"}', "第一章", ""
    )
    highlight_id = bridge.addHighlight(
        book_id,
        '{"type":"epub","cfiRange":"epubcfi(/6/4!/2/1)"}',
        "#ffe08a",
        "选中的文字",
        "笔记",
    )
    assert bookmark_id > 0 and highlight_id > 0
    rows = ReadingRepository(db).list_bookmarks(book_id)
    assert [row["kind"] for row in rows] == ["bookmark", "highlight"]
    assert rows[1]["note"] == "笔记"

    assert bridge.getProgress(book_id).startswith('{"type":"epub"')
    ReadingRepository(db).delete_bookmark(bookmark_id)
    assert len(ReadingRepository(db).list_bookmarks(book_id)) == 1


# ---- 阅读容器（无 WebEngine） ---------------------------------------
def _add_book(db, path: Path) -> int:
    return BookRepository(db).create(
        file_path=str(path),
        quick_hash=path.stem,
        format=path.suffix.lstrip("."),
        title="测试书",
        author_raw="测试作者",
        status="ok",
    )


def test_container_opens_epub_and_cycles_theme(qapp, db, tmp_path, settings):
    path = make_epub(tmp_path / "a.epub", chapters=4)
    book_id = _add_book(db, path)
    reader = ReaderContainer(db, settings, web_enabled=False)
    stages: list[tuple[str, int]] = []
    reader.loading_progress.connect(lambda stage, percent: stages.append((stage, percent)))
    assert reader.open_book(book_id) is True
    assert stages == [("探测格式", 10), ("载入 HTML", 65), ("渲染完成", 100)]
    assert reader.loading_stage_label.text() == "渲染完成"
    assert reader.external_button.text() == "用系统默认程序打开"
    assert reader._slow_timer.interval() == 10000
    reader._show_loading_overlay()
    reader._show_slow_loading()
    assert not reader.loading_slow_label.isHidden()
    assert "转换中，可稍候" in reader.loading_slow_label.text()
    assert reader.title_label.text().startswith("测试书")
    assert settings.data["reader"]["theme"] == "light"
    reader._cycle_theme()
    assert settings.data["reader"]["theme"] == "sepia"
    reader._change_font(1)
    assert settings.data["reader"]["font_size"] == 20
    reader.close_book()


def test_loading_keeps_web_visible_so_render_can_finish(qapp, db, settings):
    """载入阶段必须保持 WebEngine 可见，否则隐藏页面会被冻结并卡在 65%。"""
    reader = ReaderContainer(db, settings, web_enabled=False)
    reader._set_loading("载入 HTML", 65)
    assert reader.stack.currentWidget() is reader.web
    assert not reader.loading_overlay.isHidden()
    assert reader.loading_overlay.geometry() == reader._center.rect()
    reader._on_render_timeout()
    assert reader.stack.currentWidget() is reader.error_page
    assert "载入超时" in reader.error_reason.text()
    assert reader.loading_overlay.isHidden()


def test_render_watchdog_and_retry_button(qapp, db, tmp_path, settings):
    path = make_epub(tmp_path / "retry.epub", chapters=2)
    book_id = _add_book(db, path)
    reader = ReaderContainer(db, settings, web_enabled=False)
    assert reader._render_watchdog.interval() == 45000
    assert reader.retry_button.text() == "重试"
    reader.open_book(book_id)
    reader.close_book()
    assert not reader._render_watchdog.isActive()


def test_container_mobi_reports_conversion_stage(qapp, db, tmp_path, settings, monkeypatch):
    path = make_mobi(tmp_path / "stages.mobi")
    monkeypatch.setattr("app.reader.converter.config.CONVERTED_DIR", tmp_path / "converted")
    book_id = _add_book(db, path)
    reader = ReaderContainer(db, settings, web_enabled=False)
    stages: list[tuple[str, int]] = []
    reader.loading_progress.connect(lambda stage, percent: stages.append((stage, percent)))

    assert reader.open_book(book_id) is True
    assert stages == [
        ("探测格式", 10),
        ("转换格式", 35),
        ("载入 HTML", 65),
        ("渲染完成", 100),
    ]
    assert reader._prepared.converted
    reader.close_book()


def test_container_shows_error_for_drm(qapp, db, tmp_path, settings):
    path = make_epub(tmp_path / "drm.epub", drm=True)
    book_id = _add_book(db, path)
    reader = ReaderContainer(db, settings, web_enabled=False)
    assert reader.open_book(book_id) is False
    assert reader.stack.currentWidget() is reader.error_page
    assert "DRM" in reader.error_reason.text()
    row = db.query_one("SELECT status, drm_protected FROM books WHERE id = ?", (book_id,))
    assert row["status"] == "drm" and row["drm_protected"] == 1


def test_container_damage_error_and_system_open(qapp, db, tmp_path, settings, monkeypatch):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not a pdf")
    book_id = _add_book(db, path)
    reader = ReaderContainer(db, settings, web_enabled=False)
    opened: list[str] = []
    monkeypatch.setattr(
        "app.ui.pages.reader_container.QDesktopServices.openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )

    assert reader.open_book(book_id) is False
    assert "PDF 解析失败" in reader.error_reason.text()
    reader._open_external()
    assert len(opened) == 1 and Path(opened[0]) == path
    reader.close_book()


def test_container_pdf_toc_segments(qapp, db, tmp_path, settings):
    path = make_pdf(tmp_path / "b.pdf", pages=22)
    book_id = _add_book(db, path)
    reader = ReaderContainer(db, settings, web_enabled=False)
    assert reader.open_book(book_id) is True
    assert reader.toc_list.count() == 3
    assert reader.toc_list.item(0).data(0x0100) is not None
    reader.close_book()

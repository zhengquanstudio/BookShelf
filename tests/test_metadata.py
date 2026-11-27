"""元数据抽取测试：合成 EPUB/PDF/MOBI 样本，覆盖字段与异常边界。"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.core.metadata import extract_metadata

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000b49444154789c6360000000020001e221bc330000000049454e44ae"
    "426082"
)

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>测试之书</dc:title>
    <dc:creator opf:role="aut">张三</dc:creator>
    <dc:creator opf:role="aut">李四</dc:creator>
    <dc:identifier id="bid" opf:scheme="ISBN">978-7-536-69293-0</dc:identifier>
    <dc:publisher>测试出版社</dc:publisher>
    <dc:date>2020-05-01</dc:date>
    <dc:language>zh-CN</dc:language>
    <dc:description>这是简介。</dc:description>
    <meta name="calibre:series" content="测试系列"/>
    <meta name="calibre:series_index" content="3"/>
    <meta name="cover" content="cover-img"/>
  </metadata>
  <manifest>
    <item id="cover-img" href="images/cover.png" media-type="image/png"/>
    <item id="c1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>
"""


def _build_epub(path: Path, *, drm: bool = False) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", CONTAINER)
        archive.writestr("OEBPS/content.opf", OPF)
        archive.writestr("OEBPS/images/cover.png", PNG_1PX)
        archive.writestr("OEBPS/chap1.xhtml", "<html><body>章节</body></html>")
        if drm:
            archive.writestr(
                "META-INF/encryption.xml",
                '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                '<EncryptedData><CipherData><CipherReference URI="OEBPS/chap1.xhtml"/>'
                "</CipherData></EncryptedData></encryption>",
            )


def test_epub_embedded_metadata_and_cover(tmp_path):
    path = tmp_path / "book.epub"
    _build_epub(path)

    meta = extract_metadata(path)

    assert meta["ok"] is True
    assert meta["title"] == "测试之书"
    assert meta["authors"] == ["张三", "李四"]
    assert meta["isbn"] == "9787536692930"
    assert meta["publisher"] == "测试出版社"
    assert meta["date"] == "2020-05-01"
    assert meta["language"] == "zh-CN"
    assert meta["series"] == "测试系列"
    assert meta["series_index"] == "3"
    assert meta["description"] == "这是简介。"
    assert meta["cover_bytes"].startswith(b"\x89PNG")
    assert meta["drm"] is False


def test_epub_drm_is_detected(tmp_path):
    path = tmp_path / "drm.epub"
    _build_epub(path, drm=True)
    assert extract_metadata(path)["drm"] is True


def test_epub_broken_archive_returns_error(tmp_path):
    path = tmp_path / "broken.epub"
    path.write_bytes(b"not a zip")
    meta = extract_metadata(path)
    assert meta["ok"] is False
    assert "EPUB" in meta["reason"]


def test_pdf_metadata_and_page_count(tmp_path):
    from pypdf import PdfWriter

    path = tmp_path / "book.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_metadata(
        {
            "/Title": "PDF 测试书",
            "/Author": "王五",
            "/ISBN": "9787536692930",
            "/CreationDate": "D:20210102030405+08'00'",
        }
    )
    with path.open("wb") as handle:
        writer.write(handle)

    meta = extract_metadata(path)

    assert meta["ok"] is True
    assert meta["title"] == "PDF 测试书"
    assert meta["authors"] == ["王五"]
    assert meta["isbn"] == "9787536692930"
    assert meta["page_count"] == 1
    assert meta["date"] == "2021-01-02"
    assert meta["scanned"] is True


def test_pdf_broken_file_returns_error(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4 broken")
    meta = extract_metadata(path)
    assert meta["ok"] is False


def _exth(kind: int, payload: bytes) -> bytes:
    return kind.to_bytes(4, "big") + (8 + len(payload)).to_bytes(4, "big") + payload


def _build_mobi(path: Path, *, encryption: int = 0) -> None:
    records = (
        _exth(100, "王五".encode("utf-8"))
        + _exth(503, "MOBI 测试书".encode("utf-8"))
        + _exth(101, "某出版社".encode("utf-8"))
        + _exth(104, b"9787536692930")
    )
    exth = (
        b"EXTH"
        + (12 + len(records)).to_bytes(4, "big")
        + (4).to_bytes(4, "big")
        + records
    )
    mobi = bytearray(232)
    mobi[0:4] = b"MOBI"
    mobi[4:8] = (232).to_bytes(4, "big")
    mobi[8:12] = (2).to_bytes(4, "big")
    mobi[12:16] = (65001).to_bytes(4, "big")
    mobi[112:116] = (0x40).to_bytes(4, "big")
    palmdoc = bytearray(16)
    palmdoc[0:2] = (1).to_bytes(2, "big")
    palmdoc[12:14] = encryption.to_bytes(2, "big")
    record0 = bytes(palmdoc) + bytes(mobi) + exth

    header = bytearray(78)
    name = b"MOBI test"
    header[0 : len(name)] = name
    header[60:64] = b"BOOK"
    header[64:68] = b"MOBI"
    header[76:78] = (2).to_bytes(2, "big")
    base = 78 + 3 * 8
    offsets = (base, base + len(record0), base + len(record0) + 1)
    # 每条记录信息占 8 字节：4 字节偏移 + 1 字节属性 + 3 字节唯一 ID。
    body = b"".join(
        item.to_bytes(4, "big") + b"\x00\x00\x00\x00" for item in offsets
    )
    path.write_bytes(bytes(header) + body + record0 + b"x")


@pytest.mark.parametrize("suffix", [".mobi", ".azw3"])
def test_mobi_exth_metadata(tmp_path, suffix):
    path = tmp_path / f"book{suffix}"
    _build_mobi(path)

    meta = extract_metadata(path)

    assert meta["ok"] is True
    assert meta["title"] == "MOBI 测试书"
    assert meta["authors"] == ["王五"]
    assert meta["publisher"] == "某出版社"
    assert meta["isbn"] == "9787536692930"
    assert meta["drm"] is False


def test_mobi_drm_flag(tmp_path):
    path = tmp_path / "drm.mobi"
    _build_mobi(path, encryption=2)
    meta = extract_metadata(path)
    assert meta["ok"] is True
    assert meta["drm"] is True


def test_mobi_truncated_returns_error(tmp_path):
    path = tmp_path / "short.mobi"
    path.write_bytes(b"short")
    meta = extract_metadata(path)
    assert meta["ok"] is False


def test_unknown_extension_is_rejected(tmp_path):
    path = tmp_path / "book.txt"
    path.write_text("text", encoding="utf-8")
    meta = extract_metadata(path)
    assert meta["ok"] is False
    assert "不支持" in meta["reason"]

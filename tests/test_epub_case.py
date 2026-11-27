"""S1：EPUB 容器/条目名容错（大小写、NFC/NFD、百分号编码）。"""

from __future__ import annotations

import unicodedata
import zipfile
from pathlib import Path

from app.core.metadata import extract_metadata

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000b49444154789c6360000000020001e221bc330000000049454e44ae"
    "426082"
)

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="{opf}" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>容错之书</dc:title>
    <dc:creator>张三</dc:creator>
    <dc:identifier id="bid">9787536692930</dc:identifier>
    <dc:publisher>测试出版社</dc:publisher>
    <meta name="cover" content="cover-img"/>
  </metadata>
  <manifest>
    <item id="cover-img" href="images/cover.png" media-type="image/png"/>
    <item id="c1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>
"""


def _write_epub(
    path: Path,
    *,
    container_entry: str = "META-INF/container.xml",
    opf_declared: str = "OEBPS/content.opf",
    opf_entry: str | None = "OEBPS/content.opf",
    cover_entry: str = "OEBPS/images/cover.png",
    encryption_entry: str = "",
) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(container_entry, CONTAINER.format(opf=opf_declared))
        if opf_entry:
            archive.writestr(opf_entry, OPF)
            archive.writestr(cover_entry, PNG_1PX)
            archive.writestr(
                str(Path(opf_entry).parent / "chap1.xhtml").replace("\\", "/"),
                "<html><body>章节</body></html>",
            )
        if encryption_entry:
            archive.writestr(
                encryption_entry,
                '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                '<EncryptedData><CipherData><CipherReference URI="chap1.xhtml"/>'
                "</CipherData></EncryptedData></encryption>",
            )


def test_lowercase_container_and_opf_declaration(tmp_path):
    """container 写小写 ops/fb.opf，真实条目是 OPS/FB.OPF（15.6% 那批书）。"""
    path = tmp_path / "case.epub"
    _write_epub(
        path,
        container_entry="meta-inf/container.xml",
        opf_declared="ops/fb.opf",
        opf_entry="OPS/FB.OPF",
        cover_entry="OPS/Images/cover.png",
    )

    meta = extract_metadata(path)

    assert meta["ok"] is True
    assert meta["title"] == "容错之书"
    assert meta["authors"] == ["张三"]
    assert meta["isbn"] == "9787536692930"
    assert meta["publisher"] == "测试出版社"
    assert meta["cover_bytes"].startswith(b"\x89PNG")


def test_uppercase_container_entry(tmp_path):
    path = tmp_path / "upper.epub"
    _write_epub(path, container_entry="META-INF/CONTAINER.XML")

    meta = extract_metadata(path)

    assert meta["ok"] is True
    assert meta["title"] == "容错之书"


def test_nfd_declaration_matches_nfc_entry(tmp_path):
    """macOS 打包常见 NFD 文件名；声明写 NFD、条目是 NFC 也要命中。"""
    path = tmp_path / "nfd.epub"
    real = unicodedata.normalize("NFC", "OPS/café.opf")
    declared = unicodedata.normalize("NFD", "OPS/café.opf")
    assert real != declared
    _write_epub(
        path,
        opf_declared=declared,
        opf_entry=real,
        cover_entry="OPS/images/cover.png",
    )

    meta = extract_metadata(path)

    assert meta["ok"] is True
    assert meta["title"] == "容错之书"


def test_percent_encoded_declaration(tmp_path):
    path = tmp_path / "quoted.epub"
    _write_epub(
        path,
        opf_declared="OPS/my%20book.opf",
        opf_entry="OPS/my book.opf",
        cover_entry="OPS/images/cover.png",
    )

    meta = extract_metadata(path)

    assert meta["ok"] is True
    assert meta["title"] == "容错之书"


def test_encryption_entry_case_insensitive(tmp_path):
    path = tmp_path / "drm.epub"
    _write_epub(path, encryption_entry="meta-inf/encryption.xml")

    meta = extract_metadata(path)

    assert meta["ok"] is True
    assert meta["drm"] is True


def test_missing_opf_still_fails(tmp_path):
    path = tmp_path / "broken.epub"
    _write_epub(path, opf_declared="OPS/none.opf", opf_entry=None)

    meta = extract_metadata(path)

    assert meta["ok"] is False

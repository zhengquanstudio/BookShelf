"""内嵌元数据补强：EPUB 多作者分隔与 ISBN 形式、PDF 书签标题与 DOI。"""

from __future__ import annotations

import zipfile
from pathlib import Path

from app.core.metadata import extract_metadata

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _opf(creator: str, identifier: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>多作者之书</dc:title>
    <dc:creator>{creator}</dc:creator>
    <dc:identifier id="bid">{identifier}</dc:identifier>
    <dc:publisher>测试出版社</dc:publisher>
  </metadata>
  <manifest><item id="c1" href="chap1.xhtml" media-type="application/xhtml+xml"/></manifest>
  <spine><itemref idref="c1"/></spine>
</package>
"""


def _build_epub(path: Path, creator: str, identifier: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", CONTAINER)
        archive.writestr("OEBPS/content.opf", _opf(creator, identifier))
        archive.writestr("OEBPS/chap1.xhtml", "<html><body>章节</body></html>")


def test_epub_splits_multiple_creators(tmp_path) -> None:
    path = tmp_path / "multi.epub"
    _build_epub(path, "张三；李四、王五", "urn:isbn:978-7-536-69293-0")

    meta = extract_metadata(path)

    assert meta["authors"] == ["张三", "李四", "王五"]
    assert meta["isbn"] == "9787536692930"


def test_epub_accepts_isbn_prefix_identifier(tmp_path) -> None:
    path = tmp_path / "prefix.epub"
    _build_epub(path, "张三", "ISBN:9787536692930")

    assert extract_metadata(path)["isbn"] == "9787536692930"


def test_pdf_outline_supplies_title_when_info_missing(tmp_path) -> None:
    from pypdf import PdfWriter

    path = tmp_path / "outline.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_outline_item("书签里的书名", 0)
    with path.open("wb") as handle:
        writer.write(handle)

    meta = extract_metadata(path)

    assert meta["title"] == "书签里的书名"
    assert meta["page_count"] == 1


def test_pdf_extracts_doi_from_subject(tmp_path) -> None:
    from pypdf import PdfWriter

    path = tmp_path / "doi.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_metadata({"/Title": "带 DOI 的书", "/Subject": "doi:10.1000/xyz123"})
    with path.open("wb") as handle:
        writer.write(handle)

    meta = extract_metadata(path)

    assert meta["doi"] == "10.1000/xyz123"

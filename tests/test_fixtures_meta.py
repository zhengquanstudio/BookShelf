"""R0 固定失败样例：文件必须存在且基本结构可解析。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

FIXTURES = Path(__file__).with_name("fixtures")
DUPLICATE_NAMES = ("重复-文件名.epub", "重复-元数据.epub", "重复-完整书名.epub")


def test_required_fixtures_exist_and_parse() -> None:
    expected = {"书名.含.点.epub", "XX 全集 第Ⅰ卷.epub", "某书 卷一.pdf", *DUPLICATE_NAMES}
    assert expected <= {path.name for path in FIXTURES.iterdir() if path.is_file()}
    for name in expected - {"某书 卷一.pdf"}:
        with zipfile.ZipFile(FIXTURES / name) as archive:
            assert archive.testzip() is None
            assert archive.read("mimetype") == b"application/epub+zip"
            assert "OEBPS/content.opf" in archive.namelist()
    assert (FIXTURES / "某书 卷一.pdf").read_bytes().startswith(b"%PDF-")


def test_duplicate_epubs_have_identical_content() -> None:
    payloads = [(FIXTURES / name).read_bytes() for name in DUPLICATE_NAMES]
    assert payloads[0] == payloads[1] == payloads[2]


def test_chinese_author_country_fixture() -> None:
    data = json.loads((FIXTURES / "中文作者-法国国籍.json").read_text(encoding="utf-8"))
    assert data["authors"] == ["中文作者"]
    assert data["country"] == "法国"

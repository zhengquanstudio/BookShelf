"""L0 文件名解析（规范 N5）：畸形命名也要拆出书名/作者/年份/卷号。"""

from __future__ import annotations

import pytest

from app.core.filename_meta import parse_name


def test_author_dash_title_with_year() -> None:
    meta = parse_name("某作者 - 某书名 (2019)")
    assert meta["title"] == "某书名"
    assert meta["authors"] == ["某作者"]
    assert meta["year"] == "2019"


def test_book_mark_with_trailing_author() -> None:
    meta = parse_name("《红楼梦》曹雪芹")
    assert meta["title"] == "红楼梦"
    assert meta["authors"] == ["曹雪芹"]


def test_author_before_book_mark() -> None:
    meta = parse_name("曹雪芹《红楼梦》(1982)")
    assert meta["title"] == "红楼梦"
    assert meta["authors"] == ["曹雪芹"]
    assert meta["year"] == "1982"


def test_bracket_author_and_underscore_parts() -> None:
    meta = parse_name("[美]某某_书名(第2卷)_2019_扫描版")
    assert meta["authors"] == ["[美]某某"]
    assert "书名" in meta["title"]
    assert meta["series_index"] == "2"
    assert meta["year"] == "2019"


def test_parenthesised_volume() -> None:
    meta = parse_name("三体(第3卷)")
    assert meta["title"].startswith("三体")
    assert meta["series_index"] == "3"


def test_square_bracket_author_prefix() -> None:
    meta = parse_name("[作者] 书名")
    assert meta["authors"] == ["作者"]
    assert meta["title"] == "书名"


def test_lenticular_bracket_author_prefix() -> None:
    meta = parse_name("【作者】书名")
    assert meta["authors"] == ["作者"]
    assert meta["title"] == "书名"


def test_publisher_segment() -> None:
    meta = parse_name("某作者 - 某书名 - 人民文学出版社")
    assert meta["title"] == "某书名"
    assert meta["publisher"] == "人民文学出版社"


def test_isbn_is_extracted_and_removed_from_title() -> None:
    meta = parse_name("9787020002207 红楼梦")
    assert meta["isbn"] == "9787020002207"
    assert meta["title"] == "红楼梦"


def test_book_mark_only_has_no_author() -> None:
    meta = parse_name("《孤独小说家》")
    assert meta["title"] == "孤独小说家"
    assert meta["authors"] == []


def test_noise_tokens_are_stripped() -> None:
    meta = parse_name("[PDF]_某作者_-_某书名_[z-lib.org]")
    assert meta["title"] == "某书名"
    assert meta["authors"] == ["某作者"]


@pytest.mark.parametrize("stem", ["", "   ", "___"])
def test_empty_names_are_safe(stem: str) -> None:
    meta = parse_name(stem)
    assert meta["title"] == ""
    assert meta["authors"] == []

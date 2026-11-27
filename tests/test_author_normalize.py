"""F6 作者规范化验收用例。"""

from __future__ import annotations

from app.core import countries
from app.core.authors import normalize_author, split_authors


def test_fitzgerald_aliases() -> None:
    for raw in ("F. Scott Fitzgerald", "F.S. Fitzgerald", "Fitzgerald, F.S.", "菲茨杰拉德"):
        info = normalize_author(raw)
        assert info.name_zh == "菲茨杰拉德"
        assert info.country_code == "US"
        assert info.country == "美国"
        assert not info.is_chinese
        assert not info.needs_confirm


def test_fullwidth_parentheses_author() -> None:
    info = normalize_author("（美）埃利斯（Ellis,A.）")
    assert info.name_zh == "埃利斯"
    assert info.name_orig == "Ellis,A."
    assert info.country_code == "US"
    assert not info.needs_confirm


def test_comma_inside_parentheses_is_not_split() -> None:
    parts = split_authors("(美)埃利斯(Ellis, Albert)")
    assert parts == ["(美)埃利斯(Ellis, Albert)"]
    info = normalize_author(parts[0])
    assert info.name_zh == "埃利斯"
    assert info.name_orig == "Ellis, Albert"
    assert info.country_code == "US"
    assert not info.needs_confirm


def test_murakami_is_japanese() -> None:
    info = normalize_author("Haruki Murakami")
    assert info.name_zh == "村上春树"
    assert info.country_code == "JP"
    assert not info.is_chinese


def test_rowling() -> None:
    info = normalize_author("J. K. Rowling")
    assert info.name_zh == "J.K.罗琳"
    assert info.country_code == "GB"


def test_harari() -> None:
    info = normalize_author("Yuval Noah Harari")
    assert info.name_zh == "尤瓦尔·赫拉利"
    assert info.country_code == "IL"


def test_marquez() -> None:
    info = normalize_author("Gabriel Garcia Marquez")
    assert info.name_zh == "加西亚·马尔克斯"
    assert info.country_code == "CO"


def test_chinese_authors_have_no_country_in_name() -> None:
    assert normalize_author("钱钟书").is_chinese
    assert normalize_author("刘慈欣").is_chinese
    assert normalize_author("余华").country_code == "CN"


def test_alias_luxun() -> None:
    info = normalize_author("周树人")
    assert info.name_zh == "鲁迅"
    assert info.is_chinese


def test_unknown_foreign_needs_confirm() -> None:
    info = normalize_author("John Unknown Writer")
    assert info.name_zh == "John Unknown Writer"
    assert info.needs_confirm
    assert not info.is_chinese


def test_unknown_chinese_name() -> None:
    info = normalize_author("张三丰")
    assert info.name_zh == "张三丰"
    assert info.is_chinese
    assert not info.needs_confirm


def test_bracket_country_hint() -> None:
    info = normalize_author("Someone [美]")
    assert info.country_code == "US"
    assert info.name_zh == "Someone"


def test_leading_country_hint() -> None:
    info = normalize_author("[美] 卡尔·纽波特")
    assert info.country_code == "US"
    assert info.name_zh == "卡尔·纽波特"
    french = normalize_author("(法)勒洛尔")
    assert french.country_code == "FR"
    assert french.name_zh == "勒洛尔"


def test_trailing_latin_original_name() -> None:
    info = normalize_author("亚当·奥尔特(Adam Alter)")
    assert info.name_zh == "亚当·奥尔特"
    assert info.name_orig == "Adam Alter"
    assert not info.is_chinese


def test_unknown_cjk_has_no_country() -> None:
    info = normalize_author("一行禅师")
    assert info.is_chinese
    assert info.country_code == ""


def test_split_multiple_authors() -> None:
    assert split_authors("刘慈欣、王晋康") == ["刘慈欣", "王晋康"]
    assert split_authors("Fitzgerald, F.S.") == ["F.S. Fitzgerald"]


def test_country_render_styles() -> None:
    assert countries.render_country("US", "long") == "美国"
    assert countries.render_country("US", "short") == "美"
    assert countries.resolve_country("美国") == "US"
    assert countries.resolve_country("United States") == "US"

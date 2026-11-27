"""Windows 路径段与含点文件名回归。"""

from __future__ import annotations

import pytest

from app.core.naming import NamingRules, plan_target
from app.core.pathsafe import sanitize_segment


@pytest.mark.parametrize("name", ["CON", "PRN", "AUX", "NUL", "COM1", "COM9", "LPT1", "LPT9"])
def test_reserved_names_are_suffixed(name: str) -> None:
    assert sanitize_segment(name) == f"{name}_"
    assert sanitize_segment(f"{name}.epub") == f"{name}_.epub"


def test_illegal_characters_and_trailing_dot_space() -> None:
    assert sanitize_segment('作者/系列: 测试?"<>|') == "作者_系列_ 测试_____"
    assert sanitize_segment("文件夹.  ") == "文件夹"


def test_segment_is_utf8_byte_limited() -> None:
    value = sanitize_segment("书名" * 200)
    assert value
    assert len(value.encode("utf-8")) <= 255
    assert not value.endswith((" ", "."))


def _book(title: str, **extra) -> dict:
    return {
        "title": title,
        "author_name": "刘慈欣",
        "author_raw": "刘慈欣",
        "is_chinese": True,
        "format": "epub",
        "status": "ok",
        **extra,
    }


def test_dotted_title_preserved() -> None:
    rules = NamingRules(file_template="{书名}.{扩展名}")
    plan = plan_target(_book("书名.含.点"), rules)
    assert plan.target_name == "书名.含.点.epub"


def test_dotted_title_still_length_limited() -> None:
    rules = NamingRules(file_template="{书名}.{扩展名}", max_path_len=80)
    plan = plan_target(_book("前缀." + "长" * 200), rules)
    assert len(str(plan.target_path)) <= 80
    assert plan.target_name.startswith("前缀.")
    assert plan.target_name.endswith(".epub")

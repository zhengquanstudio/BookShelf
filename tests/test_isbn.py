"""ISBN 工具测试：合法、非法、连字符、10 位转换与全角数字。"""

from __future__ import annotations

import pytest

from app.core.isbn import find_isbns, is_valid, normalize


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("9787536692930", "9787536692930"),
        ("978-7-536-69293-0", "9787536692930"),
        ("ISBN 978-7-536-69293-0", "9787536692930"),
        ("ISBN13: 9780141182599", "9780141182599"),
        ("978 0 306 40615 7", "9780306406157"),
        ("９７８７５３６６９２９３０", "9787536692930"),
        ("0306406152", "9780306406157"),
        ("0-306-40615-2", "9780306406157"),
        ("0131103628", "9780131103627"),
        ("0201633612", "9780201633610"),
        ("0596007124", "9780596007126"),
        ("043942089X", "9780439420891"),
        ("0-439-42089-X", "9780439420891"),
        ("9791034303205", "9791034303205"),
        ("9787536692930 ", "9787536692930"),
    ],
)
def test_normalize_valid(raw, expected):
    assert normalize(raw) == expected
    assert is_valid(raw) is True


@pytest.mark.parametrize(
    "raw",
    [
        "",
        None,
        "abc",
        "9787536692931",
        "978753669293",
        "0306406153",
        "1234567890",
        "9781234567890",
        "9771234567890",
        "12345678901234",
    ],
)
def test_normalize_invalid(raw):
    assert normalize(raw) is None
    assert is_valid(raw) is False


def test_find_isbns_extracts_unique_in_order():
    text = (
        "书名页 ISBN 978-7-536-69293-0；封底又印 (ISBN13: 9780141182599)，"
        "重复一次 9787536692930。"
    )
    assert find_isbns(text) == ["9787536692930", "9780141182599"]


def test_find_isbns_handles_filename_and_fullwidth():
    assert find_isbns("书名_9787536692930.epub") == ["9787536692930"]
    assert find_isbns("ＩＳＢＮ　９７８－７－５３６－６９２９３－０") == ["9787536692930"]


def test_find_isbns_ignores_invalid_and_empty():
    assert find_isbns("") == []
    assert find_isbns("编号 1234567890 与 9787536692931") == []

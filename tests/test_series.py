"""F7 卷号与系列识别测试。"""

from __future__ import annotations

import pytest

from app.core.series import (
    chinese_to_int,
    extract_volume,
    similar_title,
    strip_volume,
    title_key,
    volume_text,
)
from app.db.repositories.book_repo import BookRepository
from app.services.author_service import AuthorService
from app.services.series_service import SeriesService


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("一", 1), ("十", 10), ("十五", 15), ("二十一", 21),
        ("一百", 100), ("一百二十三", 123), ("零", 0), ("3", 3),
    ],
)
def test_chinese_to_int(text: str, expected: int) -> None:
    assert chinese_to_int(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("第2卷", 2),
        ("第二部", 2),
        ("Vol.3", 3),
        ("book 5", 5),
        ("Vol. IV", 4),
        ("（三）", 3),
        ("(4)", 4),
        ("人类简史_vol1", 1),
        ("哈利波特_1", 1),
        ("三体3 死神永生", 3),
        ("三体1_final", 1),
    ],
)
def test_extract_volume(text: str, expected: int) -> None:
    match = extract_volume(text)
    assert match is not None
    assert match.volume == expected


def test_plain_title_has_no_volume() -> None:
    assert extract_volume("The Great Gatsby") is None
    assert extract_volume("1984") is None
    assert extract_volume("从0到1") is None
    assert extract_volume("三体2") is not None
    assert extract_volume("三体2").volume == 2


def test_strip_volume() -> None:
    assert strip_volume("三体3 死神永生") == "三体 死神永生"
    assert strip_volume("哈利波特_1") == "哈利波特"
    assert volume_text(4) == "第4卷"
    assert volume_text(4, "Vol.N") == "Vol.4"


def test_title_key_and_similarity() -> None:
    assert title_key("三体 第1卷") == title_key("三体1")
    assert similar_title("三体", "三体2") >= 90


def _book(repo: BookRepository, author_id: int, title: str, volume: int, index: int) -> int:
    return repo.create(
        file_path=f"C:/books/santi_{index}.epub",
        quick_hash=f"h{index}",
        format="epub",
        title=title,
        author_raw="刘慈欣",
        author_id=author_id,
        volume=volume,
        status="ok",
    )


def test_a10_three_volumes_become_one_series(db) -> None:
    author_id = AuthorService(db).ensure(AuthorService(db).resolve("刘慈欣"))
    repo = BookRepository(db)
    ids = [
        _book(repo, author_id, "三体", 1, 1),
        _book(repo, author_id, "三体", 2, 2),
        _book(repo, author_id, "三体", 3, 3),
    ]
    assigned = SeriesService(db).rebuild_for_author(author_id)
    assert assigned == 3
    rows = [repo.get(book_id) for book_id in ids]
    series_ids = {row["series_id"] for row in rows}
    assert len(series_ids) == 1 and None not in series_ids
    name = db.query_one("SELECT name FROM series WHERE id = ?", (series_ids.pop(),))["name"]
    assert name == "三体"


def test_different_titles_are_not_merged(db) -> None:
    author_id = AuthorService(db).ensure(AuthorService(db).resolve("刘慈欣"))
    repo = BookRepository(db)
    _book(repo, author_id, "三体", 1, 1)
    _book(repo, author_id, "球状闪电", 1, 2)
    SeriesService(db).rebuild_for_author(author_id)
    rows = db.query("SELECT series_id FROM books WHERE author_id = ?", (author_id,))
    assert all(row["series_id"] is None for row in rows)

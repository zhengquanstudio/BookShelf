"""R1-5/R1-6 卷号写法与系列名归一回归。"""

from __future__ import annotations

import pytest

from app.core.series import extract_volume, strip_volume, title_key, volume_text
from app.db.repositories.book_repo import BookRepository
from app.services.author_service import AuthorService
from app.services.series_service import SeriesService


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("XX 全集 第Ⅰ卷", 1),
        ("XX 第Ⅻ卷", 12),
        ("某书 卷一", 1),
        ("某书 第卷一", 1),
        ("某书 卷1", 1),
        ("Some Book Vol.1", 1),
        ("Some Book Volume 2", 2),
        ("某书 第３卷", 3),
        ("某书 卷４", 4),
        ("某书 第十一卷", 11),
        ("某书 第2册", 2),
        ("Some Book book 6", 6),
    ],
)
def test_volume_forms(text: str, expected: int) -> None:
    match = extract_volume(text)
    assert match is not None
    assert match.volume == expected
    assert volume_text(match.volume) == f"第{expected}卷"


def test_prefix_volume_is_not_left_in_series_name() -> None:
    assert strip_volume("某书 卷一") == "某书"
    assert title_key("某书 卷一") == "某书"


@pytest.mark.parametrize("name", ["《XX全集》", "《XX 套装》", "《XX（新译）》", "XX　合集"])
def test_series_suffix_normalization(name: str) -> None:
    assert title_key(name) == "xx"


def test_series_spellings_share_series_id(db) -> None:
    authors = AuthorService(db)
    author_id = authors.ensure(authors.resolve("测试作者"))
    books = BookRepository(db)
    ids = []
    for index, title in enumerate(("《XX全集》", "《XX 套装》", "《XX（新译）》"), 1):
        ids.append(books.create(
            file_path=f"C:/books/series-{index}.epub",
            quick_hash=f"series-{index}",
            format="epub",
            title=title,
            author_raw="测试作者",
            author_id=author_id,
            volume=index,
            status="ok",
        ))
    assert SeriesService(db).rebuild_for_author(author_id) == 3
    series_ids = {books.get(book_id)["series_id"] for book_id in ids}
    assert len(series_ids) == 1
    assert None not in series_ids

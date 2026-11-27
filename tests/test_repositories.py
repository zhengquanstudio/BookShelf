"""作者 / 系列 / 缓存 / 阅读进度仓储测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.repositories.author_repo import AuthorRepository
from app.db.repositories.book_repo import BookRepository
from app.db.repositories.cache_repo import CacheRepository
from app.db.repositories.reading_repo import ReadingRepository
from app.db.repositories.series_repo import SeriesRepository


def test_author_ensure_is_idempotent(db):
    repo = AuthorRepository(db)
    first = repo.ensure("菲茨杰拉德", name_orig="F. Scott Fitzgerald", country="美国")
    second = repo.ensure("菲茨杰拉德", name_orig="F. Scott Fitzgerald", country="美国")
    assert first == second
    assert repo.find("菲茨杰拉德", "F. Scott Fitzgerald", "美国")["id"] == first


def test_author_same_name_different_country(db):
    repo = AuthorRepository(db)
    cn = repo.ensure("张三", country="中国")
    us = repo.ensure("张三", country="美国")
    assert cn != us


def test_author_alias(db):
    repo = AuthorRepository(db)
    author_id = repo.ensure("鲁迅", country=None)
    repo.add_alias(author_id, "周树人")
    repo.add_alias(author_id, "周树人")  # 幂等
    row = repo.find_by_alias("周树人")
    assert row is not None and row["id"] == author_id


def test_series_and_volumes(db):
    authors = AuthorRepository(db)
    books = BookRepository(db)
    series = SeriesRepository(db)

    author_id = authors.ensure("刘慈欣", country=None)
    series_id = series.ensure("三体", author_id=author_id, total_volumes=3)
    assert series.ensure("三体", author_id=author_id) == series_id

    for volume in (2, 1, 3):
        books.create(
            file_path=rf"C:\books\santi{volume}.epub",
            quick_hash=f"s{volume}",
            format="epub",
            title=f"三体{volume}",
            author_id=author_id,
            series_id=series_id,
            volume=volume,
        )
    volumes = series.volumes(series_id)
    assert [row["volume"] for row in volumes] == [1, 2, 3]


def test_cache_roundtrip_and_expiry(db):
    cache = CacheRepository(db)
    cache.put("isbn:9780141182599", "openlibrary", {"title": "了不起的盖茨比"}, ttl_days=30)
    assert cache.get("isbn:9780141182599")["title"] == "了不起的盖茨比"

    future = datetime.now(timezone.utc) + timedelta(days=31)
    assert cache.get("isbn:9780141182599", now=future) is None
    assert cache.purge_expired(now=future) == 1
    assert cache.get("isbn:9780141182599") is None


def test_cache_put_twice_counts_hit(db):
    cache = CacheRepository(db)
    cache.put("q:三体", "googlebooks", {"items": []})
    cache.put("q:三体", "googlebooks", {"items": [1]})
    row = db.query_one("SELECT hit_count, payload_json FROM search_cache WHERE key='q:三体'")
    assert row["hit_count"] == 2
    assert "items" in row["payload_json"]


def test_reading_progress_accumulates(db):
    books = BookRepository(db)
    reading = ReadingRepository(db)
    book_id = books.create(file_path=r"C:\books\r.epub", quick_hash="r", format="epub")

    reading.save_progress(book_id, '{"cfi":"x"}', 10.0, seconds_delta=60)
    reading.save_progress(book_id, '{"cfi":"y"}', 25.5, seconds_delta=30)

    row = reading.get_progress(book_id)
    assert row["percent"] == pytest.approx(25.5)
    assert row["total_seconds"] == 90
    assert row["locator_json"] == '{"cfi":"y"}'


def test_bookmarks_and_highlights(db):
    books = BookRepository(db)
    reading = ReadingRepository(db)
    book_id = books.create(file_path=r"C:\books\b.epub", quick_hash="b", format="epub")

    reading.add_bookmark(book_id, '{"cfi":"1"}', chapter="第一章", text="摘录")
    reading.add_bookmark(
        book_id, "epubcfi(/6/2!/4/2,/1:0,/1:10)", text="高亮", color="#ffe08a", kind="highlight"
    )
    assert len(reading.list_bookmarks(book_id)) == 2
    assert len(reading.list_bookmarks(book_id, kind="highlight")) == 1

    bookmark_id = reading.list_bookmarks(book_id)[0]["id"]
    assert reading.delete_bookmark(bookmark_id) == 1
    assert len(reading.list_bookmarks(book_id)) == 1

"""F5 打分、缓存与离线降级测试（不访问真实网络）。"""

from __future__ import annotations

from app.db.repositories.book_repo import BookRepository
from app.net.client import NetworkError
from app.net.scoring import rank_candidates, score_candidate
from app.services.metadata_service import MetadataService

SETTINGS = {
    "meta": {"enable_network": True, "confidence_auto": 85, "confidence_confirm": 60},
    "sources": {"cache_ttl_days": 30, "daily_limit": 500, "rate_limit_ms": 0},
}


class FakeSource:
    def __init__(self, items: list[dict] | None = None, *, fail: bool = False) -> None:
        self.name = "fake"
        self.items = items or []
        self.fail = fail
        self.isbn_calls = 0
        self.search_calls = 0

    def by_isbn(self, isbn: str) -> list[dict]:
        self.isbn_calls += 1
        if self.fail:
            raise NetworkError("offline")
        return list(self.items)

    def search(self, query: str) -> list[dict]:
        self.search_calls += 1
        if self.fail:
            raise NetworkError("offline")
        return list(self.items)


def _candidate() -> dict:
    return {
        "source": "fake",
        "title": "了不起的盖茨比",
        "authors": ["F. Scott Fitzgerald"],
        "isbn": "9787020002207",
        "publisher": "人民文学出版社",
        "date": "2004",
        "language": "en",
        "series": "",
        "series_index": "",
        "cover_url": "",
    }


def _book(repo: BookRepository, **extra) -> int:
    data = {
        "file_path": "C:/books/gatsby.epub",
        "quick_hash": "g",
        "format": "epub",
        "title": "了不起的盖茨比",
        "author_raw": "F. Scott Fitzgerald",
        "isbn": "9787020002207",
        "status": "partial",
    }
    data.update(extra)
    return repo.create(**data)


def test_score_exact_match_is_high() -> None:
    book = {
        "title": "了不起的盖茨比",
        "author_raw": "F. Scott Fitzgerald",
        "isbn": "9787020002207",
        "language": "en",
    }
    assert score_candidate(_candidate(), book) >= 90


def test_rank_orders_by_score() -> None:
    book = {"title": "了不起的盖茨比", "author_raw": "F. Scott Fitzgerald"}
    low = dict(_candidate(), title="完全无关", authors=[])
    ranked = rank_candidates([low, _candidate()], book)
    assert ranked[0]["title"] == "了不起的盖茨比"
    assert ranked[0]["score"] >= ranked[1]["score"]


def test_cache_avoids_second_request(db) -> None:
    repo = BookRepository(db)
    book_id = _book(repo)
    source = FakeSource([_candidate()])
    service = MetadataService(db, SETTINGS, sources=[source])
    first = service.find_candidates(repo.get(book_id))
    second = service.find_candidates(repo.get(book_id))
    assert first and second
    assert source.isbn_calls == 1
    assert source.search_calls == 0


def test_offline_degrades_without_exception(db) -> None:
    repo = BookRepository(db)
    book_id = _book(repo, title="未知书名", author_raw="", isbn="")
    service = MetadataService(db, SETTINGS, sources=[FakeSource(fail=True)])
    assert service.find_candidates(repo.get(book_id)) == []
    result = service.enrich_book(book_id)
    assert result["status"] == "partial"
    assert "网络" in result["message"]


def test_enrich_applies_candidate(db) -> None:
    repo = BookRepository(db)
    book_id = _book(repo, publisher="")
    service = MetadataService(db, SETTINGS, sources=[FakeSource([_candidate()])])
    result = service.enrich_book(book_id, force=True)
    assert result["status"] == "ok"
    row = repo.get(book_id)
    assert row["publisher"] == "人民文学出版社"
    assert row["publish_date"] == "2004"
    assert result["candidates"][0]["score"] >= 85

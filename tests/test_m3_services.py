"""M3 作者/系列/补全服务集成测试。"""

from __future__ import annotations

from app.db.repositories.book_repo import BookRepository
from app.services.metadata_service import MetadataService
from app.services.normalization import normalize_book, normalize_library
from app.services.series_service import SeriesService

SETTINGS = {
    "meta": {"enable_network": False, "confidence_auto": 85, "confidence_confirm": 60},
    "sources": {"cache_ttl_days": 30},
    "naming": {"author_dir_template": "{作者} [{国家}]", "file_template": "{作者} [{国家}] - {书名}.{扩展名}"},
}


def _book(repo: BookRepository, index: int = 1, **extra) -> int:
    data = {
        "file_path": f"C:/books/book_{index}.epub",
        "quick_hash": f"h{index}",
        "format": "epub",
        "title": "了不起的盖茨比",
        "author_raw": "F.S. Fitzgerald",
        "status": "pending",
    }
    data.update(extra)
    return repo.create(**data)


def test_normalize_book_assigns_author_and_country(db) -> None:
    repo = BookRepository(db)
    book_id = _book(repo)
    row = normalize_book(db, book_id)
    assert row["author_id"] is not None
    author = db.query_one("SELECT * FROM authors WHERE id = ?", (row["author_id"],))
    assert author["name_zh"] == "菲茨杰拉德"
    assert author["country_code"] == "US"


def test_manual_save_locks_author_and_reuses_it(db) -> None:
    repo = BookRepository(db)
    book_id = _book(repo)
    service = MetadataService(db, SETTINGS)
    service.save_manual(
        book_id,
        {"title": "了不起的盖茨比", "author_raw": "F.S. Fitzgerald", "publisher": "人民文学出版社"},
    )
    author = db.query_one(
        "SELECT a.* FROM authors AS a JOIN books AS b ON b.author_id = a.id WHERE b.id = ?",
        (book_id,),
    )
    assert author["locked"] == 1

    second = _book(repo, index=2, title="夜色温柔", author_raw="F. Scott Fitzgerald")
    normalize_book(db, second)
    count = db.query_one("SELECT COUNT(*) AS n FROM authors")["n"]
    assert count == 1
    row = repo.get(second)
    assert row["author_id"] == author["id"]


def test_save_manual_writes_series_and_volume(db) -> None:
    repo = BookRepository(db)
    book_id = _book(repo, title="三体", author_raw="刘慈欣")
    MetadataService(db, SETTINGS).save_manual(
        book_id,
        {"title": "三体", "author_raw": "刘慈欣", "series": "三体三部曲", "volume": 2,
         "series_index": 2},
    )
    row = repo.get(book_id)
    assert row["volume"] == 2
    series_row = db.query_one("SELECT name FROM series WHERE id = ?", (row["series_id"],))
    assert series_row["name"] == "三体三部曲"


def test_normalize_library_backfills_existing_books(db) -> None:
    repo = BookRepository(db)
    _book(repo, 1)
    _book(repo, 2, title="夜色温柔", author_raw="F. Scott Fitzgerald")
    summary = normalize_library(db)
    assert summary["books"] == 2
    rows = db.query("SELECT author_id FROM books")
    assert all(row["author_id"] is not None for row in rows)


def test_series_rebuild_groups_three_volumes(db) -> None:
    repo = BookRepository(db)
    ids = [
        _book(repo, 1, title="三体", author_raw="刘慈欣", volume=1),
        _book(repo, 2, title="三体", author_raw="刘慈欣", volume=2),
        _book(repo, 3, title="三体", author_raw="刘慈欣", volume=3),
    ]
    normalize_library(db)
    SeriesService(db).rebuild_all()
    rows = [repo.get(book_id) for book_id in ids]
    assert len({row["series_id"] for row in rows}) == 1

"""数据库层测试：建表、CRUD、分页、事务回滚。"""

from __future__ import annotations

import pytest

from app.db.migrate import SCHEMA_VERSION
from app.db.repositories.book_repo import BookRepository


def test_migrate_creates_all_tables(db):
    rows = db.query("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row["name"] for row in rows}
    expected = {
        "schema_version",
        "authors",
        "series",
        "books",
        "library_items",
        "search_cache",
        "tags",
        "book_tags",
        "reading_state",
        "bookmarks",
        "task_log",
        "app_settings",
    }
    assert expected <= names


def test_schema_version_is_recorded(db):
    row = db.query_one("SELECT MAX(ver) AS ver FROM schema_version")
    assert row is not None and row["ver"] == SCHEMA_VERSION


def test_v1_database_migrates_batch_column(tmp_path):
    import sqlite3

    from app.db.connection import Database
    from app.db.migrate import init_database

    path = tmp_path / "v1.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE schema_version (ver INTEGER PRIMARY KEY, applied_at TEXT);"
        "INSERT INTO schema_version(ver) VALUES (1);"
        "CREATE TABLE library_items (id INTEGER PRIMARY KEY, book_id INTEGER,"
        " target_dir TEXT, target_name TEXT, target_path TEXT, action TEXT,"
        " result TEXT, message TEXT, created_at TEXT);"
    )
    conn.commit()
    conn.close()

    db = Database(path)
    try:
        init_database(db)
        columns = {row["name"] for row in db.query("PRAGMA table_info(library_items)")}
        assert "batch_id" in columns
        assert db.query_one("SELECT MAX(ver) AS ver FROM schema_version")["ver"] == SCHEMA_VERSION
    finally:
        db.close()


def test_book_crud(db):
    repo = BookRepository(db)
    book_id = repo.create(
        file_path=r"C:\books\test.epub",
        quick_hash="abc",
        format="epub",
        title="测试书",
        author_raw="某人",
    )
    row = repo.get(book_id)
    assert row is not None
    assert row["title"] == "测试书"
    assert row["status"] == "pending"

    repo.update(book_id, title="新书名", confidence=88.5)
    assert repo.get(book_id)["title"] == "新书名"
    assert repo.find_by_path(r"C:\books\test.epub")["id"] == book_id

    repo.set_status(book_id, "ok")
    assert repo.get(book_id)["status"] == "ok"

    assert repo.delete(book_id) == 1
    assert repo.get(book_id) is None


def test_book_path_is_unique(db):
    repo = BookRepository(db)
    repo.create(file_path=r"C:\books\a.epub", quick_hash="x")
    with pytest.raises(ValueError):
        repo.create(file_path=r"C:\books\a.epub", quick_hash="y")


def test_pagination_and_filters(db):
    repo = BookRepository(db)
    for index in range(120):
        repo.create(
            file_path=rf"C:\books\{index}.epub",
            quick_hash=f"h{index}",
            format="epub" if index % 2 == 0 else "pdf",
            title=f"书名{index:03d}",
            status="ok" if index < 60 else "pending",
        )

    assert repo.count() == 120
    assert repo.count(status="ok") == 60
    assert repo.count(formats=["pdf"]) == 60

    page3 = repo.list(page=3, page_size=50)
    assert len(page3) == 20

    found = repo.list(search="书名00")
    assert len(found) == 10

    stats = repo.count_by_status()
    assert stats["ok"] == 60
    assert stats["pending"] == 60


def test_transaction_rollback(db):
    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO books(file_path, quick_hash, format, status) "
                "VALUES ('C:/x.epub', 'h', 'epub', 'pending')"
            )
            raise RuntimeError("模拟失败")
    assert db.query_one("SELECT COUNT(*) AS n FROM books")["n"] == 0


def test_duplicates_grouping(db):
    repo = BookRepository(db)
    repo.create(file_path=r"C:\books\a.epub", quick_hash="same")
    repo.create(file_path=r"C:\books\b.epub", quick_hash="same")
    repo.create(file_path=r"C:\books\c.epub", quick_hash="other")
    groups = repo.duplicates()
    assert len(groups) == 1
    assert groups[0]["quick_hash"] == "same"
    assert groups[0]["n"] == 2

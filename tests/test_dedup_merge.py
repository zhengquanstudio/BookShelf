"""R1-1 重复内容元数据合并与扫描顺序回归。"""

from __future__ import annotations

from pathlib import Path

from app.core.scanner import ScannedFile
from app.db.repositories.book_repo import SOURCE_RANK, BookRepository
from app.services.scan_service import process_scan_file


def _book(repo: BookRepository, path: str) -> int:
    return repo.create(
        file_path=path,
        quick_hash="same",
        format="epub",
        title="原始书名",
        author_raw="保留作者",
        isbn="9787000000001",
        meta_source="embedded",
    )


def test_duplicate_keeps_existing_author(db) -> None:
    repo = BookRepository(db)
    book_id = _book(repo, "C:/books/a.epub")
    repo.merge_meta(book_id, {"title": "文件名", "author_raw": ""}, SOURCE_RANK["embedded"])
    row = repo.get(book_id)
    assert row["author_raw"] == "保留作者"
    assert row["title"] == "原始书名"


def test_duplicate_keeps_isbn(db) -> None:
    repo = BookRepository(db)
    book_id = _book(repo, "C:/books/a.epub")
    repo.merge_meta(book_id, {"isbn": None, "publisher": "新出版社"}, SOURCE_RANK["embedded"])
    row = repo.get(book_id)
    assert row["isbn"] == "9787000000001"
    assert row["publisher"] == "新出版社"


def test_order_independent(db) -> None:
    repo = BookRepository(db)
    incoming = [
        {"title": "短书名", "author_raw": "内嵌作者"},
        {"title": "完整书名：副标题", "author_raw": "手填作者", "isbn": "9787000000002"},
    ]
    results = []
    for index, sequence in enumerate((incoming, list(reversed(incoming)))):
        book_id = _book(repo, f"C:/books/order-{index}.epub")
        for fields in sequence:
            rank = SOURCE_RANK["manual"] if fields.get("isbn") else SOURCE_RANK["embedded"]
            repo.merge_meta(book_id, fields, rank)
        row = repo.get(book_id)
        results.append((row["title"], row["author_raw"], row["isbn"], row["meta_source"]))
    assert results[0] == results[1]
    assert results[0] == ("完整书名：副标题", "手填作者", "9787000000002", "manual")


def test_manual_source_wins(db) -> None:
    repo = BookRepository(db)
    book_id = _book(repo, "C:/books/a.epub")
    repo.merge_meta(book_id, {"title": "手填书名", "author_raw": "手填作者"}, SOURCE_RANK["manual"])
    repo.merge_meta(
        book_id,
        {"title": "内嵌书名：更长的副标题", "author_raw": "内嵌作者", "isbn": "9787000000003"},
        SOURCE_RANK["embedded"],
    )
    row = repo.get(book_id)
    assert row["title"] == "手填书名"
    assert row["author_raw"] == "手填作者"
    assert row["isbn"] == "9787000000001"


def _candidate(path: Path) -> ScannedFile:
    stat = path.stat()
    return ScannedFile(path, path.suffix.lstrip("."), stat.st_size, stat.st_mtime, False)


def test_duplicate_rescan_preserves_manual_row(db, tmp_path, monkeypatch) -> None:
    first = tmp_path / "first.epub"
    second = tmp_path / "second.epub"
    first.write_bytes(b"same-content" * 100)
    second.write_bytes(first.read_bytes())
    monkeypatch.setattr(
        "app.services.scan_service.extract_metadata",
        lambda _path: {"title": "内嵌书名", "authors": ["内嵌作者"], "ok": True, "cover_bytes": b""},
    )
    repo = BookRepository(db)
    process_scan_file(db, _candidate(first))
    duplicate = process_scan_file(db, _candidate(second))
    repo.update(
        duplicate["book_id"],
        title="手工标题",
        author_raw="手工作者",
        isbn="9787000000004",
        meta_source="manual",
    )

    process_scan_file(db, _candidate(second), incremental=False)
    row = repo.get(duplicate["book_id"])
    assert row["title"] == "手工标题"
    assert row["author_raw"] == "手工作者"
    assert row["isbn"] == "9787000000004"
    assert row["meta_source"] == "manual"
    assert row["dup_of"] == row["dup_group_id"]

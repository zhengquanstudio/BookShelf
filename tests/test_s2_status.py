"""S2：识别状态语义（ok/partial/failed）、状态值迁移与批量重识别。"""

from __future__ import annotations

import time
from pathlib import Path

from app.core.metadata.normalize import finalize
from app.core.scanner import ScannedFile
from app.db.migrate import init_database
from app.db.repositories.book_repo import BookRepository
from app.services.library_service import LibraryService
from app.services.metadata_service import MetadataService
from app.services.scan_service import process_scan_file
from app.workers.metadata_worker import EnrichWorker

SETTINGS = {
    "meta": {"enable_network": True, "confidence_auto": 85, "confidence_confirm": 60},
    "sources": {"cache_ttl_days": 30, "daily_limit": 500, "rate_limit_ms": 0},
}


def _candidate_file(path: Path) -> ScannedFile:
    stat = path.stat()
    return ScannedFile(
        path=path,
        format=path.suffix.lower().lstrip("."),
        size=stat.st_size,
        mtime=stat.st_mtime,
        too_small=False,
    )


class FakeSource:
    def __init__(self, items: list[dict] | None = None) -> None:
        self.name = "fake"
        self.items = items or []
        self.isbn_calls = 0
        self.search_calls = 0

    def by_isbn(self, isbn: str) -> list[dict]:
        self.isbn_calls += 1
        return list(self.items)

    def search(self, query: str) -> list[dict]:
        self.search_calls += 1
        return list(self.items)


def _net_candidate() -> dict:
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


# ---- 状态三分 -----------------------------------------------------

def test_embedded_failure_with_filename_goes_partial(db, tmp_path, monkeypatch) -> None:
    """内嵌解析失败但文件名能解析出书名/作者 → partial，不再一律 failed。"""
    path = tmp_path / "余华 - 活着 (1993).epub"
    path.write_bytes(b"broken" * 100)
    monkeypatch.setattr(
        "app.services.scan_service.extract_metadata",
        lambda _path: finalize({}, ok=False, reason="container 损坏"),
    )
    result = process_scan_file(db, _candidate_file(path))
    row = BookRepository(db).get(result["book_id"])
    assert row["status"] == "partial"
    assert row["title"] == "活着"
    assert row["author_raw"] == "余华"


def test_embedded_failure_without_title_goes_failed(db, tmp_path, monkeypatch) -> None:
    """内嵌失败且文件名也取不到书名/作者 → failed。"""
    path = tmp_path / "xxx.epub"
    path.write_bytes(b"broken" * 100)
    monkeypatch.setattr(
        "app.services.scan_service.extract_metadata",
        lambda _path: finalize({}, ok=False, reason="container 损坏"),
    )
    monkeypatch.setattr(
        "app.services.scan_service.parse_name",
        lambda _stem: {"title": "", "authors": [], "year": "", "series": "",
                       "series_index": "", "isbn": "", "publisher": ""},
    )
    result = process_scan_file(db, _candidate_file(path))
    row = BookRepository(db).get(result["book_id"])
    assert row["status"] == "failed"


def test_scanned_goes_partial(db, tmp_path, monkeypatch) -> None:
    """疑似扫描件 → partial（待补全），而非失败。"""
    path = tmp_path / "某作者 - 某书名 (2001).epub"
    path.write_bytes(b"scanned" * 100)
    monkeypatch.setattr(
        "app.services.scan_service.extract_metadata",
        lambda _path: finalize(
            {"title": "某书名", "authors": ["某作者"], "scanned": True}, ok=True
        ),
    )
    result = process_scan_file(db, _candidate_file(path))
    assert BookRepository(db).get(result["book_id"])["status"] == "partial"


# ---- 状态值迁移 ---------------------------------------------------

def test_legacy_status_values_are_migrated(db) -> None:
    """老库 recognized→ok、need_confirm→partial；再次 init 幂等。"""
    repo = BookRepository(db)
    a = repo.create(file_path="C:/b/a.epub", quick_hash="a", format="epub", title="A")
    b = repo.create(file_path="C:/b/b.epub", quick_hash="b", format="epub", title="B")
    db.execute("UPDATE books SET status = 'recognized' WHERE id = ?", (a,))
    db.execute("UPDATE books SET status = 'need_confirm' WHERE id = ?", (b,))

    init_database(db)  # version=4 → else 分支跑状态清洗
    assert repo.get(a)["status"] == "ok"
    assert repo.get(b)["status"] == "partial"

    init_database(db)  # 幂等：再次执行不变
    assert repo.get(a)["status"] == "ok"
    assert repo.get(b)["status"] == "partial"


# ---- enrich 允许 partial 被覆盖 -----------------------------------

def test_enrich_partial_complete_still_goes_online(db) -> None:
    """partial 书即使字段完整也联网，允许被新结果覆盖为 ok。"""
    repo = BookRepository(db)
    book_id = repo.create(
        file_path="C:/books/gatsby.epub", quick_hash="g", format="epub",
        title="了不起的盖茨比", author_raw="F. Scott Fitzgerald",
        isbn="9787020002207", publisher="人民文学出版社", status="partial",
    )
    source = FakeSource([_net_candidate()])
    service = MetadataService(db, SETTINGS, sources=[source])
    result = service.enrich_book(book_id)  # 不 force
    assert source.isbn_calls >= 1  # partial 没有短路，真正联网
    assert result["status"] == "ok"


def test_enrich_ok_complete_short_circuits(db) -> None:
    """ok 且字段完整的书直接短路，不发起网络请求。"""
    repo = BookRepository(db)
    book_id = repo.create(
        file_path="C:/books/gatsby.epub", quick_hash="g", format="epub",
        title="了不起的盖茨比", author_raw="F. Scott Fitzgerald",
        isbn="9787020002207", publisher="人民文学出版社", status="ok",
    )
    source = FakeSource([_net_candidate()])
    service = MetadataService(db, SETTINGS, sources=[source])
    result = service.enrich_book(book_id)
    assert source.isbn_calls == 0  # 未联网
    assert result["status"] == "ok"


# ---- partial 导航筛选与统计 ---------------------------------------

def test_partial_nav_and_statistics(db) -> None:
    repo = BookRepository(db)
    p = repo.create(file_path="C:/b/p.epub", quick_hash="p", format="epub",
                    title="P", status="partial")
    repo.create(file_path="C:/b/o.epub", quick_hash="o", format="epub",
                title="O", status="ok")
    service = LibraryService(db)
    rows, total = service.query_books(nav_key="partial")
    assert total == 1 and rows[0]["id"] == p
    stats = service.statistics()
    assert stats["partial"] == 1
    assert stats["ok"] == 1


# ---- 批量重识别 worker --------------------------------------------

def _partial_book(repo: BookRepository, key: str) -> int:
    return repo.create(
        file_path=f"C:/b/{key}.epub", quick_hash=key, format="epub",
        title="了不起的盖茨比", author_raw="F. Scott Fitzgerald",
        isbn="9787020002207", status="partial",
    )


def test_enrich_worker_success_counts(db) -> None:
    repo = BookRepository(db)
    id1 = _partial_book(repo, "1")
    service = MetadataService(db, SETTINGS, sources=[FakeSource([_net_candidate()])])
    worker = EnrichWorker(service, [id1], per_book_timeout=8.0)
    outcome: dict = {}
    worker.signals.finished.connect(lambda r: outcome.update(r))
    worker.run()
    assert outcome["total"] == 1
    assert outcome["completed"] == 1
    assert outcome["ok"] == 1
    assert not outcome["cancelled"]


def test_enrich_worker_timeout_does_not_block(db, monkeypatch) -> None:
    """单本超过 per_book_timeout 记为 timeout，继续后续，不卡死队列。"""
    repo = BookRepository(db)
    id1 = _partial_book(repo, "1")
    service = MetadataService(db, SETTINGS, sources=[])

    def slow(book_id, *, force=False):
        time.sleep(1.0)
        return {"book_id": book_id, "status": "ok", "message": ""}

    monkeypatch.setattr(service, "enrich_book", slow)
    worker = EnrichWorker(service, [id1], per_book_timeout=0.1)
    outcome: dict = {}
    worker.signals.finished.connect(lambda r: outcome.update(r))
    started = time.monotonic()
    worker.run()
    assert time.monotonic() - started < 0.9  # 未等满 1s 即超时返回
    assert outcome["timeout"] == 1


def test_enrich_worker_cancel(db) -> None:
    repo = BookRepository(db)
    id1 = _partial_book(repo, "1")
    service = MetadataService(db, SETTINGS, sources=[])
    worker = EnrichWorker(service, [id1])
    worker.cancel()
    outcome: dict = {}
    worker.signals.finished.connect(lambda r: outcome.update(r))
    worker.run()
    assert outcome["cancelled"] is True
    assert outcome["completed"] == 0

"""M2 服务层测试：扫描落库、增量、重复、查询和设置。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

from app.core.scanner import ScannedFile
from app.db.repositories.book_repo import BookRepository
from app.errors import ConfigError
from app.services.library_service import LibraryService
from app.services.scan_service import process_scan_file
from app.services.settings_service import SettingsService


def _candidate(path: Path, too_small: bool = False) -> ScannedFile:
    stat = path.stat()
    return ScannedFile(
        path=path,
        format=path.suffix.lower().lstrip("."),
        size=stat.st_size,
        mtime=stat.st_mtime,
        too_small=too_small,
    )


def _embedded(ok: bool = True) -> dict:
    return {
        "title": "测试书",
        "authors": ["测试作者"],
        "isbn": "9787020002207",
        "publisher": "测试出版社",
        "date": "2024-01-01",
        "language": "zh",
        "description": "简介",
        "page_count": 123,
        "cover_bytes": b"",
        "drm": False,
        "ok": ok,
        "reason": "" if ok else "文件损坏",
    }


def test_small_file_is_recorded_as_skipped(db, tmp_path, monkeypatch):
    path = tmp_path / "tiny.epub"
    path.write_bytes(b"tiny")
    monkeypatch.setattr(
        "app.services.scan_service.extract_metadata",
        lambda _path: pytest.fail("小文件不应进入元数据解析"),
    )

    result = process_scan_file(db, _candidate(path, too_small=True))

    assert result["status"] == "skipped"
    row = BookRepository(db).get(result["book_id"])
    assert row["title"] == "tiny"
    assert row["status"] == "skipped"


def test_recognized_file_and_incremental_skip(db, tmp_path, monkeypatch):
    path = tmp_path / "book.epub"
    path.write_bytes(b"epub-content" * 100)
    monkeypatch.setattr(
        "app.services.scan_service.extract_metadata", lambda _path: _embedded()
    )

    first = process_scan_file(db, _candidate(path))
    assert first["status"] == "ok"
    row = BookRepository(db).get(first["book_id"])
    assert row["title"] == "测试书"
    assert row["author_raw"] == "测试作者"
    assert row["isbn"] == "9787020002207"
    assert row["page_count"] == 123

    monkeypatch.setattr(
        "app.services.scan_service.extract_metadata",
        lambda _path: pytest.fail("未变更文件不应重复解析"),
    )
    second = process_scan_file(db, _candidate(path), incremental=True)
    assert second["unchanged"] is True
    assert second["book_id"] == first["book_id"]
    assert BookRepository(db).count() == 1


def test_embedded_cover_is_cached_at_320px(db, tmp_path, monkeypatch):
    path = tmp_path / "cover.epub"
    path.write_bytes(b"cover-content" * 100)
    image = QImage(640, 480, QImage.Format_RGB32)
    image.fill(Qt.white)
    buffer = QBuffer()
    buffer.open(QIODevice.ReadWrite)
    assert image.save(buffer, "PNG")
    metadata = _embedded()
    metadata["cover_bytes"] = bytes(buffer.data())
    monkeypatch.setattr("app.services.scan_service.extract_metadata", lambda _path: metadata)
    monkeypatch.setattr("app.services.scan_service.config.COVERS_DIR", tmp_path / "covers")

    result = process_scan_file(db, _candidate(path))

    cover = QImage(result["cover_path"])
    assert not cover.isNull()
    assert cover.width() == 320
    assert BookRepository(db).get(result["book_id"])["cover_path"] == result["cover_path"]


def test_non_incremental_scan_reparses_file(db, tmp_path, monkeypatch):
    path = tmp_path / "book.epub"
    path.write_bytes(b"epub-content" * 100)
    calls = []

    def metadata(_path):
        calls.append(1)
        return _embedded()

    monkeypatch.setattr("app.services.scan_service.extract_metadata", metadata)
    process_scan_file(db, _candidate(path))
    result = process_scan_file(db, _candidate(path), incremental=False)

    assert result["unchanged"] is False
    assert len(calls) == 2


def test_duplicate_content_is_grouped(db, tmp_path, monkeypatch):
    first_path = tmp_path / "a.epub"
    second_path = tmp_path / "b.epub"
    first_path.write_bytes(b"same-content" * 100)
    second_path.write_bytes(b"same-content" * 100)
    monkeypatch.setattr(
        "app.services.scan_service.extract_metadata", lambda _path: _embedded()
    )

    first = process_scan_file(db, _candidate(first_path))
    second = process_scan_file(db, _candidate(second_path))

    assert second["duplicate"] is True
    assert second["status"] == "skipped"
    repo = BookRepository(db)
    first_row = repo.get(first["book_id"])
    second_row = repo.get(second["book_id"])
    assert first_row["dup_group_id"] == first["book_id"]
    assert second_row["dup_group_id"] == first["book_id"]


def test_concurrent_duplicate_content_is_grouped(db, tmp_path, monkeypatch):
    paths = [tmp_path / "parallel-a.epub", tmp_path / "parallel-b.epub"]
    for path in paths:
        path.write_bytes(b"parallel-same-content" * 100)
    barrier = threading.Barrier(2)

    def metadata(_path):
        barrier.wait(timeout=5)
        return _embedded()

    monkeypatch.setattr("app.services.scan_service.extract_metadata", metadata)
    candidates = [_candidate(path) for path in paths]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda item: process_scan_file(db, item, incremental=False), candidates)
        )

    assert sum(bool(item["duplicate"]) for item in results) == 1
    repo = BookRepository(db)
    rows = [repo.get(item["book_id"]) for item in results]
    assert rows[0]["dup_group_id"] == rows[1]["dup_group_id"]
    assert {row["status"] for row in rows} == {"ok", "skipped"}


def test_failed_metadata_does_not_abort(db, tmp_path, monkeypatch):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"broken-pdf" * 100)
    monkeypatch.setattr(
        "app.services.scan_service.extract_metadata", lambda _path: _embedded(ok=False)
    )

    result = process_scan_file(db, _candidate(path))

    assert result["status"] == "failed"
    assert result["message"] == "文件损坏"
    assert BookRepository(db).get(result["book_id"])["status"] == "failed"


def test_library_query_filters_and_statistics(db):
    repo = BookRepository(db)
    repo.create(
        file_path="C:/books/a.epub",
        quick_hash="a",
        format="epub",
        title=" Python 入门 ",
        author_raw="作者甲",
        isbn="9780000000001",
        status="ok",
    )
    repo.create(
        file_path="C:/books/b.pdf",
        quick_hash="b",
        format="pdf",
        title="另一本",
        author_raw="作者乙",
        status="failed",
    )
    repo.create(
        file_path="C:/books/c.epub",
        quick_hash="c",
        format="epub",
        title="归档书",
        status="archived",
    )
    service = LibraryService(db)

    rows, total = service.query_books(nav_key="pending", search="Python", format_name="epub")
    assert total == 1
    assert rows[0]["title"].strip() == "Python 入门"
    assert service.query_books(nav_key="failed")[1] == 1
    assert service.query_books(nav_key="archived")[1] == 1
    assert service.statistics() == {
        "total": 3,
        "pending": 1,
        "ok": 1,
        "partial": 0,
        "failed": 1,
        "archived": 1,
    }


def test_scan_settings_are_persistent_and_validate_input(tmp_path):
    path = tmp_path / "config.json"
    source = tmp_path / "source"
    source.mkdir()
    settings = SettingsService(path)

    with pytest.raises(ConfigError):
        settings.save_scan_options([], ["epub"], {})
    with pytest.raises(ConfigError):
        settings.save_scan_options([str(source)], [], {})

    settings.save_scan_options(
        [str(source)], ["epub", "pdf"], {"workers": 3, "incremental": False}
    )
    loaded = SettingsService(path)
    assert loaded.data["formats"] == ["epub", "pdf"]
    assert loaded.data["scan"]["workers"] == 3
    assert loaded.data["scan"]["incremental"] is False
    assert loaded.data["recent_source_dirs"] == [str(source.resolve())]

    with pytest.raises(ConfigError):
        loaded.set_library_root(str(source))


def test_recent_source_dirs_keep_latest_five(tmp_path):
    settings = SettingsService(tmp_path / "config.json")
    sources = []
    for index in range(6):
        source = tmp_path / f"source-{index}"
        source.mkdir()
        sources.append(str(source.resolve()))
        settings.save_scan_options([sources[-1]], ["epub"], {})

    assert settings.data["recent_source_dirs"] == list(reversed(sources[1:]))

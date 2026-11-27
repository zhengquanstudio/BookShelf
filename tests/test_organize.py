"""M4 整理预览 / 执行 / 撤销 / 设置服务测试。"""

from __future__ import annotations

import csv
import time
from pathlib import Path

import pytest

from app.db.repositories.book_repo import BookRepository
from app.errors import OrganizeError
from app.services.normalization import normalize_book
from app.services.organize_service import OrganizeService
from app.services.settings_service import SettingsService


@pytest.fixture()
def env(tmp_path, db):
    library = tmp_path / "library"
    source = tmp_path / "source"
    library.mkdir()
    source.mkdir()
    settings = SettingsService(tmp_path / "config.json")
    settings.data["library_root"] = str(library)
    settings.data["source_dirs"] = [str(source)]
    settings.data["naming"] = {
        **settings.data.get("naming", {}),
        "author_dir_template": "{作者} [{国家}]",
        "file_template": "{作者} [{国家}] - {书名}.{扩展名}",
        "country_style": "short",
        "conflict_policy": "suffix",
    }
    settings.save()
    return db, settings, library, source


def _add_book(
    db,
    source: Path,
    index: int = 1,
    *,
    title: str = "了不起的盖茨比",
    author: str = "F.S. Fitzgerald",
    status: str = "ok",
    **extra,
) -> tuple[int, Path]:
    path = source / f"book_{index}.epub"
    path.write_bytes(b"x" * 256)
    book_id = BookRepository(db).create(
        file_path=str(path),
        quick_hash=f"hash{index}",
        format="epub",
        title=title,
        author_raw=author,
        file_size=path.stat().st_size,
        status=status,
        **extra,
    )
    normalize_book(db, book_id)
    db.execute(
        "UPDATE books SET status = ?, volume = NULL, volume_raw = NULL WHERE id = ?",
        (status, book_id),
    )
    return book_id, path


def test_preview_computes_paths_without_writing(env) -> None:
    db, settings, library, source = env
    _book_id, source_path = _add_book(db, source)
    service = OrganizeService(db, settings)
    summary = service.preview()

    assert summary.total == 1
    row = summary.rows[0]
    assert row.status == "ready"
    assert row.target_path.startswith(str(library))
    assert "菲茨杰拉德" in row.target_path
    assert not Path(row.target_path).exists()
    assert source_path.is_file()
    assert service.records() == []


def test_execute_copies_and_undo_restores(env) -> None:
    db, settings, _library, source = env
    book_id, source_path = _add_book(db, source)
    service = OrganizeService(db, settings)
    summary = service.preview()
    target = Path(summary.rows[0].target_path)

    result = service.execute(summary.rows)
    assert result.copied == 1 and result.failed == 0
    assert target.is_file()
    assert source_path.is_file()
    assert db.query_one("SELECT status FROM books WHERE id = ?", (book_id,))["status"] == "archived"
    assert db.query_one("SELECT COUNT(*) AS n FROM library_items")["n"] == 1
    assert db.query_one("SELECT COUNT(*) AS n FROM task_log")["n"] >= 1

    undone = service.undo(result.batch_id)
    assert undone.removed == 1
    assert not target.exists()
    assert source_path.is_file()
    assert db.query_one("SELECT status FROM books WHERE id = ?", (book_id,))["status"] == "ok"


def test_undo_keeps_preexisting_empty_dir(env) -> None:
    db, settings, _library, source = env
    _add_book(db, source)
    service = OrganizeService(db, settings)
    row = service.preview().rows[0]
    preexisting = Path(row.target_dir)
    preexisting.mkdir(parents=True)

    result = service.execute([row])
    assert result.dirs_created == 0
    service.undo(result.batch_id)

    assert preexisting.is_dir()
    assert not Path(row.target_path).exists()


def test_transliterated_author_without_country_is_ready(env) -> None:
    db, settings, _library, source = env
    _add_book(db, source, author="D.H.劳伦斯 (D.H.Lawrence)")
    row = OrganizeService(db, settings).preview().rows[0]
    assert row.status == "ready"
    assert not row.blocking


def test_latin_only_author_still_needs_confirm(env) -> None:
    db, settings, _library, source = env
    _add_book(db, source, author="W.Timothy Gallwey")
    row = OrganizeService(db, settings).preview().rows[0]
    assert row.blocking


def test_existing_target_gets_suffix(env) -> None:
    db, settings, _library, source = env
    _add_book(db, source)
    service = OrganizeService(db, settings)
    first = service.preview().rows[0]
    Path(first.target_path).parent.mkdir(parents=True, exist_ok=True)
    Path(first.target_path).write_bytes(b"old")

    second = service.preview()
    row = second.rows[0]
    assert row.status == "conflict"
    assert "(2)" in row.target_name
    assert "目标已存在" in row.message

    result = service.execute(second.rows)
    assert result.copied == 1
    assert Path(row.target_path).is_file()
    assert Path(first.target_path).read_bytes() == b"old"


def test_move_action_and_undo_rejected(env) -> None:
    db, settings, _library, source = env
    _book_id, source_path = _add_book(db, source)
    settings.data["organize"]["action"] = "move"
    service = OrganizeService(db, settings)
    summary = service.preview()
    result = service.execute(summary.rows)

    assert result.moved == 1
    assert not source_path.exists()
    assert Path(summary.rows[0].target_path).is_file()
    with pytest.raises(OrganizeError):
        service.undo(result.batch_id)


def test_overwrite_batch_cannot_be_undone(env) -> None:
    db, settings, _library, source = env
    _add_book(db, source)
    settings.data["naming"]["conflict_policy"] = "overwrite"
    service = OrganizeService(db, settings)
    first = service.preview().rows[0]
    Path(first.target_path).parent.mkdir(parents=True, exist_ok=True)
    Path(first.target_path).write_bytes(b"old")

    summary = service.preview(policy="overwrite")
    result = service.execute(summary.rows, overwrite=True)
    assert result.overwritten == 1
    with pytest.raises(OrganizeError):
        service.undo(result.batch_id)


def test_export_csv_is_excel_friendly(env, tmp_path) -> None:
    db, settings, _library, source = env
    _add_book(db, source)
    service = OrganizeService(db, settings)
    rows = service.preview().rows
    target = service.export_csv(rows, tmp_path / "preview.csv")

    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    with target.open(encoding="utf-8-sig", newline="") as handle:
        table = list(csv.reader(handle))
    assert table[0][0] == "状态"
    assert len(table) == 2


def test_preview_984_rows_under_three_seconds(env) -> None:
    db, settings, _library, _source = env
    with db.transaction() as conn:
        cur = conn.execute(
            "INSERT INTO authors(name_zh, country, country_code, is_chinese) "
            "VALUES ('测试作者', '美国', 'US', 0)"
        )
        author_id = cur.lastrowid
        rows = [
            (
                rf"C:\books\bulk_{index}.epub",
                f"bulk{index}",
                "epub",
                f"测试书名 {index:04d}",
                author_id,
                "ok",
            )
            for index in range(984)
        ]
        conn.executemany(
            "INSERT INTO books(file_path, quick_hash, format, title, author_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
    service = OrganizeService(db, settings)
    start = time.perf_counter()
    summary = service.preview()
    elapsed = time.perf_counter() - start
    assert summary.total == 984
    assert elapsed < 3.0, f"984 条预览耗时 {elapsed:.2f}s"
    print(f"\n984 条预览耗时：{elapsed * 1000:.0f}ms")

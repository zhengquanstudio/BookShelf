"""只重命名（N6）：同目录改名、冲突序号、批次回滚与撤销。"""

from __future__ import annotations

import os
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
        "file_template": "{作者} - {书名}{卷号} ({年份}).{扩展名}",
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
    year: str = "1925",
) -> tuple[int, Path]:
    path = source / f"vol{chr(64 + index)}.epub"
    path.write_bytes(b"x" * 256)
    book_id = BookRepository(db).create(
        file_path=str(path),
        quick_hash=f"hash{index}",
        format="epub",
        title=title,
        author_raw=author,
        publish_date=year,
        file_size=path.stat().st_size,
        status="ok",
    )
    normalize_book(db, book_id)
    db.execute(
        "UPDATE books SET status = 'ok', volume = NULL, volume_raw = NULL WHERE id = ?",
        (book_id,),
    )
    return book_id, path


def test_rename_only_keeps_directory_and_updates_db(env) -> None:
    db, settings, _library, source = env
    book_id, old_path = _add_book(db, source)
    service = OrganizeService(db, settings)

    result = service.rename_only([book_id])

    row = BookRepository(db).get(book_id)
    new_path = Path(row["file_path"])
    assert result.renamed == 1 and result.failed == 0
    assert new_path.parent == old_path.parent == source
    assert new_path.name == "菲茨杰拉德 - 了不起的盖茨比 (1925).epub"
    assert new_path.is_file() and not old_path.exists()
    item = db.query_one("SELECT * FROM library_items WHERE batch_id = ?", (result.batch_id,))
    assert item["action"] == "rename"
    assert item["result"] == "renamed"
    assert item["source_path"] == str(old_path)
    assert item["target_path"] == str(new_path)


def test_rename_only_appends_suffix_on_conflict(env) -> None:
    db, settings, _library, source = env
    book_id, _old_path = _add_book(db, source)
    occupied = source / "菲茨杰拉德 - 了不起的盖茨比 (1925).epub"
    occupied.write_bytes(b"old")
    service = OrganizeService(db, settings)

    result = service.rename_only([book_id])

    new_path = Path(BookRepository(db).get(book_id)["file_path"])
    assert result.renamed == 1
    assert "(2)" in new_path.name
    assert new_path.parent == source
    assert occupied.read_bytes() == b"old"


def test_rename_only_skips_already_matching_name(env) -> None:
    db, settings, _library, source = env
    path = source / "菲茨杰拉德 - 了不起的盖茨比 (1925).epub"
    path.write_bytes(b"x" * 256)
    book_id = BookRepository(db).create(
        file_path=str(path),
        quick_hash="same",
        format="epub",
        title="了不起的盖茨比",
        author_raw="F.S. Fitzgerald",
        publish_date="1925",
        status="ok",
    )
    normalize_book(db, book_id)
    service = OrganizeService(db, settings)

    result = service.rename_only([book_id])

    assert result.renamed == 0 and result.skipped == 1
    assert Path(BookRepository(db).get(book_id)["file_path"]) == path


def test_rename_only_rolls_back_whole_batch(env, monkeypatch) -> None:
    db, settings, _library, source = env
    first_id, first_path = _add_book(db, source, 1)
    second_id, second_path = _add_book(
        db, source, 2, title="夜色温柔", author="F.S. Fitzgerald"
    )
    service = OrganizeService(db, settings)
    real_replace = os.replace
    calls = {"count": 0}

    def flaky(source_path, target_path):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("模拟磁盘错误")
        return real_replace(source_path, target_path)

    monkeypatch.setattr("app.services.organize_service.os.replace", flaky)

    with pytest.raises(OrganizeError):
        service.rename_only([first_id, second_id])

    repo = BookRepository(db)
    assert Path(repo.get(first_id)["file_path"]) == first_path
    assert Path(repo.get(second_id)["file_path"]) == second_path
    assert first_path.is_file() and second_path.is_file()
    results = {row["result"] for row in db.query("SELECT result FROM library_items")}
    assert results == {"rolled_back"}


def test_undo_rename_restores_original_path(env) -> None:
    db, settings, _library, source = env
    book_id, old_path = _add_book(db, source)
    service = OrganizeService(db, settings)

    result = service.rename_only([book_id])
    renamed = Path(BookRepository(db).get(book_id)["file_path"])
    assert renamed != old_path

    undone = service.undo(result.batch_id)

    assert undone.removed == 1
    assert Path(BookRepository(db).get(book_id)["file_path"]) == old_path
    assert old_path.is_file() and not renamed.exists()
    assert db.query_one(
        "SELECT result FROM library_items WHERE batch_id = ?", (result.batch_id,)
    )["result"] == "undone"

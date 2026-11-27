"""M6 作者目录与系列管理测试。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.db.repositories.book_repo import BookRepository
from app.services.author_service import AuthorService
from app.services.series_service import SeriesService
from app.services.settings_service import SettingsService
from app.ui.pages.author_page import AuthorPage


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def _book(db, tmp_path, name: str, **fields) -> int:
    return BookRepository(db).create(
        file_path=str(tmp_path / f"{name}.epub"),
        quick_hash=f"hash-{name}",
        format="epub",
        title=name,
        status="ok",
        **fields,
    )


def test_author_catalog_and_explicit_merge(db, tmp_path) -> None:
    service = AuthorService(db)
    source = service.create("来源作者")
    target = service.create("目标作者")
    book_id = _book(db, tmp_path, "书", author_id=source)

    assert service.catalog("来源")[0]["book_count"] == 1
    assert service.merge(source, target) == 1
    assert db.query_one("SELECT author_id FROM books WHERE id = ?", (book_id,))["author_id"] == target
    assert db.query_one("SELECT * FROM authors WHERE id = ?", (source,)) is None
    assert "来源作者" in db.query_one("SELECT alias_json FROM authors WHERE id = ?", (target,))["alias_json"]


def test_series_missing_volumes_add_and_export(db, tmp_path) -> None:
    authors = AuthorService(db)
    service = SeriesService(db)
    author_id = authors.create("刘慈欣")
    series_id = service.create("三体", author_id, 3)
    first = _book(db, tmp_path, "三体1", author_id=author_id)
    third = _book(db, tmp_path, "三体3", author_id=author_id)
    second = _book(db, tmp_path, "三体2", author_id=author_id)
    service.assign_books([first, third], series_id)
    service.set_volume(first, 1)
    service.set_volume(third, 3)

    catalog = service.catalog(author_id)
    assert catalog[0]["missing"] == [2]
    assert catalog[0]["complete"] is False
    service.add_volume(series_id, second, 2)
    assert service.catalog(author_id)[0]["complete"] is True
    assert service.normalize_volumes(series_id) == 3

    output = tmp_path / "series.csv"
    assert service.export_list(series_id, output) == 3
    assert output.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "三体2" in output.read_text(encoding="utf-8-sig")


def test_series_merge_and_split(db, tmp_path) -> None:
    author_id = AuthorService(db).create("作者")
    service = SeriesService(db)
    source = service.create("来源系列", author_id)
    target = service.create("目标系列", author_id)
    first = _book(db, tmp_path, "第一卷", author_id=author_id)
    second = _book(db, tmp_path, "第二卷", author_id=author_id)
    service.assign_books([first], source)
    service.assign_books([second], target)

    assert service.merge(source, target) == 1
    assert db.query_one("SELECT series_id FROM books WHERE id = ?", (first,))["series_id"] == target
    assert service.split(target, [first]) == 1
    assert db.query_one("SELECT series_id FROM books WHERE id = ?", (first,))["series_id"] is None


def test_author_page_renders_books_and_series(db, tmp_path, qapp) -> None:
    author_id = AuthorService(db).create("刘慈欣")
    series = SeriesService(db)
    series_id = series.create("三体", author_id, 3)
    book_id = _book(db, tmp_path, "三体", author_id=author_id, series_id=series_id, volume=1)
    settings = SettingsService(tmp_path / "config.json")

    page = AuthorPage(db, settings)
    assert page.author_list.count() == 1
    assert page.author_title.text() == "刘慈欣"
    assert page.series_list.count() == 1
    assert page.volume_list.count() == 1
    assert "缺失" in page.series_state.text()

    opened: list[int] = []
    page.open_book_requested.connect(opened.append)
    page._open_series()
    assert opened == [book_id]
    page.close()

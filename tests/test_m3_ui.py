"""M3 图 03 编辑对话框离屏测试。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.db.repositories.book_repo import BookRepository
from app.services.metadata_service import MetadataService
from app.services.settings_service import SettingsService
from app.ui.dialogs.edit_book_dialog import EditBookDialog


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


class FakeSource:
    name = "fake"

    def by_isbn(self, isbn: str) -> list[dict]:
        return []

    def search(self, query: str) -> list[dict]:
        return [
            {
                "source": "fake",
                "title": "了不起的盖茨比",
                "authors": ["F. Scott Fitzgerald"],
                "isbn": "9787020002207",
                "publisher": "人民文学出版社",
                "date": "2004",
                "language": "en",
                "series": "",
                "series_index": "",
                "description": "一部关于美国梦的小说。",
                "cover_url": "",
            }
        ]


def test_edit_dialog_search_apply_and_save(db, tmp_path, qapp) -> None:
    repo = BookRepository(db)
    book_id = repo.create(
        file_path="C:/books/gatsby.epub",
        quick_hash="g",
        format="epub",
        title="了不起的盖茨比",
        author_raw="F.S. Fitzgerald",
        status="partial",
    )
    settings = SettingsService(tmp_path / "config.json")
    service = MetadataService(db, settings, sources=[FakeSource()])
    dialog = EditBookDialog(
        db, settings, service=service, book_id=book_id, sync_search=True
    )

    assert dialog._title.text() == "了不起的盖茨比"
    assert "菲茨杰拉德" in dialog._author_norm.text()
    assert dialog._preview_path.text() != "—"

    dialog._search()
    assert len(dialog._candidates) == 1
    assert dialog._candidates[0]["score"] >= 30

    dialog._apply_candidate(dialog._candidates[0])
    assert dialog._publisher.text() == "人民文学出版社"
    assert dialog._isbn.text() == "9787020002207"

    dialog._save(next_book=False)
    row = repo.get(book_id)
    assert row["publisher"] == "人民文学出版社"
    assert row["isbn"] == "9787020002207"
    assert row["status"] == "ok"
    assert row["meta_source"] == "manual"
    author = db.query_one(
        "SELECT a.* FROM authors AS a JOIN books AS b ON b.author_id = a.id WHERE b.id = ?",
        (book_id,),
    )
    assert author["name_zh"] == "菲茨杰拉德"
    assert author["locked"] == 1
    dialog.close()

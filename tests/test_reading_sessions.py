"""D2：阅读会话采集（reading_sessions 落库与阅读器会话生命周期）。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.db.repositories.book_repo import BookRepository
from app.db.repositories.reading_repo import ReadingRepository
from app.services.settings_service import SettingsService
from app.ui.pages.reader_container import ReaderContainer


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def _add_book(db, path) -> int:
    return BookRepository(db).create(
        file_path=str(path),
        quick_hash=path.stem,
        format=path.suffix.lstrip("."),
        title="会话测试书",
        status="ok",
    )


def test_session_repository_accumulates(db, tmp_path) -> None:
    book_id = _add_book(db, tmp_path / "session.epub")
    repo = ReadingRepository(db)

    session_id = repo.start_session(book_id)
    repo.add_session_progress(session_id, 60, 3)
    repo.add_session_progress(session_id, 30)
    repo.add_session_progress(session_id, 0, 0)
    repo.end_session(session_id)

    row = db.query_one("SELECT * FROM reading_sessions WHERE id = ?", (session_id,))
    assert row is not None
    assert row["book_id"] == book_id
    assert row["seconds"] == 90
    assert row["pages"] == 3
    assert row["device"] == "desktop"
    assert row["started_at"] and row["ended_at"]


def test_reader_container_flushes_session(qapp, db, tmp_path, monkeypatch) -> None:
    book_id = _add_book(db, tmp_path / "reader.epub")
    settings = SettingsService(tmp_path / "config.json")
    reader = ReaderContainer(db, settings, web_enabled=False)

    monkeypatch.setattr(ReaderContainer, "_session_active", lambda self: True)
    reader._book_id = book_id
    reader._ensure_session()
    assert reader._session_id is not None
    reader._session_last = None  # 排除真实计时，只验证累计逻辑

    reader._session_seconds = 75.4
    reader._session_pages = 5
    reader._flush_session()

    row = db.query_one(
        "SELECT * FROM reading_sessions WHERE book_id = ?", (book_id,)
    )
    assert row is not None
    assert row["seconds"] == 75
    assert row["pages"] == 5
    assert row["ended_at"] is None
    assert 0 <= reader._session_seconds < 1
    assert reader._session_pages == 0

    reader._end_session()
    row = db.query_one("SELECT * FROM reading_sessions WHERE id = ?", (row["id"],))
    assert row["ended_at"]
    assert reader._session_id is None


def test_inactive_window_pauses_session(qapp, db, tmp_path, monkeypatch) -> None:
    book_id = _add_book(db, tmp_path / "paused.epub")
    settings = SettingsService(tmp_path / "config.json")
    reader = ReaderContainer(db, settings, web_enabled=False)

    monkeypatch.setattr(ReaderContainer, "_session_active", lambda self: True)
    reader._book_id = book_id
    reader._ensure_session()
    reader._session_last = None
    reader._session_seconds = 12.0
    reader._sync_session_clock()  # 激活状态：继续计时
    assert reader._session_last is not None

    monkeypatch.setattr(ReaderContainer, "_session_active", lambda self: False)
    reader._sync_session_clock()  # 失焦：落库并暂停
    assert reader._session_last is None
    row = db.query_one(
        "SELECT * FROM reading_sessions WHERE book_id = ?", (book_id,)
    )
    assert row is not None
    assert row["seconds"] == 12
    reader._end_session()

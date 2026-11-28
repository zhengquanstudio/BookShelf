"""S2 批量重识别与导航筛选的 UI 接线（离屏，不访问真实网络）。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.db.repositories.book_repo import BookRepository
from app.services.settings_service import SettingsService
from app.ui.main_window import MainWindow


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def _window(db, tmp_path, qt_settings) -> MainWindow:
    settings = SettingsService(tmp_path / "config.json")
    root = tmp_path / "library"
    root.mkdir()
    settings.set_library_root(str(root))
    return MainWindow(db=db, settings=settings, qt_settings=qt_settings)


def test_nav_has_partial_entry(db, tmp_path, qapp, qt_settings) -> None:
    window = _window(db, tmp_path, qt_settings)
    keys = window.nav.keys()
    assert "partial" in keys


def test_partial_nav_filters_library(db, tmp_path, qapp, qt_settings) -> None:
    repo = BookRepository(db)
    repo.create(file_path="C:/b/p.epub", quick_hash="p", format="epub",
                title="待补全书", status="partial")
    repo.create(file_path="C:/b/o.epub", quick_hash="o", format="epub",
                title="已识别书", status="ok")
    window = _window(db, tmp_path, qt_settings)
    window.nav.set_current("partial")
    qapp.processEvents()
    assert window.table_model.rowCount() == 1
    assert window.table_model.row_data(0)["title"] == "待补全书"


class _FakePool:
    def __init__(self) -> None:
        self.started: list = []

    def start(self, worker) -> None:
        self.started.append(worker)


def test_reidentify_creates_worker_and_progress(db, tmp_path, qapp, qt_settings, monkeypatch) -> None:
    repo = BookRepository(db)
    book_id = repo.create(file_path="C:/b/a.epub", quick_hash="a", format="epub",
                          title="A", status="partial")
    window = _window(db, tmp_path, qt_settings)
    pool = _FakePool()
    monkeypatch.setattr("app.ui.main_window.QThreadPool.globalInstance", lambda: pool)
    monkeypatch.setattr("app.ui.main_window.QMessageBox.information", lambda *a, **k: None)

    window._reidentify_books([book_id])

    assert window._enrich_worker is not None
    assert window._enrich_progress is not None
    assert pool.started and pool.started[0] is window._enrich_worker
    assert window._enrich_progress.maximum() == 1

    # 重复触发应被拒绝（已有任务进行中），不会新建 worker
    window._reidentify_books([book_id])
    assert len(pool.started) == 1

    window._clear_reidentify()
    assert window._enrich_worker is None
    assert window._enrich_progress is None

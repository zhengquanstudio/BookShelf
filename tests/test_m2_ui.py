"""M2 主窗口、详情和扫描对话框的离屏集成测试。"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication

from app.db.repositories.book_repo import BookRepository
from app.services.settings_service import SettingsService
from app.ui.dialogs.scan_dialog import ScanDialog
from app.ui.main_window import MainWindow


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def test_main_window_loads_filters_and_shows_details(db, tmp_path, qapp, qt_settings):
    repo = BookRepository(db)
    repo.create(
        file_path="C:/books/a.epub",
        quick_hash="a",
        file_size=2048,
        format="epub",
        title="离屏测试书",
        author_raw="测试作者",
        publisher="测试出版社",
        status="ok",
    )
    repo.create(
        file_path="C:/books/b.pdf",
        quick_hash="b",
        format="pdf",
        title="失败书",
        status="failed",
    )
    settings = SettingsService(tmp_path / "config.json")
    library_root = tmp_path / "library"
    library_root.mkdir()
    settings.set_library_root(str(library_root))
    window = MainWindow(db=db, settings=settings, qt_settings=qt_settings)
    window.show()
    qapp.processEvents()

    assert window.table_model.rowCount() == 2
    assert window.detail._title.text() == "失败书"
    assert window._stat_labels["total"].text() == "书库总数：2"
    assert window.format_filter.count() == 5
    assert len(window.menuBar().actions()) == 9

    window.search_box.setText("离屏测试")
    window._search_timer.stop()
    window.refresh_library()
    assert window.table_model.rowCount() == 1
    assert window.detail._title.text() == "离屏测试书"
    assert "测试作者" in window.detail._author.text()

    window.search_box.clear()
    window._search_timer.stop()
    window.format_filter.setCurrentIndex(2)
    qapp.processEvents()
    assert window.table_model.rowCount() == 1
    assert window.detail._title.text() == "失败书"

    window.nav.set_current("all")
    window.format_filter.setCurrentIndex(0)
    qapp.processEvents()
    window.open_scan_dialog()
    qapp.processEvents()
    assert window._scan_dialog is not None
    assert window._scan_dialog.isVisible()
    assert window._scan_dialog.file_table.columnCount() == 6

    window._scan_dialog.close()
    qapp.processEvents()
    window.close()
    qapp.processEvents()
    saved = SettingsService(tmp_path / "config.json")
    assert saved.data["ui"]["window_size"] == [window.width(), window.height()]


def test_empty_library_guide_and_isolated_sample(db, tmp_path, qapp, qt_settings):
    settings = SettingsService(tmp_path / "config.json")
    library_root = tmp_path / "library"
    library_root.mkdir()
    settings.set_library_root(str(library_root))
    window = MainWindow(db, settings, qt_settings=qt_settings)
    window.show()
    qapp.processEvents()

    assert window.table_stack.currentWidget() is window.empty_page
    assert "作者 / 系列 / 卷号" in window.empty_page.explanation.text()
    assert window.empty_page.scan_button.text() == "选择文件夹扫描"
    window.empty_page.scan_button.click()
    qapp.processEvents()
    assert window._scan_dialog is not None and window._scan_dialog.isVisible()
    window._scan_dialog.close()
    qapp.processEvents()

    window.empty_page.sample_link.linkActivated.emit("sample")
    qapp.processEvents()
    assert window._sample_dialog is not None and window._sample_dialog.isVisible()
    assert window._sample_dialog.table.rowCount() == 3
    assert BookRepository(db).count() == 0
    assert list(library_root.iterdir()) == []
    assert settings.data["source_dirs"] == []
    window._sample_dialog.close()
    qapp.processEvents()

    BookRepository(db).create(
        file_path=str(tmp_path / "book.epub"),
        quick_hash="empty-guide-book",
        format="epub",
        title="真实书籍",
        status="ok",
    )
    window.refresh_library()
    assert window.table_stack.currentWidget() is window.table
    window.search_box.setText("没有匹配结果")
    window._search_timer.stop()
    window.refresh_library()
    assert window.table_model.rowCount() == 0
    assert window.table_stack.currentWidget() is window.table
    window.close()
    qapp.processEvents()


def test_main_window_restores_window_and_splitter_state(db, tmp_path, qapp, qt_settings):
    settings = SettingsService(tmp_path / "config.json")
    library_root = tmp_path / "library"
    library_root.mkdir()
    settings.set_library_root(str(library_root))
    window = MainWindow(db=db, settings=settings, qt_settings=qt_settings)
    window.show()
    window.resize(1280, 900)
    window.move(40, 30)
    window._clamp_to_screen()
    qapp.processEvents()
    expected_size = window.size()
    sizes = window.content_splitter.sizes()
    window.content_splitter.setSizes([max(600, sizes[0] - 40), sizes[1] + 40])
    qapp.processEvents()
    expected_splitter = window.content_splitter.sizes()
    window.showMaximized()
    qapp.processEvents()
    window.close()
    qapp.processEvents()

    assert qt_settings.value("geometry") is not None
    assert qt_settings.value("windowState") is not None
    assert qt_settings.value("splitter/content") is not None

    restored = MainWindow(db=db, settings=settings, qt_settings=qt_settings)
    restored.show()
    qapp.processEvents()
    assert restored.isMaximized()
    assert restored.windowState() & Qt.WindowMaximized
    restored.showNormal()
    qapp.processEvents()
    assert restored.size() == expected_size
    assert restored.content_splitter.sizes() == expected_splitter
    assert restored.minimumWidth() == 1180
    assert restored.minimumHeight() == 880

    restored.move(100000, 100000)
    restored._clamp_to_screen()
    available = restored.screen().availableGeometry()
    assert restored.x() >= available.left()
    assert restored.y() >= available.top()
    assert restored.x() + restored.width() <= max(
        available.right() + 1, available.left() + restored.width()
    )
    restored.close()
    qapp.processEvents()


def test_main_window_restores_normal_position(db, tmp_path, qapp, qt_settings):
    settings = SettingsService(tmp_path / "config.json")
    library_root = tmp_path / "library"
    library_root.mkdir()
    settings.set_library_root(str(library_root))
    window = MainWindow(db=db, settings=settings, qt_settings=qt_settings)
    window.show()
    window.resize(1280, 900)
    window.move(40, 30)
    window._clamp_to_screen()
    qapp.processEvents()
    expected_pos = window.pos()
    window.close()
    qapp.processEvents()

    restored = MainWindow(db=db, settings=settings, qt_settings=qt_settings)
    restored.show()
    qapp.processEvents()
    assert restored.pos() == expected_pos
    restored.close()
    qapp.processEvents()


def test_library_paginates_1200_books(db, tmp_path, qapp, qt_settings):
    with db.transaction() as conn:
        conn.executemany(
            "INSERT INTO books(file_path, quick_hash, format, title, status, updated_at) "
            "VALUES (?, ?, 'epub', ?, 'ok', ?)",
            [
                (f"C:/books/page-{index}.epub", f"hash-{index}", f"分页书 {index}", str(index))
                for index in range(1200)
            ],
        )
    settings = SettingsService(tmp_path / "config.json")
    library_root = tmp_path / "library"
    library_root.mkdir()
    settings.set_library_root(str(library_root))
    window = MainWindow(db=db, settings=settings, qt_settings=qt_settings)
    window.show()
    qapp.processEvents()

    started = time.perf_counter()
    window.refresh_library()
    elapsed = time.perf_counter() - started
    qapp.processEvents()

    assert elapsed < 0.3
    assert window.table_model.rowCount() == 200
    assert window._library_total == 1200
    assert window.load_more_button.isVisible()
    assert "共 1200 本" in window._status_label.text()

    scrollbar = window.table.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())
    qapp.processEvents()
    assert window.table_model.rowCount() == 400

    while window.table_model.rowCount() < 1200:
        window.load_more_button.click()
        qapp.processEvents()
    assert not window.load_more_button.isVisible()
    assert "已加载" not in window._status_label.text()
    assert len({window.table_model.book_id(row) for row in range(1200)}) == 1200

    window.close()
    qapp.processEvents()


def test_scan_dialog_options_and_batch_updates(db, tmp_path, qapp):
    settings = SettingsService(tmp_path / "config.json")
    from app.services.scan_service import ScanService

    service = ScanService(db)
    dialog = ScanDialog(settings, service)
    dialog.show()
    qapp.processEvents()

    assert dialog.dir_list.count() == 0
    assert set(dialog.format_checks) == {"epub", "pdf", "mobi", "azw3"}
    assert dialog.workers_spin.value() == 4
    assert not dialog.stop_button.isEnabled()

    dialog._on_started({"total": 2, "format_counts": {"epub": 2}})
    dialog._on_files(
        [
            {
                "path": "C:/books/a.epub",
                "file_name": "a.epub",
                "format": "epub",
                "size": 1024,
                "status": "ok",
                "title": "测试书",
                "message": "内嵌元数据完整",
            }
        ]
    )
    dialog._on_progress(
        {
            "total": 2,
            "completed": 1,
            "current_file": "a.epub",
            "scanned": 1,
            "success": 1,
        }
    )
    qapp.processEvents()

    assert dialog.file_table.rowCount() == 1
    assert dialog.file_table.item(0, 3).text() == "测试书"
    assert dialog.file_table.item(0, 4).text() == "内嵌元数据完整"
    assert dialog.progress.value() == 50
    assert dialog._stat_values["success"].text() == "1"

    dialog.close()
    service.shutdown()
    qapp.processEvents()


def test_scan_service_end_to_end_and_incremental(db, tmp_path, qapp, monkeypatch):
    from app.services.scan_service import ScanService

    source = tmp_path / "source"
    source.mkdir()
    for name in ("a.epub", "b.epub"):
        (source / name).write_bytes(f"content-{name}".encode() * 6000)
    monkeypatch.setattr(
        "app.services.scan_service.extract_metadata",
        lambda _path: {
            "title": "线程池测试书",
            "authors": ["测试作者"],
            "cover_bytes": b"",
            "ok": True,
            "drm": False,
        },
    )
    service = ScanService(db)
    options = {
        "formats": ["epub"],
        "recursive": True,
        "incremental": True,
        "ignore_hidden": True,
        "min_size_kb": 50,
        "max_depth": 12,
        "workers": 2,
    }

    def run_once():
        loop = QEventLoop()
        results = []
        service.finished.connect(results.append)
        service.finished.connect(loop.quit)
        QTimer.singleShot(10000, loop.quit)
        assert service.start([str(source)], options)
        loop.exec()
        assert results, "扫描超时或未完成"
        return results[-1]

    try:
        first = run_once()
        assert first["total"] == 2
        assert first["success"] == 2
        assert first["failed"] == 0
        assert BookRepository(db).count() == 2

        second = run_once()
        assert second["unchanged"] == 2
        assert BookRepository(db).count() == 2
        assert db.query_one("SELECT COUNT(*) AS n FROM task_log")["n"] == 2
    finally:
        service.shutdown()


def test_scan_service_cancel_keeps_committed_rows(db, tmp_path, qapp, monkeypatch):
    from app.services.scan_service import ScanService

    source = tmp_path / "cancel-source"
    source.mkdir()
    for index in range(20):
        (source / f"{index}.epub").write_bytes(f"cancel-{index}".encode() * 6000)

    def metadata(_path):
        time.sleep(0.05)
        return {"title": "取消测试", "authors": ["作者"], "ok": True, "cover_bytes": b""}

    monkeypatch.setattr("app.services.scan_service.extract_metadata", metadata)
    service = ScanService(db)
    loop = QEventLoop()
    results = []
    service.finished.connect(results.append)
    service.finished.connect(loop.quit)
    options = {
        "formats": ["epub"],
        "recursive": True,
        "incremental": True,
        "ignore_hidden": True,
        "min_size_kb": 50,
        "max_depth": 12,
        "workers": 2,
    }
    try:
        assert service.start([str(source)], options)
        QTimer.singleShot(50, service.cancel)
        QTimer.singleShot(5000, loop.quit)
        loop.exec()

        assert results, "取消扫描未完成"
        assert results[0]["cancelled"] is True
        assert results[0]["scanned"] < 20
        assert BookRepository(db).count() == results[0]["scanned"]
    finally:
        service.shutdown()

"""T4：书库表格 8 列、行高 56、表头排序接线与服务端重查。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHeaderView

from app.db.repositories.book_repo import BookRepository
from app.services.settings_service import SettingsService
from app.ui.main_window import MainWindow
from app.ui.widgets.book_table import HEADERS


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def _make_window(db, tmp_path, qapp, qt_settings):
    settings = SettingsService(tmp_path / "config.json")
    library_root = tmp_path / "library"
    library_root.mkdir()
    settings.set_library_root(str(library_root))
    repo = BookRepository(db)
    repo.create(
        file_path="C:/books/a.epub", quick_hash="a", format="epub",
        title="Alpha", isbn="111", file_size=1024, status="ok",
    )
    repo.create(
        file_path="C:/books/b.pdf", quick_hash="b", format="pdf",
        title="Beta", isbn="222", file_size=2048, status="pending",
    )
    window = MainWindow(db=db, settings=settings, qt_settings=qt_settings)
    window.show()
    qapp.processEvents()
    return window


def test_library_table_has_eight_columns_and_row_height_56(db, tmp_path, qapp, qt_settings):
    window = _make_window(db, tmp_path, qapp, qt_settings)
    try:
        assert len(HEADERS) == 8
        assert window.table_model.columnCount() == 8
        assert [head[2] for head in HEADERS] == [
            "check", "title", "format", "isbn", "progress", "size", "added", "status"
        ]
        assert window.table.verticalHeader().defaultSectionSize() == 56
        assert window.table.isSortingEnabled()
        # 书名列拉伸吸收剩余宽度
        assert window.table.horizontalHeader().sectionResizeMode(1) == QHeaderView.Stretch
        # 默认排序指示在“添加时间”列（第 6 列），倒序
        assert window.table.horizontalHeader().sortIndicatorSection() == 6
        assert window.table.horizontalHeader().sortIndicatorOrder() == Qt.DescendingOrder
        assert window._library_sort == "added_at"
        assert window._library_desc is True
    finally:
        window.close()
        qapp.processEvents()


def test_library_table_header_sort_reruns_query(db, tmp_path, qapp, qt_settings):
    window = _make_window(db, tmp_path, qapp, qt_settings)
    try:
        window.table.sortByColumn(1, Qt.AscendingOrder)
        qapp.processEvents()
        assert window._library_sort == "title"
        assert window._library_desc is False
        titles = [
            window.table_model.row_data(r)["title"]
            for r in range(window.table_model.rowCount())
        ]
        assert titles == ["Alpha", "Beta"]

        window.table.sortByColumn(5, Qt.DescendingOrder)
        qapp.processEvents()
        assert window._library_sort == "file_size"
        assert window._library_desc is True
        # 按文件大小倒序：Beta(2048) 排在第一
        assert window.table_model.row_data(0)["file_size"] == 2048
    finally:
        window.close()
        qapp.processEvents()


def test_detail_panel_default_width_is_384(db, tmp_path, qapp, qt_settings):
    window = _make_window(db, tmp_path, qapp, qt_settings)
    try:
        # T5：详情面板默认宽 384（未在 ui 配置里指定 detail_width 时）
        assert window.detail.maximumWidth() == 384
        assert len(window.detail._kv_values) == 8
    finally:
        window.close()
        qapp.processEvents()


def test_progress_display_and_isbn_tooltip(db, tmp_path, qapp, qt_settings):
    window = _make_window(db, tmp_path, qapp, qt_settings)
    try:
        model = window.table_model
        isbn_col = next(i for i, h in enumerate(HEADERS) if h[2] == "isbn")
        progress_col = next(i for i, h in enumerate(HEADERS) if h[2] == "progress")
        alpha_row = next(
            r for r in range(model.rowCount()) if model.row_data(r)["title"] == "Alpha"
        )
        idx = model.index(alpha_row, isbn_col)
        assert model.data(idx, Qt.DisplayRole) == "111"
        assert model.data(idx, Qt.ToolTipRole) == "111"
        # 无阅读进度的书显示“未读”
        pidx = model.index(alpha_row, progress_col)
        assert model.data(pidx, Qt.DisplayRole) == "未读"
    finally:
        window.close()
        qapp.processEvents()


def test_batch_bar_shows_hides_and_counts_checked(db, tmp_path, qapp, qt_settings):
    window = _make_window(db, tmp_path, qapp, qt_settings)
    try:
        model = window.table_model
        # 取消 refresh 时的自动选中，初始应隐藏
        window.table.clearSelection()
        qapp.processEvents()
        assert not window.batch_bar.isVisible()

        alpha_row = next(
            r for r in range(model.rowCount()) if model.row_data(r)["title"] == "Alpha"
        )
        model.setData(model.index(alpha_row, 0), Qt.Checked, Qt.CheckStateRole)
        qapp.processEvents()
        assert window.batch_bar.isVisible()
        assert "1" in window.batch_bar._count.text()

        beta_row = next(
            r for r in range(model.rowCount()) if model.row_data(r)["title"] == "Beta"
        )
        model.setData(model.index(beta_row, 0), Qt.Checked, Qt.CheckStateRole)
        qapp.processEvents()
        assert "2" in window.batch_bar._count.text()

        window.batch_bar.clear_requested.emit()
        qapp.processEvents()
        assert not window.batch_bar.isVisible()
        assert model.checked_ids() == []
    finally:
        window.close()
        qapp.processEvents()


def test_batch_bar_archive_marks_books_archived(db, tmp_path, qapp, qt_settings):
    window = _make_window(db, tmp_path, qapp, qt_settings)
    try:
        model = window.table_model
        alpha_row = next(
            r for r in range(model.rowCount()) if model.row_data(r)["title"] == "Alpha"
        )
        book_id = model.row_data(alpha_row)["id"]
        model.setData(model.index(alpha_row, 0), Qt.Checked, Qt.CheckStateRole)
        window._batch_archive()
        qapp.processEvents()
        row = window.db.query_one("SELECT status FROM books WHERE id = ?", (book_id,))
        assert row["status"] == "archived"
    finally:
        window.close()
        qapp.processEvents()


def test_library_export_list_writes_csv(db, tmp_path, qapp, qt_settings):
    window = _make_window(db, tmp_path, qapp, qt_settings)
    try:
        model = window.table_model
        alpha_row = next(
            r for r in range(model.rowCount()) if model.row_data(r)["title"] == "Alpha"
        )
        book_id = model.row_data(alpha_row)["id"]
        out = tmp_path / "list.csv"
        count = window.library.export_list([book_id], out)
        assert count == 1
        assert out.exists()
        text = out.read_text(encoding="utf-8-sig")
        assert "书名" in text
        assert "Alpha" in text
    finally:
        window.close()
        qapp.processEvents()

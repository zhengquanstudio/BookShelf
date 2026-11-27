"""M7 标签 / 收藏 / 文件夹视图筛选测试。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.db.repositories.book_repo import BookRepository
from app.services.library_service import LibraryService
from app.services.settings_service import SettingsService
from app.ui.dialogs.filter_dialog import FilterDialog
from app.ui.main_window import MainWindow


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def _book(db, path, name: str, *, status: str = "ok") -> int:
    return BookRepository(db).create(
        file_path=str(path / f"{name}.epub"),
        quick_hash=f"hash-{name}",
        format="epub",
        title=name,
        status=status,
    )


def test_tag_filter_and_counts(db, tmp_path) -> None:
    service = LibraryService(db)
    first = _book(db, tmp_path, "收藏书")
    _book(db, tmp_path, "普通书")
    service.add_favorite([first])

    rows, total = service.query_books(tag="收藏")
    assert total == 1
    assert rows[0]["id"] == first
    assert service.tag_counts()[0]["name"] == "收藏"
    assert service.tag_counts()[0]["count"] == 1


def test_folder_view_uses_archive_target(db, tmp_path) -> None:
    service = LibraryService(db)
    archived = _book(db, tmp_path / "source", "已归档")
    recognized = _book(db, tmp_path / "source", "待整理")
    target = tmp_path / "library" / "某作者" / "已归档.epub"
    db.execute(
        "INSERT INTO library_items"
        "(book_id, target_dir, target_name, target_path, action, result) "
        "VALUES (?, ?, ?, ?, 'copy', 'copy')",
        (archived, str(target.parent), target.name, str(target)),
    )

    folders = {row["path"]: row for row in service.folders()}
    assert str(target.parent) in folders
    assert folders[str(target.parent)]["count"] == 1
    assert folders[str(tmp_path / "source")]["count"] == 1

    rows, total = service.query_books(folder=str(target.parent))
    assert total == 1 and rows[0]["id"] == archived
    rows, total = service.query_books(folder=str(tmp_path / "source"))
    assert total == 1 and rows[0]["id"] == recognized


def test_filter_dialog_search_picks_first_visible(qapp) -> None:
    entries = [
        {"path": r"E:\书库\甲", "count": 2},
        {"path": r"E:\书库\乙", "count": 1},
    ]
    dialog = FilterDialog(
        "测试", "选择：", entries, None,
        value_key="path", label_key="path", searchable=True,
    )
    dialog._search.setText("乙")
    dialog._accept()
    assert dialog.selected_value.endswith("乙")


def test_ui_favorites_and_clear_filter(qapp, db, tmp_path, qt_settings) -> None:
    settings = SettingsService(tmp_path / "config.json")
    settings.data["library_root"] = str(tmp_path / "library")
    settings.save()
    first = _book(db, tmp_path, "收藏书")
    _book(db, tmp_path, "普通书")

    window = MainWindow(db, settings, qt_settings=qt_settings)
    try:
        assert window.table_model.rowCount() == 2
        window.library.add_favorite([first])
        window._on_nav("favorites")
        assert window._tag_filter == "收藏"
        assert window.table_model.rowCount() == 1
        assert window.table_model.row_data(0)["id"] == first
        assert window.clear_filter_button.isHidden() is False

        window._on_nav("all")
        assert window._tag_filter == ""
        assert window.table_model.rowCount() == 2
        assert window.clear_filter_button.isHidden() is True
    finally:
        window.close()

"""M7 标签管理、文件夹树、清单导入、缓存清理与数据库备份测试。"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from app.db.repositories.book_repo import BookRepository
from app.services.library_service import LibraryService
from app.services.maintenance_service import MaintenanceService
from app.services.settings_service import SettingsService
from app.ui.dialogs.backup_dialog import BackupDialog
from app.ui.main_window import MainWindow
from app.ui.pages.folder_page import FolderPage, build_folder_tree


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


def test_rename_tag_moves_books_and_merges(db) -> None:
    service = LibraryService(db)
    first = _book(db, Path("."), "甲")
    second = _book(db, Path("."), "乙")
    service.set_tags([first], ["旧标签"])
    service.set_tags([second], ["新标签"])

    assert service.rename_tag("旧标签", "新标签") == 1
    assert service.tags_for(first) == ["新标签"]
    names = {row["name"] for row in service.tag_counts()}
    assert "旧标签" not in names

    assert service.rename_tag("新标签", "最终标签") == 2
    assert service.tags_for(first) == ["最终标签"]
    assert service.tags_for(second) == ["最终标签"]


def test_delete_tag_keeps_books(db) -> None:
    service = LibraryService(db)
    book_id = _book(db, __import__("pathlib").Path("."), "书")
    service.set_tags([book_id], ["临时"])

    assert service.delete_tag("临时") == 1
    assert service.tags_for(book_id) == []
    assert service.tag_counts() == []
    assert BookRepository(db).get(book_id) is not None


def test_favorite_tag_is_protected(db) -> None:
    service = LibraryService(db)
    book_id = _book(db, Path("."), "被收藏")
    service.add_favorite([book_id])

    assert service.rename_tag("收藏", "喜欢") == 0
    assert service.delete_tag("收藏") == 0
    assert service.tags_for(book_id) == ["收藏"]


def test_import_pending_skips_invalid_and_existing(db, tmp_path) -> None:
    source = tmp_path / "清单"
    source.mkdir()
    good = source / "好书.epub"
    good.write_bytes(b"x")
    (source / "说明.txt").write_text("not a book", encoding="utf-8")
    existing_path = source / "已有.pdf"
    existing_path.write_bytes(b"x")
    BookRepository(db).create(file_path=str(existing_path.resolve()), format="pdf", title="已有")

    lines = [
        "# 注释",
        "好书.epub",
        "说明.txt",
        "不存在.epub",
        "",
        "已有.pdf",
        str(good),
    ]
    result = LibraryService(db).import_pending(lines, base_dir=source)
    assert result == {"added": 1, "existing": 2, "invalid": 2}
    assert BookRepository(db).find_by_path(str(good.resolve()))["status"] == "pending"


def test_folder_tree_aggregates_counts() -> None:
    entries = [
        {"path": r"E:\书库\作者甲", "count": 2},
        {"path": r"E:\书库\作者乙", "count": 3},
        {"path": r"E:\书库\作者甲\系列", "count": 1},
    ]
    tree = build_folder_tree(entries)
    assert len(tree) == 1
    drive = tree[0]
    assert drive["name"] == "E:\\"
    assert drive["total"] == 6
    library = next(item for item in drive["children"] if item["name"] == "书库")
    assert library["total"] == 6
    author = next(item for item in library["children"] if item["name"] == "作者甲")
    assert author["total"] == 3


def test_folder_page_emits_selected_path(qapp, db, tmp_path) -> None:
    folder = tmp_path / "归档" / "某作者"
    _book(db, folder, "书")
    page = FolderPage(LibraryService(db))
    captured: list[str] = []
    page.folder_selected.connect(captured.append)

    item = page.tree.topLevelItem(0)
    while item.childCount():
        item.setExpanded(True)
        item = item.child(0)
    page.tree.setCurrentItem(item)
    page._apply_current()

    assert captured and captured[0] == str(folder)


def test_nav_pages_and_folder_filter(qapp, db, tmp_path, qt_settings) -> None:
    settings = SettingsService(tmp_path / "config.json")
    settings.data["library_root"] = str(tmp_path / "library")
    settings.save()
    folder = tmp_path / "归档"
    _book(db, folder, "书")

    window = MainWindow(db, settings, qt_settings=qt_settings)
    try:
        window._on_nav("help")
        assert window.content_stack.currentWidget() is window.help_page

        window._on_nav("folders")
        assert window.content_stack.currentWidget() is window.folder_page
        window.folder_page.folder_selected.emit(str(folder))
        assert window._folder_filter == str(folder)
        assert window.content_stack.currentWidget() is window.content_stack.widget(0)
        assert window.table_model.rowCount() == 1

        window._on_nav("settings")
        assert window._settings_dialog is not None
        window._settings_dialog.close()
        window._clear_settings_dialog()
        assert window.nav.current_key() == "all"
    finally:
        window.close()


def test_backup_database_creates_consistent_copy(db, tmp_path) -> None:
    _book(db, tmp_path, "备份书")
    target = MaintenanceService(db, backup_dir=tmp_path / "backups").backup_database()

    assert target.is_file()
    copy = sqlite3.connect(str(target))
    try:
        assert copy.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 1
    finally:
        copy.close()


def test_backup_retention_and_restore_create_safety_copy(db, tmp_path) -> None:
    service = MaintenanceService(
        db, backup_dir=tmp_path / "backups", backup_retention=5
    )
    _book(db, tmp_path, "备份时的数据")
    created = [service.create_backup()[0] for _ in range(3)]
    selected, size = service.create_backup()
    created.append(selected)
    assert size == selected.stat().st_size

    _book(db, tmp_path, "备份后新增")
    created.extend(service.create_backup()[0] for _ in range(4))

    assert len(created) == 8
    assert len(list(service.backup_dir.glob("library-*.db"))) == 5
    assert all(not path.exists() for path in created[:3])
    assert selected.is_file()

    safety_copy = service.restore_backup(selected)

    assert safety_copy.name.startswith("pre-restore-")
    assert len(list(service.backup_dir.glob("library-*.db"))) == 5
    assert len(list(service.backup_dir.glob("pre-restore-*.db"))) == 1
    assert db.query_one("SELECT COUNT(*) AS n FROM books")["n"] == 1
    assert db.query_one("SELECT title FROM books")["title"] == "备份时的数据"
    copy = sqlite3.connect(str(safety_copy))
    try:
        assert copy.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 2
    finally:
        copy.close()


def test_backup_dialog_lists_copies_and_restores(qapp, db, tmp_path, monkeypatch) -> None:
    _book(db, tmp_path, "对话框备份")
    settings = SettingsService(tmp_path / "config.json")
    dialog = BackupDialog(db, settings, backup_dir=tmp_path / "backups")
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    restored: list[bool] = []
    dialog.restored.connect(lambda: restored.append(True))

    dialog.create_backup()

    assert dialog.tree.topLevelItemCount() == 1
    item = dialog.tree.topLevelItem(0)
    backup_path = Path(item.data(0, Qt.UserRole))
    path_edit = dialog.tree.itemWidget(item, 2)
    assert path_edit.isReadOnly()
    assert path_edit.text() == str(backup_path)
    path_edit.selectAll()
    assert path_edit.hasSelectedText()

    dialog.restore_backup(str(backup_path))
    assert restored == [True]
    assert dialog.tree.topLevelItemCount() == 2
    assert len(list((tmp_path / "backups").glob("pre-restore-*.db"))) == 1

    dialog.delete_backup(str(backup_path))
    assert dialog.tree.topLevelItemCount() == 1
    assert not backup_path.exists()
    dialog.close()


def test_clear_cache_purges_files_and_metadata(db, tmp_path, monkeypatch) -> None:
    cache = tmp_path / "converted"
    cache.mkdir()
    (cache / "a.epub").write_bytes(b"12345")
    moved: list[str] = []

    def fake_recycle(paths):
        moved.extend(str(path) for path in paths)
        return len(moved)

    monkeypatch.setattr(
        "app.services.maintenance_service.move_to_recycle_bin", fake_recycle
    )
    db.execute(
        "INSERT INTO search_cache(key, source, payload_json, fetched_at, expires_at) "
        "VALUES ('k', 'test', '{}', '2026-01-01T00:00:00', '2999-01-01T00:00:00')"
    )
    result = MaintenanceService(
        db, cache_dirs=[cache], backup_dir=tmp_path / "backups"
    ).clear_cache()

    assert result == {"files": 1, "bytes": 5, "metadata": 1}
    assert moved and moved[0].endswith("a.epub")

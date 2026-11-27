"""M4 图 04 / 图 06 离屏界面测试。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from app.db.repositories.book_repo import BookRepository
from app.services.normalization import normalize_book
from app.services.settings_service import SettingsService
from app.ui.dialogs.preview_dialog import PreviewDialog
from app.ui.dialogs.settings_dialog import SettingsDialog


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture()
def env(tmp_path, db):
    library = tmp_path / "library"
    source = tmp_path / "source"
    library.mkdir()
    source.mkdir()
    settings = SettingsService(tmp_path / "config.json")
    settings.data["library_root"] = str(library)
    settings.data["source_dirs"] = [str(source)]
    settings.save()
    return db, settings, library, source


def _add_book(db, source: Path, index: int = 1) -> tuple[int, Path]:
    path = source / f"gatsby_{index}.epub"
    path.write_bytes(b"x" * 256)
    book_id = BookRepository(db).create(
        file_path=str(path),
        quick_hash=f"h{index}",
        format="epub",
        title="了不起的盖茨比",
        author_raw="F.S. Fitzgerald",
        status="ok",
    )
    normalize_book(db, book_id)
    db.execute(
        "UPDATE books SET status = 'ok', volume = NULL, volume_raw = NULL "
        "WHERE id = ?",
        (book_id,),
    )
    return book_id, path


def test_settings_dialog_updates_examples_and_persists(env, qapp) -> None:
    db, settings, _library, _source = env
    dialog = SettingsDialog(db, settings, initial_page="naming")
    assert "菲茨杰拉德" in dialog.example_view.toPlainText()

    dialog.author_template_edit.setText("{作者}【{国家}】")
    dialog.file_template_edit.setText("{作者}-{书名} {卷号}.{扩展名}")
    index = dialog.country_style_combo.findData("full")
    dialog.country_style_combo.setCurrentIndex(index)
    dialog._refresh_examples()
    text = dialog.example_view.toPlainText()
    assert "【美国】" in text
    assert "刘慈欣-三体 第1卷.epub" in text

    assert dialog.save() is True
    assert settings.data["naming"]["author_dir_template"] == "{作者}【{国家}】"
    row = db.query_one("SELECT v FROM app_settings WHERE k = 'settings.last_page'")
    assert row is not None
    dialog.close()


def test_preview_dialog_executes_and_hides_archived(env, qapp) -> None:
    db, settings, _library, source = env
    _book_id, source_path = _add_book(db, source)
    dialog = PreviewDialog(db, settings)

    assert dialog.summary.total == 1
    assert dialog.model.rowCount() == 1
    target = Path(dialog.summary.rows[0].target_path)
    assert not target.exists()

    dialog._execute(confirm=False, notify=False)
    assert target.is_file()
    assert source_path.is_file()
    dialog._regenerate()
    assert dialog.summary.total == 0
    dialog.close()


def test_main_window_opens_preview_and_settings(env, qapp, qt_settings) -> None:
    db, settings, _library, source = env
    _add_book(db, source)
    from app.ui.main_window import MainWindow

    window = MainWindow(db, settings, qt_settings=qt_settings)
    window.open_preview()
    qapp.processEvents()
    assert window._preview_dialog is not None
    assert window._preview_dialog.summary.total == 1
    window._preview_dialog.close()
    qapp.processEvents()

    window._open_settings()
    qapp.processEvents()
    assert window._settings_dialog is not None
    window._settings_dialog.close()
    window.close()


def test_preview_dialog_conflict_filter(env, qapp) -> None:
    db, settings, _library, source = env
    _add_book(db, source, 1)
    dialog = PreviewDialog(db, settings)
    first = dialog.summary.rows[0]
    target = Path(first.target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"old")

    dialog._regenerate()
    assert any(row.status == "conflict" for row in dialog.summary.rows)
    dialog._conflict_only.setChecked(True)
    assert dialog.model.rowCount() == 1
    assert dialog.model.rows[0].status == "conflict"
    dialog.close()

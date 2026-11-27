"""界面主题切换与工具栏/详情栏高度测试。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QSizePolicy, QToolBar

from app.services.settings_service import SettingsService
from app.ui.main_window import MainWindow
from app.ui.theme import load_stylesheet


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def test_stylesheet_switches_between_dark_and_light() -> None:
    dark = load_stylesheet("dark")
    light = load_stylesheet("light")

    assert "#17181b" in dark
    assert "#17181b" not in light
    assert "#f3f5f7" in light
    assert "#e7e9ee" in dark
    assert "#e7e9ee" not in light


def test_main_window_applies_theme_widths_and_spacing(qapp, db, tmp_path, qt_settings) -> None:
    settings = SettingsService(tmp_path / "config.json")
    library_root = tmp_path / "library"
    library_root.mkdir()
    settings.set_library_root(str(library_root))
    settings.apply({"ui": {"theme": "light", "nav_width": 240, "detail_width": 420}})
    window = MainWindow(db, settings, qt_settings=qt_settings)
    try:
        toolbar = window.findChild(QToolBar, "MainToolBar")
        assert toolbar is not None
        assert toolbar.minimumHeight() == 60
        assert window.minimumHeight() == 880

        window.show()
        window.resize(1024, 640)
        qapp.processEvents()
        detail = window.detail
        kv_bottom = (
            detail._kv.mapTo(detail, detail._kv.rect().topLeft()).y()
            + detail._kv.height()
        )
        path_top = detail._path.mapTo(detail, detail._path.rect().topLeft()).y()
        assert path_top >= kv_bottom

        assert window.nav.maximumWidth() == 240
        assert window.detail.maximumWidth() == 420

        assert window.detail._kv.sizePolicy().verticalPolicy() == QSizePolicy.Fixed
        assert window.detail._kv_rows["出版社"].minimumHeight() == 22
        assert window.detail._path.minimumHeight() == 52

        assert "#17181b" not in window.styleSheet()
        assert "#f3f5f7" in window.styleSheet()

        settings.apply({"ui": {"nav_width": 260}})
        window._apply_ui_theme()
        assert "#f3f5f7" in window.styleSheet()
        assert window.nav.maximumWidth() == 260
    finally:
        window.close()

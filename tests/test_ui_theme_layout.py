"""界面主题切换与工具栏/详情栏高度测试。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFrame, QSizePolicy

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
        topbar = window.findChild(QFrame, "TitleBar")
        assert topbar is not None
        assert topbar.minimumHeight() == 52
        assert window.minimumHeight() == 880

        window.show()
        window.resize(1024, 640)
        qapp.processEvents()
        detail = window.detail
        # T5 详情面板：8 行元数据（含新增的「系列」「阅读进度」）+ 路径框 + 简介
        assert len(detail._kv_values) == 8
        assert "系列" in detail._kv_values
        assert "阅读进度" in detail._kv_values
        assert detail.findChild(QFrame, "PathBox") is not None
        assert detail._intro is not None

        assert window.nav.maximumWidth() == 240
        assert window.detail.maximumWidth() == 420

        assert "#17181b" not in window.styleSheet()
        assert "#f3f5f7" in window.styleSheet()

        settings.apply({"ui": {"nav_width": 260}})
        window._apply_ui_theme()
        assert "#f3f5f7" in window.styleSheet()
        assert window.nav.maximumWidth() == 260
    finally:
        window.close()

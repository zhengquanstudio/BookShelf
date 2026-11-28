"""T17：字号/行距/页边距的默认值与取值范围对齐 v3 原型，并随设置实时生效。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app import config
from app.services.settings_service import SettingsService
from app.ui.dialogs.reader_prefs_dialog import ReaderPrefsDialog
from app.ui.theme_tokens import palette_for


@pytest.fixture(autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture()
def settings(tmp_path):
    return SettingsService(tmp_path / "config.json")


def _find(dialog, key):
    for k, widget, _kind, _default in dialog._bound:
        if k == key:
            return widget
    raise AssertionError(f"bound control not found: {key}")


def test_config_defaults_align_v3():
    r = config.DEFAULT_CONFIG["reader"]
    assert r["font_size"] == 17
    assert r["line_height"] == 1.95
    assert r["margin_top"] == 54
    assert r["margin_bottom"] == 54
    assert r["margin_left"] == 54
    assert r["margin_right"] == 54
    assert r["fixed_page_width"] is True


def test_dialog_stepper_ranges_and_initial_values(settings):
    dlg = ReaderPrefsDialog(settings, palette_for("light"), {})

    font = _find(dlg, "font_size")
    assert font._minimum == 12
    assert font._maximum == 32
    assert font.value() == 17

    line = _find(dlg, "line_height")
    assert line._minimum == 1.2
    assert line._maximum == 2.5
    assert abs(line.value() - 1.95) < 1e-9

    for key in ("margin_top", "margin_bottom", "margin_left", "margin_right"):
        w = _find(dlg, key)
        assert w._minimum == 0
        assert w._maximum == 96
        assert w.value() == 54

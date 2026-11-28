"""T14：阅读器设置弹窗结构与读写行为。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from app.services.settings_service import SettingsService
from app.ui.dialogs.reader_prefs_dialog import (
    HIGHLIGHT_COLORS,
    PALETTES,
    ReaderPrefsDialog,
    _TAB_ORDER,
)
from app.ui.theme_tokens import palette_for


@pytest.fixture(autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture()
def settings(tmp_path):
    return SettingsService(tmp_path / "config.json")


def _make(settings, prefs=None):
    return ReaderPrefsDialog(settings, palette_for("dark"), prefs or {})


def _find(dialog, key, kind):
    for k, widget, knd, _default in dialog._bound:
        if k == key and knd == kind:
            return widget
    raise AssertionError(f"bound control not found: {key}/{kind}")


def test_six_tabs_present(settings):
    dialog = _make(settings)
    assert len(dialog._tab_buttons) == 6
    assert list(dialog._tab_buttons) == [k for k, _t, _g in _TAB_ORDER]
    assert dialog._stack.count() == 6
    assert dialog.sizeHint().width() == 660


def test_theme_pane_has_eight_cards_and_four_highlight_dots(settings):
    dialog = _make(settings)
    assert len(dialog._theme_cards) == 8
    assert set(dialog._theme_cards) == set(PALETTES)
    assert len(dialog._hl_dots) == 4
    assert set(dialog._hl_dots) == set(HIGHLIGHT_COLORS)


def test_initial_prefs_are_reflected_in_controls(settings):
    prefs = {
        "theme": "sepia",
        "highlight_color": "green",
        "mode": "dark",
        "font_size": 24,
        "header_footer": {"battery": True},
    }
    dialog = _make(settings, prefs)
    assert dialog._theme_cards["sepia"].isChecked()
    assert dialog._hl_dots["green"].isChecked()
    assert _find(dialog, "mode", "segmented").value() == "dark"
    assert _find(dialog, "font_size", "stepper").value() == 24
    assert _find(dialog, "battery", "hf").isChecked()


def test_theme_card_click_writes_key_and_emits(settings):
    dialog = _make(settings)
    seen: list[dict] = []
    dialog.changed.connect(seen.append)
    dialog._theme_cards["sky"].click()
    assert settings.data["reader"]["theme"] == "sky"
    assert any("theme" in d for d in seen)
    assert dialog._theme_cards["sky"].isChecked()


def test_highlight_dot_click_writes_semantic_name(settings):
    dialog = _make(settings)
    seen: list[dict] = []
    dialog.changed.connect(seen.append)
    dialog._hl_dots["pink"].click()
    assert settings.data["reader"]["highlight_color"] == "pink"
    assert any(d.get("highlight_color") == "pink" for d in seen)


def test_toggle_writes_bool_and_emits(settings):
    dialog = _make(settings)
    seen: list[dict] = []
    dialog.changed.connect(seen.append)
    toggle = _find(dialog, "invert_images_dark", "toggle")
    toggle.setChecked(True)
    assert settings.data["reader"]["invert_images_dark"] is True
    assert any(d.get("invert_images_dark") is True for d in seen)


def test_stepper_writes_number(settings):
    dialog = _make(settings)
    seen: list[dict] = []
    dialog.changed.connect(seen.append)
    stepper = _find(dialog, "font_size", "stepper")
    stepper.set_value(27, emit=True)
    assert settings.data["reader"]["font_size"] == 27
    assert any(d.get("font_size") == 27 for d in seen)


def test_segmented_writes_value(settings):
    dialog = _make(settings)
    seg = _find(dialog, "page_mode", "segmented")
    seg.set_value("spread", emit=True)
    assert settings.data["reader"]["page_mode"] == "spread"


def test_header_footer_writes_nested_dict(settings):
    dialog = _make(settings)
    seen: list[dict] = []
    dialog.changed.connect(seen.append)
    toggle = _find(dialog, "battery", "hf")
    toggle.setChecked(True)
    assert settings.data["reader"]["header_footer"]["battery"] is True
    last = seen[-1]
    assert "header_footer" in last and isinstance(last["header_footer"], dict)


def test_load_prefs_refreshes_without_emitting(settings):
    dialog = _make(settings, {"font_size": 19})
    seen: list[dict] = []
    dialog.changed.connect(seen.append)
    dialog.load_prefs({"font_size": 30, "theme": "grass", "highlight_color": "amber"})
    assert seen == []
    assert _find(dialog, "font_size", "stepper").value() == 30
    assert dialog._theme_cards["grass"].isChecked()
    assert dialog._hl_dots["amber"].isChecked()


def test_escape_closes_dialog(settings):
    dialog = _make(settings)
    QTest.keyClick(dialog, Qt.Key_Escape)
    assert dialog.result() == QDialog.Rejected

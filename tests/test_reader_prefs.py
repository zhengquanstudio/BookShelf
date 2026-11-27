"""阅读器偏好：默认值、按书覆盖、持久化与 Stepper 控件。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.services.settings_service import SettingsService
from app.ui.pages.reader_container import ReaderContainer
from app.ui.theme_tokens import palette_for
from app.ui.widgets.stepper import Stepper


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture()
def settings(tmp_path):
    return SettingsService(tmp_path / "config.json")


@pytest.fixture()
def reader(qapp, db, settings):
    return ReaderContainer(db, settings, web_enabled=False)


def test_reader_prefs_defaults(reader):
    prefs = reader._reader_prefs()
    assert prefs["theme"] == "light"
    assert prefs["font_size"] == 19
    assert prefs["line_height"] == pytest.approx(1.90)
    assert prefs["font_weight"] == 400
    assert prefs["para_spacing"] == pytest.approx(0.75)
    assert prefs["indent"] is True and prefs["justify"] is True
    assert prefs["hyphens"] is False
    assert (prefs["margin_top"], prefs["margin_bottom"]) == (48, 48)
    assert (prefs["margin_left"], prefs["margin_right"]) == (56, 56)
    assert prefs["column_count"] == 1
    assert prefs["max_column_width"] == 920
    assert prefs["turn_style"] == "push"
    assert prefs["click_turn"] is True
    assert prefs["texture"] == "none"
    assert prefs["accent"] is None
    assert prefs["palette"]["page"] == "#fbfaf7"


def test_reader_prefs_clamp_invalid_values(reader, settings):
    settings.data["reader"].update(
        {
            "font_size": 999,
            "line_height": 9.9,
            "margin_left": -20,
            "column_count": 5,
            "max_column_width": 100,
            "turn_style": "wobble",
            "texture": "sand",
            "font_weight": 900,
        }
    )
    prefs = reader._reader_prefs()
    assert prefs["font_size"] == 40
    assert prefs["line_height"] == pytest.approx(3.0)
    assert prefs["margin_left"] == 0
    assert prefs["column_count"] == 1
    assert prefs["max_column_width"] == 520
    assert prefs["turn_style"] == "push"
    assert prefs["texture"] == "none"
    assert prefs["font_weight"] == 400


def test_update_prefs_persists_and_applies(reader, settings, tmp_path):
    reader._update_prefs(font_size=22, turn_style="curl", texture="paper", accent="#c05a78")
    prefs = reader._reader_prefs()
    assert prefs["font_size"] == 22
    assert prefs["turn_style"] == "curl"
    assert prefs["texture"] == "paper"
    assert prefs["palette"]["accent"] == "#c05a78"

    reloaded = SettingsService(tmp_path / "config.json").data["reader"]
    assert reloaded["font_size"] == 22
    assert reloaded["turn_style"] == "curl"
    assert reloaded["texture"] == "paper"
    assert reloaded["accent"] == "#c05a78"


def test_per_book_override_applies_only_to_that_book(reader, settings):
    settings.data["reader"]["books"] = {"7": {"font_size": 24, "turn_style": "flip"}}
    reader._book_id = 7
    override = reader._reader_prefs()
    assert override["font_size"] == 24
    assert override["turn_style"] == "flip"

    reader._book_id = 8
    assert reader._reader_prefs()["font_size"] == 19
    assert reader._reader_prefs()["turn_style"] == "push"


def test_mode_and_accent_override(reader, settings):
    settings.data["reader"].update({"theme": "sepia", "mode": "dark"})
    assert reader._reader_prefs()["palette"]["key"] == "dark"

    settings.data["reader"].update({"theme": "dark", "mode": "light"})
    assert reader._reader_prefs()["theme"] == "light"

    settings.data["reader"].update({"theme": "sepia", "mode": "light", "accent": "not-a-color"})
    assert reader._reader_prefs()["palette"]["accent"] == palette_for("sepia").accent


def test_reset_prefs_restores_appearance_but_keeps_books(reader, settings):
    settings.data["reader"].update(
        {"font_size": 30, "theme": "cherry", "margin_px": 80, "books": {"3": {"font_size": 33}}}
    )
    reader._reset_prefs()
    reader_data = settings.data["reader"]
    assert reader_data["font_size"] == 19
    assert reader_data["theme"] == "light"
    assert "margin_px" not in reader_data
    assert reader_data["books"] == {"3": {"font_size": 33}}


def test_prefs_popup_has_three_tabs_and_swatches(reader):
    assert reader.prefs_popup.width() == 320
    assert [button.text() for button in reader.prefs_tabs] == ["字体", "版面", "主题"]
    assert reader.prefs_stack.count() == 3
    assert len(reader.theme_swatches) == 8
    reader._select_prefs_tab(2)
    assert reader.prefs_stack.currentIndex() == 2
    assert reader.prefs_tabs[2].isChecked() and not reader.prefs_tabs[0].isChecked()
    reader._show_prefs()
    assert reader.prefs_popup.isVisible()
    reader.prefs_popup.hide()


def test_chrome_toggle_and_escape(reader):
    reader._toggle_chrome()
    assert reader.topbar.isHidden() and reader.bottombar.isHidden()
    reader._toggle_chrome()
    assert not reader.topbar.isHidden()
    # Esc 在旧代码里会访问不存在的 bookmark_panel，这里确认已修复。
    reader._on_escape()


def test_stepper_steps_clamps_and_formats(qapp):
    stepper = Stepper(10, 12, 1, 10)
    values: list[float] = []
    stepper.changed.connect(values.append)
    stepper.step_by(1)
    stepper.step_by(1)
    stepper.step_by(1)
    assert stepper.value() == 12
    assert values == [11.0, 12.0]
    assert not stepper.plus_button.isEnabled()

    decimal = Stepper(1.0, 3.0, 0.05, 1.9, decimals=2)
    assert decimal.value_label.text() == "1.90"
    decimal.step_by(1)
    assert decimal.value_label.text() == "1.95"

    assert stepper.plus_button.autoRepeatDelay() == 400
    assert stepper.plus_button.autoRepeatInterval() == 90


def test_stepper_set_value_does_not_emit(qapp):
    stepper = Stepper(10, 40, 1, 19)
    emitted: list[float] = []
    stepper.changed.connect(emitted.append)
    stepper.set_value(25)
    assert stepper.value() == 25
    assert stepper.value_label.text() == "25"
    assert emitted == []

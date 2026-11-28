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
    assert prefs["font_size"] == 17
    assert prefs["line_height"] == pytest.approx(1.95)
    assert prefs["font_weight"] == 400
    assert prefs["para_spacing"] == pytest.approx(0.75)
    assert prefs["indent"] is True and prefs["justify"] is True
    assert prefs["hyphens"] is False
    assert (prefs["margin_top"], prefs["margin_bottom"]) == (54, 54)
    assert (prefs["margin_left"], prefs["margin_right"]) == (54, 54)
    assert prefs["fixed_page_width"] is True
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
    assert prefs["font_size"] == 32
    assert prefs["line_height"] == pytest.approx(2.5)
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
    assert reader._reader_prefs()["font_size"] == 17
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
    assert reader_data["font_size"] == 17
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


# ---- D3 · 新 prefs 键 --------------------------------------------
def test_d3_prefs_defaults(reader):
    prefs = reader._reader_prefs()
    assert prefs["page_mode"] == "single"
    assert prefs["page_width"] == 560
    assert prefs["disable_double_click"] is False
    assert prefs["auto_turn_sec"] == 0
    assert prefs["reading_ruler"] is False
    assert prefs["mask_top"] is True
    assert prefs["show_clock"] is True
    assert prefs["show_remaining"] is True
    assert prefs["turn_anim"] == "flip"
    assert prefs["highlight_colors"] == [
        "#f2c14e", "#d99c98", "#9cc39a", "#8fb3d9", "#b6a4d9"
    ]


def test_d3_page_mode_and_width_clamped(reader, settings):
    settings.data["reader"].update({"page_mode": "spread", "page_width": 1200})
    prefs = reader._reader_prefs()
    assert prefs["page_mode"] == "spread"
    assert prefs["page_width"] == 900  # 上界夹到 900

    settings.data["reader"].update({"page_mode": "weird", "page_width": 10})
    prefs = reader._reader_prefs()
    assert prefs["page_mode"] == "single"
    assert prefs["page_width"] == 420  # 下界夹到 420


def test_d3_highlight_colors_validation(reader, settings):
    # #ABC 是三位简写，_HEX_COLOR 只认 6 位 → 非法；xxx 非法 → 回落默认。
    settings.data["reader"]["highlight_colors"] = ["#ABC", "#f2c14e", "xxx"]
    colors = reader._reader_prefs()["highlight_colors"]
    assert colors == [
        "#f2c14e",  # 非法 → 默认 index0
        "#f2c14e",  # 合法保留
        "#9cc39a",  # 非法 → 默认 index2
        "#8fb3d9",
        "#b6a4d9",
    ]


def test_d3_migrate_column_count_to_spread_once(reader, settings, tmp_path):
    # 模拟老用户：没有 page_mode，存的是 column_count=2。
    settings.data["reader"]["column_count"] = 2
    settings.data["reader"].pop("page_mode", None)
    settings.data.pop("reader_prefs_migrated_v5", None)

    reader._migrate_reader_prefs_v5()
    assert reader._reader_prefs()["page_mode"] == "spread"
    assert settings.data["reader_prefs_migrated_v5"] == 1

    # 第二次：标记已存在，不再迁移（即便手动改回 column_count=2）。
    settings.data["reader"]["page_mode"] = "single"
    reader._migrate_reader_prefs_v5()
    assert reader._reader_prefs()["page_mode"] == "single"

    # 迁移已持久化到磁盘。
    reloaded = SettingsService(tmp_path / "config.json").data
    assert reloaded.get("reader_prefs_migrated_v5") == 1


# ---- R2 · 单页 / 双页（摊开） ------------------------------------
def test_r2_page_mode_combo_writes_prefs(reader, settings):
    assert reader.prefs_columns.itemText(0) == "单页"
    assert reader.prefs_columns.itemData(0) == "single"
    assert reader.prefs_columns.itemText(1) == "双页（摊开）"
    assert reader.prefs_columns.itemData(1) == "spread"

    reader.prefs_columns.setCurrentIndex(1)  # currentIndexChanged → 写 spread
    assert settings.data["reader"]["page_mode"] == "spread"

    reader.prefs_columns.setCurrentIndex(0)  # → 写回 single
    assert settings.data["reader"]["page_mode"] == "single"


def test_r2_sync_widgets_uses_page_mode(reader, settings):
    settings.data["reader"]["page_mode"] = "spread"
    reader._sync_prefs_widgets()
    assert reader.prefs_columns.currentData() == "spread"


def test_r2_page_label_spread(reader):
    reader._book_id = 1
    reader._location = {"page": 16, "total": 200}

    reader._spread_active = False
    reader._update_page_label()
    assert reader.page_label.text() == "16 / 200"
    assert reader.page_input.text() == "16"

    reader._spread_active = True
    reader._update_page_label()
    assert reader.page_label.text() == "16–17 / 200"  # 摊开显示左右页范围


def test_r2_narrow_window_disables_spread_option(reader, settings):
    reader._book_id = 1
    settings.data["reader"]["page_mode"] = "spread"

    reader._on_spread_changed(1, False)  # 用户要双页，但窗口太窄
    assert reader._spread_active is False
    item = reader.prefs_columns.model().item(1)
    assert item.isEnabled() is False
    assert "太窄" in item.toolTip()

    reader._on_spread_changed(1, True)  # 窗口变宽，双页恢复生效
    assert item.isEnabled() is True
    assert item.toolTip() == ""


def test_r2_spread_signal_ignores_other_book(reader, settings):
    reader._book_id = 1
    settings.data["reader"]["page_mode"] = "spread"
    reader._on_spread_changed(2, False)  # 不是当前书，应忽略
    assert reader._spread_active is False
    assert reader.prefs_columns.model().item(1).isEnabled() is True

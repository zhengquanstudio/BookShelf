"""T7：统一主题 token 与设置页 6 分区的覆盖测试。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.services.settings_service import SettingsService
from app.ui.dialogs.settings_dialog import SettingsDialog
from app.ui.theme import (
    ACCENT_NAMES,
    BASE_THEME_NAMES,
    accent_tokens,
    chrome_tokens,
    is_light_theme,
    load_stylesheet,
    normalize_accent,
    normalize_theme,
)


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def test_normalize_theme_resolves_aliases() -> None:
    assert normalize_theme("dark") == "night"
    assert normalize_theme("light") == "gray"  # 旧“浅色”兼容到冷灰调
    assert normalize_theme("paper") == "paper"
    assert normalize_theme("Night") == "night"
    assert normalize_theme("") == "night"
    assert normalize_theme("bogus") == "night"
    assert set(BASE_THEME_NAMES) == {"paper", "gray", "night"}


def test_normalize_accent_and_light_detection() -> None:
    assert normalize_accent("Green") == "green"
    assert normalize_accent("bogus") == "blue"
    assert set(ACCENT_NAMES) == {"blue", "green", "purple", "amber", "rose"}

    for light in ("paper", "gray", "light"):
        assert is_light_theme(light) is True
    for dark in ("night", "dark", ""):
        assert is_light_theme(dark) is False


def test_chrome_tokens_shape() -> None:
    keys = {
        "bg", "panel", "panel2", "hover", "sidebar",
        "ink", "muted", "faint", "line", "line2", "scroll",
        "accent", "accent_soft", "accent_ink", "accent_rgb",
        "ok", "warn", "bad", "error",
    }
    tokens = chrome_tokens("night", "blue")
    assert keys.issubset(tokens.keys())

    # blue 随底色变化：夜间更亮，浅色更深。
    assert chrome_tokens("night", "blue")["accent"] == "#6d93ff"
    assert chrome_tokens("paper", "blue")["accent"] == "#3b6ef5"
    assert chrome_tokens("gray", "blue")["accent"] == "#3b6ef5"
    # 其余强调色固定。
    assert accent_tokens("night", "green")["hex"] == "#2f9e6e"
    assert accent_tokens("paper", "amber")["hex"] == "#c88a2a"


def test_load_stylesheet_base_hexes() -> None:
    night = load_stylesheet("night")
    paper = load_stylesheet("paper")
    gray = load_stylesheet("gray")

    assert "#17181b" in night
    assert "#efe9dd" not in night
    assert "#17181b" not in paper
    assert "#efe9dd" in paper
    assert "#17181b" not in gray
    assert "#f3f5f7" in gray
    # light 别名等价于 gray。
    assert load_stylesheet("light") == gray


def test_load_stylesheet_accent_remap() -> None:
    night_blue = load_stylesheet("night", "blue")
    night_green = load_stylesheet("night", "green")

    # 默认夜间蓝把 QSS 原稿的 #4f8cf7 替换为 #6d93ff。
    assert "#6d93ff" in night_blue
    assert "#4f8cf7" not in night_blue

    # 绿色强调色：hex 与 rgba 都被替换。
    assert "#2f9e6e" in night_green
    assert "rgba(47, 158, 110," in night_green
    assert "#4f8cf7" not in night_green
    assert "rgba(79, 140, 247," not in night_green

    # 纸白 + 紫色：浅色用更深的墨色作为 accent_ink。
    paper_purple = load_stylesheet("paper", "purple")
    assert "#7a63d6" in paper_purple


def test_settings_dialog_six_sections_and_instant_accent(qapp, tmp_path) -> None:
    settings = SettingsService(tmp_path / "config.json")
    library_root = tmp_path / "library"
    library_root.mkdir()
    settings.set_library_root(str(library_root))

    dialog = SettingsDialog(None, settings)
    try:
        assert dialog.nav.count() == 6
        assert [name for _k, name in [
            ("appearance", "外观与主题"),
            ("reader", "阅读设置"),
            ("library", "书库与整理"),
            ("sources", "识别来源"),
            ("fonts", "字体"),
            ("about", "关于"),
        ]]
        assert dialog._page_keys == [
            "appearance", "reader", "library", "sources", "fonts", "about",
        ]

        # 即时切换强调色：写入 settings 并发出 applied。
        emitted = {"n": 0}
        dialog.applied.connect(lambda: emitted.__setitem__("n", emitted["n"] + 1))
        dialog._select_accent("green")
        assert settings.data["ui"]["accent"] == "green"
        assert settings.data["ui"]["theme"] == dialog._selected_theme
        assert emitted["n"] == 1

        dialog._select_theme("paper")
        assert settings.data["ui"]["theme"] == "paper"
        assert settings.data["ui"]["accent"] == "green"  # 不被覆盖

        collected = dialog._collect()
        assert collected["ui"]["theme"] == "paper"
        assert collected["ui"]["accent"] == "green"
        assert "nav_width" in collected["ui"]
    finally:
        dialog.close()

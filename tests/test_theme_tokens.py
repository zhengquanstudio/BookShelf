"""阅读器主题 token 的唯一来源与推导规则。"""

import re

import pytest

from app.ui.theme_tokens import PALETTES, THEME_KEYS, mix, palette_for

_HEX = re.compile(r"^#[0-9a-f]{6}$")


def test_eight_palettes_with_unique_keys():
    assert len(PALETTES) == 8
    assert len(THEME_KEYS) == 8
    assert len(set(THEME_KEYS)) == 8
    assert "sunset" in PALETTES and "dark" in PALETTES


@pytest.mark.parametrize("key", THEME_KEYS)
def test_palette_fields_are_valid_colors(key):
    palette = PALETTES[key]
    for field in ("page", "ink", "muted", "chrome", "canvas", "border", "accent", "panel"):
        assert _HEX.match(getattr(palette, field)), f"{key}.{field}={getattr(palette, field)}"


def test_canvas_is_derived_not_hand_copied():
    for key, palette in PALETTES.items():
        if key == "dark":
            assert palette.canvas == mix("#000000", palette.page, 0.75)
        else:
            assert palette.canvas == mix(palette.ink, palette.page, 0.10)
        assert palette.canvas != palette.page


def test_panel_sits_between_page_and_ink():
    for palette in PALETTES.values():
        assert palette.panel == mix(palette.ink, palette.page, 0.035)


def test_legacy_and_unknown_keys_fall_back():
    assert palette_for("paper").key == "light"
    assert palette_for("night").key == "dark"
    assert palette_for("dark").key == "dark"
    assert palette_for(None).key == "light"
    assert palette_for("not-a-theme").key == "light"

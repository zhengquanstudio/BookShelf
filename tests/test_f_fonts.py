"""F1/F2 内置字体清单与字体下拉（不加载 WebEngine，仅校验清单与 UI 接线）。"""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import app.ui.pages.reader_container as rc
from app.services.settings_service import SettingsService
from app.ui.pages.reader_container import ReaderContainer


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture()
def reader(qapp, db, tmp_path):
    return ReaderContainer(db, SettingsService(tmp_path / "config.json"), web_enabled=False)


def test_catalog_loads_eight_fonts_in_two_groups() -> None:
    catalog = rc._font_catalog()
    assert len(catalog) == 8
    groups: dict[str, list[str]] = {}
    for font in catalog:
        groups.setdefault(font["group"], []).append(font["family"])
    assert len(groups["中文"]) == 4
    assert len(groups["English"]) == 4


def test_default_fonts() -> None:
    assert rc._default_font_family("中文", "x") == "LXGW WenKai"
    assert rc._default_font_family("English", "x") == "Literata"
    assert rc._default_font_family("不存在", "fallback") == "fallback"


def test_catalog_marks_missing_font_files(tmp_path, monkeypatch) -> None:
    """字体文件缺失的项被标记 missing（用于置灰），存在的不标记。"""
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir()
    (fonts_dir / "fonts.json").write_text(json.dumps({"fonts": [
        {"key": "a", "label": "A", "group": "中文", "family": "A", "file": "a.ttf", "default": True},
        {"key": "b", "label": "B", "group": "中文", "family": "B", "file": "b.ttf"},
    ]}), encoding="utf-8")
    (fonts_dir / "a.ttf").write_bytes(b"x")  # a 存在，b 缺失
    monkeypatch.setattr(rc, "ASSETS_DIR", tmp_path)
    monkeypatch.setattr(rc, "_FONT_CATALOG", None)

    catalog = rc._font_catalog()
    by_family = {f["family"]: f for f in catalog}
    assert by_family["A"]["missing"] is False
    assert by_family["B"]["missing"] is True


def test_reader_has_dual_font_combos(reader) -> None:
    assert reader.prefs_font_cjk.count() == 4
    assert reader.prefs_font_latin.count() == 4
    prefs = reader._reader_prefs()
    assert prefs["reader_font_cjk"] == "LXGW WenKai"
    assert prefs["reader_font_latin"] == "Literata"


def test_font_switch_updates_prefs_without_rebuild(reader) -> None:
    """切换字体只更新 prefs（web_enabled=False 下不走网络），值持久化到 settings。"""
    index = reader.prefs_font_cjk.findData("Source Han Serif CN")
    assert index >= 0
    reader.prefs_font_cjk.setCurrentIndex(index)
    assert reader._reader_prefs()["reader_font_cjk"] == "Source Han Serif CN"

    index = reader.prefs_font_latin.findData("EB Garamond")
    reader.prefs_font_latin.setCurrentIndex(index)
    assert reader._reader_prefs()["reader_font_latin"] == "EB Garamond"

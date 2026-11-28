# -*- coding: utf-8 -*-
"""T18：阅读设置弹窗接入 ReaderContainer —— 打开即同步当前状态，改动即时落库。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.services.settings_service import SettingsService
from app.ui.dialogs.reader_prefs_dialog import ReaderPrefsDialog
from app.ui.pages.reader_container import ReaderContainer


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


def test_show_prefs_opens_dialog_with_current_snapshot(reader):
    reader._show_prefs()
    dlg = reader._prefs_dialog
    assert isinstance(dlg, ReaderPrefsDialog)
    assert dlg.isVisible()
    assert dlg._prefs["font_size"] == 17
    assert dlg._prefs["line_height"] == pytest.approx(1.95)
    dlg.reject()
    assert reader._prefs_dialog is None


def test_dialog_changed_live_applies_to_settings_and_widgets(reader):
    reader._show_prefs()
    dlg = reader._prefs_dialog
    dlg.changed.emit({"font_size": 23, "line_height": 2.0})
    assert reader.settings.data["reader"]["font_size"] == 23
    assert reader.settings.data["reader"]["line_height"] == pytest.approx(2.0)
    # 顶栏字号步进器同步刷新
    assert reader.font_stepper.value() == 23
    dlg.reject()
    assert reader._prefs_dialog is None


def test_show_prefs_reuses_already_open_dialog(reader):
    reader._show_prefs()
    first = reader._prefs_dialog
    reader._show_prefs()
    assert reader._prefs_dialog is first
    first.reject()
    assert reader._prefs_dialog is None

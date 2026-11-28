"""T12：24 段墨点进度条（自绘，可点击/拖动 seek）。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.ui.theme_tokens import palette_for
from app.ui.widgets.ink_dot_progress import InkDotProgress


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def test_value_clamps_to_0_1000_and_emits_changed(qapp):
    w = InkDotProgress()
    w.resize(520, 20)
    seen: list[int] = []
    w.valueChanged.connect(seen.append)
    w.setValue(500)
    assert w.value() == 500
    w.setValue(2000)
    assert w.value() == 1000
    w.setValue(-5)
    assert w.value() == 0
    assert 500 in seen and 1000 in seen


def test_click_seeks_by_fraction_and_emits_release(qapp):
    w = InkDotProgress()
    w.resize(520, 20)
    seen: list[int] = []
    released: list[int] = []
    w.valueChanged.connect(seen.append)
    w.sliderReleased.connect(lambda: released.append(1))
    QTest.mouseClick(w, Qt.LeftButton, pos=QPoint(260, 10))
    assert 490 <= w.value() <= 510
    assert released == [1]


def test_paint_survives_theme_change(qapp):
    w = InkDotProgress()
    w.resize(520, 20)
    w.apply_palette(palette_for("dark"))
    w.setValue(250)
    pix = w.grab()
    assert not pix.isNull()

"""S3/S6 阅读器界面：图标按钮、侧栏三 tab、目录页码、分段进度与底栏信息。"""

from __future__ import annotations

import json
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.db.repositories.book_repo import BookRepository
from app.db.repositories.reading_repo import ReadingRepository
from app.services.settings_service import SettingsService
from app.ui.pages.reader_container import ReaderContainer
from app.ui.widgets.icon_button import IconButton
from app.ui.widgets.segmented_progress import SegmentedProgress


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


def _add_book(db, path) -> int:
    return BookRepository(db).create(
        file_path=str(path),
        quick_hash=path.stem,
        format=path.suffix.lstrip("."),
        title="测试书",
        author_raw="测试作者",
        status="ok",
    )


def test_icon_button_renders_svg_and_recolors(qapp):
    button = IconButton("search", "搜索")
    assert button.objectName() == "ReaderIconButton"
    assert (button.width(), button.height()) == (36, 36)
    assert not button.icon().isNull()

    button.set_icon_color("#c05a78")
    assert not button.icon().isNull()
    # 缺图不应崩溃，只保留空图标占位。
    fallback = IconButton("not-exists", "占位")
    assert fallback.icon().isNull()


def test_segmented_progress_click_previews_and_releases(qapp):
    progress = SegmentedProgress()
    progress.resize(200, 20)
    released: list[int] = []
    changed: list[int] = []
    progress.sliderReleased.connect(lambda: released.append(progress.value()))
    progress.valueChanged.connect(changed.append)

    QTest.mouseClick(progress, Qt.LeftButton, pos=QPoint(100, 10))
    assert abs(progress.value() - 500) <= 2
    assert released and released[-1] == progress.value()
    assert changed
    # 自绘分支要能正常渲染，不能抛异常。
    pixmap = progress.grab()
    assert pixmap.width() == 200


def test_sidebar_three_tabs_and_notes_page(reader, db, tmp_path):
    assert [button.text() for button in reader.sidebar_tabs] == ["目录", "笔记", "书签"]
    assert reader.sidebar_stack.count() == 3

    book_id = _add_book(db, tmp_path / "notes.epub")
    ReadingRepository(db).add_bookmark(
        book_id,
        '{"type":"epub","cfiRange":"epubcfi(/6/4!/2/1)"}',
        text="选中的句子",
        note="想法",
        kind="highlight",
    )
    reader._book_id = book_id
    reader._select_sidebar_tab(1)
    assert reader.sidebar_stack.currentIndex() == 1
    assert reader.note_tab_button.isChecked()
    assert reader.note_list.count() == 1
    assert "选中的句子" in reader.note_list.item(0).text()

    reader._select_sidebar_tab(2)
    assert reader.bookmark_tab_button.isChecked()
    assert reader.bookmark_button.isChecked()


def test_toc_rows_show_number_and_visited_page(reader):
    reader._book_id = 0
    reader._set_toc(
        [
            {"label": "第一章", "href": "c1.xhtml", "level": 0},
            {"label": "第二章", "href": "c2.xhtml", "level": 1},
        ]
    )
    first = reader.toc_list.item(0)
    second = reader.toc_list.item(1)
    assert first.data(Qt.UserRole) == "c1.xhtml"
    assert first.data(Qt.UserRole + 4) == 1
    assert first.data(Qt.UserRole + 5) == 0
    assert second.data(Qt.UserRole + 5) == 1
    # 未访问章节显示 ~，行高按 34 绘制。
    assert first.data(Qt.UserRole + 3) == "~"
    assert reader.toc_list.sizeHintForRow(0) == 34

    reader._on_location(
        0,
        json.dumps(
            {
                "label": "第一章",
                "href": "c1.xhtml",
                "page": 7,
                "total": 120,
                "percent": 0.06,
                "sectionSeconds": 0,
            }
        ),
    )
    assert reader.toc_list.item(0).data(Qt.UserRole + 3) == "7"
    assert reader.toc_list.currentRow() == 0
    assert reader.page_label.text() == "7 / 120"


def test_bottom_bar_info_clock_and_remaining(reader, db, tmp_path):
    from app.ui.widgets.ink_dot_progress import InkDotProgress

    assert reader.bottombar.height() == 38
    assert reader.progress_slider is reader.progress
    assert isinstance(reader.progress, InkDotProgress)
    assert reader.battery.width() == 20
    assert reader.page_input.objectName() == "ReaderPageInput"
    assert reader.font_stepper.value() == 19
    assert re.match(r"^\d{2}:\d{2}$", reader.clock_label.text())

    # 没有阅读统计时只显示破折号。
    reader._book_id = 0
    reader._update_remaining(120)
    assert reader.remaining_label.text() == "本章剩余 —"

    book_id = _add_book(db, tmp_path / "stats.epub")
    ReadingRepository(db).save_progress(book_id, "{}", 0.25, seconds_delta=120)
    reader._book_id = book_id
    reader._location = {"page": 25, "total": 100, "percent": 0.25}
    reader._update_remaining(120)
    assert "分钟" in reader.remaining_label.text()
    assert "页" in reader.remaining_label.text()


def test_header_footer_flags_hide_groups(reader, settings):
    settings.data["reader"]["header_footer"] = {
        "remaining_time": False,
        "remaining_pages": False,
        "progress": False,
        "clock": False,
        "clock_24h": False,
        "battery": False,
    }
    reader._apply_theme()
    assert reader.clock_label.isHidden()
    assert reader.progress.isHidden()
    assert reader.remaining_label.isHidden()
    assert reader._reader_prefs()["header_footer"]["clock"] is False


def test_theme_and_motion_segments(reader, settings):
    # 模式：浅色 / 深色 / 跟随系统；动效五档；纹理三档。
    assert list(reader.mode_buttons) == ["light", "dark", "auto"]
    assert len(reader.turn_buttons) == 5
    assert len(reader.texture_buttons) == 3

    reader._on_turn_selected("curl")
    assert settings.data["reader"]["turn_style"] == "curl"
    assert reader.turn_buttons["curl"].isChecked()
    assert not reader.turn_buttons["push"].isChecked()
    assert "520ms" in reader.turn_buttons["curl"].toolTip()

    reader._on_mode_selected("dark")
    assert settings.data["reader"]["mode"] == "dark"
    assert reader.mode_buttons["dark"].isChecked()
    assert reader._reader_prefs()["palette"]["key"] == "dark"

    reader._on_texture_selected("noise")
    assert settings.data["reader"]["texture"] == "noise"
    assert reader.texture_buttons["noise"].isChecked()

    reader._update_prefs(accent="#c05a78")
    assert "C05A78" in reader.prefs_accent_value.text()

    # 点色卡要立即看到所选颜色：樱粉把模式切回浅色，夜读切深色。
    reader._select_theme("cherry")
    assert settings.data["reader"]["theme"] == "cherry"
    assert settings.data["reader"]["mode"] == "light"
    assert reader.theme_swatches["cherry"].isChecked()
    reader._select_theme("dark")
    assert settings.data["reader"]["mode"] == "dark"
    assert reader.theme_swatches["dark"].isChecked()
    assert reader._prefs_fade.duration() == 160


def test_sidebar_collapse_animation_toggles(qapp, reader):
    assert reader._sidebar_anim.duration() == 160
    assert not reader.sidebar.isHidden()

    reader._show_sidebar(False)
    QTest.qWait(240)
    assert reader.sidebar.isHidden()
    assert not reader._sidebar_visible
    assert not reader.toc_button.isChecked()

    reader._toggle_toc()
    QTest.qWait(240)
    assert not reader.sidebar.isHidden()
    assert reader._sidebar_visible
    assert reader.toc_button.isChecked()


def test_t10_sidebar_width_is_288(reader):
    # v3 原型：阅读左栏固定 288px。
    assert reader._sidebar_width == 288
    assert reader.sidebar.maximumWidth() == 288


def test_t10_toc_current_row_paints_position_tag(qapp):
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QPainter, QPixmap
    from PySide6.QtWidgets import (
        QListWidget,
        QListWidgetItem,
        QStyle,
        QStyleOptionViewItem,
    )

    from app.ui.pages.reader_container import _TocItemDelegate
    from app.ui.theme_tokens import palette_for

    theme = palette_for("light")
    delegate = _TocItemDelegate(lambda: theme)
    lw = QListWidget()
    lw.addItem(QListWidgetItem("第三章"))
    index = lw.indexFromItem(lw.item(0))

    def render(selected: bool):
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 288, 34)
        option.state = (
            QStyle.State_Enabled | QStyle.State_Selected
            if selected else QStyle.State_Enabled
        )
        pix = QPixmap(288, 34)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        delegate.paint(painter, option, index)
        painter.end()
        return pix.toImage()

    def accent_in_right_band(img) -> bool:
        accent = QColor(theme.accent).name().lower()
        for x in range(288 - 64, 288):
            for y in range(34):
                if img.pixelColor(x, y).name().lower() == accent:
                    return True
        return False

    # 当前章右侧画出强调色「当前位置」胶囊；非当前章右侧无强调色。
    assert accent_in_right_band(render(True))
    assert not accent_in_right_band(render(False))

"""阅读器设置弹窗（T14）：居中 660px、圆角 18、半透明遮罩，6 个图标页签。

页签与卡片严格对齐 `docs/书格-阅读界面原型-v3-1.1.6.html` 与
`docs/书格-1.1.6-阅读界面v3-给TRAE.md` 第三节表格。控件统一「左标签 + 右控件」，
开关用自绘 Toggle，数值用 Stepper。改动写入 settings 并经 `changed` 信号外抛，
由 reader_container（T18）接管落库与即时生效。
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QMouseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.ui.theme_tokens import (
    HIGHLIGHT_COLORS,
    HIGHLIGHT_LIGHT,
    PALETTES,
    ReaderPalette,
    mix,
    palette_for,
)
from app.ui.widgets.stepper import Stepper

# 页签顺序与原型一致：主题 / 字体 / 布局 / 阅读 / 手势 / 其他。
_TAB_ORDER: list[tuple[str, str, str]] = [
    ("theme", "主题", "◎"),
    ("font", "字体", "Aa"),
    ("layout", "布局", "▦"),
    ("read", "阅读", "▤"),
    ("gesture", "手势", "✋"),
    ("about", "其他", "⋯"),
]

_CJK_FONTS = ["LXGW WenKai", "Noto Serif CJK SC", "Source Han Serif SC", "Literata"]
_LATIN_FONTS = ["Literata", "Georgia", "Noto Sans SC", "Inter", "Roboto"]
_MONO_FONTS = ["Consolas", "JetBrains Mono", "Courier New"]


class Toggle(QPushButton):
    """自绘开关：左侧标签由父布局提供，这里只画轨道 + 圆点。"""

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(38, 22)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setObjectName("ReaderToggle")

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        track = QColor("#3f6fa8") if on else QColor("#c9c4b8")
        painter.setBrush(track)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, 38, 22, 11, 11)
        painter.setBrush(QColor("#ffffff"))
        x = 19 if on else 2
        painter.drawEllipse(x, 2, 18, 18)


class Segmented(QWidget):
    """等分分段按钮组（互斥）。"""

    valueChanged = Signal(str)

    def __init__(
        self, options: list[tuple[str, str]], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._value: str = options[0][0] if options else ""
        self.setObjectName("ReaderSegmented")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for value, label in options:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            button.setObjectName("SegBtn")
            button.clicked.connect(lambda _=False, v=value: self._select(v))
            layout.addWidget(button)
            self._group.addButton(button)
            self._buttons[value] = button

    def value(self) -> str:
        return self._value

    def set_value(self, value: str, *, emit: bool = False) -> None:
        value = value if value in self._buttons else self._value
        self._value = value
        for v, button in self._buttons.items():
            button.setChecked(v == value)
        if emit:
            self.valueChanged.emit(value)

    def _select(self, value: str) -> None:
        if value == self._value:
            return
        self.set_value(value, emit=True)


class _ThemeCard(QPushButton):
    def __init__(self, key: str, palette: ReaderPalette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self._palette = palette
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(72, 84)
        self.setObjectName("ThemeCard")

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        p = self._palette
        painter.setBrush(QColor(p.page))
        painter.setPen(QColor(p.border))
        painter.drawRoundedRect(1, 1, 70, 82, 10, 10)
        painter.setPen(QColor(p.ink))
        painter.setFont(self.font())
        f = painter.font()
        f.setPointSize(16)
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(0, 8, 72, 40, Qt.AlignCenter, "Aa")
        f.setPointSize(9)
        f.setBold(False)
        painter.setFont(f)
        painter.setPen(QColor(p.muted))
        painter.drawText(0, 52, 72, 28, Qt.AlignCenter, p.label)
        if self.isChecked():
            painter.setPen(QColor(p.accent))
            pen = painter.pen()
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(2, 2, 68, 80, 9, 9)


class _HlDot(QPushButton):
    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(28, 28)
        self.setObjectName("HlDot")
        self._color = HIGHLIGHT_LIGHT[name]

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(self._color))
        painter.setPen(QColor("rgba(0,0,0,0.25)"))
        painter.drawEllipse(1, 1, 26, 26)
        if self.isChecked():
            painter.setPen(QColor("#ffffff"))
            pen = painter.pen()
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawEllipse(1, 1, 26, 26)


class ReaderPrefsDialog(QDialog):
    """阅读器居中设置弹窗。"""

    changed = Signal(dict)

    def __init__(
        self,
        settings: Any,
        palette: ReaderPalette,
        prefs: dict[str, Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self._palette = palette
        self._prefs: dict[str, Any] = {}
        self._loading = False
        # (key, widget, kind, default) — load_prefs 据此刷新，不触发 changed。
        self._bound: list[tuple[str, Any, str, Any]] = []
        self.setObjectName("ReaderPrefsDialog")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.resize(660, 560)

        self._build_ui()
        self.load_prefs(prefs)
        self.apply_palette(palette)

    # ---- 构建 -------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._panel = QFrame(self)
        self._panel.setObjectName("ReaderPrefsPanel")
        outer.addWidget(self._panel)

        root = QVBoxLayout(self._panel)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(10)

        # 顶部：页签 + 标题 + 关闭
        head = QHBoxLayout()
        head.setSpacing(4)
        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        self._tab_buttons: dict[str, QPushButton] = {}
        for key, _title, glyph in _TAB_ORDER:
            button = QPushButton(glyph)
            button.setCheckable(True)
            button.setFixedSize(38, 34)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            button.setObjectName("PrefsTab")
            button.setToolTip(_title)
            button.clicked.connect(lambda _=False, k=key: self._switch_tab(k))
            head.addWidget(button)
            self._tab_group.addButton(button)
            self._tab_buttons[key] = button
        head.addStretch(1)
        self._title_label = QLabel("主题")
        self._title_label.setObjectName("PrefsTitle")
        head.addWidget(self._title_label)
        self._close_button = QPushButton("✕")
        self._close_button.setFixedSize(28, 28)
        self._close_button.setCursor(Qt.PointingHandCursor)
        self._close_button.setFocusPolicy(Qt.NoFocus)
        self._close_button.setObjectName("PrefsClose")
        self._close_button.clicked.connect(self.reject)
        head.addWidget(self._close_button)
        root.addLayout(head)

        self._stack = QStackedWidget()
        self._stack.setObjectName("PrefsStack")
        root.addWidget(self._stack, 1)

        self._panes: dict[str, QWidget] = {}
        self._panes["theme"] = self._build_theme_pane()
        self._panes["font"] = self._build_font_pane()
        self._panes["layout"] = self._build_layout_pane()
        self._panes["read"] = self._build_read_pane()
        self._panes["gesture"] = self._build_gesture_pane()
        self._panes["about"] = self._build_about_pane()
        for key, _t, _g in _TAB_ORDER:
            self._stack.addWidget(self._panes[key])

    # ---- 通用构建块 -------------------------------------------------
    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("PrefsSect")
        return label

    def _card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("PrefsCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)
        return frame

    def _row(self, card: QFrame, label_text: str, control: QWidget, note: str = "") -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        label = QLabel(label_text)
        label.setObjectName("PrefsLabel")
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        label.setWordWrap(True)
        row.addWidget(label, 1)
        if note:
            hint = QLabel(note)
            hint.setObjectName("PrefsHint")
            row.addWidget(hint)
        row.addWidget(control, 0, Qt.AlignVCenter)
        card.layout().addLayout(row)

    def _toggle(self, key: str, default: bool = False) -> Toggle:
        widget = Toggle(self._get(key, default))
        widget.toggled.connect(lambda on: self._set(key, bool(on)))
        self._bound.append((key, widget, "toggle", default))
        return widget

    def _toggle_hf(self, subkey: str, default: bool = False) -> Toggle:
        widget = Toggle(self._get_hf(subkey, default))
        widget.toggled.connect(lambda on: self._set_hf(subkey, bool(on)))
        self._bound.append((subkey, widget, "hf", default))
        return widget

    def _stepper(
        self,
        key: str,
        default: float,
        lo: float,
        hi: float,
        step: float,
        decimals: int = 0,
    ) -> Stepper:
        widget = Stepper(lo, hi, step, float(self._get(key, default)), decimals=decimals)
        widget.changed.connect(lambda v: self._set(key, v))
        self._bound.append((key, widget, "stepper", default))
        return widget

    def _segmented(
        self, key: str, options: list[tuple[str, str]], default: str
    ) -> Segmented:
        widget = Segmented(options)
        widget.set_value(str(self._get(key, default)))
        widget.valueChanged.connect(lambda v: self._set(key, v))
        self._bound.append((key, widget, "segmented", default))
        return widget

    def _combo(
        self, key: str, options: list[tuple[str, str]], default: str
    ) -> QComboBox:
        widget = QComboBox()
        widget.setObjectName("PrefsCombo")
        widget.setMinimumWidth(150)
        current = str(self._get(key, default))
        for value, label in options:
            widget.addItem(label, value)
        index = widget.findData(current)
        if index < 0 and current:
            widget.addItem(current, current)
            index = widget.count() - 1
        if index >= 0:
            widget.setCurrentIndex(index)
        widget.currentIndexChanged.connect(
            lambda _i: self._set(key, widget.currentData())
        )
        self._bound.append((key, widget, "combo", default))
        return widget

    # ---- 各页签 -----------------------------------------------------
    def _build_theme_pane(self) -> QWidget:
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setObjectName("PrefsScroll")
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(8)

        layout.addWidget(self._section("主题模式"))
        card = self._card()
        self._row(card, "跟随系统 / 浅色 / 深色",
                 self._segmented("mode", [("auto", "跟随系统"), ("light", "浅色"),
                                          ("dark", "深色")], "auto"))
        self._row(card, "深色主题下图片反色", self._toggle("invert_images_dark", False))
        self._row(card, "透明图片背景", self._toggle("transparent_image_bg", False))
        self._row(card, "覆盖书籍颜色", self._toggle("override_book_colors", False))
        layout.addWidget(card)

        layout.addWidget(self._section("主题颜色"))
        self._theme_grid = QFrame()
        self._theme_grid.setObjectName("ThemeGrid")
        grid = QHBoxLayout(self._theme_grid)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        self._theme_cards: dict[str, _ThemeCard] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, palette in PALETTES.items():
            card = _ThemeCard(key, palette)
            card.clicked.connect(lambda _=False, k=key: self._pick_theme(k))
            grid.addWidget(card)
            group.addButton(card)
            self._theme_cards[key] = card
        grid.addStretch(1)
        layout.addWidget(self._theme_grid)

        layout.addWidget(self._section("高亮颜色"))
        card = self._card()
        hl_host = QWidget()
        hl_row = QHBoxLayout(hl_host)
        hl_row.setContentsMargins(0, 0, 0, 0)
        hl_row.setSpacing(8)
        self._hl_dots: dict[str, _HlDot] = {}
        hl_group = QButtonGroup(self)
        hl_group.setExclusive(True)
        for name in HIGHLIGHT_COLORS:
            dot = _HlDot(name)
            dot.clicked.connect(lambda _=False, n=name: self._pick_highlight(n))
            hl_row.addWidget(dot)
            hl_group.addButton(dot)
            self._hl_dots[name] = dot
        hl_row.addStretch(1)
        self._row(card, "标注与批注颜色", hl_host)
        layout.addWidget(card)

        layout.addStretch(1)
        page.setWidget(host)
        return page

    def _build_font_pane(self) -> QWidget:
        page = self._scroll_host()
        layout = page.layout()

        card = self._card()
        self._row(card, "覆盖书籍字体", self._toggle("override_font", False))
        layout.addWidget(card)

        layout.addWidget(self._section("字号"))
        card = self._card()
        self._row(card, "默认字号", self._stepper("font_size", 19, 10, 40, 1))
        self._row(card, "最小字号", self._stepper("min_font_size", 8, 6, 14, 1))
        self._row(card, "正文字重", self._stepper("font_weight", 400, 100, 900, 100))
        layout.addWidget(card)

        layout.addWidget(self._section("首选字体"))
        card = self._card()
        self._row(card, "字体类别", self._combo("font_category",
                 [("serif", "衬线字体"), ("sans", "无衬线字体")], "serif"))
        self._row(card, "衬线字体", self._combo("reader_font_cjk",
                 [(f, f) for f in _CJK_FONTS], _CJK_FONTS[0]))
        self._row(card, "忽略出版方字体名称", self._toggle("ignore_publisher_fonts", True))
        self._row(card, "无衬线字体", self._combo("reader_font_sans",
                 [(f, f) for f in _LATIN_FONTS], _LATIN_FONTS[0]))
        self._row(card, "等宽字体", self._combo("reader_font_mono",
                 [(f, f) for f in _MONO_FONTS], _MONO_FONTS[0]))
        layout.addWidget(card)

        card = self._card()
        preview = QLabel(
            "掉剪掉，枯枝反而培育起来呢？\nA quiet, deliberate rhythm of reading."
        )
        preview.setObjectName("FontPreview")
        preview.setWordWrap(True)
        card.layout().addWidget(preview)
        layout.addWidget(card)
        layout.addStretch(1)
        return self._finish_scroll(page)

    def _build_layout_pane(self) -> QWidget:
        page = self._scroll_host()
        layout = page.layout()

        card = self._card()
        self._row(card, "覆盖版面布局", self._toggle("override_layout", False))
        layout.addWidget(card)

        layout.addWidget(self._section("排版模式"))
        card = self._card()
        self._row(card, "段落样式", self._segmented("para_style", [
            ("justify_indent", "☰"), ("left", "≡"), ("indent", "¶"), ("hanging", "⌐"),
        ], "justify_indent"))
        layout.addWidget(card)

        layout.addWidget(self._section("段落"))
        card = self._card()
        self._row(card, "使用书籍排版", self._toggle("use_book_layout", False))
        self._row(card, "段间距", self._stepper("para_spacing", 0.75, 0, 3, 0.05, 2))
        self._row(card, "行间距", self._stepper("line_height", 1.9, 1, 3, 0.05, 2))
        self._row(card, "字间距", self._stepper("letter_spacing", 0, -2, 8, 0.1, 1))
        self._row(card, "首行缩进", self._stepper("indent", 2, 0, 4, 0.5, 1))
        self._row(card, "两端对齐", self._toggle("justify", True))
        self._row(card, "断字", self._toggle("hyphens", False))
        layout.addWidget(card)

        layout.addWidget(self._section("页面"))
        card = self._card()
        self._row(card, "上边距", self._stepper("margin_top", 48, 0, 240, 2))
        self._row(card, "下边距", self._stepper("margin_bottom", 48, 0, 240, 2))
        self._row(card, "左边距", self._stepper("margin_left", 56, 0, 240, 2))
        self._row(card, "右边距", self._stepper("margin_right", 56, 0, 240, 2))
        self._row(card, "页宽固定（文字重排不拉长书页）",
                 self._toggle("fixed_page_width", True))
        layout.addWidget(card)
        layout.addStretch(1)
        return self._finish_scroll(page)

    def _build_read_pane(self) -> QWidget:
        page = self._scroll_host()
        layout = page.layout()

        card = self._card()
        self._row(card, "翻页方式", self._segmented("scroll_mode",
                 [("page", "翻页"), ("scroll", "滚动")], "page"))
        self._row(card, "分栏", self._segmented("page_mode",
                 [("single", "单页"), ("spread", "双页摊开")], "single"))
        auto = self._toggle("auto_turn", False)
        self._row(card, "自动翻页", auto, "30 秒")
        self._row(card, "段滚模式", self._segmented("paragraph_scroll",
                 [("off", "关"), ("para", "按段")], "para"))
        layout.addWidget(card)

        layout.addWidget(self._section("状态栏"))
        card = self._card()
        self._row(card, "显示剩余时间与页数", self._toggle_hf("remaining_time", True))
        self._row(card, "显示时钟", self._toggle_hf("clock", True))
        self._row(card, "显示电池", self._toggle_hf("battery", False))
        self._row(card, "点击翻页区", self._segmented("click_zone",
                 [("left10", "左 10%"), ("left30", "左 30%"), ("full", "整屏")], "left30"))
        layout.addWidget(card)

        layout.addWidget(self._section("辅助"))
        card = self._card()
        self._row(card, "顶部遮罩（减少反光）", self._toggle("mask_top", True))
        self._row(card, "选中即朗读", self._toggle("select_to_read", False))
        self._row(card, "阅读尺", self._toggle("reading_ruler", False))
        layout.addWidget(card)
        layout.addStretch(1)
        return self._finish_scroll(page)

    def _build_gesture_pane(self) -> QWidget:
        page = self._scroll_host()
        layout = page.layout()
        card = self._card()
        self._row(card, "单击中央显示 / 隐藏工具栏",
                  self._toggle("tap_toggle_chrome", True))
        self._row(card, "双击缩放", self._toggle("double_click_zoom", False))
        self._row(card, "长按选词", self._toggle("long_press_select", True))
        self._row(card, "左右滑动翻页", self._toggle("swipe_turn", True))
        layout.addWidget(card)
        layout.addStretch(1)
        return self._finish_scroll(page)

    def _build_about_pane(self) -> QWidget:
        page = self._scroll_host()
        layout = page.layout()
        card = self._card()
        version = QLabel("书格 BookShelf 1.1.6")
        version.setObjectName("PrefsLabel")
        row = QHBoxLayout()
        row.addWidget(version, 1)
        tag = QLabel("GPL-3.0")
        tag.setObjectName("PrefsHint")
        row.addWidget(tag)
        card.layout().addLayout(row)
        layout.addWidget(card)
        layout.addStretch(1)
        return self._finish_scroll(page)

    # ---- 滚动页辅助 -------------------------------------------------
    def _scroll_host(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(8)
        return host

    def _finish_scroll(self, host: QWidget) -> QScrollArea:
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setObjectName("PrefsScroll")
        page.setWidget(host)
        return page

    # ---- 数据读写 ---------------------------------------------------
    def _defaults(self) -> dict[str, Any]:
        return dict(config.DEFAULT_CONFIG.get("reader", {}))

    def _get(self, key: str, default: Any) -> Any:
        if key in self._prefs:
            return self._prefs[key]
        defaults = self._defaults()
        if key in defaults:
            return defaults[key]
        return default

    def _get_hf(self, subkey: str, default: bool) -> bool:
        hf = self._prefs.get("header_footer")
        if isinstance(hf, dict) and subkey in hf:
            return bool(hf[subkey])
        defaults = self._defaults().get("header_footer", {})
        if isinstance(defaults, dict) and subkey in defaults:
            return bool(defaults[subkey])
        return default

    def _set(self, key: str, value: Any) -> None:
        if self._loading:
            return
        reader = self.settings.data.setdefault("reader", {})
        reader[key] = value
        try:
            self.settings.save()
        except Exception:  # noqa: BLE001 - 设置保存失败不应卡住 UI
            pass
        self.changed.emit({key: value})

    def _set_hf(self, subkey: str, value: bool) -> None:
        if self._loading:
            return
        reader = self.settings.data.setdefault("reader", {})
        hf = dict(reader.get("header_footer") or {})
        hf[subkey] = value
        reader["header_footer"] = hf
        try:
            self.settings.save()
        except Exception:  # noqa: BLE001
            pass
        self.changed.emit({"header_footer": hf})

    # ---- 外部入口 ---------------------------------------------------
    def load_prefs(self, prefs: dict[str, Any]) -> None:
        """用一份最新快照刷新控件（不触发 changed）。"""
        self._loading = True
        try:
            self._prefs = dict(prefs or {})
            self._refresh_bound()
            # 主题卡
            theme = str(self._get("theme", "light"))
            for key, card in self._theme_cards.items():
                card.setChecked(key == theme)
            # 高亮色点
            hl = str(self._get("highlight_color", "blue")).lower()
            for name, dot in self._hl_dots.items():
                dot.setChecked(name == hl)
            # 页签
            for key, button in self._tab_buttons.items():
                button.setChecked(False)
            first = _TAB_ORDER[0][0]
            if first in self._tab_buttons:
                self._tab_buttons[first].setChecked(True)
            self._switch_tab(first)
        finally:
            self._loading = False

    def _refresh_bound(self) -> None:
        """按当前 self._prefs 回填所有绑定控件（_loading 为真时不写库）。"""
        for key, widget, kind, default in self._bound:
            if kind == "toggle":
                widget.setChecked(bool(self._get(key, default)))
            elif kind == "hf":
                widget.setChecked(self._get_hf(key, default))
            elif kind == "stepper":
                widget.set_value(self._get(key, default))
            elif kind == "segmented":
                widget.set_value(str(self._get(key, default)))
            elif kind == "combo":
                current = str(self._get(key, default))
                idx = widget.findData(current)
                if idx < 0 and current:
                    widget.addItem(current, current)
                    idx = widget.count() - 1
                if idx >= 0:
                    widget.blockSignals(True)
                    widget.setCurrentIndex(idx)
                    widget.blockSignals(False)

    def apply_palette(self, palette: ReaderPalette) -> None:
        self._palette = palette
        for card in self._theme_cards.values():
            card._palette = palette if card.key == palette.key else PALETTES.get(
                card.key, palette
            )
            card.update()
        self.setStyleSheet(self._build_qss(palette))

    def _pick_theme(self, key: str) -> None:
        if self._loading:
            return
        for k, card in self._theme_cards.items():
            card.setChecked(k == key)
        self._set("theme", key)
        mode = str(self._get("mode", "auto"))
        self.apply_palette(palette_for(key, mode))

    def _pick_highlight(self, name: str) -> None:
        if self._loading:
            return
        for n, dot in self._hl_dots.items():
            dot.setChecked(n == name)
        self._set("highlight_color", name)

    def _switch_tab(self, key: str) -> None:
        for k, button in self._tab_buttons.items():
            button.setChecked(k == key)
        if key in self._panes:
            self._stack.setCurrentWidget(self._panes[key])
        titles = {k: t for k, t, _g in _TAB_ORDER}
        self._title_label.setText(titles.get(key, ""))

    # ---- 外观 -------------------------------------------------------
    @staticmethod
    def _build_qss(p: ReaderPalette) -> str:
        panel = p.canvas
        card = mix(p.ink, p.page, 0.045)
        return f"""
        #ReaderPrefsPanel {{
            background: {panel};
            border: 1px solid {p.border};
            border-radius: 18px;
        }}
        #PrefsTitle {{ color: {p.ink}; font-size: 14px; font-weight: 600; }}
        #PrefsTab {{
            background: transparent; color: {p.muted};
            border: 0; border-radius: 9px; font-size: 15px;
        }}
        #PrefsTab:hover {{ background: {mix(p.ink, p.page, 0.08)}; color: {p.ink}; }}
        #PrefsTab:checked {{
            background: {mix(p.accent, p.page, 0.16)}; color: {p.accent};
        }}
        #PrefsClose {{
            background: transparent; color: {p.muted};
            border: 0; border-radius: 8px; font-size: 14px;
        }}
        #PrefsClose:hover {{ background: {mix(p.ink, p.page, 0.1)}; color: {p.ink}; }}
        #PrefsSect {{
            color: {p.muted}; font-size: 11px; font-weight: 600;
            padding: 6px 4px 2px; letter-spacing: 1px;
        }}
        #PrefsCard {{
            background: {card}; border: 1px solid {mix(p.ink, p.page, 0.06)};
            border-radius: 12px;
        }}
        #PrefsLabel {{ color: {p.ink}; font-size: 13px; }}
        #PrefsHint {{ color: {p.muted}; font-size: 11px; }}
        #FontPreview {{
            color: {p.ink}; background: {p.page};
            border: 1px solid {p.border}; border-radius: 10px;
            padding: 12px; font-size: 15px; line-height: 1.6;
        }}
        #PrefsCombo {{
            background: {p.page}; color: {p.ink};
            border: 1px solid {p.border}; border-radius: 8px;
            padding: 4px 8px; min-height: 24px;
        }}
        #ReaderSegmented {{ background: transparent; }}
        #SegBtn {{
            background: {mix(p.ink, p.page, 0.05)}; color: {p.muted};
            border: 1px solid {p.border}; border-radius: 7px;
            padding: 4px 10px; font-size: 12px;
        }}
        #SegBtn:checked {{
            background: {p.page}; color: {p.ink}; font-weight: 600;
            border: 1px solid {p.accent};
        }}
        #PrefsScroll {{ border: 0; background: transparent; }}
        """

    # ---- 关闭：Esc / 点遮罩 / 右上 × --------------------------------
    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Escape, Qt.Key_Return):
            self.reject()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            if not self._panel.geometry().contains(pos):
                self.reject()
                event.accept()
                return
        super().mousePressEvent(event)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(660, 560)

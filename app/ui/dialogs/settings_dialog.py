"""设置对话框（图 06）：分区设置、命名规则实时示例与预设。"""

from __future__ import annotations

import copy
import html
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ... import config
from ...core.naming import NamingRules, plan_target
from ...db.connection import Database
from ...errors import ConfigError
from ...services.settings_service import SettingsService
from ..theme import ui_colors

_PAGES = (
    ("general", "常规"),
    ("library", "书库与路径"),
    ("scan", "扫描"),
    ("meta", "元数据与检索"),
    ("naming", "命名规则"),
    ("reader", "阅读器"),
    ("appearance", "外观主题"),
    ("database", "数据库与缓存"),
    ("logs", "高级日志"),
    ("reset", "恢复默认"),
)

_SAMPLES: tuple[dict[str, Any], ...] = (
    {
        "title": "三体",
        "author_name": "刘慈欣",
        "author_raw": "刘慈欣",
        "is_chinese": 1,
        "country_code": "CN",
        "volume": 1,
        "series_name": "三体三部曲",
        "format": "epub",
        "file_path": "src/三体1.epub",
    },
    {
        "title": "了不起的盖茨比",
        "author_name": "菲茨杰拉德",
        "author_raw": "F.S. Fitzgerald",
        "is_chinese": 0,
        "country_code": "US",
        "format": "epub",
        "file_path": "src/gatsby.epub",
    },
    {
        "title": "人类简史",
        "author_name": "尤瓦尔·赫拉利",
        "author_raw": "Yuval Noah Harari",
        "is_chinese": 0,
        "country_code": "IL",
        "format": "pdf",
        "file_path": "src/sapiens.pdf",
    },
    {
        "title": "围城",
        "author_name": "钱钟书",
        "author_raw": "钱钟书",
        "is_chinese": 1,
        "country_code": "CN",
        "format": "mobi",
        "file_path": "src/围城.mobi",
    },
)


class SettingsDialog(QDialog):
    """分页设置；命名规则改动会实时刷新底部四条示例。"""

    applied = Signal()

    def __init__(
        self,
        db: Database | None,
        settings: SettingsService,
        parent: QWidget | None = None,
        *,
        initial_page: str = "",
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.setObjectName("SettingsDialog")
        self.setWindowTitle("设置")
        self.resize(1080, 720)
        self.setMinimumSize(920, 620)
        self._page_keys = [key for key, _name in _PAGES]
        self._build_ui()
        self._load_from_settings()
        if initial_page in self._page_keys:
            self.nav.setCurrentRow(self._page_keys.index(initial_page))

    # ---- 构建 -------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setObjectName("SettingsNav")
        self.nav.setFixedWidth(196)
        for _key, name in _PAGES:
            self.nav.addItem(name)
        self.nav.currentRowChanged.connect(self._on_page_changed)
        body.addWidget(self.nav)

        self.stack = QStackedWidget()
        self.stack.setObjectName("SettingsStack")
        builders = (
            self._page_general,
            self._page_library,
            self._page_scan,
            self._page_meta,
            self._page_naming,
            self._page_reader,
            self._page_appearance,
            self._page_database,
            self._page_logs,
            self._page_reset,
        )
        for builder in builders:
            self.stack.addWidget(builder())
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        footer = QFrame()
        footer.setObjectName("SettingsFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(16, 10, 16, 10)
        self.path_label = QLabel(f"配置保存在 {self.settings.path}")
        self.path_label.setObjectName("DetailSub")
        footer_layout.addWidget(self.path_label)
        footer_layout.addStretch(1)
        reset_button = QPushButton("恢复默认")
        reset_button.setObjectName("GhostButton")
        reset_button.clicked.connect(self._reset_all)
        footer_layout.addWidget(reset_button)
        preset_button = QPushButton("另存为预设")
        preset_button.setObjectName("GhostButton")
        preset_button.clicked.connect(self._save_preset)
        footer_layout.addWidget(preset_button)
        self.save_button = QPushButton("保存并应用")
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.clicked.connect(self.save)
        footer_layout.addWidget(self.save_button)
        self.status_label = QLabel("")
        self.status_label.setObjectName("DetailSub")
        footer_layout.addWidget(self.status_label)
        root.addWidget(footer)
        self.nav.setCurrentRow(0)

    def _page(self, title: str, subtitle: str = "") -> tuple[QWidget, QVBoxLayout]:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setObjectName("SettingsPageScroll")
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(22, 18, 22, 24)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)
        if subtitle:
            hint = QLabel(subtitle)
            hint.setObjectName("DetailSub")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        area.setWidget(inner)
        return area, layout

    def _row(
        self,
        layout: QVBoxLayout,
        label: str,
        widget: QWidget,
        hint: str = "",
    ) -> None:
        row = QHBoxLayout()
        row.setSpacing(12)
        name = QLabel(label)
        name.setObjectName("SettingLabel")
        name.setFixedWidth(170)
        row.addWidget(name)
        row.addWidget(widget)
        if hint:
            note = QLabel(hint)
            note.setObjectName("DetailSub")
            row.addWidget(note)
        row.addStretch(1)
        layout.addLayout(row)

    @staticmethod
    def _combo(items: tuple[tuple[str, Any], ...]) -> QComboBox:
        combo = QComboBox()
        combo.setFixedWidth(340)
        for text, value in items:
            combo.addItem(text, value)
        return combo

    # ---- 各页 -------------------------------------------------------
    def _page_general(self) -> QWidget:
        page, layout = self._page("常规", "界面语言与启动行为。")
        lang = QLabel("简体中文（zh-CN）")
        self._row(layout, "界面语言", lang, "当前版本仅提供简体中文")
        self.open_mode_combo = self._combo(
            (("双击在新窗口阅读", "window"), ("双击用外部程序打开", "external"))
        )
        self._row(layout, "双击书籍", self.open_mode_combo, "阅读窗口为独立窗口，不占用书库界面")
        layout.addStretch(1)
        return page

    def _page_library(self) -> QWidget:
        page, layout = self._page(
            "书库与路径", "书库根目录是整理后的归档位置，源目录只读。"
        )
        row = QHBoxLayout()
        label = QLabel("书库根目录")
        label.setObjectName("SettingLabel")
        label.setFixedWidth(170)
        row.addWidget(label)
        self.library_root_edit = QLineEdit()
        self.library_root_edit.setFixedWidth(340)
        row.addWidget(self.library_root_edit)
        browse = QPushButton("浏览…")
        browse.setObjectName("GhostButton")
        browse.clicked.connect(self._choose_library_root)
        row.addWidget(browse)
        row.addStretch(1)
        layout.addLayout(row)

        self.source_list = QListWidget()
        self.source_list.setObjectName("SourceList")
        self.source_list.setFixedHeight(120)
        layout.addWidget(self.source_list)
        open_data = QPushButton("打开数据目录")
        open_data.setObjectName("GhostButton")
        open_data.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.DATA_DIR)))
        )
        layout.addWidget(open_data)
        data_hint = QLabel(f"数据目录：{config.DATA_DIR}")
        data_hint.setObjectName("DetailSub")
        layout.addWidget(data_hint)
        layout.addStretch(1)
        return page

    def _page_scan(self) -> QWidget:
        page, layout = self._page("扫描", "扫描仅登记路径；整理时默认复制入库，不移动或删除原文件。")
        self.scan_recursive = QCheckBox("递归子目录")
        self.scan_incremental = QCheckBox("增量扫描（跳过未变化文件）")
        self.scan_ignore_hidden = QCheckBox("忽略隐藏文件与目录")
        for box in (self.scan_recursive, self.scan_incremental, self.scan_ignore_hidden):
            layout.addWidget(box)
        self.scan_min_size = QSpinBox()
        self.scan_min_size.setRange(0, 10240)
        self.scan_min_size.setSuffix(" KB")
        self.scan_min_size.setFixedWidth(120)
        self._row(layout, "最小文件大小", self.scan_min_size, "小于该值的文件视为损坏并跳过")
        self.scan_workers = QSpinBox()
        self.scan_workers.setRange(1, 16)
        self.scan_workers.setFixedWidth(120)
        self._row(layout, "扫描线程数", self.scan_workers, "机械硬盘建议 2–4")
        layout.addStretch(1)
        return page

    def _page_meta(self) -> QWidget:
        page, layout = self._page(
            "元数据与检索", "联网检索失败时自动降级为本地元数据，不会中断扫描。"
        )
        self.meta_network = QCheckBox("启用联网检索（豆瓣 / Crossref / OpenLibrary / Google Books）")
        layout.addWidget(self.meta_network)
        self.meta_douban = QCheckBox("使用豆瓣读书（中文书首选，网页抓取）")
        self.meta_crossref = QCheckBox("使用 Crossref（外文与学术书）")
        self.meta_kongfz = QCheckBox("使用孔夫子旧书网（旧书/绝版书）")
        self.meta_openlibrary = QCheckBox("使用 OpenLibrary")
        self.meta_googlebooks = QCheckBox("使用 Google Books")
        for box in (
            self.meta_douban,
            self.meta_crossref,
            self.meta_kongfz,
            self.meta_openlibrary,
            self.meta_googlebooks,
        ):
            layout.addWidget(box)
        self.meta_auto = QSpinBox()
        self.meta_auto.setRange(50, 100)
        self.meta_auto.setFixedWidth(120)
        self._row(layout, "自动应用阈值", self.meta_auto, "匹配度达到该值自动写入")
        self.meta_confirm = QSpinBox()
        self.meta_confirm.setRange(0, 100)
        self.meta_confirm.setFixedWidth(120)
        self._row(layout, "待确认阈值", self.meta_confirm, "低于自动阈值但高于该值时进入待确认")
        self.meta_daily_limit = QSpinBox()
        self.meta_daily_limit.setRange(0, 5000)
        self.meta_daily_limit.setFixedWidth(120)
        self._row(layout, "每日请求上限", self.meta_daily_limit)
        self.meta_ttl = QSpinBox()
        self.meta_ttl.setRange(1, 365)
        self.meta_ttl.setSuffix(" 天")
        self.meta_ttl.setFixedWidth(120)
        self._row(layout, "缓存有效期", self.meta_ttl)
        self.meta_rate = QSpinBox()
        self.meta_rate.setRange(0, 10000)
        self.meta_rate.setSuffix(" ms")
        self.meta_rate.setFixedWidth(120)
        self._row(layout, "请求最小间隔", self.meta_rate)
        layout.addStretch(1)
        return page

    def _page_naming(self) -> QWidget:
        page, layout = self._page(
            "命名规则",
            "占位符：{作者} {作者全} {国家} {书名} {副标题} {卷号} {丛书} {年份} {出版社} {ISBN} {扩展名}。修改后下方示例实时更新。",
        )
        self.author_template_edit = QLineEdit()
        self.author_template_edit.setFixedWidth(340)
        self.author_template_edit.textChanged.connect(self._refresh_examples)
        self._row(layout, "作者目录模板", self.author_template_edit)

        self.file_template_edit = QLineEdit()
        self.file_template_edit.setFixedWidth(340)
        self.file_template_edit.textChanged.connect(self._refresh_examples)
        self._row(layout, "文件模板", self.file_template_edit)

        self.country_style_combo = self._combo((("短名（美 / 日）", "short"), ("全名（美国 / 日本）", "full")))
        self.country_style_combo.currentIndexChanged.connect(self._refresh_examples)
        self._row(layout, "国别写法", self.country_style_combo)

        self.hierarchy_combo = self._combo(
            (("丛书 → 作者 → 作品", "series_first"), ("作者 → 丛书 → 作品", "author_first"))
        )
        self.hierarchy_combo.currentIndexChanged.connect(self._refresh_examples)
        self._row(layout, "套书层级", self.hierarchy_combo, "当前设置随老库保留；仅新装或重置默认作者优先")

        self.volume_style_combo = self._combo((("第N卷", "第N卷"), ("Vol.N", "Vol.N")))
        self.volume_style_combo.currentIndexChanged.connect(self._refresh_examples)
        self._row(layout, "卷号写法", self.volume_style_combo)

        self.action_combo = self._combo((("复制入库（保留原文件，推荐）", "copy"), ("移动入库", "move")))
        self._row(layout, "整理方式", self.action_combo, "扫描仅登记路径；移动入库仅在复制校验成功后删除源文件")

        self.conflict_policy_combo = self._combo(
            (("同名时追加序号", "suffix"), ("同名时覆盖", "overwrite"), ("同名时跳过", "skip"))
        )
        self.conflict_policy_combo.currentIndexChanged.connect(self._refresh_examples)
        self._row(layout, "同名冲突", self.conflict_policy_combo)

        self.chinese_no_country = QCheckBox("中国作者目录不加国别")
        layout.addWidget(self.chinese_no_country)
        self.series_subdir = QCheckBox("系列使用独立子目录")
        self.series_subdir.stateChanged.connect(lambda _=0: self._refresh_examples())
        layout.addWidget(self.series_subdir)
        self.delete_empty_dirs = QCheckBox("移动整理后清理变空的源目录")
        layout.addWidget(self.delete_empty_dirs)

        self.max_title_spin = QSpinBox()
        self.max_title_spin.setRange(20, 300)
        self.max_title_spin.setFixedWidth(120)
        self._row(layout, "书名最大长度", self.max_title_spin, "字符")
        self.max_path_spin = QSpinBox()
        self.max_path_spin.setRange(80, 320)
        self.max_path_spin.setFixedWidth(120)
        self._row(layout, "完整路径上限", self.max_path_spin, "字符，超长时自动缩短书名")

        preset_row = QHBoxLayout()
        preset_label = QLabel("命名预设")
        preset_label.setObjectName("SettingLabel")
        preset_label.setFixedWidth(170)
        preset_row.addWidget(preset_label)
        self.preset_combo = QComboBox()
        self.preset_combo.setFixedWidth(220)
        preset_row.addWidget(self.preset_combo)
        load_preset = QPushButton("载入预设")
        load_preset.setObjectName("GhostButton")
        load_preset.clicked.connect(self._load_preset)
        preset_row.addWidget(load_preset)
        preset_row.addStretch(1)
        layout.addLayout(preset_row)

        example_title = QLabel("示例输出")
        example_title.setObjectName("SettingLabel")
        layout.addWidget(example_title)
        self.example_view = QTextEdit()
        self.example_view.setObjectName("ExampleBox")
        self.example_view.setReadOnly(True)
        self.example_view.setFixedHeight(96)
        layout.addWidget(self.example_view)
        layout.addStretch(1)
        return page

    def _page_reader(self) -> QWidget:
        page, layout = self._page("阅读器", "阅读器设置在 M5 生效。")
        self.reader_theme = self._combo((("浅色纸面", "light"), ("米黄", "sepia"), ("深色", "dark")))
        self._row(layout, "阅读主题", self.reader_theme)
        self.reader_font = QLineEdit()
        self.reader_font.setFixedWidth(340)
        self._row(layout, "正文字体", self.reader_font)
        self.reader_font_size = QSpinBox()
        self.reader_font_size.setRange(10, 40)
        self.reader_font_size.setFixedWidth(120)
        self._row(layout, "字号", self.reader_font_size, "px")
        self.reader_line_height = QDoubleSpinBox()
        self.reader_line_height.setRange(1.0, 3.0)
        self.reader_line_height.setSingleStep(0.02)
        self.reader_line_height.setDecimals(2)
        self.reader_line_height.setFixedWidth(120)
        self._row(layout, "行距", self.reader_line_height)
        self.reader_margin = QSpinBox()
        self.reader_margin.setRange(0, 240)
        self.reader_margin.setFixedWidth(120)
        self._row(layout, "页边距", self.reader_margin, "px")
        layout.addStretch(1)
        return page

    def _page_appearance(self) -> QWidget:
        page, layout = self._page("外观主题", "界面主题与三栏宽度。")
        self.ui_theme = self._combo((("深色", "dark"), ("浅色", "light")))
        self._row(layout, "界面主题", self.ui_theme, "保存后立即生效")
        self.nav_width = QSpinBox()
        self.nav_width.setRange(180, 320)
        self.nav_width.setFixedWidth(120)
        self._row(layout, "左栏宽度", self.nav_width, "px")
        self.detail_width = QSpinBox()
        self.detail_width.setRange(300, 520)
        self.detail_width.setFixedWidth(120)
        self._row(layout, "右栏宽度", self.detail_width, "px")
        layout.addStretch(1)
        return page

    def _page_database(self) -> QWidget:
        page, layout = self._page("数据库与缓存", "数据库使用 SQLite WAL，可直接备份。")
        db_label = QLabel(str(config.DB_PATH))
        db_label.setObjectName("DetailSub")
        self._row(layout, "数据库文件", db_label)
        cache_label = QLabel(str(config.CACHE_DIR))
        cache_label.setObjectName("DetailSub")
        self._row(layout, "缓存目录", cache_label)
        open_cache = QPushButton("打开缓存目录")
        open_cache.setObjectName("GhostButton")
        open_cache.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.CACHE_DIR)))
        )
        layout.addWidget(open_cache)
        self.cache_ttl_note = QLabel("检索缓存有效期在「元数据与检索」页设置。")
        self.cache_ttl_note.setObjectName("DetailSub")
        layout.addWidget(self.cache_ttl_note)
        layout.addStretch(1)
        return page

    def _page_logs(self) -> QWidget:
        page, layout = self._page("高级日志", "日志按天写入用户数据目录，便于排查。")
        log_label = QLabel(str(config.LOG_PATH))
        log_label.setObjectName("DetailSub")
        self._row(layout, "日志文件", log_label)
        open_log = QPushButton("打开日志目录")
        open_log.setObjectName("GhostButton")
        open_log.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.LOG_DIR)))
        )
        layout.addWidget(open_log)
        layout.addStretch(1)
        return page

    def _page_reset(self) -> QWidget:
        page, layout = self._page("恢复默认", "恢复默认不会删除已扫描的书籍与整理记录。")
        naming_button = QPushButton("恢复命名规则默认值")
        naming_button.setObjectName("GhostButton")
        naming_button.clicked.connect(self._reset_naming)
        layout.addWidget(naming_button)
        all_button = QPushButton("恢复全部默认设置（保留书库路径与源目录）")
        all_button.setObjectName("GhostButton")
        all_button.clicked.connect(self._reset_all)
        layout.addWidget(all_button)
        layout.addStretch(1)
        return page

    # ---- 载入 / 收集 ------------------------------------------------
    def _on_page_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(max(0, index))

    def _choose_library_root(self) -> None:
        initial = self.library_root_edit.text() or str(Path.home())
        directory = QFileDialog.getExistingDirectory(self, "选择书库根目录", initial)
        if directory:
            self.library_root_edit.setText(directory)

    def _load_from_settings(self) -> None:
        data = self.settings.data
        scan = data.get("scan") or {}
        meta = data.get("meta") or {}
        sources = data.get("sources") or {}
        naming = data.get("naming") or {}
        organize = data.get("organize") or {}
        reader = data.get("reader") or {}
        ui = data.get("ui") or {}

        self.library_root_edit.setText(str(data.get("library_root") or ""))
        self.source_list.clear()
        self.source_list.addItems([str(item) for item in data.get("source_dirs", [])])

        self.scan_recursive.setChecked(bool(scan.get("recursive", True)))
        self.scan_incremental.setChecked(bool(scan.get("incremental", True)))
        self.scan_ignore_hidden.setChecked(bool(scan.get("ignore_hidden", True)))
        self.scan_min_size.setValue(int(scan.get("min_size_kb", 50)))
        self.scan_workers.setValue(int(scan.get("workers", 4)))

        self.meta_network.setChecked(bool(meta.get("enable_network", True)))
        self.meta_douban.setChecked(bool(sources.get("douban", True)))
        self.meta_crossref.setChecked(bool(sources.get("crossref", False)))
        self.meta_kongfz.setChecked(bool(sources.get("kongfz", False)))
        self.meta_openlibrary.setChecked(bool(sources.get("openlibrary", True)))
        self.meta_googlebooks.setChecked(bool(sources.get("googlebooks", True)))
        self.meta_auto.setValue(int(meta.get("confidence_auto", 85)))
        self.meta_confirm.setValue(int(meta.get("confidence_confirm", 60)))
        self.meta_daily_limit.setValue(int(sources.get("daily_limit", 500)))
        self.meta_ttl.setValue(int(sources.get("cache_ttl_days", 30)))
        self.meta_rate.setValue(int(sources.get("rate_limit_ms", 2000)))

        self.author_template_edit.setText(
            str(naming.get("author_dir_template") or "{作者} [{国家}]")
        )
        self.file_template_edit.setText(
            str(naming.get("file_template") or "{作者} - {书名}{卷号} ({年份}).{扩展名}")
        )
        _select_data(self.country_style_combo, naming.get("country_style", "short"))
        _select_data(self.hierarchy_combo, naming.get("hierarchy", "series_first"))
        _select_data(self.volume_style_combo, naming.get("volume_style", "第N卷"))
        _select_data(self.action_combo, organize.get("action", "copy"))
        _select_data(self.conflict_policy_combo, naming.get("conflict_policy", "suffix"))
        self.chinese_no_country.setChecked(
            bool(naming.get("chinese_author_no_country", True))
        )
        self.series_subdir.setChecked(bool(naming.get("series_subdir", False)))
        self.delete_empty_dirs.setChecked(bool(organize.get("delete_empty_dirs", True)))
        self.max_title_spin.setValue(int(naming.get("max_title_len", 120)))
        self.max_path_spin.setValue(int(naming.get("max_path_len", 250)))
        self._refresh_preset_combo()

        _select_data(self.reader_theme, reader.get("theme", "light"))
        self.reader_font.setText(str(reader.get("font_family") or "Noto Serif CJK SC"))
        self.reader_font_size.setValue(int(reader.get("font_size", 15)))
        self.reader_line_height.setValue(float(reader.get("line_height", 1.98)))
        self.reader_margin.setValue(int(reader.get("margin_px", 64)))
        _select_data(self.open_mode_combo, reader.get("open_mode", "window"))

        _select_data(self.ui_theme, ui.get("theme", "dark"))
        self.nav_width.setValue(int(ui.get("nav_width", 220)))
        self.detail_width.setValue(int(ui.get("detail_width", 376)))
        self._refresh_examples()

    def _refresh_preset_combo(self) -> None:
        current = self.preset_combo.currentText()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItems(sorted(self.settings.presets()))
        if current:
            index = self.preset_combo.findText(current)
            if index >= 0:
                self.preset_combo.setCurrentIndex(index)
        self.preset_combo.blockSignals(False)

    def _naming_values(self) -> dict[str, Any]:
        return {
            "author_dir_template": self.author_template_edit.text().strip(),
            "file_template": self.file_template_edit.text().strip(),
            "chinese_author_no_country": self.chinese_no_country.isChecked(),
            "country_style": str(self.country_style_combo.currentData() or "short"),
            "hierarchy": str(self.hierarchy_combo.currentData() or "series_first"),
            "volume_style": str(self.volume_style_combo.currentData() or "第N卷"),
            "series_subdir": self.series_subdir.isChecked(),
            "max_title_len": int(self.max_title_spin.value()),
            "max_path_len": int(self.max_path_spin.value()),
            "conflict_policy": str(self.conflict_policy_combo.currentData() or "suffix"),
        }

    def _collect(self) -> dict[str, Any]:
        return {
            "library_root": self.library_root_edit.text().strip(),
            "scan": {
                "recursive": self.scan_recursive.isChecked(),
                "incremental": self.scan_incremental.isChecked(),
                "ignore_hidden": self.scan_ignore_hidden.isChecked(),
                "min_size_kb": int(self.scan_min_size.value()),
                "workers": int(self.scan_workers.value()),
            },
            "meta": {
                "enable_network": self.meta_network.isChecked(),
                "confidence_auto": int(self.meta_auto.value()),
                "confidence_confirm": int(self.meta_confirm.value()),
            },
            "sources": {
                "douban": self.meta_douban.isChecked(),
                "crossref": self.meta_crossref.isChecked(),
                "kongfz": self.meta_kongfz.isChecked(),
                "openlibrary": self.meta_openlibrary.isChecked(),
                "googlebooks": self.meta_googlebooks.isChecked(),
                "daily_limit": int(self.meta_daily_limit.value()),
                "cache_ttl_days": int(self.meta_ttl.value()),
                "rate_limit_ms": int(self.meta_rate.value()),
            },
            "naming": self._naming_values(),
            "organize": {
                "action": str(self.action_combo.currentData() or "copy"),
                "delete_empty_dirs": self.delete_empty_dirs.isChecked(),
            },
            "reader": {
                "theme": str(self.reader_theme.currentData() or "light"),
                "font_family": self.reader_font.text().strip(),
                "font_size": int(self.reader_font_size.value()),
                "line_height": float(self.reader_line_height.value()),
                "margin_px": int(self.reader_margin.value()),
                "open_mode": str(self.open_mode_combo.currentData() or "window"),
            },
            "ui": {
                "theme": str(self.ui_theme.currentData() or "dark"),
                "nav_width": int(self.nav_width.value()),
                "detail_width": int(self.detail_width.value()),
            },
        }

    # ---- 示例 -------------------------------------------------------
    def refresh_theme(self) -> None:
        """界面主题切换后，用新主题色重绘示例 HTML。"""
        self._refresh_examples()

    def _refresh_examples(self) -> None:
        if not hasattr(self, "example_view"):
            return
        try:
            naming_values = self._naming_values()
        except AttributeError:
            return
        root = self.library_root_edit.text().strip() if hasattr(self, "library_root_edit") else ""
        rules = NamingRules.from_config(
            {
                "library_root": root,
                "naming": naming_values,
                "organize": {
                    "action": str(self.action_combo.currentData() or "copy")
                    if hasattr(self, "action_combo")
                    else "copy"
                },
            }
        )
        theme = str((self.settings.data.get("ui") or {}).get("theme") or "dark")
        colors = ui_colors(theme)
        lines: list[str] = []
        for sample in _SAMPLES:
            plan = plan_target(dict(sample), rules)
            if not plan.target_path:
                lines.append(
                    f"<span style='color:{colors['error']}'>{html.escape(sample['title'])}："
                    f"{html.escape(plan.message or '无法生成')}</span>"
                )
                continue
            directories = plan.target_path.parent
            prefix = ""
            if root:
                prefix = (
                    f"<span style='color:{colors['faint']}'>{html.escape(root)}</span>\\"
                )
            lines.append(
                f"{prefix}<span style='color:{colors['accent']}'>"
                f"{html.escape(str(directories))}</span>\\"
                f"<span style='color:{colors['text']}'>{html.escape(plan.target_name)}</span>"
            )
        body = "<br>".join(lines)
        self.example_view.setHtml(
            "<div style='font-family:Consolas,\"Microsoft YaHei UI\";font-size:11.5px;"
            f"color:{colors['muted']}'>{body}</div>"
        )

    # ---- 操作 -------------------------------------------------------
    def save(self) -> bool:
        try:
            self.settings.apply(self._collect())
        except ConfigError as exc:
            QMessageBox.warning(self, "无法保存设置", str(exc))
            return False
        except Exception as exc:  # noqa: BLE001 - 设置保存失败要明确提示
            QMessageBox.warning(self, "无法保存设置", f"{type(exc).__name__}: {exc}")
            return False
        if self.db is not None:
            try:
                self.settings.sync_ui_state(self.db, "settings.last_page", self.nav.currentRow())
            except Exception:  # noqa: BLE001 - UI 状态同步失败不影响配置
                pass
        self.status_label.setText("已保存并应用")
        self.applied.emit()
        return True

    def _save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "另存为预设", "预设名称：")
        if not ok:
            return
        try:
            self.settings.save_preset(name)
        except ConfigError as exc:
            QMessageBox.warning(self, "无法保存预设", str(exc))
            return
        self._refresh_preset_combo()
        self.status_label.setText(f"已保存预设：{name.strip()}")

    def _load_preset(self) -> None:
        name = self.preset_combo.currentText()
        if not name:
            return
        try:
            self.settings.apply_preset(name)
        except ConfigError as exc:
            QMessageBox.warning(self, "无法载入预设", str(exc))
            return
        self._load_from_settings()
        self.status_label.setText(f"已载入预设：{name}")

    def _reset_naming(self) -> None:
        self.settings.reset_naming()
        self._load_from_settings()
        self.applied.emit()
        self.status_label.setText("命名规则已恢复默认")

    def _reset_all(self) -> None:
        answer = QMessageBox.question(
            self,
            "恢复默认设置",
            "将恢复全部默认设置（保留书库路径与源目录），是否继续？",
        )
        if answer != QMessageBox.Yes:
            return
        self.settings.reset_all(keep_paths=True)
        self._load_from_settings()
        self.applied.emit()
        self.status_label.setText("已恢复默认设置")


def _select_data(combo: QComboBox, value: Any) -> None:
    index = combo.findData(value)
    if index < 0:
        index = combo.findData(str(value))
    if index >= 0:
        combo.setCurrentIndex(index)


__all__ = ["SettingsDialog"]

"""主窗口：书库导航、书籍列表、详情、扫描和状态统计。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import re

from PySide6.QtCore import QSettings, QThreadPool, QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
    QApplication,
)

from .. import config
from ..db.connection import Database, get_database
from ..errors import BookShelfError
from ..logger import get_logger
from ..services.author_service import AuthorService
from ..services.library_service import LibraryService
from ..services.metadata_service import MetadataService
from ..services.maintenance_service import MaintenanceService
from ..services.organize_service import OrganizeService
from ..services.series_service import SeriesService
from ..services.scan_service import ScanService
from ..services.settings_service import SettingsService
from .dialogs.backup_dialog import BackupDialog
from .dialogs.edit_book_dialog import EditBookDialog
from .dialogs.preview_dialog import PreviewDialog
from .dialogs.scan_dialog import ScanDialog
from .dialogs.settings_dialog import SettingsDialog
from .dialogs.tag_dialog import TagManagerDialog
from .pages.author_page import AuthorPage
from .pages.folder_page import FolderPage
from .pages.help_page import HelpPage
from .pages.library_page import EmptyLibraryPage, SampleLibraryDialog
from .pages.reader_container import open_with_system
from .reader_window import ReaderWindow
from .theme import load_stylesheet, ui_colors
from .widgets.book_table import HEADERS, BookTableModel
from .widgets.detail_panel import DetailPanel
from .widgets.log_panel import LogPanel
from .widgets.nav_sidebar import NavSidebar
from ..workers.metadata_worker import EnrichWorker

log = get_logger("ui")

_PLACEHOLDER_HINT = "该功能将在后续里程碑实现"
_LIBRARY_NAV = {"all", "pending", "partial", "archived", "failed"}


class MainWindow(QMainWindow):
    def __init__(
        self,
        db: Database | None = None,
        settings: SettingsService | None = None,
        qt_settings: QSettings | None = None,
    ) -> None:
        super().__init__()
        self.db = db or get_database()
        self.settings = settings or SettingsService()
        self.qt_settings = qt_settings or QSettings("BookShelf", "BookShelf")
        self.library = LibraryService(self.db)
        self.scan_service = ScanService(self.db, self)
        self._nav_key = "all"
        self._nav_display_key = "all"
        self._tag_filter = ""
        self._folder_filter = ""
        self._library_page = 1
        self._library_page_size = 200
        self._library_total = 0
        self._library_loading = False
        self._settings_from_nav = False
        self._scan_dialog: ScanDialog | None = None
        self._edit_dialog: EditBookDialog | None = None
        self._preview_dialog: PreviewDialog | None = None
        self._settings_dialog: SettingsDialog | None = None
        self._backup_dialog: BackupDialog | None = None
        self._sample_dialog: SampleLibraryDialog | None = None

        self.setWindowTitle(config.APP_NAME_CN)
        # 右侧详情栏的元数据需要完整显示，窗口过矮会压扁文字
        self.setMinimumSize(1180, 880)
        width, height = self.settings.data.get("ui", {}).get(
            "window_size", [1440, 900]
        )
        self.resize(int(width), int(height))

        self._build_menu()
        self._build_body()
        self._build_statusbar()
        self._load_style()
        self._restore_window_state()

        self.scan_service.running_changed.connect(self._on_scan_running)
        self.scan_service.finished.connect(self._on_scan_finished)
        self.refresh_library()
        log.info("主窗口已就绪")

    # ---- 菜单 / 工具栏 ---------------------------------------------
    def _placeholder(self, text: str, shortcut: str | None = None) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(lambda: self._not_implemented(text))
        return action

    def _build_menu(self) -> None:
        bar = self.menuBar()
        menus = {
            "文件": ["选择书库", "导入待整理清单", "退出"],
            "扫描": ["扫描新书", "停止扫描"],
            "整理": ["预览整理", "只重命名", "执行整理", "撤销上次整理", "查看整理记录"],
            "作者": ["作者目录", "合并重复作者"],
            "系列": ["套书系列", "统一卷号"],
            "阅读": ["在新窗口阅读", "用外部阅读器打开"],
            "工具": ["清理缓存", "数据库备份"],
            "设置": ["首选项"],
            "帮助": ["使用说明", "关于"],
        }
        for menu_name, items in menus.items():
            menu = bar.addMenu(menu_name)
            for item in items:
                if item == "退出":
                    action = QAction(item, self)
                    action.setShortcut("Ctrl+Q")
                    action.triggered.connect(self.close)
                elif item == "关于":
                    action = QAction(item, self)
                    action.triggered.connect(self._about)
                elif item == "选择书库":
                    action = QAction(item, self)
                    action.triggered.connect(self._choose_library)
                elif item == "导入待整理清单":
                    action = QAction(item, self)
                    action.triggered.connect(lambda: self._import_pending_list())
                    menu.addAction(action)
                    continue
                elif item == "清理缓存":
                    action = QAction(item, self)
                    action.triggered.connect(lambda: self._clear_cache())
                    menu.addAction(action)
                    continue
                elif item == "数据库备份":
                    action = QAction(item, self)
                    action.triggered.connect(lambda: self._backup_database())
                    menu.addAction(action)
                    continue
                elif item == "首选项":
                    action = QAction(item, self)
                    action.triggered.connect(lambda: self._open_settings())
                    menu.addAction(action)
                    continue
                elif item == "使用说明":
                    action = QAction(item, self)
                    action.triggered.connect(lambda: self._show_help())
                    menu.addAction(action)
                    continue
                elif item == "扫描新书":
                    action = QAction(item, self)
                    action.setShortcut("Ctrl+N")
                    action.triggered.connect(self.open_scan_dialog)
                elif item == "停止扫描":
                    action = QAction(item, self)
                    action.setEnabled(False)
                    action.triggered.connect(self.scan_service.cancel)
                    self.stop_scan_action = action
                elif item == "预览整理":
                    action = QAction(item, self)
                    action.triggered.connect(lambda: self.open_preview())
                    menu.addAction(action)
                    continue
                elif item == "只重命名":
                    action = QAction(item, self)
                    action.triggered.connect(lambda: self.open_preview(auto_rename=True))
                    menu.addAction(action)
                    continue
                elif item == "执行整理":
                    action = QAction(item, self)
                    action.triggered.connect(lambda: self.open_preview(auto_execute=True))
                    menu.addAction(action)
                    continue
                elif item == "撤销上次整理":
                    action = QAction(item, self)
                    action.triggered.connect(self._undo_last_organize)
                    menu.addAction(action)
                    continue
                elif item == "查看整理记录":
                    action = QAction(item, self)
                    action.triggered.connect(self._show_organize_records)
                    menu.addAction(action)
                    continue
                elif item == "在新窗口阅读":
                    action = QAction(item, self)
                    action.setShortcut("Ctrl+Return")
                    action.triggered.connect(lambda: self._open_reader())
                    menu.addAction(action)
                    continue
                elif item == "用外部阅读器打开":
                    action = QAction(item, self)
                    action.triggered.connect(self._open_external_current)
                    menu.addAction(action)
                    continue
                elif item in {"作者目录", "套书系列", "合并重复作者", "统一卷号"}:
                    action = QAction(item, self)
                    nav_key = "series" if item in {"套书系列", "统一卷号"} else "authors"
                    action.triggered.connect(lambda _=False, key=nav_key: self._on_nav(key))
                    menu.addAction(action)
                    continue
                else:
                    action = self._placeholder(item)
                menu.addAction(action)

    def _build_topbar(self, header: QFrame) -> None:
        """单行 52px 顶栏：品牌 | 分段动作 | 执行整理 | 搜索 | 视图切换 | 设置。

        对应 v4 原型 <header class="topbar">；合并原 38px 标题栏与 60px 工具条。
        """
        layout = QHBoxLayout(header)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(10)

        # 品牌字标（T1）
        _ui_cfg = self.settings.data.get("ui") or {}
        _accent = ui_colors(str(_ui_cfg.get("theme") or "dark"))["accent"]
        _accent_dark = QColor(_accent).darker(120).name()
        mark = QLabel(config.APP_NAME_CN[0])
        mark.setObjectName("BrandMark")
        mark.setFixedSize(26, 26)
        mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            f" stop:0 {_accent}, stop:1 {_accent_dark});"
        )
        text_col = QWidget()
        text_layout = QVBoxLayout(text_col)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        cn = QLabel(config.APP_NAME_CN)
        cn.setObjectName("BrandCN")
        en = QLabel(config.APP_NAME.upper())
        en.setObjectName("BrandEN")
        text_layout.addWidget(cn)
        text_layout.addWidget(en)
        layout.addWidget(mark)
        layout.addWidget(text_col)

        divider = QFrame()
        divider.setObjectName("TopDivider")
        layout.addWidget(divider)

        # 分段动作组（非互斥，点击即触发）
        seg = self._make_segment()
        for text, slot in (
            ("扫描新书", self.open_scan_dialog),
            ("书库", self._choose_library),
            ("识别元数据", lambda: self._open_editor(auto_search=True)),
            ("整理预览", self.open_preview),
        ):
            btn = QPushButton(text)
            btn.setObjectName("SegButton")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(slot)
            seg.layout().addWidget(btn)
        layout.addWidget(seg)

        run_btn = QPushButton("执行整理")
        run_btn.setObjectName("PrimaryButton")
        run_btn.clicked.connect(lambda: self.open_preview(auto_execute=True))
        layout.addWidget(run_btn)

        layout.addStretch(1)

        self.format_filter = QComboBox()
        self.format_filter.setObjectName("FormatFilter")
        self.format_filter.addItem("全部格式", "")
        for key, label in (("epub", "EPUB"), ("pdf", "PDF"), ("mobi", "MOBI"), ("azw3", "AZW3")):
            self.format_filter.addItem(label, key)
        self.format_filter.currentIndexChanged.connect(self.refresh_library)
        layout.addWidget(self.format_filter)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("搜索书名 / 作者 / ISBN / 标签")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setFixedWidth(240)
        layout.addWidget(self.search_box)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self.refresh_library)
        self.search_box.textChanged.connect(lambda: self._search_timer.start())

        # 视图切换：列表 / 网格（网格视图随 T7 书架页落地后接线）
        self._library_view_mode = "list"
        viewseg = self._make_segment()
        self._view_list_btn = self._make_toggle_button("列表", checked=True)
        self._view_grid_btn = self._make_toggle_button("网格")
        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        self._view_group.addButton(self._view_list_btn)
        self._view_group.addButton(self._view_grid_btn)
        self._view_list_btn.clicked.connect(lambda: self._set_library_view("list"))
        self._view_grid_btn.clicked.connect(lambda: self._set_library_view("grid"))
        viewseg.layout().addWidget(self._view_list_btn)
        viewseg.layout().addWidget(self._view_grid_btn)
        layout.addWidget(viewseg)

        # 设置齿轮（替换原「设置」文字按钮；菜单仍保留设置项）
        gear = QPushButton("⚙")
        gear.setObjectName("IconButton")
        gear.setToolTip("设置")
        gear.setFixedSize(30, 30)
        gear.setCursor(Qt.PointingHandCursor)
        gear.clicked.connect(lambda: self._open_settings())
        layout.addWidget(gear)

        self.clear_filter_button = QPushButton("清除筛选")
        self.clear_filter_button.setObjectName("GhostButton")
        self.clear_filter_button.clicked.connect(self._clear_filters)
        self.clear_filter_button.setVisible(False)
        layout.addWidget(self.clear_filter_button)

    def _make_segment(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("SegGroup")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        return frame

    def _make_toggle_button(self, text: str, *, checked: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("SegButton")
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def _set_library_view(self, mode: str) -> None:
        self._library_view_mode = mode
        # 网格视图尚未实现（T7 书架页），当前始终显示表格
        if hasattr(self, "table_stack"):
            self.table_stack.setCurrentWidget(self.table)

    # ---- 主体三栏 + 底部 -------------------------------------------
    def _build_body(self) -> None:
        central = QWidget()
        central.setObjectName("Central")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("TitleBar")
        header.setFixedHeight(52)
        self._build_topbar(header)
        root.addWidget(header)

        ui_config = self.settings.data.get("ui") or {}
        nav_width = int(ui_config.get("nav_width", 220))
        detail_width = int(ui_config.get("detail_width", 376))

        self.nav = NavSidebar()
        self.nav.setFixedWidth(nav_width)
        self.table_model = BookTableModel(self)
        self.table = QTableView()
        self.table.setObjectName("BookTable")
        self.table.setModel(self.table_model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_book_context_menu)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        for index, (_name, width, _key) in enumerate(HEADERS):
            self.table.setColumnWidth(index, width)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        self.table_stack = QStackedWidget()
        self.table_stack.addWidget(self.table)
        self.empty_page = EmptyLibraryPage()
        self.empty_page.scan_requested.connect(self.open_scan_dialog)
        self.empty_page.sample_requested.connect(self._show_sample_library)
        self.table_stack.addWidget(self.empty_page)
        center_layout.addWidget(self.table_stack, 1)
        self.load_more_button = QPushButton("加载更多")
        self.load_more_button.setObjectName("GhostButton")
        self.load_more_button.setFixedWidth(260)
        self.load_more_button.setVisible(False)
        self.load_more_button.clicked.connect(self._load_more_library)
        center_layout.addWidget(self.load_more_button, 0, Qt.AlignCenter)

        self.detail = DetailPanel()
        self.detail.setFixedWidth(detail_width)

        self.content_splitter = QSplitter(Qt.Horizontal)
        self.content_splitter.setObjectName("ContentSplitter")
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.addWidget(center)
        self.content_splitter.addWidget(self.detail)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 0)
        self.content_splitter.setSizes([max(600, 1220 - detail_width), detail_width])

        self.author_page = AuthorPage(self.db, self.settings)
        self.author_page.back_requested.connect(self._show_library)
        self.author_page.open_book_requested.connect(self._open_book_by_id)
        self.author_page.changed.connect(self.refresh_library)
        self.folder_page = FolderPage(self.library)
        self.folder_page.back_requested.connect(self._return_to_library)
        self.folder_page.folder_selected.connect(self._filter_folder)
        self.help_page = HelpPage()
        self.help_page.back_requested.connect(self._return_to_library)
        self._reader_windows: dict[int, ReaderWindow] = {}

        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.content_splitter)
        self.content_stack.addWidget(self.author_page)
        self.content_stack.addWidget(self.folder_page)
        self.content_stack.addWidget(self.help_page)

        self.body_splitter = QSplitter(Qt.Horizontal)
        self.body_splitter.setObjectName("BodySplitter")
        self.body_splitter.setChildrenCollapsible(False)
        self.body_splitter.addWidget(self.nav)
        self.body_splitter.addWidget(self.content_stack)
        self.body_splitter.setStretchFactor(0, 0)
        self.body_splitter.setStretchFactor(1, 1)
        self.body_splitter.setSizes([nav_width, 1220])

        self.log_panel = LogPanel()
        stats = self._build_stats()
        self.bottom_splitter = QSplitter(Qt.Horizontal)
        self.bottom_splitter.setObjectName("BottomSplitter")
        self.bottom_splitter.addWidget(self.log_panel)
        self.bottom_splitter.addWidget(stats)
        self.bottom_splitter.setStretchFactor(0, 1)
        self.bottom_splitter.setStretchFactor(1, 0)
        self.bottom_splitter.setSizes([1000, 320])

        self.vertical = QSplitter(Qt.Vertical)
        self.vertical.setObjectName("VerticalSplitter")
        self.vertical.addWidget(self.body_splitter)
        self.vertical.addWidget(self.bottom_splitter)
        self.vertical.setStretchFactor(0, 1)
        self.vertical.setStretchFactor(1, 0)
        self.vertical.setSizes([680, 140])

        root.addWidget(self.vertical, 1)
        self.setCentralWidget(central)

        self.nav.nav_changed.connect(self._on_nav)
        self.table.selectionModel().currentRowChanged.connect(self._on_selection)
        self.table.verticalScrollBar().valueChanged.connect(self._on_library_scrolled)
        self.table.doubleClicked.connect(self._open_reader)
        self.detail.edit_requested.connect(lambda: self._open_editor(auto_search=False))
        self.detail.research_requested.connect(lambda: self._open_editor(auto_search=True))
        self.detail.open_folder_requested.connect(self._open_folder)
        self.detail.favorite_requested.connect(self._favorite_current)
        self.detail.read_requested.connect(lambda: self._open_reader())

    def _build_stats(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("StatsPanel")
        panel.setFixedWidth(320)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(4)
        header = QLabel("状态统计")
        header.setObjectName("SectionTitle")
        layout.addWidget(header)
        self._stat_labels: dict[str, QLabel] = {}
        for key, name in (
            ("total", "书库总数"),
            ("pending", "待整理"),
            ("ok", "已识别"),
            ("partial", "待补全"),
            ("failed", "识别失败"),
            ("archived", "已归档"),
        ):
            label = QLabel(f"{name}：0")
            label.setObjectName("StatRow")
            self._stat_labels[key] = label
            layout.addWidget(label)
        layout.addStretch(1)
        return panel

    def _build_statusbar(self) -> None:
        bar = self.statusBar()
        bar.setObjectName("MainStatusBar")
        self._status_label = QLabel()
        bar.addWidget(self._status_label, 1)
        self._update_status(0)

    def _load_style(self) -> None:
        self._apply_ui_theme()

    def _restore_window_state(self) -> None:
        geometry = self.qt_settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        window_state = self.qt_settings.value("windowState")
        if window_state is not None:
            self.restoreState(window_state)
        for name, splitter in self._state_splitters():
            state = self.qt_settings.value(f"splitter/{name}")
            if state is not None:
                splitter.restoreState(state)
        self._clamp_to_screen()

    def _save_window_state(self) -> None:
        self.qt_settings.setValue("geometry", self.saveGeometry())
        self.qt_settings.setValue("windowState", self.saveState())
        for name, splitter in self._state_splitters():
            self.qt_settings.setValue(f"splitter/{name}", splitter.saveState())
        self.qt_settings.sync()

    def _state_splitters(self) -> tuple[tuple[str, QSplitter], ...]:
        return (
            ("content", self.content_splitter),
            ("body", self.body_splitter),
            ("bottom", self.bottom_splitter),
            ("vertical", self.vertical),
        )

    def _clamp_to_screen(self) -> None:
        """窗口越出当前屏幕时移回可用区域；小屏仍保留既定最小尺寸。"""
        if self.isMaximized() or self.isFullScreen():
            return
        screen = (
            QApplication.screenAt(self.geometry().center())
            or self.screen()
            or QApplication.primaryScreen()
        )
        if screen is None:
            return
        available = screen.availableGeometry()
        width = max(self.minimumWidth(), min(self.width(), available.width()))
        height = max(self.minimumHeight(), min(self.height(), available.height()))
        if (width, height) != (self.width(), self.height()):
            self.resize(width, height)
        geometry = self.geometry()
        x = max(available.left(), min(geometry.x(), available.right() - width + 1))
        y = max(available.top(), min(geometry.y(), available.bottom() - height + 1))
        self.move(x, y)

    def _apply_ui_theme(self) -> None:
        """立即应用界面主题与左右栏宽度（保存设置后无需重启）。"""
        ui_config = self.settings.data.get("ui") or {}
        qss = load_stylesheet(str(ui_config.get("theme") or "dark"))
        self.setStyleSheet(qss)
        if self._settings_dialog is not None:
            self._settings_dialog.setStyleSheet(qss)
            self._settings_dialog.refresh_theme()
        self.nav.setFixedWidth(int(ui_config.get("nav_width", 220)))
        self.detail.setFixedWidth(int(ui_config.get("detail_width", 376)))

    # ---- 书库数据 ---------------------------------------------------
    def refresh_library(self, *_args) -> None:
        """按当前导航、搜索词和格式重新读取第一页与统计。"""
        selected_id = self.table_model.book_id(self.table.currentIndex().row())
        self._library_page = 1
        rows, total = self._query_library_page(self._library_page)
        self._library_total = total
        self.table_model.set_rows(rows)
        stats = self._refresh_stats()
        self.table_stack.setCurrentWidget(
            self.empty_page if stats.get("total", 0) == 0 else self.table
        )
        self.clear_filter_button.setVisible(bool(self._tag_filter or self._folder_filter))

        target_row = -1
        if rows:
            target_row = 0
            if selected_id is not None:
                for index, row in enumerate(rows):
                    if row.get("id") == selected_id:
                        target_row = index
                        break
        if target_row >= 0:
            self.table.selectRow(target_row)
            self._show_row(target_row)
        else:
            self.detail.clear()
        shown = len(rows)
        self._update_load_more(total, shown)
        self._update_status(total, shown)

    def _query_library_page(self, page: int) -> tuple[list[dict[str, Any]], int]:
        return self.library.query_books(
            nav_key=self._nav_key,
            search=self.search_box.text(),
            format_name=str(self.format_filter.currentData() or ""),
            tag=self._tag_filter,
            folder=self._folder_filter,
            page=page,
            page_size=self._library_page_size,
        )

    def _load_more_library(self) -> None:
        shown = self.table_model.rowCount()
        if self._library_loading or shown >= self._library_total:
            return
        self._library_loading = True
        try:
            next_page = self._library_page + 1
            rows, total = self._query_library_page(next_page)
            self._library_page = next_page
            self._library_total = total
            self.table_model.append_rows(rows)
            shown = self.table_model.rowCount()
            self._update_load_more(total, shown)
            self._update_status(total, shown)
        finally:
            self._library_loading = False

    def _on_library_scrolled(self, value: int) -> None:
        scrollbar = self.table.verticalScrollBar()
        if scrollbar.maximum() > 0 and value >= scrollbar.maximum():
            self._load_more_library()

    def _update_load_more(self, total: int, shown: int) -> None:
        self.load_more_button.setVisible(shown < total)
        self.load_more_button.setText(f"加载更多（已显示 {shown} / 共 {total} 本）")

    def _refresh_stats(self) -> dict[str, int]:
        stats = self.library.statistics()
        names = {
            "total": "书库总数",
            "pending": "待整理",
            "ok": "已识别",
            "partial": "待补全",
            "failed": "识别失败",
            "archived": "已归档",
        }
        for key, label in self._stat_labels.items():
            label.setText(f"{names[key]}：{stats.get(key, 0)}")
            if key in {"total", "pending", "partial", "archived", "failed"}:
                self.nav.set_badge(key, stats.get(key, 0))
        return stats

    def _show_row(self, row: int) -> None:
        book = self.table_model.row_data(row)
        if book is None:
            self.detail.clear()
            return
        self.detail.show_book(book, self.library.cover_for(book))

    def _on_selection(self, current, _previous) -> None:
        self._show_row(current.row() if current.isValid() else -1)

    def _update_status(self, total: int, shown: int | None = None) -> None:
        root = self.settings.data.get("library_root") or "未选择"
        count = f"共 {total} 本"
        if shown is not None and shown < total:
            count += f"（已加载 {shown} 本）"
        filters: list[str] = []
        if self._tag_filter:
            filters.append(f"标签：{self._tag_filter}")
        if self._folder_filter:
            filters.append(f"文件夹：{self._folder_filter}")
        filter_text = ("  |  " + "  ·  ".join(filters)) if filters else ""
        self._status_label.setText(
            f"书库：{root}  |  {count}{filter_text}  |  数据目录：{config.DATA_DIR}"
        )

    # ---- 扫描 -------------------------------------------------------
    def open_scan_dialog(self) -> None:
        if self._scan_dialog is None:
            dialog = ScanDialog(self.settings, self.scan_service, self)
            dialog.setAttribute(Qt.WA_DeleteOnClose, True)
            dialog.destroyed.connect(self._clear_scan_dialog)
            self._scan_dialog = dialog
        self._scan_dialog.show()
        self._scan_dialog.raise_()
        self._scan_dialog.activateWindow()

    def _clear_scan_dialog(self, *_args) -> None:
        self._scan_dialog = None

    def _show_sample_library(self) -> None:
        if self._sample_dialog is None:
            dialog = SampleLibraryDialog(self)
            dialog.setAttribute(Qt.WA_DeleteOnClose, True)
            dialog.destroyed.connect(self._clear_sample_dialog)
            self._sample_dialog = dialog
        self._sample_dialog.show()
        self._sample_dialog.raise_()
        self._sample_dialog.activateWindow()

    def _clear_sample_dialog(self, *_args) -> None:
        self._sample_dialog = None

    def _on_scan_running(self, running: bool) -> None:
        self.stop_scan_action.setEnabled(running)

    def _on_scan_finished(self, result: dict[str, Any]) -> None:
        self.refresh_library()
        self.statusBar().showMessage(result.get("message", "扫描完成"), 10000)

    # ---- 元数据编辑 -------------------------------------------------
    def _current_book_id(self, index=None) -> int | None:
        if index is not None and hasattr(index, "isValid"):
            if not index.isValid():
                return None
            return self.table_model.book_id(index.row())
        index = self.table.currentIndex()
        if not index.isValid():
            return None
        return self.table_model.book_id(index.row())

    def _open_editor(self, *, auto_search: bool = False) -> None:
        book_id = self._current_book_id()
        dialog = EditBookDialog(
            self.db,
            self.settings,
            book_id=book_id,
            auto_search=auto_search,
            parent=self,
        )
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.saved.connect(lambda _book_id: self.refresh_library())
        dialog.destroyed.connect(self._clear_edit_dialog)
        self._edit_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _clear_edit_dialog(self, *_args) -> None:
        self._edit_dialog = None

    def _open_folder(self) -> None:
        book_id = self._current_book_id()
        if book_id is None:
            return
        row = self.db.query_one("SELECT file_path FROM books WHERE id = ?", (book_id,))
        if row is None or not row["file_path"]:
            return
        folder = Path(str(row["file_path"])).parent
        if folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # ---- 右键菜单与批量整理（M6） ----------------------------------
    def _books_for_action(self, row: int | None = None) -> list[int]:
        """已勾选优先，否则取所选行并附带右键所在行。"""
        checked = self.table_model.checked_ids()
        if checked:
            return checked
        selected = {index.row() for index in self.table.selectionModel().selectedRows()}
        if row is not None:
            selected.add(row)
        ids = [self.table_model.book_id(item_row) for item_row in sorted(selected)]
        return [int(book_id) for book_id in ids if book_id is not None]

    def _show_book_context_menu(self, pos) -> None:
        index = self.table.indexAt(pos)
        selected = {item.row() for item in self.table.selectionModel().selectedRows()}
        if index.isValid() and index.row() not in selected:
            self.table.selectRow(index.row())
        ids = self._books_for_action(index.row() if index.isValid() else None)
        if not ids:
            return

        menu = QMenu(self)
        single = ids[0] if len(ids) == 1 else None
        read_action = menu.addAction("在新窗口阅读")
        edit_action = menu.addAction("编辑元数据")
        folder_action = menu.addAction("打开所在文件夹")
        for action in (read_action, edit_action, folder_action):
            action.setEnabled(single is not None)
        reidentify_action = menu.addAction("重新识别（联网）")
        menu.addSeparator()
        favorite_action = menu.addAction("加入收藏")
        tag_action = menu.addAction("编辑标签…")
        author_action = menu.addAction("分配到作者…")
        series_action = menu.addAction("加入系列…")
        menu.addSeparator()
        archive_action = menu.addAction("标记为已归档")
        remove_action = menu.addAction("从书库移除（不删除文件）")

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is read_action and single is not None:
            self._open_book_id(single)
        elif chosen is edit_action and single is not None:
            self._open_editor(auto_search=False)
        elif chosen is folder_action:
            self._open_folder()
        elif chosen is reidentify_action:
            self._reidentify_books(ids)
        elif chosen is favorite_action:
            count = self.library.add_favorite(ids)
            self.statusBar().showMessage(f"已加入收藏：{count} 本", 8000)
        elif chosen is tag_action:
            self._edit_tags(ids)
        elif chosen is author_action:
            self._assign_author(ids)
        elif chosen is series_action:
            self._assign_series(ids)
        elif chosen is archive_action:
            count = self.library.set_status(ids, "archived")
            self.refresh_library()
            self.statusBar().showMessage(f"已归档：{count} 本", 8000)
        elif chosen is remove_action:
            answer = QMessageBox.question(
                self,
                "从书库移除",
                f"将移除 {len(ids)} 本书的库记录，原始文件不会删除，是否继续？",
            )
            if answer == QMessageBox.Yes:
                count = self.library.remove_books(ids)
                self.refresh_library()
                self.statusBar().showMessage(f"已移除 {count} 条记录", 8000)

    def _reidentify_books(self, book_ids: list[int]) -> None:
        """批量重识别：QThreadPool 后台执行，进度条可取消，不在主线程跑网络。"""
        ids = [int(book_id) for book_id in book_ids]
        if not ids:
            return
        if getattr(self, "_enrich_worker", None) is not None:
            QMessageBox.information(self, "重新识别", "已有批量识别任务在进行中。")
            return
        service = MetadataService(self.db, self.settings)
        worker = EnrichWorker(service, ids, batch_size=50, per_book_timeout=8.0)
        progress = QProgressDialog("准备重新识别…", "取消", 0, len(ids), self)
        progress.setWindowTitle("批量重新识别")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        self._enrich_worker = worker
        self._enrich_progress = progress
        worker.signals.progress.connect(self._on_reidentify_progress)
        worker.signals.finished.connect(self._on_reidentify_finished)
        worker.signals.failed.connect(self._on_reidentify_failed)
        progress.canceled.connect(worker.cancel)
        QThreadPool.globalInstance().start(worker)
        log.info("开始批量重新识别 %s 本", len(ids))

    def _on_reidentify_progress(self, done: int, total: int, message: str) -> None:
        progress = getattr(self, "_enrich_progress", None)
        if progress is None:
            return
        progress.setMaximum(total)
        progress.setValue(done)
        progress.setLabelText(f"已处理 {done}/{total} 本\n{message}")

    def _on_reidentify_finished(self, result: dict[str, Any]) -> None:
        self._clear_reidentify()
        self.refresh_library()
        message = (
            f"重新识别{'已取消，' if result.get('cancelled') else '完成'}："
            f"成功 {result.get('ok', 0)}，待补全 {result.get('partial', 0)}，"
            f"失败 {result.get('failed', 0)}，超时 {result.get('timeout', 0)}"
        )
        self.statusBar().showMessage(message, 10000)
        log.info(message)

    def _on_reidentify_failed(self, message: str) -> None:
        self._clear_reidentify()
        QMessageBox.warning(self, "重新识别", f"批量识别中断：{message}")

    def _clear_reidentify(self) -> None:
        progress = getattr(self, "_enrich_progress", None)
        if progress is not None:
            progress.reset()
            progress.deleteLater()
        self._enrich_progress = None
        self._enrich_worker = None

    def _assign_author(self, book_ids: list[int]) -> None:
        authors = AuthorService(self.db).catalog()
        if not authors:
            QMessageBox.information(self, "分配到作者", "还没有作者，请先在“作者目录”中新建作者。")
            return
        labels = [
            f"{row['name_zh']}（{row['country'] or '国别未知'}，{row['book_count']} 本）"
            for row in authors
        ]
        label, ok = QInputDialog.getItem(
            self, "分配到作者", f"将 {len(book_ids)} 本书归入作者：", labels, 0, False
        )
        if not ok:
            return
        try:
            count = AuthorService(self.db).assign_author(
                book_ids, int(authors[labels.index(label)]["id"])
            )
        except ValueError as exc:
            QMessageBox.warning(self, "分配到作者", str(exc))
            return
        self.refresh_library()
        self.statusBar().showMessage(f"已更新 {count} 本书的作者", 8000)

    def _assign_series(self, book_ids: list[int]) -> None:
        service = SeriesService(self.db)
        rows = service.list_all()
        if not rows:
            QMessageBox.information(
                self, "加入系列", "还没有系列，请先在“作者目录”中新建系列。"
            )
            return
        labels = [f"{row['author_name'] or '未指定作者'} · {row['name']}" for row in rows]
        label, ok = QInputDialog.getItem(
            self, "加入系列", f"将 {len(book_ids)} 本书加入系列：", labels, 0, False
        )
        if not ok:
            return
        try:
            count = service.assign_books(book_ids, int(rows[labels.index(label)]["id"]))
        except ValueError as exc:
            QMessageBox.warning(self, "加入系列", str(exc))
            return
        self.refresh_library()
        self.statusBar().showMessage(f"已加入系列：{count} 本", 8000)

    def _edit_tags(self, book_ids: list[int]) -> None:
        current: set[str] = set()
        for book_id in book_ids:
            current.update(self.library.tags_for(book_id))
        text, ok = QInputDialog.getText(
            self,
            "编辑标签",
            "标签（用逗号分隔，留空即清除）：",
            text="，".join(sorted(current)),
        )
        if not ok:
            return
        names = [name.strip() for name in re.split(r"[,，、;；]", text) if name.strip()]
        count = self.library.set_tags(book_ids, names)
        self.refresh_library()
        self.statusBar().showMessage(f"已更新 {count} 本书的标签", 8000)

    # ---- 独立阅读窗口 ----------------------------------------------
    def _open_reader(self, index=None) -> None:
        """双击表格行或菜单进入阅读：每本书在独立窗口中打开。"""
        book_id = self._current_book_id(index)
        if book_id is not None:
            self._open_book_id(book_id)

    def _open_book_by_id(self, book_id: int) -> None:
        self._open_book_id(book_id)

    def _open_book_id(self, book_id: int) -> None:
        row = self.db.query_one(
            "SELECT title, file_path FROM books WHERE id = ?", (book_id,)
        )
        if row is None or not row["file_path"]:
            QMessageBox.information(self, "阅读", "该书籍没有可读取的文件路径。")
            return

        mode = str((self.settings.data.get("reader") or {}).get("open_mode") or "window")
        if mode == "external":
            error = open_with_system(str(row["file_path"]))
            if error:
                QMessageBox.warning(self, "打开书籍", error)
            return

        existing = self._reader_windows.get(book_id)
        if existing is not None:
            existing.showNormal()
            existing.raise_()
            existing.activateWindow()
            return

        title = str(row["title"] or Path(str(row["file_path"])).stem)
        window = ReaderWindow(
            self.db, self.settings, book_id, title, stylesheet=self.styleSheet()
        )
        window.destroyed.connect(lambda *_: self._reader_windows.pop(book_id, None))
        window.book_changed.connect(self.refresh_library)
        self._reader_windows[book_id] = window
        window.show()
        window.raise_()
        window.activateWindow()

    def open_paths(self, paths: list[str]) -> bool:
        """处理资源管理器双击/右键打开请求：已在库中的路径直接打开阅读窗口。"""
        missing: list[str] = []
        for raw in paths:
            target = Path(raw)
            row = self.db.query_one(
                "SELECT id FROM books WHERE file_path = ? COLLATE NOCASE",
                (str(target),),
            )
            if row is None:
                row = self.db.query_one(
                    "SELECT id FROM books WHERE file_path = ? COLLATE NOCASE",
                    (str(target.resolve()),),
                )
            if row is None:
                missing.append(str(target))
                continue
            self.raise_()
            self.activateWindow()
            self._open_book_id(int(row["id"]))
            return True
        if missing:
            QMessageBox.information(
                self,
                "打开书籍",
                "这本书还没有入库，请先扫描它所在的文件夹：\n\n" + missing[0],
            )
            self.open_scan_dialog()
        return False

    def _show_library(self) -> None:
        self.content_stack.setCurrentWidget(self.content_stack.widget(0))
        self.vertical.widget(1).setVisible(True)
        self.refresh_library()

    def _return_to_library(self) -> None:
        """从文件夹树或帮助页返回，并把导航选中项恢复到进入前。"""
        self.nav.set_current_silent(self._nav_display_key)
        self._show_library()

    def _open_external_current(self) -> None:
        book_id = self._current_book_id()
        if book_id is None:
            return
        row = self.db.query_one("SELECT file_path FROM books WHERE id = ?", (book_id,))
        if row is not None and row["file_path"]:
            error = open_with_system(str(row["file_path"]))
            if error:
                QMessageBox.warning(self, "打开书籍", error)

    # ---- 整理预览 / 设置（M4） --------------------------------------
    def open_preview(
        self, *, auto_execute: bool = False, auto_rename: bool = False
    ) -> None:
        """打开整理预览；未选择书库根目录时先提示。"""
        if not self.settings.data.get("library_root"):
            QMessageBox.information(
                self,
                "整理预览",
                "请先选择书库根目录（整理后的归档位置）。",
            )
            return
        dialog = PreviewDialog(self.db, self.settings, self)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.organized.connect(lambda _batch: self.refresh_library())
        dialog.destroyed.connect(self._clear_preview_dialog)
        self._preview_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        if auto_rename:
            dialog._execute_rename()
        elif auto_execute:
            dialog._execute()

    def _clear_preview_dialog(self, *_args) -> None:
        self._preview_dialog = None

    def _open_settings(self, *, from_nav: bool = False) -> None:
        self._settings_from_nav = from_nav
        dialog = SettingsDialog(self.db, self.settings, self)
        dialog.setStyleSheet(self.styleSheet())
        dialog.applied.connect(self._apply_ui_theme)
        dialog.applied.connect(self.refresh_library)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.destroyed.connect(self._clear_settings_dialog)
        self._settings_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _clear_settings_dialog(self, *_args) -> None:
        self._settings_dialog = None
        if self._settings_from_nav:
            self._settings_from_nav = False
            self.nav.set_current_silent(self._nav_display_key)

    def _undo_last_organize(self) -> None:
        service = OrganizeService(self.db, self.settings)
        batch = service.latest_batch()
        if not batch:
            QMessageBox.information(self, "撤销整理", "没有可撤销的整理记录。")
            return
        actions = {
            str(row["action"])
            for row in self.db.query(
                "SELECT DISTINCT action FROM library_items WHERE batch_id = ?", (batch,)
            )
        }
        prompt = (
            "将把文件名还原为整理前的名称（不跨目录移动），是否继续？"
            if actions == {"rename"}
            else "将删除上次整理新建的文件（原始文件不受影响），是否继续？"
        )
        answer = QMessageBox.question(self, "撤销上次整理", prompt)
        if answer != QMessageBox.Yes:
            return
        try:
            result = service.undo(batch)
        except BookShelfError as exc:
            QMessageBox.warning(self, "无法撤销", str(exc))
            return
        self.refresh_library()
        QMessageBox.information(self, "撤销完成", result.summary())

    def _show_organize_records(self) -> None:
        service = OrganizeService(self.db, self.settings)
        rows = service.records(20)
        if not rows:
            QMessageBox.information(self, "整理记录", "还没有整理记录。")
            return
        lines = [
            f"{row.get('created_at', '')[:19]}  {row.get('result', '')}  "
            f"{row.get('title') or row.get('target_name', '')}"
            for row in rows
        ]
        QMessageBox.information(self, "最近整理记录", "\n".join(lines))

    # ---- 其他交互 ---------------------------------------------------
    def _choose_library(self) -> bool:
        initial = self.settings.data.get("library_root") or str(Path.home())
        directory = QFileDialog.getExistingDirectory(self, "选择书库根目录", initial)
        if not directory:
            return False
        try:
            self.settings.set_library_root(directory)
        except BookShelfError as exc:
            QMessageBox.warning(self, "无法选择书库", str(exc))
            return False
        self._update_status(self.library.statistics()["total"])
        log.info("书库根目录已设置：%s", directory)
        if str(directory).startswith("\\\\"):
            QMessageBox.information(self, "网络目录", "网络盘扫描较慢，请耐心等待。")
        return True

    def _not_implemented(self, name: str) -> None:
        log.info("点击了占位功能：%s", name)
        QMessageBox.information(self, config.APP_NAME_CN, f"「{name}」{_PLACEHOLDER_HINT}。")

    def _on_nav(self, key: str) -> None:
        log.info("导航切换：%s", key)
        if key in _LIBRARY_NAV:
            self._nav_key = key
            self._nav_display_key = key
            self._tag_filter = ""
            self._folder_filter = ""
            self._show_library()
        elif key in {"authors", "series"}:
            self.content_stack.setCurrentWidget(self.author_page)
            self.vertical.widget(1).setVisible(True)
            self.author_page.refresh()
        elif key == "favorites":
            self._nav_key = "all"
            self._nav_display_key = "favorites"
            self._folder_filter = ""
            self._tag_filter = "收藏"
            self._show_library()
        elif key == "tags":
            self._manage_tags()
        elif key == "folders":
            self._show_folders()
        elif key == "settings":
            self._open_settings(from_nav=True)
        elif key == "help":
            self._show_help()
        else:
            self._not_implemented(key)

    def _show_folders(self) -> None:
        self.folder_page.refresh()
        self.content_stack.setCurrentWidget(self.folder_page)
        self.vertical.widget(1).setVisible(True)

    def _filter_folder(self, folder: str) -> None:
        self._nav_key = "all"
        self._nav_display_key = "all"
        self._tag_filter = ""
        self._folder_filter = folder
        self.nav.set_current_silent("all")
        self._show_library()

    def _show_help(self) -> None:
        self.content_stack.setCurrentWidget(self.help_page)
        self.vertical.widget(1).setVisible(True)
        self.nav.set_current_silent("help")

    # ---- 标签管理（M7） --------------------------------------------
    def _manage_tags(self) -> None:
        dialog = TagManagerDialog(self.library, self)
        accepted = dialog.exec()
        if accepted and dialog.selected_value:
            self._nav_key = "all"
            self._nav_display_key = "all"
            self._folder_filter = ""
            self._tag_filter = dialog.selected_value
            self.nav.set_current_silent("all")
        else:
            self.nav.set_current_silent(self._nav_display_key)
            if self._tag_filter:
                names = {str(row["name"]) for row in self.library.tag_counts()}
                if self._tag_filter not in names:
                    self._tag_filter = ""
        self._show_library()

    # ---- 导入待整理清单（M7） ---------------------------------------
    def _import_pending_list(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入待整理清单",
            "",
            "清单文件 (*.txt *.csv);;所有文件 (*.*)",
        )
        if not path:
            return
        list_path = Path(path)
        try:
            text = list_path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = list_path.read_text(encoding="gbk")
            except (OSError, UnicodeDecodeError) as exc:
                QMessageBox.warning(self, "导入失败", f"无法读取清单：{exc}")
                return
        except OSError as exc:
            QMessageBox.warning(self, "导入失败", f"无法读取清单：{exc}")
            return

        result = self.library.import_pending(text.splitlines(), base_dir=list_path.parent)
        self._nav_key = "pending"
        self._nav_display_key = "pending"
        self._tag_filter = ""
        self._folder_filter = ""
        self.nav.set_current_silent("pending")
        self._show_library()
        QMessageBox.information(
            self,
            "导入完成",
            f"新增 {result['added']} 本，已存在 {result['existing']} 本，"
            f"无效或不存在 {result['invalid']} 条。",
        )

    # ---- 工具：缓存与备份（M7） -------------------------------------
    def _clear_cache(self) -> None:
        answer = QMessageBox.question(
            self,
            "清理缓存",
            "将清理阅读转换缓存与联网检索缓存，封面缩略图会保留。是否继续？",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            result = MaintenanceService(self.db).clear_cache()
        except OSError as exc:
            QMessageBox.warning(self, "清理失败", str(exc))
            return
        size_mb = result["bytes"] / (1024 * 1024)
        self.statusBar().showMessage(
            f"已清理 {result['files']} 个缓存文件、{result['metadata']} 条检索缓存",
            10000,
        )
        QMessageBox.information(
            self,
            "清理完成",
            f"缓存文件 {result['files']} 个（{size_mb:.1f} MB）已移入回收站，\n"
            f"联网检索缓存 {result['metadata']} 条已清除。",
        )

    def _backup_database(self) -> None:
        if self._backup_dialog is not None:
            self._backup_dialog.raise_()
            self._backup_dialog.activateWindow()
            return
        dialog = BackupDialog(self.db, self.settings, self)
        dialog.setStyleSheet(self.styleSheet())
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.restored.connect(self._on_database_restored)
        dialog.destroyed.connect(self._clear_backup_dialog)
        self._backup_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _clear_backup_dialog(self, *_args) -> None:
        self._backup_dialog = None

    def _on_database_restored(self) -> None:
        self.refresh_library()
        self.statusBar().showMessage("数据库已恢复，书库列表已刷新", 10000)

    def _clear_filters(self) -> None:
        self._nav_key = "all"
        self._tag_filter = ""
        self._folder_filter = ""
        self.nav.set_current("all")
        self._show_library()

    def _favorite_current(self) -> None:
        book_id = self._current_book_id()
        if book_id is None:
            return
        self.library.add_favorite([book_id])
        self.statusBar().showMessage("已加入收藏", 5000)

    def _about(self) -> None:
        QMessageBox.about(
            self,
            f"关于 {config.APP_NAME_CN}",
            f"{config.APP_NAME_CN} BookShelf {config.APP_VERSION}\n\n"
            "Windows 电子书整理与内嵌阅读器\n"
            f"数据目录：{config.DATA_DIR}",
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        for window in list(self._reader_windows.values()):
            window.close()
        self._reader_windows.clear()
        self.scan_service.shutdown()
        self._save_window_state()
        ui = self.settings.data.setdefault("ui", {})
        normal_size = self.normalGeometry().size() if self.isMaximized() else self.size()
        ui["window_size"] = [normal_size.width(), normal_size.height()]
        try:
            self.settings.save()
        except BookShelfError as exc:
            log.error("保存窗口配置失败：%s", exc)
        self.db.close()
        event.accept()

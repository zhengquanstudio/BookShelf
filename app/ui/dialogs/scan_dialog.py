"""扫描文件夹对话框（图 02）：目录、格式、选项、进度与实时结果。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...errors import BookShelfError
from ...services.scan_service import ScanService
from ...services.settings_service import SettingsService

_FORMATS = (("epub", "EPUB"), ("pdf", "PDF"), ("mobi", "MOBI"), ("azw3", "AZW3"))
_STAT_ITEMS = (
    ("scanned", "已扫描"),
    ("success", "识别成功"),
    ("need_network", "待联网检索"),
    ("failed", "异常"),
    ("dup", "重复"),
    ("library_total", "库总数"),
)
_STATUS_TEXT = {
    "pending": "待整理",
    "ok": "已识别",
    "partial": "待补全",
    "failed": "失败",
    "drm": "受保护",
    "skipped": "跳过",
    "archived": "已归档",
}


class ScanDialog(QDialog):
    scan_completed = Signal(object)

    def __init__(
        self,
        settings: SettingsService,
        service: ScanService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.service = service
        self.setWindowTitle("扫描文件夹")
        self.resize(1120, 706)
        self.setMinimumSize(960, 620)
        self.setAcceptDrops(True)

        self.dir_list = QListWidget()
        self.dir_list.addItems(settings.data.get("source_dirs", []))
        self.format_checks: dict[str, QCheckBox] = {}
        self._stat_values: dict[str, QLabel] = {}
        self._running = False
        self._build_ui()
        self._load_options()

        service.started.connect(self._on_started)
        service.progress.connect(self._on_progress)
        service.files_updated.connect(self._on_files)
        service.finished.connect(self._on_finished)
        service.running_changed.connect(self._on_running_changed)
        self._on_running_changed(service.is_running)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setSizes([440, 640])
        root.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        add_button = QPushButton("添加目录")
        add_button.setObjectName("GhostButton")
        add_button.clicked.connect(self._choose_directory)
        bottom.addWidget(add_button)
        hint = QLabel("扫描仅登记路径，不复制或删除原文件；整理时默认复制入库")
        hint.setObjectName("DetailSub")
        bottom.addWidget(hint)
        bottom.addStretch(1)
        self.stop_button = QPushButton("停止扫描")
        self.stop_button.setObjectName("GhostButton")
        self.stop_button.clicked.connect(self.service.cancel)
        bottom.addWidget(self.stop_button)
        self.close_button = QPushButton("取消")
        self.close_button.setObjectName("GhostButton")
        self.close_button.clicked.connect(self.close)
        bottom.addWidget(self.close_button)
        self.start_button = QPushButton("开始扫描")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.clicked.connect(self._start_scan)
        bottom.addWidget(self.start_button)
        root.addLayout(bottom)

    def _build_left(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(10)
        layout.addWidget(self._section_title("扫描目录"))
        layout.addWidget(self.dir_list, 1)
        row = QHBoxLayout()
        add_button = QPushButton("+ 添加目录 / 拖入文件夹")
        add_button.setObjectName("GhostButton")
        add_button.clicked.connect(self._choose_directory)
        remove_button = QPushButton("移除选中")
        remove_button.setObjectName("GhostButton")
        remove_button.clicked.connect(self._remove_selected)
        row.addWidget(add_button, 1)
        row.addWidget(remove_button)
        layout.addLayout(row)
        self.recent_combo = QComboBox()
        self.recent_combo.addItem("最近使用的目录…", "")
        for directory in self.settings.data.get("recent_source_dirs", []):
            if Path(directory).is_dir():
                self.recent_combo.addItem(directory, directory)
        self.recent_combo.setVisible(self.recent_combo.count() > 1)
        self.recent_combo.activated.connect(self._add_recent_directory)
        layout.addWidget(self.recent_combo)

        layout.addWidget(self._section_title("文件格式"))
        format_grid = QGridLayout()
        enabled = set(self.settings.data.get("formats", []))
        for index, (key, label) in enumerate(_FORMATS):
            check = QCheckBox(label)
            check.setChecked(key in enabled)
            self.format_checks[key] = check
            format_grid.addWidget(check, index // 2, index % 2)
        layout.addLayout(format_grid)

        layout.addWidget(self._section_title("扫描选项"))
        self.recursive_check = QCheckBox("递归扫描子目录")
        self.incremental_check = QCheckBox("启用增量扫描（未变更文件跳过）")
        self.hidden_check = QCheckBox("忽略隐藏文件和目录")
        for check in (self.recursive_check, self.incremental_check, self.hidden_check):
            layout.addWidget(check)
        self.min_size_spin = self._option_spin(layout, "最小文件大小", 0, 10240, " KB")
        self.depth_spin = self._option_spin(layout, "最大目录深度", 1, 30, " 层")
        self.workers_spin = self._option_spin(layout, "扫描并发数", 1, 8, " 线程")
        note = QLabel("扫描只读取文件与内嵌元数据；异常单本记录，不中断整批。")
        note.setWordWrap(True)
        note.setObjectName("DetailSub")
        layout.addWidget(note)
        return panel

    def _build_right(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._section_title("扫描进度"))
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.current_label = QLabel("等待开始")
        self.current_label.setObjectName("DetailSub")
        self.current_label.setWordWrap(True)
        layout.addWidget(self.current_label)

        stats = QGridLayout()
        for index, (key, label) in enumerate(_STAT_ITEMS):
            card = QFrame()
            card.setObjectName("StatCard")
            card_layout = QVBoxLayout(card)
            value = QLabel("0")
            value.setObjectName("StatValue")
            name = QLabel(label)
            name.setObjectName("DetailSub")
            card_layout.addWidget(value)
            card_layout.addWidget(name)
            self._stat_values[key] = value
            stats.addWidget(card, index // 3, index % 3)
        layout.addLayout(stats)

        layout.addWidget(self._section_title("实时文件"))
        self.file_table = QTableWidget(0, 6)
        self.file_table.setHorizontalHeaderLabels(["状态", "文件", "格式", "识别结果", "原因", "大小"])
        self.file_table.verticalHeader().setVisible(False)
        self.file_table.setSelectionMode(QTableWidget.NoSelection)
        self.file_table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.file_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        layout.addWidget(self.file_table, 1)
        return panel

    @staticmethod
    def _section_title(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    @staticmethod
    def _option_spin(
        layout: QVBoxLayout, label: str, minimum: int, maximum: int, suffix: str
    ) -> QSpinBox:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSuffix(suffix)
        row.addWidget(spin)
        layout.addLayout(row)
        return spin

    def _load_options(self) -> None:
        options = self.settings.data.get("scan", {})
        self.recursive_check.setChecked(options.get("recursive", True))
        self.incremental_check.setChecked(options.get("incremental", True))
        self.hidden_check.setChecked(options.get("ignore_hidden", True))
        self.min_size_spin.setValue(int(options.get("min_size_kb", 50)))
        self.depth_spin.setValue(int(options.get("max_depth", 12)))
        self.workers_spin.setValue(int(options.get("workers", 4)))

    def _choose_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择扫描目录")
        if directory:
            self._add_directories([directory])

    def _add_directories(self, directories: list[str]) -> None:
        existing = {self.dir_list.item(i).text() for i in range(self.dir_list.count())}
        for directory in directories:
            path = str(Path(directory).resolve())
            if path not in existing and Path(path).is_dir():
                self.dir_list.addItem(path)
                existing.add(path)

    def _add_recent_directory(self, index: int) -> None:
        directory = str(self.recent_combo.itemData(index) or "")
        if directory:
            self._add_directories([directory])
        self.recent_combo.setCurrentIndex(0)

    def _remove_selected(self) -> None:
        for item in self.dir_list.selectedItems():
            self.dir_list.takeItem(self.dir_list.row(item))

    def _start_scan(self) -> None:
        directories = [self.dir_list.item(i).text() for i in range(self.dir_list.count())]
        formats = [key for key, check in self.format_checks.items() if check.isChecked()]
        options = {
            "formats": formats,
            "recursive": self.recursive_check.isChecked(),
            "incremental": self.incremental_check.isChecked(),
            "ignore_hidden": self.hidden_check.isChecked(),
            "min_size_kb": self.min_size_spin.value(),
            "max_depth": self.depth_spin.value(),
            "workers": self.workers_spin.value(),
        }
        try:
            self.settings.save_scan_options(directories, formats, options)
        except BookShelfError as exc:
            QMessageBox.warning(self, "无法开始扫描", str(exc))
            return
        self.file_table.setRowCount(0)
        self.progress.setValue(0)
        if any(str(item).startswith("\\\\") for item in directories):
            QMessageBox.information(self, "网络目录", "网络盘扫描较慢，请耐心等待。")
        self.service.start(directories, options)

    def _on_started(self, data: dict) -> None:
        total = int(data.get("total", 0))
        self.current_label.setText("正在发现文件…" if not total else f"发现 {total} 个文件")
        counts = data.get("format_counts", {})
        if counts:
            for key, check in self.format_checks.items():
                label = dict(_FORMATS)[key]
                check.setText(f"{label}（{counts.get(key, 0)}）")

    def _on_progress(self, data: dict) -> None:
        total = int(data.get("total", 0))
        completed = int(data.get("completed", 0))
        self.progress.setValue(round(completed * 100 / total) if total else 0)
        self.current_label.setText(
            f"{completed}/{total}  {data.get('current_file', '')}"
        )
        for key in self._stat_values:
            self._stat_values[key].setText(str(data.get(key, 0)))

    def _on_files(self, files: list[dict]) -> None:
        for item in files:
            row = self.file_table.rowCount()
            self.file_table.insertRow(row)
            status = "unchanged" if item.get("unchanged") else str(item.get("status", ""))
            values = [
                "未变更" if status == "unchanged" else _STATUS_TEXT.get(status, status),
                item.get("file_name", ""),
                str(item.get("format", "")).upper(),
                item.get("title") or "",
                item.get("message", ""),
                self._format_size(int(item.get("size", 0))),
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setToolTip(item.get("message", "") if column == 4 else item.get("path", ""))
                self.file_table.setItem(row, column, cell)
            if row >= 1000:
                self.file_table.removeRow(0)
        self.file_table.scrollToBottom()

    def _on_finished(self, result: dict) -> None:
        self.current_label.setText(result.get("message", "扫描完成"))
        self.scan_completed.emit(result)

    def _on_running_changed(self, running: bool) -> None:
        self._running = running
        self.start_button.setEnabled(not running)
        self.start_button.setText("扫描中…" if running else "开始扫描")
        self.stop_button.setEnabled(running)
        self.close_button.setText("取消" if running else "关闭")

    @staticmethod
    def _format_size(size: int) -> str:
        if size >= 1024 * 1024:
            return f"{size / 1024 / 1024:.1f} MB"
        return f"{size / 1024:.1f} KB"

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        self._add_directories([path for path in paths if Path(path).is_dir()])

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._running:
            answer = QMessageBox.question(self, "停止扫描", "关闭对话框将中止扫描，是否继续？")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.service.cancel()
        event.accept()

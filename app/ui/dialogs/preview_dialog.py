"""整理预览对话框（图 04）：规则面板、预览表与冲突面板。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...db.connection import Database
from ...errors import OrganizeError
from ...services.organize_service import OrganizeService, PreviewRow, PreviewSummary
from ...services.settings_service import SettingsService
from .settings_dialog import SettingsDialog

_STATUS_COLORS = {
    "ready": QColor("#46c07f"),
    "conflict": QColor("#e8b04b"),
    "skip": QColor("#6f7681"),
    "failed": QColor("#e0645d"),
}
_STATUS_TEXT = {"ready": "就绪", "conflict": "冲突", "skip": "跳过", "failed": "失败"}


class PreviewTableModel(QAbstractTableModel):
    HEADERS = ("状态", "原文件", "目标目录", "目标文件名", "动作", "备注")

    def __init__(self, rows: list[PreviewRow] | None = None) -> None:
        super().__init__()
        self._all: list[PreviewRow] = list(rows or [])
        self._rows: list[PreviewRow] = list(self._all)
        self._conflict_only = False
        self._sort = "default"

    # ---- 数据切换 ---------------------------------------------------
    def set_rows(self, rows: list[PreviewRow]) -> None:
        self.beginResetModel()
        self._all = list(rows)
        self._rows = self._filtered()
        self.endResetModel()

    def set_conflict_only(self, flag: bool) -> None:
        self.beginResetModel()
        self._conflict_only = bool(flag)
        self._rows = self._filtered()
        self.endResetModel()

    def set_sort(self, key: str) -> None:
        self.beginResetModel()
        self._sort = key
        self._rows = self._filtered()
        self.endResetModel()

    @property
    def rows(self) -> list[PreviewRow]:
        return list(self._rows)

    @property
    def all_rows(self) -> list[PreviewRow]:
        return list(self._all)

    def _filtered(self) -> list[PreviewRow]:
        rows = [
            row
            for row in self._all
            if not self._conflict_only or row.status in {"conflict", "failed"}
        ]
        if self._sort == "author":
            rows.sort(key=lambda row: (row.author, row.title))
        elif self._sort == "series":
            rows.sort(key=lambda row: (row.series_name, row.volume_num, row.title))
        return rows

    def row_at(self, index: QModelIndex) -> PreviewRow | None:
        if 0 <= index.row() < len(self._rows):
            return self._rows[index.row()]
        return None

    # ---- Qt 模型接口 ------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        row = self.row_at(index)
        if row is None:
            return None
        column = index.column()
        if role == Qt.DisplayRole:
            return (
                row.display_status,
                row.source_path,
                row.target_dir,
                row.target_name,
                row.action_label,
                row.message,
            )[column]
        if role == Qt.ForegroundRole and column == 0:
            return _STATUS_COLORS.get(row.status, QColor("#a3a9b4"))
        if role == Qt.ToolTipRole:
            if column == 0:
                return f"{_STATUS_TEXT.get(row.status, row.status)}：{row.message or '无冲突'}"
            if column in {1, 2, 3}:
                return str(
                    (row.source_path, row.target_dir, row.target_path)[column - 1]
                )
        return None


class PreviewDialog(QDialog):
    """F8/F9 的整理预览与执行入口。"""

    organized = Signal(str)

    def __init__(
        self,
        db: Database,
        settings: SettingsService,
        parent: QWidget | None = None,
        *,
        service: OrganizeService | None = None,
        only_recognized: bool = True,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.service = service or OrganizeService(db, settings)
        self.summary = PreviewSummary(rows=[])
        self.setObjectName("PreviewDialog")
        self.setWindowTitle("整理预览")
        self.resize(1320, 780)
        self.setMinimumSize(1080, 640)
        self._build_ui()
        self._only_recognized.setChecked(only_recognized)
        self._regenerate()

    # ---- 构建 -------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        title = QLabel("整理预览")
        title.setObjectName("PageTitle")
        top.addWidget(title)
        back = QPushButton("返回书库")
        back.setObjectName("GhostButton")
        back.clicked.connect(self.close)
        top.addWidget(back)
        rebuild = QPushButton("重新生成预览")
        rebuild.setObjectName("GhostButton")
        rebuild.clicked.connect(self._regenerate)
        top.addWidget(rebuild)
        rules_button = QPushButton("应用命名规则")
        rules_button.setObjectName("GhostButton")
        rules_button.clicked.connect(self._open_settings)
        top.addWidget(rules_button)
        self._only_recognized = QCheckBox("仅整理已识别")
        self._only_recognized.stateChanged.connect(lambda _=0: self._regenerate())
        top.addWidget(self._only_recognized)
        top.addStretch(1)
        self._stats_label = QLabel("")
        self._stats_label.setObjectName("StatPill")
        top.addWidget(self._stats_label)
        rename = QPushButton("只重命名")
        rename.setObjectName("GhostButton")
        rename.clicked.connect(self._execute_rename)
        top.addWidget(rename)
        execute = QPushButton("整理（复制/移动）")
        execute.setObjectName("PrimaryButton")
        execute.clicked.connect(self._execute)
        top.addWidget(execute)
        root.addLayout(top)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        self._rules_panel = self._build_rules_panel()
        splitter.addWidget(self._rules_panel)
        splitter.addWidget(self._build_table_panel())
        self._conflict_panel = self._build_conflict_panel()
        splitter.addWidget(self._conflict_panel)
        splitter.setSizes([292, 660, 352])
        root.addWidget(splitter, 1)

        self._message = QLabel("预览只计算目标路径，不会写入磁盘。")
        self._message.setObjectName("DetailSub")
        root.addWidget(self._message)

    def _build_rules_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("RulesPanel")
        panel.setMinimumWidth(280)
        panel.setMaximumWidth(330)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        heading = QLabel("命名规则")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        self._rule_values: dict[str, QLabel] = {}
        for key, name in (
            ("source", "源目录"),
            ("target", "书库根目录"),
            ("author_template", "作者目录模板"),
            ("file_template", "文件模板"),
            ("hierarchy", "套书层级"),
            ("action", "整理方式"),
            ("empty_dirs", "空目录"),
        ):
            label = QLabel(name)
            label.setObjectName("DetailSub")
            layout.addWidget(label)
            value = QLabel("—")
            value.setObjectName("CodeBlock")
            value.setWordWrap(True)
            layout.addWidget(value)
            self._rule_values[key] = value
        conflict_label = QLabel("同名冲突")
        conflict_label.setObjectName("DetailSub")
        layout.addWidget(conflict_label)
        self._policy_combo = QComboBox()
        self._policy_combo.addItem("追加序号 (2)", "suffix")
        self._policy_combo.addItem("覆盖已有文件", "overwrite")
        self._policy_combo.addItem("跳过", "skip")
        self._policy_combo.currentIndexChanged.connect(self._regenerate)
        layout.addWidget(self._policy_combo)
        layout.addStretch(1)
        csv_button = QPushButton("导出 CSV")
        csv_button.setObjectName("GhostButton")
        csv_button.clicked.connect(self._export_csv)
        layout.addWidget(csv_button)
        return panel

    def _build_table_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        filters = QHBoxLayout()
        self._conflict_only = QCheckBox("仅看冲突")
        self._conflict_only.stateChanged.connect(self._on_filter_changed)
        filters.addWidget(self._conflict_only)
        sort_label = QLabel("排序")
        sort_label.setObjectName("DetailSub")
        filters.addWidget(sort_label)
        self._sort_combo = QComboBox()
        self._sort_combo.addItem("默认顺序", "default")
        self._sort_combo.addItem("按作者", "author")
        self._sort_combo.addItem("按系列", "series")
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        filters.addWidget(self._sort_combo)
        filters.addStretch(1)
        self._rows_label = QLabel("")
        self._rows_label.setObjectName("DetailSub")
        filters.addWidget(self._rows_label)
        layout.addLayout(filters)

        self.model = PreviewTableModel()
        self.table = QTableView()
        self.table.setObjectName("PreviewTable")
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 48)
        self.table.setColumnWidth(1, 190)
        self.table.setColumnWidth(2, 170)
        self.table.setColumnWidth(3, 210)
        self.table.setColumnWidth(4, 56)
        self.table.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self.table, 1)
        hint = QLabel("双击「目标文件名」可手动修改；冲突行用瓶色符号标记。")
        hint.setObjectName("DetailSub")
        layout.addWidget(hint)
        return panel

    def _build_conflict_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("ConflictPanel")
        panel.setMinimumWidth(320)
        panel.setMaximumWidth(380)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)
        heading = QLabel("冲突与预计结果")
        heading.setObjectName("SectionTitle")
        outer.addWidget(heading)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("ConflictScroll")
        self._conflict_host = QWidget()
        self._conflict_layout = QVBoxLayout(self._conflict_host)
        self._conflict_layout.setContentsMargins(0, 0, 0, 0)
        self._conflict_layout.setSpacing(8)
        self._conflict_layout.addStretch(1)
        scroll.setWidget(self._conflict_host)
        outer.addWidget(scroll, 1)
        self._undo_button = QPushButton("撤销上次整理")
        self._undo_button.setObjectName("GhostButton")
        self._undo_button.clicked.connect(self._undo)
        outer.addWidget(self._undo_button)
        return panel

    def _card(self, title: str, count: int, hint: str = "") -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("ConflictCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(5)
        heading = QLabel(f"{title}  {count}")
        heading.setObjectName("ConflictTitle")
        layout.addWidget(heading)
        if hint:
            note = QLabel(hint)
            note.setObjectName("DetailSub")
            note.setWordWrap(True)
            layout.addWidget(note)
        return card, layout

    # ---- 数据 -------------------------------------------------------
    def _regenerate(self, *_args) -> None:
        policy = str(self._policy_combo.currentData() or "suffix")
        self.summary = self.service.preview(
            only_recognized=self._only_recognized.isChecked(), policy=policy
        )
        self.model.set_conflict_only(self._conflict_only.isChecked())
        self.model.set_sort(str(self._sort_combo.currentData() or "default"))
        self.model.set_rows(self.summary.rows)
        self._refresh_rules()
        self._refresh_stats()
        self._refresh_conflicts()
        self._undo_button.setEnabled(bool(self.service.latest_batch()))

    def _refresh_rules(self) -> None:
        data = self.settings.data
        naming = data.get("naming") or {}
        organize = data.get("organize") or {}
        sources = [str(item) for item in data.get("source_dirs", [])]
        self._rule_values["source"].setText(sources[0] if sources else "未设置")
        self._rule_values["target"].setText(str(data.get("library_root") or "未选择"))
        self._rule_values["author_template"].setText(
            str(naming.get("author_dir_template") or "")
        )
        self._rule_values["file_template"].setText(
            str(naming.get("file_template") or "")
        )
        self._rule_values["hierarchy"].setText(
            "丛书 → 作者 → 作品"
            if str(naming.get("hierarchy") or "series_first") == "series_first"
            else "作者 → 丛书 → 作品"
        )
        self._rule_values["action"].setText(
            "复制到新目录" if str(organize.get("action") or "copy") == "copy" else "移动到新目录"
        )
        self._rule_values["empty_dirs"].setText(
            "移动后清理空目录"
            if bool(organize.get("delete_empty_dirs", True))
            else "保留源目录"
        )

    def _refresh_stats(self) -> None:
        summary = self.summary
        size_mb = summary.total_bytes / (1024 * 1024)
        self._stats_label.setText(
            f"共 {summary.total}  ·  就绪 {summary.ready}  ·  冲突 {summary.conflict}"
            f"  ·  跳过 {summary.skip}  ·  约 {size_mb:.1f} MB"
        )
        self._rows_label.setText(f"显示 {self.model.rowCount()} / {summary.total} 行")
        if summary.disk_shortage:
            self._message.setText("警告：预计占用超过磁盘剩余空间，执行将被拒绝。")
        else:
            self._message.setText(
                f"预计新建 {summary.dirs} 个目录；磁盘剩余 "
                f"{summary.disk_free / (1024 ** 3):.1f} GB（只计算，不写盘）。"
            )

    def _refresh_conflicts(self) -> None:
        while self._conflict_layout.count() > 1:
            item = self._conflict_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        rows = self.summary.rows
        exists = [row for row in rows if "exists" in row.conflict_kinds]
        authors = [row for row in rows if "author" in row.conflict_kinds and not row.confirmed]
        volumes = [row for row in rows if "volume" in row.conflict_kinds]
        dirs = [row for row in rows if "dir" in row.conflict_kinds]

        card, layout = self._card("同名冲突", len(exists), "目标文件已存在，选择处理方式")
        buttons = QHBoxLayout()
        for text, policy in (("追加 (2)", "suffix"), ("覆盖", "overwrite"), ("跳过", "skip")):
            button = QPushButton(text)
            button.setObjectName("TinyButton")
            button.clicked.connect(lambda _=False, value=policy: self._set_policy(value))
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self._conflict_layout.insertWidget(0, card)

        card, layout = self._card("译名待确认", len(authors), "确认后目录与文件名将使用当前译名")
        if authors:
            confirm = QPushButton("确认全部译名")
            confirm.setObjectName("TinyButton")
            confirm.clicked.connect(self._confirm_authors)
            layout.addWidget(confirm)
        self._conflict_layout.insertWidget(1, card)

        card, _layout = self._card("卷号待确认", len(volumes), "卷号未归入系列或系列内卷号重复")
        self._conflict_layout.insertWidget(2, card)
        card, _layout = self._card("目录同名", len(dirs), "不同作者生成了相同的目录名")
        self._conflict_layout.insertWidget(3, card)

        summary = self.summary
        card, layout = self._card("预计结果", summary.ready + summary.conflict, "按当前规则实际可执行的文件数")
        detail = QLabel(
            f"目标目录 {summary.dirs} 个\n"
            f"预计占用 {summary.total_bytes / (1024 ** 2):.1f} MB\n"
            f"磁盘剩余 {summary.disk_free / (1024 ** 3):.1f} GB"
        )
        detail.setObjectName("DetailSub")
        layout.addWidget(detail)
        self._conflict_layout.insertWidget(4, card)

    def _set_policy(self, policy: str) -> None:
        index = self._policy_combo.findData(policy)
        if index >= 0:
            self._policy_combo.setCurrentIndex(index)
            self._regenerate()

    def _on_filter_changed(self, _state: int = 0) -> None:
        self.model.set_conflict_only(self._conflict_only.isChecked())
        self._rows_label.setText(f"显示 {self.model.rowCount()} / {self.summary.total} 行")

    def _on_sort_changed(self, _index: int = 0) -> None:
        self.model.set_sort(str(self._sort_combo.currentData() or "default"))

    def _confirm_authors(self) -> None:
        author_ids: set[int] = set()
        for row in self.summary.rows:
            if "author" not in row.conflict_kinds or row.confirmed:
                continue
            row.confirmed = True
            row.conflict_kinds = [kind for kind in row.conflict_kinds if kind != "author"]
            parts = [part for part in row.message.split("；") if part and part != "作者译名待确认"]
            row.message = "；".join(parts)
            if row.status == "conflict" and not row.conflict_kinds:
                row.status = "ready"
            if row.author_id:
                author_ids.add(row.author_id)
        if author_ids:
            marks = ", ".join("?" for _ in author_ids)
            self.db.execute(
                f"UPDATE authors SET locked = 1 WHERE id IN ({marks})",
                tuple(author_ids),
            )
        self.model.set_rows(self.summary.rows)
        self._refresh_stats()
        self._refresh_conflicts()

    def _on_double_click(self, index: QModelIndex) -> None:
        if index.column() != 3:
            return
        row = self.model.row_at(index)
        if row is None:
            return
        name, ok = QInputDialog.getText(
            self, "修改目标文件名", "目标文件名：", text=row.target_name
        )
        if not ok or not name.strip() or name.strip() == row.target_name:
            return
        row.rename(name.strip())
        self.model.set_rows(self.summary.rows)
        self._refresh_conflicts()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            self.db, self.settings, self, initial_page="naming"
        )
        dialog.applied.connect(self._regenerate)
        dialog.exec()
        self._regenerate()

    def _export_csv(self) -> None:
        initial = Path(str(self.settings.data.get("library_root") or Path.home()))
        path, _filter = QFileDialog.getSaveFileName(
            self, "导出整理预览", str(initial / "整理预览.csv"), "CSV (*.csv)"
        )
        if not path:
            return
        try:
            target = self.service.export_csv(self.model.rows, path)
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self._message.setText(f"已导出 {self.model.rowCount()} 条到 {target}")

    # ---- 执行 / 撤销 ------------------------------------------------
    def _execute(self, confirm: bool = True, notify: bool = True) -> None:
        summary = self.summary
        if not str(self.settings.data.get("library_root") or ""):
            QMessageBox.warning(self, "无法执行整理", "请先在设置中选择书库根目录。")
            return
        if summary.disk_shortage:
            QMessageBox.warning(self, "磁盘空间不足", "预计占用超过磁盘剩余空间，已取消。")
            return
        action = str((self.settings.data.get("organize") or {}).get("action") or "copy")
        if confirm:
            answer = QMessageBox.question(
                self,
                "确认执行整理",
                f"将{'复制' if action == 'copy' else '移动'} "
                f"{summary.ready + summary.conflict} 个文件、新建 {summary.dirs} 个目录、"
                f"占用 {summary.total_bytes / (1024 ** 2):.1f} MB。\n"
                f"磁盘剩余 {summary.disk_free / (1024 ** 3):.1f} GB。\n"
                "原文件默认不会被删除，是否继续？",
            )
            if answer != QMessageBox.Yes:
                return
        try:
            result = self.service.execute(self.model.all_rows, action=action)
        except OrganizeError as exc:
            QMessageBox.warning(self, "整理失败", str(exc))
            return
        if notify:
            detail = result.summary()
            if result.errors:
                detail += "\n\n" + "\n".join(result.errors[:5])
            QMessageBox.information(self, "整理完成", detail)
        self._message.setText(f"整理完成：{result.summary()}（批次 {result.batch_id}）")
        self.organized.emit(result.batch_id)
        self._regenerate()

    def _execute_rename(self, confirm: bool = True) -> None:
        """只改文件名：不创建目录、不跨目录，冲突自动追加序号。"""
        rows = [
            row for row in self.model.all_rows if row.status in {"ready", "conflict"}
        ]
        if not rows:
            QMessageBox.information(self, "只重命名", "没有可重命名的文件。")
            return
        if confirm:
            answer = QMessageBox.question(
                self,
                "确认只重命名",
                f"将只修改 {len(rows)} 个文件的名称，不移动、不复制、不跨目录。\n"
                "同名冲突会自动追加 (2)/(3)，是否继续？",
            )
            if answer != QMessageBox.Yes:
                return
        try:
            result = self.service.rename_only([row.book_id for row in rows])
        except OrganizeError as exc:
            QMessageBox.warning(self, "重命名失败", str(exc))
            return
        detail = f"重命名 {result.renamed} 个，跳过 {result.skipped}，失败 {result.failed}"
        if result.errors:
            detail += "\n\n" + "\n".join(result.errors[:5])
        QMessageBox.information(self, "只重命名完成", detail)
        self._message.setText(f"只重命名完成：{detail}（批次 {result.batch_id}）")
        self._regenerate()

    def _undo(self) -> None:
        batch = self.service.latest_batch()
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
            result = self.service.undo(batch)
        except OrganizeError as exc:
            QMessageBox.warning(self, "无法撤销", str(exc))
            return
        QMessageBox.information(self, "撤销完成", result.summary())
        self._regenerate()


__all__ = ["PreviewDialog", "PreviewTableModel"]

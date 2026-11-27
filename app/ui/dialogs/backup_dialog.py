"""数据库备份管理：数量保留、安全恢复与备份文件操作。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...db.connection import Database
from ...errors import BookShelfError
from ...services.maintenance_service import MaintenanceService
from ...services.settings_service import SettingsService


class BackupDialog(QDialog):
    """非模态备份管理窗口；恢复成功后通知主窗口刷新数据。"""

    restored = Signal()

    def __init__(
        self,
        db: Database,
        settings: SettingsService,
        parent: QWidget | None = None,
        *,
        backup_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        retention = int((settings.data.get("backup") or {}).get("retention", 5))
        self.service = MaintenanceService(
            db, backup_dir=backup_dir, backup_retention=retention
        )
        self.setObjectName("BackupDialog")
        self.setWindowTitle("数据库备份")
        self.resize(980, 540)
        self.setMinimumSize(820, 420)
        self._build_ui(retention)
        self.refresh()

    def _build_ui(self, retention: int) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)
        hint = QLabel(
            "备份仅包含书库数据库，不包含电子书文件。恢复前会自动备份当前数据库；"
            "路径框可直接选择并复制。"
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        options = QHBoxLayout()
        options.addWidget(QLabel("普通备份保留"))
        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(1, 50)
        self.retention_spin.setSuffix(" 份")
        self.retention_spin.setValue(retention)
        self.retention_spin.valueChanged.connect(self._retention_changed)
        options.addWidget(self.retention_spin)
        options.addWidget(QLabel("超出后自动删除最旧的一份；恢复前备份不会被自动清理。"))
        options.addStretch(1)
        create_button = QPushButton("立即备份")
        create_button.setObjectName("PrimaryButton")
        create_button.clicked.connect(self.create_backup)
        options.addWidget(create_button)
        root.addLayout(options)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["时间", "大小", "路径（可复制）", "操作"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setSelectionMode(QTreeWidget.SingleSelection)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        root.addWidget(self.tree, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("DetailSub")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = QPushButton("关闭")
        close_button.setObjectName("GhostButton")
        close_button.clicked.connect(self.close)
        footer.addWidget(close_button)
        root.addLayout(footer)

    def refresh(self) -> None:
        """重新读取备份列表，新备份排在最前。"""
        self.tree.clear()
        for path in self.service.list_backups():
            stat = path.stat()
            item = QTreeWidgetItem(
                [
                    datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    self._format_size(stat.st_size),
                    str(path),
                    "",
                ]
            )
            item.setData(0, Qt.UserRole, str(path))
            item.setToolTip(2, str(path))
            self.tree.addTopLevelItem(item)
            path_edit = QLineEdit(str(path))
            path_edit.setReadOnly(True)
            path_edit.setFrame(False)
            self.tree.setItemWidget(item, 2, path_edit)
            self.tree.setItemWidget(item, 3, self._actions(str(path)))
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        else:
            self.status_label.setText("还没有数据库备份，点击“立即备份”创建第一份。")

    def _actions(self, path: str) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for text, handler in (
            ("恢复", self.restore_backup),
            ("删除", self.delete_backup),
            ("打开目录", self.open_directory),
        ):
            button = QPushButton(text)
            button.setObjectName("GhostButton")
            button.clicked.connect(lambda _checked=False, p=path, fn=handler: fn(p))
            layout.addWidget(button)
        return widget

    @staticmethod
    def _format_size(size: int) -> str:
        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        return f"{max(1, size / 1024):.1f} KB"

    def _retention_changed(self, value: int) -> None:
        self.service.backup_retention = int(value)
        try:
            self.settings.apply({"backup": {"retention": int(value)}})
        except (BookShelfError, OSError) as exc:
            QMessageBox.warning(self, "无法保存保留策略", str(exc))

    def create_backup(self) -> None:
        try:
            target, size = self.service.create_backup()
        except (BookShelfError, OSError) as exc:
            QMessageBox.warning(self, "备份失败", str(exc))
            return
        self.refresh()
        self.status_label.setText(
            f"备份完成：{target.name}（{self._format_size(size)}），当前保留 "
            f"{self.service.backup_retention} 份普通备份。"
        )

    def restore_backup(self, path: str) -> None:
        answer = QMessageBox.question(
            self,
            "恢复数据库",
            "将用所选备份替换当前书库数据库。恢复前会自动备份当前数据，是否继续？",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            safety_copy = self.service.restore_backup(Path(path))
        except (BookShelfError, OSError) as exc:
            QMessageBox.warning(self, "恢复失败", str(exc))
            return
        self.refresh()
        self.status_label.setText(f"恢复完成；恢复前数据已保存到：{safety_copy}")
        self.restored.emit()
        QMessageBox.information(
            self, "恢复完成", f"数据库已恢复。\n恢复前备份：\n{safety_copy}"
        )

    def delete_backup(self, path: str) -> None:
        answer = QMessageBox.question(
            self, "删除备份", f"确定删除这个数据库备份吗？\n{path}"
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.service.delete_backup(Path(path))
        except (BookShelfError, OSError) as exc:
            QMessageBox.warning(self, "删除失败", str(exc))
            return
        self.refresh()
        self.status_label.setText("备份已删除。")

    def open_directory(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))


__all__ = ["BackupDialog"]

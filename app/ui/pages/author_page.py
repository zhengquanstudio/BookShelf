"""图 07：作者目录与系列/套书管理。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core import naming
from ...db.connection import Database
from ...services.author_service import AuthorService
from ...services.library_service import LibraryService
from ...services.series_service import SeriesService


class AuthorPage(QWidget):
    back_requested = Signal()
    open_book_requested = Signal(int)
    changed = Signal()

    def __init__(self, db: Database, settings: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AuthorPage")
        self.settings = settings
        self.authors = AuthorService(db)
        self.series = SeriesService(db)
        self.library = LibraryService(db)
        self._author_rows: list[dict[str, Any]] = []
        self._series_rows: dict[int, dict[str, Any]] = {}
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        toolbar = QHBoxLayout()
        for text, handler in (
            ("返回书库", lambda: self.back_requested.emit()),
            ("新建作者", self._new_author),
            ("编辑作者信息", self._edit_author),
            ("合并重复作者", self._merge_author),
            ("新建系列", self._new_series),
        ):
            button = QPushButton(text)
            button.setObjectName("GhostButton")
            button.clicked.connect(handler)
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("搜索作者 / 原文名 / 国别")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setFixedWidth(250)
        self.search_box.textChanged.connect(self.refresh)
        toolbar.addWidget(self.search_box)
        root.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_authors())
        splitter.addWidget(self._build_center())
        splitter.addWidget(self._build_series_detail())
        splitter.setSizes([300, 700, 356])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        root.addWidget(splitter, 1)

    def _build_authors(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(240)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 6, 0)
        title = QLabel("作者目录")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        self.author_list = QListWidget()
        self.author_list.setObjectName("AuthorList")
        self.author_list.currentItemChanged.connect(self._on_author_changed)
        layout.addWidget(self.author_list, 1)
        return panel

    def _build_center(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 0, 8, 0)
        self.author_title = QLabel("请选择作者")
        self.author_title.setObjectName("DetailTitle")
        self.author_meta = QLabel("")
        self.author_meta.setObjectName("DetailSub")
        self.author_path = QLabel("")
        self.author_path.setObjectName("PathBox")
        self.author_path.setWordWrap(True)
        layout.addWidget(self.author_title)
        layout.addWidget(self.author_meta)
        layout.addWidget(self.author_path)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        host = QWidget()
        self.book_grid = QGridLayout(host)
        self.book_grid.setContentsMargins(2, 8, 2, 8)
        self.book_grid.setSpacing(10)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)

        series_title = QLabel("系列 / 套书")
        series_title.setObjectName("SectionTitle")
        layout.addWidget(series_title)
        self.series_list = QListWidget()
        self.series_list.setObjectName("SeriesList")
        self.series_list.setMaximumHeight(170)
        self.series_list.currentItemChanged.connect(self._on_series_changed)
        layout.addWidget(self.series_list)
        return panel

    def _build_series_detail(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(420)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 0, 0, 0)
        title = QLabel("系列详情")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        self.series_name = QLabel("请选择系列")
        self.series_name.setObjectName("DetailTitle")
        self.series_name.setWordWrap(True)
        self.series_state = QLabel("—")
        self.series_state.setObjectName("StatusPill")
        self.series_path = QLabel("目录与 series_id：—")
        self.series_path.setObjectName("DetailSub")
        self.series_path.setWordWrap(True)
        layout.addWidget(self.series_name)
        layout.addWidget(self.series_state, 0, Qt.AlignLeft)
        layout.addWidget(self.series_path)
        self.volume_list = QListWidget()
        self.volume_list.setObjectName("VolumeList")
        self.volume_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.volume_list.itemDoubleClicked.connect(
            lambda item: self.open_book_requested.emit(int(item.data(Qt.UserRole)))
        )
        layout.addWidget(self.volume_list, 1)

        for text, handler in (
            ("统一卷号", self._normalize_volumes),
            ("手动补卷", self._manual_volume),
            ("合并系列", self._merge_series),
            ("拆分所选书籍", self._split_series),
            ("按顺序打开", self._open_series),
            ("导出清单", self._export_series),
        ):
            button = QPushButton(text)
            button.setObjectName("GhostButton")
            button.clicked.connect(handler)
            layout.addWidget(button)
        hint = QLabel("识别依据：同作者、书名主干相似且卷号存在；手动合并与拆分只修改库记录。")
        hint.setObjectName("DetailSub")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return panel

    # ---- 数据与渲染 -------------------------------------------------
    def refresh(self, *_args, select_author: int | None = None) -> None:
        selected = select_author or self._selected_author_id()
        self._author_rows = self.authors.catalog(self.search_box.text())
        self.author_list.blockSignals(True)
        self.author_list.clear()
        target_row = 0
        for index, row in enumerate(self._author_rows):
            author_id = int(row["id"])
            initial = (str(row["name_zh"] or "?").strip() or "?")[0]
            country = str(row["country"] or ("中国" if row["is_chinese"] else "国别未知"))
            item = QListWidgetItem(
                f"{initial}   {row['name_zh']}\n     {country}                         {row['book_count']} 本"
            )
            item.setData(Qt.UserRole, author_id)
            item.setToolTip(str(row["name_orig"] or ""))
            self.author_list.addItem(item)
            if author_id == selected:
                target_row = index
        self.author_list.blockSignals(False)
        if self._author_rows:
            self.author_list.setCurrentRow(target_row)
            self._render_author(int(self._author_rows[target_row]["id"]))
        else:
            self._render_empty()

    def _render_empty(self) -> None:
        self.author_title.setText("暂无作者")
        self.author_meta.setText("扫描或手动新建后在此管理")
        self.author_path.setText("—")
        self._clear_grid()
        self.series_list.clear()
        self._series_rows = {}
        self._render_series(None)

    def _on_author_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if current is not None:
            self._render_author(int(current.data(Qt.UserRole)))

    def _render_author(self, author_id: int, select_series: int | None = None) -> None:
        row = next((item for item in self._author_rows if int(item["id"]) == author_id), None)
        if row is None:
            self._render_empty()
            return
        books = self.authors.books_for(author_id)
        self.author_title.setText(str(row["name_zh"]))
        country = str(row["country"] or ("中国" if row["is_chinese"] else "国别未知"))
        self.author_meta.setText(f"{country}  ·  {len(books)} 本书  ·  原文名 {row['name_orig'] or '—'}")
        self.author_path.setText(self._directory_text(row, books))

        self._clear_grid()
        for index, book in enumerate(books):
            card = self._book_card(book)
            self.book_grid.addWidget(card, index // 4, index % 4)
        if not books:
            self.book_grid.addWidget(QLabel("该作者下还没有书籍"), 0, 0)
        self.book_grid.setRowStretch((len(books) // 4) + 1, 1)

        series_rows = self.series.catalog(author_id)
        self._series_rows = {int(item["id"]): item for item in series_rows}
        self.series_list.blockSignals(True)
        self.series_list.clear()
        target_row = 0
        for index, item in enumerate(series_rows):
            state = "完整" if item["complete"] else "缺 " + "、".join(map(str, item["missing"])) + " 卷"
            if not item["volumes"]:
                state = "空系列"
            list_item = QListWidgetItem(f"{item['name']}  ·  {item['volume_count']} 卷\n{state}")
            list_item.setData(Qt.UserRole, int(item["id"]))
            self.series_list.addItem(list_item)
            if int(item["id"]) == select_series:
                target_row = index
        self.series_list.blockSignals(False)
        if series_rows:
            self.series_list.setCurrentRow(target_row)
            self._render_series(series_rows[target_row])
        else:
            self._render_series(None)

    def _directory_text(self, author: dict[str, Any], books: list[dict[str, Any]]) -> str:
        if books:
            rules = naming.NamingRules.from_config(self.settings.data)
            plan = naming.plan_target(books[0], rules)
            if str(plan.target_dir):
                root = Path(str(self.settings.data.get("library_root") or ""))
                return f"目录路径：{root / plan.target_dir}"
        return f"目录路径：按当前命名规则生成（{author['name_zh']}）"

    def _book_card(self, book: dict[str, Any]) -> QToolButton:
        volume = f" · 第{book['volume']}卷" if book.get("volume") else ""
        card = QToolButton()
        card.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        card.setText(f"{book.get('title') or '未命名'}\n{str(book.get('format') or '').upper()}{volume}")
        card.setToolTip(str(book.get("file_path") or ""))
        card.setIconSize(QSize(88, 116))
        card.setFixedSize(150, 172)
        card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        cover = self.library.cover_for(book)
        if cover is not None:
            card.setIcon(QIcon(cover))
        card.clicked.connect(lambda _=False, book_id=int(book["id"]): self.open_book_requested.emit(book_id))
        return card

    def _clear_grid(self) -> None:
        while self.book_grid.count():
            item = self.book_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def _on_series_changed(self, current: QListWidgetItem | None, _previous) -> None:
        self._render_series(self._series_rows.get(int(current.data(Qt.UserRole))) if current else None)

    def _render_series(self, row: dict[str, Any] | None) -> None:
        self.volume_list.clear()
        if row is None:
            self.series_name.setText("请选择系列")
            self.series_state.setText("—")
            self.series_path.setText("目录与 series_id：—")
            return
        self.series_name.setText(str(row["name"]))
        missing = row["missing"]
        self.series_state.setText("完整" if row["complete"] else f"缺失：{missing}" if missing else "空系列")
        self.series_state.setStyleSheet(f"color:{'#4ade80' if row['complete'] else '#facc15'};")
        total = row["total_volumes"] or "未设定"
        self.series_path.setText(f"总卷数：{total}\n作者目录 / {row['name']}\nseries_id = {row['id']}")
        for book in row["volumes"]:
            volume = f"第 {book['volume']} 卷" if book["volume"] else "卷号未定"
            item = QListWidgetItem(f"{volume}    {book['title'] or '未命名'}")
            item.setData(Qt.UserRole, int(book["id"]))
            self.volume_list.addItem(item)

    # ---- 作者操作 ---------------------------------------------------
    def _new_author(self) -> None:
        name, ok = QInputDialog.getText(self, "新建作者", "作者名")
        if not ok or not name.strip():
            return
        country, ok = QInputDialog.getText(self, "新建作者", "国别（中国作者可留空）")
        if not ok:
            return
        try:
            author_id = self.authors.create(name, country=country)
        except ValueError as exc:
            QMessageBox.warning(self, "新建作者", str(exc))
            return
        self.refresh(select_author=author_id)
        self.changed.emit()

    def _edit_author(self) -> None:
        author_id = self._selected_author_id()
        row = next((item for item in self._author_rows if int(item["id"]) == author_id), None)
        if row is None:
            return
        name, ok = QInputDialog.getText(self, "编辑作者", "作者名", text=str(row["name_zh"]))
        if not ok:
            return
        original, ok = QInputDialog.getText(self, "编辑作者", "原文名", text=str(row["name_orig"] or ""))
        if not ok:
            return
        country, ok = QInputDialog.getText(self, "编辑作者", "国别", text=str(row["country"] or ""))
        if not ok:
            return
        try:
            self.authors.update(author_id, name, name_orig=original, country=country)
        except ValueError as exc:
            QMessageBox.warning(self, "编辑作者", str(exc))
            return
        self.refresh(select_author=author_id)
        self.changed.emit()

    def _merge_author(self) -> None:
        source_id = self._selected_author_id()
        choices = [row for row in self.authors.catalog() if int(row["id"]) != source_id]
        if source_id is None or not choices:
            QMessageBox.information(self, "合并作者", "请先选择来源作者，并确保存在另一个作者。")
            return
        labels = [f"{row['name_zh']}（{row['country'] or '国别未知'}，{row['book_count']} 本）" for row in choices]
        label, ok = QInputDialog.getItem(self, "合并重复作者", "合并到目标作者：", labels, 0, False)
        if not ok:
            return
        target_id = int(choices[labels.index(label)]["id"])
        if QMessageBox.question(self, "确认合并", "来源作者的书籍与系列将转移到目标作者，是否继续？") != QMessageBox.Yes:
            return
        try:
            self.authors.merge(source_id, target_id)
        except ValueError as exc:
            QMessageBox.warning(self, "合并作者", str(exc))
            return
        self.refresh(select_author=target_id)
        self.changed.emit()

    # ---- 系列操作 ---------------------------------------------------
    def _new_series(self) -> None:
        author_id = self._selected_author_id()
        if author_id is None:
            QMessageBox.information(self, "新建系列", "请先选择作者。")
            return
        name, ok = QInputDialog.getText(self, "新建系列", "系列名")
        if not ok or not name.strip():
            return
        total, ok = QInputDialog.getInt(self, "新建系列", "总卷数（0 表示未设定）", 0, 0, 9999)
        if not ok:
            return
        try:
            series_id = self.series.create(name, author_id, total or None)
        except ValueError as exc:
            QMessageBox.warning(self, "新建系列", str(exc))
            return
        self._render_author(author_id, select_series=series_id)
        self.changed.emit()

    def _normalize_volumes(self) -> None:
        series_id = self._selected_series_id()
        if series_id is not None:
            count = self.series.normalize_volumes(series_id)
            self._render_author(self._selected_author_id(), select_series=series_id)
            self.changed.emit()
            QMessageBox.information(self, "统一卷号", f"已统一 {count} 本书的卷号格式。")

    def _manual_volume(self) -> None:
        author_id = self._selected_author_id()
        series_id = self._selected_series_id()
        if author_id is None or series_id is None:
            return
        candidates = [book for book in self.authors.books_for(author_id) if book.get("series_id") != series_id]
        if not candidates:
            QMessageBox.information(self, "手动补卷", "该作者没有可补入此系列的书籍。")
            return
        labels = [str(book.get("title") or Path(book["file_path"]).name) for book in candidates]
        label, ok = QInputDialog.getItem(self, "手动补卷", "选择书籍：", labels, 0, False)
        if not ok:
            return
        volume, ok = QInputDialog.getInt(self, "手动补卷", "卷号：", 1, 1, 9999)
        if not ok:
            return
        book_id = int(candidates[labels.index(label)]["id"])
        try:
            self.series.add_volume(series_id, book_id, volume)
        except ValueError as exc:
            QMessageBox.warning(self, "手动补卷", str(exc))
            return
        self._render_author(author_id, select_series=series_id)
        self.changed.emit()

    def _merge_series(self) -> None:
        source_id = self._selected_series_id()
        author_id = self._selected_author_id()
        choices = [row for row in self.series.catalog(author_id) if int(row["id"]) != source_id]
        if source_id is None or not choices:
            QMessageBox.information(self, "合并系列", "请先选择来源系列，并确保该作者还有另一个系列。")
            return
        labels = [str(row["name"]) for row in choices]
        label, ok = QInputDialog.getItem(self, "合并系列", "合并到目标系列：", labels, 0, False)
        if not ok:
            return
        target_id = int(choices[labels.index(label)]["id"])
        if QMessageBox.question(self, "确认合并", "来源系列中的书籍将并入目标系列，是否继续？") != QMessageBox.Yes:
            return
        self.series.merge(source_id, target_id)
        self._render_author(author_id, select_series=target_id)
        self.changed.emit()

    def _split_series(self) -> None:
        series_id = self._selected_series_id()
        ids = [int(item.data(Qt.UserRole)) for item in self.volume_list.selectedItems()]
        if series_id is None or not ids:
            QMessageBox.information(self, "拆分系列", "请先在各卷列表中选择要拆出的书籍。")
            return
        if QMessageBox.question(self, "确认拆分", f"将 {len(ids)} 本书移出系列（保留卷号），是否继续？") != QMessageBox.Yes:
            return
        self.series.split(series_id, ids)
        self._render_author(self._selected_author_id(), select_series=series_id)
        self.changed.emit()

    def _open_series(self) -> None:
        row = self._series_rows.get(self._selected_series_id())
        if row and row["volumes"]:
            self.open_book_requested.emit(int(row["volumes"][0]["id"]))

    def _export_series(self) -> None:
        series_id = self._selected_series_id()
        row = self._series_rows.get(series_id)
        if row is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出系列清单", f"{row['name']}.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            count = self.series.export_list(series_id, path)
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "导出完成", f"已导出 {count} 卷到：\n{path}")

    def _selected_author_id(self) -> int | None:
        item = self.author_list.currentItem()
        return int(item.data(Qt.UserRole)) if item is not None else None

    def _selected_series_id(self) -> int | None:
        item = self.series_list.currentItem()
        return int(item.data(Qt.UserRole)) if item is not None else None

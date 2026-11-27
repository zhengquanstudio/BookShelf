"""图 03：单本元数据编辑 + 联网检索结果。

左侧为待确认队列，中间为编辑表单与归档预览，右侧为检索结果。
所有读写交给 MetadataService，对话框本身不直接拼 SQL。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core import authors, isbn as isbn_tools, naming
from ...db.connection import Database
from ...net.scoring import why_text
from ...services.metadata_service import MetadataService
from ...workers.metadata_worker import CoverWorker, SearchWorker

_CANDIDATE_FIELDS = (
    ("title", "书名"),
    ("subtitle", "副标题"),
    ("authors", "作者"),
    ("isbn", "ISBN"),
    ("publisher", "出版社"),
    ("date", "出版日期"),
    ("language", "语言"),
    ("series", "系列"),
    ("series_index", "卷号"),
    ("description", "简介"),
)

_STATUS_TEXT = {
    "pending": "待整理",
    "ok": "已识别",
    "partial": "待补全",
    "failed": "识别失败",
    "drm": "DRM",
    "skipped": "已跳过",
    "archived": "已归档",
}
_QUEUE_STATUS = ("pending", "partial", "failed")


class EditBookDialog(QDialog):
    saved = Signal(int)

    def __init__(
        self,
        db: Database,
        settings: Any,
        service: MetadataService | None = None,
        book_id: int | None = None,
        *,
        auto_search: bool = False,
        sync_search: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.service = service or MetadataService(db, settings)
        self.book_id = book_id
        self._sync_search = sync_search
        self._candidates: list[dict[str, Any]] = []
        self._search_worker: SearchWorker | None = None
        self._cover_workers: list[CoverWorker] = []
        self._loading = False

        self.setWindowTitle("编辑元数据")
        self.setObjectName("EditBookDialog")
        self.resize(1280, 780)
        self._build_ui()
        self._refresh_queue()
        if book_id is not None:
            self._load_book(book_id)
        else:
            self._select_first_queue_item()
        if auto_search and self.book_id is not None:
            QTimer.singleShot(0, self._search)

    # ---- 界面 -------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 8)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("EditSplitter")
        splitter.addWidget(self._build_queue())
        splitter.addWidget(self._build_form())
        splitter.addWidget(self._build_results())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([280, 560, 420])
        root.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self._message = QLabel("")
        self._message.setObjectName("DetailSub")
        footer.addWidget(self._message, 1)
        reset = QPushButton("还原为内嵌元数据")
        reset.setObjectName("GhostButton")
        reset.clicked.connect(self._reset_embedded)
        footer.addWidget(reset)
        self._search_button = QPushButton("重新检索")
        self._search_button.setObjectName("GhostButton")
        self._search_button.clicked.connect(self._search)
        footer.addWidget(self._search_button)
        close = QPushButton("关闭")
        close.setObjectName("GhostButton")
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        save_next = QPushButton("保存并下一本")
        save_next.setObjectName("GhostButton")
        save_next.clicked.connect(lambda: self._save(next_book=True))
        footer.addWidget(save_next)
        save = QPushButton("保存")
        save.setObjectName("PrimaryButton")
        save.clicked.connect(lambda: self._save(next_book=False))
        footer.addWidget(save)
        root.addLayout(footer)

    def _build_queue(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("QueuePanel")
        panel.setMinimumWidth(230)
        panel.setMaximumWidth(330)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 8, 4)
        layout.setSpacing(6)
        title = QLabel("待确认队列")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        self._queue = QListWidget()
        self._queue.setObjectName("QueueList")
        self._queue.currentItemChanged.connect(self._on_queue_changed)
        layout.addWidget(self._queue, 1)
        return panel

    def _build_form(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("EditFormScroll")
        scroll.setWidgetResizable(True)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self._title = QLineEdit()
        self._subtitle = QLineEdit()
        self._author = QLineEdit()
        self._author_norm = QLabel("—")
        self._author_norm.setObjectName("DetailSub")
        self._author_norm.setWordWrap(True)
        self._isbn = QLineEdit()
        self._isbn_state = QLabel("—")
        self._isbn_state.setObjectName("DetailSub")
        self._publisher = QLineEdit()
        self._date = QLineEdit()
        self._language = QLineEdit()
        self._series = QLineEdit()
        self._volume = QSpinBox()
        self._volume.setRange(0, 9999)
        self._volume.setSpecialValueText("无")
        self._description = QTextEdit()
        self._description.setFixedHeight(86)
        self._source = QLabel("—")
        self._source.setObjectName("DetailSub")

        form.addRow("书名", self._title)
        form.addRow("副标题", self._subtitle)
        form.addRow("作者（原文）", self._author)
        form.addRow("规范化", self._author_norm)
        form.addRow("ISBN", self._isbn)
        form.addRow("", self._isbn_state)
        form.addRow("出版社", self._publisher)
        form.addRow("出版日期", self._date)
        form.addRow("语言", self._language)
        form.addRow("系列", self._series)
        form.addRow("卷号", self._volume)
        form.addRow("简介", self._description)
        form.addRow("元数据来源", self._source)
        layout.addLayout(form)

        preview_title = QLabel("归档预览")
        preview_title.setObjectName("SectionTitle")
        layout.addWidget(preview_title)
        self._preview_box = QFrame()
        self._preview_box.setObjectName("KvBox")
        preview_layout = QVBoxLayout(self._preview_box)
        preview_layout.setContentsMargins(10, 8, 10, 8)
        preview_layout.setSpacing(4)
        self._preview_path = QLabel("—")
        self._preview_path.setObjectName("PathBox")
        self._preview_path.setWordWrap(True)
        self._preview_status = QLabel("—")
        self._preview_status.setObjectName("DetailSub")
        self._preview_status.setWordWrap(True)
        preview_layout.addWidget(self._preview_path)
        preview_layout.addWidget(self._preview_status)
        layout.addWidget(self._preview_box)
        layout.addStretch(1)

        scroll.setWidget(host)
        self._title.textChanged.connect(self._on_field_changed)
        self._author.textChanged.connect(self._on_field_changed)
        self._isbn.textChanged.connect(self._on_field_changed)
        self._series.textChanged.connect(self._on_field_changed)
        self._volume.valueChanged.connect(self._on_field_changed)
        return scroll

    def _build_results(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("ResultsPanel")
        panel.setMinimumWidth(340)
        panel.setMaximumWidth(480)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 4, 4, 4)
        layout.setSpacing(6)
        title = QLabel("检索结果")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        self._source_filter = QComboBox()
        self._source_filter.addItem("全部来源", "")
        self._source_filter.currentIndexChanged.connect(self._render_results)
        layout.addWidget(self._source_filter)
        self._results_scroll = QScrollArea()
        self._results_scroll.setObjectName("ResultsScroll")
        self._results_scroll.setWidgetResizable(True)
        host = QWidget()
        self._results_layout = QVBoxLayout(host)
        self._results_layout.setContentsMargins(2, 2, 2, 2)
        self._results_layout.setSpacing(8)
        self._results_layout.addStretch(1)
        self._results_scroll.setWidget(host)
        layout.addWidget(self._results_scroll, 1)
        return panel

    # ---- 队列与加载 -------------------------------------------------
    def _refresh_queue(self) -> None:
        selected = self.book_id
        self._queue.blockSignals(True)
        self._queue.clear()
        rows = self.db.query(
            "SELECT id, title, status FROM books WHERE status IN (?, ?, ?) "
            "ORDER BY CASE status WHEN 'partial' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, id",
            _QUEUE_STATUS,
        )
        ids: list[int] = []
        for row in rows:
            ids.append(int(row["id"]))
            item = QListWidgetItem(
                f"{row['title'] or '未命名'}  ·  {_STATUS_TEXT.get(str(row['status']), row['status'])}"
            )
            item.setData(Qt.UserRole, int(row["id"]))
            self._queue.addItem(item)
        if selected is not None and selected not in ids:
            row = self.db.query_one("SELECT id, title FROM books WHERE id = ?", (selected,))
            if row:
                item = QListWidgetItem(f"当前：{row['title'] or '未命名'}")
                item.setData(Qt.UserRole, int(row["id"]))
                self._queue.insertItem(0, item)
        self._queue.blockSignals(False)

    def _select_first_queue_item(self) -> None:
        if self._queue.count():
            self._queue.setCurrentRow(0)

    def _on_queue_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        book_id = current.data(Qt.UserRole)
        if book_id is not None:
            self._load_book(int(book_id))

    def _load_book(self, book_id: int) -> None:
        row = self.db.query_one(
            "SELECT b.*, a.name_zh AS author_name, a.country, a.country_code, "
            "a.is_chinese, s.name AS series_name "
            "FROM books AS b LEFT JOIN authors AS a ON a.id = b.author_id "
            "LEFT JOIN series AS s ON s.id = b.series_id WHERE b.id = ?",
            (book_id,),
        )
        if row is None:
            self._message.setText("书籍不存在")
            return
        self.book_id = int(book_id)
        self._loading = True
        self._title.setText(str(row["title"] or ""))
        self._subtitle.setText(str(row["subtitle"] or ""))
        self._author.setText(str(row["author_raw"] or row["author_name"] or ""))
        self._isbn.setText(str(row["isbn"] or ""))
        self._publisher.setText(str(row["publisher"] or ""))
        self._date.setText(str(row["publish_date"] or ""))
        self._language.setText(str(row["language"] or ""))
        self._series.setText(str(row["series_name"] or ""))
        self._volume.setValue(int(row["volume"] or 0))
        self._description.setPlainText(str(row["description"] or ""))
        self._source.setText(f"{row['meta_source'] or 'embedded'}  ·  置信度 {row['confidence'] or 0}")
        self._loading = False
        self.setWindowTitle(f"编辑元数据 · {row['title'] or '未命名'}")
        self._message.setText("")
        self._on_field_changed()

    # ---- 表单联动 ---------------------------------------------------
    def _on_field_changed(self, *_args) -> None:
        if self._loading:
            return
        self._validate_isbn()
        self._update_author_hint()
        self._update_preview()

    def _read(self) -> dict[str, Any]:
        return {
            "title": self._title.text().strip(),
            "subtitle": self._subtitle.text().strip(),
            "author_raw": self._author.text().strip(),
            "isbn": self._isbn.text().strip(),
            "publisher": self._publisher.text().strip(),
            "publish_date": self._date.text().strip(),
            "language": self._language.text().strip(),
            "description": self._description.toPlainText().strip(),
            "series": self._series.text().strip(),
            "volume": self._volume.value() or None,
        }

    def _validate_isbn(self) -> None:
        raw = self._isbn.text().strip()
        if not raw:
            self._isbn_state.setText("未填写 ISBN（可选）")
            self._isbn_state.setStyleSheet("")
        elif isbn_tools.is_valid(raw):
            self._isbn_state.setText("ISBN 校验通过")
            self._isbn_state.setStyleSheet("color:#4ade80;")
        else:
            self._isbn_state.setText("ISBN 校验失败，请检查")
            self._isbn_state.setStyleSheet("color:#f87171;")

    def _update_author_hint(self) -> None:
        info = authors.normalize_author(self._author.text().strip())
        if not info.name_zh:
            self._author_norm.setText("—")
            return
        parts = [info.name_zh]
        if info.country:
            parts.append(info.country)
        text = " · ".join(parts)
        if info.needs_confirm:
            text += "（译名/国别待确认）"
        self._author_norm.setText(text)

    def _preview_book(self) -> dict[str, Any]:
        data = self._read()
        return {
            "title": data["title"],
            "author_raw": data["author_raw"],
            "volume": data["volume"],
            "series_name": data["series"],
            "format": self._book_format(),
            "status": "ok",
        }

    def _book_format(self) -> str:
        row = self.db.query_one("SELECT format, file_path FROM books WHERE id = ?", (self.book_id,))
        if row is None:
            return ""
        return str(row["format"] or Path(str(row["file_path"] or "")).suffix.lstrip("."))

    def _update_preview(self) -> None:
        if self.book_id is None:
            return
        rules = naming.NamingRules.from_config(self.settings.data)
        plan = naming.plan_target(self._preview_book(), rules)
        if plan.target_name:
            self._preview_path.setText(plan.display())
        else:
            self._preview_path.setText("—")
        status_text = {
            "ready": "路径可用",
            "conflict": "存在冲突，将追加序号或待确认",
            "skip": "该状态不参与整理",
            "failed": "无法生成路径",
            "drm": "受 DRM 保护，不参与整理",
        }.get(plan.status, plan.status)
        self._preview_status.setText(f"{status_text}  {plan.message}".strip())

    # ---- 检索 -------------------------------------------------------
    def _search(self) -> None:
        if self.book_id is None:
            self._message.setText("请先选择一本书")
            return
        book = self._preview_book()
        if not book["title"] and not self._isbn.text().strip():
            self._message.setText("请先填写书名或 ISBN")
            return
        self._search_button.setEnabled(False)
        self._message.setText("正在检索豆瓣、Crossref、OpenLibrary 与 Google Books…")
        if self._sync_search:
            try:
                self._on_search_finished(self.service.find_candidates(book))
            except Exception as exc:
                self._on_search_failed(str(exc))
            return
        worker = SearchWorker(self.service, book)
        worker.signals.finished.connect(self._on_search_finished)
        worker.signals.failed.connect(self._on_search_failed)
        self._search_worker = worker
        QThreadPool.globalInstance().start(worker)

    def _on_search_finished(self, candidates: list[dict[str, Any]]) -> None:
        self._search_button.setEnabled(True)
        self._candidates = list(candidates or [])
        self._refresh_source_filter()
        self._message.setText(
            f"检索完成，共 {len(self._candidates)} 条结果" if self._candidates else "未找到结果，可手动填写"
        )
        self._render_results()

    def _refresh_source_filter(self) -> None:
        current = str(self._source_filter.currentData() or "")
        names = {str(item.get("source") or "") for item in self._candidates}
        self._source_filter.blockSignals(True)
        self._source_filter.clear()
        self._source_filter.addItem("全部来源", "")
        for name in sorted(name for name in names if name):
            self._source_filter.addItem(name, name)
        index = self._source_filter.findData(current)
        self._source_filter.setCurrentIndex(index if index >= 0 else 0)
        self._source_filter.blockSignals(False)

    def _on_search_failed(self, message: str) -> None:
        self._search_button.setEnabled(True)
        self._candidates = []
        self._render_results()
        self._message.setText(f"检索失败：{message}")

    def _visible_candidates(self) -> list[dict[str, Any]]:
        """过滤被否决候选，并把 60–84 分的待确认候选置顶。"""
        source = str(self._source_filter.currentData() or "")
        visible = [
            item
            for item in self._candidates
            if not item.get("rejected") and (not source or item.get("source") == source)
        ]
        low, high = self.service.confirm_score, self.service.auto_score
        visible.sort(
            key=lambda item: 0 if low <= int(item.get("score") or 0) < high else 1
        )
        return visible

    def _render_results(self, *_args) -> None:
        while self._results_layout.count():
            item = self._results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        visible = self._visible_candidates()
        if not visible:
            hint = QLabel("暂无结果。填写书名/ISBN 后点击「重新检索」。")
            hint.setObjectName("DetailSub")
            hint.setWordWrap(True)
            self._results_layout.addWidget(hint)
        for candidate in visible:
            self._results_layout.addWidget(self._result_card(candidate))
        self._results_layout.addStretch(1)

    @staticmethod
    def _field_value(candidate: dict[str, Any], key: str) -> str:
        value = candidate.get(key)
        if key == "authors":
            return "、".join(str(item) for item in (value or []) if str(item).strip())
        if value in (None, ""):
            return ""
        return str(value)

    def _available_fields(self, candidate: dict[str, Any]) -> list[tuple[str, str]]:
        return [
            (key, label)
            for key, label in _CANDIDATE_FIELDS
            if self._field_value(candidate, key)
        ]

    def _default_fields(self, candidate: dict[str, Any]) -> set[str]:
        """高分候选默认全勾（简介除外）；待确认候选只勾书名与作者。"""
        available = {key for key, _label in self._available_fields(candidate)}
        if int(candidate.get("score") or 0) >= self.service.auto_score:
            return available - {"description"}
        return available & {"title", "authors"}

    def _result_card(self, candidate: dict[str, Any]) -> QWidget:
        card = QFrame()
        card.setObjectName("ResultCard")
        score = int(candidate.get("score") or 0)
        pending = self.service.confirm_score <= score < self.service.auto_score
        if pending:
            card.setStyleSheet(
                "QFrame#ResultCard{background:rgba(250,204,21,0.10);"
                "border:1px solid #facc15;}"
            )
        outer = QHBoxLayout(card)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(10)

        cover = QLabel("无封面")
        cover.setObjectName("DetailSub")
        cover.setFixedSize(72, 100)
        cover.setAlignment(Qt.AlignCenter)
        cover.setWordWrap(True)
        outer.addWidget(cover, 0, Qt.AlignTop)
        self._load_cover(cover, str(candidate.get("cover_url") or ""))

        body = QVBoxLayout()
        body.setSpacing(4)
        outer.addLayout(body, 1)

        header = QHBoxLayout()
        title = QLabel(str(candidate.get("title") or "未命名"))
        title.setObjectName("ResultTitle")
        title.setWordWrap(True)
        header.addWidget(title, 1)
        badge = QLabel(str(candidate.get("source") or "未知来源"))
        badge.setObjectName("StatusPill")
        header.addWidget(badge, 0, Qt.AlignTop)
        body.addLayout(header)

        authors_text = "、".join(candidate.get("authors") or []) or "作者未知"
        detail = " · ".join(
            part for part in (
                authors_text,
                str(candidate.get("date") or ""),
                str(candidate.get("publisher") or ""),
            ) if part
        )
        sub = QLabel(detail)
        sub.setObjectName("DetailSub")
        sub.setWordWrap(True)
        body.addWidget(sub)
        reasons = why_text(candidate.get("why"))
        if reasons:
            why_label = QLabel("匹配依据：" + " / ".join(reasons))
            why_label.setObjectName("DetailSub")
            why_label.setWordWrap(True)
            body.addWidget(why_label)
        if pending:
            note = QLabel("待确认：默认只勾选书名与作者，请核对后再应用")
            note.setObjectName("DetailSub")
            note.setWordWrap(True)
            body.addWidget(note)

        boxes: dict[str, QCheckBox] = {}
        defaults = self._default_fields(candidate)
        checks = QGridLayout()
        checks.setHorizontalSpacing(10)
        checks.setVerticalSpacing(2)
        for index, (key, label) in enumerate(self._available_fields(candidate)):
            box = QCheckBox(label)
            box.setChecked(key in defaults)
            boxes[key] = box
            checks.addWidget(box, index // 3, index % 3)
        if boxes:
            body.addLayout(checks)

        foot = QHBoxLayout()
        score_label = QLabel(f"匹配度 {score}%")
        score_label.setObjectName("StatusPill")
        color = "#4ade80" if score >= self.service.auto_score else (
            "#facc15" if score >= self.service.confirm_score else "#f87171"
        )
        score_label.setStyleSheet(f"color:{color};")
        foot.addWidget(score_label)
        foot.addStretch(1)
        apply_button = QPushButton("应用勾选字段")
        apply_button.setObjectName("GhostButton")
        apply_button.clicked.connect(
            lambda _=False, c=candidate, b=boxes: self._apply_candidate(
                c, fields={key for key, box in b.items() if box.isChecked()}
            )
        )
        foot.addWidget(apply_button)
        body.addLayout(foot)
        return card

    def _load_cover(self, label: QLabel, url: str) -> None:
        if not url:
            return
        worker = CoverWorker(self.service, url)
        worker.signals.finished.connect(
            lambda data, target=label: self._show_cover(target, data)
        )
        worker.signals.failed.connect(lambda _message: None)
        self._cover_workers.append(worker)
        QThreadPool.globalInstance().start(worker)

    @staticmethod
    def _show_cover(label: QLabel, data: bytes) -> None:
        try:
            pixmap = QPixmap()
            if pixmap.loadFromData(data or b""):
                label.setPixmap(
                    pixmap.scaled(
                        72, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                )
                label.setText("")
        except RuntimeError:  # 卡片已随结果刷新销毁
            pass

    def _apply_candidate(
        self, candidate: dict[str, Any], fields: set[str] | None = None
    ) -> None:
        chosen = None if fields is None else set(fields)

        def want(key: str) -> bool:
            return chosen is None or key in chosen

        self._loading = True
        if want("title") and candidate.get("title"):
            self._title.setText(str(candidate["title"]))
        if want("subtitle") and candidate.get("subtitle"):
            self._subtitle.setText(str(candidate["subtitle"]))
        authors_list = candidate.get("authors") or []
        if want("authors") and authors_list:
            self._author.setText("、".join(str(item) for item in authors_list))
        if want("isbn") and candidate.get("isbn"):
            self._isbn.setText(str(candidate["isbn"]))
        if want("publisher") and candidate.get("publisher"):
            self._publisher.setText(str(candidate["publisher"]))
        if want("date") and candidate.get("date"):
            self._date.setText(str(candidate["date"]))
        if want("language") and candidate.get("language"):
            self._language.setText(str(candidate["language"]))
        if want("description") and candidate.get("description"):
            self._description.setPlainText(str(candidate["description"]))
        if want("series") and candidate.get("series"):
            self._series.setText(str(candidate["series"]))
        index = candidate.get("series_index")
        if want("series_index") and index not in (None, ""):
            try:
                self._volume.setValue(int(float(str(index))))
            except (TypeError, ValueError):
                pass
        self._source.setText(
            f"{candidate.get('source') or 'network'}  ·  匹配度 {candidate.get('score') or 0}%"
        )
        self._loading = False
        if chosen is not None and not chosen:
            self._message.setText("未勾选任何字段，未修改表单")
        else:
            self._message.setText("已填入勾选字段，点击「保存」写入数据库")
        self._on_field_changed()

    # ---- 保存 / 还原 ------------------------------------------------
    def _save(self, *, next_book: bool) -> None:
        if self.book_id is None:
            self._message.setText("请先选择一本书")
            return
        fields = self._read()
        fields["series_index"] = fields["volume"]
        try:
            self.service.save_manual(self.book_id, fields)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.saved.emit(self.book_id)
        self._message.setText("已保存")
        self._refresh_queue()
        if next_book:
            self._select_next()
        else:
            self._load_book(self.book_id)

    def _select_next(self) -> None:
        if not self._queue.count():
            self._message.setText("队列已空")
            return
        for index in range(self._queue.count()):
            item = self._queue.item(index)
            if item.data(Qt.UserRole) != self.book_id:
                self._queue.setCurrentRow(index)
                return
        self._message.setText("没有下一本待确认书籍")

    def _reset_embedded(self) -> None:
        if self.book_id is None:
            return
        try:
            self.service.reset_to_embedded(self.book_id)
        except Exception as exc:
            QMessageBox.warning(self, "还原失败", str(exc))
            return
        self._load_book(self.book_id)
        self._message.setText("已还原为文件内嵌元数据")

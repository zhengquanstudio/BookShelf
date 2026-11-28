"""图 05 · 内嵌阅读器宿主：工具栏、目录、正文 Web 载体、底部进度。"""

from __future__ import annotations

import copy
import json
import re
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRunnable,
    QThreadPool,
    QTime,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QUrl

from ... import config
from ...core import isbn as isbn_tools
from ...core.metadata.opf_write import backup_path, write_embedded_metadata
from ...db.connection import Database
from ...db.repositories.book_repo import BookRepository
from ...db.repositories.reading_repo import ReadingRepository
from ...errors import BookShelfError
from ...logger import get_logger
from ...reader.converter import PreparedBook, pdf_outline, prepare_book
from ...reader import ASSETS_DIR
from ...reader.view import ReaderWebView
from ...services.library_service import LibraryService
from ...services.metadata_service import MetadataService
from ...services.organize_service import OrganizeService
from ...services.settings_service import SettingsService
from ..theme_tokens import PALETTES, THEME_KEYS, ReaderPalette, mix, palette_for
from ..widgets.book_detail_overlay import BookDetailOverlay
from ..widgets.icon_button import IconButton
from ..widgets.reader_cover_card import ReaderCoverCard
from ..widgets.segmented_progress import SegmentedProgress
from ..widgets.stepper import Stepper

log = get_logger("reader")

_FONTS = (
    "LXGW WenKai",
    "Noto Serif CJK SC",
    "Source Han Serif SC",
    "SimSun",
    "Microsoft YaHei",
    "KaiTi",
    "Georgia",
)


def _load_font_catalog() -> list[dict[str, Any]]:
    """读取内置字体清单 fonts.json；文件缺失的项标记 missing（置灰，不静默回退）。"""
    path = ASSETS_DIR / "fonts" / "fonts.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    catalog: list[dict[str, Any]] = []
    for item in data.get("fonts") or []:
        family = str(item.get("family") or "").strip()
        if not family:
            continue
        file_name = str(item.get("file") or "").strip()
        exists = bool(file_name) and (ASSETS_DIR / "fonts" / file_name).is_file()
        catalog.append({
            "label": str(item.get("label") or family),
            "group": str(item.get("group") or ""),
            "family": family,
            "default": bool(item.get("default")),
            "missing": not exists,
        })
    return catalog


_FONT_CATALOG: list[dict[str, Any]] | None = None


def _font_catalog() -> list[dict[str, Any]]:
    global _FONT_CATALOG
    if _FONT_CATALOG is None:
        _FONT_CATALOG = _load_font_catalog()
    return _FONT_CATALOG


def _default_font_family(group: str, fallback: str) -> str:
    """fonts.json 里该组的默认字体；无默认取该组第一项，清单为空则回退 fallback。"""
    fonts = [f for f in _font_catalog() if f["group"] == group]
    for font in fonts:
        if font["default"]:
            return font["family"]
    return fonts[0]["family"] if fonts else fallback

_PREF_MODES = ("auto", "light", "dark")
_TURN_STYLES = (
    ("instant", "直接"),
    ("push", "平移"),
    ("slide", "滑动"),
    ("curl", "卷角"),
    ("flip", "整页"),
)
# 动效时长来自规范 §2.3，悬停提示里写清楚，用户不必试错。
_TURN_TIPS = {
    "instant": "直接翻页 · 无过渡",
    "push": "平移 · 300ms 两段式",
    "slide": "滑动 · 420ms",
    "curl": "卷角 · 520ms",
    "flip": "整页翻 · 520ms View Transition",
}
# 主题模式按“浅色 / 深色 / 跟随系统”展示，配置值仍是 light/dark/auto。
_MODE_SEGMENTS = (("light", "浅色"), ("dark", "深色"), ("auto", "跟随系统"))
_TEXTURES = (("none", "无"), ("paper", "纸纹"), ("noise", "细噪"))
_FONT_WEIGHTS = (400, 500, 600)
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")

# D3：高亮五色默认值，只接受 #rrggbb（6 位），非法位回退默认。
_HL_DEFAULT = ["#f2c14e", "#d99c98", "#9cc39a", "#8fb3d9", "#b6a4d9"]


def _highlight_colors(raw: Any) -> list[str]:
    """校验高亮色列表：长度固定 5，仅接受 #rrggbb，非法项回落默认值。"""
    if not isinstance(raw, (list, tuple)):
        return list(_HL_DEFAULT)
    out = list(_HL_DEFAULT)
    for i, v in enumerate(list(raw)[:5]):
        s = str(v).strip().lower()
        if _HEX_COLOR.match(s):
            out[i] = s
    return out

# 目录行的数据角色：数字沿用 Qt.UserRole，其余依次递增，测试可按 0x0100 取目标。
_ROLE_TARGET = Qt.UserRole
_ROLE_LABEL = Qt.UserRole + 1
_ROLE_HREF = Qt.UserRole + 2
_ROLE_PAGE = Qt.UserRole + 3
_ROLE_INDEX = Qt.UserRole + 4
_ROLE_LEVEL = Qt.UserRole + 5


class _TocItemDelegate(QStyledItemDelegate):
    """目录行：序号 + 标题（省略） + 页码；当前章整行浅底 + 左侧 3px 竖条 + 「当前位置」胶囊。"""

    ROW_HEIGHT = 34
    NUMBER_WIDTH = 28
    PAGE_WIDTH = 32
    PADDING = 8
    TAG_TEXT = "当前位置"

    def __init__(self, palette_provider, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette_provider = palette_provider

    def sizeHint(self, option, index):  # noqa: N802
        size = super().sizeHint(option, index)
        size.setHeight(self.ROW_HEIGHT)
        return size

    def paint(self, painter, option, index) -> None:  # noqa: N802
        theme = self._palette_provider()
        rect = option.rect
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        if selected:
            painter.fillRect(rect, QColor(theme.panel))
            painter.fillRect(
                rect.left(),
                rect.top() + 7,
                3,
                max(0, rect.height() - 14),
                QColor(theme.accent),
            )
        elif hovered:
            painter.fillRect(rect, QColor(theme.chrome))

        number = str(index.data(_ROLE_INDEX) or "")
        title = str(index.data(_ROLE_LABEL) or "")
        page = str(index.data(_ROLE_PAGE) or "")
        level = max(0, int(index.data(_ROLE_LEVEL) or 0))

        # 当前章右侧的「当前位置」胶囊：先量出宽度，把页码让到它左边。
        tag_w = 0
        if selected:
            tag_font = QFont(painter.font())
            tag_font.setPixelSize(9)
            tag_w = QFontMetrics(tag_font).horizontalAdvance(self.TAG_TEXT) + 10

        font = painter.font()
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(QColor(theme.muted))
        number_rect = rect.adjusted(self.PADDING, 0, 0, 0)
        number_rect.setWidth(self.NUMBER_WIDTH)
        painter.drawText(number_rect, Qt.AlignRight | Qt.AlignVCenter, number)

        page_right = rect.right() - self.PADDING - (tag_w + 6 if tag_w else 0)
        page_rect = QRect(
            page_right - self.PAGE_WIDTH + 1, rect.top(),
            self.PAGE_WIDTH, rect.height(),
        )
        painter.drawText(page_rect, Qt.AlignRight | Qt.AlignVCenter, page)

        font.setPixelSize(13)
        painter.setFont(font)
        painter.setPen(QColor(theme.ink))
        title_left = number_rect.right() + 8 + level * 10
        title_width = max(10, page_rect.left() - 8 - title_left)
        elided = painter.fontMetrics().elidedText(title, Qt.ElideRight, title_width)
        painter.drawText(
            title_left, rect.top(), title_width, rect.height(),
            Qt.AlignLeft | Qt.AlignVCenter, elided,
        )

        if tag_w:
            tag_h = 16
            tag_rect = QRect(
                rect.right() - self.PADDING - tag_w,
                rect.center().y() - tag_h // 2,
                tag_w, tag_h,
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.accent))
            painter.drawRoundedRect(tag_rect, 4, 4)
            painter.setBrush(Qt.NoBrush)
            tag_font = QFont(painter.font())
            tag_font.setPixelSize(9)
            painter.setFont(tag_font)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(tag_rect, Qt.AlignCenter, self.TAG_TEXT)
        painter.restore()


def _as_int(value: Any, default: int) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool) -> bool:
    """兼容老配置里的 "false"/"0" 字符串，避免 bool("false") 为真。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(value)


def _system_dark() -> bool:
    """系统是否处于深色模式；取不到时按浅色处理。"""
    try:
        return "dark" in str(QGuiApplication.styleHints().colorScheme()).lower()
    except Exception:  # 无 GUI 或旧版本 Qt
        return False


def _is_dark_palette(theme: ReaderPalette) -> bool:
    """夜读主题的交互浮层用白色叠加，其余主题用黑色叠加。"""
    return theme.key == "dark"


def _reader_qss(theme: ReaderPalette) -> str:
    """阅读器窗口的局部样式，跟随主题切换，优先于全局样式表。"""
    hover = "rgba(255,255,255,0.08)" if _is_dark_palette(theme) else "rgba(0,0,0,0.06)"
    pressed = "rgba(255,255,255,0.12)" if _is_dark_palette(theme) else "rgba(0,0,0,0.10)"
    dark = theme.key == "dark"
    accent_soft = mix(theme.accent, theme.page, 0.82)
    accent_ink = mix(theme.accent, "#ffffff" if dark else theme.ink, 0.55)
    return f"""
    #ReaderPage {{ background: {theme.chrome}; }}
    #ReaderTopBar, #ReaderBottomBar {{ background: {theme.chrome}; border: 0; }}
    #ReaderTopBar {{ border-bottom: 1px solid {theme.border}; }}
    #ReaderBottomBar {{ border-top: 1px solid {theme.border}; }}
    #ReaderTopTitle {{ color: {theme.ink}; font-size: 13px; font-weight: 600; background: transparent; }}
    #ReaderTopBook {{ color: {theme.muted}; font-size: 11px; background: transparent; }}
    #ReaderTocMeta, #ReaderPageLabel, #ReaderRemaining, #ReaderClock, #ReaderSearchCount,
    #ReaderSectionTitle, #ReaderPrefsLabel {{ color: {theme.muted}; background: transparent; }}
    #ReaderPercent {{ color: {theme.ink}; background: transparent; font-weight: 600; }}
    QPushButton#ReaderIconButton {{ background: transparent; border: 0; border-radius: 9px; }}
    QPushButton#ReaderIconButton:hover {{ background: {hover}; }}
    QPushButton#ReaderIconButton:checked {{ background: {pressed}; }}
    QPushButton#ReaderIconButton:pressed {{ background: {pressed}; }}
    QPushButton#ReaderTool {{
        background: transparent; color: {theme.ink};
        border: 1px solid transparent; border-radius: 7px; padding: 5px 9px;
    }}
    QPushButton#ReaderTool:hover {{ background: {theme.panel}; border-color: {theme.border}; }}
    QPushButton#ReaderTool:checked {{ background: {theme.panel}; border-color: {theme.accent}; color: {theme.accent}; }}
    QPushButton#ReaderBack {{ background: transparent; color: {theme.ink}; border: 0; border-radius: 7px; padding: 6px 10px; }}
    QPushButton#ReaderBack:hover {{ background: {theme.panel}; }}
    QPushButton#ReaderTabButton {{
        background: transparent; color: {theme.muted}; border: 0;
        border-bottom: 2px solid transparent; border-radius: 0; padding: 8px 10px;
    }}
    QPushButton#ReaderTabButton:hover {{ color: {theme.ink}; }}
    QPushButton#ReaderTabButton:checked {{ color: {theme.ink}; border-bottom: 2px solid {theme.accent}; font-weight: 600; }}
    #ReaderSidebar {{ background: {theme.chrome}; border-right: 1px solid {theme.border}; }}
    #ReaderSidebarPage {{ background: transparent; }}
    #ReaderTocList, #ReaderNoteList, #ReaderBookmarkList {{ background: transparent; color: {theme.ink}; border: 0; outline: 0; }}
    #ReaderTocList::item {{ padding: 0; border: 0; background: transparent; }}
    #ReaderNoteList::item, #ReaderBookmarkList::item {{ padding: 7px 8px; border-radius: 6px; color: {theme.ink}; }}
    #ReaderNoteList::item:hover, #ReaderBookmarkList::item:hover {{ background: {theme.panel}; }}
    #ReaderNoteList::item:selected, #ReaderBookmarkList::item:selected {{ background: {theme.panel}; color: {theme.ink}; }}
    #ReaderSearchBar {{ background: {theme.chrome}; border-bottom: 1px solid {theme.border}; }}
    QLineEdit#ReaderSearchEdit {{
        background: {theme.panel}; color: {theme.ink};
        border: 1px solid {theme.border}; border-radius: 7px; padding: 5px 9px;
    }}
    #ReaderPrefsPopup {{ background: {theme.panel}; border: 1px solid {theme.border}; border-radius: 14px; }}
    QPushButton#ReaderPrefsTab {{
        background: transparent; color: {theme.muted}; border: 0;
        border-bottom: 2px solid transparent; border-radius: 0; padding: 7px 2px;
        font-size: 13px;
    }}
    QPushButton#ReaderPrefsTab:hover {{ color: {theme.ink}; }}
    QPushButton#ReaderPrefsTab:checked {{
        color: {theme.ink}; border-bottom: 2px solid {theme.accent}; font-weight: 600;
    }}
    #ReaderPrefsSection {{ color: {theme.muted}; font-size: 12px; background: transparent; }}
    #ReaderPrefsValue {{ color: {theme.muted}; font-size: 12px; background: transparent; }}
    QPushButton#ReaderPrefsSegment {{
        background: transparent; color: {theme.muted};
        border: 1px solid {theme.border}; border-radius: 7px;
        padding: 3px 4px; font-size: 12px;
    }}
    QPushButton#ReaderPrefsSegment:hover {{ color: {theme.ink}; border-color: {theme.accent}; }}
    QPushButton#ReaderPrefsSegment:checked {{
        color: {theme.accent}; border-color: {theme.accent};
        background: {theme.panel}; font-weight: 600;
    }}
    QPushButton#StepBtn {{
        background: transparent; color: {theme.ink};
        border: 1px solid {theme.border}; border-radius: 8px; font-size: 15px;
    }}
    QPushButton#StepBtn:hover {{ border-color: {theme.accent}; color: {theme.accent}; }}
    QPushButton#StepBtn:pressed {{ background: {theme.accent}; color: #ffffff; border-color: {theme.accent}; }}
    QPushButton#StepBtn:disabled {{ color: {theme.muted}; border-color: {theme.border}; }}
    #StepValue {{ color: {theme.ink}; font-size: 13px; background: transparent; }}
    QCheckBox {{ color: {theme.ink}; font-size: 12px; spacing: 5px; background: transparent; }}
    QCheckBox::indicator {{
        width: 15px; height: 15px; border: 1px solid {theme.border};
        border-radius: 4px; background: {theme.chrome};
    }}
    QCheckBox::indicator:checked {{ background: {theme.accent}; border-color: {theme.accent}; }}
    #ReaderAccentSwatch {{ border-radius: 4px; }}
    #ReaderErrorPage, #ReaderLoadingPage, #ReaderPlaceholder {{ background: {theme.chrome}; }}
    #ReaderErrorTitle {{ color: {theme.ink}; font-size: 17px; font-weight: 600; background: transparent; }}
    #ReaderErrorText, #ReaderErrorHint {{ color: {theme.muted}; background: transparent; }}
    /* 分段进度条完全自绘（见 SegmentedProgress），QSS 只负责让背景透明。 */
    QSlider#ReaderProgress {{ background: transparent; }}
    QComboBox {{
        background: {theme.chrome}; color: {theme.ink};
        border: 1px solid {theme.border}; border-radius: 6px; padding: 3px 6px;
    }}
    #ReaderDetailOverlay {{ background: {theme.panel}; border: 1px solid {theme.border}; border-radius: 12px; }}
    #ReaderDetailScroll, #ReaderDetailBody {{ background: {theme.panel}; border: 0; }}
    #ReaderDetailCover {{ background: {theme.chrome}; color: {theme.muted}; border: 1px solid {theme.border}; border-radius: 6px; }}
    #ReaderDetailTitle {{ color: {theme.ink}; background: transparent; font-size: 15.5px; font-weight: 600; }}
    #ReaderDetailAuthor, #ReaderDetailTags {{ color: {theme.muted}; background: transparent; font-size: 11px; }}
    #ReaderDetailSection {{ color: {theme.muted}; background: transparent; font-size: 10.5px; font-weight: 600; }}
    #ReaderDetailKey {{ color: {theme.muted}; background: transparent; font-size: 11.5px; }}
    #ReaderDetailRow, #ReaderDetailPath, #ReaderDetailDescription {{ color: {theme.ink}; background: transparent; font-size: 11.5px; }}
    #ReaderDetailArchiveState {{ background: transparent; font-size: 11px; }}
    #ReaderDetailArchiveState[state="ok"] {{ color: #4e7d46; }}
    #ReaderDetailArchiveState[state="pending"] {{ color: #a97c3c; }}
    QPushButton#ReaderDetailClose, QPushButton#ReaderDetailDescriptionToggle {{
        background: transparent; color: {theme.muted}; border: 0; border-radius: 7px;
    }}
    QPushButton#ReaderDetailClose:hover, QPushButton#ReaderDetailDescriptionToggle:hover {{ color: {theme.accent}; background: {hover}; }}
    #ReaderDetailActions {{ background: {theme.chrome}; border-top: 1px solid {theme.border}; }}
    QPushButton#ReaderDetailAction, QPushButton#ReaderDetailGhost {{
        background: {theme.panel}; color: {theme.ink}; border: 1px solid {theme.border};
        border-radius: 7px; padding: 4px 5px; font-size: 10.5px;
    }}
    QPushButton#ReaderDetailAction:hover {{ color: {theme.accent}; border-color: {theme.accent}; }}
    QPushButton#ReaderDetailAction:disabled, QPushButton#ReaderDetailGhost:disabled {{ color: {theme.muted}; background: {theme.chrome}; }}
    QPushButton#ReaderDetailGhost:disabled {{ border-style: dashed; }}
    QPushButton#ReaderDetailPrimary {{
        background: {theme.accent}; color: #ffffff; border: 1px solid {theme.accent};
        border-radius: 7px; padding: 4px 8px; font-size: 10.5px; font-weight: 600;
    }}
    QPushButton#ReaderDetailPrimary:hover {{ background: {theme.ink}; border-color: {theme.ink}; }}
    QLineEdit#ReaderDetailInput {{
        background: {theme.page}; color: {theme.ink}; border: 1px solid {theme.border};
        border-radius: 6px; padding: 3px 6px; font-size: 11.5px; min-height: 20px;
    }}
    QLineEdit#ReaderDetailInput:focus {{ border-color: {theme.accent}; }}
    #ReaderDetailEditHint {{ color: {theme.muted}; background: transparent; font-size: 10px; }}
    #ReaderDetailStatus {{ color: {theme.accent}; background: transparent; font-size: 11px; }}
    #ReaderDetailStatus[error="true"] {{ color: #c05a78; }}
    QSplitter#ReaderSplitter::handle:horizontal {{ background: {theme.border}; }}
    QSplitter#ReaderSplitter::handle:horizontal:hover {{ background: {theme.accent}; }}
    /* T9：侧栏顶部封面卡 */
    #ReaderCoverCard {{ background: {theme.panel}; border: 1px solid {theme.border}; border-radius: 14px; }}
    #ReaderCoverTitle {{ color: {theme.ink}; font-size: 14.5px; font-weight: 600; background: transparent; }}
    #ReaderCoverAuthor {{ color: {theme.muted}; font-size: 11.5px; background: transparent; }}
    #ReaderCoverPill {{ background: {accent_soft}; color: {accent_ink}; border-radius: 20px; padding: 1px 6px; font-size: 10px; font-weight: 600; }}
    #ReaderCoverPercent {{ color: {theme.muted}; font-size: 10.5px; background: transparent; }}
    QProgressBar#ReaderCoverProgress {{ background: {theme.border}; border: 0; border-radius: 3px; }}
    QProgressBar#ReaderCoverProgress::chunk {{ background: {theme.accent}; border-radius: 3px; }}
    QPushButton#ReaderCoverInfo {{ background: {theme.chrome}; color: {theme.muted}; border: 1px solid {theme.border}; border-radius: 11px; font-size: 11px; font-weight: 600; }}
    QPushButton#ReaderCoverInfo:hover {{ color: {theme.accent}; border-color: {theme.accent}; }}
    """


def open_with_system(path: str) -> str | None:
    """用系统默认程序打开文件；成功返回 None，失败返回可展示的错误说明。"""
    target = Path(path)
    if not target.is_file():
        return "文件不存在或已被移动"
    try:
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
    except OSError as exc:
        return f"无法启动系统默认程序：{exc}"
    if not opened:
        return "无法启动系统默认程序，请检查该格式的文件关联。"
    return None


def _prepare_for_reader(path: str) -> tuple[PreparedBook, dict[str, Any] | None]:
    prepared = prepare_book(path)
    outline = (
        pdf_outline(Path(prepared.path))
        if prepared.ok and prepared.kind == "pdf" and prepared.path
        else None
    )
    return prepared, outline


class _PrepareSignals(QObject):
    finished = Signal(int, object, object)


class _PrepareWorker(QRunnable):
    """在后台探测、转换并提取目录，避免阻塞 Qt 主线程。"""

    def __init__(self, serial: int, path: str) -> None:
        super().__init__()
        self.serial = serial
        self.path = path
        self.signals = _PrepareSignals()

    def run(self) -> None:
        try:
            prepared, outline = _prepare_for_reader(self.path)
        except Exception as exc:  # 后台异常必须回到可读错误页
            log.warning("准备阅读文件失败：%s", exc)
            prepared, outline = PreparedBook(error=f"读取或转换失败：{exc}"), None
        self.signals.finished.emit(self.serial, prepared, outline)


class _ClickableLabel(QLabel):
    """封面与书名共用：保持 QLabel 的省略/绘图行为，同时提供点击信号。"""

    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ReaderContainer(QWidget):
    """阅读态整页容器；由主窗口在内容区切换显示。"""

    back_requested = Signal()
    book_changed = Signal(int)
    loading_progress = Signal(str, int)

    def __init__(
        self,
        db: Database,
        settings: SettingsService,
        *,
        web_enabled: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ReaderPage")
        self.db = db
        self.settings = settings
        self.repo = ReadingRepository(db)
        self._web_enabled = web_enabled
        self._book_id: int | None = None
        self._book: dict[str, Any] = {}
        self._book_path = ""
        self._prepared: Any = None
        self._toc: list[dict[str, Any]] = []
        self._location: dict[str, Any] = {}
        self._spread_active = False  # R2：摊开模式当前是否真正生效
        # 已访问章节的页码缓存：EPUB 未访问的目录行显示 ~，不为了页码逐章 goTo。
        self._chapter_pages: dict[str, int] = {}
        self._icon_buttons: list[IconButton] = []
        self._title_full = ""
        self._sidebar_visible = True
        self._sidebar_width = 288
        self._clock_24h = True
        self._syncing = False
        self._open_serial = 0
        self._loading_stage = ""
        self._prepare_pool = QThreadPool(self)
        self._prepare_pool.setMaxThreadCount(1)
        self._slow_timer = QTimer(self)
        self._slow_timer.setSingleShot(True)
        self._slow_timer.setInterval(10000)
        self._slow_timer.timeout.connect(self._show_slow_loading)
        # 前端渲染回调缺失时的兜底，避免永久停在 65%。
        self._render_watchdog = QTimer(self)
        self._render_watchdog.setSingleShot(True)
        self._render_watchdog.setInterval(45000)
        self._render_watchdog.timeout.connect(self._on_render_timeout)

        # D2 会话采集：每分钟落一次库，只在窗口激活且未最小化时累计。
        self._session_id: int | None = None
        self._session_last: float | None = None
        self._session_seconds = 0.0
        self._session_pages = 0
        self._filtered_window: QWidget | None = None
        self._session_timer = QTimer(self)
        self._session_timer.setInterval(60000)
        self._session_timer.timeout.connect(self._flush_session)
        self._session_timer.start()

        # D3：一次性把老配置 column_count=2 迁移为 page_mode=spread。
        self._migrate_reader_prefs_v5()

        self._build_ui()
        self._bind_shortcuts()
        self._init_chrome_autohide()
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(30000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()
        self._apply_theme()
        self._refresh_toc_meta()
        self._sync_prefs_widgets()

    # ---- 界面搭建 ---------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        # 顶底栏使用绝对定位；预留区域在显隐时保持不变，正文不会跳动。
        root.setContentsMargins(0, 46, 0, 40)
        root.setSpacing(0)
        self.topbar = self._build_topbar()
        self.topbar.setParent(self)

        self._center = QWidget()
        center_layout = QVBoxLayout(self._center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        center_layout.addWidget(self._build_search())
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_web())
        self.stack.addWidget(self._build_error())
        center_layout.addWidget(self.stack, 1)

        # 左右分栏可拖动，像 Readest 一样把目录与正文分开。
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setObjectName("ReaderSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(5)
        self.splitter.addWidget(self._build_sidebar())
        self.splitter.addWidget(self._center)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([self._sidebar_width, 1000])
        self.sidebar.setMaximumWidth(self._sidebar_width)
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        # 侧栏折叠动效：160ms 内把左栏 maximumWidth 降到 0，QSplitter 随之收窄。
        self._sidebar_anim = QPropertyAnimation(self.sidebar, b"maximumWidth", self)
        self._sidebar_anim.setDuration(160)
        self._sidebar_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._sidebar_anim.valueChanged.connect(self._on_sidebar_anim_value)
        self._sidebar_anim.finished.connect(self._on_sidebar_anim_finished)

        self.body = self.splitter
        root.addWidget(self.splitter, 1)

        # 载入页做成浮层而不是堆叠页：WebEngine 视图被隐藏时 Chromium 会冻结页面，
        # epub.js 的渲染队列依赖 requestAnimationFrame，隐藏后就不再有渲染回调。
        self.loading_overlay = self._build_loading(self._center)
        self.loading_overlay.hide()

        self.bottombar = self._build_bottom()
        self.bottombar.setParent(self)
        self._bottombar_opacity = QGraphicsOpacityEffect(self.bottombar)
        self._bottombar_opacity.setOpacity(1.0)
        self.bottombar.setGraphicsEffect(self._bottombar_opacity)
        self.topbar.raise_()
        self.bottombar.raise_()
        self.detail_panel = BookDetailOverlay(
            self,
            on_close=self._hide_book_detail,
            on_reveal=self._reveal_book_folder,
            on_rename=self._recalculate_book_path,
            on_back=self._on_back,
            on_note=self._detail_add_note,
            on_bookmark=self._detail_add_bookmark,
            on_restore=self._restore_embedded_metadata,
        )
        self.detail_panel.save_requested.connect(self._save_book_detail_edit)
        self.search_bar.hide()

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("ReaderTopBar")
        bar.setFixedHeight(46)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(6)

        self.toc_button = self._make_icon(
            "toc", "显示/隐藏目录（Ctrl+B）", checkable=True, checked=True, size=30
        )
        self.toc_button.clicked.connect(self._toggle_toc)
        layout.addWidget(self.toc_button)

        # 章节名（醒目） + 书名（灰）；点击章节名打开书籍详情。
        self.title_label = _ClickableLabel("未打开书籍")
        self.title_label.setObjectName("ReaderTopTitle")
        self.title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.title_label.setCursor(Qt.PointingHandCursor)
        self.title_label.clicked.connect(self._show_book_detail)
        layout.addWidget(self.title_label, 1)

        self.book_label = QLabel("")
        self.book_label.setObjectName("ReaderTopBook")
        self.book_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.book_label, 1)

        layout.addStretch(1)

        # 右侧 5 图标：书签 / 搜索 / 字体排版 / 笔记 / 更多。
        self.bookmark_button = self._make_icon(
            "bookmark", "书签", checkable=True, size=30
        )
        self.bookmark_button.clicked.connect(self._toggle_bookmarks)
        layout.addWidget(self.bookmark_button)
        self.search_button = self._make_icon("search", "搜索正文（Ctrl+F）", size=30)
        self.search_button.clicked.connect(self.toggle_search)
        layout.addWidget(self.search_button)
        self.aa_button = self._make_icon("aa", "阅读设置：字体、版面、主题", size=30)
        self.aa_button.clicked.connect(self._show_prefs)
        layout.addWidget(self.aa_button)
        self.note_button = self._make_icon("note", "笔记", size=30)
        self.note_button.clicked.connect(lambda: self._select_sidebar_tab(1))
        layout.addWidget(self.note_button)
        self.more_button = self._make_icon("more", "更多", size=30)
        self.more_menu = QMenu(self.more_button)
        self.more_menu.addAction("全屏（F11）", self._toggle_fullscreen)
        self.more_menu.addAction("返回书库", self._on_back)
        self.more_menu.addAction("快捷键", self._show_shortcut_help)
        self.more_menu.addSeparator()
        self.favorite_button = self.more_menu.addAction("收藏")
        self.favorite_button.setCheckable(True)
        self.favorite_button.triggered.connect(self._on_favorite)
        self.more_button.clicked.connect(self._show_more_menu)
        layout.addWidget(self.more_button)

        self._topbar_opacity = QGraphicsOpacityEffect(bar)
        self._topbar_opacity.setOpacity(1.0)
        bar.setGraphicsEffect(self._topbar_opacity)
        return bar

    def _show_more_menu(self) -> None:
        anchor = self.more_button.mapToGlobal(
            QPoint(self.more_button.width() - self.more_menu.sizeHint().width(),
                   self.more_button.height() + 4)
        )
        self.more_menu.exec(anchor)

    def _make_icon(
        self,
        name: str,
        tooltip: str,
        *,
        checkable: bool = False,
        size: int = 36,
        checked: bool = False,
    ) -> IconButton:
        """创建图标按钮并登记，主题切换时统一改图标颜色。"""
        button = IconButton(name, tooltip, checkable=checkable, size=size)
        if checked:
            button.setChecked(True)
        self._icon_buttons.append(button)
        return button

    def _build_sidebar(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("ReaderSidebar")
        panel.setMinimumWidth(0)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(6)

        # T9：侧栏顶部封面卡（56×78 书封 + 书名/作者 + 进度 + 圆 i）。
        self.cover_card = ReaderCoverCard()
        self.cover_card.detail_requested.connect(self._show_book_detail)
        layout.addWidget(self.cover_card)

        tabs = QHBoxLayout()
        tabs.setSpacing(0)
        self.sidebar_tabs: list[QPushButton] = []
        for index, title in enumerate(("目录", "笔记", "书签")):
            button = QPushButton(title)
            button.setObjectName("ReaderTabButton")
            button.setCheckable(True)
            button.setFixedHeight(34)
            button.setCursor(Qt.PointingHandCursor)
            button.setChecked(index == 0)
            button.clicked.connect(
                lambda _checked=False, i=index: self._select_sidebar_tab(i)
            )
            tabs.addWidget(button, 1)
            self.sidebar_tabs.append(button)
        self.toc_tab_button = self.sidebar_tabs[0]
        self.note_tab_button = self.sidebar_tabs[1]
        self.bookmark_tab_button = self.sidebar_tabs[2]
        layout.addLayout(tabs)

        self.sidebar_stack = QStackedWidget()
        self.sidebar_stack.setObjectName("ReaderSidebarPage")
        self.sidebar_stack.addWidget(self._build_toc_page())
        self.sidebar_stack.addWidget(self._build_notes_page())
        self.sidebar_stack.addWidget(self._build_bookmarks_page())
        layout.addWidget(self.sidebar_stack, 1)
        self.sidebar = panel
        return panel

    def _build_toc_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("ReaderSidebarPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)

        self.toc_list = QListWidget()
        self.toc_list.setObjectName("ReaderTocList")
        self.toc_list.setFrameShape(QFrame.NoFrame)
        self.toc_list.setUniformItemSizes(True)
        self.toc_list.setMouseTracking(True)
        self.toc_list.setSpacing(0)
        self._toc_delegate = _TocItemDelegate(self._resolve_palette, self.toc_list)
        self.toc_list.setItemDelegate(self._toc_delegate)
        self.toc_list.itemClicked.connect(self._on_toc_clicked)
        layout.addWidget(self.toc_list, 1)

        self.toc_meta = QLabel("")
        self.toc_meta.setObjectName("ReaderTocMeta")
        self.toc_meta.setWordWrap(True)
        layout.addWidget(self.toc_meta)
        return page

    def _build_notes_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("ReaderSidebarPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)

        self.note_list = QListWidget()
        self.note_list.setObjectName("ReaderNoteList")
        self.note_list.setFrameShape(QFrame.NoFrame)
        self.note_list.itemDoubleClicked.connect(self._jump_bookmark)
        layout.addWidget(self.note_list, 1)

        row = QHBoxLayout()
        delete_button = QPushButton("删除笔记")
        delete_button.setObjectName("GhostButton")
        delete_button.clicked.connect(self._delete_note)
        row.addWidget(delete_button)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    def _build_bookmarks_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("ReaderSidebarPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)

        self.bookmark_list = QListWidget()
        self.bookmark_list.setObjectName("ReaderBookmarkList")
        self.bookmark_list.setFrameShape(QFrame.NoFrame)
        self.bookmark_list.itemDoubleClicked.connect(self._jump_bookmark)
        layout.addWidget(self.bookmark_list, 1)

        row = QHBoxLayout()
        add_button = QPushButton("添加书签")
        add_button.setObjectName("GhostButton")
        add_button.clicked.connect(self.add_bookmark)
        row.addWidget(add_button)
        delete_button = QPushButton("删除")
        delete_button.setObjectName("GhostButton")
        delete_button.clicked.connect(self._delete_bookmark)
        row.addWidget(delete_button)
        layout.addLayout(row)
        return page

    def _build_search(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("ReaderSearchBar")
        bar.setFixedHeight(42)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 6, 14, 6)
        layout.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("ReaderSearchEdit")
        self.search_edit.setPlaceholderText("搜索正文（Ctrl+F）")
        self.search_edit.returnPressed.connect(self._search_next)
        layout.addWidget(self.search_edit, 1)

        self.search_count = QLabel("")
        self.search_count.setObjectName("ReaderSearchCount")
        layout.addWidget(self.search_count)

        next_button = QPushButton("下一个")
        next_button.setObjectName("ReaderTool")
        next_button.clicked.connect(self._search_next)
        layout.addWidget(next_button)

        close_button = QPushButton("关闭")
        close_button.setObjectName("ReaderTool")
        close_button.clicked.connect(self.toggle_search)
        layout.addWidget(close_button)

        self._search_timer = self._make_timer(350, self._search_now)
        self.search_edit.textChanged.connect(lambda: self._search_timer.start())
        self.search_bar = bar
        return bar

    @staticmethod
    def _make_timer(interval: int, slot) -> QTimer:
        timer = QTimer()
        timer.setSingleShot(True)
        timer.setInterval(interval)
        timer.timeout.connect(slot)
        return timer

    def _build_web(self) -> QWidget:
        if self._web_enabled:
            self.web = ReaderWebView(self.db, self)
            bridge = self.web.bridge
            bridge.tocReady.connect(self._on_toc)
            bridge.locationChanged.connect(self._on_location)
            bridge.bookmarkAdded.connect(self._on_bookmarks_changed)
            bridge.highlightAdded.connect(self._on_bookmarks_changed)
            bridge.escapeRequested.connect(self._on_escape)
            bridge.bookmarkRequested.connect(self.add_bookmark)
            bridge.searchRequested.connect(self.toggle_search)
            bridge.searchFinished.connect(self._on_search_finished)
            bridge.chromeToggleRequested.connect(self._toggle_chrome)
            bridge.spreadChanged.connect(self._on_spread_changed)
            bridge.externalRequested.connect(self.open_external)
            bridge.renderingFinished.connect(self._on_rendered)
            bridge.failed.connect(self._on_web_failed)
            return self.web

        self.web = QLabel("测试模式：不加载 WebEngine 阅读画布")
        self.web.setAlignment(Qt.AlignCenter)
        self.web.setObjectName("ReaderPlaceholder")
        return self.web

    def _build_error(self) -> QWidget:
        page = QWidget()
        page.setObjectName("ReaderErrorPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(60, 60, 60, 60)
        layout.setSpacing(12)
        layout.addStretch(1)

        title = QLabel("无法在软件内打开这本书")
        title.setObjectName("ReaderErrorTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.error_reason = QLabel("")
        self.error_reason.setObjectName("ReaderErrorText")
        self.error_reason.setWordWrap(True)
        self.error_reason.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.error_reason)

        self.error_hint = QLabel("")
        self.error_hint.setObjectName("ReaderErrorHint")
        self.error_hint.setAlignment(Qt.AlignCenter)
        self.error_hint.setWordWrap(True)
        layout.addWidget(self.error_hint)

        row = QHBoxLayout()
        row.addStretch(1)
        self.retry_button = QPushButton("重试")
        self.retry_button.setObjectName("GhostButton")
        self.retry_button.clicked.connect(self._retry_open)
        row.addWidget(self.retry_button)
        self.external_button = QPushButton("用系统默认程序打开")
        self.external_button.setObjectName("PrimaryButton")
        self.external_button.clicked.connect(self._open_external)
        row.addWidget(self.external_button)
        back = QPushButton("返回书库")
        back.setObjectName("GhostButton")
        back.clicked.connect(self._on_back)
        row.addWidget(back)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        self.error_page = page
        return page

    def _build_loading(self, parent: QWidget | None = None) -> QWidget:
        page = QWidget(parent)
        page.setObjectName("ReaderLoadingPage")
        page.setAutoFillBackground(True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(60, 60, 60, 60)
        layout.setSpacing(14)
        layout.addStretch(1)
        title = QLabel("正在打开书籍")
        title.setObjectName("ReaderErrorTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        self.loading_stage_label = QLabel("探测格式")
        self.loading_stage_label.setObjectName("ReaderErrorText")
        self.loading_stage_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.loading_stage_label)
        self.loading_progress_bar = QProgressBar()
        self.loading_progress_bar.setRange(0, 100)
        self.loading_progress_bar.setValue(0)
        self.loading_progress_bar.setMaximumWidth(420)
        self.loading_progress_bar.setTextVisible(True)
        layout.addWidget(self.loading_progress_bar, 0, Qt.AlignCenter)
        self.loading_slow_label = QLabel("转换中，可稍候；大型 PDF 载入也需要一些时间。")
        self.loading_slow_label.setObjectName("ReaderErrorHint")
        self.loading_slow_label.setAlignment(Qt.AlignCenter)
        self.loading_slow_label.hide()
        layout.addWidget(self.loading_slow_label)
        back = QPushButton("返回书库")
        back.setObjectName("GhostButton")
        back.clicked.connect(self._on_back)
        layout.addWidget(back, 0, Qt.AlignCenter)
        layout.addStretch(1)
        return page

    def _build_bookmarks(self) -> QWidget:
        """兼容旧接口：书签已并入左侧栏的“书签”页。"""
        return self.sidebar_stack.widget(2)

    def _build_bottom(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("ReaderBottomBar")
        bar.setFixedHeight(40)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 0, 10, 0)
        layout.setSpacing(8)

        self.prev_button = self._make_icon("prev_page", "上一页（←）", size=32)
        self.prev_button.clicked.connect(self.prev_page)
        layout.addWidget(self.prev_button)
        self.next_button = self._make_icon("next_page", "下一页（→）", size=32)
        self.next_button.clicked.connect(self.next_page)
        layout.addWidget(self.next_button)

        self.progress = SegmentedProgress()
        self.progress.sliderReleased.connect(self._on_slider)
        self.progress.valueChanged.connect(self._on_progress_preview)
        self.progress_slider = self.progress  # 兼容旧调用点
        layout.addWidget(self.progress, 1)

        self.page_label = QLabel("第 — 页")
        self.page_label.setObjectName("ReaderPageLabel")
        self.page_label.setMinimumWidth(56)
        self.page_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.page_label)

        self.remaining_label = QLabel("本章剩余 —")
        self.remaining_label.setObjectName("ReaderRemaining")
        self.remaining_label.setToolTip("读几页后开始估算")
        layout.addWidget(self.remaining_label)

        self.clock_label = QLabel("--:--")
        self.clock_label.setObjectName("ReaderClock")
        self.clock_label.setMinimumWidth(40)
        self.clock_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.clock_label)

        self.font_stepper = Stepper(10, 40, 1, 19)
        self.font_stepper.setToolTip("字号（Ctrl+= / Ctrl+-）")
        self.font_stepper.changed.connect(
            lambda value: self._update_prefs(font_size=int(round(value)))
        )
        layout.addWidget(self.font_stepper)

        self.prefs_popup = self._build_prefs_popup()
        return bar

    def _build_prefs_popup(self) -> QFrame:
        popup = QFrame(self, Qt.Popup)
        popup.setObjectName("ReaderPrefsPopup")
        popup.setFixedWidth(320)
        outer = QVBoxLayout(popup)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(10)

        tabs = QHBoxLayout()
        tabs.setSpacing(6)
        self.prefs_tabs: list[QPushButton] = []
        for index, title in enumerate(("字体", "版面", "主题")):
            button = QPushButton(title)
            button.setObjectName("ReaderPrefsTab")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setChecked(index == 0)
            button.clicked.connect(
                lambda _checked=False, i=index: self._select_prefs_tab(i)
            )
            tabs.addWidget(button, 1)
            self.prefs_tabs.append(button)
        outer.addLayout(tabs)

        self.prefs_stack = QStackedWidget()
        self.prefs_stack.addWidget(self._build_font_tab())
        self.prefs_stack.addWidget(self._build_layout_tab())
        self.prefs_stack.addWidget(self._build_theme_tab())
        # 三个 tab 统一高度，切换时不跳变、不裁切。
        pages = [self.prefs_stack.widget(i) for i in range(self.prefs_stack.count())]
        self.prefs_stack.setFixedHeight(max(page.sizeHint().height() for page in pages))
        outer.addWidget(self.prefs_stack)
        # 弹层 160ms 淡入（规范 §2.3）；只动窗口透明度，不重新渲染内容。
        self._prefs_fade = QPropertyAnimation(popup, b"windowOpacity", popup)
        self._prefs_fade.setDuration(160)
        self._prefs_fade.setEasingCurve(QEasingCurve.OutCubic)
        return popup

    def _build_font_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(10)

        self.prefs_font_cjk = self._build_font_combo("中文")
        self.prefs_font_cjk.currentIndexChanged.connect(
            lambda _i: self._on_font_changed(self.prefs_font_cjk, "reader_font_cjk")
        )
        layout.addLayout(self._prefs_row("中文字体", self.prefs_font_cjk))

        self.prefs_font_latin = self._build_font_combo("English")
        self.prefs_font_latin.currentIndexChanged.connect(
            lambda _i: self._on_font_changed(self.prefs_font_latin, "reader_font_latin")
        )
        layout.addLayout(self._prefs_row("英文字体", self.prefs_font_latin))

        self.prefs_size = Stepper(10, 40, 1, 19)
        self.prefs_size.changed.connect(
            lambda value: self._update_prefs(font_size=int(round(value)))
        )
        layout.addLayout(self._prefs_row("字号", self.prefs_size))

        self.prefs_line = Stepper(1.0, 3.0, 0.05, 1.9, decimals=2)
        self.prefs_line.changed.connect(
            lambda value: self._update_prefs(line_height=round(float(value), 2))
        )
        layout.addLayout(self._prefs_row("行距", self.prefs_line))

        self.prefs_weight = QComboBox()
        for weight in _FONT_WEIGHTS:
            self.prefs_weight.addItem(str(weight), weight)
        self.prefs_weight.currentIndexChanged.connect(self._on_weight_changed)
        layout.addLayout(self._prefs_row("字重", self.prefs_weight))

        hint = QLabel("改动即时生效，按书保存阅读位置与外观。")
        hint.setObjectName("ReaderPrefsSection")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _build_font_combo(self, group: str) -> QComboBox:
        """按 fonts.json 的 group 渲染下拉；缺失文件的项置灰且不可选。"""
        combo = QComboBox()
        for font in _font_catalog():
            if font["group"] != group:
                continue
            label = font["label"] + ("（字体文件缺失）" if font["missing"] else "")
            combo.addItem(label, font["family"])
            if font["missing"]:
                item = combo.model().item(combo.count() - 1)
                if item is not None:
                    item.setEnabled(False)
        return combo

    def _on_font_changed(self, combo: QComboBox, key: str) -> None:
        # 切换只更新 prefs → setStyles 重排样式，不重建 foliate view，保留滚动位置。
        family = combo.currentData()
        if family:
            self._update_prefs(**{key: family})

    def _build_layout_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)

        self.prefs_para = Stepper(0, 3, 0.25, 0.75, decimals=2)
        self.prefs_para.changed.connect(
            lambda value: self._update_prefs(para_spacing=round(float(value), 2))
        )
        layout.addLayout(self._prefs_row("段距", self.prefs_para))

        toggles = QHBoxLayout()
        toggles.setSpacing(8)
        self.prefs_indent = QCheckBox("段首缩进")
        self.prefs_indent.toggled.connect(
            lambda checked: self._update_prefs(indent=bool(checked))
        )
        toggles.addWidget(self.prefs_indent)
        self.prefs_justify = QCheckBox("两端对齐")
        self.prefs_justify.toggled.connect(
            lambda checked: self._update_prefs(justify=bool(checked))
        )
        toggles.addWidget(self.prefs_justify)
        self.prefs_hyphens = QCheckBox("英文断字")
        self.prefs_hyphens.toggled.connect(
            lambda checked: self._update_prefs(hyphens=bool(checked))
        )
        toggles.addWidget(self.prefs_hyphens)
        toggles.addStretch(1)
        layout.addLayout(toggles)

        margin_title = QLabel("页边距")
        margin_title.setObjectName("ReaderPrefsSection")
        layout.addWidget(margin_title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self.prefs_margin_top = self._margin_cell(grid, 0, 0, "上", "margin_top")
        self.prefs_margin_bottom = self._margin_cell(grid, 0, 1, "下", "margin_bottom")
        self.prefs_margin_left = self._margin_cell(grid, 1, 0, "左", "margin_left")
        self.prefs_margin_right = self._margin_cell(grid, 1, 1, "右", "margin_right")
        layout.addLayout(grid)

        self.prefs_columns = QComboBox()
        self.prefs_columns.addItem("单页", "single")
        self.prefs_columns.addItem("双页（摊开）", "spread")
        self.prefs_columns.currentIndexChanged.connect(self._on_columns_changed)
        layout.addLayout(self._prefs_row("展示方式", self.prefs_columns))
        self.prefs_max_width = Stepper(520, 1200, 20, 920)
        self.prefs_max_width.changed.connect(
            lambda value: self._update_prefs(max_column_width=int(round(value)))
        )
        layout.addLayout(self._prefs_row("最大列宽", self.prefs_max_width))

        anim_title = QLabel("动效")
        anim_title.setObjectName("ReaderPrefsSection")
        layout.addWidget(anim_title)
        turn_row = QHBoxLayout()
        turn_row.setSpacing(4)
        self.turn_buttons: dict[str, QPushButton] = {}
        for value, label in _TURN_STYLES:
            button = self._make_segment(label, value, self._on_turn_selected)
            button.setToolTip(_TURN_TIPS.get(value, label))
            turn_row.addWidget(button, 1)
            self.turn_buttons[value] = button
        layout.addLayout(turn_row)

        self.prefs_click = QCheckBox("点击正文左右两侧翻页")
        self.prefs_click.toggled.connect(
            lambda checked: self._update_prefs(click_turn=bool(checked))
        )
        layout.addWidget(self.prefs_click)
        layout.addStretch(1)
        return page

    def _build_theme_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(10)

        swatch_title = QLabel("主题色卡")
        swatch_title.setObjectName("ReaderPrefsSection")
        layout.addWidget(swatch_title)

        grid = QGridLayout()
        grid.setSpacing(8)
        self.theme_swatches: dict[str, QPushButton] = {}
        for index, palette in enumerate(PALETTES.values()):
            button = QPushButton()
            button.setFixedSize(30, 30)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(palette.label)
            button.setStyleSheet(
                f"QPushButton {{ background: {palette.page}; border: 2px solid {palette.border}; border-radius: 15px; }}"
                f"QPushButton:hover {{ border-color: {palette.accent}; }}"
                f"QPushButton:checked {{ border: 3px solid {palette.accent}; }}"
            )
            button.clicked.connect(
                lambda _checked=False, key=palette.key: self._select_theme(key)
            )
            grid.addWidget(button, index // 4, index % 4)
            self.theme_swatches[palette.key] = button
        grid.setColumnStretch(4, 1)
        layout.addLayout(grid)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        self.mode_buttons: dict[str, QPushButton] = {}
        for value, label in _MODE_SEGMENTS:
            button = self._make_segment(label, value, self._on_mode_selected)
            mode_row.addWidget(button, 1)
            self.mode_buttons[value] = button
        layout.addLayout(self._prefs_row("模式", mode_row))

        accent_row = QHBoxLayout()
        accent_row.setSpacing(6)
        self.prefs_accent_swatch = QLabel()
        self.prefs_accent_swatch.setObjectName("ReaderAccentSwatch")
        self.prefs_accent_swatch.setFixedSize(20, 20)
        accent_row.addWidget(self.prefs_accent_swatch)
        self.prefs_accent_value = QLabel("")
        self.prefs_accent_value.setObjectName("ReaderPrefsValue")
        accent_row.addWidget(self.prefs_accent_value)
        pick = QPushButton("选择…")
        pick.setObjectName("GhostButton")
        pick.clicked.connect(self._pick_accent)
        accent_row.addWidget(pick)
        follow = QPushButton("跟随主题")
        follow.setObjectName("GhostButton")
        follow.clicked.connect(lambda: self._update_prefs(accent=None))
        accent_row.addWidget(follow)
        accent_row.addStretch(1)
        layout.addLayout(self._prefs_row("强调色", accent_row))

        texture_title = QLabel("背景纹理")
        texture_title.setObjectName("ReaderPrefsSection")
        layout.addWidget(texture_title)
        texture_row = QHBoxLayout()
        texture_row.setSpacing(4)
        self.texture_buttons: dict[str, QPushButton] = {}
        for value, label in _TEXTURES:
            button = self._make_segment(label, value, self._on_texture_selected)
            texture_row.addWidget(button, 1)
            self.texture_buttons[value] = button
        layout.addLayout(texture_row)

        reset = QPushButton("恢复默认")
        reset.setObjectName("GhostButton")
        reset.clicked.connect(self._reset_prefs)
        layout.addWidget(reset)
        layout.addStretch(1)
        return page

    def _margin_cell(
        self, grid: QGridLayout, row: int, column: int, label: str, key: str
    ) -> Stepper:
        cell = QVBoxLayout()
        cell.setSpacing(2)
        title = QLabel(label)
        title.setObjectName("ReaderPrefsSection")
        stepper = Stepper(0, 240, 4, 48)
        stepper.changed.connect(
            lambda value, name=key: self._update_prefs(**{name: int(round(value))})
        )
        cell.addWidget(title)
        cell.addWidget(stepper)
        grid.addLayout(cell, row, column)
        return stepper

    def _make_segment(self, text: str, value: str, handler) -> QPushButton:
        """设置弹层里的等宽分段按钮；选中态由 _sync_prefs_widgets 统一维护。"""
        button = QPushButton(text)
        button.setObjectName("ReaderPrefsSegment")
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedHeight(28)
        button.clicked.connect(lambda _checked=False, item=value: handler(item))
        return button

    def _select_prefs_tab(self, index: int) -> None:
        self.prefs_stack.setCurrentIndex(index)
        for position, button in enumerate(self.prefs_tabs):
            button.setChecked(position == index)

    def _on_mode_selected(self, value: str) -> None:
        if not self._syncing:
            self._update_prefs(mode=str(value))

    def _select_theme(self, key: str) -> None:
        """点色卡立即看到所选颜色：夜读切深色模式，其余色卡切浅色模式。"""
        if self._syncing:
            return
        self._update_prefs(theme=key, mode="dark" if key == "dark" else "light")

    def _on_turn_selected(self, value: str) -> None:
        if not self._syncing:
            self._update_prefs(turn_style=str(value))

    def _on_texture_selected(self, value: str) -> None:
        if not self._syncing:
            self._update_prefs(texture=str(value))

    def _on_weight_changed(self, _index: int) -> None:
        if not self._syncing:
            self._update_prefs(font_weight=int(self.prefs_weight.currentData() or 400))

    def _on_columns_changed(self, _index: int) -> None:
        if not self._syncing:
            self._update_prefs(page_mode=str(self.prefs_columns.currentData() or "single"))

    def _pick_accent(self) -> None:
        current = QColor(self._resolve_palette().accent)
        chosen = QColorDialog.getColor(current, self, "自定义强调色")
        if chosen.isValid():
            self._update_prefs(accent=chosen.name())

    @staticmethod
    def _prefs_row(label: str, widget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        title = QLabel(label)
        title.setObjectName("ReaderPrefsLabel")
        title.setFixedWidth(60)
        row.addWidget(title)
        if isinstance(widget, QWidget):
            row.addWidget(widget, 1)
        else:
            row.addLayout(widget, 1)
        return row

    # ---- 打开 / 关闭 -------------------------------------------------
    def open_book(self, book_id: int) -> bool:
        """开始打开一本书；生产模式后台准备，测试模式同步返回结果。"""
        self.flush()
        self._end_session()
        self._open_serial += 1
        serial = self._open_serial
        self._slow_timer.stop()
        self._render_watchdog.stop()
        self._book_id = None
        self._book = {}
        self._book_path = ""
        row = self.db.query_one(
            "SELECT books.*, authors.name_zh AS author_name, authors.country AS country, "
            "series.name AS series_name "
            "FROM books LEFT JOIN authors ON authors.id = books.author_id "
            "LEFT JOIN series ON series.id = books.series_id "
            "WHERE books.id = ?",
            (book_id,),
        )
        if row is None:
            self._show_error("书籍记录不存在")
            return False

        self._book = dict(row)
        self._book_id = int(book_id)
        self._book_path = str(row["file_path"] or "")
        self._location = {}
        self._toc = []
        self._chapter_pages.clear()
        self.toc_list.clear()
        self.note_list.clear()
        self.bookmark_list.clear()
        self._select_sidebar_tab(0)
        self.search_bar.hide()
        self.detail_panel.hide()
        self._update_header()
        self.loading_slow_label.hide()
        self._set_loading("探测格式", 10)
        self._slow_timer.start()
        if Path(self._book_path).suffix.lower() in (".mobi", ".azw3"):
            self._set_loading("转换格式", 35)

        if not self._web_enabled:
            prepared, outline = _prepare_for_reader(self._book_path)
            return self._finish_prepared(serial, prepared, outline)

        worker = _PrepareWorker(serial, self._book_path)
        worker.signals.finished.connect(self._finish_prepared)
        self._prepare_pool.start(worker)
        return True

    def _finish_prepared(
        self, serial: int, prepared: PreparedBook, outline: dict[str, Any] | None
    ) -> bool:
        if serial != self._open_serial:
            return False
        self._prepared = prepared
        if prepared.drm:
            self._mark_drm()
        if not prepared.ok:
            self._show_error(prepared.error or "无法打开这本书")
            return False
        if outline and outline.get("error"):
            self._show_error(str(outline["error"]))
            return False

        self._set_loading("载入 HTML", 65)
        payload: dict[str, Any] = {
            "bookId": self._book_id,
            "kind": prepared.kind,
            "url": Path(prepared.path).as_uri() if prepared.path else "",
            "title": self._display_title(),
            "author": self._display_author(),
            "format": str(self._book.get("format") or ""),
            "prefs": self._reader_prefs(),
            "locator": self._saved_locator(),
            "toc": outline,
            "highlights": self._saved_highlights(),
        }
        if prepared.kind == "pdf" and outline:
            self._set_toc(outline.get("items") or [])

        if self._web_enabled:
            self.web.open_payload(payload)
            self._render_watchdog.start()
        else:
            self._on_rendered(int(self._book_id or 0))
        return True

    def _set_loading(self, stage: str, percent: int) -> None:
        self._loading_stage = stage
        self.loading_stage_label.setText(stage)
        self.loading_progress_bar.setValue(percent)
        if percent < 100:
            self._show_loading_overlay()
        self.loading_progress.emit(stage, percent)

    def _show_loading_overlay(self) -> None:
        """载入时保持 WebEngine 视图可见，只用浮层遮挡，避免页面被冻结。"""
        self.stack.setCurrentWidget(self.web)
        self.loading_overlay.setGeometry(self._center.rect())
        self.loading_overlay.show()
        self.loading_overlay.raise_()

    def _hide_loading_overlay(self) -> None:
        self.loading_overlay.hide()
        self.loading_slow_label.hide()

    def _on_rendered(self, book_id: int) -> None:
        if book_id != self._book_id:
            return
        self._slow_timer.stop()
        self._render_watchdog.stop()
        self._set_loading("渲染完成", 100)
        self._hide_loading_overlay()
        self.stack.setCurrentWidget(self.web)
        self._ensure_session()

    def _on_render_timeout(self) -> None:
        if self.loading_overlay.isHidden():
            return
        self._show_error(
            "载入超时：这本文件可能在解析或排版阶段卡住了，"
            "可以点“重试”，或先用系统默认程序打开确认文件是否正常。"
        )

    def _retry_open(self) -> None:
        if self._book_id:
            self.open_book(self._book_id)

    def _show_slow_loading(self) -> None:
        if not self.loading_overlay.isHidden():
            self.loading_slow_label.show()

    def close_book(self) -> None:
        self._open_serial += 1
        self._slow_timer.stop()
        self._render_watchdog.stop()
        self._hide_loading_overlay()
        self.flush()
        self._end_session()
        self.search_bar.hide()
        self.detail_panel.hide()

    def flush(self) -> None:
        if self._web_enabled:
            try:
                self.web.bridge.flush()
            except Exception as exc:  # 关闭阶段不应抛异常
                log.warning("写入阅读进度失败：%s", exc)

    # ---- 顶部信息 ---------------------------------------------------
    def _display_title(self) -> str:
        return str(self._book.get("title") or Path(self._book_path).stem or "未命名")

    def _display_author(self) -> str:
        return str(self._book.get("author_name") or self._book.get("author_raw") or "作者未知")

    def _make_cover_pixmap(self, w: int, h: int) -> QPixmap:
        """生成 w×h 竖封面：有真实封面则居中裁切，否则书名首字占位。"""
        pix = LibraryService.cover_for(self._book) if self._book else None
        if pix is None or pix.isNull():
            theme = self._resolve_palette()
            pix = QPixmap(w, h)
            pix.fill(QColor(theme.panel))
            painter = QPainter(pix)
            painter.setPen(QColor(theme.muted))
            font = painter.font()
            font.setPointSize(max(8, int(h * 0.28)))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                pix.rect(), Qt.AlignCenter, (self._display_title() or "?").strip()[:1]
            )
            painter.end()
        else:
            scaled = pix.scaled(
                w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            pix = scaled.copy(
                max(0, (scaled.width() - w) // 2),
                max(0, (scaled.height() - h) // 2),
                w,
                h,
            )
        return pix

    def _render_cover_thumb(self) -> None:
        """侧栏封面卡 56×78（顶栏封面已移至侧栏卡）。"""
        if hasattr(self, "cover_card"):
            self.cover_card.set_book(self._book or {})
            self.cover_card.set_cover_pixmap(self._make_cover_pixmap(56, 78))

    def _on_favorite(self) -> None:
        """顶栏收藏按钮：切换 books.favorite。"""
        if not self._book_id:
            return
        try:
            row = self.db.query_one(
                "SELECT favorite FROM books WHERE id = ?", (self._book_id,)
            )
        except Exception:
            row = None
        current = int(row["favorite"] or 0) if row else 0
        new_value = 0 if current else 1
        try:
            self.db.execute(
                "UPDATE books SET favorite = ?, updated_at = datetime('now') WHERE id = ?",
                (new_value, self._book_id),
            )
            self._book["favorite"] = new_value
            self.favorite_button.blockSignals(True)
            self.favorite_button.setChecked(bool(new_value))
            self.favorite_button.blockSignals(False)
            self.book_changed.emit(self._book_id)
            if not self.detail_panel.isHidden():
                self._populate_book_detail()
        except Exception as exc:
            log.warning("收藏写入失败：%s", exc)
            # 回退按钮状态，避免 UI 与 DB 不一致。
            self.favorite_button.blockSignals(True)
            self.favorite_button.setChecked(bool(current))
            self.favorite_button.blockSignals(False)
        self._show_chrome()

    def _show_book_detail(self) -> None:
        """圆 i / 封面 / 书名：打开或关闭 R3a 只读详情浮层。"""
        if not self._book_id:
            return
        if not self.detail_panel.isHidden():
            self._hide_book_detail()
            return
        self.prefs_popup.hide()
        self._populate_book_detail()
        self._position_book_detail()
        self.detail_panel.show()
        self.detail_panel.raise_()
        self._show_chrome()

    def _hide_book_detail(self) -> None:
        self.detail_panel.leave_edit()
        self.detail_panel.hide()
        self._schedule_chrome_hide()

    def _position_book_detail(self) -> None:
        self.detail_panel.adjustSize()
        anchor = self.more_button.mapTo(self, QPoint(0, self.more_button.height() + 6))
        x = anchor.x() + self.more_button.width() - self.detail_panel.width()
        x = max(8, min(x, self.width() - self.detail_panel.width() - 8))
        available = max(280, self.height() - anchor.y() - 48)
        self.detail_panel.setMaximumHeight(min(600, available))
        self.detail_panel.move(x, anchor.y())

    def _populate_book_detail(self) -> None:
        progress_row = self.repo.get_progress(self._book_id) if self._book_id else None
        progress = dict(progress_row) if progress_row is not None else {}
        archive_path = ""
        if self._book_id:
            try:
                archive_path = OrganizeService(self.db, self.settings).plan_for_book(
                    self._book_id
                ).target_path
            except BookShelfError as exc:
                log.info("暂不能计算归档路径：%s", exc)
        self.detail_panel.populate(
            self._book,
            tags=LibraryService(self.db).tags_for(self._book_id) if self._book_id else [],
            progress=progress,
            archive_path=archive_path,
            cover=LibraryService.cover_for(self._book),
            current_page=int(self._location.get("page") or 0),
            total_pages=int(self._location.get("total") or 0),
        )
        self.detail_panel.set_restore_available(self._can_restore_embedded())

    def _can_restore_embedded(self) -> bool:
        if not self._book_id:
            return False
        row = self.db.query_one(
            "SELECT file_path, format FROM books WHERE id = ?", (self._book_id,)
        )
        if row is None:
            return False
        return (
            str(row["format"] or "").lower() == "epub"
            and Path(str(row["file_path"] or "")).is_file()
        )

    def _reveal_book_folder(self) -> None:
        folder = Path(self._book_path).parent
        if not self._book_path or not folder.is_dir():
            self.detail_panel.show_status("文件所在文件夹不存在或已被移动", error=True)
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            self.detail_panel.show_status("无法打开文件所在文件夹", error=True)

    def _recalculate_book_path(self) -> None:
        """先预览再复用“只重命名”服务；不跨目录、不覆盖同名文件。"""
        if not self._book_id:
            return
        service = OrganizeService(self.db, self.settings)
        try:
            plan = service.plan_for_book(self._book_id, for_rename=True)
        except BookShelfError as exc:
            self.detail_panel.show_status(f"无法计算目标文件名：{exc}", error=True)
            return
        old = Path(self._book_path)
        if not plan.target_name or plan.status == "failed":
            self.detail_panel.show_status(
                f"无法计算目标文件名：{plan.message or '模板结果为空'}", error=True
            )
            return
        target = old.parent / plan.target_name
        if old.name.casefold() == target.name.casefold():
            self.detail_panel.show_status("文件名已符合当前模板，无需修改")
            return
        answer = QMessageBox.question(
            self,
            "按命名模板重算",
            "将在原目录内重命名，不跨目录、不覆盖已有文件。\n\n"
            f"当前：{old.name}\n目标：{target.name}\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            result = service.rename_only([self._book_id])
        except BookShelfError as exc:
            self.detail_panel.show_status(f"重命名失败：{exc}", error=True)
            return
        if result.failed or result.errors:
            self.detail_panel.show_status(
                "重命名失败：" + "；".join(result.errors or ["未知错误"]), error=True
            )
            return
        if not self._reload_current_book():
            self.detail_panel.show_status("文件已处理，但书库记录刷新失败", error=True)
            return
        self.book_changed.emit(self._book_id)
        self.detail_panel.show_status(
            f"已重命名为 {Path(self._book_path).name}"
            if result.renamed
            else "文件名已符合当前模板，无需修改"
        )

    def _reload_current_book(self) -> bool:
        if not self._book_id:
            return False
        row = self.db.query_one(
            "SELECT books.*, authors.name_zh AS author_name, authors.country AS country, "
            "series.name AS series_name "
            "FROM books LEFT JOIN authors ON authors.id = books.author_id "
            "LEFT JOIN series ON series.id = books.series_id WHERE books.id = ?",
            (self._book_id,),
        )
        if row is None:
            return False
        self._book = dict(row)
        self._book_path = str(row["file_path"] or "")
        self._update_header()
        self.window().setWindowTitle(f"{self._display_title()} · 阅读")
        self._populate_book_detail()
        return True

    def _detail_add_note(self) -> None:
        self._hide_book_detail()
        self._select_sidebar_tab(1)

    def _detail_add_bookmark(self) -> None:
        self._hide_book_detail()
        self.add_bookmark()

    # ---- R3b：编辑元数据 ---------------------------------------------
    _EDIT_RESTORE_FIELDS = (
        "title", "subtitle", "author_id", "author_raw", "isbn", "publisher",
        "publish_date", "language", "series_id", "volume", "volume_raw",
        "description", "page_count", "status", "confidence", "meta_source",
        "file_path", "read_state", "favorite",
    )

    def _save_book_detail_edit(self) -> None:
        """校验 → 写库 → 归档移动 → 刷新；任一步失败按快照回滚。"""
        if not self._book_id:
            return
        panel = self.detail_panel
        fields = panel.edit_values()
        title = fields["title"]
        if not title:
            panel.show_status("书名不能为空", error=True)
            return
        if fields["isbn"] and not isbn_tools.is_valid(fields["isbn"]):
            panel.show_status("ISBN 校验未通过，请填写 10 位或 13 位有效 ISBN", error=True)
            return
        page_count = None
        if fields["pages"]:
            if not fields["pages"].isdigit() or int(fields["pages"]) <= 0:
                panel.show_status("页数必须是正整数", error=True)
                return
            page_count = int(fields["pages"])

        raw_tags = (
            fields["tags"]
            .replace("；", ",")
            .replace(";", ",")
            .replace("，", ",")
            .replace("、", ",")
        )
        tags = [tag.strip() for tag in raw_tags.split(",") if tag.strip()]

        old_row = self.db.query_one(
            "SELECT * FROM books WHERE id = ?", (self._book_id,)
        )
        if old_row is None:
            panel.show_status("书籍记录不存在，无法保存", error=True)
            return
        snapshot = {key: old_row[key] for key in self._EDIT_RESTORE_FIELDS}
        old_tags = LibraryService(self.db).tags_for(self._book_id)

        try:
            MetadataService(self.db).save_manual(
                self._book_id,
                {
                    "title": title,
                    "author_raw": fields["author"],
                    "publisher": fields["publisher"],
                    "publish_date": fields["publish_date"],
                    "language": fields["language"],
                    "isbn": fields["isbn"],
                    "series": fields["series"],
                },
            )
            books = BookRepository(self.db)
            if page_count is not None:
                books.update(self._book_id, page_count=page_count)
            if not fields["author"]:
                books.update(self._book_id, author_id=None, author_raw="")
            if not fields["series"] and snapshot.get("series_id"):
                books.update(self._book_id, series_id=None)
            LibraryService(self.db).set_tags([self._book_id], tags)
            moved, note = self._move_edited_book_to_archive()
            note += self._write_embedded_after_save(fields, page_count)
        except Exception as exc:
            log.warning("保存元数据失败，开始回滚：%s", exc)
            self._restore_book_snapshot(snapshot, old_tags)
            panel.show_status(f"保存失败，已回滚：{exc}", error=True)
            return

        if not self._reload_current_book():
            panel.show_status("已写入书库，但阅读器刷新失败，请关闭后重开", error=True)
            return
        panel.leave_edit()
        panel.show_status(note)
        self.book_changed.emit(self._book_id)
        if moved and self._web_enabled:
            # 文件已换位置：按已保存进度重新载入，避免继续读取旧路径。
            self.open_book(self._book_id)

    def _move_edited_book_to_archive(self) -> tuple[bool, str]:
        """按当前命名模板把单本书移动到归档位置；返回是否移动及提示语。"""
        root = str(self.settings.data.get("library_root") or "")
        if not root or not Path(root).is_dir():
            return False, "已保存并同步到书库（未设置书库根目录，文件未移动）"
        service = OrganizeService(self.db, self.settings)
        plan = service.plan_for_book(self._book_id)
        if not plan.target_path:
            if plan.status == "failed":
                raise BookShelfError(plan.message or "无法计算归档路径")
            return False, "已保存并同步到书库（未计算到归档路径，文件未移动）"
        source = Path(plan.source_path)
        target = Path(plan.target_path)
        if source.resolve() == target.resolve():
            return False, "已保存并同步到书库"
        if plan.status == "conflict" and "目标已存在" in plan.message:
            raise BookShelfError("归档目标已存在同名文件，未移动文件")
        if plan.status == "skip":
            return False, "已保存并同步到书库（按当前策略跳过移动）"
        plan.action = "move"
        result = service.execute([plan], action="move")
        if result.failed or result.errors:
            raise BookShelfError("；".join(result.errors or ["移动文件失败"]))
        if result.moved or result.overwritten:
            return True, "已保存并同步到书库，文件已归档"
        return False, "已保存并同步到书库（文件未移动）"

    def _write_embedded_after_save(
        self, fields: dict[str, str], page_count: int | None
    ) -> str:
        """R3c：EPUB 写回 OPF；失败只提示并保留备份，不回滚已保存的元数据。"""
        row = self.db.query_one(
            "SELECT file_path, format FROM books WHERE id = ?", (self._book_id,)
        )
        if row is None:
            return ""
        fmt = str(row["format"] or "").lower()
        path = Path(str(row["file_path"] or ""))
        if fmt != "epub":
            return "（该格式不支持回写内嵌元数据）"
        if not path.is_file():
            return "；OPF 未写入：数据文件不存在"
        try:
            write_embedded_metadata(
                path,
                {
                    "title": fields["title"],
                    "author": fields["author"],
                    "publisher": fields["publisher"],
                    "publish_date": fields["publish_date"],
                    "language": fields["language"],
                    "isbn": fields["isbn"],
                },
                page_count=page_count,
            )
        except Exception as exc:
            log.warning("OPF 回写失败：%s", exc)
            kept = "，已保留备份" if backup_path(path).exists() else ""
            return f"；OPF 未写入{kept}（{exc}）"
        return "；已写入 EPUB 内嵌元数据"

    def _restore_embedded_metadata(self) -> None:
        """R3c：用文件内嵌元数据覆盖书库记录（仅 EPUB 可用）。"""
        if not self._book_id:
            return
        try:
            MetadataService(self.db).reset_to_embedded(self._book_id)
        except Exception as exc:
            log.warning("恢复内嵌元数据失败：%s", exc)
            self.detail_panel.show_status(f"恢复失败：{exc}", error=True)
            return
        if not self._reload_current_book():
            self.detail_panel.show_status("已恢复，但阅读器刷新失败", error=True)
            return
        self.detail_panel.show_status("已恢复为文件内嵌元数据")
        self.book_changed.emit(self._book_id)

    def _restore_book_snapshot(
        self, snapshot: dict[str, Any], old_tags: list[str]
    ) -> None:
        """回滚书籍字段与标签；回滚本身失败只记日志，不掩盖原始错误。"""
        try:
            BookRepository(self.db).update(self._book_id, **snapshot)
        except Exception as exc:
            log.error("回滚书籍字段失败：%s", exc)
        try:
            LibraryService(self.db).set_tags([self._book_id], old_tags)
        except Exception as exc:
            log.error("回滚标签失败：%s", exc)
        self._reload_current_book()

    def _update_header(self) -> None:
        title = self._display_title()
        # 章节标题优先取 location.title，其次 label；封面/书名页不当作章节名。
        chapter = str(
            self._location.get("title") or self._location.get("label") or ""
        ).strip()
        if chapter.lower() in {
            "封面", "封面页", "书名页", "cover", "title page", "titlepage",
        }:
            chapter = ""
        self._header_chapter = chapter
        self._header_book = title
        self._title_full = f"{title} · {chapter}" if chapter else title
        self._elide_title()

        self.favorite_button.blockSignals(True)
        self.favorite_button.setChecked(bool(self._book.get("favorite")))
        self.favorite_button.blockSignals(False)

        self._render_cover_thumb()
        if hasattr(self, "cover_card"):
            self.cover_card.set_progress(float(self._location.get("percent") or 0))

        author = self._display_author() if self._book else ""
        fmt = str(self._book.get("format") or "").upper()
        parts = [part for part in (author, fmt) if part]
        progress = self.repo.get_progress(self._book_id) if self._book_id else None
        seconds = int(progress["total_seconds"] or 0) if progress else 0
        if seconds >= 60:
            parts.append(f"已读 {seconds // 60} 分钟")
        self.topbar.setToolTip(" · ".join(item for item in parts if item))

    def _elide_title(self) -> None:
        """顶栏：章节名醒目 + 书名（灰）；宽度不足时各自省略。"""
        book = getattr(self, "_header_book", "")
        if not book:
            book = (
                self._display_title() if getattr(self, "_book", None) else "未打开书籍"
            )
        chapter = getattr(self, "_header_chapter", "") or book
        self.title_label.setText(
            self.title_label.fontMetrics().elidedText(
                chapter, Qt.ElideRight, max(40, self.title_label.width() - 4)
            )
        )
        show_book = bool(getattr(self, "_book", None)) and chapter != book
        self.book_label.setVisible(show_book)
        if show_book:
            self.book_label.setText(
                self.book_label.fontMetrics().elidedText(
                    book, Qt.ElideRight, max(40, self.book_label.width() - 4)
                )
            )
        self.title_label.setToolTip(self._title_full or book)

    def _mark_drm(self) -> None:
        if not self._book_id:
            return
        try:
            self.db.execute(
                "UPDATE books SET drm_protected = 1, status = 'drm', updated_at = datetime('now') "
                "WHERE id = ?",
                (self._book_id,),
            )
        except Exception as exc:
            log.warning("标记 DRM 失败：%s", exc)

    # ---- 目录 -------------------------------------------------------
    def _on_toc(self, book_id: int, payload: str) -> None:
        if book_id != self._book_id:
            return
        try:
            items = json.loads(payload)
        except ValueError:
            return
        self._set_toc(items if isinstance(items, list) else [])

    def _set_toc(self, items: list[dict[str, Any]]) -> None:
        self._toc = items
        self.toc_list.clear()
        for index, item in enumerate(items, start=1):
            label = str(item.get("label") or "").strip() or f"第 {index} 节"
            level = max(0, int(item.get("level") or 0))
            href = str(item.get("href") or "")
            page = item.get("page") or ""
            node = QListWidgetItem(label)
            node.setData(_ROLE_TARGET, href or page)
            node.setData(_ROLE_LABEL, label)
            node.setData(_ROLE_HREF, href)
            node.setData(_ROLE_PAGE, self._chapter_page_text(href, label, page))
            node.setData(_ROLE_INDEX, index)
            node.setData(_ROLE_LEVEL, level)
            node.setToolTip(label)
            self.toc_list.addItem(node)
        self._highlight_toc(
            str(self._location.get("label") or ""),
            str(self._location.get("href") or ""),
        )

    def _chapter_page_text(self, href: str, label: str, page: Any = "") -> str:
        """页码只取已访问缓存；EPUB 未访问章节显示 ~，不为了页码去逐章排版。"""
        if href and href in self._chapter_pages:
            return str(self._chapter_pages[href])
        if label and label in self._chapter_pages:
            return str(self._chapter_pages[label])
        if page not in (None, "", 0, "0"):
            return str(page)
        return "~"

    def _refresh_toc_page(self, href: str, page: int) -> None:
        changed = False
        for index in range(self.toc_list.count()):
            item = self.toc_list.item(index)
            if str(item.data(_ROLE_HREF) or "") != href:
                continue
            if item.data(_ROLE_PAGE) != str(page):
                item.setData(_ROLE_PAGE, str(page))
                changed = True
        if changed:
            self.toc_list.viewport().update()

    def _highlight_toc(self, label: str, href: str = "") -> None:
        if not label and not href:
            return
        for index in range(self.toc_list.count()):
            item = self.toc_list.item(index)
            matched = bool(href) and item.data(_ROLE_HREF) == href
            if not matched and label:
                matched = item.data(_ROLE_LABEL) == label
            if not matched:
                continue
            if self.toc_list.currentRow() != index:
                self.toc_list.blockSignals(True)
                self.toc_list.setCurrentRow(index)
                self.toc_list.blockSignals(False)
            self.toc_list.scrollToItem(item, QAbstractItemView.EnsureVisible)
            return

    def _on_toc_clicked(self, item: QListWidgetItem) -> None:
        if not self._web_enabled:
            return
        target = item.data(_ROLE_TARGET)
        if self._prepared is not None and getattr(self._prepared, "kind", "") == "pdf":
            try:
                self.web.go_to({"page": int(target)})
            except (TypeError, ValueError):
                return
        elif target:
            self.web.go_to(str(target))

    def _toggle_toc(self) -> None:
        """顶栏按钮只控制整块侧栏的显示与隐藏。"""
        if self._sidebar_visible:
            self._show_sidebar(False)
        else:
            self._select_sidebar_tab(0)

    def _show_sidebar(self, visible: bool) -> None:
        """显示/隐藏侧栏；宽度用 160ms 动效过渡，拖拽后保留用户宽度。"""
        if visible:
            if self.sidebar.isVisible() and self.sidebar.maximumWidth() > 10:
                self._sidebar_visible = True
                self.toc_button.setChecked(True)
                return
            self._sidebar_visible = True
            self.sidebar.setMaximumWidth(0)
            self.sidebar.show()
            self._start_sidebar_animation(self._sidebar_width)
        else:
            if self.sidebar.isHidden():
                self._sidebar_visible = False
                self.toc_button.setChecked(False)
                return
            if self.sidebar.width() > 0:
                self._sidebar_width = max(180, min(480, self.sidebar.width()))
            self._sidebar_visible = False
            self._start_sidebar_animation(0)
        self.toc_button.setChecked(visible)

    def _start_sidebar_animation(self, target: int) -> None:
        self._sidebar_anim.stop()
        self._sidebar_anim.setStartValue(self.sidebar.maximumWidth())
        self._sidebar_anim.setEndValue(int(target))
        self._sidebar_anim.start()

    def _on_sidebar_anim_value(self, value: Any) -> None:
        width = int(value)
        total = max(640, self.splitter.width() or self.width() or 1180)
        self.splitter.setSizes([width, max(320, total - width)])

    def _on_sidebar_anim_finished(self) -> None:
        if not self._sidebar_visible:
            self.sidebar.hide()
        self.sidebar.setMaximumWidth(self._sidebar_width)

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        if self._sidebar_visible and self.sidebar.width() > 0:
            self._sidebar_width = self.sidebar.width()
            self.sidebar.setMaximumWidth(self._sidebar_width)

    def _select_sidebar_tab(self, index: int) -> None:
        index = max(0, min(2, int(index)))
        self.sidebar_stack.setCurrentIndex(index)
        for position, button in enumerate(self.sidebar_tabs):
            button.setChecked(position == index)
        self.bookmark_button.setChecked(index == 2)
        if index == 1:
            self._refresh_notes()
        elif index == 2:
            self._refresh_bookmarks()
        self._show_sidebar(True)

    # ---- 进度同步 ---------------------------------------------------
    def _on_location(self, book_id: int, payload: str) -> None:
        if book_id != self._book_id:
            return
        try:
            info = json.loads(payload)
        except ValueError:
            return
        previous_page = int(self._location.get("page") or 0)
        self._location = info if isinstance(info, dict) else {}
        percent = float(self._location.get("percent") or 0)
        page = int(self._location.get("page") or 0)
        total = int(self._location.get("total") or 0)
        if (
            self._session_id is not None
            and page > 0
            and previous_page > 0
            and page != previous_page
        ):
            self._session_pages += 1
        section_seconds = float(self._location.get("sectionSeconds") or 0)
        label = str(self._location.get("label") or "")
        href = str(self._location.get("href") or "")

        # 记录已访问章节页码，目录行据此显示真实页码。
        if page > 0:
            if href:
                self._chapter_pages[href] = page
                self._refresh_toc_page(href, page)
            if label:
                self._chapter_pages[label] = page

        self.progress.blockSignals(True)
        self.progress.setValue(int(percent * 1000))
        self.progress.blockSignals(False)
        self._update_page_label()
        self._update_remaining(section_seconds)
        self._update_header()
        self._highlight_toc(label, href)

    def _update_page_label(self) -> None:
        """底栏页码：摊开时显示 16–17，单页显示 16。"""
        page = int(self._location.get("page") or 0)
        total = int(self._location.get("total") or 0)
        if self._spread_active and page > 0:
            right = min(page + 1, total) if total else page + 1
            text = f"{page}–{right}/{total}" if total else f"第 {page}–{right} 页"
        elif total:
            text = f"{page}/{total}"
        else:
            text = f"第 {page} 页"
        self.page_label.setText(text)

    def _on_spread_changed(self, book_id: int, active: bool) -> None:
        if book_id != self._book_id:
            return
        self._spread_active = bool(active)
        # 用户选了双页但窗口太窄 → 临时回落单页：置灰双页选项提示，不改 prefs。
        user_wants_spread = self._reader_prefs()["page_mode"] == "spread"
        narrow = user_wants_spread and not self._spread_active
        item = self.prefs_columns.model().item(1)  # 双页（摊开）
        if item is not None:
            item.setEnabled(not narrow)
            item.setToolTip("窗口太窄，已临时回落单页" if narrow else "")
        self._update_page_label()

    def _on_progress_preview(self, value: int) -> None:
        """拖动进度条时只预览页码，松手才真正跳转。"""
        total = int(self._location.get("total") or 0)
        if not total:
            return
        page = max(1, min(total, int(round(value / 1000 * total))))
        self.page_label.setText(f"{page}/{total}")

    def _on_slider(self) -> None:
        if not self._web_enabled:
            return
        self.web.go_to_percent(self.progress.value() / 1000)

    # ---- 剩余时间 ---------------------------------------------------
    def _average_page_seconds(self) -> float | None:
        """用累计阅读时长与已读页数估算每页秒数；样本不足返回 None。"""
        if not self._book_id:
            return None
        row = self.repo.get_progress(self._book_id)
        if row is None:
            return None
        seconds = float(row["total_seconds"] or 0)
        percent = float(row["percent"] or 0)
        total = int(self._location.get("total") or 0)
        pages_read = percent * total
        if seconds >= 20 and pages_read >= 2:
            return seconds / pages_read
        return None

    def _update_remaining(self, section_seconds: float) -> None:
        """本章剩余 = 剩余页数 × 每页秒数；没有统计样本时显示破折号。"""
        average = self._average_page_seconds()
        pages = 0
        if average:
            if section_seconds > 0:
                pages = max(1, int(round(section_seconds / average)))
            else:
                pages = self._pdf_section_remaining(int(self._location.get("page") or 0))
        if not average or not pages:
            self.remaining_label.setText("本章剩余 —")
            self.remaining_label.setToolTip("读几页后开始估算")
            return
        minutes = max(1, int(round(pages * average / 60)))
        self.remaining_label.setText(f"本章剩余 {minutes} 分钟 / {pages} 页")
        self.remaining_label.setToolTip("按当前阅读速度估算")

    def _pdf_section_remaining(self, page: int) -> int:
        """PDF 按 outline 的下一章起始页推算本章还剩多少页。"""
        if page <= 0:
            return 0
        starts = sorted(
            int(item.get("page") or 0)
            for item in self._toc
            if int(item.get("page") or 0) > 0
        )
        for start in starts:
            if start > page:
                return start - page
        total = int(self._location.get("total") or 0)
        return max(0, total - page + 1) if total else 0

    def _saved_locator(self) -> dict[str, Any] | None:
        if not self._book_id:
            return None
        row = self.repo.get_progress(self._book_id)
        if row is None or not row["locator_json"]:
            return None
        try:
            data = json.loads(row["locator_json"])
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def _saved_highlights(self) -> list[dict[str, Any]]:
        """把已落库的 EPUB 高亮交给前端重绘。"""
        if not self._book_id:
            return []
        marks: list[dict[str, Any]] = []
        for row in self.repo.list_bookmarks(self._book_id):
            if str(row["kind"] or "") != "highlight":
                continue
            try:
                locator = json.loads(row["locator_json"] or "{}")
            except ValueError:
                continue
            if not isinstance(locator, dict) or locator.get("type") != "epub":
                continue
            if locator.get("cfiRange"):
                marks.append(
                    {
                        "cfiRange": str(locator["cfiRange"]),
                        "color": str(row["color"] or "#ffe08a"),
                    }
                )
        return marks

    # ---- 书签 / 高亮 ------------------------------------------------
    def add_bookmark(self) -> None:
        if self._web_enabled:
            self.web.request_bookmark()

    def _on_bookmarks_changed(self, book_id: int) -> None:
        if book_id != self._book_id:
            return
        index = self.sidebar_stack.currentIndex()
        if index == 1:
            self._refresh_notes()
        elif index == 2:
            self._refresh_bookmarks()

    def _toggle_bookmarks(self) -> None:
        showing = self._sidebar_visible and self.sidebar_stack.currentIndex() == 2
        if showing:
            self._show_sidebar(False)
            self.bookmark_button.setChecked(False)
        else:
            self._select_sidebar_tab(2)

    def _refresh_bookmarks(self) -> None:
        self.bookmark_list.clear()
        if not self._book_id:
            return
        for row in self.repo.list_bookmarks(self._book_id):
            kind = str(row["kind"] or "bookmark")
            prefix = "🔖" if kind == "bookmark" else "✎"
            label = str(row["chapter"] or row["text"] or "未命名")[:36]
            node = QListWidgetItem(f"{prefix}  {label}")
            node.setData(Qt.UserRole, int(row["id"]))
            node.setData(Qt.UserRole + 1, str(row["locator_json"] or ""))
            node.setToolTip(str(row["note"] or row["text"] or ""))
            self.bookmark_list.addItem(node)

    def _refresh_notes(self) -> None:
        """笔记页只列 kind=highlight 的标注。"""
        self.note_list.clear()
        if not self._book_id:
            return
        for row in self.repo.list_bookmarks(self._book_id, kind="highlight"):
            label = str(row["text"] or row["note"] or "未命名")[:36]
            node = QListWidgetItem(f"✎  {label}")
            node.setData(Qt.UserRole, int(row["id"]))
            node.setData(Qt.UserRole + 1, str(row["locator_json"] or ""))
            node.setToolTip(str(row["note"] or row["text"] or ""))
            self.note_list.addItem(node)

    def _delete_note(self) -> None:
        item = self.note_list.currentItem()
        if item is None:
            return
        note_id = int(item.data(Qt.UserRole) or 0)
        if note_id:
            self.repo.delete_bookmark(note_id)
        self._refresh_notes()

    def _jump_bookmark(self, item: QListWidgetItem) -> None:
        if not self._web_enabled:
            return
        raw = str(item.data(Qt.UserRole + 1) or "")
        try:
            locator = json.loads(raw)
        except ValueError:
            return
        if not isinstance(locator, dict):
            return
        if locator.get("type") == "pdf":
            page = int(locator.get("page") or 0)
            if page > 0:
                self.web.go_to({"page": page})
        else:
            target = locator.get("cfi") or locator.get("href")
            if target:
                self.web.go_to(str(target))

    def _delete_bookmark(self) -> None:
        item = self.bookmark_list.currentItem()
        if item is None:
            return
        bookmark_id = int(item.data(Qt.UserRole) or 0)
        if bookmark_id:
            self.repo.delete_bookmark(bookmark_id)
        self._refresh_bookmarks()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_chrome_anim"):
            self._chrome_anim.stop()
        if hasattr(self, "bottombar"):
            self._position_chrome()
        if self.loading_overlay.isVisible():
            self.loading_overlay.setGeometry(self._center.rect())
        if hasattr(self, "detail_panel") and self.detail_panel.isVisible():
            self._position_book_detail()
        self._elide_title()

    # ---- 阅读会话（D2） ---------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        window = self.window()
        if self._filtered_window is not window:
            if self._filtered_window is not None:
                self._filtered_window.removeEventFilter(self)
            window.installEventFilter(self)
            self._filtered_window = window
        self._ensure_session()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._end_session()
        super().hideEvent(event)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._filtered_window and event.type() in (
            QEvent.ActivationChange,
            QEvent.WindowStateChange,
            QEvent.Hide,
            QEvent.Show,
            QEvent.Close,
        ):
            self._sync_session_clock()
        return super().eventFilter(obj, event)

    def _session_active(self) -> bool:
        window = self.window()
        return bool(
            self._book_id
            and self.isVisible()
            and window.isActiveWindow()
            and not window.isMinimized()
        )

    def _ensure_session(self) -> None:
        if self._session_id is not None or not self._book_id:
            return
        try:
            self._session_id = self.repo.start_session(self._book_id)
        except Exception as exc:  # 统计失败不应打断阅读
            log.warning("创建阅读会话失败：%s", exc)
            return
        self._session_seconds = 0.0
        self._session_pages = 0
        self._session_last = time.monotonic() if self._session_active() else None

    def _accrue_session(self) -> None:
        if self._session_last is None:
            return
        now = time.monotonic()
        self._session_seconds += max(0.0, now - self._session_last)
        self._session_last = now

    def _sync_session_clock(self) -> None:
        """窗口激活/最小化切换时暂停或恢复计时。"""
        if self._session_id is None:
            if self._session_active():
                self._ensure_session()
            return
        if self._session_active():
            if self._session_last is None:
                self._session_last = time.monotonic()
            return
        self._accrue_session()
        self._session_last = None
        self._flush_session()

    def _flush_session(self) -> None:
        if self._session_id is None:
            return
        self._accrue_session()
        seconds = int(self._session_seconds)
        pages = self._session_pages
        if seconds <= 0 and pages <= 0:
            return
        try:
            self.repo.add_session_progress(self._session_id, seconds, pages)
        except Exception as exc:  # 统计失败不应打断阅读
            log.warning("写入阅读会话失败：%s", exc)
            return
        self._session_seconds -= seconds
        self._session_pages = 0

    def _end_session(self) -> None:
        self._flush_session()
        session_id = self._session_id
        self._session_id = None
        self._session_last = None
        self._session_seconds = 0.0
        self._session_pages = 0
        if session_id is None:
            return
        try:
            self.repo.end_session(session_id)
        except Exception as exc:
            log.warning("结束阅读会话失败：%s", exc)

    # ---- 主题 / 字体 -------------------------------------------------
    def _merged_reader(self) -> dict[str, Any]:
        """全局阅读设置叠加当前书籍的覆盖项。"""
        reader = dict(self.settings.data.get("reader") or {})
        books = reader.get("books")
        if self._book_id and isinstance(books, dict):
            override = books.get(str(self._book_id))
            if isinstance(override, dict):
                reader.update(override)
        return reader

    def _resolve_palette(self, raw: dict[str, Any] | None = None) -> ReaderPalette:
        data = self._merged_reader() if raw is None else raw
        palette = palette_for(
            data.get("theme"), data.get("mode"), system_dark=_system_dark()
        )
        accent = str(data.get("accent") or "").strip()
        if _HEX_COLOR.match(accent):
            palette = replace(palette, accent=accent.lower())
        return palette

    def _migrate_reader_prefs_v5(self) -> None:
        """一次性迁移：老用户存的 column_count=2（旧双栏）映射为 page_mode=spread。

        用 settings 顶层标记 reader_prefs_migrated_v5 控制只跑一次；已存在 page_mode
        时不覆盖（用户在新版里手动改过就尊重）。
        """
        if self.settings.data.get("reader_prefs_migrated_v5"):
            return
        reader = self.settings.data.setdefault("reader", {})
        if (
            "page_mode" not in reader
            and _as_int(reader.get("column_count"), 1) == 2
        ):
            reader["page_mode"] = "spread"
        self.settings.data["reader_prefs_migrated_v5"] = 1
        try:
            self.settings.save()
        except BookShelfError as exc:
            log.warning("保存阅读器偏好迁移失败：%s", exc)

    def _reader_prefs(self) -> dict[str, Any]:
        data = self._merged_reader()
        palette = self._resolve_palette(data)
        legacy = _as_int(data.get("margin_px"), 64)
        mode = str(data.get("mode") or "auto")
        weight = _as_int(data.get("font_weight"), 400)
        turn = str(data.get("turn_style") or "push")
        texture = str(data.get("texture") or "none")
        return {
            "theme": palette.key,
            "mode": mode if mode in _PREF_MODES else "auto",
            "palette": palette.as_dict(),
            "font_family": str(data.get("font_family") or _FONTS[0]),
            "reader_font_cjk": str(
                data.get("reader_font_cjk") or _default_font_family("中文", "LXGW WenKai")
            ),
            "reader_font_latin": str(
                data.get("reader_font_latin") or _default_font_family("English", "Literata")
            ),
            "font_size": min(40, max(10, _as_int(data.get("font_size"), 19))),
            "line_height": min(3.0, max(1.0, _as_float(data.get("line_height"), 1.9))),
            "font_weight": weight if weight in _FONT_WEIGHTS else 400,
            "para_spacing": min(3.0, max(0.0, _as_float(data.get("para_spacing"), 0.75))),
            "indent": _as_bool(data.get("indent"), True),
            "justify": _as_bool(data.get("justify"), True),
            "hyphens": _as_bool(data.get("hyphens"), False),
            "margin_top": min(240, max(0, _as_int(data.get("margin_top"), legacy))),
            "margin_bottom": min(240, max(0, _as_int(data.get("margin_bottom"), legacy))),
            "margin_left": min(240, max(0, _as_int(data.get("margin_left"), legacy))),
            "margin_right": min(240, max(0, _as_int(data.get("margin_right"), legacy))),
            "margin_px": legacy,
            "column_count": 2 if _as_int(data.get("column_count"), 1) == 2 else 1,
            "page_mode": "spread" if str(data.get("page_mode")) == "spread" else "single",
            "page_width": min(900, max(420, _as_int(data.get("page_width"), 560))),
            "disable_double_click": _as_bool(data.get("disable_double_click"), False),
            "auto_turn_sec": min(120, max(0, _as_int(data.get("auto_turn_sec"), 0))),
            "reading_ruler": _as_bool(data.get("reading_ruler"), False),
            "mask_top": _as_bool(data.get("mask_top"), True),
            "show_clock": _as_bool(data.get("show_clock"), True),
            "show_remaining": _as_bool(data.get("show_remaining"), True),
            "highlight_colors": _highlight_colors(data.get("highlight_colors")),
            "turn_anim": str(data.get("turn_anim") or "flip")
            if str(data.get("turn_anim") or "flip") in {"instant", "push", "flip"}
            else "flip",
            "max_column_width": min(
                1200, max(520, _as_int(data.get("max_column_width"), 920))
            ),
            "turn_style": turn
            if turn in [value for value, _label in _TURN_STYLES]
            else "push",
            "click_turn": _as_bool(data.get("click_turn"), True),
            "hide_chrome_delay": min(
                10000, max(600, _as_int(data.get("hide_chrome_delay"), 1600))
            ),
            "header_footer": self._header_footer(),
            "texture": texture if texture in [value for value, _label in _TEXTURES] else "none",
            "accent": str(data.get("accent") or "") if _HEX_COLOR.match(
                str(data.get("accent") or "")
            ) else None,
        }

    def _header_footer(self) -> dict[str, bool]:
        """底栏信息开关；缺字段时回落到默认配置。"""
        defaults = config.DEFAULT_CONFIG["reader"]["header_footer"]
        raw = self._merged_reader().get("header_footer")
        data = raw if isinstance(raw, dict) else {}
        return {
            key: _as_bool(data.get(key), bool(value)) for key, value in defaults.items()
        }

    def _apply_header_footer(self) -> None:
        flags = self._header_footer()
        self.progress.setVisible(flags["progress"])
        self.page_label.setVisible(flags["progress"])
        self.remaining_label.setVisible(
            flags["remaining_time"] or flags["remaining_pages"]
        )
        self.clock_label.setVisible(flags["clock"])
        self._clock_24h = flags["clock_24h"]

    def _update_clock(self) -> None:
        now = QTime.currentTime()
        self.clock_label.setText(
            now.toString("HH:mm" if self._clock_24h else "h:mm AP")
        )

    def _apply_theme(self) -> None:
        theme = self._resolve_palette()
        self.setStyleSheet(_reader_qss(theme))
        for button in self._icon_buttons:
            button.set_icon_color(theme.ink)
        self.progress.apply_palette(theme)
        if hasattr(self, "cover_card"):
            self.cover_card.set_theme(theme)
            self._render_cover_thumb()
        self._apply_header_footer()
        self._update_clock()

    def _reset_prefs(self) -> None:
        """只恢复阅读外观相关字段，不动外部阅读器路径与按书覆盖。"""
        reader = self.settings.data.setdefault("reader", {})
        for key, value in config.DEFAULT_CONFIG["reader"].items():
            if key in ("external_readest_path", "open_mode", "books"):
                continue
            reader[key] = copy.deepcopy(value)
        reader.pop("margin_px", None)
        try:
            self.settings.save()
        except BookShelfError as exc:
            log.warning("保存阅读器设置失败：%s", exc)
        self._apply_theme()
        if self._web_enabled:
            self.web.set_prefs(self._reader_prefs())
        self._refresh_toc_meta()
        self._sync_prefs_widgets()

    def _update_prefs(self, **changes: Any) -> None:
        if self._syncing:
            return
        reader = self.settings.data.setdefault("reader", {})
        reader.update(changes)
        try:
            self.settings.save()
        except BookShelfError as exc:
            log.warning("保存阅读器设置失败：%s", exc)
        self._apply_theme()
        prefs = self._reader_prefs()
        if self._web_enabled:
            self.web.set_prefs(prefs)
        self._refresh_toc_meta()
        self._sync_prefs_widgets()

    def _sync_prefs_widgets(self) -> None:
        prefs = self._reader_prefs()
        palette = self._resolve_palette()
        self._syncing = True
        try:
            self._sync_font_combo(self.prefs_font_cjk, prefs["reader_font_cjk"])
            self._sync_font_combo(self.prefs_font_latin, prefs["reader_font_latin"])
            self.prefs_size.set_value(prefs["font_size"])
            self.font_stepper.set_value(prefs["font_size"])
            self.prefs_line.set_value(prefs["line_height"])
            self._set_combo_data(self.prefs_weight, prefs["font_weight"])
            self.prefs_para.set_value(prefs["para_spacing"])
            self.prefs_indent.setChecked(prefs["indent"])
            self.prefs_justify.setChecked(prefs["justify"])
            self.prefs_hyphens.setChecked(prefs["hyphens"])
            self.prefs_margin_top.set_value(prefs["margin_top"])
            self.prefs_margin_bottom.set_value(prefs["margin_bottom"])
            self.prefs_margin_left.set_value(prefs["margin_left"])
            self.prefs_margin_right.set_value(prefs["margin_right"])
            self._set_combo_data(self.prefs_columns, prefs["page_mode"])
            self.prefs_max_width.set_value(prefs["max_column_width"])
            for key, button in self.turn_buttons.items():
                button.setChecked(key == prefs["turn_style"])
            self.prefs_click.setChecked(prefs["click_turn"])
            for key, button in self.mode_buttons.items():
                button.setChecked(key == prefs["mode"])
            for key, button in self.texture_buttons.items():
                button.setChecked(key == prefs["texture"])
            for key, button in self.theme_swatches.items():
                button.setChecked(key == prefs["theme"])
            accent = prefs["accent"] or palette.accent
            self.prefs_accent_value.setText(
                ("自定义 " if prefs["accent"] else "跟随 ") + accent.upper()
            )
            self.prefs_accent_swatch.setStyleSheet(
                f"background: {accent}; border: 1px solid {palette.border}; border-radius: 4px;"
            )
        finally:
            self._syncing = False

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: Any) -> None:
        index = combo.findData(value)
        if index < 0:
            index = combo.findText(str(value))
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _sync_font_combo(combo: QComboBox, family: str) -> None:
        """按 family 选中下拉项；旧配置里的系统/自定义字体不在清单时补一项保留。"""
        index = combo.findData(family)
        if index < 0 and family:
            combo.addItem(family, family)
            index = combo.count() - 1
        if index >= 0:
            combo.setCurrentIndex(index)

    def _change_font(self, delta: int) -> None:
        size = max(10, min(40, self._reader_prefs()["font_size"] + delta))
        self._update_prefs(font_size=size)

    def _cycle_theme(self) -> None:
        current = self._reader_prefs()["theme"]
        try:
            index = THEME_KEYS.index(current)
        except ValueError:
            index = -1
        self._select_theme(THEME_KEYS[(index + 1) % len(THEME_KEYS)])

    def _show_prefs(self) -> None:
        self._sync_prefs_widgets()
        self.prefs_popup.adjustSize()
        button = self.aa_button
        anchor = button.mapToGlobal(QPoint(button.width() - self.prefs_popup.width(), button.height() + 6))
        self.prefs_popup.move(anchor)
        self.prefs_popup.setWindowOpacity(0.0)
        self.prefs_popup.show()
        self._prefs_fade.stop()
        self._prefs_fade.setStartValue(0.0)
        self._prefs_fade.setEndValue(1.0)
        self._prefs_fade.start()

    def _refresh_toc_meta(self) -> None:
        prefs = self._reader_prefs()
        self.toc_meta.setText(
            f"{self._resolve_palette().label} · {prefs['font_size']}px · 行距 {prefs['line_height']:.2f}"
        )

    # ---- 搜索 -------------------------------------------------------
    def toggle_search(self) -> None:
        visible = not self.search_bar.isVisible()
        self.search_bar.setVisible(visible)
        # 搜索框聚焦时把翻页键让给输入，避免打字被快捷键吃掉。
        for shortcut in getattr(self, "_typing_shortcuts", []):
            shortcut.setEnabled(not visible)
        if visible:
            self.search_edit.setFocus()
            self.search_edit.selectAll()
        elif self._web_enabled:
            self.search_count.setText("")
            self.web.close_search()

    def _search_now(self) -> None:
        keyword = self.search_edit.text().strip()
        if not keyword:
            self.search_count.setText("")
            return
        if self._web_enabled:
            self.web.search(keyword)

    def _search_next(self) -> None:
        if self._web_enabled and self.search_edit.text().strip():
            self.web.search_next()

    def _on_search_finished(self, total: int, current: int) -> None:
        self.search_count.setText(f"{current}/{total}" if total else "无结果")

    # ---- 翻页 / 全屏 / 返回 ------------------------------------------
    def next_page(self) -> None:
        if self._web_enabled:
            self.web.next_page()
        self._show_chrome()

    def prev_page(self) -> None:
        if self._web_enabled:
            self.web.prev_page()
        self._show_chrome()

    def next_chapter(self) -> None:
        if self._web_enabled:
            self.web.turn_chapter(1)
        self._show_chrome()

    def prev_chapter(self) -> None:
        if self._web_enabled:
            self.web.turn_chapter(-1)
        self._show_chrome()

    def go_to_percent(self, percent: float) -> None:
        if self._web_enabled:
            self.web.go_to_percent(percent)
        self._show_chrome()

    def _reset_font_size(self) -> None:
        self._update_prefs(font_size=config.DEFAULT_CONFIG["reader"]["font_size"])

    # ---- R1：顶栏 / 底栏自动隐藏 ------------------------------------
    def _init_chrome_autohide(self) -> None:
        """顶底栏同步滑出；仅光标进入顶部或底部唤出区域时恢复。"""
        self._chrome_visible = True
        self._last_cursor: QPoint | None = None
        self._chrome_hide_timer = QTimer(self)
        self._chrome_hide_timer.setSingleShot(True)
        self._chrome_hide_timer.timeout.connect(self._hide_chrome)
        # WebEngine 不向宿主派发 mouseMove，用全局光标轮询兜底。
        self._cursor_poll = QTimer(self)
        self._cursor_poll.setInterval(100)
        self._cursor_poll.timeout.connect(self._poll_cursor)

        self._chrome_anim = QParallelAnimationGroup(self)
        self._chrome_pos_anims: dict[str, QPropertyAnimation] = {}
        self._chrome_opacity_anims: dict[str, QPropertyAnimation] = {}
        for name, target, effect in (
            ("top", self.topbar, self._topbar_opacity),
            ("bottom", self.bottombar, self._bottombar_opacity),
        ):
            pos_anim = QPropertyAnimation(target, b"pos")
            pos_anim.setDuration(180)
            pos_anim.setEasingCurve(QEasingCurve.OutCubic)
            opacity_anim = QPropertyAnimation(effect, b"opacity")
            opacity_anim.setDuration(180)
            opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
            self._chrome_anim.addAnimation(pos_anim)
            self._chrome_anim.addAnimation(opacity_anim)
            self._chrome_pos_anims[name] = pos_anim
            self._chrome_opacity_anims[name] = opacity_anim
        self._position_chrome()
        self._cursor_poll.start()
        self._schedule_chrome_hide()

    def _poll_cursor(self) -> None:
        pos = QCursor.pos()
        if self._last_cursor is not None and (pos - self._last_cursor).manhattanLength() <= 2:
            return
        self._last_cursor = pos
        local = self.mapFromGlobal(pos)
        if self.rect().contains(local) and (
            local.y() < 96 or local.y() > self.height() - 76
        ):
            self._show_chrome()

    def _schedule_chrome_hide(self) -> None:
        delay = int(self._reader_prefs().get("hide_chrome_delay") or 1600)
        self._chrome_hide_timer.start(delay)

    def _chrome_should_hide(self) -> bool:
        if not self._book_id or self.topbar.isHidden() or self._sidebar_visible:
            return False
        if self.prefs_popup.isVisible() or self.search_bar.isVisible():
            return False
        if self.more_menu.isVisible() or not self.loading_overlay.isHidden():
            return False
        detail = getattr(self, "detail_panel", None)
        return not bool(detail and not detail.isHidden())

    def _chrome_targets(self, visible: bool) -> dict[str, QPoint]:
        return {
            "top": QPoint(0, 0 if visible else -self.topbar.height()),
            "bottom": QPoint(
                0,
                self.height() - self.bottombar.height()
                if visible
                else self.height(),
            ),
        }

    def _position_chrome(self) -> None:
        targets = self._chrome_targets(getattr(self, "_chrome_visible", True))
        self.topbar.setGeometry(
            0, targets["top"].y(), self.width(), self.topbar.height()
        )
        self.bottombar.setGeometry(
            0, targets["bottom"].y(), self.width(), self.bottombar.height()
        )

    def _animate_chrome(self, visible: bool) -> None:
        self._chrome_anim.stop()
        targets = self._chrome_targets(visible)
        for name, target, effect in (
            ("top", self.topbar, self._topbar_opacity),
            ("bottom", self.bottombar, self._bottombar_opacity),
        ):
            pos_anim = self._chrome_pos_anims[name]
            pos_anim.setStartValue(target.pos())
            pos_anim.setEndValue(targets[name])
            opacity_anim = self._chrome_opacity_anims[name]
            opacity_anim.setStartValue(effect.opacity())
            opacity_anim.setEndValue(1.0 if visible else 0.0)
        self._chrome_anim.start()

    def _show_chrome(self) -> None:
        # 正文点击手动收起时，不因翻页等操作擅自恢复。
        if self.topbar.isHidden():
            self._schedule_chrome_hide()
            return
        was_visible = self._chrome_visible
        self._chrome_visible = True
        self.topbar.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.bottombar.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        if not was_visible:
            self._animate_chrome(True)
        else:
            self._position_chrome()
        self._schedule_chrome_hide()

    def _hide_chrome(self) -> None:
        if not self._chrome_should_hide():
            self._schedule_chrome_hide()
            return
        self._chrome_hide_timer.stop()
        self._chrome_visible = False
        self.topbar.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.bottombar.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._animate_chrome(False)

    def _toggle_chrome(self) -> None:
        """点击正文中间：淡出时先恢复；否则收起或呼出顶栏与底栏。"""
        if not self._chrome_visible:
            self._show_chrome()
            return
        visible = self.topbar.isHidden()
        self.topbar.setVisible(visible)
        self.bottombar.setVisible(visible)
        if visible:
            self._show_chrome()

    def _show_shortcut_help(self) -> None:
        QMessageBox.information(
            self,
            "快捷键",
            "← / h / Shift+空格　上一页\n"
            "→ / l / 空格　　　下一页\n"
            "Alt+← / Alt+→　　上/下一章\n"
            "d / u　　　　　　下/上半页\n"
            "Home / End　　　首 / 尾\n"
            "Ctrl+= / Ctrl+-　字号增减（Ctrl+0 复原）\n"
            "Ctrl+F 搜索　Ctrl+B 目录　Ctrl+Shift+T 主题\n"
            "F11 全屏　Shift+? 本帮助　Esc 返回",
        )

    def _toggle_fullscreen(self) -> None:
        window = self.window()
        if window.isFullScreen():
            window.showNormal()
        else:
            window.showFullScreen()

    def _bind_shortcuts(self) -> None:
        """按规范 §3.6 注册快捷键；正文 iframe 内只保留 Escape。"""
        context = Qt.WidgetWithChildrenShortcut
        # 搜索框聚焦时这些键要留给输入法/光标，不能翻页。
        typing_keys = {
            "Left",
            "Right",
            "h",
            "l",
            "Space",
            "Shift+Space",
            "Alt+Left",
            "Alt+Right",
            "d",
            "u",
            "Home",
            "End",
        }
        bindings = (
            ("Escape", self._on_escape),
            ("Left", self.prev_page),
            ("Right", self.next_page),
            ("h", self.prev_page),
            ("l", self.next_page),
            ("Shift+Space", self.prev_page),
            ("Space", self.next_page),
            ("Alt+Left", self.prev_chapter),
            ("Alt+Right", self.next_chapter),
            ("d", self.next_page),
            ("u", self.prev_page),
            ("Home", lambda: self.go_to_percent(0.0)),
            ("End", lambda: self.go_to_percent(1.0)),
            ("Ctrl+=", lambda: self._change_font(1)),
            ("Ctrl+-", lambda: self._change_font(-1)),
            ("Ctrl+0", self._reset_font_size),
            ("Ctrl+F", self.toggle_search),
            ("Ctrl+B", self._toggle_toc),
            ("F11", self._toggle_fullscreen),
            ("Shift+?", self._show_shortcut_help),
            ("Ctrl+Shift+T", self._cycle_theme),
        )
        self._typing_shortcuts: list[QShortcut] = []
        for keys, slot in bindings:
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(context)
            shortcut.activated.connect(slot)
            if keys in typing_keys:
                self._typing_shortcuts.append(shortcut)

    def _on_escape(self) -> None:
        if not self.detail_panel.isHidden():
            self._hide_book_detail()
            return
        if self.window().isFullScreen():
            self._toggle_fullscreen()
            return
        if self.prefs_popup.isVisible():
            self.prefs_popup.hide()
            return
        if self.search_bar.isVisible():
            self.toggle_search()
            return
        if not self._chrome_visible:
            self._show_chrome()
            return
        if self.topbar.isHidden() or self.bottombar.isHidden():
            self.topbar.setVisible(True)
            self.bottombar.setVisible(True)
            return
        if self._sidebar_visible and self.sidebar_stack.currentIndex() != 0:
            self._show_sidebar(False)
            return
        self._on_back()

    def _on_back(self) -> None:
        self.flush()
        self.back_requested.emit()

    # ---- 错误页 / 外部打开 -------------------------------------------
    def _show_error(self, message: str) -> None:
        self._slow_timer.stop()
        self._render_watchdog.stop()
        self._hide_loading_overlay()
        text = str(message or "未知错误")
        self.error_reason.setText(text)
        # 提示必须随真实原因变化：以前所有失败都显示 DRM 文案，会误导用户。
        lower = text.lower()
        if "drm" in lower or "encrypt" in lower or "加密" in text:
            hint = "受 DRM 保护的文件不会进行任何解密尝试。"
        elif any(
            token in lower for token in ("container", "package document", "opf", "zip")
        ) or "无法读取" in text:
            hint = "这本书的 EPUB 目录结构与内部声明不一致，容错读取后仍无法解析；可尝试用系统默认程序打开。"
        elif "password" in lower or "密码" in text:
            hint = "该文件受密码保护，BookShelf 无法打开。"
        else:
            hint = "可点击「重试」，或选择「用系统默认程序打开」。"
        self.error_hint.setText(hint)
        self.stack.setCurrentWidget(self.error_page)

    def _on_web_failed(self, message: str) -> None:
        self._show_error(f"渲染失败：{message}")

    def _open_external(self) -> None:
        self.open_external(self._book_path)

    def open_external(self, path: str) -> None:
        error = open_with_system(path)
        if error:
            self._show_error(error)

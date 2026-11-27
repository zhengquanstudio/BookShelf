"""阅读态 Web 载体：本地 reader.html + QWebChannel 桥。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from ..db.connection import Database
from ..logger import get_logger
from . import ASSETS_DIR, READER_HTML
from .bridge import ReaderBridge

log = get_logger("reader")

WEBENGINE_AVAILABLE = True


class _ReaderPage(QWebEnginePage):
    """只允许访问本地阅读器资源，杜绝运行时外网请求。"""

    def acceptNavigationRequest(  # noqa: N802
        self, url: QUrl, nav_type: QWebEnginePage.NavigationType, is_main_frame: bool
    ) -> bool:
        scheme = url.scheme().lower()
        if scheme in ("file", "data", "blob", "about"):
            if scheme == "file":
                path = Path(url.toLocalFile()).resolve()
                try:
                    path.relative_to(ASSETS_DIR.resolve())
                except ValueError:
                    return False
            return True
        log.warning("阅读器阻止了外部导航：%s", url.toString())
        return False


class ReaderWebView(QWebEngineView):
    """封装 WebEngine 设置、桥注册与 JS 调用。"""

    bridgeFailed = Signal(str)

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._ready = False
        self._pending_open: str | None = None

        page = _ReaderPage(self)
        self.setPage(page)
        page.setBackgroundColor(QColor("#e9e6df"))
        # 本地资源随版本更新，禁用磁盘缓存避免读到旧脚本。
        page.profile().setHttpCacheType(
            QWebEngineProfile.HttpCacheType.NoCache
        )

        web_settings = page.settings()
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        web_settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
        web_settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, False)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
        web_settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False
        )
        web_settings.setAttribute(
            QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, False
        )

        self.bridge = ReaderBridge(db, self)
        self._channel = QWebChannel(page)
        self._channel.registerObject("bridge", self.bridge)
        page.setWebChannel(self._channel)

        self.bridge.frontendReady.connect(self._on_ready)
        self.bridge.failed.connect(self.bridgeFailed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.load(QUrl.fromLocalFile(str(READER_HTML)))

    # ---- JS 调用 -----------------------------------------------------
    def _on_ready(self) -> None:
        self._ready = True
        if self._pending_open is not None:
            payload, self._pending_open = self._pending_open, None
            self.run_js(f"window.readerApi.open({payload});")

    def run_js(self, script: str) -> None:
        self.page().runJavaScript(script)

    def open_payload(self, payload: dict[str, Any]) -> None:
        """等前端 bridge 就绪后再下发打开指令。"""
        self._apply_page_background((payload.get("prefs") or {}).get("palette") or {})
        encoded = json.dumps(payload, ensure_ascii=False)
        if self._ready:
            self.run_js(f"window.readerApi.open({encoded});")
        else:
            self._pending_open = encoded

    def set_prefs(self, prefs: dict[str, Any]) -> None:
        self._apply_page_background(prefs.get("palette") or {})
        encoded = json.dumps(prefs, ensure_ascii=False)
        self.run_js(f"window.readerApi.setPrefs({encoded});")

    def _apply_page_background(self, palette: dict[str, Any]) -> None:
        """WebEngine 画布底色跟随主题 canvas，切主题时不会闪出深色底。"""
        color = str((palette or {}).get("canvas") or "").strip()
        if color:
            self.page().setBackgroundColor(QColor(color))

    def go_to(self, target: str | dict[str, Any]) -> None:
        encoded = json.dumps(target, ensure_ascii=False)
        self.run_js(f"window.readerApi.goTo({encoded});")

    def next_page(self) -> None:
        self.run_js("window.readerApi.next();")

    def go_to_percent(self, percent: float) -> None:
        self.run_js(f"window.readerApi.goToPercent({float(percent)});")

    def prev_page(self) -> None:
        self.run_js("window.readerApi.prev();")

    def turn_chapter(self, direction: int) -> None:
        self.run_js(f"window.readerApi.turnChapter({int(direction)});")

    def request_bookmark(self) -> None:
        self.run_js("window.readerApi.addBookmark();")

    def search(self, keyword: str) -> None:
        encoded = json.dumps(keyword, ensure_ascii=False)
        self.run_js(f"window.readerApi.search({encoded});")

    def search_next(self) -> None:
        self.run_js("window.readerApi.searchNext();")

    def close_search(self) -> None:
        self.run_js("window.readerApi.closeSearch();")

    def add_highlight(self, locator: str, color: str) -> None:
        encoded = json.dumps(locator, ensure_ascii=False)
        self.run_js(f"window.readerApi.highlight({encoded}, {json.dumps(color)});")

"""内嵌阅读器：本地 Web 前端资源、MOBI/AZW3 转换与 QWebChannel 桥。"""

from __future__ import annotations

from pathlib import Path

ASSETS_DIR = Path(__file__).with_name("assets")
READER_HTML = ASSETS_DIR / "reader.html"

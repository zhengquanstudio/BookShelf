"""顶栏 / 底栏用的线性图标按钮。

图标是 `app/ui/resources/icons/*.svg` 里的 24×24 线性 SVG，`stroke="currentColor"`
在渲染前替换成当前主题的 ink 色，避免为深浅主题各准备一套图。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QPushButton, QWidget

ICONS_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons"


def icon_path(name: str) -> Path:
    """返回图标文件路径；调用方按 basename 取图，不带扩展名。"""
    return ICONS_DIR / f"{name}.svg"


class IconButton(QPushButton):
    """36×36（可缩小）的透明图标按钮，图标颜色随主题 ink 变化。"""

    def __init__(
        self,
        name: str,
        tooltip: str = "",
        *,
        checkable: bool = False,
        size: int = 36,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ReaderIconButton")
        self.setFixedSize(size, size)
        self.setIconSize(QSize(20 if size >= 36 else 16, 20 if size >= 36 else 16))
        self.setCheckable(checkable)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setToolTip(tooltip)
        self._name = name
        self._color = "#1f2328"
        self._render_icon()

    # ---- 对外接口 ---------------------------------------------------
    def icon_name(self) -> str:
        return self._name

    def set_icon_name(self, name: str) -> None:
        if name == self._name:
            return
        self._name = name
        self._render_icon()

    def set_icon_color(self, color: str) -> None:
        """主题切换时调用；颜色没变就不重复渲染。"""
        value = str(color or "").strip()
        if not value or value == self._color:
            return
        self._color = value
        self._render_icon()

    # ---- 内部 -------------------------------------------------------
    def _render_icon(self) -> None:
        path = icon_path(self._name)
        if not path.is_file():
            return
        svg = path.read_text(encoding="utf-8").replace("currentColor", self._color)
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        side = self.iconSize().width()
        # 2 倍渲染后交给 QIcon 缩放，高 DPI 屏不糊。
        ratio = 2
        pixmap = QPixmap(side * ratio, side * ratio)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(ratio)
        self.setIcon(QIcon(pixmap))

"""界面主题：深色为基准样式，浅色通过颜色映射生成，避免维护两份 QSS。"""

from __future__ import annotations

from pathlib import Path

_STYLE_PATH = Path(__file__).with_name("resources") / "style.qss"

# 深色 Token -> 浅色 Token（只替换样式表中出现的颜色值）
_LIGHT_COLORS = {
    "#17181b": "#f3f5f7",
    "#1b1d21": "#eceef2",
    "#1f2125": "#ffffff",
    "#25282d": "#f3f5f8",
    "#2c3036": "#e8ecf1",
    "#33383f": "#d8dde4",
    "#3a4048": "#c6ced8",
    "#4a515a": "#aeb7c2",
    "#22262c": "#e5e9ef",
    "#14161a": "#f7f8fa",
    "#1c1f24": "#eef1f5",
    "#2b2f35": "#dde2e9",
    "#151619": "#f8f9fb",
    "#1a1c20": "#ffffff",
    "#202226": "#eef1f5",
    "#0e0f12": "#ffffff",
    "#e7e9ee": "#20242b",
    "#d6d9df": "#2a2f36",
    "#a3a9b4": "#5b6470",
    "#6f7681": "#868e99",
    "#565d67": "#7c8490",
    "#8fb6fb": "#2f6fd0",
    "#649cf8": "#3f7ff0",
    "#3f78dd": "#2f6fd0",
}


def load_stylesheet(theme: str) -> str:
    """按主题名返回完整 QSS；未知主题按深色处理。"""
    text = _STYLE_PATH.read_text(encoding="utf-8")
    if str(theme).strip().lower() != "light":
        return text
    for dark, light in _LIGHT_COLORS.items():
        text = text.replace(dark, light)
    return text


def ui_colors(theme: str) -> dict[str, str]:
    """供 Python 内嵌 HTML（如命名示例）使用的主题色。"""
    if str(theme).strip().lower() == "light":
        return {
            "text": "#20242b",
            "muted": "#5b6470",
            "faint": "#868e99",
            "accent": "#2f6fd0",
            "error": "#c8443d",
        }
    return {
        "text": "#e7e9ee",
        "muted": "#a3a9b4",
        "faint": "#6f7681",
        "accent": "#4f8cf7",
        "error": "#e0645d",
    }


__all__ = ["load_stylesheet", "ui_colors"]

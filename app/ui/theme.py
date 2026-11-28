"""统一主题 token：主界面 chrome 底色（3 套）+ 强调色（5 套）。

单一来源，QSS 生成与 Python 内联绘制共用本模块。阅读器纸面 token 在 T14/T19
接入时同样落在本模块，避免色值散落。
"""

from __future__ import annotations

from pathlib import Path

_STYLE_PATH = Path(__file__).with_name("resources") / "style.qss"

# 兼容旧主题名
_THEME_ALIASES = {"dark": "night", "light": "gray"}

DEFAULT_THEME = "night"
DEFAULT_ACCENT = "blue"
BASE_THEME_NAMES = ("paper", "gray", "night")
ACCENT_NAMES = ("blue", "green", "purple", "amber", "rose")

# 深色基准（night，即现有 QSS）→ 纸白（paper，暖）。值取自 v4 原型 :root。
_PAPER_COLORS = {
    "#17181b": "#efe9dd",
    "#1b1d21": "#f5efe3",
    "#1f2125": "#fffdf8",
    "#25282d": "#f7f3ea",
    "#2c3036": "#f1ece0",
    "#33383f": "#e2dac9",
    "#3a4048": "#d9cfba",
    "#4a515a": "#c8bda6",
    "#22262c": "#f0ebe0",
    "#14161a": "#faf6ee",
    "#1c1f24": "#f5f0e6",
    "#2b2f35": "#e8e0d0",
    "#151619": "#faf6ee",
    "#1a1c20": "#fffdf8",
    "#202226": "#f5f0e6",
    "#0e0f12": "#fffdf8",
    "#e7e9ee": "#2b2a26",
    "#d6d9df": "#4a4840",
    "#a3a9b4": "#8a8377",
    "#6f7681": "#a59c89",
    "#565d67": "#9a917e",
}

# 深色基准 → 灰调（gray，冷）。沿用原“浅色”映射，保持稳定。
_GRAY_COLORS = {
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
}

_BASE_COLORS = {"paper": _PAPER_COLORS, "gray": _GRAY_COLORS, "night": {}}

# chrome 逻辑 token 的 night 基准值，供 Python 绘制读取（与 QSS 一致）。
_CHROME_BASE = {
    "night": {
        "bg": "#17181b", "panel": "#1f2125", "panel2": "#25282d", "hover": "#2c3036",
        "sidebar": "#1b1d21", "ink": "#e7e9ee", "muted": "#a3a9b4", "faint": "#6f7681",
        "line": "#33383f", "line2": "#3a4048", "scroll": "#4a515a",
    },
    "paper": {
        "bg": "#efe9dd", "panel": "#fffdf8", "panel2": "#f7f3ea", "hover": "#f1ece0",
        "sidebar": "#f5efe3", "ink": "#2b2a26", "muted": "#8a8377", "faint": "#a59c89",
        "line": "#e2dac9", "line2": "#d9cfba", "scroll": "#c8bda6",
    },
    "gray": {
        "bg": "#e9eaec", "panel": "#ffffff", "panel2": "#f4f5f7", "hover": "#eef0f3",
        "sidebar": "#f0f1f4", "ink": "#26282c", "muted": "#848a93", "faint": "#9aa0a8",
        "line": "#dcdee2", "line2": "#d2d5da", "scroll": "#c6ccd4",
    },
}

# 5 套强调色（取自 v4 原型）。blue 随底色不同，其余固定。
_ACCENTS = {
    "blue": {
        "paper": {"hex": "#3b6ef5", "rgb": "59, 110, 245", "soft": "#e7edff", "ink": "#2b56c4"},
        "gray": {"hex": "#3b6ef5", "rgb": "59, 110, 245", "soft": "#e7edff", "ink": "#2b56c4"},
        "night": {"hex": "#6d93ff", "rgb": "109, 147, 255", "soft": "#23304d", "ink": "#a9c0ff"},
    },
    "green": {
        "hex": "#2f9e6e", "rgb": "47, 158, 110", "soft": "#e4f5ec", "ink": "#1d6f4c",
    },
    "purple": {
        "hex": "#7a63d6", "rgb": "122, 99, 214", "soft": "#eeeaff", "ink": "#5642a8",
    },
    "amber": {
        "hex": "#c88a2a", "rgb": "200, 138, 42", "soft": "#fbf0dc", "ink": "#8f5f13",
    },
    "rose": {
        "hex": "#c95f7a", "rgb": "201, 95, 122", "soft": "#fce8ec", "ink": "#95405a",
    },
}

# 语义色（不随强调色变化）
_SEMANTIC = {
    "ok": "#2f9e6e", "warn": "#c88a2a", "bad": "#c95f7a", "error": "#c8443d",
}


def normalize_theme(theme: str) -> str:
    name = str(theme or DEFAULT_THEME).strip().lower()
    name = _THEME_ALIASES.get(name, name)
    return name if name in _BASE_COLORS else DEFAULT_THEME


def normalize_accent(accent: str) -> str:
    name = str(accent or DEFAULT_ACCENT).strip().lower()
    return name if name in _ACCENTS else DEFAULT_ACCENT


def is_light_theme(theme: str) -> bool:
    return normalize_theme(theme) in ("paper", "gray")


def accent_tokens(theme: str, accent: str) -> dict[str, str]:
    theme = normalize_theme(theme)
    accent = normalize_accent(accent)
    spec = _ACCENTS[accent]
    return spec.get(theme, spec)  # type: ignore[no-any-return]


def chrome_tokens(theme: str = DEFAULT_THEME, accent: str = DEFAULT_ACCENT) -> dict[str, str]:
    """chrome 逻辑 token → hex，供 Python 绘制使用（单一来源）。"""
    base = _CHROME_BASE[normalize_theme(theme)]
    acc = accent_tokens(theme, accent)
    return {
        **base,
        "accent": acc["hex"],
        "accent_soft": acc["soft"],
        "accent_ink": acc["ink"],
        "accent_rgb": acc["rgb"],
        **_SEMANTIC,
    }


def load_stylesheet(theme: str, accent: str = DEFAULT_ACCENT) -> str:
    """按主题名与强调色返回完整 QSS；未知值按 night + blue 处理。"""
    text = _STYLE_PATH.read_text(encoding="utf-8")
    base_name = normalize_theme(theme)
    for dark, light in _BASE_COLORS[base_name].items():
        text = text.replace(dark, light)
    acc = accent_tokens(theme, accent)
    for src, dst in (
        ("#4f8cf7", acc["hex"]),
        ("#649cf8", acc["hex"]),
        ("#3f78dd", acc["ink"]),
        ("#8fb6fb", acc["ink"]),
        ("#2f6fd0", acc["ink"]),
        ("rgba(79, 140, 247,", f"rgba({acc['rgb']},"),
    ):
        text = text.replace(src, dst)
    return text


def ui_colors(theme: str, accent: str | None = None) -> dict[str, str]:
    """供 Python 内嵌 HTML（如命名示例）使用的主题色。"""
    tokens = chrome_tokens(theme, accent or DEFAULT_ACCENT)
    return {
        "text": tokens["ink"],
        "muted": tokens["muted"],
        "faint": tokens["faint"],
        "accent": tokens["accent"],
        "error": tokens["error"],
        "panel": tokens["panel"],
        "line": tokens["line"],
        "ok": tokens["ok"],
        "warn": tokens["warn"],
        "bad": tokens["bad"],
    }


__all__ = [
    "load_stylesheet",
    "ui_colors",
    "chrome_tokens",
    "accent_tokens",
    "normalize_theme",
    "normalize_accent",
    "is_light_theme",
    "DEFAULT_THEME",
    "DEFAULT_ACCENT",
    "BASE_THEME_NAMES",
    "ACCENT_NAMES",
]

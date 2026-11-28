"""阅读器主题 token：八套色卡的唯一来源。

色值只在这里维护，配置里只保存 key；窗口 QSS 与 Web 阅读页共用同一份
palette，避免出现"工具条一套色、纸面另一套色"的黑边或白块。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


def mix(fg: str, bg: str, t: float) -> str:
    """把 fg 按比例 t 混入 bg，返回 #rrggbb。"""
    a = [int(fg[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(b[i] + (a[i] - b[i]) * t):02x}" for i in range(3))


@dataclass(frozen=True)
class ReaderPalette:
    """一套阅读器配色。canvas/panel 由公式推导，不手填第二套。"""

    key: str
    label: str
    page: str
    ink: str
    muted: str
    chrome: str
    canvas: str
    border: str
    accent: str
    panel: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


# 基础色卡：page/ink/muted/chrome/border/accent 来自设计稿；
# canvas 与 panel 在 _build() 中统一推导。
_BASE = (
    ("light", "纸白", "#fbfaf7", "#1f2328", "#8b9099", "#f3f1ec", "#ddd8cd", "#3f6fa8"),
    ("sepia", "米黄", "#f5ecd8", "#4a3b2a", "#9a8a6f", "#efe2c6", "#dccbaa", "#a8763e"),
    ("gray", "灰白", "#f2f3f4", "#23262b", "#8d9299", "#e8eaec", "#d4d7db", "#4a5563"),
    ("grass", "草绿", "#eef2e7", "#24301f", "#7d8a72", "#e3ead9", "#cbd6be", "#4e7d46"),
    ("cherry", "樱粉", "#fbeef2", "#45232c", "#a5808b", "#f6e0e7", "#e5c6d1", "#c05a78"),
    ("sky", "天青", "#eff5fb", "#1f2c3d", "#7d8fa3", "#e3edf8", "#c9d9eb", "#3d7bb5"),
    ("sunset", "日晖", "#fff7ef", "#43302a", "#a08678", "#fbeade", "#e8d2bd", "#d9764a"),
    ("dark", "夜读", "#23262b", "#d8dbe0", "#8b929c", "#1b1e22", "#33373d", "#7ba7e0"),
)

_DARK_KEYS = {"dark", "night"}


def _build() -> dict[str, ReaderPalette]:
    palettes: dict[str, ReaderPalette] = {}
    for key, label, page, ink, muted, chrome, border, accent in _BASE:
        canvas = (
            mix("#000000", page, 0.75)
            if key in _DARK_KEYS
            else mix(ink, page, 0.10)
        )
        palettes[key] = ReaderPalette(
            key=key,
            label=label,
            page=page,
            ink=ink,
            muted=muted,
            chrome=chrome,
            canvas=canvas,
            border=border,
            accent=accent,
            panel=mix(ink, page, 0.035),
        )
    return palettes


PALETTES: dict[str, ReaderPalette] = _build()
THEME_KEYS: tuple[str, ...] = tuple(PALETTES)

# 兼容旧配置：paper/night 是设计稿里的名字，内部仍沿用 light/dark。
_ALIASES = {"paper": "light", "night": "dark"}


def palette_for(
    key: str | None, mode: str | None = "auto", *, system_dark: bool = False
) -> ReaderPalette:
    """按 key 与深浅模式取色卡；未知或空值回落到纸白。

    mode=light 强制浅色（选到夜读时回落纸白），mode=dark 强制夜读，
    auto 跟随系统深浅，但用户显式选了夜读时保持夜读。
    """
    normalized = _ALIASES.get(str(key or "").strip(), str(key or "").strip())
    selected = PALETTES.get(normalized, PALETTES["light"])
    scheme = str(mode or "auto").strip().lower()
    if scheme == "dark":
        return PALETTES["dark"]
    if scheme == "light":
        return PALETTES["light"] if selected.key in _DARK_KEYS else selected
    if system_dark and selected.key not in _DARK_KEYS:
        return PALETTES["dark"]
    return selected


# ---- 高亮荧光笔 4 色（决策回复 §二）-------------------------------------
# 只存语义名（blue/amber/green/pink），不存 hex；浅色纸面直接用 hex，
# 夜间纸面自动压暗。换主题无需迁移数据。
HIGHLIGHT_COLORS: tuple[str, ...] = ("blue", "amber", "green", "pink")
DEFAULT_HIGHLIGHT = "blue"

HIGHLIGHT_LIGHT: dict[str, str] = {
    "blue": "#CFE3F3",
    "amber": "#F5D9A8",
    "green": "#D8E8C2",
    "pink": "#ECCFD8",
}
HIGHLIGHT_NIGHT: dict[str, str] = {
    "blue": "#2C4257",
    "amber": "#4A3B22",
    "green": "#31412A",
    "pink": "#45303A",
}

# 老库曾存的 hex → 语义名（不迁移数据，仅在读写时归一化）。
_HIGHLIGHT_LEGACY: dict[str, str] = {
    "#ffe08a": "amber",
    "#f2c14e": "amber",
    "#b7e1a1": "green",
    "#9cc39a": "green",
    "#d8e8c2": "green",
    "#a8d8f0": "blue",
    "#8fb3d9": "blue",
    "#cfe3f3": "blue",
    "#f5b7c4": "pink",
    "#d99c98": "pink",
    "#eccfd8": "pink",
    "#b6a4d9": "pink",
}


def normalize_highlight_name(value: object) -> str:
    """任意高亮颜色输入 → 语义名；无法识别回退默认蓝。"""
    if value is None:
        return DEFAULT_HIGHLIGHT
    text = str(value).strip().lower()
    if text in HIGHLIGHT_COLORS:
        return text
    return _HIGHLIGHT_LEGACY.get(text, DEFAULT_HIGHLIGHT)


def resolve_highlight_color(name: object, *, dark: bool) -> str:
    """语义名 → 当前纸面下的 hex；深色纸面用压暗后的色值。"""
    key = normalize_highlight_name(name)
    return (HIGHLIGHT_NIGHT if dark else HIGHLIGHT_LIGHT)[key]

"""卷号与系列识别（文档 7.3）。

对外主要函数：
- `extract_volume(text)`：返回卷号、原始写法与匹配区间；
- `strip_volume(text)`：去掉卷号后的书名主干；
- `title_key(text)`：用于系列归并的强归一字符串；
- `similar_title(a, b)`：书名主干相似度（0–100）。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

try:  # rapidfuzz 为文档指定依赖；缺失时退化为标准库
    from rapidfuzz import fuzz as _fuzz

    def _ratio(a: str, b: str) -> float:
        return float(_fuzz.token_set_ratio(a, b))

except Exception:  # pragma: no cover - 仅在依赖缺失时触发
    from difflib import SequenceMatcher

    def _ratio(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio() * 100


_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_ROMAN = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6,
    "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12,
}

CN_VOLUME = re.compile(r"第\s*([零〇一二三四五六七八九十百千0-9]+)\s*[部卷册集篇]")
CN_ROMAN_VOLUME = re.compile(
    r"(?i)第\s*(I{1,3}|IV|V|VI{0,3}|IX|X|XI|XII)\s*[部卷册集篇]"
)
CN_PREFIX_VOLUME = re.compile(r"(?:第\s*)?卷\s*([零〇一二三四五六七八九十百千0-9]+)(?:\s*卷)?")
EN_VOLUME = re.compile(r"(?i)(?:vol(?:ume)?|book|part)\s*[.:]?\s*([0-9]+)")
ROMAN_VOLUME = re.compile(
    r"(?i)(?:vol(?:ume)?|book)\s*[.:]?\s*(I{1,3}|IV|V|VI{0,3}|IX|X|XI|XII)\b"
)
CN_PAREN = re.compile(r"[（(]\s*([零〇一二三四五六七八九十百]+)\s*[）)]")
NUM_PAREN = re.compile(r"[（(]\s*([0-9]{1,2})\s*[）)]")
TRAIL_NUMBER = re.compile(r"[-_ ]\s*([0-9]{1,2})\s*$")
# 「三体3 死神永生」「三体2」这类中文书名后紧跟卷号的写法。
CJK_MID_NUMBER = re.compile(r"(?<=[\u4e00-\u9fff])([0-9]{1,2})(?=[\s_\-]|$)")


@dataclass(frozen=True)
class VolumeMatch:
    volume: int
    raw: str
    start: int
    end: int


def chinese_to_int(text: str) -> int | None:
    """中文数字转整数，支持 一…十九、二十一、一百二十三、〇/零。"""
    value = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    total = 0
    number = 0
    for char in value:
        if char in _CN_DIGITS:
            number = _CN_DIGITS[char]
        elif char in _CN_UNITS:
            unit = _CN_UNITS[char]
            total += (number or 1) * unit
            number = 0
        else:
            return None
    return total + number


def _match(text: str, pattern: re.Pattern[str], *, roman: bool = False,
           chinese: bool = False) -> VolumeMatch | None:
    found = pattern.search(text)
    if not found:
        return None
    token = found.group(1)
    if roman:
        volume = _ROMAN.get(token.upper())
    elif chinese:
        volume = chinese_to_int(token)
    else:
        volume = int(token)
    if not volume or volume <= 0:
        return None
    return VolumeMatch(volume, found.group(0), found.start(), found.end())


def _match_cjk_mid(text: str) -> VolumeMatch | None:
    """中文书名后的卷号；排除「从0到1」这类区间/数字表达。"""
    for found in CJK_MID_NUMBER.finditer(text):
        start = found.start(1)
        previous = text[start - 2] if start >= 2 else ""
        if previous.isdigit() or previous in "到至-~—":
            continue
        return VolumeMatch(int(found.group(1)), found.group(0), found.start(), found.end())
    return None


def extract_volume(text: str | None) -> VolumeMatch | None:
    """按文档顺序识别卷号；找不到返回 None。"""
    value = unicodedata.normalize("NFKC", str(text or ""))
    if not value:
        return None
    return (
        _match(value, CN_VOLUME, chinese=True)
        or _match(value, CN_ROMAN_VOLUME, roman=True)
        or _match(value, CN_PREFIX_VOLUME, chinese=True)
        or _match(value, EN_VOLUME)
        or _match(value, ROMAN_VOLUME, roman=True)
        or _match(value, CN_PAREN, chinese=True)
        or _match(value, NUM_PAREN)
        or _match(value, TRAIL_NUMBER)
        or _match_cjk_mid(value)
    )


def strip_volume(text: str | None) -> str:
    """去掉卷号片段并清理残留分隔符，得到书名主干。"""
    value = str(text or "")
    match = extract_volume(value)
    if match:
        value = f"{value[:match.start]}{value[match.end:]}"
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"[_\-–—·,，.。:：;；\s]+", " ", value)
    return value.strip(" _-·,，.。")


def title_key(text: str | None) -> str:
    """系列归一：去卷号、副标题括号、套装尾缀、空白并小写折叠。"""
    value = strip_volume(text)
    value = re.sub(r"[\[【（(][^\]】）)]*[\]】）)]", "", value)
    value = value.replace("《", "").replace("》", "")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"(?:全集|套装|合集|文集|丛书)+$", "", normalized)
    return "".join(char for char in normalized if char.isalnum())


def similar_title(left: str | None, right: str | None) -> float:
    a, b = title_key(left), title_key(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 100.0
    return _ratio(a, b)


def volume_text(volume: int | None, style: str = "第N卷") -> str:
    """把卷号格式化为展示文本；无卷号返回空串。"""
    if not volume:
        return ""
    return str(style or "第N卷").replace("N", str(int(volume)))

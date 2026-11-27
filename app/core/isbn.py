"""ISBN 工具：提取、归一化与校验（支持全角数字、连字符、10→13）。"""

from __future__ import annotations

import re

_FULLWIDTH = str.maketrans("０１２３４５６７８９Ｘｘ－　", "0123456789Xx- ")
_PREFIX = re.compile(r"(?i)isbn(?:-?1[03])?\s*[:：]?\s*")
_CANDIDATE = re.compile(
    r"(?<![0-9A-Za-z])(?:97[89](?:[-\s]?\d){10}|(?:\d[-\s]?){9}[\dXx])(?![0-9A-Za-z])"
)


def _clean(text: str) -> str:
    return str(text).translate(_FULLWIDTH)


def _check13(core: str) -> str:
    """core 为前 12 位，返回校验位。"""
    total = sum(
        (1 if index % 2 == 0 else 3) * int(digit)
        for index, digit in enumerate(core)
    )
    return str((10 - total % 10) % 10)


def _valid10(code: str) -> bool:
    if len(code) != 10 or not code[:9].isdigit():
        return False
    if code[9] not in "0123456789X":
        return False
    total = sum((10 - index) * int(digit) for index, digit in enumerate(code[:9]))
    total += 10 if code[9] == "X" else int(code[9])
    return total % 11 == 0


def _valid13(code: str) -> bool:
    if len(code) != 13 or not code.isdigit():
        return False
    return code[-1] == _check13(code[:12])


def normalize(isbn: str | None) -> str | None:
    """去掉前缀、连字符与空格；10 位转为 13 位；校验位不符返回 None。"""
    if isbn is None:
        return None
    text = _clean(isbn).strip()
    if not text:
        return None
    text = _PREFIX.sub("", text)
    code = re.sub(r"[^0-9Xx]", "", text).upper()
    if len(code) == 10:
        if not _valid10(code):
            return None
        core = "978" + code[:9]
        return core + _check13(core)
    if len(code) == 13:
        if not code.startswith(("978", "979")) or not _valid13(code):
            return None
        return code
    return None


def is_valid(isbn: str | None) -> bool:
    return normalize(isbn) is not None


def find_isbns(text: str) -> list[str]:
    """从任意文本中提取合法 ISBN，按出现顺序去重。"""
    if not text:
        return []
    cleaned = _clean(text)
    found: list[str] = []
    seen: set[str] = set()
    for match in _CANDIDATE.finditer(cleaned):
        normalized = normalize(match.group(0))
        if normalized and normalized not in seen:
            seen.add(normalized)
            found.append(normalized)
    return found

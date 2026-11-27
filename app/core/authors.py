"""作者规范化：原文姓名 → 标准中文名 + 国别。

优先级（文档 F6）：
1. 已锁定/已有的 `authors` 记录由调用方（AuthorService）优先处理；
2. 内置译名字典 `resources/author_zh.json`；
3. 中文本名直接使用；中国作者不加国别；
4. 未命中的外文姓名保留原文并标记 needs_confirm，绝不静默硬译。
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from . import countries

_RESOURCE = Path(__file__).with_name("resources") / "author_zh.json"
_COUNTRY_HINT = re.compile(r"[\[【（(]([^\]】）)]{1,6})[\]】）)]\s*$")
_COUNTRY_PREFIX = re.compile(r"^[\[【（(]([^\]】）)]{1,6})[\]】）)]\s*")
_TRAILING_LATIN = re.compile(
    r"^(.*[\u3400-\u9fff][^()（）]*?)\s*[（(]\s*([A-Za-z][A-Za-z.,，\-\s']*)\s*[）)]\s*$"
)
_HAN = re.compile(r"[\u3400-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")
_INITIAL = re.compile(r"^[A-Z]\.?$")


@dataclass
class AuthorInfo:
    name_zh: str
    name_orig: str = ""
    country: str = ""
    country_code: str = ""
    is_chinese: bool = False
    needs_confirm: bool = False
    matched: bool = False
    aliases: list[str] = field(default_factory=list)

    def as_fields(self) -> dict[str, Any]:
        """转为 authors 表字段。"""
        return {
            "name_zh": self.name_zh,
            "name_orig": self.name_orig or self.name_zh,
            "country": self.country or None,
            "country_code": self.country_code or None,
            "is_chinese": 1 if self.is_chinese else 0,
        }


def _canonical(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    return "".join(
        char for char in normalized.casefold() if char.isalnum() or _HAN.match(char)
    )


@lru_cache(maxsize=1)
def _dictionary() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """返回（别名键 → 条目, 中文名 → 条目）。"""
    try:
        raw = json.loads(_RESOURCE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    by_alias: dict[str, dict[str, Any]] = {}
    by_zh: dict[str, dict[str, Any]] = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not item.get("name_zh"):
            continue
        by_zh.setdefault(_canonical(item["name_zh"]), item)
        for alias in (item.get("name_zh"), item.get("name_orig"), *item.get("aliases", [])):
            key = _canonical(alias or "")
            if key:
                by_alias.setdefault(key, item)
    return by_alias, by_zh


def _split_country_hint(text: str) -> tuple[str, str]:
    """提取作者名前的 `[美]`、`(法)` 或末尾的 `【美国】`；仅当能识别为国别时才剥离。"""
    value = str(text or "").strip()
    match = _COUNTRY_HINT.search(value)
    if match:
        hint = match.group(1).strip()
        if countries.resolve_country(hint):
            return value[: match.start()].strip(), hint
    match = _COUNTRY_PREFIX.match(value)
    if match:
        hint = match.group(1).strip()
        if countries.resolve_country(hint):
            return value[match.end():].strip(), hint
    return value, ""


def _split_author_list(text: str) -> list[str]:
    """按分隔符拆分作者，跳过括号内的逗号（如 `(Ellis, Albert)`）。"""
    parts: list[str] = []
    buffer: list[str] = []
    depth = 0
    for index, char in enumerate(text):
        if char in "([【（":
            depth += 1
        elif char in ")]】）" and depth:
            depth -= 1
        if depth == 0 and char in ";；、":
            parts.append("".join(buffer))
            buffer = []
            continue
        if depth == 0 and char == ",":
            rest = text[index + 1:].lstrip()
            if rest and (rest[0].isupper() or "\u3400" <= rest[0] <= "\u9fff"):
                parts.append("".join(buffer))
                buffer = []
                continue
        buffer.append(char)
    parts.append("".join(buffer))
    return [part.strip() for part in parts if part.strip()]


def split_authors(raw: str | Iterable[str] | None) -> list[str]:
    """拆分作者串：兼容 `、 ; ；` 与 "姓, 名" 结构。"""
    if raw is None:
        return []
    if not isinstance(raw, str):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw).strip()
    if not text:
        return []
    if "," in text:
        left, right = [part.strip() for part in text.rsplit(",", 1)]
        if left and right and _looks_like_initials(right):
            return [f"{right} {left}"]
    return _split_author_list(text) or [text]


def _looks_like_initials(text: str) -> bool:
    tokens = [token for token in re.split(r"[\s.]+", text) if token]
    return bool(tokens) and all(
        re.fullmatch(r"[A-Za-z]+\.?", token) for token in tokens
    )


def _is_han_text(text: str) -> bool:
    return bool(text) and not _LATIN.search(text) and bool(_HAN.search(text))


def parse_author(raw: str | None, country_hint: str | None = None) -> AuthorInfo:
    """规范化单个作者；空输入返回空 AuthorInfo。"""
    text = unicodedata.normalize("NFKC", str(raw or "")).strip()
    text, inline_hint = _split_country_hint(text)
    hint = (country_hint or inline_hint or "").strip()
    if not text:
        return AuthorInfo(name_zh="", needs_confirm=True)

    by_alias, by_zh = _dictionary()
    entry = by_alias.get(_canonical(text)) or by_zh.get(_canonical(text))
    hint_code = countries.resolve_country(hint) if hint else None

    if entry is not None:
        code = str(entry.get("country") or "").upper() or hint_code or ""
        return AuthorInfo(
            name_zh=str(entry["name_zh"]),
            name_orig=str(entry.get("name_orig") or text),
            country=countries.country_zh(code),
            country_code=code,
            is_chinese=countries.is_china(code),
            needs_confirm=False,
            matched=True,
            aliases=list(entry.get("aliases") or []),
        )

    if _is_han_text(text) and "·" not in text and "•" not in text:
        code = hint_code or ""
        is_chinese = not code or countries.is_china(code)
        return AuthorInfo(
            name_zh=text,
            name_orig=text,
            country=countries.country_zh(code),
            country_code=code,
            is_chinese=is_chinese,
            needs_confirm=False,
            matched=False,
        )

    latin = _TRAILING_LATIN.match(text)
    if latin:
        main_name = latin.group(1).strip()
        original = latin.group(2).strip()
        code = hint_code or ""
        return AuthorInfo(
            name_zh=main_name,
            name_orig=original,
            country=countries.country_zh(code),
            country_code=code,
            is_chinese=False,
            needs_confirm=not bool(code),
            matched=False,
        )

    code = hint_code or ""
    return AuthorInfo(
        name_zh=text,
        name_orig=text,
        country=countries.country_zh(code),
        country_code=code,
        is_chinese=False,
        needs_confirm=not bool(code),
        matched=False,
    )


def normalize_author(raw: str | None, country_hint: str | None = None) -> AuthorInfo:
    """规范化作者串；多作者时只取第一位（目录与文件名只用一个作者名）。"""
    authors = split_authors(raw)
    return parse_author(authors[0] if authors else "", country_hint)

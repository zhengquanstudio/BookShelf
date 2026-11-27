"""国别字典：把各种写法的国家名归一为 ISO 代码、标准中文名与短名。

数据文件 `resources/countries.json` 由用户可扩展；本模块只读，不修改。
"""

from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

_RESOURCE = Path(__file__).with_name("resources") / "countries.json"


@lru_cache(maxsize=1)
def _data() -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(_RESOURCE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


@lru_cache(maxsize=1)
def _lookup() -> dict[str, str]:
    table: dict[str, str] = {}
    for code, item in _data().items():
        for name in (code, item.get("zh", ""), item.get("short", ""), *item.get("names", [])):
            key = _key(name)
            if key:
                table.setdefault(key, code)
    return table


def _key(text: str) -> str:
    """国家名归一：去空格、标点、大小写。"""
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    return "".join(
        char for char in normalized.casefold() if char.isalnum()
    )


def resolve_country(value: str | None) -> str | None:
    """返回 ISO 国家代码；无法识别返回 None。"""
    key = _key(value or "")
    return _lookup().get(key) if key else None


def country_zh(code: str | None) -> str:
    item = _data().get(str(code or ""))
    return str(item.get("zh")) if item else ""


def country_short(code: str | None) -> str:
    item = _data().get(str(code or ""))
    return str(item.get("short")) if item else ""


def render_country(code: str | None, style: str = "long") -> str:
    """按 long/short 输出国别中文；未知返回空串。"""
    if not code:
        return ""
    return country_short(code) if style == "short" else country_zh(code)


def is_china(code: str | None) -> bool:
    return str(code or "").upper() == "CN"

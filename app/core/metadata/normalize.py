"""元数据统一结构：各格式解析结果都归一到固定键。"""

from __future__ import annotations

from typing import Any

KEYS = (
    "title",
    "subtitle",
    "authors",
    "isbn",
    "publisher",
    "date",
    "language",
    "series",
    "series_index",
    "description",
    "doi",
    "cover_bytes",
    "page_count",
    "drm",
    "ok",
    "reason",
    "scanned",
)


def empty_metadata() -> dict[str, Any]:
    return {
        "title": "",
        "subtitle": "",
        "authors": [],
        "isbn": "",
        "publisher": "",
        "date": "",
        "language": "",
        "series": "",
        "series_index": "",
        "description": "",
        "doi": "",
        "cover_bytes": b"",
        "page_count": None,
        "drm": False,
        "ok": False,
        "reason": "",
        "scanned": False,
    }


def finalize(
    data: dict[str, Any] | None,
    *,
    ok: bool = True,
    reason: str = "",
) -> dict[str, Any]:
    """补齐固定键并清理空白；保留解析器给出的 ok/reason。"""
    result = empty_metadata()
    payload = dict(data or {})
    result.update(payload)
    for key in ("title", "subtitle", "publisher", "date", "language", "series",
                "series_index", "description", "isbn", "doi"):
        value = result.get(key)
        result[key] = str(value).strip() if value is not None else ""
    authors = result.get("authors") or []
    if isinstance(authors, str):
        authors = [part.strip() for part in authors.replace("；", ";").split(";")]
    result["authors"] = [str(item).strip() for item in authors if str(item).strip()]
    result["cover_bytes"] = result.get("cover_bytes") or b""
    result["drm"] = bool(result.get("drm"))
    result["scanned"] = bool(result.get("scanned"))
    result["ok"] = bool(payload.get("ok", ok))
    result["reason"] = str(payload.get("reason") or reason or "")
    return result

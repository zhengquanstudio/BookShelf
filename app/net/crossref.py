"""Crossref 检索源：外文与学术图书的结构化元数据（无封面）。

查询走 `query.bibliographic`，ISBN 优先；返回 title/author/publisher/issued/ISBN。
DOI 不做单独接口，扫描阶段抽到的 DOI 也走这里回查。
"""

from __future__ import annotations

from typing import Any

from ..core import isbn as isbn_tools
from .client import HttpClient

BASE = "https://api.crossref.org/works"


def _date(value: Any) -> str:
    parts = ((value or {}).get("date-parts") or [[]])[0]
    return "-".join(str(part) for part in parts if part)


def _authors(items: Any) -> list[str]:
    names: list[str] = []
    for entry in items or []:
        if not isinstance(entry, dict):
            continue
        given = str(entry.get("given") or "").strip()
        family = str(entry.get("family") or "").strip()
        name = " ".join(part for part in (given, family) if part) or str(
            entry.get("name") or ""
        ).strip()
        if name:
            names.append(name)
    return names


def _pick_isbn(values: Any) -> str:
    if isinstance(values, str):
        values = [values]
    normalized = [isbn_tools.normalize(str(item)) for item in (values or [])]
    for candidate in normalized:
        if candidate and candidate.startswith("978"):
            return candidate
    for candidate in normalized:
        if candidate:
            return candidate
    return ""


def _map(item: dict[str, Any]) -> dict[str, Any]:
    titles = item.get("title") or []
    title = str(titles[0]).strip() if titles else ""
    return {
        "source": "crossref",
        "title": title,
        "subtitle": str((item.get("subtitle") or [""])[0] or "").strip(),
        "authors": _authors(item.get("author")),
        "isbn": _pick_isbn(item.get("ISBN")),
        "publisher": str(item.get("publisher") or "").strip(),
        "date": _date(item.get("issued"))[:32],
        "language": str(item.get("language") or "").strip(),
        "series": "",
        "series_index": "",
        "description": "",
        "cover_url": "",
        "raw": item,
    }


class CrossrefSource:
    name = "crossref"
    label = "Crossref"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def lookup(
        self,
        *,
        isbn: str | None = None,
        title: str | None = None,
        authors: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        query = isbn_tools.normalize(isbn or "") or " ".join(
            part for part in (str(title or "").strip(), (authors or [""])[0]) if part
        ).strip()
        if not query:
            return []
        payload = self.client.get_json(
            BASE,
            source=self.name,
            params={"query.bibliographic": query, "rows": 3},
        )
        items = ((payload or {}).get("message") or {}).get("items") if isinstance(payload, dict) else None
        return [_map(item) for item in (items or []) if isinstance(item, dict)]

    def by_isbn(self, isbn: str) -> list[dict[str, Any]]:
        return self.lookup(isbn=isbn)

    def search(self, query: str) -> list[dict[str, Any]]:
        return self.lookup(title=query)

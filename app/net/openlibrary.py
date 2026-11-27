"""OpenLibrary 检索源（文档 8.1/8.3）。"""

from __future__ import annotations

from typing import Any

from ..core import isbn as isbn_tools
from .client import HttpClient, NetworkError

BASE = "https://openlibrary.org"
FIELDS = "key,title,subtitle,author_name,first_publish_year,isbn,publisher,language,cover_i"


class OpenLibrarySource:
    name = "openlibrary"
    label = "OpenLibrary"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def by_isbn(self, isbn: str) -> list[dict[str, Any]]:
        normalized = isbn_tools.normalize(isbn)
        if not normalized:
            return []
        return self._search(f"isbn:{normalized}", limit=5)

    def search(self, query: str) -> list[dict[str, Any]]:
        if not (query or "").strip():
            return []
        return self._search(query.strip(), limit=5)

    def _search(self, query: str, limit: int) -> list[dict[str, Any]]:
        payload = self.client.get_json(
            f"{BASE}/search.json",
            source=self.name,
            params={"q": query, "fields": FIELDS, "limit": limit},
        )
        docs = payload.get("docs") if isinstance(payload, dict) else None
        return [self._map(doc) for doc in (docs or []) if isinstance(doc, dict)]

    @staticmethod
    def _map(doc: dict[str, Any]) -> dict[str, Any]:
        cover_id = doc.get("cover_i")
        isbn_value = _pick_isbn(doc.get("isbn") or [])
        languages = doc.get("language") or []
        publishers = doc.get("publisher") or []
        series_values = doc.get("series") or []
        return {
            "source": "openlibrary",
            "title": str(doc.get("title") or "").strip(),
            "subtitle": str(doc.get("subtitle") or "").strip(),
            "authors": [str(item).strip() for item in (doc.get("author_name") or []) if str(item).strip()],
            "isbn": isbn_value,
            "publisher": str(publishers[0]).strip() if publishers else "",
            "date": str(doc.get("first_publish_year") or "").strip(),
            "language": str(languages[0]).strip() if languages else "",
            "series": str(series_values[0]).strip() if series_values else "",
            "series_index": "",
            "description": "",
            "cover_url": f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if cover_id else "",
            "raw": doc,
        }


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


__all__ = ["OpenLibrarySource", "NetworkError"]

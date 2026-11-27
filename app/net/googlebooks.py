"""Google Books 检索源（文档 8.1/8.3）。"""

from __future__ import annotations

from typing import Any

from ..core import isbn as isbn_tools
from .client import HttpClient

BASE = "https://www.googleapis.com/books/v1/volumes"


class GoogleBooksSource:
    name = "googlebooks"
    label = "Google Books"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def by_isbn(self, isbn: str) -> list[dict[str, Any]]:
        normalized = isbn_tools.normalize(isbn)
        if not normalized:
            return []
        return self._query(f"isbn:{normalized}")

    def search(self, query: str) -> list[dict[str, Any]]:
        if not (query or "").strip():
            return []
        return self._query(query.strip())

    def _query(self, query: str) -> list[dict[str, Any]]:
        payload = self.client.get_json(
            BASE,
            source=self.name,
            params={"q": query, "maxResults": 5, "printType": "books"},
        )
        items = payload.get("items") if isinstance(payload, dict) else None
        return [self._map(item) for item in (items or []) if isinstance(item, dict)]

    @staticmethod
    def _map(item: dict[str, Any]) -> dict[str, Any]:
        info = item.get("volumeInfo") or {}
        identifiers = info.get("industryIdentifiers") or []
        isbn_value = ""
        for wanted in ("ISBN_13", "ISBN_10"):
            for entry in identifiers:
                if entry.get("type") == wanted:
                    isbn_value = isbn_tools.normalize(str(entry.get("identifier") or "")) or ""
                    if isbn_value:
                        break
            if isbn_value:
                break
        image = (info.get("imageLinks") or {}).get("thumbnail") or ""
        return {
            "source": "googlebooks",
            "title": str(info.get("title") or "").strip(),
            "subtitle": str(info.get("subtitle") or "").strip(),
            "authors": [str(name).strip() for name in (info.get("authors") or []) if str(name).strip()],
            "isbn": isbn_value,
            "publisher": str(info.get("publisher") or "").strip(),
            "date": str(info.get("publishedDate") or "").strip(),
            "language": str(info.get("language") or "").strip(),
            "series": "",
            "series_index": "",
            "description": str(info.get("description") or "").strip(),
            "cover_url": str(image).replace("http://", "https://"),
            "raw": item,
        }

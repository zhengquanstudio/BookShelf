"""孔夫子旧书网检索源：中文旧书/绝版书补充来源。

搜索结果页为服务端渲染卡片，按卡片块解析标题/作者/出版社/出版时间；
只填这四个字段，不做详情页二次请求。
"""

from __future__ import annotations

import re
from typing import Any

from ..core import isbn as isbn_tools
from .client import HttpClient

BASE = "https://search.kongfz.com/product/"
_REFERER = {"Referer": "https://www.kongfz.com/"}
_TAG = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"<br\s*/?>", re.I)
_ANCHOR = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_LABEL = re.compile(
    r"(作者|出版社|出版时间|出版年|出版日期|ISBN)\s*[:：]\s*([^<\n|/]{1,80})"
)
_SKIP_TITLE = ("孔夫子旧书网", "登录", "注册", "更多", "下一页", "上一页")


def _clean(html: str) -> str:
    text = _BREAK.sub("\n", html or "")
    text = _TAG.sub("", text)
    return re.sub(r"\s+", " ", text.replace("&nbsp;", " ")).strip()


def _blocks(html: str) -> list[str]:
    """按搜索卡片切块；`item-row-detail` 之类的子类不能当作新卡片。"""
    parts = re.split(
        r'(?=<div[^>]+class="[^"]*item-row(?=[\s"]))',
        html or "",
        flags=re.I,
    )
    return [part for part in parts if part.strip()]


def _split_authors(value: str) -> list[str]:
    names = [
        part.strip()
        for part in re.split(r"\s*[/、]\s*", value or "")
        if part.strip()
    ]
    return names


def _parse_block(block: str) -> dict[str, Any] | None:
    text = _clean(block)
    fields: dict[str, str] = {}
    for match in _LABEL.finditer(text):
        fields.setdefault(match.group(1), match.group(2).strip(" ，,"))

    title = ""
    for _href, inner in _ANCHOR.findall(block):
        candidate = _clean(inner)
        if not (2 <= len(candidate) <= 80):
            continue
        if any(token in candidate for token in _SKIP_TITLE):
            continue
        if len(candidate) > len(title):
            title = candidate
    if not title or any(token in title for token in _SKIP_TITLE):
        return None

    isbn_value = isbn_tools.normalize(fields.get("ISBN", "")) or ""
    if not isbn_value:
        found = isbn_tools.find_isbns(text)
        isbn_value = found[0] if found else ""
    return {
        "source": "kongfz",
        "title": title,
        "subtitle": "",
        "authors": _split_authors(fields.get("作者", "")),
        "isbn": isbn_value,
        "publisher": fields.get("出版社", ""),
        "date": (fields.get("出版时间") or fields.get("出版年") or fields.get("出版日期") or "")[:32],
        "language": "",
        "series": "",
        "series_index": "",
        "description": "",
        "cover_url": "",
    }


def parse_search(html: str) -> list[dict[str, Any]]:
    """解析搜索结果页；无卡片结构时返回空列表。"""
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block in _blocks(html):
        item = _parse_block(block)
        if item is None:
            continue
        key = item["title"].casefold()
        if key in seen:
            continue
        seen.add(key)
        results.append(item)
        if len(results) >= 5:
            break
    return results


class KongfzSource:
    name = "kongfz"
    label = "孔夫子旧书网"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def lookup(
        self,
        *,
        isbn: str | None = None,
        title: str | None = None,
        authors: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        keyword = isbn_tools.normalize(isbn or "") or str(title or "").strip()
        if not keyword:
            return []
        html = self.client.get_text(
            BASE,
            source=self.name,
            params={"keyword": keyword},
            headers=_REFERER,
            ua="browser",
        )
        return parse_search(html)

    def by_isbn(self, isbn: str) -> list[dict[str, Any]]:
        return self.lookup(isbn=isbn)

    def search(self, query: str) -> list[dict[str, Any]]:
        return self.lookup(title=query)

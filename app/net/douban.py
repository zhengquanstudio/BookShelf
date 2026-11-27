"""豆瓣读书检索源（网页抓取，无需 API key）。

- ISBN 直达：`/isbn/{isbn}/` 会 302 到具体书目页，必须跟随后强制校验页面 ISBN，
  不等就返回空列表（假 ISBN 会乱跳）。
- 书名检索：`/j/subject_suggest` 拿候选 id，再逐个抓详情页（客户端已按源限速）。
- 只返回标题/作者/出版社/出版年/ISBN/封面，不展开简介。
"""

from __future__ import annotations

import re
from typing import Any

from ..core import isbn as isbn_tools
from .client import HttpClient

BASE = "https://book.douban.com"
_REFERER = {"Referer": "https://book.douban.com/"}
_TAG = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"<br\s*/?>", re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_MAINPIC = re.compile(
    r'<div[^>]+id="mainpic"[^>]*>.*?<img[^>]+src="([^"]+)"', re.I | re.S
)
_INFO = re.compile(r'<div[^>]+id="info"[^>]*>(.*?)</div>', re.I | re.S)
_FIELD = re.compile(
    r"(作者|译者|出版社|出版年|出版日期|页数|定价|装帧|ISBN|副标题|原作名|丛书)\s*[:：]\s*(.+)"
)
_AUTHOR_SUFFIX = re.compile(r"\s*(?:著|编著|主编|编|译|注|校注|校|等)\s*$")
_TITLE_SUFFIX = re.compile(r"\s*(?:[（(]豆瓣[）)]|[-–—]\s*图书.*)$")


def _clean_text(html: str) -> str:
    text = _BREAK.sub("\n", html or "")
    text = _TAG.sub("", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"')
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _split_authors(value: str) -> list[str]:
    names: list[str] = []
    for part in re.split(r"\s*/\s*", value or ""):
        name = _AUTHOR_SUFFIX.sub("", part.strip())
        name = name.strip(" :：")
        if name:
            names.append(name)
    return names


def _parse_detail(html: str, *, requested_isbn: str = "") -> dict[str, Any] | None:
    """解析详情页；请求 ISBN 与页面 ISBN 不一致时返回 None。"""
    if not html or "页面不存在" in html or "检测到有异常请求" in html:
        return None
    match = _TITLE.search(html)
    title = _clean_text(match.group(1)) if match else ""
    title = _TITLE_SUFFIX.sub("", title).strip()
    if not title or title in {"豆瓣", "豆瓣读书"}:
        return None

    info_match = _INFO.search(html)
    info_text = _clean_text(info_match.group(1)) if info_match else _clean_text(html)
    fields: dict[str, str] = {}
    for line in info_text.splitlines():
        found = _FIELD.match(line.strip())
        if found and found.group(1) not in fields:
            fields[found.group(1)] = found.group(2).strip()

    page_isbns = isbn_tools.find_isbns(info_text)
    if requested_isbn:
        normalized = isbn_tools.normalize(requested_isbn)
        if not normalized or normalized not in page_isbns:
            return None

    isbn_value = isbn_tools.normalize(fields.get("ISBN", "")) or (
        page_isbns[0] if page_isbns else ""
    )
    date = fields.get("出版年") or fields.get("出版日期") or ""
    cover = ""
    pic = _MAINPIC.search(html)
    if pic:
        cover = pic.group(1).strip().replace("http://", "https://")
    return {
        "source": "douban",
        "title": title,
        "subtitle": fields.get("副标题", ""),
        "authors": _split_authors(fields.get("作者", "")),
        "isbn": isbn_value,
        "publisher": fields.get("出版社", ""),
        "date": date[:32],
        "language": "",
        "series": fields.get("丛书", ""),
        "series_index": "",
        "description": "",
        "cover_url": cover,
    }


class DoubanSource:
    name = "douban"
    label = "豆瓣读书"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def lookup(
        self,
        *,
        isbn: str | None = None,
        title: str | None = None,
        authors: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        normalized = isbn_tools.normalize(isbn or "")
        if normalized:
            items = self._by_isbn(normalized)
            if items:
                return items
        keyword = str(title or "").strip()
        if not keyword:
            return []
        return self._by_title(keyword)

    def by_isbn(self, isbn: str) -> list[dict[str, Any]]:
        normalized = isbn_tools.normalize(isbn or "")
        return self._by_isbn(normalized) if normalized else []

    def search(self, query: str) -> list[dict[str, Any]]:
        return self._by_title(str(query or "").strip())

    def _by_isbn(self, isbn: str) -> list[dict[str, Any]]:
        html = self.client.get_text(
            f"{BASE}/isbn/{isbn}/",
            source=self.name,
            headers=_REFERER,
            allow_redirects=True,
            ua="browser",
        )
        detail = _parse_detail(html, requested_isbn=isbn)
        return [detail] if detail else []

    def _by_title(self, title: str) -> list[dict[str, Any]]:
        suggestions = self.client.get_json(
            f"{BASE}/j/subject_suggest",
            source=self.name,
            params={"q": title},
            headers=_REFERER,
            ua="browser",
        )
        if not isinstance(suggestions, list):
            return []
        results: list[dict[str, Any]] = []
        for entry in suggestions[:5]:
            if not isinstance(entry, dict):
                continue
            subject_id = str(entry.get("id") or "").strip()
            detail: dict[str, Any] | None = None
            if subject_id.isdigit():
                try:
                    html = self.client.get_text(
                        f"{BASE}/subject/{subject_id}/",
                        source=self.name,
                        headers=_REFERER,
                        ua="browser",
                    )
                    detail = _parse_detail(html)
                except Exception:  # 单个详情失败不影响其余候选
                    detail = None
            if detail is None:
                detail = {
                    "source": self.name,
                    "title": str(entry.get("title") or "").strip(),
                    "subtitle": "",
                    "authors": _split_authors(str(entry.get("author_name") or "")),
                    "isbn": "",
                    "publisher": "",
                    "date": str(entry.get("year") or "")[:32],
                    "language": "",
                    "series": "",
                    "series_index": "",
                    "description": "",
                    "cover_url": str(entry.get("pic") or "").replace("http://", "https://"),
                }
            if detail.get("title"):
                results.append(detail)
        return results

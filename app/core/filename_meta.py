"""L0 文件名解析：零成本拿到书名/作者/年份/卷号/ISBN 猜测（规范 §2、§7 N5）。

只做纯文本推断，不读文件、不联网。调用方必须先跑本层，再用内嵌元数据覆盖，
最后才交给联网多源。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from . import isbn as isbn_tools
from . import series

_NOISE = (
    re.compile(
        r"[\[【(（]\s*(?:z-?lib(?:rary)?(?:\.org)?|libgen|epub|mobi|azw3|pdf|txt|"
        r"ocr|扫描版|高清版|校对版|精校版|完整版)\s*[\]】)）]",
        re.I,
    ),
    re.compile(r"(?<![A-Za-z])(?:z-?lib(?:rary)?(?:\.org)?|libgen)(?![A-Za-z])", re.I),
    re.compile(r"(?<![A-Za-z])(?:ocr|scanned|scan)(?![A-Za-z])", re.I),
    re.compile(r"(?<![A-Za-z])v\d+(?:\.\d+)*(?![A-Za-z])", re.I),
    re.compile(r"(?i)[._-](?:epub|mobi|azw3|pdf|txt)$"),
    re.compile(r"扫描版|高清版|校对版|精校版"),
)
_YEAR_GROUP = re.compile(r"[（(\[]\s*((?:19|20)\d{2})(?:[-/.]\d{1,2})?(?:[-/.]\d{1,2})?\s*[）)\]]")
_YEAR_ANY = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_BOOK_MARK = re.compile(r"《([^》]{1,80})》")
_BRACKET_AUTHOR = re.compile(r"^[\[【]([^\]】]{1,30})[\]】]\s*(.+)$")
_COUNTRY_PREFIX = re.compile(r"^[\[【（(][^\]】）)]{1,6}[\]】）)]")
_SEPARATORS = re.compile(r"\s+[-–—]\s+|\s*_\s*")
_PUBLISHER_HINT = re.compile(r"(?:出版社|书局|书店|出版公司|出版集团)")
_INVALID_AUTHOR = re.compile(r"^(?:第\s*[0-9一二三四五六七八九十百]+\s*[卷册部集]|unknown|未知)$", re.I)


def _strip_noise(text: str) -> str:
    value = text
    for pattern in _NOISE:
        value = pattern.sub(" ", value)
    # 连续分隔符归一：含连字符的统一成 " - "，纯下划线保留为分段符。
    value = re.sub(
        r"[_\-–—]{2,}",
        lambda match: " - " if any(ch in match.group(0) for ch in "-–—") else "_",
        value,
    )
    value = re.sub(r"\s{2,}", " ", value)
    return value.strip(" _-·,，。;；")


def _strip_isbn(text: str, isbn: str) -> str:
    if not isbn:
        return text
    compact = re.sub(r"[^0-9Xx]", "", text).upper()
    if isbn.upper() not in compact:
        return text
    # 去掉 ISBN 本体（允许中间夹连字符/空格）及其常见前缀，避免参与书名判断。
    flex = r"[-\s]?".join(re.escape(char) for char in isbn)
    value = re.sub(flex, " ", text, flags=re.I)
    return re.sub(r"(?i)isbn(?:-?1[03])?\s*[:：]?\s*", " ", value)


def _clean_author(value: str) -> str:
    name = re.sub(r"\s+", " ", value or "").strip(" _-·,，。;；")
    return name


def parse_name(stem: str) -> dict[str, Any]:
    """从文件名主干解析元数据猜测；无法判断的字段留空。"""
    result: dict[str, Any] = {
        "title": "",
        "authors": [],
        "year": "",
        "series": "",
        "series_index": "",
        "isbn": "",
        "publisher": "",
    }
    original = unicodedata.normalize("NFKC", str(stem or "")).strip()
    if not original:
        return result

    found_isbns = isbn_tools.find_isbns(original)
    if found_isbns:
        result["isbn"] = found_isbns[0]

    text = _strip_noise(original)
    text = _strip_isbn(text, result["isbn"])

    year_match = _YEAR_GROUP.search(text)
    if year_match:
        result["year"] = year_match.group(1)
        text = f"{text[:year_match.start()]} {text[year_match.end():]}"
    else:
        loose = _YEAR_ANY.search(text)
        if loose:
            result["year"] = loose.group(1)
            text = f"{text[:loose.start()]} {text[loose.end():]}"
    text = _strip_noise(text)

    volume = series.extract_volume(text)
    if volume:
        result["series_index"] = str(volume.volume)

    author = ""
    title = ""
    publisher = ""
    mark = _BOOK_MARK.search(text)
    if mark:
        title = mark.group(1).strip()
        author = _clean_author(f"{text[:mark.start()]} {text[mark.end():]}")
    else:
        parts = [part.strip() for part in _SEPARATORS.split(text) if part.strip()]
        parts = [part for part in parts if part and not _INVALID_AUTHOR.match(part)]
        if len(parts) >= 2:
            author = parts[0]
            title = parts[1]
            for extra in parts[2:]:
                if _PUBLISHER_HINT.search(extra):
                    publisher = extra
                    break
        elif len(parts) == 1:
            bracketed = _BRACKET_AUTHOR.match(parts[0])
            if bracketed and _looks_like_author(bracketed.group(1)):
                author = bracketed.group(1).strip()
                title = bracketed.group(2).strip()
            else:
                title = parts[0]
        else:
            title = text

    if author and not _looks_like_author(author):
        # 首段不像作者时把它并回书名，避免把书名误当作者。
        title = f"{author} {title}".strip()
        author = ""

    result["title"] = _clean_author(title)
    result["authors"] = [author] if author else []
    result["publisher"] = publisher
    return result


def _looks_like_author(value: str) -> bool:
    text = (value or "").strip()
    if not text or len(text) > 40:
        return False
    if _COUNTRY_PREFIX.match(text):
        return True
    if _PUBLISHER_HINT.search(text) or "第" in text:
        return False
    # 含明显书名符号或副标题分隔时不像作者。
    if any(mark in text for mark in ("《", "》", "：", ":")):
        return False
    return True

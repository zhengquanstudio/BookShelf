"""PDF 内嵌元数据：pypdf 读取文档信息，必要时从前 3 页文本启发式提取。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ...errors import ExtractError
from ..isbn import find_isbns, normalize
from .normalize import finalize

_DATE = re.compile(r"D:(\d{4})(\d{2})?(\d{2})?")
_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
_TITLE_NOISE = ("isbn", "目录", "版权", "http", "www.")


def _outline_title(reader) -> str:
    """取 PDF 书签第一层的第一个标题；中文排版下比正文第一行更可靠。"""
    def walk(items) -> str:
        for node in items or []:
            if isinstance(node, list):
                found = walk(node)
                if found:
                    return found
                continue
            title = str(getattr(node, "title", "") or "").strip()
            if not title and isinstance(node, dict):
                title = str(node.get("/Title") or "").strip()
            if title:
                return title
        return ""

    try:
        return walk(reader.outline)
    except Exception:  # 书签损坏不影响其余字段
        return ""


def _pdf_date(value: str) -> str:
    match = _DATE.search(value or "")
    if not match:
        return str(value or "")[:32]
    year, month, day = match.groups()
    return "-".join(part for part in (year, month, day) if part)


def _first_page_text(reader) -> str:
    chunks: list[str] = []
    for page in reader.pages[:3]:
        try:
            text = page.extract_text() or ""
        except Exception:  # 单页文本层异常不影响其余页面
            continue
        if text:
            chunks.append(text)
    return "\n".join(chunks)


def _guess_title(text: str) -> str:
    for line in text.splitlines():
        value = line.strip()
        if not (2 <= len(value) <= 80):
            continue
        lowered = value.lower()
        if any(token in lowered for token in _TITLE_NOISE):
            continue
        if value.isdigit():
            continue
        return value
    return ""


def extract(path: Path) -> dict[str, Any]:
    """读取 PDF；加密文档标记 DRM，无文本层标记疑似扫描件。"""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # 依赖缺失时明确报告，而不是静默失败
        raise ExtractError("缺少 pypdf 依赖") from exc

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        return finalize({}, ok=False, reason=f"PDF 解析失败：{exc}")

    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception:
            pass
        if getattr(reader, "is_encrypted", False):
            return finalize(
                {"drm": True, "title": path.stem},
                ok=True,
                reason="PDF 已加密，无法读取正文",
            )

    info = {}
    try:
        info = reader.metadata or {}
    except Exception:
        info = {}

    def meta(key: str) -> str:
        try:
            value = info.get(key, "")  # type: ignore[union-attr]
        except Exception:
            return ""
        return str(value or "").strip()

    title = meta("/Title")
    author = meta("/Author")
    subject = meta("/Subject")
    text = ""
    scanned = False
    try:
        text = _first_page_text(reader)
        scanned = len(reader.pages) > 0 and len(text.strip()) < 20
    except Exception:
        scanned = False

    isbn = normalize(meta("/ISBN")) or ""
    if not isbn:
        for candidate in find_isbns(" ".join((title, subject, text[:4000]))):
            isbn = candidate
            break
    if not title:
        title = _outline_title(reader)
    if not title:
        title = _guess_title(text)

    doi_match = _DOI.search(" ".join((subject, text[:4000])))
    doi = doi_match.group(0).rstrip(".,;") if doi_match else ""

    authors = [author] if author else []
    result = {
        "title": title,
        "authors": authors,
        "isbn": isbn,
        "doi": doi,
        "publisher": meta("/Publisher"),
        "date": _pdf_date(meta("/CreationDate")),
        "language": meta("/Language"),
        "description": subject,
        "page_count": len(reader.pages),
        "scanned": scanned,
    }
    return finalize(result, ok=True)

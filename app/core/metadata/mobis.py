"""MOBI / AZW3 内嵌元数据：解析 PalmDB、PalmDOC、MOBI 与 EXTH。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..isbn import normalize
from .normalize import finalize

_EXTH_AUTHOR = 100
_EXTH_PUBLISHER = 101
_EXTH_DESCRIPTION = 103
_EXTH_ISBN = 104
_EXTH_DATE = 106
_EXTH_LANGUAGE = 524
_EXTH_TITLE = 503


def _decode(raw: bytes, encoding: str) -> str:
    for codec in (encoding, "utf-8", "gb18030", "cp1252"):
        if not codec:
            continue
        try:
            return raw.decode(codec).strip()
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "ignore").strip()


def _exth_records(data: bytes, start: int, count: int) -> dict[int, list[bytes]]:
    records: dict[int, list[bytes]] = {}
    position = start + 12
    for _ in range(max(0, count)):
        if position + 8 > len(data):
            break
        kind = int.from_bytes(data[position : position + 4], "big")
        length = int.from_bytes(data[position + 4 : position + 8], "big")
        if length < 8 or position + length > len(data):
            break
        records.setdefault(kind, []).append(data[position + 8 : position + length])
        position += length
    return records


def extract(path: Path) -> dict[str, Any]:
    """解析 MOBI/AZW3；结构损坏返回 ok=False，加密标记 drm。"""
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        return finalize({}, ok=False, reason=f"无法读取文件：{exc}")

    if len(data) < 100:
        return finalize({}, ok=False, reason="文件过小，不是有效 MOBI/AZW3")

    title = _decode(data[:32].split(b"\x00", 1)[0], "utf-8")
    try:
        record_count = int.from_bytes(data[76:78], "big")
        offsets = [
            int.from_bytes(data[78 + index * 8 : 82 + index * 8], "big")
            for index in range(record_count + 1)
        ]
        if len(offsets) < 2 or offsets[1] <= offsets[0]:
            return finalize({"title": title}, ok=False, reason="记录表损坏")
        record0 = data[offsets[0] : offsets[1]]
    except (IndexError, ValueError) as exc:
        return finalize({}, ok=False, reason=f"PalmDB 头解析失败：{exc}")

    if len(record0) < 24:
        return finalize({"title": title}, ok=False, reason="PalmDOC 头不完整")

    encryption = int.from_bytes(record0[12:14], "big")
    drm = encryption != 0
    encoding = "cp1252"
    exth: dict[int, list[bytes]] = {}
    full_title = ""

    if record0[16:20] == b"MOBI":
        mobi = record0[16:]
        try:
            header_length = int.from_bytes(mobi[4:8], "big")
            encoding = "utf-8" if int.from_bytes(mobi[12:16], "big") == 65001 else "cp1252"
            name_offset = int.from_bytes(mobi[68:72], "big")
            name_length = int.from_bytes(mobi[72:76], "big")
            if name_length and name_offset + name_length <= len(record0):
                full_title = _decode(record0[name_offset : name_offset + name_length], encoding)
            exth_flags = int.from_bytes(mobi[112:116], "big")
            if exth_flags & 0x40:
                exth_start = 16 + header_length
                if record0[exth_start : exth_start + 4] == b"EXTH":
                    count = int.from_bytes(record0[exth_start + 8 : exth_start + 12], "big")
                    exth = _exth_records(record0, exth_start, count)
        except (IndexError, ValueError):
            exth = {}

    def first(kind: int, fallback: str = "") -> str:
        values = exth.get(kind)
        if values:
            return _decode(values[0], encoding)
        return fallback

    exth_title = first(_EXTH_TITLE, full_title or title)
    authors = [_decode(item, encoding) for item in exth.get(_EXTH_AUTHOR, [])]
    authors = [item for item in authors if item]
    isbn = normalize(first(_EXTH_ISBN)) or ""

    result = {
        "title": exth_title,
        "authors": authors,
        "isbn": isbn,
        "publisher": first(_EXTH_PUBLISHER),
        "date": first(_EXTH_DATE)[:32],
        "language": first(_EXTH_LANGUAGE),
        "description": first(_EXTH_DESCRIPTION),
        "drm": drm,
    }
    return finalize(result, ok=True, reason="受 DRM 保护" if drm else "")

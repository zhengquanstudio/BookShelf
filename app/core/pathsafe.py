"""Windows 路径段安全规则；不访问文件系统。"""

from __future__ import annotations

import os
import re
import unicodedata

_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ILLEGAL = re.compile(r'[\\/:*?"<>|]')


def is_reserved_name(value: object) -> bool:
    """Windows 保留名即使带扩展名也无效，例如 CON.txt。"""
    stem = unicodedata.normalize("NFKC", str(value or "")).split(".")[0]
    return stem.rstrip(" .").upper() in _RESERVED


def sanitize_segment(
    value: object, *, replacement: str = "_", max_bytes: int = 255
) -> str:
    """净化单个路径段，并按 UTF-8 字节数截断，避免切断多字节字符。"""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = _CONTROL.sub("", text)
    text = _ILLEGAL.sub(replacement or "_", text)
    text = re.sub(r"\s+", " ", text).rstrip(" .")
    if not text:
        return "_"
    if is_reserved_name(text):
        stem, suffix = os.path.splitext(text)
        text = f"{stem}_{suffix}"
    limit = max(1, int(max_bytes))
    if len(text.encode("utf-8")) > limit:
        text = text.encode("utf-8")[:limit].decode("utf-8", "ignore").rstrip(" .")
    return text or "_"

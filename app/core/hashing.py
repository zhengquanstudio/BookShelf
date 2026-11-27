"""哈希工具：增量扫描用 quick_hash，完整校验用 full_md5。"""

from __future__ import annotations

import hashlib
from pathlib import Path

_QUICK_CHUNK = 64 * 1024
_FULL_CHUNK = 1024 * 1024


def quick_hash(path: Path) -> str:
    """快速指纹：文件大小 + 前 64KB，用于增量扫描。"""
    path = Path(path)
    size = path.stat().st_size
    digest = hashlib.md5()
    digest.update(f"{size}|".encode("ascii"))
    with path.open("rb") as handle:
        digest.update(handle.read(_QUICK_CHUNK))
    return digest.hexdigest()


def full_md5(path: Path) -> str:
    """完整文件 MD5，用于最终确认重复内容。"""
    digest = hashlib.md5()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_FULL_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()

"""目录发现：os.scandir 递归，扩展名白名单，不跟随符号链接。"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

_FILE_ATTRIBUTE_HIDDEN = 0x2


@dataclass(frozen=True)
class ScannedFile:
    path: Path
    format: str
    size: int
    mtime: float
    too_small: bool = False


def _normalize_formats(formats: Iterable[str]) -> set[str]:
    result: set[str] = set()
    for item in formats:
        key = str(item).strip().lower().lstrip(".")
        if key:
            result.add(key)
    return result


def _is_hidden(entry: os.DirEntry) -> bool:
    if entry.name.startswith("."):
        return True
    try:
        info = entry.stat(follow_symlinks=False)
    except OSError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & _FILE_ATTRIBUTE_HIDDEN)


def discover_files(
    directories: Iterable[str | Path],
    formats: Iterable[str],
    *,
    recursive: bool = True,
    ignore_hidden: bool = True,
    min_size_kb: int = 50,
    max_depth: int = 12,
    cancel_check: Callable[[], bool] | None = None,
) -> list[ScannedFile]:
    """扫描目录并返回候选文件；调用方负责并发解析元数据。"""
    wanted = _normalize_formats(formats)
    minimum = max(0, int(min_size_kb)) * 1024
    depth_limit = max(0, int(max_depth))
    found: list[ScannedFile] = []
    seen: set[str] = set()

    for raw in directories:
        root = Path(raw).expanduser()
        try:
            if not root.is_dir():
                continue
        except OSError:
            continue
        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack:
            if cancel_check and cancel_check():
                return found
            current, depth = stack.pop()
            try:
                with os.scandir(current) as entries:
                    items = list(entries)
            except OSError:
                continue
            subdirs: list[Path] = []
            for entry in items:
                if cancel_check and cancel_check():
                    return found
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if ignore_hidden and _is_hidden(entry):
                            continue
                        if recursive and depth < depth_limit:
                            subdirs.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if ignore_hidden and _is_hidden(entry):
                        continue
                    suffix = Path(entry.name).suffix.lower().lstrip(".")
                    if suffix not in wanted:
                        continue
                    info = entry.stat(follow_symlinks=False)
                    if info.st_size <= 0:
                        continue
                    path = Path(entry.path)
                    key = str(path.resolve()).lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append(
                        ScannedFile(
                            path=path,
                            format=suffix,
                            size=int(info.st_size),
                            mtime=float(info.st_mtime),
                            too_small=info.st_size < minimum,
                        )
                    )
                except OSError:
                    continue
            # 逆序入栈，保证最终结果按名称顺序稳定输出。
            for item in reversed(sorted(subdirs, key=lambda item: item.name.lower())):
                stack.append((item, depth + 1))

    found.sort(key=lambda item: str(item.path).lower())
    return found

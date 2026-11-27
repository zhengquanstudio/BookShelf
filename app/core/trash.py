"""Windows 回收站删除：所有用户文件的删除都走这里。"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Iterable

_FO_DELETE = 0x0003
_FOF_SILENT = 0x0004
_FOF_NOCONFIRMATION = 0x0010
_FOF_ALLOWUNDO = 0x0040
_FOF_NOERRORUI = 0x0400


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def move_to_recycle_bin(paths: Iterable[Path | str]) -> int:
    """把文件/目录移入回收站，返回实际提交的路径数。"""
    if sys.platform != "win32":
        raise OSError("回收站删除仅在 Windows 上可用")
    items = []
    for item in paths:
        path = Path(item)
        if path.exists():
            items.append(str(path))
    if not items:
        return 0
    payload = "\0".join(items) + "\0\0"
    operation = _SHFILEOPSTRUCTW(
        None,
        _FO_DELETE,
        payload,
        None,
        _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT | _FOF_NOERRORUI,
        False,
        None,
        None,
    )
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if code != 0:
        raise OSError(f"移入回收站失败（错误码 {code}）")
    if operation.fAnyOperationsAborted:
        raise OSError("移入回收站操作被中止")
    return len(items)

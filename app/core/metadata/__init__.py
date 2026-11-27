"""元数据抽取入口：按扩展名分发，统一异常边界。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...errors import ExtractError
from . import epubs, mobis, pdfs
from .normalize import finalize

_HANDLERS = {
    ".epub": epubs.extract,
    ".pdf": pdfs.extract,
    ".mobi": mobis.extract,
    ".azw3": mobis.extract,
}


def extract_metadata(path: Path) -> dict[str, Any]:
    """返回固定键的元数据字典；解析失败不抛异常。"""
    path = Path(path)
    handler = _HANDLERS.get(path.suffix.lower())
    if handler is None:
        return finalize({}, ok=False, reason=f"不支持的格式：{path.suffix or '无扩展名'}")
    try:
        return finalize(handler(path))
    except ExtractError as exc:
        return finalize({}, ok=False, reason=str(exc))
    except Exception as exc:  # 解析器边界统一兜底，单本失败不中断整批
        return finalize({}, ok=False, reason=f"元数据解析失败：{exc}")

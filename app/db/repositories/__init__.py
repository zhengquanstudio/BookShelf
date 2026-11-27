"""仓储层公共工具。"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> str:
    """ISO8601 UTC 时间串（秒精度足够，便于排序与显示）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

"""统一日志：滚动文件 + 内存缓冲（供界面底部日志面板轮询）。

日志格式（文档 18.2）：
    2026-11-23T10:24:03.512+08:00 | INFO  | scan     | 开始扫描 ...
"""

from __future__ import annotations

import logging
import logging.handlers
import queue
from datetime import datetime

from . import config

OK_LEVEL = 25
logging.addLevelName(OK_LEVEL, "OK")

LOG_FORMAT = "%(asctime)s | %(levelname)-5s | %(action)-8s | %(message)s"


class _LocalTimeFormatter(logging.Formatter):
    """输出带毫秒与时区偏移的本地时间。"""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: N802
        dt = datetime.fromtimestamp(record.created).astimezone()
        return dt.isoformat(timespec="milliseconds")


_formatter = _LocalTimeFormatter(LOG_FORMAT)


class _ActionFilter(logging.Filter):
    """保证每条记录都有 action 字段。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "action", ""):
            record.action = record.name.split(".")[-1][:8]
        return True


_ui_queue: "queue.Queue[dict]" = queue.Queue(maxsize=2000)
_configured = False


class _QueueLogHandler(logging.Handler):
    """把日志推入内存队列，界面用定时器取走。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            item = {
                "ts": self.format(record).split(" | ", 1)[0],
                "level": record.levelname,
                "action": getattr(record, "action", ""),
                "message": record.getMessage(),
            }
        except Exception:  # 日志自身异常不能影响业务
            return
        try:
            _ui_queue.put_nowait(item)
        except queue.Full:
            try:
                _ui_queue.get_nowait()
                _ui_queue.put_nowait(item)
            except queue.Empty:
                pass


def setup_logging(level: int = logging.INFO) -> None:
    """初始化根日志：滚动文件（10MB × 3）+ 控制台 + 界面队列。"""
    global _configured
    if _configured:
        return
    config.ensure_dirs()
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    file_handler = logging.handlers.RotatingFileHandler(
        config.LOG_PATH, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(_formatter)
    file_handler.addFilter(_ActionFilter())

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(_formatter)
    console.addFilter(_ActionFilter())

    ui_handler = _QueueLogHandler()
    ui_handler.setLevel(level)
    ui_handler.setFormatter(_formatter)

    root.addHandler(file_handler)
    root.addHandler(console)
    root.addHandler(ui_handler)
    _configured = True


def get_logger(action: str) -> logging.LoggerAdapter:
    """按动作名（scan/fetch/organize/read/convert/meta）取日志器。"""
    return logging.LoggerAdapter(logging.getLogger("bookshelf"), {"action": action})


def log_ok(logger: logging.LoggerAdapter, message: str, *args) -> None:
    """记录一条 OK 级别日志（成功但非错误）。"""
    logger.log(OK_LEVEL, message, *args)


def drain_ui_logs(limit: int = 200) -> list[dict]:
    """界面定时器调用：取走最多 limit 条日志。"""
    items: list[dict] = []
    for _ in range(limit):
        try:
            items.append(_ui_queue.get_nowait())
        except queue.Empty:
            break
    return items

"""数据库连接管理。

约束：
- 每个线程独立连接（sqlite3 连接不能跨线程共享）；
- WAL 模式 + 外键开启；
- 连接使用 sqlite3.Row，便于按列名取值。
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .. import config
from ..errors import DatabaseError


class Database:
    """线程本地连接的数据库句柄。"""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or config.DB_PATH)
        self._local = threading.local()

    # ---- 连接 -------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        """获取当前线程的连接，必要时新建。"""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(str(self.path), timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error as exc:
            raise DatabaseError(f"无法打开数据库：{self.path}（{exc}）") from exc
        self._local.conn = conn
        return conn

    def close(self) -> None:
        """关闭当前线程连接（线程退出或测试清理时调用）。"""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            finally:
                self._local.conn = None

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """事务上下文：正常提交，异常回滚。"""
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ---- 便捷查询 ---------------------------------------------------
    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return list(self.connect().execute(sql, params))

    def query_one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        return self.connect().execute(sql, params).fetchone()

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        """执行写语句并提交，返回 lastrowid。"""
        with self.transaction() as conn:
            cur = conn.execute(sql, params)
            return int(cur.lastrowid or 0)


_default_db: Database | None = None


def get_database(path: Path | str | None = None) -> Database:
    """进程级默认数据库句柄。"""
    global _default_db
    if path is not None:
        return Database(path)
    if _default_db is None:
        _default_db = Database()
    return _default_db

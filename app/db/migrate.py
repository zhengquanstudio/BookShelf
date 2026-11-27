"""数据库初始化与版本迁移。

版本记录在 schema_version 表；当前基线为 1（第 5 章 DDL）。
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..errors import DatabaseError
from ..logger import get_logger
from .connection import Database

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 5

log = get_logger("db")


def current_version(db: Database) -> int:
    """返回当前 schema 版本，空库返回 0。"""
    try:
        row = db.query_one("SELECT MAX(ver) AS ver FROM schema_version")
    except sqlite3.Error:
        return 0
    if row is None or row["ver"] is None:
        return 0
    return int(row["ver"])


def _apply_baseline(db: Database) -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = db.connect()
    conn.executescript(sql)
    with db.transaction() as tx:
        tx.execute(
            "INSERT OR REPLACE INTO schema_version(ver, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
        )


def _migrate_v2(db: Database) -> None:
    """v1 → v2：library_items 增加批次号，供整理记录与撤销使用。"""
    columns = {row["name"] for row in db.query("PRAGMA table_info(library_items)")}
    if "batch_id" not in columns:
        db.execute("ALTER TABLE library_items ADD COLUMN batch_id TEXT")
    db.execute(
        "CREATE INDEX IF NOT EXISTS ix_items_batch ON library_items(batch_id)"
    )
    with db.transaction() as tx:
        tx.execute(
            "INSERT OR REPLACE INTO schema_version(ver, applied_at) VALUES (?, ?)",
            (2, datetime.now(timezone.utc).isoformat()),
        )


def _migrate_v3(db: Database) -> None:
    """v2 → v3：books 增加重复来源指针，保留既有重复组逻辑。"""
    columns = {row["name"] for row in db.query("PRAGMA table_info(books)")}
    if columns and "dup_of" not in columns:
        db.execute("ALTER TABLE books ADD COLUMN dup_of INTEGER REFERENCES books(id) ON DELETE SET NULL")
    with db.transaction() as tx:
        tx.execute(
            "INSERT OR REPLACE INTO schema_version(ver, applied_at) VALUES (?, ?)",
            (3, datetime.now(timezone.utc).isoformat()),
        )


def _migrate_v4(db: Database) -> None:
    """v3 → v4：library_items 记录源路径，供"只重命名"批次撤销。"""
    columns = {row["name"] for row in db.query("PRAGMA table_info(library_items)")}
    if columns and "source_path" not in columns:
        db.execute("ALTER TABLE library_items ADD COLUMN source_path TEXT")
    with db.transaction() as tx:
        tx.execute(
            "INSERT OR REPLACE INTO schema_version(ver, applied_at) VALUES (?, ?)",
            (4, datetime.now(timezone.utc).isoformat()),
        )


def _migrate_v5(db: Database) -> None:
    """v4 → v5：阅读会话、喜爱标记与阅读状态。"""
    columns = {row["name"] for row in db.query("PRAGMA table_info(books)")}
    with db.transaction() as tx:
        if columns:
            if "favorite" not in columns:
                tx.execute(
                    "ALTER TABLE books ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0"
                )
            if "read_state" not in columns:
                tx.execute(
                    "ALTER TABLE books ADD COLUMN read_state TEXT NOT NULL DEFAULT 'unread'"
                )
            if "status" not in columns:
                tx.execute(
                    "ALTER TABLE books ADD COLUMN status TEXT NOT NULL DEFAULT 'ok'"
                )
        tx.execute(
            """CREATE TABLE IF NOT EXISTS reading_sessions (
              id INTEGER PRIMARY KEY,
              book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
              started_at TEXT NOT NULL,
              ended_at TEXT,
              seconds INTEGER DEFAULT 0,
              pages INTEGER DEFAULT 0,
              device TEXT DEFAULT 'desktop'
            )"""
        )
        tx.execute(
            "CREATE INDEX IF NOT EXISTS ix_rs_day "
            "ON reading_sessions(substr(started_at,1,10))"
        )
        tx.execute(
            "CREATE INDEX IF NOT EXISTS ix_rs_book ON reading_sessions(book_id)"
        )
        tx.execute(
            "INSERT OR REPLACE INTO schema_version(ver, applied_at) VALUES (?, ?)",
            (5, datetime.now(timezone.utc).isoformat()),
        )


def _backup_before_v5(db: Database) -> Path:
    """在 v5 结构变更前生成一致性备份，保留 WAL 中已提交的数据。"""
    backup = db.path.with_name(f"{db.path.name}.bak-v4")
    destination: sqlite3.Connection | None = None
    try:
        destination = sqlite3.connect(str(backup))
        db.connect().backup(destination)
        destination.close()
    except sqlite3.Error as exc:
        if destination is not None:
            destination.close()
        raise DatabaseError(f"数据库 v4 备份失败，已取消升级：{exc}") from exc
    return backup


def _restore_v4_backup(db: Database, backup: Path) -> None:
    """v5 失败时恢复备份；备份文件本身保留，便于人工核查。"""
    db.close()
    try:
        for suffix in ("-wal", "-shm"):
            db.path.with_name(db.path.name + suffix).unlink(missing_ok=True)
        shutil.copy2(str(backup), str(db.path))
    except OSError as exc:
        raise DatabaseError(
            f"数据库升级失败且自动回滚失败，请用 {backup.name} 手动恢复：{exc}"
        ) from exc


def _normalize_status_values(db: Database) -> None:
    """S2：识别状态语义迁移 recognized→ok、need_confirm→partial（幂等）。

    仅做数据清洗，不升 schema 版本；结构变更留给 v5。
    部分旧测试库只建了个别表，books 不存在时直接跳过。
    """
    tables = {
        row["name"]
        for row in db.query("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if "books" not in tables:
        return
    with db.transaction() as tx:
        tx.execute("UPDATE books SET status = 'ok' WHERE status = 'recognized'")
        tx.execute("UPDATE books SET status = 'partial' WHERE status = 'need_confirm'")


def _integrity_ok(db: Database) -> bool:
    try:
        row = db.query_one("PRAGMA integrity_check")
    except sqlite3.Error:
        return False
    return bool(row) and row[0] == "ok"


def _quarantine(db: Database) -> None:
    """数据库损坏时改名备份，随后重建空库。"""
    db.close()
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    broken = db.path.with_name(f"{db.path.name}.broken-{stamp}")
    try:
        shutil.move(str(db.path), str(broken))
    except OSError as exc:
        raise DatabaseError(f"数据库损坏且无法备份：{exc}") from exc
    for suffix in ("-wal", "-shm"):
        extra = db.path.with_name(db.path.name + suffix)
        if extra.exists():
            extra.unlink(missing_ok=True)
    log.warning("数据库损坏，已备份为 %s，将重建空库", broken.name)


def init_database(db: Database | None = None) -> Database:
    """确保数据库可用且结构为最新版本。"""
    db = db or Database()
    if db.path.exists() and db.path.stat().st_size > 0:
        if not _integrity_ok(db):
            _quarantine(db)
    try:
        version = current_version(db)
        if version == 0:
            _apply_baseline(db)
        else:
            if version < 2:
                _migrate_v2(db)
            if version < 3:
                _migrate_v3(db)
            if version < 4:
                _migrate_v4(db)
            if version < 5:
                backup = _backup_before_v5(db)
                try:
                    _migrate_v5(db)
                except sqlite3.Error as exc:
                    _restore_v4_backup(db, backup)
                    raise DatabaseError(
                        f"数据库升级 v5 失败，已回滚到升级前备份：{exc}"
                    ) from exc
            _normalize_status_values(db)
    except sqlite3.Error as exc:
        raise DatabaseError(f"数据库初始化失败：{exc}") from exc
    log.info(
        "数据库就绪 path=%s version=%s", db.path, current_version(db)
    )
    return db

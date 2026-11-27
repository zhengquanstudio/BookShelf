"""维护操作：清理缓存与备份数据库。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .. import config
from ..core.trash import move_to_recycle_bin
from ..db.connection import Database
from ..db.repositories.cache_repo import CacheRepository
from ..errors import BookShelfError
from ..logger import get_logger

log = get_logger("maintenance")


class MaintenanceService:
    """不触碰书籍文件与封面，只清理可再生缓存并做一致性备份。"""

    def __init__(
        self,
        db: Database,
        *,
        cache_dirs: Iterable[Path] | None = None,
        backup_dir: Path | None = None,
        backup_retention: int = 5,
    ) -> None:
        self.db = db
        self.cache_dirs = [Path(item) for item in (cache_dirs or (config.CONVERTED_DIR,))]
        self.backup_dir = Path(backup_dir or (config.DATA_DIR / "backups"))
        self.backup_retention = max(1, int(backup_retention))

    def clear_cache(self) -> dict[str, int]:
        """把转换缓存移入回收站，并清空联网检索缓存；封面缩略图保留。"""
        files: list[Path] = []
        total_bytes = 0
        for directory in self.cache_dirs:
            if not directory.is_dir():
                continue
            for path in directory.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    total_bytes += path.stat().st_size
                except OSError:
                    pass
                files.append(path)
        removed = move_to_recycle_bin(files) if files else 0
        metadata = CacheRepository(self.db).clear()
        log.info("缓存清理完成：文件 %s 个，检索缓存 %s 条", removed, metadata)
        return {"files": removed, "bytes": total_bytes, "metadata": metadata}

    def create_backup(self) -> tuple[Path, int]:
        """创建一致性备份，清理超额普通备份并返回路径与字节数。"""
        target = self._create_backup("library")
        backups = sorted(
            self.backup_dir.glob("library-*.db"),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )
        for old_path in backups[self.backup_retention :]:
            old_path.unlink(missing_ok=True)
            log.info("已清理超额数据库备份 %s", old_path)
        return target, target.stat().st_size

    def backup_database(self) -> Path:
        """兼容旧调用：创建备份并仅返回路径。"""
        target, _size = self.create_backup()
        return target

    def list_backups(self) -> list[Path]:
        """列出普通与恢复前备份，最新的排在前面。"""
        if not self.backup_dir.is_dir():
            return []
        paths = [
            path
            for path in self.backup_dir.glob("*.db")
            if path.name.startswith(("library-", "pre-restore-"))
        ]
        return sorted(
            paths,
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )

    def delete_backup(self, path: Path) -> None:
        """删除备份目录内由本应用管理的一份备份。"""
        target = self._managed_path(path)
        target.unlink()
        log.info("数据库备份已删除 %s", target)

    def restore_backup(self, path: Path) -> Path:
        """校验并恢复备份，返回恢复前自动生成的安全副本路径。"""
        target = self._managed_path(path)
        source: sqlite3.Connection | None = None
        destination: sqlite3.Connection | None = None
        safety_copy: Path | None = None
        try:
            source = sqlite3.connect(str(target))
            result = source.execute("PRAGMA integrity_check").fetchone()
            if result is None or str(result[0]).lower() != "ok":
                detail = str(result[0]) if result else "未知错误"
                raise BookShelfError(f"备份文件校验失败：{detail}")
            safety_copy = self._create_backup("pre-restore")
            self.db.close()
            destination = sqlite3.connect(str(self.db.path))
            source.backup(destination)
            destination.commit()
        except BookShelfError:
            raise
        except (sqlite3.Error, OSError) as exc:
            suffix = f"；恢复前备份位于 {safety_copy}" if safety_copy else ""
            raise BookShelfError(f"数据库恢复失败：{exc}{suffix}") from exc
        finally:
            if destination is not None:
                destination.close()
            if source is not None:
                source.close()
        log.info("数据库已从 %s 恢复，恢复前副本为 %s", target, safety_copy)
        return safety_copy

    def _create_backup(self, prefix: str) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = f"{datetime.now():%Y%m%d-%H%M%S-%f}"
        target = self.backup_dir / f"{prefix}-{stamp}.db"
        counter = 1
        while target.exists():
            target = self.backup_dir / f"{prefix}-{stamp}-{counter}.db"
            counter += 1
        source = self.db.connect()
        destination: sqlite3.Connection | None = None
        try:
            destination = sqlite3.connect(str(target))
            source.backup(destination)
        except sqlite3.Error as exc:
            target.unlink(missing_ok=True)
            raise BookShelfError(f"数据库备份失败：{exc}") from exc
        finally:
            if destination is not None:
                destination.close()
        log.info("数据库已备份到 %s", target)
        return target

    def _managed_path(self, path: Path) -> Path:
        target = Path(path).expanduser().resolve()
        if target.parent != self.backup_dir.expanduser().resolve() or not (
            target.name.startswith(("library-", "pre-restore-"))
            and target.suffix == ".db"
        ):
            raise BookShelfError("只能操作备份目录中由 BookShelf 创建的备份文件")
        if not target.is_file():
            raise BookShelfError(f"备份文件不存在：{target}")
        return target

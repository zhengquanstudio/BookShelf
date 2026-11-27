"""联网检索缓存仓储：避免重复请求，带过期时间。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from ..connection import Database


class CacheRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def get(self, key: str, now: datetime | None = None) -> dict[str, Any] | None:
        """命中未过期缓存时返回 payload，否则 None。"""
        row = self.db.query_one(
            "SELECT payload_json, expires_at FROM search_cache WHERE key = ?", (key,)
        )
        if row is None:
            return None
        moment = now or datetime.now(timezone.utc)
        try:
            expires = datetime.fromisoformat(row["expires_at"])
        except ValueError:
            return None
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= moment:
            return None
        try:
            payload = json.loads(row["payload_json"])
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else {"items": payload}

    def put(
        self,
        key: str,
        source: str,
        payload: dict[str, Any] | list[Any],
        ttl_days: int = 30,
    ) -> None:
        fetched = datetime.now(timezone.utc)
        expires = fetched + timedelta(days=ttl_days)
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO search_cache"
                "(key, source, payload_json, hit_count, fetched_at, expires_at) "
                "VALUES (?, ?, ?, 1, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "source=excluded.source, payload_json=excluded.payload_json, "
                "hit_count=search_cache.hit_count + 1, "
                "fetched_at=excluded.fetched_at, expires_at=excluded.expires_at",
                (
                    key,
                    source,
                    json.dumps(payload, ensure_ascii=False),
                    fetched.isoformat(timespec="seconds"),
                    expires.isoformat(timespec="seconds"),
                ),
            )

    def purge_expired(self, now: datetime | None = None) -> int:
        moment = now or datetime.now(timezone.utc)
        with self.db.transaction() as conn:
            cur = conn.execute(
                "DELETE FROM search_cache WHERE expires_at <= ?",
                (moment.isoformat(timespec="seconds"),),
            )
            return cur.rowcount

    def clear(self) -> int:
        with self.db.transaction() as conn:
            cur = conn.execute("DELETE FROM search_cache")
            return cur.rowcount

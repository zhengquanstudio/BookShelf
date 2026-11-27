"""联网补全与元数据合并（文档 F5 核心管线）。

设计要点：
- 缓存优先；同一本书第二次检索不应产生网络请求；
- 任何网络异常都降级为本地元数据 + 待确认，不向 UI 抛异常；
- 内嵌字段只补空，不覆盖；用户手动应用时才覆盖。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from .. import config
from ..core import authors, isbn as isbn_tools
from ..core import naming, series
from ..core.metadata import extract_metadata
from ..db.connection import Database
from ..db.repositories.book_repo import BookRepository
from ..db.repositories.cache_repo import CacheRepository
from ..logger import get_logger
from ..net import HttpClient, NetworkError
from ..net.scoring import rank_candidates, score_candidate, why_text
from .author_service import AuthorService
from .normalization import normalize_book
from .series_service import SeriesService

log = get_logger("meta")

_MERGE = (
    ("title", "title"),
    ("subtitle", "subtitle"),
    ("isbn", "isbn"),
    ("publisher", "publisher"),
    ("date", "publish_date"),
    ("language", "language"),
    ("description", "description"),
)


class MetadataService:
    def __init__(
        self,
        db: Database,
        settings: Any | None = None,
        *,
        sources: Sequence[Any] | None = None,
        client: HttpClient | None = None,
    ) -> None:
        self.db = db
        self.books = BookRepository(db)
        self.cache = CacheRepository(db)
        self.options = _options(settings)
        meta = self.options.get("meta", {})
        src = self.options.get("sources", {})
        self.enable_network = bool(meta.get("enable_network", True))
        self.ttl_days = int(src.get("cache_ttl_days", 30) or 30)
        self.auto_score = int(meta.get("confidence_auto", 85) or 85)
        self.confirm_score = int(meta.get("confidence_confirm", 60) or 60)
        self._sources = list(sources) if sources is not None else None
        self._client = client
        self._meta_options = meta
        self._source_options = src
        self.last_network_error = ""

    # ---- 检索 -------------------------------------------------------
    def _all_sources(self) -> list[Any]:
        if self._sources is not None:
            return self._sources
        self._sources = self._build_sources()
        return self._sources

    def _build_sources(self) -> list[Any]:
        if not self.enable_network:
            return []
        src = self._source_options
        meta = self._meta_options
        self._client = self._client or HttpClient(
            timeout=(5, float(meta.get("timeout_sec", 15) or 15)),
            retries=int(meta.get("retries", 3) or 3),
            daily_limit=int(src.get("daily_limit", 500) or 500),
            rate_limit_sec=float(src.get("rate_limit_ms", 2000) or 2000) / 1000.0,
        )
        sources: list[Any] = []
        if src.get("douban", True):
            from ..net.douban import DoubanSource

            sources.append(DoubanSource(self._client))
        if src.get("crossref", False):
            from ..net.crossref import CrossrefSource

            sources.append(CrossrefSource(self._client))
        if src.get("kongfz", False):
            from ..net.kongfz import KongfzSource

            sources.append(KongfzSource(self._client))
        if src.get("openlibrary", True):
            from ..net.openlibrary import OpenLibrarySource

            sources.append(OpenLibrarySource(self._client))
        if src.get("googlebooks", True):
            from ..net.googlebooks import GoogleBooksSource

            sources.append(GoogleBooksSource(self._client))
        return sources

    def find_candidates(self, book: Mapping[str, Any], *, use_cache: bool = True) -> list[dict[str, Any]]:
        """按 ISBN 优先、书名+作者兜底检索，返回按匹配度降序的候选。"""
        book = dict(book)
        self.last_network_error = ""
        sources = self._all_sources()
        if not sources:
            return []
        isbn_value = isbn_tools.normalize(str(book.get("isbn") or "")) or ""
        title = naming.clean_text(book.get("title") or "", max_len=120)
        author_list = authors.split_authors(
            book.get("author_raw") or book.get("author_name") or ""
        )
        # 老接口仍需要一条查询串；新接口按 isbn/title/authors 三个字段传。
        query = " ".join(part for part in (title, author_list[0] if author_list else "") if part).strip()

        collected: list[dict[str, Any]] = []
        for source in sources:
            items: list[dict[str, Any]] = []
            if isbn_value:
                items = self._fetch(
                    source,
                    key_prefix="isbn",
                    key_value=isbn_value,
                    mode="isbn",
                    use_cache=use_cache,
                    isbn=isbn_value,
                    title=title,
                    authors=author_list,
                    query=isbn_value,
                )
            if not items and title:
                cache_value = "|".join(
                    ("".join(title.split()).casefold(),
                     author_list[0].casefold() if author_list else "")
                )
                items = self._fetch(
                    source,
                    key_prefix="q",
                    key_value=cache_value,
                    mode="search",
                    use_cache=use_cache,
                    isbn=None,
                    title=title,
                    authors=author_list,
                    query=query,
                )
            for item in items:
                item = dict(item)
                item.setdefault("source", getattr(source, "name", "unknown"))
                collected.append(item)
        return rank_candidates(_dedupe(collected), book)

    def _fetch(
        self,
        source: Any,
        *,
        key_prefix: str,
        key_value: str,
        mode: str,
        use_cache: bool,
        isbn: str | None = None,
        title: str | None = None,
        authors: list[str] | None = None,
        query: str = "",
    ) -> list[dict[str, Any]]:
        name = str(getattr(source, "name", "unknown"))
        digest = hashlib.sha1(key_value.encode("utf-8")).hexdigest()[:20]
        key = f"{key_prefix}:{name}:{digest}"
        if use_cache:
            cached = self.cache.get(key)
            if cached is not None and isinstance(cached.get("items"), list):
                return list(cached["items"])
        try:
            lookup = getattr(source, "lookup", None)
            if callable(lookup):
                items = lookup(isbn=isbn, title=title, authors=authors)
            elif mode == "isbn":
                items = source.by_isbn(query)
            else:
                items = source.search(query)
        except Exception as exc:  # 网络层任何异常都降级为本地元数据
            self.last_network_error = str(exc)
            log.warning("%s 检索失败：%s", name, exc)
            return []
        items = [dict(item) for item in (items or []) if isinstance(item, Mapping)]
        if items:
            self.cache.put(key, name, {"items": items}, ttl_days=self.ttl_days)
        return items

    # ---- 补全 -------------------------------------------------------
    def enrich_book(self, book_id: int, *, force: bool = False) -> dict[str, Any]:
        book = self.books.get(book_id)
        if book is None:
            return {"book_id": book_id, "status": "missing", "candidates": [], "message": "书籍不存在"}
        current = dict(book)
        # partial（待补全）即使字段看似完整也继续联网，允许被新结果覆盖；
        # 只有 ok 且字段完整时才直接短路，failed/drm/skipped 的保留语义见下方。
        if not force and _is_complete(current) and current.get("status") not in {
            "failed", "drm", "skipped", "partial"
        }:
            self.books.update(book_id, status="ok", confidence=100,
                              meta_source=current.get("meta_source") or "embedded")
            normalize_book(self.db, book_id)
            return {
                "book_id": book_id,
                "status": "ok",
                "confidence": 100,
                "candidates": [],
                "message": "内嵌元数据完整，无需联网",
            }

        candidates: list[dict[str, Any]] = []
        offline = False
        try:
            candidates = self.find_candidates(current)
            offline = bool(self.last_network_error) and not candidates
        except Exception as exc:  # 兜底：网络层任何异常都不致命
            offline = True
            log.warning("联网补全失败，降级本地元数据：%s", exc)
        best = next((item for item in candidates if not item.get("rejected")), None)

        if best and int(best.get("score") or 0) >= self.confirm_score:
            self._apply_fields(book_id, current, best, overwrite=False,
                               source=str(best.get("source") or "network"))
            status = "ok" if int(best["score"]) >= self.auto_score else "partial"
            confidence = float(best["score"])
            message = (
                f"采用 {best.get('source')} 结果，匹配度 {best['score']}%"
                f"（{' / '.join(why_text(best.get('why')))}）"
                if best.get("why") else
                f"采用 {best.get('source')} 结果，匹配度 {best['score']}%"
            )
        else:
            status = "partial"
            if current.get("status") in {"failed", "drm", "skipped"}:
                status = str(current.get("status"))
            confidence = float(current.get("confidence") or 50)
            message = "网络不可用，保留本地元数据" if offline else "未找到足够可信的结果，待人工确认"
        old_status = str(current.get("status") or "")
        self.books.update(book_id, status=status, confidence=confidence)
        if old_status != status:
            # 状态流转留痕：partial/failed 被新结果覆盖为 ok 时尤其需要可追溯。
            log.info("[id=%s] 识别状态 %s → %s（%s）",
                     book_id, old_status or "空", status, message)
        normalize_book(self.db, book_id)
        return {
            "book_id": book_id,
            "status": status,
            "confidence": confidence,
            "candidates": candidates,
            "message": message,
        }

    def apply_candidate(
        self, book_id: int, candidate: Mapping[str, Any], *, manual: bool = True
    ) -> dict[str, Any]:
        book = self.books.get(book_id)
        if book is None:
            return {}
        current = dict(book)
        source = "manual" if manual else str(candidate.get("source") or "network")
        score = 100 if manual else int(candidate.get("score") or 0)
        self._apply_fields(book_id, current, candidate, overwrite=True, source=source)
        status = "ok" if current.get("title") or candidate.get("title") else "partial"
        self.books.update(book_id, status=status, confidence=score, meta_source=source)
        normalize_book(self.db, book_id)
        return dict(self.books.get(book_id) or {})

    def save_manual(self, book_id: int, fields: Mapping[str, Any]) -> dict[str, Any]:
        """保存手动编辑；作者与系列同步落库，作者记录锁定。"""
        allowed = {
            "title", "subtitle", "author_raw", "isbn", "publisher", "publish_date",
            "language", "description", "volume", "status",
        }
        data = {key: value for key, value in fields.items() if key in allowed}
        if "isbn" in data:
            raw = data.get("isbn") or ""
            data["isbn"] = isbn_tools.normalize(str(raw)) or ""
        if data.get("volume") in ("", 0):
            data["volume"] = None
        self.books.update(book_id, **data)

        book = self.books.get(book_id)
        author_id = book["author_id"] if book else None
        raw_author = str(data.get("author_raw") or (book["author_raw"] if book else "") or "")
        if raw_author:
            author_id = AuthorService(self.db).assign_book(book_id, raw_author, locked=True)

        series_name = str(fields.get("series") or "").strip()
        if series_name or data.get("volume"):
            SeriesService(self.db).assign(
                book_id,
                title=str(data.get("title") or (book["title"] if book else "")),
                series_name=series_name or None,
                series_index=fields.get("series_index"),
                volume=_int_or_none(data.get("volume")),
                author_id=int(author_id) if author_id else None,
            )

        status = str(fields.get("status") or "").strip()
        if not status:
            status = "ok" if (data.get("title") or (book and book["title"])) and raw_author else "partial"
        self.books.update(book_id, status=status, confidence=100, meta_source="manual")
        normalize_book(self.db, book_id)
        return dict(self.books.get(book_id) or {})

    def reset_to_embedded(self, book_id: int) -> dict[str, Any]:
        """用文件内嵌元数据覆盖当前表单（不联网）。"""
        book = self.books.get(book_id)
        if book is None:
            return {}
        metadata = extract_metadata(Path(str(book["file_path"])))
        if not metadata.get("ok"):
            return dict(book)
        candidate = {
            "title": metadata.get("title") or "",
            "subtitle": metadata.get("subtitle") or "",
            "authors": metadata.get("authors") or [],
            "isbn": metadata.get("isbn") or "",
            "publisher": metadata.get("publisher") or "",
            "date": metadata.get("date") or "",
            "language": metadata.get("language") or "",
            "series": metadata.get("series") or "",
            "series_index": metadata.get("series_index") or "",
            "description": metadata.get("description") or "",
            "source": "embedded",
        }
        self._apply_fields(book_id, dict(book), candidate, overwrite=True, source="embedded")
        status = "drm" if metadata.get("drm") else "ok" if candidate["title"] and candidate["authors"] else "partial"
        self.books.update(book_id, status=status, confidence=100, meta_source="embedded")
        normalize_book(self.db, book_id)
        return dict(self.books.get(book_id) or {})

    # ---- 内部 -------------------------------------------------------
    def _apply_fields(
        self,
        book_id: int,
        book: Mapping[str, Any],
        candidate: Mapping[str, Any],
        *,
        overwrite: bool,
        source: str,
    ) -> None:
        updates: dict[str, Any] = {}
        for source_key, column in _MERGE:
            value = str(candidate.get(source_key) or "").strip()
            if not value:
                continue
            if overwrite or not str(book.get(column) or "").strip():
                updates[column] = value
        authors_list = candidate.get("authors") or []
        if isinstance(authors_list, str):
            authors_list = [authors_list]
        authors_list = [str(item).strip() for item in authors_list if str(item).strip()]
        if authors_list and (overwrite or not str(book.get("author_raw") or "").strip()):
            updates["author_raw"] = "、".join(authors_list)
        isbn_value = isbn_tools.normalize(str(candidate.get("isbn") or ""))
        if isbn_value and (overwrite or not str(book.get("isbn") or "").strip()):
            updates["isbn"] = isbn_value
        if updates:
            self.books.update(book_id, **updates)

        current = self.books.get(book_id)
        if current is None:
            return
        raw_author = str(updates.get("author_raw") or current["author_raw"] or "")
        author_id = current["author_id"]
        if raw_author and (overwrite or not author_id):
            author_id = AuthorService(self.db).assign_book(book_id, raw_author)

        volume = _int_or_none(candidate.get("series_index"))
        series_name = str(candidate.get("series") or "").strip()
        if author_id and (series_name or volume):
            SeriesService(self.db).assign(
                book_id,
                title=str(updates.get("title") or current["title"] or ""),
                series_name=series_name or None,
                series_index=candidate.get("series_index"),
                volume=volume,
                author_id=int(author_id),
            )

        cover_url = str(candidate.get("cover_url") or "").strip()
        if cover_url and not current["cover_path"]:
            self._save_cover(book_id, cover_url)

    def _save_cover(self, book_id: int, url: str) -> None:
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QImage

            data = self._cover_bytes(url)
            if not data:
                return
            image = QImage.fromData(data)
            if image.isNull():
                return
            if image.width() > 320:
                image = image.scaledToWidth(320, Qt.SmoothTransformation)
            config.COVERS_DIR.mkdir(parents=True, exist_ok=True)
            path = config.COVERS_DIR / f"{book_id}.jpg"
            if image.save(str(path), "JPEG", 85):
                self.books.update(book_id, cover_path=str(path))
        except Exception as exc:  # 封面失败不影响元数据
            log.warning("封面下载失败：%s", exc)

    def cover_bytes(self, url: str) -> bytes:
        """候选封面缩略图下载入口，复用限速与 UA 策略。"""
        return self._cover_bytes(url)

    def _cover_bytes(self, url: str) -> bytes:
        """封面下载与检索共用同一客户端（限速/日上限/重试）。"""
        headers = {}
        if "douban" in url:
            headers["Referer"] = "https://book.douban.com/"
        if self._client is not None:
            return self._client.get_bytes(url, source="cover", headers=headers, ua="browser")
        import requests

        response = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": f"BookShelf/{config.APP_VERSION}", **headers},
        )
        response.raise_for_status()
        return response.content


def _options(settings: Any) -> dict[str, Any]:
    if settings is None:
        return config.load_config()
    if isinstance(settings, Mapping):
        return dict(settings)
    return dict(getattr(settings, "data", {}) or config.load_config())


def _is_complete(book: Mapping[str, Any]) -> bool:
    return bool(
        str(book.get("title") or "").strip()
        and str(book.get("author_raw") or book.get("author_id") or "").strip()
        and (str(book.get("isbn") or "").strip() or str(book.get("publisher") or "").strip())
    )


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(float(str(value)))
        return number if number > 0 else None
    except (TypeError, ValueError):
        match = series.extract_volume(str(value))
        return match.volume if match else None


def _dedupe(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = (
            str(item.get("source") or "").casefold(),
            str(item.get("title") or "").strip().casefold(),
            str(item.get("isbn") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def score(book: Mapping[str, Any], candidate: Mapping[str, Any]) -> int:
    return score_candidate(candidate, book)

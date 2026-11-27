"""联网检索 HTTP 客户端：统一 UA、超时、重试、按源限速与日上限（文档 8.2）。

除 JSON API 外还提供 HTML 与二进制取法：豆瓣/孔夫子等网页源必须用浏览器 UA
并带 Referer，封面下载同样走本客户端的限速与日上限。
"""

from __future__ import annotations

import threading
import time
from typing import Any

from .. import config
from ..logger import get_logger

log = get_logger("net")

USER_AGENT = f"BookShelf/{config.APP_VERSION} (personal library organizer)"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class NetworkError(Exception):
    """网络请求最终失败（已重试）。"""


class DailyLimitExceeded(NetworkError):
    """达到设置的每日请求上限。"""


class RateLimiter:
    """同一来源的最小请求间隔（默认 2 秒）。"""

    def __init__(self, min_interval: float = 2.0) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next_at - now
            self._next_at = max(now, self._next_at) + self.min_interval
        if delay > 0:
            time.sleep(delay)


class HttpClient:
    """轻量封装 requests；测试可传入自定义 session 或直接使用假源。"""

    def __init__(
        self,
        *,
        timeout: tuple[float, float] = (5, 15),
        retries: int = 3,
        daily_limit: int = 500,
        rate_limit_sec: float = 2.0,
        session: Any | None = None,
    ) -> None:
        self.timeout = timeout
        self.retries = max(1, int(retries))
        self.daily_limit = int(daily_limit)
        self._session = session
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}
        self._limiters: dict[str, RateLimiter] = {}
        self._rate_limit_sec = max(0.0, float(rate_limit_sec))

    def _session_obj(self) -> Any:
        if self._session is not None:
            return self._session
        import requests

        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        return self._session

    def _limiter(self, source: str) -> RateLimiter:
        with self._lock:
            limiter = self._limiters.get(source)
            if limiter is None:
                limiter = RateLimiter(self._rate_limit_sec)
                self._limiters[source] = limiter
            return limiter

    def _count(self, source: str) -> int:
        with self._lock:
            if self.daily_limit > 0:
                used = self._counts.get(source, 0)
                if used >= self.daily_limit:
                    raise DailyLimitExceeded(f"{source} 已达到每日请求上限 {self.daily_limit}")
            self._counts[source] = self._counts.get(source, 0) + 1
            return self._counts[source]

    def used(self, source: str) -> int:
        with self._lock:
            return self._counts.get(source, 0)

    def _headers(self, ua: str | None, headers: dict[str, str] | None) -> dict[str, str]:
        """合并请求头；`ua="browser"` 时使用 Chrome UA，不污染全局 session。"""
        merged: dict[str, str] = {}
        if ua == "browser":
            merged["User-Agent"] = BROWSER_UA
        elif ua:
            merged["User-Agent"] = str(ua)
        merged.update(headers or {})
        return merged

    def _request(
        self,
        url: str,
        *,
        source: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        allow_redirects: bool = True,
        ua: str | None = None,
    ) -> Any:
        """限速 + 计数 + 重试的 GET，返回原始响应对象。"""
        last_error: Exception | None = None
        request_headers = self._headers(ua, headers)
        for attempt in range(self.retries):
            self._limiter(source).wait()
            self._count(source)
            try:
                response = self._session_obj().get(
                    url,
                    params=params,
                    timeout=self.timeout,
                    headers=request_headers or None,
                    allow_redirects=allow_redirects,
                )
                status = int(getattr(response, "status_code", 0))
                if status in (429, 500, 502, 503, 504):
                    raise NetworkError(f"HTTP {status}")
                if status >= 400:
                    raise NetworkError(f"HTTP {status}")
                return response
            except Exception as exc:  # requests 的异常族也在此统一兜底
                last_error = exc
                if attempt < self.retries - 1:
                    time.sleep(1.0 * (2 ** attempt))
                else:
                    break
        log.warning("请求失败 %s：%s", url, last_error)
        raise NetworkError(str(last_error or "请求失败"))

    def get_json(
        self,
        url: str,
        *,
        source: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        ua: str | None = None,
    ) -> Any:
        """GET 并解析 JSON；失败重试 3 次（1s/2s/4s），仍失败抛 NetworkError。"""
        response = self._request(url, source=source, params=params, headers=headers, ua=ua)
        return response.json()

    def get_text(
        self,
        url: str,
        *,
        source: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        allow_redirects: bool = True,
        ua: str | None = None,
    ) -> str:
        """GET HTML 文本；豆瓣等网页源需传 `ua="browser"` 与 Referer。"""
        response = self._request(
            url,
            source=source,
            params=params,
            headers=headers,
            allow_redirects=allow_redirects,
            ua=ua,
        )
        encoding = getattr(response, "encoding", None)
        if not encoding:
            try:
                response.encoding = response.apparent_encoding or "utf-8"
            except Exception:  # 编码探测失败时退回 utf-8
                pass
        return str(getattr(response, "text", "") or "")

    def get_bytes(
        self,
        url: str,
        *,
        source: str,
        headers: dict[str, str] | None = None,
        ua: str | None = None,
    ) -> bytes:
        """GET 二进制数据（封面下载），同样走按源限速与日上限。"""
        response = self._request(url, source=source, headers=headers, ua=ua)
        return bytes(getattr(response, "content", b"") or b"")

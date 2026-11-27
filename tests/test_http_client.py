"""HttpClient 扩展取法：HTML/二进制、浏览器 UA、限速与日上限（规范 N1）。"""

from __future__ import annotations

import pytest

from app.net.client import BROWSER_UA, DailyLimitExceeded, HttpClient, NetworkError


class FakeResponse:
    def __init__(self, *, status_code: int = 200, payload=None, text: str = "", content: bytes = b"") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.content = content
        self.encoding = ""

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


def _client(response: FakeResponse, **kwargs) -> tuple[HttpClient, FakeSession]:
    session = FakeSession(response)
    return HttpClient(session=session, retries=1, rate_limit_sec=0, **kwargs), session


def test_get_text_uses_browser_ua_without_polluting_session() -> None:
    client, session = _client(FakeResponse(text="<html>豆瓣</html>"))
    text = client.get_text(
        "https://book.douban.com/isbn/9787020002207/",
        source="douban",
        headers={"Referer": "https://book.douban.com/"},
        ua="browser",
    )

    assert text == "<html>豆瓣</html>"
    headers = session.calls[0]["headers"]
    assert headers["User-Agent"] == BROWSER_UA
    assert headers["Referer"] == "https://book.douban.com/"
    assert session.headers == {}


def test_get_bytes_returns_content() -> None:
    client, _session = _client(FakeResponse(content=b"\x89PNG"))
    assert client.get_bytes("https://img/douban.jpg", source="cover", ua="browser") == b"\x89PNG"


def test_get_json_keeps_default_user_agent() -> None:
    client, session = _client(FakeResponse(payload={"ok": True}))
    assert client.get_json("https://api.example/books", source="fake") == {"ok": True}
    assert session.calls[0]["headers"] is None


def test_daily_limit_counts_per_source() -> None:
    client, _session = _client(FakeResponse(payload={}), daily_limit=1)
    client.get_json("https://api.example/1", source="douban")
    assert client.used("douban") == 1
    with pytest.raises(DailyLimitExceeded):
        client.get_json("https://api.example/2", source="douban")


def test_retry_exhausted_raises_network_error() -> None:
    client, _session = _client(FakeResponse(status_code=500))
    with pytest.raises(NetworkError):
        client.get_text("https://book.douban.com/subject/1/", source="douban", ua="browser")

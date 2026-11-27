"""中文源码解析与 lookup 优先级（不联网，全部使用本地 HTML 夹具）。"""

from __future__ import annotations

from app.net.crossref import CrossrefSource, _map
from app.net.douban import DoubanSource, _parse_detail
from app.net.kongfz import parse_search
from app.services.metadata_service import MetadataService

DOUBAN_HTML = """
<html><head><title>红楼梦 (豆瓣)</title></head><body>
<div id="mainpic"><a href="#"><img src="https://img9.doubanio.com/view/subject/l/public/s1.jpg"></a></div>
<div id="info">
  <span><span class="pl">作者</span>: <a href="/author/1">[清] 曹雪芹</a> / 高鹗 著</span><br/>
  <span><span class="pl">出版社:</span> 人民文学出版社<br/></span>
  <span><span class="pl">出版年:</span> 1982-3<br/></span>
  <span><span class="pl">页数:</span> 1200<br/></span>
  <span><span class="pl">ISBN:</span> 9787020002207<br/></span>
</div>
</body></html>
"""

KONGFZ_HTML = """
<div class="item-row">
  <a href="//item.kongfz.com/book/1.html" class="item-row-title">红楼梦</a>
  <div class="item-row-detail">作者：曹雪芹 / 出版社：人民文学出版社 / 出版时间：1982</div>
</div>
<div class="item-row">
  <a href="//item.kongfz.com/book/2.html" class="item-row-title">三体</a>
  <div class="item-row-detail">作者：刘慈欣 / 出版社：重庆出版社 / 出版时间：2008</div>
</div>
"""


def test_douban_detail_fields_are_parsed() -> None:
    item = _parse_detail(DOUBAN_HTML, requested_isbn="9787020002207")
    assert item is not None
    assert item["title"] == "红楼梦"
    assert item["authors"] == ["[清] 曹雪芹", "高鹗"]
    assert item["publisher"] == "人民文学出版社"
    assert item["date"] == "1982-3"
    assert item["isbn"] == "9787020002207"
    assert item["cover_url"].startswith("https://")


def test_douban_rejects_isbn_mismatch() -> None:
    assert _parse_detail(DOUBAN_HTML, requested_isbn="9787536692930") is None


def test_kongfz_search_cards_are_parsed() -> None:
    items = parse_search(KONGFZ_HTML)
    assert [item["title"] for item in items] == ["红楼梦", "三体"]
    assert items[0]["authors"] == ["曹雪芹"]
    assert items[0]["publisher"] == "人民文学出版社"
    assert items[0]["date"] == "1982"


class FakeClient:
    def __init__(self, *, text: str = "", payload=None) -> None:
        self.text = text
        self.payload = payload
        self.calls: list[str] = []

    def get_text(self, url: str, **kwargs) -> str:
        self.calls.append(url)
        return self.text

    def get_json(self, url: str, **kwargs):
        self.calls.append(url)
        return self.payload


def test_douban_source_validates_isbn_through_client() -> None:
    source = DoubanSource(FakeClient(text=DOUBAN_HTML))
    items = source.lookup(isbn="9787020002207")
    assert len(items) == 1 and items[0]["publisher"] == "人民文学出版社"

    missing = DoubanSource(FakeClient(text=DOUBAN_HTML)).lookup(isbn="9787536692930")
    assert missing == []


def test_crossref_mapping() -> None:
    payload = {
        "message": {
            "items": [
                {
                    "title": ["The Great Gatsby"],
                    "author": [{"given": "F. Scott", "family": "Fitzgerald"}],
                    "publisher": "Scribner",
                    "issued": {"date-parts": [[2004, 9, 30]]},
                    "ISBN": ["9780743273565"],
                    "language": "en",
                }
            ]
        }
    }
    items = CrossrefSource(FakeClient(payload=payload)).lookup(title="The Great Gatsby")
    assert items[0]["title"] == "The Great Gatsby"
    assert items[0]["authors"] == ["F. Scott Fitzgerald"]
    assert items[0]["date"] == "2004-9-30"
    assert items[0]["isbn"] == "9780743273565"

    mapped = _map({"title": ["无作者"], "publisher": "某社"})
    assert mapped["authors"] == []


class LookupSource:
    name = "douban"

    def __init__(self) -> None:
        self.lookup_calls = 0
        self.isbn_calls = 0
        self.search_calls = 0

    def lookup(self, *, isbn=None, title=None, authors=None):
        self.lookup_calls += 1
        return [
            {
                "source": "douban",
                "title": "红楼梦",
                "authors": ["曹雪芹"],
                "isbn": "9787020002207",
                "publisher": "人民文学出版社",
                "date": "1982",
                "language": "zh",
            }
        ]

    def by_isbn(self, isbn: str):
        self.isbn_calls += 1
        return []

    def search(self, query: str):
        self.search_calls += 1
        return []


def test_metadata_service_prefers_structured_lookup(db) -> None:
    source = LookupSource()
    service = MetadataService(
        db,
        {"meta": {"enable_network": True}, "sources": {"cache_ttl_days": 30}},
        sources=[source],
    )
    book = {
        "title": "红楼梦",
        "author_raw": "曹雪芹",
        "isbn": "9787020002207",
        "publisher": "人民文学出版社",
        "publish_date": "1982",
        "language": "zh",
    }
    candidates = service.find_candidates(book)
    assert source.lookup_calls == 1
    assert source.isbn_calls == 0 and source.search_calls == 0
    assert candidates[0]["score"] >= 85

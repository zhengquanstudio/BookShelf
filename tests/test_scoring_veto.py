"""打分否决与权重（规范 N4）：ISBN 冲突必须丢弃，而不是靠其它维度凑分。"""

from __future__ import annotations

from app.net.scoring import rank_candidates, reject_reason, score_candidate, why_text


def _book(**extra) -> dict:
    book = {
        "title": "红楼梦",
        "author_raw": "曹雪芹",
        "isbn": "9787020002207",
        "publisher": "人民文学出版社",
        "publish_date": "1982",
        "language": "zh",
    }
    book.update(extra)
    return book


def _candidate(**extra) -> dict:
    item = {
        "source": "douban",
        "title": "红楼梦",
        "authors": ["曹雪芹"],
        "isbn": "9787020002207",
        "publisher": "人民文学出版社",
        "date": "1982",
        "language": "zh",
    }
    item.update(extra)
    return item


def test_isbn_conflict_is_rejected_not_merely_scored() -> None:
    other = _candidate(isbn="9787536692930")
    assert reject_reason(other, _book()) == "isbn:conflict"
    assert score_candidate(other, _book()) == 0
    ranked = rank_candidates([other], _book())
    assert ranked[0]["rejected"] == "isbn:conflict"


def test_invalid_candidate_isbn_is_rejected() -> None:
    bad = _candidate(isbn="9787020002208")
    assert reject_reason(bad, _book()) == "isbn:invalid"


def test_same_title_different_author_stays_below_threshold() -> None:
    wrong_author = _candidate(authors=["余华"], isbn="", publisher="", date="")
    right_author = _candidate()
    ranked = rank_candidates([wrong_author, right_author], _book())
    assert ranked[0]["score"] >= 85
    assert ranked[1]["score"] < 60
    assert "author:hit" in ranked[0]["why"]


def test_missing_isbn_with_same_title_and_author_is_kept() -> None:
    candidate = _candidate(isbn="")
    assert reject_reason(candidate, _book()) == ""
    assert score_candidate(candidate, _book()) > 0


def test_missing_isbn_low_title_is_rejected() -> None:
    candidate = _candidate(isbn="", title="西游记")
    assert reject_reason(candidate, _book()) == "title:low"


def test_source_weight_breaks_ties_instead_of_openlibrary() -> None:
    openlibrary = _candidate(source="openlibrary")
    douban = _candidate(source="douban")
    ranked = rank_candidates([openlibrary, douban], _book())
    assert ranked[0]["source"] == "douban"
    assert ranked[1]["source"] == "openlibrary"


def test_crossref_candidate_has_source_bonus() -> None:
    candidate = {
        "source": "crossref",
        "title": "The Great Gatsby",
        "authors": ["F. Scott Fitzgerald"],
        "isbn": "",
        "publisher": "Scribner",
        "date": "2004",
        "language": "en",
    }
    book = {
        "title": "The Great Gatsby",
        "author_raw": "F. Scott Fitzgerald",
        "publisher": "Scribner",
        "publish_date": "2004",
        "language": "en",
    }
    score = score_candidate(candidate, book)
    assert score >= 45
    assert any(item.startswith("source:crossref") for item in rank_candidates([candidate], book)[0]["why"])


def test_empty_candidate_scores_zero() -> None:
    assert score_candidate({}, {}) == 0


def test_why_text_is_human_readable() -> None:
    assert why_text(["isbn:equal", "title:96", "author:hit", "source:douban"]) == [
        "ISBN 一致",
        "书名 96%",
        "作者一致",
        "来源 douban",
    ]

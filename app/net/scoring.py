"""候选结果置信度打分（规范 §3：先否决，再打分）。

规则要点：
- ISBN 冲突是硬否决，不是扣分；否则靠书名/作者/出版社仍能凑到 70 分造成串书。
- 每个候选额外输出 `why` 列表，UI 直接展示"凭什么给了 92 分"。
- 源权重按实测可信度：豆瓣 3、孔夫子 2、Crossref 2，其余 0。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping, Sequence

from ..core import authors, isbn as isbn_tools, series

try:
    from rapidfuzz import fuzz as _fuzz

    def _ratio(a: str, b: str) -> float:
        return float(_fuzz.token_set_ratio(a, b))

except Exception:  # pragma: no cover
    from difflib import SequenceMatcher

    def _ratio(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio() * 100


SOURCE_WEIGHT = {"douban": 3, "kongfz": 2, "crossref": 2}

_WHY_LABELS = {
    "isbn:equal": "ISBN 一致",
    "author:hit": "作者一致",
    "author:similar": "作者相近",
    "publisher:equal": "出版社一致",
    "year:equal": "同年",
    "year:+1": "年份相近",
    "language:equal": "语言一致",
    "isbn:conflict": "ISBN 冲突",
    "isbn:invalid": "ISBN 非法",
    "title:low": "书名相似度不足",
}


def why_text(items: Sequence[str] | None) -> list[str]:
    """把 why 代码翻译成界面可读的中文短句。"""
    labels: list[str] = []
    for raw in items or []:
        key = str(raw)
        if key.startswith("title:"):
            labels.append(f"书名 {key.split(':', 1)[1]}%")
        elif key.startswith("source:"):
            labels.append(f"来源 {key.split(':', 1)[1]}")
        else:
            labels.append(_WHY_LABELS.get(key, key))
    return labels


def _norm(text: Any) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return "".join(char for char in value if char.isalnum())


def _authors_of(book: Mapping[str, Any]) -> list[str]:
    raw = book.get("author_raw") or book.get("authors") or book.get("author_name") or ""
    return authors.split_authors(raw)


def _language(value: Any) -> str:
    code = str(value or "").strip().casefold()
    mapping = {
        "chi": "zh", "zho": "zh", "zh-cn": "zh", "zh-tw": "zh", "chinese": "zh",
        "eng": "en", "en-us": "en", "en-gb": "en", "english": "en",
        "jpn": "ja", "japanese": "ja", "fra": "fr", "fre": "fr", "french": "fr",
        "deu": "de", "ger": "de", "german": "de",
    }
    return mapping.get(code, code[:2])


def _author_keys(name: str) -> set[str]:
    """原文与规范化译名都作为作者键，兼容 F.S./F. Scott 等写法。"""
    keys = {_norm(name)}
    info = authors.normalize_author(name)
    if info.name_zh:
        keys.add(_norm(info.name_zh))
    keys.discard("")
    return keys


def _title_key(value: Any) -> str:
    """比较用书名：去卷号后做 NFKC + 去标点。"""
    return _norm(series.strip_volume(value))


def reject_reason(candidate: Mapping[str, Any], book: Mapping[str, Any]) -> str:
    """返回否决原因；空串表示可以参与打分。"""
    raw_cand = str(candidate.get("isbn") or "").strip()
    cand_isbn = isbn_tools.normalize(raw_cand) or ""
    if raw_cand and not cand_isbn:
        return "isbn:invalid"
    book_isbn = isbn_tools.normalize(str(book.get("isbn") or "")) or ""
    if book_isbn and cand_isbn and book_isbn != cand_isbn:
        return "isbn:conflict"
    if book_isbn and not cand_isbn:
        title_ratio = _ratio(_title_key(book.get("title")), _title_key(candidate.get("title")))
        if title_ratio < 85:
            return "title:low"
    return ""


def evaluate_candidate(
    candidate: Mapping[str, Any], book: Mapping[str, Any]
) -> tuple[float, list[str], str]:
    """返回（分值, 解释列表, 否决原因）。"""
    reason = reject_reason(candidate, book)
    if reason:
        return 0.0, [], reason

    score = 0.0
    why: list[str] = []
    book_isbn = isbn_tools.normalize(str(book.get("isbn") or "")) or ""
    cand_isbn = isbn_tools.normalize(str(candidate.get("isbn") or "")) or ""
    if book_isbn and cand_isbn and book_isbn == cand_isbn:
        score += 55
        why.append("isbn:equal")

    title_ratio = _ratio(_title_key(book.get("title")), _title_key(candidate.get("title")))
    score += 25.0 * title_ratio / 100.0
    if title_ratio > 0:
        why.append(f"title:{int(round(title_ratio))}")

    book_keys: set[str] = set()
    for name in _authors_of(book):
        book_keys |= _author_keys(name)
    cand_keys: set[str] = set()
    for name in (candidate.get("authors") or []):
        cand_keys |= _author_keys(str(name))
    if book_keys and cand_keys:
        if book_keys & cand_keys:
            score += 8
            why.append("author:hit")
        elif any(_ratio(left, right) >= 70 for left in book_keys for right in cand_keys):
            score += 6
            why.append("author:similar")

    if _norm(book.get("publisher")) and _norm(book.get("publisher")) == _norm(
        candidate.get("publisher")
    ):
        score += 5
        why.append("publisher:equal")

    book_year = _year(book.get("publish_date"))
    cand_year = _year(candidate.get("date"))
    if book_year and cand_year:
        if book_year == cand_year:
            score += 5
            why.append("year:equal")
        elif abs(int(book_year) - int(cand_year)) == 1:
            score += 2
            why.append("year:+1")

    book_lang = _language(book.get("language"))
    cand_lang = _language(candidate.get("language"))
    if book_lang and cand_lang and book_lang == cand_lang:
        score += 2
        why.append("language:equal")

    weight = SOURCE_WEIGHT.get(str(candidate.get("source") or "").casefold(), 0)
    if weight:
        score += weight
        why.append(f"source:{candidate.get('source')}")

    return min(100.0, max(0.0, score)), why, ""


def score_candidate(candidate: Mapping[str, Any], book: Mapping[str, Any]) -> int:
    """候选匹配分（0–100）；命中否决规则返回 0。"""
    score, _why, _reason = evaluate_candidate(dict(candidate), dict(book))
    return int(round(score))


def rank_candidates(
    candidates: Sequence[Mapping[str, Any]], book: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """给每个候选写入 score/why/rejected 并降序返回（不修改入参）。"""
    ranked: list[tuple[dict[str, Any], int]] = []
    for index, candidate in enumerate(candidates):
        item = dict(candidate)
        score, why, reason = evaluate_candidate(item, book)
        item["score"] = int(round(score))
        item["why"] = why
        if reason:
            item["rejected"] = reason
        ranked.append((item, index))
    ranked.sort(
        key=lambda pair: (
            pair[0]["score"],
            SOURCE_WEIGHT.get(str(pair[0].get("source") or "").casefold(), 0),
            -pair[1],
        ),
        reverse=True,
    )
    return [item for item, _index in ranked]


def _year(value: Any) -> str:
    found = re.search(r"(1[5-9]\d{2}|20\d{2})", str(value or ""))
    return found.group(1) if found else ""

"""命名与归档路径算法（文档第 7 章）。

纯函数：不读文件、不写数据库；调用方传入书籍字段与命名规则即可得到目标路径。
M4 的整理预览与执行直接复用本模块。
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import authors, countries, series
from .pathsafe import is_reserved_name, sanitize_segment

_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ILLEGAL = re.compile(r'[\\/:*?"<>|]')
_NOISE = (
    re.compile(r"\[[^\]]*(?:z-?lib|zlibrary|libgen)[^\]]*\]", re.I),
    re.compile(
        r"[\[【（(]\s*(?:高清|全本|完结|精校|校对版|epub\+mobi|azw3\+mobi|mobi|epub|pdf)\s*[\]】）)]",
        re.I,
    ),
    re.compile(r"(?i)[-_ ](?:final|ocr|v\d+|副本|copy)\b"),
)
_TRAILING_FORMAT = re.compile(r"(?i)\s*\b(?:epub|mobi|azw3|pdf|azw|fb2|txt)\b\s*$")
_EMPTY_BRACKETS = re.compile(r"[\[【（(]\s*[\]】）)]")


@dataclass
class NamingRules:
    root: Path = Path("")
    author_dir_template: str = "{作者} [{国家}]"
    file_template: str = "{作者} - {书名}{卷号} ({年份}).{扩展名}"
    chinese_author_no_country: bool = True
    country_style: str = "short"
    hierarchy: str = "author_first"
    series_subdir: bool = False
    volume_style: str = "第N卷"
    illegal_char_replacement: str = "_"
    max_title_len: int = 120
    max_path_len: int = 250
    conflict_policy: str = "suffix"
    action: str = "copy"
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "NamingRules":
        naming = dict((config or {}).get("naming") or {})
        organize = dict((config or {}).get("organize") or {})
        root = str((config or {}).get("library_root") or "")
        return cls(
            root=Path(root) if root else Path(""),
            author_dir_template=str(naming.get("author_dir_template") or "{作者} [{国家}]"),
            file_template=str(naming.get("file_template") or "{作者} - {书名}{卷号} ({年份}).{扩展名}"),
            chinese_author_no_country=bool(naming.get("chinese_author_no_country", True)),
            country_style=str(naming.get("country_style") or "short"),
            hierarchy=str(naming.get("hierarchy") or "author_first"),
            series_subdir=bool(naming.get("series_subdir", False)),
            volume_style=str(naming.get("volume_style") or "第N卷"),
            illegal_char_replacement=str(naming.get("illegal_char_replacement") or "_"),
            max_title_len=int(naming.get("max_title_len") or 120),
            max_path_len=int(naming.get("max_path_len") or 250),
            conflict_policy=str(naming.get("conflict_policy") or "suffix"),
            action=str(organize.get("action") or "copy"),
            extra=naming,
        )


@dataclass
class TargetPlan:
    target_dir: Path
    target_name: str
    target_path: Path
    action: str = "copy"
    status: str = "ready"
    message: str = ""

    @property
    def relative(self) -> str:
        return str(self.target_path)

    def display(self) -> str:
        return str(self.target_path) if self.target_name else "（无目标路径）"


def clean_text(
    value: Any,
    *,
    max_len: int | None = None,
    replacement: str = "_",
    drop_noise: bool = True,
    keep_spaces: bool = True,
) -> str:
    """按文档 7.2 的顺序清洗：NFKC → 去控制符 → 去噪声 → 非法字符 → 截断。"""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = _ZERO_WIDTH.sub("", text)
    text = _CONTROL.sub("", text)
    if drop_noise:
        for pattern in _NOISE:
            text = pattern.sub("", text)
        text = _TRAILING_FORMAT.sub("", text)
        text = re.sub(r"(?i)\.(?:epub|mobi|azw3|pdf|azw|fb2|txt)$", "", text)
    text = _ILLEGAL.sub(replacement or "_", text)
    if keep_spaces:
        text = re.sub(r"\s+", " ", text)
    text = re.sub(rf"{re.escape(replacement or '_')}{{2,}}", replacement or "_", text)
    text = re.sub(r"\s*([,，;；])\s*", r"\1", text)
    text = text.strip(" ._-·,，。;；")
    if max_len and len(text) > max_len:
        text = text[: max(1, int(max_len))].rstrip(" ._-·,，。")
    return text


def _strip_empty_brackets(text: str) -> str:
    """国别未知时模板会留下 `[]`/`【】`，渲染后统一去掉并压缩空白。"""
    value = _EMPTY_BRACKETS.sub("", str(text or ""))
    return re.sub(r"\s{2,}", " ", value).strip()


def _safe_segment(segment: str, rules: NamingRules) -> str:
    value = clean_text(segment, replacement=rules.illegal_char_replacement)
    return sanitize_segment(value, replacement=rules.illegal_char_replacement)


def _mapping(
    *,
    author: str,
    title: str,
    country: str,
    volume: str,
    extension: str,
    subtitle: str = "",
    series_name: str = "",
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    mapping = {
        "作者": author,
        "书名": title,
        "国家": country,
        "卷号": volume,
        "扩展名": extension,
        "副标题": subtitle,
        "系列": series_name,
        "丛书": series_name,
    }
    mapping.update({key: str(value) for key, value in (extra or {}).items()})
    return mapping


def _template_values(book: Mapping[str, Any], author_name: str) -> dict[str, str]:
    """模板扩展变量：年份 / 出版社 / ISBN / 作者全。"""
    found = re.search(r"(1[5-9]\d{2}|20\d{2})", str(book.get("publish_date") or ""))
    all_authors = [
        name for name in authors.split_authors(book.get("author_raw")) if name
    ]
    return {
        "年份": found.group(1) if found else "",
        "出版社": clean_text(book.get("publisher") or "", max_len=40),
        "ISBN": str(book.get("isbn") or ""),
        "作者全": "、".join(all_authors) or author_name,
    }


def _render(template: str, mapping: Mapping[str, str]) -> str:
    class _Safe(dict):
        def __missing__(self, key):  # noqa: D401 - 模板占位缺失时留空
            return ""

    return str(template or "").format_map(_Safe(mapping))


def _book_author(book: Mapping[str, Any]) -> tuple[str, str, str, bool, bool]:
    """返回（显示名, 国别代码, 国别中文, 是否中国作者, 是否待确认）。"""
    raw = str(book.get("author_raw") or "")
    info = book.get("author_info")
    if info is None:
        info = authors.normalize_author(
            book.get("author_name") or raw, book.get("country")
        )
    name = str(book.get("author_name") or getattr(info, "name_zh", "") or "")
    code = str(book.get("country_code") or getattr(info, "country_code", "") or "")
    if not code:
        code = countries.resolve_country(book.get("country") or getattr(info, "country", "")) or ""
    is_chinese = book.get("is_chinese")
    if is_chinese is None:
        is_chinese = countries.is_china(code) or bool(getattr(info, "is_chinese", False))
    needs_confirm = book.get("author_needs_confirm")
    if needs_confirm is None:
        needs_confirm = bool(getattr(info, "needs_confirm", False))
    return name, code, countries.country_zh(code), bool(is_chinese), bool(needs_confirm)


def _book_volume(book: Mapping[str, Any]) -> tuple[int | None, str]:
    volume = book.get("volume")
    try:
        volume = int(volume) if volume not in (None, "") else None
    except (TypeError, ValueError):
        volume = None
    raw = str(book.get("volume_raw") or "")
    if not volume:
        title = str(book.get("title") or "")
        stem = Path(str(book.get("file_path") or "")).stem
        for candidate in (title, stem):
            match = series.extract_volume(candidate)
            if match:
                volume, raw = match.volume, raw or match.raw
                break
    return volume, raw


def _fallback_status(book: Mapping[str, Any]) -> tuple[str, str]:
    status = str(book.get("status") or "ok")
    if book.get("drm_protected") or status == "drm":
        return "drm", "受 DRM 保护，不生成归档路径"
    if status == "failed":
        return "failed", "识别失败，不参与整理"
    if status == "skipped" or book.get("dup_group_id"):
        return "skip", "重复或已跳过，不参与整理"
    return "", ""


def plan_target(
    book: Mapping[str, Any],
    rules: NamingRules,
    existing: Iterable[str | Path] | None = None,
) -> TargetPlan:
    """计算一本书的归档目标；不写盘。"""
    status, reason = _fallback_status(book)
    if status:
        return TargetPlan(Path(""), "", Path(""), rules.action, status, reason)

    title = clean_text(book.get("title") or Path(str(book.get("file_path") or "")).stem,
                       max_len=rules.max_title_len,
                       replacement=rules.illegal_char_replacement)
    if series.extract_volume(title):
        title = series.strip_volume(title) or title
    author_name, country_code, country_zh, is_chinese, needs_confirm = _book_author(book)
    author_name = clean_text(author_name, replacement=rules.illegal_char_replacement)
    if not title or not author_name:
        return TargetPlan(Path(""), "", Path(""), rules.action, "failed",
                          "书名或作者缺失，无法生成归档路径")

    display_country = countries.render_country(country_code, rules.country_style) or country_zh
    volume, _volume_raw = _book_volume(book)
    volume_label = series.volume_text(volume, rules.volume_style)
    extension = str(book.get("format") or Path(str(book.get("file_path") or "")).suffix.lstrip("."))
    extension = extension.lower()

    author_dir = _author_directory(
        author_name, display_country, is_chinese, rules
    )
    extra = _template_values(book, author_name)
    file_name = _file_name(
        author_name, title, display_country, volume_label, extension,
        str(book.get("subtitle") or ""), str(book.get("series_name") or book.get("series") or ""),
        rules, extra=extra,
    )
    directories = _directories(book, author_dir, rules)
    relative = Path(*directories, file_name) if directories else Path(file_name)

    relative = _fit_path(relative, book, rules, author_name, display_country,
                         volume_label, extension, directories, extra)

    plan_status = "ready"
    messages: list[str] = []
    if needs_confirm:
        plan_status = "conflict"
        messages.append("作者译名待确认")
    name = relative.name
    if isinstance(existing, (set, frozenset)):
        # 调用方传入集合时视为已 casefold 的路径集合，避免大书库预览时反复重建。
        path_set = existing
    else:
        path_set = {str(Path(item)).casefold() for item in (existing or [])}
    if path_set and str(relative).casefold() in path_set:
        if rules.conflict_policy == "skip":
            plan_status = "skip"
            messages.append("目标已存在，按设置跳过")
        elif rules.conflict_policy == "overwrite":
            plan_status = "conflict"
            messages.append("目标已存在，执行时覆盖")
        else:
            name = _unique_name(name, str(relative.parent), path_set)
            relative = relative.parent / name
            plan_status = "conflict"
            messages.append("目标已存在，追加序号")
    return TargetPlan(
        target_dir=relative.parent,
        target_name=name,
        target_path=relative,
        action=rules.action,
        status=plan_status,
        message="；".join(messages),
    )


def _author_directory(
    author: str, country: str, is_chinese: bool, rules: NamingRules
) -> str:
    if is_chinese and rules.chinese_author_no_country:
        return _safe_segment(author, rules)
    if not country:
        return _safe_segment(author, rules)
    rendered = _render(
        rules.author_dir_template,
        _mapping(author=author, title="", country=country, volume="", extension=""),
    )
    return _safe_segment(rendered, rules)


def _file_name(
    author: str,
    title: str,
    country: str,
    volume: str,
    extension: str,
    subtitle: str,
    series_name: str,
    rules: NamingRules,
    extra: Mapping[str, str] | None = None,
) -> str:
    template = str(rules.file_template or "{作者} - {书名}{卷号} ({年份}).{扩展名}")
    if not volume:
        for token in (" {卷号}", "{卷号}", "（{卷号}）", "({卷号})", "【{卷号}】"):
            template = template.replace(token, "")
    if not (extra or {}).get("年份"):
        for token in (
            " ({年份})", "（{年份}）", "({年份})", "（{年份}）",
            " [{年份}]", "[{年份}]", "【{年份}】", " {年份}", "-{年份}", "- {年份}",
        ):
            template = template.replace(token, "")
    rendered = _render(
        template,
        _mapping(
            author=author,
            title=title,
            country=country,
            volume=volume,
            extension=extension,
            subtitle=subtitle,
            series_name=series_name,
            extra=extra,
        ),
    )
    rendered = clean_text(
        rendered,
        replacement=rules.illegal_char_replacement,
        drop_noise=False,
    )
    rendered = _strip_empty_brackets(rendered)
    if not rendered:
        rendered = f"{author}-{title}"
    stem, suffix = os.path.splitext(rendered)
    if not suffix and extension:
        rendered = f"{rendered}.{extension}"
    if is_reserved_name(stem):
        rendered = f"{stem}_{suffix}"
    return rendered


def _directories(book: Mapping[str, Any], author_dir: str, rules: NamingRules) -> list[str]:
    series_name = clean_text(
        book.get("series_name") or book.get("series") or "",
        max_len=rules.max_title_len,
        replacement=rules.illegal_char_replacement,
    )
    if not series_name:
        return [author_dir]
    series_dir = _safe_segment(series_name, rules)
    if rules.series_subdir:
        return [author_dir, series_dir]
    if rules.hierarchy == "author_first":
        return [author_dir, series_dir]
    return [series_dir, author_dir]


def _unique_name(name: str, parent: str, path_set: set[str]) -> str:
    stem, suffix = os.path.splitext(name)
    index = 2
    while index < 1000:
        candidate = f"{stem} ({index}){suffix}"
        full = str(Path(parent) / candidate).casefold() if parent else candidate.casefold()
        if full not in path_set:
            return candidate
        index += 1
    return name


def unique_name(
    name: str, parent: str | Path, existing: Iterable[str | Path]
) -> str:
    """生成不冲突的文件名：原名可用则原样返回，冲突才追加 (2)/(3)。"""
    path_set = {str(Path(item)).casefold() for item in (existing or [])}
    full = str(Path(parent) / name).casefold()
    if full not in path_set:
        return name
    return _unique_name(name, str(parent), path_set)


def _fit_path(
    relative: Path,
    book: Mapping[str, Any],
    rules: NamingRules,
    author: str,
    country: str,
    volume: str,
    extension: str,
    directories: list[str],
    extra: Mapping[str, str] | None = None,
) -> Path:
    """整路径超长时逐步缩短书名，保证 ≤ max_path_len。"""
    limit = max(60, int(rules.max_path_len))
    title = clean_text(book.get("title") or "", max_len=rules.max_title_len,
                       replacement=rules.illegal_char_replacement)
    while len(str(relative)) > limit and len(title) > 12:
        title = title[:-6].rstrip(" ._-·,，")
        name = _file_name(
            author, title, country, volume, extension,
            str(book.get("subtitle") or ""),
            str(book.get("series_name") or book.get("series") or ""), rules,
            extra=extra,
        )
        relative = Path(*directories, name) if directories else Path(name)
    return relative

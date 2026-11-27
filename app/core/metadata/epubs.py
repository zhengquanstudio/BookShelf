"""EPUB 内嵌元数据：标准库 zipfile + ElementTree 解析 OPF。"""

from __future__ import annotations

import posixpath
import re
import unicodedata
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from xml.etree import ElementTree

from ...errors import ExtractError
from ..isbn import normalize
from .normalize import finalize


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _find_all(root: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [node for node in root.iter() if _local(node.tag) == name]


def _text(node: ElementTree.Element | None, tag: str) -> str:
    if node is None:
        return ""
    for child in node:
        if _local(child.tag) == tag:
            return (child.text or "").strip()
    return ""


def _entry_index(archive: zipfile.ZipFile) -> dict[str, str]:
    """casefold/NFC 归一后的条目名 → 真实条目名；索引挂在 archive 上只建一次。

    条目数超过 2000 的巨型 zip 不缓存（避免长驻内存），但匹配规则一致。
    """
    cached = getattr(archive, "_bookshelf_entry_index", None)
    if cached is not None:
        return cached
    index: dict[str, str] = {}
    for real in archive.namelist():
        index.setdefault(real.casefold(), real)
        normalized = unicodedata.normalize("NFC", real)
        if normalized != real:
            index.setdefault(normalized.casefold(), real)
    if len(index) <= 2000:
        archive._bookshelf_entry_index = index  # type: ignore[attr-defined]
    return index


def _resolve_entry(archive: zipfile.ZipFile, name: str) -> str:
    """按 字面 → 忽略大小写 → NFC 归一 → unquote 逐级降级匹配 zip 条目名。

    返回真实条目名，供 ``archive.read()`` 使用；全部不中时抛 KeyError。
    修复 container.xml 写小写 ``ops/fb.opf``、zip 里却是 ``OPS/fb.opf`` 这类书。
    """
    if name in archive.NameToInfo:
        return name
    index = _entry_index(archive)
    for candidate in (name, unicodedata.normalize("NFC", name)):
        hit = index.get(candidate.casefold())
        if hit is not None:
            return hit
    decoded = unquote(name)
    if decoded != name:
        if decoded in archive.NameToInfo:
            return decoded
        for candidate in (decoded, unicodedata.normalize("NFC", decoded)):
            hit = index.get(candidate.casefold())
            if hit is not None:
                return hit
    raise KeyError(name)


def _read_xml(archive: zipfile.ZipFile, name: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(archive.read(_resolve_entry(archive, name)))
    except (KeyError, ElementTree.ParseError) as exc:
        raise ExtractError(f"无法读取 {name}：{exc}") from exc


def _package_path(archive: zipfile.ZipFile) -> str:
    try:
        container = _read_xml(archive, "META-INF/container.xml")
        for node in container.iter():
            if _local(node.tag) == "rootfile" and node.get("full-path"):
                return node.get("full-path", "")
    except ExtractError:
        pass
    for name in archive.namelist():
        if name.lower().endswith(".opf"):
            return name
    raise ExtractError("EPUB 缺少 OPF 包文件")


def _is_drm(archive: zipfile.ZipFile) -> bool:
    try:
        raw = archive.read(_resolve_entry(archive, "META-INF/encryption.xml")).lower()
    except KeyError:
        return False
    # 字体混淆很常见且无害；只有正文被加密才视为 DRM。
    return any(token in raw for token in (b".xhtml", b".html", b".epub"))


def _cover_bytes(
    archive: zipfile.ZipFile,
    manifest: list[tuple[str, str, str, str]],
    cover_id: str,
    base_dir: str,
) -> bytes:
    image_types = ("image/jpeg", "image/png", "image/gif", "image/webp")
    candidates: list[tuple[str, str, str, str]] = []
    for item in manifest:
        ident, href, media_type, properties = item
        if media_type not in image_types:
            continue
        if ident == cover_id or "cover-image" in properties.split():
            candidates.insert(0, item)
        elif "cover" in ident.lower() or "cover" in href.lower():
            candidates.append(item)
    for _ident, href, _media_type, _properties in candidates:
        path = posixpath.normpath(posixpath.join(base_dir, href.split("#")[0]))
        for name in (path, path.lstrip("./")):
            try:
                return archive.read(_resolve_entry(archive, name))
            except KeyError:
                continue
    return b""


def _split_creators(values: list[str]) -> list[str]:
    """一个 dc:creator 里可能塞多作者，按规范分隔符拆开。"""
    names: list[str] = []
    for value in values:
        for part in re.split(r"\s*[;；、&|]\s*|\s+/\s+", value or ""):
            name = part.strip()
            if name:
                names.append(name)
    return names


def extract(path: Path) -> dict[str, Any]:
    """解析 EPUB；任何结构异常都转为 ok=False。"""
    try:
        with zipfile.ZipFile(path) as archive:
            opf_name = _package_path(archive)
            try:
                # 统一成真实条目名：manifest 相对路径（封面、正文）以它为基准。
                opf_name = _resolve_entry(archive, opf_name)
            except KeyError:
                pass
            opf = _read_xml(archive, opf_name)
            base_dir = posixpath.dirname(opf_name)

            metadata = None
            for node in opf.iter():
                if _local(node.tag) == "metadata":
                    metadata = node
                    break

            titles = [
                (node.text or "").strip()
                for node in _find_all(opf, "title")
                if (node.text or "").strip()
            ]
            authors = _split_creators([
                (node.text or "").strip()
                for node in _find_all(opf, "creator")
                if (node.text or "").strip()
            ])
            identifiers = [
                (node.text or "").strip() for node in _find_all(opf, "identifier")
            ]
            isbn = ""
            for value in identifiers:
                normalized = normalize(value)
                if normalized:
                    isbn = normalized
                    break

            manifest: list[tuple[str, str, str, str]] = []
            for node in opf.iter():
                if _local(node.tag) == "item":
                    manifest.append(
                        (
                            node.get("id", ""),
                            node.get("href", ""),
                            node.get("media-type", ""),
                            node.get("properties", ""),
                        )
                    )

            cover_id = ""
            for node in opf.iter():
                if _local(node.tag) == "meta" and node.get("name", "").lower() == "cover":
                    cover_id = node.get("content", "")

            series = ""
            series_index = ""
            if metadata is not None:
                for node in metadata:
                    local = _local(node.tag)
                    name = node.get("name", "").lower()
                    prop = node.get("property", "").lower()
                    text = (node.text or "").strip()
                    if local == "meta" and name == "calibre:series":
                        series = node.get("content", "").strip()
                    elif local == "meta" and name == "calibre:series_index":
                        series_index = node.get("content", "").strip()
                    elif local == "meta" and prop == "belongs-to-collection" and text:
                        series = series or text
                    elif local == "meta" and prop == "group-position" and text:
                        series_index = series_index or text

            result = {
                "title": titles[0] if titles else "",
                "subtitle": titles[1] if len(titles) > 1 else "",
                "authors": authors,
                "isbn": isbn,
                "publisher": _text(metadata, "publisher"),
                "date": _text(metadata, "date")[:32],
                "language": _text(metadata, "language"),
                "series": series,
                "series_index": series_index,
                "description": _text(metadata, "description"),
                "cover_bytes": _cover_bytes(archive, manifest, cover_id, base_dir),
                "drm": _is_drm(archive),
            }
            return finalize(result, ok=True)
    except (zipfile.BadZipFile, OSError, ExtractError) as exc:
        return finalize({}, ok=False, reason=f"EPUB 解析失败：{exc}")

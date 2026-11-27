"""EPUB 内嵌元数据回写（R3c）。

流程：备份 `<book>.epub.bak` → 读取并修改 OPF → 按原条目顺序与压缩方式
重新打包到临时文件 → 原子替换原文件。失败时原文件保持不变，备份保留。
"""

from __future__ import annotations

import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Mapping
from xml.etree import ElementTree

from ...errors import ExtractError
from .epubs import _local, _package_path, _resolve_entry

DC_NS = "http://purl.org/dc/elements/1.1/"
OPF_NS = "http://www.idpf.org/2007/opf"

# 库里字段 → OPF 元素；顺序即写入顺序。
_DC_FIELDS = (
    ("title", "title"),
    ("author", "creator"),
    ("publisher", "publisher"),
    ("publish_date", "date"),
    ("language", "language"),
)


def _register_namespaces(raw: bytes) -> None:
    """按原文件声明注册前缀，避免 ElementTree 输出 ns0:title。"""
    for prefix, uri in re.findall(
        rb'xmlns(?::([A-Za-z_][\w.\-]*))?="([^"]+)"', raw
    ):
        try:
            ElementTree.register_namespace(
                prefix.decode("utf-8", "ignore"), uri.decode("utf-8", "ignore")
            )
        except ValueError:
            # xml / xmlns 等保留前缀不允许注册，忽略即可。
            continue


def _parse(raw: bytes) -> ElementTree.Element:
    parser = ElementTree.XMLParser(target=ElementTree.TreeBuilder(insert_comments=True))
    try:
        return ElementTree.fromstring(raw, parser=parser)
    except ElementTree.ParseError as exc:
        raise ExtractError(f"OPF 解析失败：{exc}") from exc


def _metadata_node(root: ElementTree.Element) -> ElementTree.Element:
    for node in root.iter():
        if _local(node.tag) == "metadata":
            return node
    raise ExtractError("OPF 缺少 metadata 节点")


def _namespace_of(root: ElementTree.Element, local: str, fallback: str) -> str:
    for node in root.iter():
        if _local(node.tag) == local and node.tag.startswith("{"):
            return node.tag.split("}", 1)[0][1:]
    return fallback


def _set_text(
    metadata: ElementTree.Element, local: str, value: str, namespace: str
) -> None:
    """更新首个同名元素并删除重复项；值允许为空字符串（表示清空）。"""
    nodes = [child for child in metadata if _local(child.tag) == local]
    if nodes:
        nodes[0].text = value
        for extra in nodes[1:]:
            metadata.remove(extra)
        return
    if value:
        element = ElementTree.SubElement(metadata, f"{{{namespace}}}{local}")
        element.text = value


def _set_identifier(
    metadata: ElementTree.Element, value: str, namespace: str
) -> None:
    """优先改 ISBN 标识；没有时改第一个 identifier；空值不清除原标识。"""
    if not value:
        return
    identifiers = [child for child in metadata if _local(child.tag) == "identifier"]
    if not identifiers:
        element = ElementTree.SubElement(metadata, f"{{{namespace}}}identifier")
        element.set("id", "isbn")
        element.text = value
        return
    target = identifiers[0]
    for node in identifiers:
        if "isbn" in (node.get("id") or "").lower():
            target = node
            break
    target.text = value


def _set_page_count(
    root: ElementTree.Element, metadata: ElementTree.Element, page_count: int
) -> None:
    """优先更新已有的页数 meta；没有时补一条 schema:numberOfPages。"""
    for node in metadata:
        if _local(node.tag) != "meta":
            continue
        name = (node.get("name") or "").lower()
        prop = (node.get("property") or "").lower()
        if name in ("page_count", "pages") or prop.endswith("numberofpages"):
            if node.get("content") is not None:
                node.set("content", str(page_count))
            else:
                node.text = str(page_count)
            return
    opf_ns = _namespace_of(root, "package", OPF_NS)
    node = ElementTree.SubElement(metadata, f"{{{opf_ns}}}meta")
    node.set("property", "schema:numberOfPages")
    node.text = str(page_count)


def _update_opf(
    raw: bytes, fields: Mapping[str, Any], page_count: int | None
) -> bytes:
    _register_namespaces(raw)
    root = _parse(raw)
    metadata = _metadata_node(root)
    dc_ns = _namespace_of(root, "title", DC_NS)

    for field, local in _DC_FIELDS:
        value = str(fields.get(field) or "").strip()
        if local == "language" and not value:
            continue
        # 作者/出版社/日期为空时保留原值，避免写出非法的空 dc 元素。
        if not value and local in ("creator", "publisher", "date", "language"):
            continue
        _set_text(metadata, local, value, dc_ns)

    _set_identifier(metadata, str(fields.get("isbn") or "").strip(), dc_ns)
    if page_count and page_count > 0:
        _set_page_count(root, metadata, page_count)

    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


def write_embedded_metadata(
    path: Path | str,
    fields: Mapping[str, Any],
    *,
    page_count: int | None = None,
) -> Path:
    """把字段写回 EPUB 的 OPF，返回备份路径。失败时抛出异常且原文件不变。"""
    path = Path(path)
    if not path.is_file():
        raise ExtractError("数据文件不存在，无法回写内嵌元数据")
    backup = path.with_name(path.name + ".bak")
    try:
        shutil.copy2(path, backup)
    except OSError as exc:
        raise ExtractError(f"无法创建备份：{exc}") from exc

    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with zipfile.ZipFile(path) as source:
            opf_name = _resolve_entry(source, _package_path(source))
            new_opf = _update_opf(source.read(opf_name), fields, page_count)
            with zipfile.ZipFile(temp, "w") as target:
                for info in source.infolist():
                    data = (
                        new_opf
                        if info.filename == opf_name
                        else source.read(info.filename)
                    )
                    clone = zipfile.ZipInfo(info.filename, info.date_time)
                    clone.compress_type = info.compress_type
                    clone.comment = info.comment
                    clone.extra = info.extra
                    clone.internal_attr = info.internal_attr
                    clone.external_attr = info.external_attr
                    clone.create_system = info.create_system
                    target.writestr(clone, data)
        os.replace(temp, path)
    except (ExtractError, zipfile.BadZipFile, OSError):
        temp.unlink(missing_ok=True)
        raise
    except Exception as exc:  # 打包期间的任意异常都不应破坏原文件
        temp.unlink(missing_ok=True)
        raise ExtractError(f"重新打包失败：{exc}") from exc
    return backup


def backup_path(path: Path | str) -> Path:
    """与写入逻辑一致的备份路径，供界面提示或检查是否存在。"""
    return Path(path).with_name(Path(path).name + ".bak")

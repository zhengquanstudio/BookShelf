"""MOBI / AZW3 → EPUB 转换（纯标准库实现，离线可用）。

思路（对应需求文档 3.4）：
1. 解析 PalmDB 记录表与 PalmDOC/MOBI 头；
2. 加密标记非 0 直接判定为 DRM，不做任何解密；
3. 解压文本记录（PalmDOC LZ77 / 无压缩），提取图片记录；
4. 生成最小但合法的 EPUB 3：mimetype 首条不压缩 + container.xml + content.opf + nav + 章节。
"""

from __future__ import annotations

import re
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

_COMPRESSION_NONE = 1
_COMPRESSION_PALMDOC = 2
_COMPRESSION_HUFF = 17480

_PAGEBREAK = re.compile(r"<\s*mbp:pagebreak[^>]*>", re.IGNORECASE)
_MOBI_TAG = re.compile(r"</?\s*mbp:[^>]*>", re.IGNORECASE)
_HEADING = re.compile(r"<\s*h[1-3][^>]*>(.*?)<\s*/\s*h[1-3]\s*>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")

_IMAGE_MAGIC = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF89a", ".gif"),
    (b"GIF87a", ".gif"),
)


class MobiError(Exception):
    """MOBI/AZW3 结构异常或不受支持。"""


class DrmProtected(MobiError):
    """文件带加密标记，禁止继续解析。"""


@dataclass
class MobiContent:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    language: str = ""
    chapters: list[tuple[str, str]] = field(default_factory=list)  # (标题, HTML 片段)
    images: list[tuple[str, bytes]] = field(default_factory=list)  # (文件名, 数据)


def _records(data: bytes) -> list[bytes]:
    if len(data) < 86:
        raise MobiError("文件过小，不是有效的 MOBI/AZW3")
    count = int.from_bytes(data[76:78], "big")
    if count <= 0:
        raise MobiError("PalmDB 记录数为 0")
    table_end = 78 + count * 8
    if table_end > len(data):
        raise MobiError("PalmDB 记录表越界")
    offsets = [
        int.from_bytes(data[78 + index * 8 : 82 + index * 8], "big")
        for index in range(count)
    ]
    offsets.append(len(data))
    records: list[bytes] = []
    for index in range(count):
        start, end = offsets[index], offsets[index + 1]
        if start >= end or end > len(data):
            raise MobiError(f"PalmDB 第 {index} 条记录偏移异常")
        records.append(data[start:end])
    return records


def _palmdoc_decompress(raw: bytes) -> bytes:
    """PalmDOC LZ77 解压（MOBI 文本记录的标准压缩方式）。"""
    out = bytearray()
    position = 0
    size = len(raw)
    while position < size:
        value = raw[position]
        position += 1
        if value == 0:
            out.append(0)
        elif value <= 8:
            out.extend(raw[position : position + value])
            position += value
        elif value <= 0x7F:
            out.append(value)
        elif value <= 0xBF:
            if position >= size:
                break
            pair = (value << 8) | raw[position]
            position += 1
            distance = (pair >> 3) & 0x07FF
            length = (pair & 0x07) + 3
            if distance == 0 or distance > len(out):
                break
            for _ in range(length):
                out.append(out[-distance])
        else:
            out.append(0x20)
            out.append(value ^ 0x80)
    return bytes(out)


def _decode_text(raw: bytes, encoding: str) -> str:
    order = [encoding or "utf-8", "utf-8", "gb18030", "cp1252"]
    for codec in order:
        try:
            return raw.decode(codec)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "ignore")


def _exth_records(data: bytes, start: int, count: int) -> dict[int, list[bytes]]:
    records: dict[int, list[bytes]] = {}
    position = start + 12
    for _ in range(max(0, count)):
        if position + 8 > len(data):
            break
        kind = int.from_bytes(data[position : position + 4], "big")
        length = int.from_bytes(data[position + 4 : position + 8], "big")
        if length < 8 or position + length > len(data):
            break
        records.setdefault(kind, []).append(data[position + 8 : position + length])
        position += length
    return records


@dataclass
class _Section:
    start: int
    compression: int
    text_count: int
    encoding: str
    first_image: int
    exth: dict[int, list[bytes]]
    boundary: int


def _read_section(records: list[bytes], start: int) -> _Section:
    if start >= len(records):
        raise MobiError("MOBI 头记录不存在")
    record0 = records[start]
    if len(record0) < 24:
        raise MobiError("PalmDOC 头不完整")
    compression = int.from_bytes(record0[0:2], "big")
    text_count = int.from_bytes(record0[8:10], "big")
    encryption = int.from_bytes(record0[12:14], "big")
    if encryption:
        raise DrmProtected("文件带加密标记，无法内嵌阅读")

    encoding = "cp1252"
    first_image = 0
    exth: dict[int, list[bytes]] = {}
    boundary = 0
    if record0[16:20] == b"MOBI":
        mobi = record0[16:]
        try:
            header_length = int.from_bytes(mobi[4:8], "big")
            if int.from_bytes(mobi[12:16], "big") == 65001:
                encoding = "utf-8"
            first_image = int.from_bytes(mobi[92:96], "big")
            flags = int.from_bytes(mobi[112:116], "big")
            if flags & 0x40:
                exth_start = 16 + header_length
                if record0[exth_start : exth_start + 4] == b"EXTH":
                    count = int.from_bytes(record0[exth_start + 8 : exth_start + 12], "big")
                    exth = _exth_records(record0, exth_start, count)
                    boundary = int.from_bytes((exth.get(121) or [b"\0\0\0\0"])[0][:4], "big")
        except (IndexError, ValueError):
            pass
    return _Section(start, compression, text_count, encoding, first_image, exth, boundary)


def _image_extension(data: bytes) -> str:
    for magic, ext in _IMAGE_MAGIC:
        if data.startswith(magic):
            return ext
    return ""


def _extract_images(
    records: list[bytes], section: _Section
) -> tuple[list[tuple[int, str, bytes]], dict[int, str]]:
    """返回 (记录序号, 文件名, 数据) 列表与 recindex → 文件名映射。"""
    candidates: list[int] = []
    if section.first_image:
        candidates.append(section.start + section.first_image if section.start else section.first_image)
        if section.start:
            candidates.append(section.first_image)
    result: list[tuple[int, str, bytes]] = []
    mapping: dict[int, str] = {}
    seen: set[int] = set()
    for base in candidates:
        if base <= 0:
            continue
        position = base
        while position < len(records) and position not in seen:
            data = records[position]
            extension = _image_extension(data)
            if not extension:
                break
            name = f"img{len(result) + 1:05d}{extension}"
            result.append((position, name, data))
            mapping[position - base + 1] = name
            seen.add(position)
            position += 1
        if result:
            break
    return result, mapping


def _chapter_title(html: str, index: int) -> str:
    match = _HEADING.search(html)
    if match:
        text = _TAGS.sub("", match.group(1))
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            return text[:60]
    return f"第 {index} 节"


def _rewrite_images(html: str, mapping: dict[int, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        recindex = int(match.group(1))
        name = mapping.get(recindex)
        if not name:
            return ""
        return f'<img src="../images/{name}" alt=""/>'

    return re.sub(
        r"<\s*(?:img|image)[^>]*?recindex\s*=\s*\"0*(\d+)\"[^>]*>",
        replace,
        html,
        flags=re.IGNORECASE,
    )


def parse(path: Path) -> MobiContent:
    """解析 MOBI/AZW3 为章节与图片；受 DRM 保护时抛 DrmProtected。"""
    data = Path(path).read_bytes()
    records = _records(data)
    section = _read_section(records, 0)

    # 双格式 AZW3：EXTH 121 指向 KF8 段起始记录，真实内容在 KF8 段。
    if section.boundary and section.boundary < len(records):
        try:
            section = _read_section(records, section.boundary)
        except MobiError:
            pass

    if section.compression not in (_COMPRESSION_NONE, _COMPRESSION_PALMDOC):
        if section.compression == _COMPRESSION_HUFF:
            raise MobiError("HUFF/CDIC 压缩暂不支持，请安装 Calibre 后重试")
        raise MobiError(f"未知压缩格式：{section.compression}")

    chunks: list[bytes] = []
    first_text = section.start + 1
    for index in range(section.text_count):
        position = first_text + index
        if position >= len(records):
            break
        chunk = records[position]
        if section.compression == _COMPRESSION_PALMDOC:
            chunk = _palmdoc_decompress(chunk)
        if chunk.endswith(b"\xe9\x8e\r\n"):
            chunk = chunk[:-4]
        chunks.append(chunk)
    raw_text = b"".join(chunks)
    if not raw_text:
        raise MobiError("没有解析到正文")

    text = _decode_text(raw_text, section.encoding)
    text = text.replace("\x00", "")

    images, mapping = _extract_images(records, section)
    parts = [part for part in _PAGEBREAK.split(text) if part.strip()]
    if not parts:
        parts = [text]

    chapters: list[tuple[str, str]] = []
    for index, part in enumerate(parts, start=1):
        cleaned = _MOBI_TAG.sub("", part)
        cleaned = _rewrite_images(cleaned, mapping)
        title = _chapter_title(cleaned, index)
        chapters.append((title, cleaned.strip()))

    # 书名优先取 EXTH 503，其次 MOBI 头里的 full name，最后用文件名。
    title = ""
    if section.exth.get(503):
        title = _decode_text(section.exth[503][0], section.encoding).strip()
    if not title:
        record0 = records[0]
        try:
            mobi = record0[16:]
            name_offset = int.from_bytes(mobi[68:72], "big")
            name_length = int.from_bytes(mobi[72:76], "big")
            if name_length and name_offset + name_length <= len(record0):
                title = _decode_text(
                    record0[name_offset : name_offset + name_length], section.encoding
                ).strip()
        except (IndexError, ValueError):
            title = ""
    if not title:
        title = Path(path).stem

    authors = [
        _decode_text(item, section.encoding).strip()
        for item in section.exth.get(100, [])
    ]
    authors = [item for item in authors if item]
    language = (
        _decode_text(section.exth[524][0], section.encoding).strip()
        if section.exth.get(524)
        else ""
    )
    return MobiContent(
        title=title,
        authors=authors,
        language=language,
        chapters=chapters,
        images=[(name, payload) for _pos, name, payload in images],
    )


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _chapter_document(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml" lang="zh">\n'
        "<head><meta charset=\"utf-8\"/><title>"
        f"{_escape(title)}</title></head>\n"
        f"<body>{body}</body>\n</html>"
    )


def build_epub(content: MobiContent, destination: Path) -> Path:
    """把解析结果写成最小 EPUB 3；返回目标路径。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    book_id = f"urn:uuid:{uuid.uuid4()}"
    manifest: list[str] = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
    ]
    spine: list[str] = []
    chapters_xml: list[tuple[str, str]] = []

    for index, (title, body) in enumerate(content.chapters, start=1):
        name = f"ch{index:03d}.html"
        manifest.append(
            f'<item id="ch{index}" href="text/{name}" media-type="text/html"/>'
        )
        spine.append(f'<itemref idref="ch{index}"/>')
        chapters_xml.append((name, _chapter_document(title, body)))

    nav_items = "\n".join(
        f'<li><a href="text/ch{index:03d}.html">{_escape(title)}</a></li>'
        for index, (title, _body) in enumerate(content.chapters, start=1)
    )

    image_manifest: list[str] = []
    for index, (name, _data) in enumerate(content.images, start=1):
        image_manifest.append(
            f'<item id="img{index}" href="images/{name}" media-type="image/'
            f"{'jpeg' if name.endswith('.jpg') else name.rsplit('.', 1)[-1]}\"/>"
        )

    authors = "".join(
        f"<dc:creator>{_escape(item)}</dc:creator>" for item in content.authors
    )
    language = content.language or "zh"
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="BookId">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="BookId">{book_id}</dc:identifier>\n'
        f"    <dc:title>{_escape(content.title)}</dc:title>\n"
        f"    {authors}\n"
        f"    <dc:language>{_escape(language)}</dc:language>\n"
        "  </metadata>\n"
        "  <manifest>\n    " + "\n    ".join(manifest + image_manifest) + "\n  </manifest>\n"
        "  <spine>\n    " + "\n    ".join(spine) + "\n  </spine>\n"
        "</package>\n"
    )

    nav = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" lang="zh">\n'
        "<head><meta charset=\"utf-8\"/><title>目录</title></head>\n"
        "<body><nav epub:type=\"toc\" id=\"toc\"><h1>目录</h1><ol>\n"
        f"{nav_items}\n"
        "</ol></nav></body></html>\n"
    )

    container = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        "  <rootfiles>\n"
        '    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>\n'
        "  </rootfiles>\n"
        "</container>\n"
    )

    with zipfile.ZipFile(destination, "w") as archive:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        archive.writestr(info, "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", opf)
        archive.writestr("OEBPS/nav.xhtml", nav)
        for name, document in chapters_xml:
            archive.writestr(f"OEBPS/text/{name}", document)
        for name, payload in content.images:
            archive.writestr(f"OEBPS/images/{name}", payload)
    return destination

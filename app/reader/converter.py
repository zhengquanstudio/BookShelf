"""阅读前准备：格式识别、DRM 检测、MOBI/AZW3 → EPUB 转换与缓存。"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .. import config
from ..core.hashing import quick_hash
from ..logger import get_logger
from . import mobi

log = get_logger("reader")


@dataclass
class PreparedBook:
    """交给前端渲染的本地文件。"""

    kind: str = ""  # epub / pdf
    path: Path | None = None
    drm: bool = False
    error: str = ""
    converted: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.path) and not self.drm and not self.error


class ConvertError(Exception):
    """转换失败，需要向用户展示错误页。"""


def _epub_drm(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read("META-INF/encryption.xml").lower()
    except (KeyError, zipfile.BadZipFile, OSError):
        return False
    return any(token in raw for token in (b".xhtml", b".html", b".epub"))


def _pdf_problem(path: Path) -> tuple[bool, str]:
    """返回 (是否受保护, 错误说明)；空密码可解密的 PDF 视为可用。"""
    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # pypdf 抛出的异常类型较杂
        return False, f"PDF 解析失败：{exc}"
    if not reader.is_encrypted:
        return False, ""
    try:
        if reader.decrypt(""):
            return False, ""
    except Exception:
        pass
    return True, ""


def pdf_outline(path: Path) -> dict[str, Any]:
    """提取 PDF 目录与页数；没有 outline 时按每 10 页分段。"""
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            reader.decrypt("")
        total = len(reader.pages)
    except Exception as exc:
        return {"total": 0, "items": [], "error": f"PDF 解析失败：{exc}"}

    items: list[dict[str, Any]] = []

    def walk(nodes: Any, level: int) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if isinstance(node, list):
                walk(node, level + 1)
                continue
            title = getattr(node, "title", None)
            if title is None and isinstance(node, dict):
                title = node.get("/Title")
            if not title:
                continue
            try:
                page = int(reader.get_destination_page_number(node)) + 1
            except Exception:
                page = 1
            items.append({"label": str(title), "page": page, "level": level})

    try:
        walk(reader.outline, 0)
    except Exception:
        items = []

    if not items and total:
        for start in range(1, total + 1, 10):
            end = min(start + 9, total)
            label = f"第 {start} 页" if start == end else f"第 {start}-{end} 页"
            items.append({"label": label, "page": start, "level": 0})
    return {"total": total, "items": items, "error": ""}


def _cache_path(source: Path, converted_dir: Path) -> Path:
    fingerprint = quick_hash(source)
    return converted_dir / f"{fingerprint}-{int(source.stat().st_mtime)}.epub"


def convert_mobi(source: Path, converted_dir: Path | None = None) -> Path:
    """把 MOBI/AZW3 转为 EPUB，按「quick-hash + mtime」缓存。"""
    target_dir = converted_dir or config.CONVERTED_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target = _cache_path(source, target_dir)
    if target.is_file() and target.stat().st_size > 0:
        return target
    content = mobi.parse(source)
    if not content.chapters:
        raise ConvertError("没有解析到可读章节")
    temporary = target.with_suffix(".tmp")
    mobi.build_epub(content, temporary)
    temporary.replace(target)
    log.info("已转换 %s → %s", source.name, target.name)
    return target


def prepare_book(
    file_path: str | Path, converted_dir: Path | None = None
) -> PreparedBook:
    """返回可直接交给 epub.js / pdf.js 的文件；失败时带 error/drm。"""
    source = Path(file_path)
    if not source.is_file():
        return PreparedBook(error="文件不存在或已被移动")
    suffix = source.suffix.lower()

    if suffix == ".epub":
        if _epub_drm(source):
            return PreparedBook(kind="epub", drm=True, error="该 EPUB 受 DRM 保护，无法内嵌阅读")
        return PreparedBook(kind="epub", path=source)

    if suffix == ".pdf":
        drm, error = _pdf_problem(source)
        if drm:
            return PreparedBook(kind="pdf", drm=True, error="该 PDF 已加密，无法内嵌阅读")
        if error:
            return PreparedBook(kind="pdf", error=error)
        return PreparedBook(kind="pdf", path=source)

    if suffix in (".mobi", ".azw3"):
        try:
            target = convert_mobi(source, converted_dir)
        except mobi.DrmProtected:
            return PreparedBook(kind="epub", drm=True, error="该文件受 DRM 保护，无法内嵌阅读")
        except (mobi.MobiError, ConvertError) as exc:
            return PreparedBook(kind="epub", error=str(exc))
        except (OSError, zipfile.BadZipFile) as exc:
            return PreparedBook(kind="epub", error=f"转换失败：{exc}")
        return PreparedBook(kind="epub", path=target, converted=True)

    return PreparedBook(error=f"暂不支持阅读 {suffix or '未知'} 格式")

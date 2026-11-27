"""目录扫描测试：过滤、递归深度、隐藏文件、小文件标记与取消。"""

from __future__ import annotations

from pathlib import Path

from app.core.scanner import discover_files

LARGE = 60 * 1024


def _make_tree(root: Path) -> None:
    (root / "a.epub").write_bytes(b"a" * LARGE)
    (root / "b.PDF").write_bytes(b"b" * LARGE)
    (root / "small.epub").write_bytes(b"s" * 1024)
    (root / "notes.txt").write_text("not a book", encoding="utf-8")
    (root / "empty.mobi").write_bytes(b"")
    (root / ".hidden.epub").write_bytes(b"h" * LARGE)
    (root / "sub").mkdir()
    (root / "sub" / "c.azw3").write_bytes(b"c" * LARGE)
    (root / "sub" / "deep").mkdir()
    (root / "sub" / "deep" / "d.epub").write_bytes(b"d" * LARGE)


def test_discover_filters_formats_and_marks_small(tmp_path):
    _make_tree(tmp_path)
    files = discover_files([tmp_path], ["epub", "pdf", "mobi", "azw3"])

    names = {item.path.name for item in files}
    assert names == {"a.epub", "b.PDF", "small.epub", "c.azw3", "d.epub"}
    small = next(item for item in files if item.path.name == "small.epub")
    assert small.too_small is True
    assert next(item for item in files if item.path.name == "a.epub").too_small is False


def test_discover_respects_recursive_and_depth(tmp_path):
    _make_tree(tmp_path)
    flat = discover_files([tmp_path], ["epub"], recursive=False)
    assert {item.path.name for item in flat} == {"a.epub", "small.epub"}

    shallow = discover_files([tmp_path], ["epub"], recursive=True, max_depth=1)
    assert {item.path.name for item in shallow} == {"a.epub", "small.epub"}


def test_discover_hidden_toggle(tmp_path):
    _make_tree(tmp_path)
    assert ".hidden.epub" not in {
        item.path.name for item in discover_files([tmp_path], ["epub"])
    }
    assert ".hidden.epub" in {
        item.path.name
        for item in discover_files([tmp_path], ["epub"], ignore_hidden=False)
    }


def test_discover_case_insensitive_and_extension_dot(tmp_path):
    _make_tree(tmp_path)
    files = discover_files([tmp_path], [".PDF"], recursive=False)
    assert [item.format for item in files] == ["pdf"]


def test_discover_cancel_returns_early(tmp_path):
    _make_tree(tmp_path)
    assert discover_files([tmp_path], ["epub"], cancel_check=lambda: True) == []


def test_discover_deduplicates_overlapping_roots(tmp_path):
    _make_tree(tmp_path)
    files = discover_files([tmp_path, tmp_path / "sub"], ["epub"])
    keys = [str(item.path.resolve()).lower() for item in files]
    assert len(keys) == len(set(keys))


def test_discover_skips_missing_and_empty_directories(tmp_path):
    missing = tmp_path / "missing"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert discover_files([missing, empty], ["epub"]) == []

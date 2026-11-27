"""扫描合并：L0 文件名兜底、内嵌优先、字段级合并（规范 N5）。"""

from __future__ import annotations

from pathlib import Path

from app.core.metadata.normalize import finalize
from app.core.scanner import ScannedFile
from app.db.repositories.book_repo import BookRepository
from app.services.scan_service import process_scan_file


def _candidate(path: Path) -> ScannedFile:
    stat = path.stat()
    return ScannedFile(
        path=path,
        format=path.suffix.lower().lstrip("."),
        size=stat.st_size,
        mtime=stat.st_mtime,
        too_small=False,
    )


def test_filename_only_book_goes_to_confirm(db, tmp_path, monkeypatch) -> None:
    path = tmp_path / "曹雪芹 - 红楼梦 (1982).epub"
    path.write_bytes(b"empty-metadata" * 100)
    monkeypatch.setattr(
        "app.services.scan_service.extract_metadata",
        lambda _path: finalize({}, ok=True),
    )

    result = process_scan_file(db, _candidate(path))

    row = BookRepository(db).get(result["book_id"])
    assert row["title"] == "红楼梦"
    assert row["author_raw"] == "曹雪芹"
    assert row["publish_date"] == "1982"
    assert row["meta_source"] == "filename"
    assert row["status"] == "partial"
    assert row["confidence"] == 40


def test_embedded_fields_win_over_filename(db, tmp_path, monkeypatch) -> None:
    path = tmp_path / "某作者 - 某书名 (1999).epub"
    path.write_bytes(b"embedded" * 100)
    monkeypatch.setattr(
        "app.services.scan_service.extract_metadata",
        lambda _path: finalize(
            {
                "title": "内嵌书名",
                "authors": ["内嵌作者"],
                "publisher": "内嵌出版社",
                "isbn": "9787020002207",
                "date": "2020-01-01",
            },
            ok=True,
        ),
    )

    result = process_scan_file(db, _candidate(path))

    row = BookRepository(db).get(result["book_id"])
    assert row["title"] == "内嵌书名"
    assert row["author_raw"] == "内嵌作者"
    assert row["publisher"] == "内嵌出版社"
    assert row["isbn"] == "9787020002207"
    assert row["publish_date"] == "2020-01-01"
    assert row["meta_source"] == "embedded"
    assert row["status"] == "ok"
    assert row["confidence"] == 95

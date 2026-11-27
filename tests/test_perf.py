"""分页性能测试：10 万行下首页查询应满足 DoD（<50ms，测试放宽到 200ms）。"""

from __future__ import annotations

import time

from app.db.repositories.book_repo import BookRepository


def test_paged_query_on_100k_rows(db):
    rows = [
        (
            rf"C:\books\{index}.epub",
            f"hash{index}",
            "epub" if index % 3 else "pdf",
            f"书名{index:06d}",
            "ok" if index % 2 else "pending",
        )
        for index in range(100_000)
    ]
    with db.transaction() as conn:
        conn.executemany(
            "INSERT INTO books(file_path, quick_hash, format, title, status) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )

    repo = BookRepository(db)
    start = time.perf_counter()
    page = repo.list(page=1, page_size=50, status="ok")
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert len(page) == 50
    assert elapsed_ms < 200, f"分页查询耗时 {elapsed_ms:.1f}ms 超出预期"
    print(f"\n10 万行分页查询耗时：{elapsed_ms:.1f}ms")

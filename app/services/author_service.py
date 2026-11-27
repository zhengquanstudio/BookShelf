"""作者服务：规范化、按唯一键落库、复用已锁定记录。"""

from __future__ import annotations

from typing import Any

from ..core import authors, countries
from ..db.connection import Database
from ..db.repositories import utc_now
from ..db.repositories.author_repo import AuthorRepository
from ..db.repositories.book_repo import BookRepository


class AuthorService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.repo = AuthorRepository(db)
        self.books = BookRepository(db)

    def resolve(self, raw: str | None, country_hint: str | None = None) -> authors.AuthorInfo:
        """先查库（含 locked 与别名），未命中再走内置字典。"""
        info = authors.normalize_author(raw, country_hint)
        if not info.name_zh:
            return info
        row = self.repo.find(info.name_zh, info.name_orig or info.name_zh,
                             info.country or None)
        if row is None and info.matched and raw:
            row = self.repo.find_by_alias(str(raw).strip())
        if row is None and info.is_chinese:
            row = self.repo.find(info.name_zh)
        if row is None:
            return info
        code = str(row["country_code"] or "") or countries.resolve_country(row["country"]) or ""
        return authors.AuthorInfo(
            name_zh=str(row["name_zh"]),
            name_orig=str(row["name_orig"] or ""),
            country=str(row["country"] or countries.country_zh(code)),
            country_code=code,
            is_chinese=bool(row["is_chinese"]),
            needs_confirm=False,
            matched=True,
            aliases=list(info.aliases),
        )

    def ensure(self, info: authors.AuthorInfo, *, locked: bool = False) -> int | None:
        """按（中文名, 原文, 国别）唯一定位；不存在则创建。"""
        if not info.name_zh:
            return None
        row = self.repo.find(info.name_zh, info.name_orig or info.name_zh,
                             info.country or None)
        if row is None and info.is_chinese:
            row = self.repo.find(info.name_zh)
        if row is not None:
            if locked and not row["locked"]:
                self.repo.update(int(row["id"]), locked=1)
            return int(row["id"])
        fields: dict[str, Any] = info.as_fields()
        fields.pop("name_zh", None)
        fields["locked"] = 1 if locked else 0
        return self.repo.create(info.name_zh, **fields)

    def catalog(self, search: str = "") -> list[dict[str, Any]]:
        return [dict(row) for row in self.repo.list_with_counts(search)]

    def books_for(self, author_id: int) -> list[dict[str, Any]]:
        rows = self.books.list(
            page=1, page_size=1000, author_id=author_id, sort="title", desc=False
        )
        return [dict(row) for row in rows]

    def create(self, name: str, *, name_orig: str = "", country: str = "") -> int:
        name = name.strip()
        if not name:
            raise ValueError("作者名不能为空")
        info = authors.normalize_author(name, country or None)
        return self.repo.ensure(
            name,
            name_orig=name_orig.strip() or info.name_orig or name,
            country=country.strip() or info.country or None,
            country_code=info.country_code or None,
            is_chinese=1 if info.is_chinese else 0,
            locked=1,
        )

    def update(self, author_id: int, name: str, *, name_orig: str = "", country: str = "") -> None:
        if not name.strip():
            raise ValueError("作者名不能为空")
        info = authors.normalize_author(name, country or None)
        self.repo.update(
            author_id,
            name_zh=name.strip(),
            name_orig=name_orig.strip() or name.strip(),
            country=country.strip() or None,
            country_code=info.country_code or None,
            is_chinese=1 if info.is_chinese else 0,
            locked=1,
        )

    def merge(self, source_id: int, target_id: int) -> int:
        return self.repo.merge(source_id, target_id)

    def assign_author(self, book_ids: list[int], author_id: int) -> int:
        """批量应用已存在的作者，单事务写入。"""
        author = self.repo.get(author_id)
        if author is None:
            raise ValueError("作者不存在")
        if not book_ids:
            return 0
        ids = [int(book_id) for book_id in book_ids]
        marks = ", ".join("?" for _ in ids)
        with self.db.transaction() as conn:
            cur = conn.execute(
                f"UPDATE books SET author_id = ?, author_raw = ?, updated_at = ? "
                f"WHERE id IN ({marks})",
                (author_id, author["name_zh"], utc_now(), *ids),
            )
            return cur.rowcount

    def assign_book(
        self, book_id: int, raw: str | None, country_hint: str | None = None,
        *, locked: bool = False,
    ) -> int | None:
        info = self.resolve(raw, country_hint)
        author_id = self.ensure(info, locked=locked)
        if author_id is not None:
            fields: dict[str, Any] = {"author_id": author_id}
            if raw:
                fields["author_raw"] = str(raw)
            self.books.update(book_id, **fields)
        return author_id

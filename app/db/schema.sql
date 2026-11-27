-- 书库助手 BookShelf 数据库结构（文档第 5 章 DDL 原文）
-- 时间统一使用 ISO8601 文本（UTC）。

CREATE TABLE IF NOT EXISTS schema_version (ver INTEGER PRIMARY KEY, applied_at TEXT);

CREATE TABLE IF NOT EXISTS authors (
  id            INTEGER PRIMARY KEY,
  name_zh       TEXT NOT NULL,
  name_orig     TEXT,
  country       TEXT,
  country_code  TEXT,
  is_chinese    INTEGER NOT NULL DEFAULT 0,
  alias_json    TEXT DEFAULT '[]',
  locked        INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT,
  updated_at    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_author_key
  ON authors(name_zh, IFNULL(name_orig, ''), IFNULL(country, ''));

CREATE TABLE IF NOT EXISTS series (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL,
  author_id     INTEGER REFERENCES authors(id) ON DELETE SET NULL,
  total_volumes INTEGER,
  locked        INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT,
  updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS books (
  id             INTEGER PRIMARY KEY,
  file_path      TEXT NOT NULL UNIQUE,
  quick_hash     TEXT NOT NULL,
  full_hash      TEXT,
  file_size      INTEGER,
  file_mtime     REAL,
  format         TEXT NOT NULL,
  title          TEXT,
  subtitle       TEXT,
  author_id      INTEGER REFERENCES authors(id) ON DELETE SET NULL,
  author_raw     TEXT,
  isbn           TEXT,
  publisher      TEXT,
  publish_date   TEXT,
  language       TEXT,
  series_id      INTEGER REFERENCES series(id) ON DELETE SET NULL,
  volume         INTEGER,
  volume_raw     TEXT,
  description    TEXT,
  cover_path     TEXT,
  page_count     INTEGER,
  meta_source    TEXT,
  confidence     REAL DEFAULT 0,
  status         TEXT NOT NULL DEFAULT 'pending',
  favorite       INTEGER NOT NULL DEFAULT 0,
  read_state     TEXT NOT NULL DEFAULT 'unread',
  drm_protected  INTEGER NOT NULL DEFAULT 0,
  dup_group_id   INTEGER,
  dup_of         INTEGER REFERENCES books(id) ON DELETE SET NULL,
  added_at       TEXT,
  updated_at     TEXT
);
CREATE INDEX IF NOT EXISTS ix_books_status ON books(status);
CREATE INDEX IF NOT EXISTS ix_books_author ON books(author_id);
CREATE INDEX IF NOT EXISTS ix_books_series ON books(series_id, volume);
CREATE INDEX IF NOT EXISTS ix_books_isbn ON books(isbn);

CREATE TABLE IF NOT EXISTS library_items (
  id            INTEGER PRIMARY KEY,
  book_id       INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  source_path   TEXT,
  target_dir    TEXT NOT NULL,
  target_name   TEXT NOT NULL,
  target_path   TEXT NOT NULL,
  action        TEXT NOT NULL,
  result        TEXT NOT NULL,
  message       TEXT,
  batch_id      TEXT,
  created_at    TEXT
);
CREATE INDEX IF NOT EXISTS ix_items_batch ON library_items(batch_id);

CREATE TABLE IF NOT EXISTS search_cache (
  key           TEXT PRIMARY KEY,
  source        TEXT NOT NULL,
  payload_json  TEXT NOT NULL,
  hit_count     INTEGER DEFAULT 1,
  fetched_at    TEXT NOT NULL,
  expires_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE,
  color TEXT DEFAULT '#4f8cf7'
);

CREATE TABLE IF NOT EXISTS book_tags (
  book_id INTEGER,
  tag_id INTEGER,
  PRIMARY KEY (book_id, tag_id)
);

CREATE TABLE IF NOT EXISTS reading_state (
  book_id      INTEGER PRIMARY KEY REFERENCES books(id) ON DELETE CASCADE,
  locator_json TEXT,
  percent      REAL DEFAULT 0,
  last_read_at TEXT,
  total_seconds INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reading_sessions (
  id INTEGER PRIMARY KEY,
  book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  started_at TEXT NOT NULL,          -- ISO8601 本地时间
  ended_at TEXT,
  seconds INTEGER DEFAULT 0,
  pages INTEGER DEFAULT 0,
  device TEXT DEFAULT 'desktop'
);
CREATE INDEX IF NOT EXISTS ix_rs_day ON reading_sessions(substr(started_at,1,10));
CREATE INDEX IF NOT EXISTS ix_rs_book ON reading_sessions(book_id);

CREATE TABLE IF NOT EXISTS bookmarks (
  id INTEGER PRIMARY KEY,
  book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  locator_json TEXT NOT NULL,
  chapter TEXT,
  text TEXT,
  note TEXT,
  color TEXT DEFAULT '#ffe08a',
  kind TEXT DEFAULT 'bookmark',
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_bm_book ON bookmarks(book_id);

CREATE TABLE IF NOT EXISTS task_log (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  level TEXT NOT NULL,
  action TEXT,
  book_id INTEGER,
  message TEXT
);

CREATE TABLE IF NOT EXISTS app_settings (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL,
  updated_at TEXT
);

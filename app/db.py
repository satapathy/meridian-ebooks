import contextlib
import sqlite3

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id           TEXT PRIMARY KEY,           -- uuid4 hex, 32 chars
    title        TEXT NOT NULL,
    author       TEXT NOT NULL DEFAULT '',   -- "A; B"
    publisher    TEXT NOT NULL DEFAULT '',
    description  TEXT NOT NULL DEFAULT '',
    language     TEXT NOT NULL DEFAULT '',
    published    TEXT NOT NULL DEFAULT '',
    isbn         TEXT NOT NULL DEFAULT '',
    tags         TEXT NOT NULL DEFAULT '[]', -- JSON array
    category     TEXT NOT NULL DEFAULT '',
    subcategory  TEXT NOT NULL DEFAULT '',
    series       TEXT NOT NULL DEFAULT '',
    series_index REAL,
    rating       INTEGER,
    format       TEXT NOT NULL,
    filename     TEXT NOT NULL,
    rel_dir      TEXT NOT NULL,              -- 1234/5678/abcd/...
    size         INTEGER NOT NULL DEFAULT 0,
    md5          TEXT NOT NULL,              -- hash of the file as first uploaded
    current_md5  TEXT NOT NULL,              -- hash after metadata was written into it
    has_cover    INTEGER NOT NULL DEFAULT 0,
    embedded     TEXT NOT NULL DEFAULT '[]', -- fields stored inside the file
    source_path  TEXT,
    added_at     TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_books_md5 ON books(md5);
CREATE INDEX IF NOT EXISTS idx_books_current_md5 ON books(current_md5);
CREATE INDEX IF NOT EXISTS idx_books_added ON books(added_at);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextlib.contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    settings.ensure_dirs()
    with db() as conn:
        conn.executescript(SCHEMA)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(books)")}
        if "subcategory" not in cols:  # databases created before sub-categories existed
            conn.execute("ALTER TABLE books ADD COLUMN subcategory TEXT NOT NULL DEFAULT ''")

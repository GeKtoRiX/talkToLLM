"""SQLite persistence layer for the vocabulary study subsystem."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS study_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type           TEXT    NOT NULL CHECK(item_type IN ('word', 'phrasal_verb', 'idiom', 'collocation')),
    target_text         TEXT    NOT NULL,
    native_text         TEXT    NOT NULL DEFAULT '',
    context_note        TEXT    NOT NULL DEFAULT '',
    example_sentence    TEXT    NOT NULL DEFAULT '',
    source_kind         TEXT    NOT NULL DEFAULT 'manual'
                                CHECK(source_kind IN ('manual', 'mcp_extract', 'mcp_manual')),
    source_turn_text    TEXT    NOT NULL DEFAULT '',
    source_response_text TEXT   NOT NULL DEFAULT '',
    language_target     TEXT    NOT NULL DEFAULT 'en',
    language_native     TEXT    NOT NULL DEFAULT 'ru',
    status              TEXT    NOT NULL DEFAULT 'new'
                                CHECK(status IN ('new', 'learning', 'review', 'suspended')),
    ease                REAL    NOT NULL DEFAULT 2.5,
    interval_days       REAL    NOT NULL DEFAULT 1.0,
    repetitions         INTEGER NOT NULL DEFAULT 0,
    lapses              INTEGER NOT NULL DEFAULT 0,
    next_review_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    last_reviewed_at    TEXT,
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    updated_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
);

CREATE TABLE IF NOT EXISTS review_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER NOT NULL REFERENCES study_items(id),
    rating          TEXT    NOT NULL CHECK(rating IN ('again', 'hard', 'good', 'easy')),
    ease_before     REAL    NOT NULL,
    interval_before REAL    NOT NULL,
    ease_after      REAL    NOT NULL,
    interval_after  REAL    NOT NULL,
    reviewed_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
);

CREATE TABLE IF NOT EXISTS study_sessions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    ended_at       TEXT,
    items_reviewed INTEGER NOT NULL DEFAULT 0,
    note           TEXT    NOT NULL DEFAULT ''
);
"""


def init_db(db_path: Path) -> None:
    """Create the database file and apply the schema (idempotent)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA_SQL)


@contextmanager
def get_db(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Yield a connection with Row factory, WAL mode, and FK enforcement.

    Commits on success; rolls back on any exception.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

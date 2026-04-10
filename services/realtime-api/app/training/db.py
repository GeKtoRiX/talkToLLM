"""Database migration for the training module.

Extends the existing study_items schema (from study/db.py) and creates
three new tables: item_progress, training_sessions, session_questions.

Migration is idempotent: safe to call on every app start.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.study.db import get_db

# ---------------------------------------------------------------------------
# New study_items DDL — replaces the old one during migration.
# Changes vs. original:
#   • item_type CHECK extended: adds phrasal_verb, idiom, collocation
#   • status CHECK extended: adds mastered, difficult
#   • Six new vocabulary-metadata columns appended
# ---------------------------------------------------------------------------
_STUDY_ITEMS_NEW_DDL = """
CREATE TABLE study_items_new (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type               TEXT    NOT NULL
                                    CHECK(item_type IN (
                                        'word','phrase','phrasal_verb','idiom','collocation'
                                    )),
    target_text             TEXT    NOT NULL,
    native_text             TEXT    NOT NULL DEFAULT '',
    context_note            TEXT    NOT NULL DEFAULT '',
    example_sentence        TEXT    NOT NULL DEFAULT '',
    source_kind             TEXT    NOT NULL DEFAULT 'manual'
                                    CHECK(source_kind IN ('manual','mcp_extract','mcp_manual')),
    source_turn_text        TEXT    NOT NULL DEFAULT '',
    source_response_text    TEXT    NOT NULL DEFAULT '',
    language_target         TEXT    NOT NULL DEFAULT 'en',
    language_native         TEXT    NOT NULL DEFAULT 'ru',
    status                  TEXT    NOT NULL DEFAULT 'new'
                                    CHECK(status IN (
                                        'new','learning','review','mastered','difficult','suspended'
                                    )),
    ease                    REAL    NOT NULL DEFAULT 2.5,
    interval_days           REAL    NOT NULL DEFAULT 1.0,
    repetitions             INTEGER NOT NULL DEFAULT 0,
    lapses                  INTEGER NOT NULL DEFAULT 0,
    next_review_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
    last_reviewed_at        TEXT,
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
    updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
    -- vocabulary metadata (all nullable / empty-default)
    lexical_type            TEXT    DEFAULT NULL,
    alternative_translations TEXT   NOT NULL DEFAULT '[]',
    topic                   TEXT    NOT NULL DEFAULT '',
    difficulty_level        INTEGER DEFAULT NULL,
    tags                    TEXT    NOT NULL DEFAULT '[]',
    example_sentence_native TEXT    NOT NULL DEFAULT ''
)
"""

_TRAINING_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS item_progress (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id                 INTEGER NOT NULL UNIQUE
                                    REFERENCES study_items(id) ON DELETE CASCADE,
    times_shown             INTEGER NOT NULL DEFAULT 0,
    times_correct           INTEGER NOT NULL DEFAULT 0,
    times_wrong             INTEGER NOT NULL DEFAULT 0,
    current_correct_streak  INTEGER NOT NULL DEFAULT 0,
    current_wrong_streak    INTEGER NOT NULL DEFAULT 0,
    -- JSON: {"mc":{"shown":0,"correct":0},"input":{...},"context":{...},"fill":{...}}
    exercise_type_stats     TEXT    NOT NULL DEFAULT '{}',
    active_recall_successes INTEGER NOT NULL DEFAULT 0,
    weighted_score          REAL    NOT NULL DEFAULT 0.0,
    is_mastered             INTEGER NOT NULL DEFAULT 0,
    mastered_at             TEXT,
    is_difficult            INTEGER NOT NULL DEFAULT 0,
    last_shown_at           TEXT,
    last_correct_at         TEXT,
    last_wrong_at           TEXT,
    created_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
    updated_at              TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS training_sessions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    mode                TEXT    NOT NULL,
    filters_json        TEXT    NOT NULL DEFAULT '{}',
    target_count        INTEGER NOT NULL DEFAULT 20,
    item_ids_json       TEXT    NOT NULL DEFAULT '[]',
    status              TEXT    NOT NULL DEFAULT 'active'
                                CHECK(status IN ('active','completed','abandoned')),
    correct_count       INTEGER NOT NULL DEFAULT 0,
    wrong_count         INTEGER NOT NULL DEFAULT 0,
    total_questions     INTEGER NOT NULL DEFAULT 0,
    newly_mastered_ids  TEXT    NOT NULL DEFAULT '[]',
    newly_difficult_ids TEXT    NOT NULL DEFAULT '[]',
    error_item_ids      TEXT    NOT NULL DEFAULT '[]',
    started_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
    ended_at            TEXT
);

CREATE TABLE IF NOT EXISTS session_questions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL
                            REFERENCES training_sessions(id) ON DELETE CASCADE,
    item_id         INTEGER NOT NULL
                            REFERENCES study_items(id),
    exercise_type   TEXT    NOT NULL
                            CHECK(exercise_type IN ('mc','input','context','fill')),
    direction       TEXT    NOT NULL DEFAULT 'en_to_ru',
    correct_answer  TEXT    NOT NULL,
    distractors_json TEXT   NOT NULL DEFAULT '[]',
    prompt_text     TEXT    NOT NULL,
    answer_given    TEXT,
    is_correct      INTEGER,
    error_type      TEXT,
    answered_at     TEXT,
    retry_scheduled INTEGER NOT NULL DEFAULT 0,
    position        INTEGER NOT NULL DEFAULT 0
);
"""


def _study_items_needs_migration(conn: sqlite3.Connection) -> bool:
    """Return True if the study_items table does NOT yet have the new schema.

    Detection strategy: read the DDL text stored in sqlite_master and check
    whether the word 'mastered' appears in it.  The old CHECK constraint is
    ``status IN ('new', 'learning', 'review', 'suspended')`` — it never
    contains 'mastered'.  The new one does.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='study_items'"
    ).fetchone()
    if row is None:
        # Table does not exist yet — init_db hasn't run, nothing to migrate.
        return False
    ddl: str = row[0] or ""
    return "'mastered'" not in ddl


def migrate_db(db_path: Path) -> None:
    """Apply all training-module migrations to the database.

    Safe to call on every startup (idempotent).

    Phase 1 — Widen study_items (table recreation):
        - Extends item_type and status CHECK constraints.
        - Adds six vocabulary-metadata columns.
        - Converts legacy item_type='sentence' rows to item_type='phrase'.

    Phase 2 — Create new tables (CREATE … IF NOT EXISTS):
        - item_progress
        - training_sessions
        - session_questions
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        # ------------------------------------------------------------------ #
        # Phase 1: Recreate study_items only when migration has not yet run.  #
        # ------------------------------------------------------------------ #
        if _study_items_needs_migration(conn):
            # Disable FK enforcement for the duration of the table swap so
            # SQLite does not refuse to DROP the referenced table.
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("BEGIN")
            try:
                conn.execute(_STUDY_ITEMS_NEW_DDL)
                # Copy all rows; 'sentence' → 'phrase' for the item_type column.
                conn.execute("""
                    INSERT INTO study_items_new (
                        id, item_type, target_text, native_text, context_note,
                        example_sentence, source_kind, source_turn_text,
                        source_response_text, language_target, language_native,
                        status, ease, interval_days, repetitions, lapses,
                        next_review_at, last_reviewed_at, created_at, updated_at,
                        lexical_type, alternative_translations, topic,
                        difficulty_level, tags, example_sentence_native
                    )
                    SELECT
                        id,
                        CASE item_type WHEN 'sentence' THEN 'phrase' ELSE item_type END,
                        target_text, native_text, context_note, example_sentence,
                        source_kind, source_turn_text, source_response_text,
                        language_target, language_native,
                        status, ease, interval_days, repetitions, lapses,
                        next_review_at, last_reviewed_at, created_at, updated_at,
                        NULL, '[]', '', NULL, '[]', ''
                    FROM study_items
                """)
                conn.execute("DROP TABLE study_items")
                conn.execute("ALTER TABLE study_items_new RENAME TO study_items")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.execute("PRAGMA foreign_keys=ON")

        # ------------------------------------------------------------------ #
        # Phase 2: Create new tables (idempotent).                            #
        # ------------------------------------------------------------------ #
        conn.executescript(_TRAINING_TABLES_DDL)
        conn.commit()
    finally:
        conn.close()

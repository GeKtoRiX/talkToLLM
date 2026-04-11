"""Unit tests for training/db.py — migration logic.

Tests cover:
  - Brand-new database: all four tables created correctly.
  - Existing database with old schema: data preserved.
  - Already-migrated database: second call is a no-op (no data loss).
  - New columns have correct defaults after migration.
  - New item_type and status values accepted after migration.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.study.db import init_db
from app.training.db import migrate_db, _study_items_needs_migration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {row["name"] for row in rows}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_db(tmp_path) -> Path:
    """Freshly initialised database (old schema only)."""
    p = tmp_path / "study.sqlite"
    init_db(p)
    return p


@pytest.fixture
def migrated_db(fresh_db) -> Path:
    """Database that has already been fully migrated."""
    migrate_db(fresh_db)
    return fresh_db


# ---------------------------------------------------------------------------
# Tests: brand-new database
# ---------------------------------------------------------------------------

class TestFreshDatabase:
    def test_all_tables_exist_after_migration(self, fresh_db):
        migrate_db(fresh_db)
        with _connect(fresh_db) as conn:
            tables = _table_names(conn)
        assert "study_items" in tables
        assert "item_progress" in tables
        assert "training_sessions" in tables
        assert "session_questions" in tables

    def test_study_items_has_new_columns(self, fresh_db):
        migrate_db(fresh_db)
        with _connect(fresh_db) as conn:
            cols = _columns(conn, "study_items")
        for col in ("lexical_type", "alternative_translations", "topic",
                    "difficulty_level", "tags", "example_sentence_native"):
            assert col in cols, f"Missing column: {col}"

    def test_mastered_status_accepted(self, fresh_db):
        migrate_db(fresh_db)
        with _connect(fresh_db) as conn:
            conn.execute(
                "INSERT INTO study_items(item_type, target_text, status) "
                "VALUES ('word','test','mastered')"
            )
            conn.commit()
            count = conn.execute(
                "SELECT COUNT(*) FROM study_items WHERE status='mastered'"
            ).fetchone()[0]
        assert count == 1

    def test_difficult_status_accepted(self, fresh_db):
        migrate_db(fresh_db)
        with _connect(fresh_db) as conn:
            conn.execute(
                "INSERT INTO study_items(item_type, target_text, status) "
                "VALUES ('word','word2','difficult')"
            )
            conn.commit()
            count = conn.execute(
                "SELECT COUNT(*) FROM study_items WHERE status='difficult'"
            ).fetchone()[0]
        assert count == 1

    def test_phrasal_verb_item_type_accepted(self, fresh_db):
        migrate_db(fresh_db)
        with _connect(fresh_db) as conn:
            conn.execute(
                "INSERT INTO study_items(item_type, target_text) "
                "VALUES ('phrasal_verb','give up')"
            )
            conn.commit()
            row = conn.execute(
                "SELECT item_type FROM study_items WHERE target_text='give up'"
            ).fetchone()
        assert row["item_type"] == "phrasal_verb"

    def test_idiom_and_collocation_types_accepted(self, fresh_db):
        migrate_db(fresh_db)
        with _connect(fresh_db) as conn:
            conn.execute(
                "INSERT INTO study_items(item_type, target_text) VALUES ('idiom','spill the beans')"
            )
            conn.execute(
                "INSERT INTO study_items(item_type, target_text) VALUES ('collocation','make a decision')"
            )
            conn.commit()
            types = {
                r["item_type"]
                for r in conn.execute("SELECT item_type FROM study_items").fetchall()
            }
        assert "idiom" in types
        assert "collocation" in types

    def test_new_columns_have_correct_defaults(self, fresh_db):
        migrate_db(fresh_db)
        with _connect(fresh_db) as conn:
            conn.execute(
                "INSERT INTO study_items(item_type, target_text) VALUES ('word','hello')"
            )
            conn.commit()
            row = dict(conn.execute(
                "SELECT * FROM study_items WHERE target_text='hello'"
            ).fetchone())
        assert row["lexical_type"] is None
        assert json.loads(row["alternative_translations"]) == []
        assert row["topic"] == ""
        assert row["difficulty_level"] is None
        assert json.loads(row["tags"]) == []
        assert row["example_sentence_native"] == ""


# ---------------------------------------------------------------------------
# Tests: existing database with data
# ---------------------------------------------------------------------------

class TestExistingDatabase:
    def test_existing_rows_preserved(self, fresh_db):
        """Migration must not lose any rows."""
        # Insert rows BEFORE migration using old-schema item_types
        with _connect(fresh_db) as conn:
            conn.execute(
                "INSERT INTO study_items(item_type, target_text, native_text) "
                "VALUES ('word','ephemeral','кратковременный')"
            )
            conn.execute(
                "INSERT INTO study_items(item_type, target_text, native_text) "
                "VALUES ('word','run out of','исчерпать')"
            )
            conn.commit()

        migrate_db(fresh_db)

        with _connect(fresh_db) as conn:
            rows = conn.execute("SELECT target_text FROM study_items ORDER BY id").fetchall()
        texts = [r["target_text"] for r in rows]
        assert "ephemeral" in texts
        assert "run out of" in texts

    def test_existing_review_events_preserved(self, fresh_db):
        """review_events rows must survive the study_items table recreation."""
        with _connect(fresh_db) as conn:
            conn.execute(
                "INSERT INTO study_items(item_type, target_text) VALUES ('word','persist')"
            )
            item_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO review_events(item_id, rating, ease_before, interval_before, ease_after, interval_after) "
                "VALUES (?, 'good', 2.5, 1.0, 2.5, 4.0)",
                (item_id,),
            )
            conn.commit()

        migrate_db(fresh_db)

        with _connect(fresh_db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM review_events").fetchone()[0]
        assert count == 1

    def test_srs_values_preserved(self, fresh_db):
        """ease, interval_days, repetitions, lapses must be unchanged after migration."""
        with _connect(fresh_db) as conn:
            conn.execute(
                "INSERT INTO study_items(item_type, target_text, ease, interval_days, repetitions, lapses) "
                "VALUES ('word','track',3.1, 14.0, 5, 1)"
            )
            conn.commit()

        migrate_db(fresh_db)

        with _connect(fresh_db) as conn:
            row = dict(conn.execute(
                "SELECT ease, interval_days, repetitions, lapses "
                "FROM study_items WHERE target_text='track'"
            ).fetchone())
        assert row["ease"] == pytest.approx(3.1)
        assert row["interval_days"] == pytest.approx(14.0)
        assert row["repetitions"] == 5
        assert row["lapses"] == 1


# ---------------------------------------------------------------------------
# Tests: idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_double_migration_no_error(self, fresh_db):
        """Calling migrate_db twice must not raise."""
        migrate_db(fresh_db)
        migrate_db(fresh_db)  # second call — should be a no-op

    def test_double_migration_preserves_data(self, fresh_db):
        """Data added after first migration must survive second call."""
        migrate_db(fresh_db)
        with _connect(fresh_db) as conn:
            conn.execute(
                "INSERT INTO study_items(item_type, target_text, lexical_type) "
                "VALUES ('word','idempotent','adjective')"
            )
            conn.commit()

        migrate_db(fresh_db)  # second call

        with _connect(fresh_db) as conn:
            row = conn.execute(
                "SELECT lexical_type FROM study_items WHERE target_text='idempotent'"
            ).fetchone()
        assert row["lexical_type"] == "adjective"

    def test_needs_migration_false_after_migration(self, fresh_db):
        migrate_db(fresh_db)
        with _connect(fresh_db) as conn:
            assert _study_items_needs_migration(conn) is False

    def test_needs_migration_true_before_migration(self, fresh_db):
        with _connect(fresh_db) as conn:
            assert _study_items_needs_migration(conn) is True


# ---------------------------------------------------------------------------
# Tests: new table schemas
# ---------------------------------------------------------------------------

class TestNewTableSchemas:
    def test_item_progress_columns(self, migrated_db):
        with _connect(migrated_db) as conn:
            cols = _columns(conn, "item_progress")
        expected = {
            "id", "item_id", "times_shown", "times_correct", "times_wrong",
            "current_correct_streak", "current_wrong_streak", "exercise_type_stats",
            "active_recall_successes", "weighted_score", "is_mastered", "mastered_at",
            "is_difficult", "last_shown_at", "last_correct_at", "last_wrong_at",
            "created_at", "updated_at",
        }
        assert expected.issubset(cols)

    def test_training_sessions_columns(self, migrated_db):
        with _connect(migrated_db) as conn:
            cols = _columns(conn, "training_sessions")
        expected = {
            "id", "mode", "filters_json", "target_count", "item_ids_json",
            "status", "correct_count", "wrong_count", "total_questions",
            "newly_mastered_ids", "newly_difficult_ids", "error_item_ids",
            "started_at", "ended_at",
        }
        assert expected.issubset(cols)

    def test_session_questions_columns(self, migrated_db):
        with _connect(migrated_db) as conn:
            cols = _columns(conn, "session_questions")
        expected = {
            "id", "session_id", "item_id", "exercise_type", "direction",
            "correct_answer", "distractors_json", "prompt_text", "answer_given",
            "is_correct", "error_type", "answered_at", "retry_scheduled", "position",
        }
        assert expected.issubset(cols)

    def test_item_progress_cascade_delete(self, migrated_db):
        """Deleting a study_item must cascade-delete its item_progress row."""
        with _connect(migrated_db) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                "INSERT INTO study_items(item_type, target_text) VALUES ('word','cascade_test')"
            )
            item_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO item_progress(item_id) VALUES (?)", (item_id,)
            )
            conn.commit()

            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("DELETE FROM study_items WHERE id=?", (item_id,))
            conn.commit()

            count = conn.execute(
                "SELECT COUNT(*) FROM item_progress WHERE item_id=?", (item_id,)
            ).fetchone()[0]
        assert count == 0

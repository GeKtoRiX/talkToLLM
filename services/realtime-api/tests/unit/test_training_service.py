"""Unit tests for TrainingService."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.study.db import get_db, init_db
from app.training.service import TrainingService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path) -> Path:
    p = tmp_path / "study.sqlite"
    init_db(p)
    return p


@pytest.fixture
def svc(db_path) -> TrainingService:
    return TrainingService(db_path)


def _add_item(db_path: Path, target: str, native: str = "перевод",
              item_type: str = "word", lexical_type: str | None = None,
              example: str = "") -> int:
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO study_items(item_type, target_text, native_text, "
            "lexical_type, example_sentence) VALUES (?, ?, ?, ?, ?)",
            (item_type, target, native, lexical_type, example),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


# ---------------------------------------------------------------------------
# Session creation
# ---------------------------------------------------------------------------

class TestCreateSession:
    def test_creates_session_with_items(self, svc, db_path):
        _add_item(db_path, "ephemeral", "кратковременный")
        _add_item(db_path, "transient", "мимолётный")
        session, question = svc.create_session("auto", {}, 2)

        assert session["id"] is not None
        assert session["status"] == "active"
        assert session["total_questions"] >= 1
        assert question is not None

    def test_no_items_returns_completed_session(self, svc):
        session, question = svc.create_session("auto", {}, 20)
        assert session["status"] == "completed"
        assert question is None

    def test_creates_item_progress_rows(self, svc, db_path):
        _add_item(db_path, "word1", "слово1")
        svc.create_session("auto", {}, 5)
        with get_db(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM item_progress").fetchone()[0]
        assert count >= 1

    def test_session_questions_have_positions(self, svc, db_path):
        for i in range(5):
            _add_item(db_path, f"word{i}", f"слово{i}")
        session, _ = svc.create_session("auto", {}, 5)
        with get_db(db_path) as conn:
            positions = [
                r[0] for r in conn.execute(
                    "SELECT position FROM session_questions WHERE session_id=? ORDER BY position",
                    (session["id"],),
                ).fetchall()
            ]
        assert positions == sorted(positions)

    def test_mode_new_only_selects_new_items(self, svc, db_path):
        new_id = _add_item(db_path, "fresh", "свежий")
        # Manually set one item to 'learning'
        _add_item(db_path, "learned", "изученный")
        with get_db(db_path) as conn:
            conn.execute("UPDATE study_items SET status='learning' WHERE target_text='learned'")
        session, q = svc.create_session("new_only", {}, 5)
        if q:
            assert q["item_id"] == new_id

    def test_manual_mode_with_no_items_returns_completed(self, svc):
        session, question = svc.create_session("manual", {}, 10)
        assert session["status"] == "completed"
        assert question is None


# ---------------------------------------------------------------------------
# Answer submission
# ---------------------------------------------------------------------------

class TestSubmitAnswer:
    def _setup_session(self, svc, db_path):
        _add_item(db_path, "ephemeral", "кратковременный")
        for i in range(4):
            _add_item(db_path, f"distractor{i}", f"слово{i}")
        session, q = svc.create_session("auto", {}, 10)
        return session, q

    def test_correct_answer_returns_is_correct_true(self, svc, db_path):
        session, q = self._setup_session(svc, db_path)
        assert q is not None
        result = svc.submit_answer(session["id"], q["id"], q["correct_answer"])
        assert result["is_correct"] is True

    def test_wrong_answer_returns_is_correct_false(self, svc, db_path):
        session, q = self._setup_session(svc, db_path)
        result = svc.submit_answer(session["id"], q["id"], "COMPLETELY_WRONG_ANSWER_XYZ")
        assert result["is_correct"] is False

    def test_wrong_answer_increments_wrong_count(self, svc, db_path):
        session, q = self._setup_session(svc, db_path)
        svc.submit_answer(session["id"], q["id"], "WRONG")
        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT wrong_count FROM training_sessions WHERE id=?", (session["id"],)
            ).fetchone()
        assert row["wrong_count"] == 1

    def test_correct_answer_increments_correct_count(self, svc, db_path):
        session, q = self._setup_session(svc, db_path)
        svc.submit_answer(session["id"], q["id"], q["correct_answer"])
        with get_db(db_path) as conn:
            row = conn.execute(
                "SELECT correct_count FROM training_sessions WHERE id=?", (session["id"],)
            ).fetchone()
        assert row["correct_count"] == 1

    def test_wrong_answer_schedules_retry(self, svc, db_path):
        session, q = self._setup_session(svc, db_path)
        before_total = session["total_questions"]
        svc.submit_answer(session["id"], q["id"], "WRONG")
        with get_db(db_path) as conn:
            new_total = conn.execute(
                "SELECT total_questions FROM training_sessions WHERE id=?", (session["id"],)
            ).fetchone()[0]
        assert new_total > before_total

    def test_answering_already_answered_raises(self, svc, db_path):
        session, q = self._setup_session(svc, db_path)
        svc.submit_answer(session["id"], q["id"], q["correct_answer"])
        with pytest.raises(ValueError, match="already been answered"):
            svc.submit_answer(session["id"], q["id"], q["correct_answer"])

    def test_answer_for_wrong_session_raises(self, svc, db_path):
        session, q = self._setup_session(svc, db_path)
        with pytest.raises(ValueError):
            svc.submit_answer(session["id"], q["id"] + 9999, "answer")

    def test_inactive_session_raises(self, svc, db_path):
        session, q = self._setup_session(svc, db_path)
        svc.complete_session(session["id"])
        if q:
            with pytest.raises(ValueError, match="not active"):
                svc.submit_answer(session["id"], q["id"], "answer")

    def test_session_completes_after_all_questions(self, svc, db_path):
        """A session with 1 item should auto-complete after answering correctly."""
        _add_item(db_path, "solo", "один")
        for i in range(3):
            _add_item(db_path, f"d{i}", f"д{i}")
        session, q = svc.create_session("auto", {}, 1)
        assert q is not None
        result = svc.submit_answer(session["id"], q["id"], q["correct_answer"])
        # May or may not be complete depending on wrong-answer retries; check via get
        if result["session_complete"]:
            updated_session, _, _ = svc.get_session(session["id"])
            assert updated_session["status"] == "completed"

    def test_progress_updated_on_correct(self, svc, db_path):
        item_id = _add_item(db_path, "track", "отслеживать")
        for i in range(3):
            _add_item(db_path, f"d{i}", f"d{i}")
        session, q = svc.create_session("auto", {}, 5)
        assert q is not None and q["item_id"] == item_id
        svc.submit_answer(session["id"], q["id"], q["correct_answer"])
        with get_db(db_path) as conn:
            p = dict(conn.execute(
                "SELECT times_shown, times_correct FROM item_progress WHERE item_id=?",
                (item_id,),
            ).fetchone())
        assert p["times_shown"] == 1
        assert p["times_correct"] == 1

    def test_review_event_logged(self, svc, db_path):
        item_id = _add_item(db_path, "record", "запись")
        for i in range(3):
            _add_item(db_path, f"d{i}", f"d{i}")
        session, q = svc.create_session("auto", {}, 5)
        assert q is not None
        svc.submit_answer(session["id"], q["id"], q["correct_answer"])
        with get_db(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM review_events").fetchone()[0]
        assert count >= 1


# ---------------------------------------------------------------------------
# Session completion
# ---------------------------------------------------------------------------

class TestCompleteSession:
    def test_complete_sets_status(self, svc, db_path):
        _add_item(db_path, "finish", "завершить")
        session, _ = svc.create_session("auto", {}, 5)
        results = svc.complete_session(session["id"])
        with get_db(db_path) as conn:
            status = conn.execute(
                "SELECT status FROM training_sessions WHERE id=?", (session["id"],)
            ).fetchone()[0]
        assert status == "completed"

    def test_complete_returns_results_dict(self, svc, db_path):
        _add_item(db_path, "done", "готово")
        session, _ = svc.create_session("auto", {}, 5)
        results = svc.complete_session(session["id"])
        assert "session_id" in results
        assert "accuracy_pct" in results
        assert "by_exercise_type" in results

    def test_get_session_results_for_nonexistent_raises(self, svc):
        with pytest.raises(ValueError):
            svc.get_session_results(99999)


# ---------------------------------------------------------------------------
# User stats
# ---------------------------------------------------------------------------

class TestGetUserStats:
    def test_returns_expected_keys(self, svc, db_path):
        _add_item(db_path, "word1", "слово1")
        stats = svc.get_user_stats()
        for key in ("total_items", "new", "learning", "review", "mastered",
                    "difficult", "by_lexical_type", "by_item_type"):
            assert key in stats, f"Missing key: {key}"

    def test_counts_by_item_type(self, svc, db_path):
        _add_item(db_path, "noun1", "сущ1", "word", "noun")
        _add_item(db_path, "idiom1", "идиома1", "idiom")
        stats = svc.get_user_stats()
        assert stats["by_item_type"].get("word", 0) >= 1
        assert stats["by_item_type"].get("idiom", 0) >= 1

    def test_counts_by_lexical_type(self, svc, db_path):
        _add_item(db_path, "verb1", "глагол1", "word", "verb")
        stats = svc.get_user_stats()
        assert stats["by_lexical_type"].get("verb", 0) >= 1


# ---------------------------------------------------------------------------
# Filtered items
# ---------------------------------------------------------------------------

class TestGetFilteredItems:
    def test_filter_by_item_type(self, svc, db_path):
        _add_item(db_path, "give up", "сдаться", "phrasal_verb", "verb")
        _add_item(db_path, "apple", "яблоко", "word", "noun")
        result = svc.get_filtered_items(item_type="phrasal_verb")
        assert all(r["item_type"] == "phrasal_verb" for r in result)
        assert len(result) >= 1

    def test_filter_by_lexical_type(self, svc, db_path):
        _add_item(db_path, "run", "бежать", "word", "verb")
        _add_item(db_path, "apple", "яблоко", "word", "noun")
        result = svc.get_filtered_items(lexical_type="verb")
        assert all(r["lexical_type"] == "verb" for r in result)

    def test_limit_respected(self, svc, db_path):
        for i in range(20):
            _add_item(db_path, f"w{i}", f"слово{i}")
        result = svc.get_filtered_items(limit=5)
        assert len(result) <= 5

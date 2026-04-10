"""TrainingService — session lifecycle and adaptive question generation.

Responsibilities:
  - Create and manage training sessions.
  - Build question queues with exercise interleaving.
  - Process answers: SRS updates, progress tracking, mastery detection.
  - Compute user-level and session-level statistics.
"""
from __future__ import annotations

import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.study.db import get_db
from app.study.service import apply_srs
from app.training.db import migrate_db
from app.training.distractors import DistractorSelector
from app.training.progress import (
    ACTIVE_RECALL_TYPES,
    check_answer,
    check_mastery,
    compute_priority,
    compute_srs_rating,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Ratio of item types to include in an automatic session.
_AUTO_MIX: dict[str, float] = {
    "new": 0.30,
    "active": 0.40,  # learning + difficult
    "review": 0.20,
    "mastered": 0.10,
}

# After an incorrect answer, re-queue the item this many positions later.
_RETRY_OFFSET_MIN = 3
_RETRY_OFFSET_MAX = 5

_NOW_SQL = "strftime('%Y-%m-%d %H:%M:%S','now')"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


# ---------------------------------------------------------------------------
# TrainingService
# ---------------------------------------------------------------------------


class TrainingService:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        migrate_db(db_path)
        self._distractors = DistractorSelector(db_path)

    # ======================================================================
    # Session creation
    # ======================================================================

    def create_session(
        self,
        mode: str,
        filters: dict,
        target_count: int,
    ) -> tuple[dict, dict | None]:
        """Create a new training session.

        Returns (session_dict, first_question_dict | None).
        If no eligible items match the filters, the session is created with
        status='completed' and no first question.
        """
        items = self._select_items(mode, filters, target_count)

        with get_db(self.db_path) as conn:
            # Build the question queue
            questions = self._build_question_queue(items, target_count)

            if not questions:
                # No items available — create a completed session immediately.
                conn.execute(
                    """
                    INSERT INTO training_sessions
                        (mode, filters_json, target_count, item_ids_json, status,
                         total_questions, ended_at)
                    VALUES (?, ?, ?, '[]', 'completed', 0, ?)
                    """,
                    (mode, json.dumps(filters), target_count, _now()),
                )
                session_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                session = dict(conn.execute(
                    "SELECT * FROM training_sessions WHERE id=?", (session_id,)
                ).fetchone())
                return session, None

            item_ids = list({q["item_id"] for q in questions})

            conn.execute(
                """
                INSERT INTO training_sessions
                    (mode, filters_json, target_count, item_ids_json, status, total_questions)
                VALUES (?, ?, ?, ?, 'active', ?)
                """,
                (mode, json.dumps(filters), target_count,
                 json.dumps(item_ids), len(questions)),
            )
            session_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Persist all questions
            for q in questions:
                conn.execute(
                    """
                    INSERT INTO session_questions
                        (session_id, item_id, exercise_type, direction,
                         correct_answer, distractors_json, prompt_text, position)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (session_id, q["item_id"], q["exercise_type"], q["direction"],
                     q["correct_answer"], json.dumps(q["distractors"]),
                     q["prompt_text"], q["position"]),
                )

            # Ensure item_progress rows exist for all selected items
            for iid in item_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO item_progress(item_id) VALUES (?)", (iid,)
                )

            session = dict(conn.execute(
                "SELECT * FROM training_sessions WHERE id=?", (session_id,)
            ).fetchone())
            first_q = self._get_current_question(conn, session_id)

        return session, first_q

    # ======================================================================
    # Session retrieval
    # ======================================================================

    def get_session(self, session_id: int) -> tuple[dict, dict | None, int]:
        """Return (session, current_question|None, questions_remaining)."""
        with get_db(self.db_path) as conn:
            session = self._load_session(conn, session_id)
            question = self._get_current_question(conn, session_id)
            remaining = conn.execute(
                "SELECT COUNT(*) FROM session_questions "
                "WHERE session_id=? AND is_correct IS NULL",
                (session_id,),
            ).fetchone()[0]
        return session, question, remaining

    # ======================================================================
    # Answer submission
    # ======================================================================

    def submit_answer(
        self, session_id: int, question_id: int, answer_given: str
    ) -> dict:
        """Process a user answer. Returns AnswerResultResponse dict."""
        with get_db(self.db_path) as conn:
            session = self._load_session(conn, session_id)
            if session["status"] != "active":
                raise ValueError(f"Session {session_id} is not active.")

            q_row = conn.execute(
                "SELECT * FROM session_questions WHERE id=? AND session_id=?",
                (question_id, session_id),
            ).fetchone()
            if q_row is None:
                raise ValueError(f"Question {question_id} not found in session {session_id}.")
            q = dict(q_row)
            if q["is_correct"] is not None:
                raise ValueError(f"Question {question_id} has already been answered.")

            alternatives = _parse_json(
                self._load_item_alternatives(conn, q["item_id"]), []
            )
            is_correct, error_type = check_answer(
                answer_given, q["correct_answer"], alternatives
            )

            # Persist the answer
            conn.execute(
                """
                UPDATE session_questions
                SET answer_given=?, is_correct=?, error_type=?, answered_at=?
                WHERE id=?
                """,
                (answer_given, int(is_correct), error_type, _now(), question_id),
            )

            # Update item_progress
            self._update_progress(conn, q["item_id"], is_correct, q["exercise_type"])

            # Update SRS state on study_items
            newly_mastered = self._update_srs(
                conn, q["item_id"], is_correct, q["exercise_type"]
            )

            # Log to review_events for backward compatibility
            self._log_review_event(conn, q["item_id"], is_correct, q["exercise_type"])

            # If wrong, schedule a retry
            if not is_correct:
                max_pos = conn.execute(
                    "SELECT COALESCE(MAX(position), 0) FROM session_questions WHERE session_id=?",
                    (session_id,),
                ).fetchone()[0]
                retry_pos = max_pos + random.randint(_RETRY_OFFSET_MIN, _RETRY_OFFSET_MAX)
                conn.execute(
                    """
                    INSERT INTO session_questions
                        (session_id, item_id, exercise_type, direction,
                         correct_answer, distractors_json, prompt_text, position, retry_scheduled)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (session_id, q["item_id"], q["exercise_type"], q["direction"],
                     q["correct_answer"], q["distractors_json"], q["prompt_text"], retry_pos),
                )
                conn.execute(
                    "UPDATE training_sessions SET total_questions = total_questions + 1 WHERE id=?",
                    (session_id,),
                )

            # Update session counters
            if is_correct:
                conn.execute(
                    "UPDATE training_sessions SET correct_count = correct_count + 1 WHERE id=?",
                    (session_id,),
                )
                if newly_mastered:
                    self._append_json_list(conn, session_id, "newly_mastered_ids", q["item_id"])
            else:
                conn.execute(
                    "UPDATE training_sessions SET wrong_count = wrong_count + 1 WHERE id=?",
                    (session_id,),
                )
                self._append_json_list(conn, session_id, "error_item_ids", q["item_id"])

            # Get next question
            next_q = self._get_current_question(conn, session_id)
            session_complete = next_q is None

            if session_complete:
                conn.execute(
                    "UPDATE training_sessions SET status='completed', ended_at=? WHERE id=?",
                    (_now(), session_id),
                )

            explanation = None
            if not is_correct:
                explanation = f"Correct answer: {q['correct_answer']}"
            elif error_type == "spelling":
                explanation = "Close! Watch the spelling."
            elif error_type == "partial":
                explanation = "Correct meaning, but check the exact phrasing."

        return {
            "is_correct": is_correct,
            "error_type": error_type,
            "correct_answer": q["correct_answer"],
            "explanation": explanation,
            "next_question": next_q,
            "session_complete": session_complete,
            "newly_mastered": newly_mastered,
            "newly_difficult": False,
        }

    # ======================================================================
    # Session completion
    # ======================================================================

    def complete_session(self, session_id: int) -> dict:
        """Explicitly mark a session as completed and return results."""
        with get_db(self.db_path) as conn:
            session = self._load_session(conn, session_id)
            if session["status"] == "active":
                conn.execute(
                    "UPDATE training_sessions SET status='completed', ended_at=? WHERE id=?",
                    (_now(), session_id),
                )
        return self.get_session_results(session_id)

    def get_session_results(self, session_id: int) -> dict:
        """Return a SessionResults dict for a (completed) session."""
        with get_db(self.db_path) as conn:
            session = dict(self._load_session(conn, session_id))

        total = session["total_questions"]
        correct = session["correct_count"]
        wrong = session["wrong_count"]
        accuracy = round(correct / total * 100, 1) if total > 0 else 0.0

        # Duration
        duration = None
        if session["ended_at"] and session["started_at"]:
            try:
                fmt = "%Y-%m-%d %H:%M:%S"
                start = datetime.strptime(session["started_at"], fmt)
                end = datetime.strptime(session["ended_at"], fmt)
                duration = (end - start).total_seconds()
            except ValueError:
                pass

        newly_mastered = self._resolve_item_summaries(
            _parse_json(session["newly_mastered_ids"], [])
        )
        error_items = self._resolve_item_summaries_with_errors(session_id)
        newly_difficult: list[dict] = []

        by_exercise = self._session_exercise_stats(session_id)

        return {
            "session_id": session_id,
            "mode": session["mode"],
            "total_questions": total,
            "correct_count": correct,
            "wrong_count": wrong,
            "accuracy_pct": accuracy,
            "duration_seconds": duration,
            "newly_mastered": newly_mastered,
            "newly_difficult": newly_difficult,
            "error_items": error_items,
            "by_exercise_type": by_exercise,
        }

    # ======================================================================
    # Statistics
    # ======================================================================

    def get_item_progress(self, item_id: int) -> dict:
        with get_db(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM item_progress WHERE item_id=?", (item_id,)
            ).fetchone()
        if row is None:
            raise ValueError(f"No progress record for item {item_id}.")
        return dict(row)

    def get_user_stats(self) -> dict:
        with get_db(self.db_path) as conn:
            status_rows = conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM study_items GROUP BY status"
            ).fetchall()
            status_counts = {r["status"]: r["cnt"] for r in status_rows}

            by_lexical = dict(conn.execute(
                "SELECT lexical_type, COUNT(*) AS cnt FROM study_items "
                "WHERE lexical_type IS NOT NULL GROUP BY lexical_type"
            ).fetchall())

            by_type = dict(conn.execute(
                "SELECT item_type, COUNT(*) AS cnt FROM study_items GROUP BY item_type"
            ).fetchall())

            total_sessions = conn.execute(
                "SELECT COUNT(*) FROM training_sessions WHERE status='completed'"
            ).fetchone()[0]

            q_stats = conn.execute(
                "SELECT COUNT(*) AS total, SUM(is_correct) AS correct "
                "FROM session_questions WHERE is_correct IS NOT NULL"
            ).fetchone()
            total_q = q_stats["total"] or 0
            total_correct = int(q_stats["correct"] or 0)

        accuracy = round(total_correct / total_q * 100, 1) if total_q > 0 else 0.0
        total_items = sum(status_counts.values())

        return {
            "total_items": total_items,
            "new": status_counts.get("new", 0),
            "learning": status_counts.get("learning", 0),
            "review": status_counts.get("review", 0),
            "mastered": status_counts.get("mastered", 0),
            "difficult": status_counts.get("difficult", 0),
            "suspended": status_counts.get("suspended", 0),
            "by_lexical_type": by_lexical,
            "by_item_type": by_type,
            "total_training_sessions": total_sessions,
            "total_questions_answered": total_q,
            "overall_accuracy_pct": accuracy,
        }

    def get_filtered_items(
        self,
        mode: str | None = None,
        lexical_type: str | None = None,
        item_type: str | None = None,
        topic: str | None = None,
        difficulty_min: int | None = None,
        difficulty_max: int | None = None,
        status: list[str] | None = None,
        language_target: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        conditions = ["1=1"]
        params: list[Any] = []

        if lexical_type:
            conditions.append("lexical_type = ?")
            params.append(lexical_type)
        if item_type:
            conditions.append("item_type = ?")
            params.append(item_type)
        if topic:
            conditions.append("topic = ?")
            params.append(topic)
        if difficulty_min is not None:
            conditions.append("difficulty_level >= ?")
            params.append(difficulty_min)
        if difficulty_max is not None:
            conditions.append("difficulty_level <= ?")
            params.append(difficulty_max)
        if status:
            placeholders = ",".join("?" * len(status))
            conditions.append(f"status IN ({placeholders})")
            params.extend(status)
        if language_target:
            conditions.append("language_target = ?")
            params.append(language_target)

        params.append(limit)
        where = " AND ".join(conditions)

        with get_db(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM study_items WHERE {where} LIMIT ?", params
            ).fetchall()
        return [dict(r) for r in rows]

    # ======================================================================
    # Private: item selection
    # ======================================================================

    def _select_items(
        self, mode: str, filters: dict, target_count: int
    ) -> list[dict]:
        """Select items for a session based on mode and filters."""
        now_dt = datetime.now(timezone.utc)
        base_q = "SELECT si.*, ip.current_wrong_streak, ip.last_shown_at FROM study_items si LEFT JOIN item_progress ip ON ip.item_id = si.id WHERE si.status != 'suspended'"
        conditions: list[str] = []
        params: list[Any] = []

        # Apply user filters
        if filters.get("lexical_type"):
            conditions.append("si.lexical_type = ?")
            params.append(filters["lexical_type"])
        if filters.get("item_type"):
            conditions.append("si.item_type = ?")
            params.append(filters["item_type"])
        if filters.get("topic"):
            conditions.append("si.topic = ?")
            params.append(filters["topic"])
        if filters.get("difficulty_min") is not None:
            conditions.append("si.difficulty_level >= ?")
            params.append(filters["difficulty_min"])
        if filters.get("difficulty_max") is not None:
            conditions.append("si.difficulty_level <= ?")
            params.append(filters["difficulty_max"])
        if filters.get("language_target"):
            conditions.append("si.language_target = ?")
            params.append(filters["language_target"])

        # Mode-specific status/ordering filters
        if mode == "new_only":
            conditions.append("si.status = 'new'")
        elif mode == "difficult":
            conditions.append("si.status IN ('difficult','learning')")
        elif mode == "overdue":
            conditions.append("si.next_review_at <= strftime('%Y-%m-%d %H:%M:%S','now')")
        elif mode == "errors":
            conditions.append("ip.times_wrong > 0")
        elif mode == "by_type":
            # Filters already applied above; no extra status filter
            pass

        if filters.get("status"):
            placeholders = ",".join("?" * len(filters["status"]))
            conditions.append(f"si.status IN ({placeholders})")
            params.extend(filters["status"])

        where_extra = (" AND " + " AND ".join(conditions)) if conditions else ""
        sql = base_q + where_extra
        params.append(target_count * 3)  # fetch more than needed for mixing
        sql += " LIMIT ?"

        with get_db(self.db_path) as conn:
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

        if mode == "auto":
            rows = self._auto_mix(rows, target_count, now_dt)
        else:
            rows = rows[:target_count]

        return rows

    def _auto_mix(
        self, all_items: list[dict], target: int, now_dt: datetime
    ) -> list[dict]:
        """Build a mixed set according to _AUTO_MIX ratios."""
        by_bucket: dict[str, list[dict]] = {
            "new": [], "active": [], "review": [], "mastered": []
        }
        for item in all_items:
            s = item["status"]
            if s == "new":
                by_bucket["new"].append(item)
            elif s in ("learning", "difficult"):
                by_bucket["active"].append(item)
            elif s == "review":
                by_bucket["review"].append(item)
            elif s == "mastered":
                by_bucket["mastered"].append(item)

        # Sort each bucket by priority (descending)
        def _sort_key(item: dict) -> float:
            overdue = 0.0
            if item.get("next_review_at"):
                try:
                    nra = datetime.strptime(item["next_review_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    overdue = max(0.0, (now_dt - nra).total_seconds() / 86400)
                except ValueError:
                    pass
            last_shown = None
            if item.get("last_shown_at"):
                try:
                    ls = datetime.strptime(item["last_shown_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    last_shown = (now_dt - ls).total_seconds() / 86400
                except ValueError:
                    pass
            return compute_priority(
                item["status"], overdue,
                int(item.get("current_wrong_streak") or 0),
                last_shown,
            )

        for bucket in by_bucket.values():
            bucket.sort(key=_sort_key, reverse=True)

        selected: list[dict] = []
        for bucket_name, ratio in _AUTO_MIX.items():
            count = round(target * ratio)
            pool = by_bucket[bucket_name]
            selected.extend(pool[:count])

        # Fill shortfalls from any bucket
        used_ids = {item["id"] for item in selected}
        leftovers = [i for i in all_items if i["id"] not in used_ids]
        while len(selected) < target and leftovers:
            selected.append(leftovers.pop(0))

        return selected[:target]

    # ======================================================================
    # Private: question queue building
    # ======================================================================

    def _build_question_queue(
        self, items: list[dict], target_count: int
    ) -> list[dict]:
        """Build a list of question dicts with position and exercise type."""
        questions: list[dict] = []
        last_types: list[str] = []

        for item in items:
            ex_type = self._pick_exercise_type(item, last_types)
            q = self._make_question(item, ex_type)
            if q is None:
                # Fallback: mc is always possible if native_text exists
                if item.get("native_text"):
                    ex_type = "mc"
                    q = self._make_question(item, ex_type)
                if q is None:
                    continue
            questions.append(q)
            last_types = (last_types + [ex_type])[-3:]

        for i, q in enumerate(questions):
            q["position"] = i

        return questions[:target_count]

    def _pick_exercise_type(
        self, item: dict, last_types: list[str]
    ) -> str:
        """Pick the most appropriate exercise type, avoiding 2 same in a row."""
        has_native = bool(item.get("native_text", "").strip())
        has_example = bool(item.get("example_sentence", "").strip())

        eligible: list[str] = []
        if has_native:
            eligible += ["mc", "input"]
        if has_example and has_native:
            eligible += ["context", "fill"]

        if not eligible:
            return "mc"  # will be skipped by _make_question if no native_text

        # Prefer types not in the last 2
        preferred = [t for t in eligible if t not in last_types[-2:]]
        if not preferred:
            preferred = eligible

        return random.choice(preferred)

    def _make_question(self, item: dict, ex_type: str) -> dict | None:
        """Build a question dict for the given item and exercise type."""
        if not item.get("native_text", "").strip() and ex_type in ("mc", "input"):
            return None
        if not item.get("example_sentence", "").strip() and ex_type in ("context", "fill"):
            return None

        if ex_type == "mc":
            distractors = self._distractors.select_native_distractors(
                item["id"], item["item_type"], item.get("lexical_type")
            )
            return {
                "item_id": item["id"],
                "exercise_type": "mc",
                "direction": "en_to_ru",
                "correct_answer": item["native_text"],
                "distractors": distractors,
                "prompt_text": item["target_text"],
            }

        elif ex_type == "input":
            return {
                "item_id": item["id"],
                "exercise_type": "input",
                "direction": "ru_to_en",
                "correct_answer": item["target_text"],
                "distractors": [],
                "prompt_text": item["native_text"],
            }

        elif ex_type == "context":
            distractors = self._distractors.select_native_distractors(
                item["id"], item["item_type"], item.get("lexical_type")
            )
            return {
                "item_id": item["id"],
                "exercise_type": "context",
                "direction": "en_to_ru",
                "correct_answer": item["native_text"],
                "distractors": distractors,
                "prompt_text": item["example_sentence"],
            }

        elif ex_type == "fill":
            # Replace first occurrence of target_text in example_sentence with _____
            sentence = item["example_sentence"]
            target = item["target_text"]
            blanked = re.sub(
                re.escape(target), "_____", sentence, count=1, flags=re.IGNORECASE
            )
            if blanked == sentence:
                # Target word not found in sentence — use generic blank
                words = sentence.split()
                if words:
                    blanked = sentence.replace(words[0], "_____", 1)
            return {
                "item_id": item["id"],
                "exercise_type": "fill",
                "direction": "en_to_ru",
                "correct_answer": item["target_text"],
                "distractors": [],
                "prompt_text": blanked,
            }

        return None

    # ======================================================================
    # Private: progress and SRS updates
    # ======================================================================

    def _update_progress(
        self, conn, item_id: int, is_correct: bool, exercise_type: str
    ) -> None:
        """Update item_progress counters atomically."""
        row = conn.execute(
            "SELECT * FROM item_progress WHERE item_id=?", (item_id,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT OR IGNORE INTO item_progress(item_id) VALUES (?)", (item_id,)
            )
            row = conn.execute(
                "SELECT * FROM item_progress WHERE item_id=?", (item_id,)
            ).fetchone()

        p = dict(row)
        p["times_shown"] = p.get("times_shown", 0) + 1

        if is_correct:
            p["times_correct"] = p.get("times_correct", 0) + 1
            p["current_correct_streak"] = p.get("current_correct_streak", 0) + 1
            p["current_wrong_streak"] = 0
            p["last_correct_at"] = _now()
            if exercise_type in ACTIVE_RECALL_TYPES:
                p["active_recall_successes"] = p.get("active_recall_successes", 0) + 1
        else:
            p["times_wrong"] = p.get("times_wrong", 0) + 1
            p["current_wrong_streak"] = p.get("current_wrong_streak", 0) + 1
            p["current_correct_streak"] = 0
            p["last_wrong_at"] = _now()

        # Update per-exercise-type stats
        stats = _parse_json(p.get("exercise_type_stats"), {})
        et_stats = stats.get(exercise_type, {"shown": 0, "correct": 0})
        et_stats["shown"] += 1
        if is_correct:
            et_stats["correct"] += 1
        stats[exercise_type] = et_stats
        p["exercise_type_stats"] = json.dumps(stats)

        p["last_shown_at"] = _now()
        p["updated_at"] = _now()

        conn.execute(
            """
            UPDATE item_progress SET
                times_shown=?, times_correct=?, times_wrong=?,
                current_correct_streak=?, current_wrong_streak=?,
                exercise_type_stats=?, active_recall_successes=?,
                last_shown_at=?, last_correct_at=?, last_wrong_at=?,
                updated_at=?
            WHERE item_id=?
            """,
            (
                p["times_shown"], p.get("times_correct", 0), p.get("times_wrong", 0),
                p["current_correct_streak"], p["current_wrong_streak"],
                p["exercise_type_stats"], p.get("active_recall_successes", 0),
                p.get("last_shown_at"), p.get("last_correct_at"), p.get("last_wrong_at"),
                p["updated_at"],
                item_id,
            ),
        )

    def _update_srs(
        self, conn, item_id: int, is_correct: bool, exercise_type: str
    ) -> bool:
        """Apply SRS update to study_items. Returns True if item became mastered."""
        item_row = conn.execute(
            "SELECT ease, interval_days, repetitions, lapses, status FROM study_items WHERE id=?",
            (item_id,),
        ).fetchone()
        if item_row is None:
            return False

        item = dict(item_row)
        rating = compute_srs_rating(is_correct, exercise_type, item["ease"])
        new_ease, new_interval, new_reps, new_lapses, new_status = apply_srs(
            rating, item["ease"], item["interval_days"], item["repetitions"], item["lapses"]
        )

        # Check mastery (do not override existing 'mastered' or 'difficult' down)
        progress_row = conn.execute(
            "SELECT * FROM item_progress WHERE item_id=?", (item_id,)
        ).fetchone()
        newly_mastered = False
        if progress_row:
            progress = dict(progress_row)
            if not progress.get("is_mastered") and check_mastery(progress):
                new_status = "mastered"
                newly_mastered = True
                conn.execute(
                    "UPDATE item_progress SET is_mastered=1, mastered_at=? WHERE item_id=?",
                    (_now(), item_id),
                )

        # Preserve 'mastered' and 'difficult' status unless there's a regression
        current_status = item["status"]
        if current_status in ("mastered", "difficult") and new_status == "learning":
            new_status = current_status  # keep hard-won status

        conn.execute(
            """
            UPDATE study_items SET
                ease=?, interval_days=?, repetitions=?, lapses=?,
                status=?, last_reviewed_at=?,
                next_review_at=datetime('now', ? || ' days'),
                updated_at=?
            WHERE id=?
            """,
            (
                new_ease, new_interval, new_reps, new_lapses,
                new_status, _now(),
                str(new_interval),
                _now(), item_id,
            ),
        )
        return newly_mastered

    def _log_review_event(
        self, conn, item_id: int, is_correct: bool, exercise_type: str
    ) -> None:
        """Insert a backward-compatible review_events row."""
        item = conn.execute(
            "SELECT ease, interval_days FROM study_items WHERE id=?", (item_id,)
        ).fetchone()
        if item is None:
            return
        rating = compute_srs_rating(is_correct, exercise_type, item["ease"])
        conn.execute(
            """
            INSERT INTO review_events
                (item_id, rating, ease_before, interval_before, ease_after, interval_after)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (item_id, rating, item["ease"], item["interval_days"],
             item["ease"], item["interval_days"]),
        )

    # ======================================================================
    # Private: query helpers
    # ======================================================================

    def _load_session(self, conn, session_id: int) -> dict:
        row = conn.execute(
            "SELECT * FROM training_sessions WHERE id=?", (session_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Session {session_id} not found.")
        return dict(row)

    def _get_current_question(self, conn, session_id: int) -> dict | None:
        row = conn.execute(
            """
            SELECT * FROM session_questions
            WHERE session_id=? AND is_correct IS NULL
            ORDER BY position
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        return dict(row) if row else None

    def _load_item_alternatives(self, conn, item_id: int) -> str:
        row = conn.execute(
            "SELECT alternative_translations FROM study_items WHERE id=?", (item_id,)
        ).fetchone()
        return row["alternative_translations"] if row else "[]"

    def _resolve_item_summaries(self, item_ids: list[int]) -> list[dict]:
        if not item_ids:
            return []
        with get_db(self.db_path) as conn:
            placeholders = ",".join("?" * len(item_ids))
            rows = conn.execute(
                f"SELECT id, target_text, native_text, item_type FROM study_items "
                f"WHERE id IN ({placeholders})",
                item_ids,
            ).fetchall()
        return [dict(r) for r in rows]

    def _resolve_item_summaries_with_errors(self, session_id: int) -> list[dict]:
        with get_db(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT si.id, si.target_text, si.native_text, si.item_type,
                       sq.error_type
                FROM session_questions sq
                JOIN study_items si ON si.id = sq.item_id
                WHERE sq.session_id=? AND sq.is_correct=0
                """,
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _session_exercise_stats(self, session_id: int) -> dict:
        with get_db(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT exercise_type,
                       COUNT(*) AS shown,
                       SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END) AS correct
                FROM session_questions
                WHERE session_id=? AND is_correct IS NOT NULL
                GROUP BY exercise_type
                """,
                (session_id,),
            ).fetchall()
        return {
            r["exercise_type"]: {"shown": r["shown"], "correct": int(r["correct"] or 0)}
            for r in rows
        }

    @staticmethod
    def _append_json_list(conn, session_id: int, column: str, item_id: int) -> None:
        """Append item_id to a JSON list column in training_sessions."""
        row = conn.execute(
            f"SELECT {column} FROM training_sessions WHERE id=?", (session_id,)
        ).fetchone()
        current: list = _parse_json(row[0] if row else None, [])
        if item_id not in current:
            current.append(item_id)
        conn.execute(
            f"UPDATE training_sessions SET {column}=? WHERE id=?",
            (json.dumps(current), session_id),
        )

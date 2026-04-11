"""Vocabulary study service: insert, SRS scheduling, review, stats."""
from __future__ import annotations

import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .db import get_db, init_db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VALID_RATINGS = {"again", "hard", "good", "easy"}
VALID_STATUSES = {"new", "learning", "review", "mastered", "difficult", "suspended"}
VALID_ITEM_TYPES = {"word", "phrasal_verb", "idiom", "collocation"}
VALID_LEXICAL_TYPES = {"noun", "verb", "adjective", "adverb"}
VALID_SOURCE_KINDS = {"manual", "mcp_extract", "mcp_manual"}

EASE_MIN = 1.3
EASE_DEFAULT = 2.5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _normalize(text: str) -> str:
    """Casefold + NFKC for deduplication key."""
    return unicodedata.normalize("NFKC", text.strip()).casefold()


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _due_at(interval_days: float) -> str:
    due = datetime.now(timezone.utc) + timedelta(days=interval_days)
    return due.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# SRS (SM-2 variant)
# ---------------------------------------------------------------------------
def apply_srs(
    rating: str,
    ease: float,
    interval_days: float,
    repetitions: int,
    lapses: int,
) -> tuple[float, float, int, int, str]:
    """Return (new_ease, new_interval_days, new_repetitions, new_lapses, new_status).

    Rating semantics:
      again — failed recall; reset interval; ease penalty; lapse counted
      hard  — recalled with difficulty; mild ease penalty; short interval boost
      good  — normal recall; standard SM-2 progression
      easy  — effortless recall; ease bonus; accelerated interval
    """
    if rating == "again":
        ease = max(EASE_MIN, ease - 0.2)
        interval_days = 1.0
        repetitions = 0
        lapses = lapses + 1
        status = "learning"

    elif rating == "hard":
        ease = max(EASE_MIN, ease - 0.15)
        interval_days = max(1.0, interval_days * 1.2)
        repetitions = repetitions + 1
        status = "learning" if repetitions < 3 else "review"

    elif rating == "good":
        if repetitions == 0:
            interval_days = 1.0
        elif repetitions == 1:
            interval_days = 4.0
        else:
            interval_days = max(1.0, interval_days * ease)
        repetitions = repetitions + 1
        status = "learning" if repetitions < 3 else "review"

    else:  # easy
        ease = min(ease + 0.15, 5.0)
        if repetitions == 0:
            interval_days = 4.0
        elif repetitions == 1:
            interval_days = 7.0
        else:
            interval_days = max(1.0, interval_days * ease * 1.3)
        repetitions = repetitions + 1
        status = "review"

    return ease, interval_days, repetitions, lapses, status


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class StudyService:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        init_db(db_path)

    # ------------------------------------------------------------------
    # Write: add items
    # ------------------------------------------------------------------
    def add_items(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """Insert study items with deduplication.

        Dedup key: (normalize(target_text), item_type, language_target, language_native).
        Returns { "saved": int, "skipped": int, "ids": list[int] }.
        """
        saved_ids: list[int] = []
        skipped = 0

        with get_db(self.db_path) as conn:
            for item in items:
                item_type = item.get("item_type", "word")
                target_text = str(item.get("target_text", "")).strip()
                language_target = str(item.get("language_target", "en"))
                language_native = str(item.get("language_native", "ru"))

                if not target_text or item_type not in VALID_ITEM_TYPES:
                    skipped += 1
                    continue

                target_norm = _normalize(target_text)

                existing = conn.execute(
                    """SELECT id FROM study_items
                       WHERE lower(trim(target_text)) = ?
                         AND item_type = ?
                         AND language_target = ?
                         AND language_native = ?""",
                    (target_norm, item_type, language_target, language_native),
                ).fetchone()

                if existing:
                    skipped += 1
                    continue

                conn.execute(
                    """INSERT INTO study_items
                       (item_type, target_text, native_text, context_note, example_sentence,
                        source_kind, source_turn_text, source_response_text,
                        language_target, language_native)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        item_type,
                        target_text,
                        str(item.get("native_text", "")),
                        str(item.get("context_note", "")),
                        str(item.get("example_sentence", "")),
                        item.get("source_kind", "manual") if item.get("source_kind") in VALID_SOURCE_KINDS else "manual",
                        str(item.get("source_turn_text", "")),
                        str(item.get("source_response_text", "")),
                        language_target,
                        language_native,
                    ),
                )
                row_id: int = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                saved_ids.append(row_id)

        return {"saved": len(saved_ids), "skipped": skipped, "ids": saved_ids}

    # ------------------------------------------------------------------
    # Read: list items
    # ------------------------------------------------------------------
    def get_items(
        self,
        status: str | None = None,
        lexical_type: str | None = None,
        item_type: str | None = None,
        topic: str | None = None,
        difficulty_min: int | None = None,
        difficulty_max: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return items ordered by created_at DESC with optional filters."""
        conditions: list[str] = []
        params: list[Any] = []

        if status:
            conditions.append("status = ?")
            params.append(status)
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

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.extend([limit, offset])

        with get_db(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM study_items {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",  # noqa: S608
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Read: due queue
    # ------------------------------------------------------------------
    def get_due(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return items due for review (next_review_at <= now).

        Ordering: new first, then learning, then review; within each group by next_review_at ASC.
        """
        now = _now_utc()
        with get_db(self.db_path) as conn:
            rows = conn.execute(
                """SELECT * FROM study_items
                   WHERE status != 'suspended'
                     AND next_review_at <= ?
                   ORDER BY
                     CASE status
                       WHEN 'new'      THEN 0
                       WHEN 'learning' THEN 1
                       ELSE                 2
                     END,
                     next_review_at ASC
                   LIMIT ?""",
                (now, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Write: review
    # ------------------------------------------------------------------
    def review_item(self, item_id: int, rating: str) -> dict[str, Any]:
        """Apply an SRS rating to one item and log the review event.

        Returns the updated item row.
        Raises ValueError for unknown item_id or invalid rating.
        """
        if rating not in VALID_RATINGS:
            raise ValueError(
                f"Invalid rating '{rating}'. Must be one of: {', '.join(sorted(VALID_RATINGS))}"
            )

        with get_db(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM study_items WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Item {item_id} not found")

            old = dict(row)
            new_ease, new_interval, new_reps, new_lapses, new_status = apply_srs(
                rating,
                old["ease"],
                old["interval_days"],
                old["repetitions"],
                old["lapses"],
            )
            now = _now_utc()
            due_at = _due_at(new_interval)

            conn.execute(
                """INSERT INTO review_events
                   (item_id, rating, ease_before, interval_before, ease_after, interval_after)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (item_id, rating, old["ease"], old["interval_days"], new_ease, new_interval),
            )
            conn.execute(
                """UPDATE study_items
                   SET ease = ?, interval_days = ?, repetitions = ?, lapses = ?,
                       status = ?, next_review_at = ?, last_reviewed_at = ?, updated_at = ?
                   WHERE id = ?""",
                (new_ease, new_interval, new_reps, new_lapses, new_status, due_at, now, now, item_id),
            )
            updated = conn.execute(
                "SELECT * FROM study_items WHERE id = ?", (item_id,)
            ).fetchone()

        return dict(updated)

    # ------------------------------------------------------------------
    # Write: update
    # ------------------------------------------------------------------
    def update_item(self, item_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        """Update editable content fields of a study item.

        Allowed keys: item_type, target_text, native_text, context_note,
                      example_sentence, status.
        Raises ValueError for unknown item_id or invalid field values.
        """
        EDITABLE = {
            "item_type", "target_text", "native_text", "context_note",
            "example_sentence", "status",
            # new vocabulary-metadata fields
            "lexical_type", "alternative_translations", "topic",
            "difficulty_level", "tags", "example_sentence_native",
        }
        filtered = {k: v for k, v in updates.items() if k in EDITABLE}
        if not filtered:
            raise ValueError("No editable fields provided.")

        if "item_type" in filtered and filtered["item_type"] not in VALID_ITEM_TYPES:
            raise ValueError(f"Invalid item_type '{filtered['item_type']}'.")
        if "status" in filtered and filtered["status"] not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{filtered['status']}'.")
        if "lexical_type" in filtered and filtered["lexical_type"] is not None:
            if filtered["lexical_type"] not in VALID_LEXICAL_TYPES:
                raise ValueError(f"Invalid lexical_type '{filtered['lexical_type']}'.")
        if "target_text" in filtered:
            filtered["target_text"] = str(filtered["target_text"]).strip()
            if not filtered["target_text"]:
                raise ValueError("target_text cannot be empty.")

        filtered["updated_at"] = _now_utc()

        set_clause = ", ".join(f"{col} = ?" for col in filtered)
        values = list(filtered.values()) + [item_id]

        with get_db(self.db_path) as conn:
            row = conn.execute(
                "SELECT id FROM study_items WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Item {item_id} not found")

            conn.execute(
                f"UPDATE study_items SET {set_clause} WHERE id = ?", values  # noqa: S608
            )
            updated = conn.execute(
                "SELECT * FROM study_items WHERE id = ?", (item_id,)
            ).fetchone()

        return dict(updated)

    # ------------------------------------------------------------------
    # Write: delete
    # ------------------------------------------------------------------
    def delete_item(self, item_id: int) -> None:
        """Delete a study item and all its review events.

        Raises ValueError if item_id does not exist.
        """
        with get_db(self.db_path) as conn:
            row = conn.execute(
                "SELECT id FROM study_items WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Item {item_id} not found")
            conn.execute("DELETE FROM review_events WHERE item_id = ?", (item_id,))
            conn.execute("DELETE FROM study_items WHERE id = ?", (item_id,))

    # ------------------------------------------------------------------
    # Read: stats
    # ------------------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        """Return counts per status, due count, and total review events."""
        now = _now_utc()
        with get_db(self.db_path) as conn:
            status_rows = conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM study_items GROUP BY status"
            ).fetchall()
            due_count: int = conn.execute(
                """SELECT COUNT(*) FROM study_items
                   WHERE status != 'suspended' AND next_review_at <= ?""",
                (now,),
            ).fetchone()[0]
            total_reviews: int = conn.execute(
                "SELECT COUNT(*) FROM review_events"
            ).fetchone()[0]
            total_items: int = conn.execute(
                "SELECT COUNT(*) FROM study_items"
            ).fetchone()[0]

        result: dict[str, Any] = {s: 0 for s in VALID_STATUSES}
        for row in status_rows:
            if row["status"] in result:
                result[row["status"]] = row["cnt"]
        result["due"] = due_count
        result["total_reviews"] = total_reviews
        result["total_items"] = total_items
        return result

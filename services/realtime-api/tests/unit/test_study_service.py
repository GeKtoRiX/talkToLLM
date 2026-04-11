"""Unit tests for the study service: SRS logic, deduplication, queries."""
from __future__ import annotations

import pytest

from app.study.service import StudyService, apply_srs, EASE_MIN, EASE_DEFAULT


# ---------------------------------------------------------------------------
# apply_srs unit tests (pure function, no DB)
# ---------------------------------------------------------------------------

class TestApplySrs:
    def test_again_resets_repetitions(self):
        _, _, reps, _, _ = apply_srs("again", EASE_DEFAULT, 10.0, 5, 0)
        assert reps == 0

    def test_again_resets_interval_to_one(self):
        _, interval, _, _, _ = apply_srs("again", EASE_DEFAULT, 10.0, 5, 0)
        assert interval == 1.0

    def test_again_increments_lapses(self):
        _, _, _, lapses, _ = apply_srs("again", EASE_DEFAULT, 10.0, 3, 2)
        assert lapses == 3

    def test_again_sets_status_learning(self):
        *_, status = apply_srs("again", EASE_DEFAULT, 10.0, 5, 0)
        assert status == "learning"

    def test_again_ease_cannot_go_below_min(self):
        ease, _, _, _, _ = apply_srs("again", EASE_MIN, 1.0, 0, 0)
        assert ease == EASE_MIN

    def test_hard_reduces_ease(self):
        ease, _, _, _, _ = apply_srs("hard", EASE_DEFAULT, 1.0, 0, 0)
        assert ease < EASE_DEFAULT

    def test_hard_increases_interval(self):
        _, interval, _, _, _ = apply_srs("hard", EASE_DEFAULT, 4.0, 3, 0)
        assert interval > 4.0

    def test_hard_ease_floor(self):
        ease, _, _, _, _ = apply_srs("hard", EASE_MIN, 1.0, 0, 0)
        assert ease == EASE_MIN

    def test_good_first_rep_interval_is_one(self):
        _, interval, _, _, _ = apply_srs("good", EASE_DEFAULT, 1.0, 0, 0)
        assert interval == 1.0

    def test_good_second_rep_interval_is_four(self):
        _, interval, _, _, _ = apply_srs("good", EASE_DEFAULT, 1.0, 1, 0)
        assert interval == 4.0

    def test_good_later_rep_uses_ease(self):
        ease = 2.5
        base_interval = 4.0
        _, interval, _, _, _ = apply_srs("good", ease, base_interval, 2, 0)
        assert interval == pytest.approx(base_interval * ease)

    def test_good_increments_repetitions(self):
        _, _, reps, _, _ = apply_srs("good", EASE_DEFAULT, 1.0, 3, 0)
        assert reps == 4

    def test_good_status_learning_before_threshold(self):
        *_, status = apply_srs("good", EASE_DEFAULT, 1.0, 0, 0)
        assert status == "learning"

    def test_good_status_review_at_threshold(self):
        *_, status = apply_srs("good", EASE_DEFAULT, 4.0, 2, 0)
        assert status == "review"

    def test_easy_increases_ease(self):
        ease, _, _, _, _ = apply_srs("easy", EASE_DEFAULT, 1.0, 3, 0)
        assert ease > EASE_DEFAULT

    def test_easy_first_rep_interval_is_four(self):
        _, interval, _, _, _ = apply_srs("easy", EASE_DEFAULT, 1.0, 0, 0)
        assert interval == 4.0

    def test_easy_second_rep_interval_is_seven(self):
        _, interval, _, _, _ = apply_srs("easy", EASE_DEFAULT, 1.0, 1, 0)
        assert interval == 7.0

    def test_easy_later_rep_accelerated(self):
        ease = 2.5
        base = 7.0
        _, interval, _, _, _ = apply_srs("easy", ease, base, 2, 0)
        assert interval == pytest.approx(base * (ease + 0.15) * 1.3)

    def test_easy_always_sets_status_review(self):
        *_, status = apply_srs("easy", EASE_DEFAULT, 1.0, 0, 0)
        assert status == "review"


# ---------------------------------------------------------------------------
# StudyService integration tests (uses temp SQLite via tmp_path)
# ---------------------------------------------------------------------------

@pytest.fixture
def svc(tmp_path):
    return StudyService(tmp_path / "test_study.sqlite")


class TestAddItems:
    def test_add_single_item(self, svc):
        result = svc.add_items([{"item_type": "word", "target_text": "hello"}])
        assert result["saved"] == 1
        assert result["skipped"] == 0
        assert len(result["ids"]) == 1

    def test_add_multiple_items(self, svc):
        result = svc.add_items([
            {"item_type": "word", "target_text": "apple"},
            {"item_type": "word", "target_text": "banana"},
        ])
        assert result["saved"] == 2

    def test_deduplication_same_text_same_type(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "hello"}])
        result = svc.add_items([{"item_type": "word", "target_text": "hello"}])
        assert result["saved"] == 0
        assert result["skipped"] == 1

    def test_deduplication_is_case_insensitive(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "Hello"}])
        result = svc.add_items([{"item_type": "word", "target_text": "hello"}])
        assert result["saved"] == 0

    def test_deduplication_different_type_allowed(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "hello"}])
        result = svc.add_items([{"item_type": "collocation", "target_text": "hello"}])
        assert result["saved"] == 1

    def test_deduplication_different_language_pair_allowed(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "hello", "language_target": "en", "language_native": "ru"}])
        result = svc.add_items([{"item_type": "word", "target_text": "hello", "language_target": "en", "language_native": "fr"}])
        assert result["saved"] == 1

    def test_invalid_item_type_skipped(self, svc):
        result = svc.add_items([{"item_type": "invalid", "target_text": "test"}])
        assert result["saved"] == 0
        assert result["skipped"] == 1

    def test_empty_target_text_skipped(self, svc):
        result = svc.add_items([{"item_type": "word", "target_text": "  "}])
        assert result["saved"] == 0
        assert result["skipped"] == 1

    def test_fields_stored_correctly(self, svc):
        svc.add_items([{
            "item_type": "collocation",
            "target_text": "by the way",
            "native_text": "кстати",
            "context_note": "informal",
            "example_sentence": "By the way, did you eat?",
            "source_kind": "mcp_manual",
        }])
        items = svc.get_items()
        assert len(items) == 1
        item = items[0]
        assert item["native_text"] == "кстати"
        assert item["context_note"] == "informal"
        assert item["source_kind"] == "mcp_manual"

    def test_invalid_source_kind_defaults_to_manual(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "test", "source_kind": "unknown"}])
        items = svc.get_items()
        assert items[0]["source_kind"] == "manual"


class TestGetItems:
    def test_get_items_empty(self, svc):
        assert svc.get_items() == []

    def test_get_items_filter_by_status(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "apple"}])
        new_items = svc.get_items(status="new")
        assert len(new_items) == 1
        review_items = svc.get_items(status="review")
        assert len(review_items) == 0

    def test_get_items_limit(self, svc):
        for i in range(5):
            svc.add_items([{"item_type": "word", "target_text": f"word{i}"}])
        assert len(svc.get_items(limit=3)) == 3

    def test_get_items_offset(self, svc):
        for i in range(4):
            svc.add_items([{"item_type": "word", "target_text": f"word{i}"}])
        all_items = svc.get_items()
        offset_items = svc.get_items(offset=2)
        assert len(offset_items) == 2
        assert offset_items[0]["id"] != all_items[0]["id"]


class TestGetDue:
    def test_new_items_are_due(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "fresh"}])
        due = svc.get_due()
        assert len(due) == 1

    def test_new_items_appear_before_review(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "new_word"}])
        new_id = svc.get_items()[0]["id"]
        # Push it through to 'review' state
        svc.review_item(new_id, "good")
        svc.review_item(new_id, "good")
        svc.review_item(new_id, "good")
        # Add another new item
        svc.add_items([{"item_type": "word", "target_text": "brand_new"}])
        due = svc.get_due()
        # The brand-new item should come first
        new_ones = [d for d in due if d["status"] == "new"]
        assert new_ones[0]["target_text"] == "brand_new"

    def test_suspended_items_not_in_due(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "suspended_word"}])
        item_id = svc.get_items()[0]["id"]
        # Manually update status to suspended by reviewing past due date
        # (We can't easily set next_review_at in the future from the service,
        #  so we test suspended via direct inspection)
        from app.study.db import get_db
        with get_db(svc.db_path) as conn:
            conn.execute("UPDATE study_items SET status = 'suspended' WHERE id = ?", (item_id,))
        due = svc.get_due()
        assert len(due) == 0


class TestReviewItem:
    def test_review_again_resets_progress(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "test"}])
        item_id = svc.get_items()[0]["id"]
        # Advance a couple of times first
        svc.review_item(item_id, "good")
        svc.review_item(item_id, "good")
        # Now fail it
        result = svc.review_item(item_id, "again")
        assert result["repetitions"] == 0
        assert result["interval_days"] == 1.0
        assert result["lapses"] == 1
        assert result["status"] == "learning"

    def test_review_good_advances_status(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "test"}])
        item_id = svc.get_items()[0]["id"]
        for _ in range(3):
            result = svc.review_item(item_id, "good")
        assert result["status"] == "review"

    def test_review_easy_always_review(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "test"}])
        item_id = svc.get_items()[0]["id"]
        result = svc.review_item(item_id, "easy")
        assert result["status"] == "review"

    def test_review_invalid_rating_raises(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "test"}])
        item_id = svc.get_items()[0]["id"]
        with pytest.raises(ValueError, match="Invalid rating"):
            svc.review_item(item_id, "perfect")

    def test_review_unknown_id_raises(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.review_item(9999, "good")

    def test_review_logs_review_event(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "test"}])
        item_id = svc.get_items()[0]["id"]
        svc.review_item(item_id, "good")
        from app.study.db import get_db
        with get_db(svc.db_path) as conn:
            events = conn.execute(
                "SELECT * FROM review_events WHERE item_id = ?", (item_id,)
            ).fetchall()
        assert len(events) == 1
        assert events[0]["rating"] == "good"

    def test_review_updates_last_reviewed_at(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "test"}])
        item_id = svc.get_items()[0]["id"]
        result = svc.review_item(item_id, "good")
        assert result["last_reviewed_at"] is not None


class TestUpdateItem:
    def test_update_native_text(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "test"}])
        item_id = svc.get_items()[0]["id"]
        result = svc.update_item(item_id, {"native_text": "тест"})
        assert result["native_text"] == "тест"

    def test_update_target_text(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "old"}])
        item_id = svc.get_items()[0]["id"]
        result = svc.update_item(item_id, {"target_text": "new"})
        assert result["target_text"] == "new"

    def test_update_status_to_suspended(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "test"}])
        item_id = svc.get_items()[0]["id"]
        result = svc.update_item(item_id, {"status": "suspended"})
        assert result["status"] == "suspended"

    def test_update_multiple_fields(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "test"}])
        item_id = svc.get_items()[0]["id"]
        result = svc.update_item(item_id, {
            "native_text": "перевод",
            "context_note": "формальный",
            "example_sentence": "This is a test.",
        })
        assert result["native_text"] == "перевод"
        assert result["context_note"] == "формальный"
        assert result["example_sentence"] == "This is a test."

    def test_update_unknown_id_raises(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.update_item(9999, {"native_text": "x"})

    def test_update_invalid_status_raises(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "test"}])
        item_id = svc.get_items()[0]["id"]
        with pytest.raises(ValueError, match="Invalid status"):
            svc.update_item(item_id, {"status": "unknown"})

    def test_update_invalid_item_type_raises(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "test"}])
        item_id = svc.get_items()[0]["id"]
        with pytest.raises(ValueError, match="Invalid item_type"):
            svc.update_item(item_id, {"item_type": "paragraph"})

    def test_update_empty_target_text_raises(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "test"}])
        item_id = svc.get_items()[0]["id"]
        with pytest.raises(ValueError, match="empty"):
            svc.update_item(item_id, {"target_text": "  "})

    def test_update_no_editable_fields_raises(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "test"}])
        item_id = svc.get_items()[0]["id"]
        with pytest.raises(ValueError, match="No editable fields"):
            svc.update_item(item_id, {"ease": 1.5})

    def test_update_bumps_updated_at(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "test"}])
        item_id = svc.get_items()[0]["id"]
        before = svc.get_items()[0]["updated_at"]
        import time; time.sleep(0.01)
        result = svc.update_item(item_id, {"native_text": "x"})
        assert result["updated_at"] >= before


class TestDeleteItem:
    def test_delete_removes_item(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "to_delete"}])
        item_id = svc.get_items()[0]["id"]
        svc.delete_item(item_id)
        assert svc.get_items() == []

    def test_delete_removes_review_events(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "test"}])
        item_id = svc.get_items()[0]["id"]
        svc.review_item(item_id, "good")
        svc.delete_item(item_id)
        from app.study.db import get_db
        with get_db(svc.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM review_events WHERE item_id = ?", (item_id,)).fetchone()[0]
        assert count == 0

    def test_delete_unknown_id_raises(self, svc):
        with pytest.raises(ValueError, match="not found"):
            svc.delete_item(9999)

    def test_delete_updates_stats(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "test"}])
        item_id = svc.get_items()[0]["id"]
        svc.delete_item(item_id)
        assert svc.stats()["total_items"] == 0


class TestStats:
    def test_stats_empty_db(self, svc):
        s = svc.stats()
        assert s["new"] == 0
        assert s["learning"] == 0
        assert s["review"] == 0
        assert s["total_items"] == 0
        assert s["total_reviews"] == 0
        assert s["due"] == 0

    def test_stats_counts_items(self, svc):
        svc.add_items([
            {"item_type": "word", "target_text": "one"},
            {"item_type": "word", "target_text": "two"},
        ])
        s = svc.stats()
        assert s["new"] == 2
        assert s["total_items"] == 2

    def test_stats_counts_reviews(self, svc):
        svc.add_items([{"item_type": "word", "target_text": "test"}])
        item_id = svc.get_items()[0]["id"]
        svc.review_item(item_id, "good")
        svc.review_item(item_id, "hard")
        s = svc.stats()
        assert s["total_reviews"] == 2

    def test_stats_due_count(self, svc):
        svc.add_items([
            {"item_type": "word", "target_text": "one"},
            {"item_type": "word", "target_text": "two"},
        ])
        s = svc.stats()
        assert s["due"] == 2

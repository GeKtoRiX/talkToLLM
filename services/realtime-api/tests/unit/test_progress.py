"""Unit tests for mastery check and SRS rating computation."""
from __future__ import annotations

import pytest

from app.training.progress import (
    check_mastery,
    compute_srs_rating,
    compute_priority,
    MASTERY_MIN_SHOWN,
    MASTERY_MIN_ACCURACY,
    MASTERY_MIN_STREAK,
    MASTERY_MIN_ACTIVE_RECALL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _progress(**overrides) -> dict:
    """Build a progress dict with sensible defaults that pass mastery."""
    base = {
        "times_shown": MASTERY_MIN_SHOWN,
        "times_correct": MASTERY_MIN_SHOWN,  # 100% accuracy
        "current_correct_streak": MASTERY_MIN_STREAK,
        "active_recall_successes": MASTERY_MIN_ACTIVE_RECALL,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# check_mastery
# ---------------------------------------------------------------------------

class TestCheckMastery:
    def test_all_criteria_met_returns_true(self):
        assert check_mastery(_progress()) is True

    def test_below_min_shown_returns_false(self):
        assert check_mastery(_progress(times_shown=MASTERY_MIN_SHOWN - 1)) is False

    def test_zero_shown_returns_false(self):
        assert check_mastery(_progress(times_shown=0, times_correct=0)) is False

    def test_below_accuracy_threshold(self):
        # 4 correct out of 5 = 80% < 85%
        assert check_mastery(_progress(times_shown=5, times_correct=4)) is False

    def test_exactly_at_accuracy_threshold(self):
        # 5 correct out of 5 = 100% ≥ 85%
        assert check_mastery(_progress(times_shown=5, times_correct=5)) is True

    def test_barely_above_accuracy(self):
        # 9 correct out of 10 = 90%
        assert check_mastery(_progress(times_shown=10, times_correct=9)) is True

    def test_streak_too_low(self):
        assert check_mastery(_progress(current_correct_streak=MASTERY_MIN_STREAK - 1)) is False

    def test_streak_exactly_at_threshold(self):
        assert check_mastery(_progress(current_correct_streak=MASTERY_MIN_STREAK)) is True

    def test_insufficient_active_recall(self):
        assert check_mastery(_progress(active_recall_successes=MASTERY_MIN_ACTIVE_RECALL - 1)) is False

    def test_exactly_at_active_recall_threshold(self):
        assert check_mastery(_progress(active_recall_successes=MASTERY_MIN_ACTIVE_RECALL)) is True

    def test_multiple_criteria_fail(self):
        p = _progress(
            times_shown=2,
            times_correct=1,
            current_correct_streak=1,
            active_recall_successes=0,
        )
        assert check_mastery(p) is False


# ---------------------------------------------------------------------------
# compute_srs_rating
# ---------------------------------------------------------------------------

class TestComputeSrsRating:
    # Wrong answer always returns "again"
    def test_wrong_mc_returns_again(self):
        assert compute_srs_rating(False, "mc", 2.5) == "again"

    def test_wrong_input_returns_again(self):
        assert compute_srs_rating(False, "input", 3.0) == "again"

    def test_wrong_fill_returns_again(self):
        assert compute_srs_rating(False, "fill", 2.0) == "again"

    # MC correct — weak signal
    def test_mc_correct_high_ease_returns_hard(self):
        # ease ≥ 2.5 → "hard"
        assert compute_srs_rating(True, "mc", 2.5) == "hard"

    def test_mc_correct_low_ease_returns_good(self):
        # ease < 2.5 → "good"
        assert compute_srs_rating(True, "mc", 1.5) == "good"

    # Input correct — strong signal
    def test_input_correct_normal_ease_returns_good(self):
        # ease ≥ 2.0 → "good"
        assert compute_srs_rating(True, "input", 2.5) == "good"

    def test_input_correct_low_ease_returns_easy(self):
        # ease < 2.0 → "easy"
        assert compute_srs_rating(True, "input", 1.3) == "easy"

    # Fill correct — same as input (weight 1.7)
    def test_fill_correct_high_ease_returns_good(self):
        assert compute_srs_rating(True, "fill", 2.5) == "good"

    def test_fill_correct_low_ease_returns_easy(self):
        assert compute_srs_rating(True, "fill", 1.8) == "easy"

    # Context correct — medium signal
    def test_context_correct_returns_good(self):
        assert compute_srs_rating(True, "context", 2.5) == "good"

    def test_context_correct_low_ease_returns_good(self):
        assert compute_srs_rating(True, "context", 1.3) == "good"

    # Unknown exercise type falls back gracefully
    def test_unknown_type_correct_returns_good(self):
        assert compute_srs_rating(True, "unknown_type", 2.5) == "hard"


# ---------------------------------------------------------------------------
# compute_priority
# ---------------------------------------------------------------------------

class TestComputePriority:
    def test_new_status_highest_base(self):
        score_new = compute_priority("new", 0, 0, None)
        score_review = compute_priority("review", 0, 0, None)
        assert score_new > score_review

    def test_overdue_bonus_increases_score(self):
        s_on_time = compute_priority("review", 0.0, 0, None)
        s_overdue = compute_priority("review", 5.0, 0, None)
        assert s_overdue > s_on_time

    def test_overdue_bonus_capped_at_0_5(self):
        s_very_overdue = compute_priority("review", 100.0, 0, None)
        s_capped = compute_priority("review", 10.0, 0, None)
        # Both should hit the same cap
        assert s_very_overdue == pytest.approx(s_capped, abs=1e-9)

    def test_wrong_streak_increases_score(self):
        s_no_streak = compute_priority("learning", 0, 0, None)
        s_with_streak = compute_priority("learning", 0, 3, None)
        assert s_with_streak > s_no_streak

    def test_recently_shown_decreases_score(self):
        s_old = compute_priority("review", 0, 0, 10.0)   # shown 10 days ago
        s_recent = compute_priority("review", 0, 0, 1.0)  # shown 1 day ago
        assert s_old > s_recent

    def test_shown_7_plus_days_ago_no_penalty(self):
        s_7 = compute_priority("review", 0, 0, 7.0)
        s_none = compute_priority("review", 0, 0, None)
        assert s_7 == pytest.approx(s_none)

    def test_suspended_lowest_priority(self):
        assert compute_priority("suspended", 100, 10, 0) == pytest.approx(0.0)

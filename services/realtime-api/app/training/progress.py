"""Pure functions for answer checking, mastery detection, and SRS rating.

No database access here — every function is deterministic and testable in isolation.
"""
from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------------------
# Exercise weights
# ---------------------------------------------------------------------------

EXERCISE_WEIGHTS: dict[str, float] = {
    "mc": 1.0,
    "input": 1.5,
    "context": 1.3,
    "fill": 1.7,
}

# ---------------------------------------------------------------------------
# Mastery thresholds — centralised so they are easy to adjust
# ---------------------------------------------------------------------------

MASTERY_MIN_SHOWN = 5
MASTERY_MIN_ACCURACY = 0.85
MASTERY_MIN_STREAK = 3
MASTERY_MIN_ACTIVE_RECALL = 2  # successful input / fill / context answers

# Active-recall exercise types (higher value evidence of actual recall)
ACTIVE_RECALL_TYPES = frozenset({"input", "fill", "context"})


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Normalise a user answer for comparison.

    Steps:
      1. NFKC Unicode normalisation (handles composed/decomposed forms, full-width chars, …)
      2. Strip leading/trailing whitespace.
      3. Case-fold (locale-agnostic lowercase).
      4. Remove all punctuation except the apostrophe (preserves contractions).
      5. Collapse consecutive whitespace to a single space.
    """
    text = unicodedata.normalize("NFKC", text.strip()).casefold()
    text = re.sub(r"[^\w\s']", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Levenshtein distance (pure Python, O(m × n))
# ---------------------------------------------------------------------------

def levenshtein(a: str, b: str) -> int:
    """Return the edit distance between two strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    # Use a single row DP approach to keep memory O(min(m, n)).
    if len(a) < len(b):
        a, b = b, a  # a is always the longer string

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            insert = prev[j] + 1
            delete = curr[j - 1] + 1
            replace = prev[j - 1] + (0 if ca == cb else 1)
            curr.append(min(insert, delete, replace))
        prev = curr
    return prev[-1]


# ---------------------------------------------------------------------------
# Answer checking
# ---------------------------------------------------------------------------

def check_answer(
    given: str,
    correct: str,
    alternatives: list[str] | None = None,
) -> tuple[bool, str | None]:
    """Check a user answer against the correct answer and optional alternatives.

    Returns:
        (is_correct, error_type)

        is_correct  — True if the answer is acceptable.
        error_type  — None (correct), "spelling" (close but not exact),
                      "partial" (all key words present), or "full_miss".

    Matching is performed in three tiers:
      1. Exact match (after normalisation) against correct + alternatives.
      2. Soft match via Levenshtein distance ≤ 2 for strings longer than 5 chars.
      3. Partial phrase match: all words of the correct answer appear in the given answer.
    """
    norm_given = normalize(given)

    if not norm_given:
        return False, "full_miss"

    all_correct = {normalize(correct)}
    if alternatives:
        for alt in alternatives:
            if alt:
                all_correct.add(normalize(alt))

    # Tier 1: exact match
    if norm_given in all_correct:
        return True, None

    # Tier 2: fuzzy match (Levenshtein ≤ 2 for strings > 5 chars)
    for candidate in all_correct:
        if len(candidate) > 5 and levenshtein(norm_given, candidate) <= 2:
            return True, "spelling"

    # Tier 3: partial phrase match (all key words present, order-independent)
    for candidate in all_correct:
        candidate_words = candidate.split()
        if len(candidate_words) > 1 and all(w in norm_given for w in candidate_words):
            return True, "partial"

    return False, "full_miss"


# ---------------------------------------------------------------------------
# SRS rating mapping
# ---------------------------------------------------------------------------

def compute_srs_rating(
    is_correct: bool,
    exercise_type: str,
    current_ease: float,
) -> str:
    """Map exercise outcome to an SRS rating (again / hard / good / easy).

    Key principle: Multiple-choice correct is a weaker signal than typed input.
    MC correct answers do not deserve a "good" rating unless the ease is low —
    otherwise we would inflate intervals for items that were merely recognised.
    """
    if not is_correct:
        return "again"

    weight = EXERCISE_WEIGHTS.get(exercise_type, 1.0)

    if weight < 1.2:
        # mc — weakest signal; use "hard" if the item is already well-known,
        # "good" only if the item still has a low ease factor.
        return "hard" if current_ease >= 2.5 else "good"
    elif weight >= 1.5:
        # input / fill — strongest signal; can earn "easy" for struggling items.
        return "good" if current_ease >= 2.0 else "easy"
    else:
        # context — medium signal
        return "good"


# ---------------------------------------------------------------------------
# Mastery check
# ---------------------------------------------------------------------------

def check_mastery(progress: dict) -> bool:
    """Return True when all mastery criteria are met.

    Criteria (all must hold):
      1. At least MASTERY_MIN_SHOWN total exposures.
      2. Accuracy ≥ MASTERY_MIN_ACCURACY.
      3. Current correct streak ≥ MASTERY_MIN_STREAK.
      4. At least MASTERY_MIN_ACTIVE_RECALL successes in active-recall exercises
         (input / fill / context).

    Note: criterion 5 from the spec ("no wrong answers in last 2 sessions") is
    evaluated by the caller (TrainingService), which has session history access.
    """
    times_shown: int = progress.get("times_shown", 0)
    times_correct: int = progress.get("times_correct", 0)
    streak: int = progress.get("current_correct_streak", 0)
    active_recall: int = progress.get("active_recall_successes", 0)

    if times_shown < MASTERY_MIN_SHOWN:
        return False
    accuracy = times_correct / times_shown
    if accuracy < MASTERY_MIN_ACCURACY:
        return False
    if streak < MASTERY_MIN_STREAK:
        return False
    if active_recall < MASTERY_MIN_ACTIVE_RECALL:
        return False
    return True


# ---------------------------------------------------------------------------
# Priority scoring (for auto-mode session item selection)
# ---------------------------------------------------------------------------

_STATUS_BASE: dict[str, float] = {
    "new": 1.0,
    "learning": 0.8,
    "difficult": 0.9,
    "review": 0.6,
    "mastered": 0.1,
    "suspended": 0.0,
}


def compute_priority(
    status: str,
    overdue_days: float,
    wrong_streak: int,
    days_since_shown: float | None,
) -> float:
    """Compute a scheduling priority score for an item.

    Higher score → shown sooner in an automatic session.
    Suspended items always return 0.0 (they are excluded from sessions anyway,
    but we guarantee the score so callers can safely rely on it).
    """
    base = _STATUS_BASE.get(status, 0.5)
    if base == 0.0:
        return 0.0
    score = base
    score += min(0.5, overdue_days * 0.1)
    score += wrong_streak * 0.15
    if days_since_shown is not None and days_since_shown < 7:
        score -= days_since_shown * 0.05
    return score

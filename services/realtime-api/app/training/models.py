"""Pydantic request/response models for the training module.

No business logic lives here — pure data contracts only.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums (as Literal-style type aliases used in Field validators)
# ---------------------------------------------------------------------------

VALID_MODES = frozenset({
    "auto", "new_only", "difficult", "overdue", "errors", "by_type", "manual",
})

VALID_EXERCISE_TYPES = frozenset({"mc", "input", "context", "fill"})

VALID_ITEM_TYPES = frozenset({
    "word", "phrasal_verb", "idiom", "collocation",
})

VALID_LEXICAL_TYPES = frozenset({"noun", "verb", "adjective", "adverb"})

VALID_STATUSES = frozenset({
    "new", "learning", "review", "mastered", "difficult", "suspended",
})

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class SessionFilters(BaseModel):
    """Filters applied when selecting vocabulary for a training session."""

    lexical_type: Optional[str] = None
    item_type: Optional[str] = None
    topic: Optional[str] = None
    difficulty_min: Optional[int] = Field(default=None, ge=1, le=5)
    difficulty_max: Optional[int] = Field(default=None, ge=1, le=5)
    # If provided, only items whose status is in this list are selected.
    status: Optional[list[str]] = None
    language_target: Optional[str] = None


class CreateSessionRequest(BaseModel):
    mode: str = "auto"
    filters: SessionFilters = Field(default_factory=SessionFilters)
    target_count: int = Field(default=20, ge=1, le=200)


class AnswerRequest(BaseModel):
    question_id: int
    answer_given: str = ""


class CompleteSessionRequest(BaseModel):
    note: str = ""


# ---------------------------------------------------------------------------
# Response models (mirror DB row structure)
# ---------------------------------------------------------------------------


class TrainingSessionSchema(BaseModel):
    id: int
    mode: str
    filters_json: str
    target_count: int
    item_ids_json: str
    status: str
    correct_count: int
    wrong_count: int
    total_questions: int
    newly_mastered_ids: str
    newly_difficult_ids: str
    error_item_ids: str
    started_at: str
    ended_at: Optional[str]


class SessionQuestionSchema(BaseModel):
    id: int
    session_id: int
    item_id: int
    exercise_type: str
    direction: str
    correct_answer: str
    distractors_json: str
    prompt_text: str
    answer_given: Optional[str]
    is_correct: Optional[int]
    error_type: Optional[str]
    answered_at: Optional[str]
    retry_scheduled: int
    position: int


class ItemProgressSchema(BaseModel):
    id: int
    item_id: int
    times_shown: int
    times_correct: int
    times_wrong: int
    current_correct_streak: int
    current_wrong_streak: int
    exercise_type_stats: str  # JSON
    active_recall_successes: int
    weighted_score: float
    is_mastered: int
    mastered_at: Optional[str]
    is_difficult: int
    last_shown_at: Optional[str]
    last_correct_at: Optional[str]
    last_wrong_at: Optional[str]
    created_at: str
    updated_at: str


class ItemSummary(BaseModel):
    """Compact item representation used in session results."""
    id: int
    target_text: str
    native_text: str
    item_type: str
    error_type: Optional[str] = None


class ExerciseTypeStats(BaseModel):
    shown: int = 0
    correct: int = 0


class AnswerResultResponse(BaseModel):
    is_correct: bool
    error_type: Optional[str]
    correct_answer: str
    explanation: Optional[str]
    next_question: Optional[dict[str, Any]]
    session_complete: bool
    newly_mastered: bool
    newly_difficult: bool


class SessionResultsResponse(BaseModel):
    session_id: int
    mode: str
    total_questions: int
    correct_count: int
    wrong_count: int
    accuracy_pct: float
    duration_seconds: Optional[float]
    newly_mastered: list[ItemSummary]
    newly_difficult: list[ItemSummary]
    error_items: list[ItemSummary]
    by_exercise_type: dict[str, ExerciseTypeStats]


class UserStatsResponse(BaseModel):
    total_items: int
    mastered: int
    learning: int
    difficult: int
    new: int
    suspended: int
    review: int
    by_lexical_type: dict[str, int]
    by_item_type: dict[str, int]
    total_training_sessions: int
    total_questions_answered: int
    overall_accuracy_pct: float

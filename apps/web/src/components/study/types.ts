/**
 * TypeScript types for the Training (Заучивание) module.
 * These mirror the backend Pydantic models in app/training/models.py.
 */

// ---------------------------------------------------------------------------
// Enumerations
// ---------------------------------------------------------------------------

export type LexicalType = "noun" | "verb" | "adjective" | "adverb";

export type ExtendedItemType =
  | "word" | "phrasal_verb" | "idiom" | "collocation";

export type ExtendedStatus =
  | "new" | "learning" | "review" | "mastered" | "difficult" | "suspended";

export type ExerciseType = "mc" | "input" | "context" | "fill";

export type SessionMode =
  | "auto" | "new_only" | "difficult" | "overdue"
  | "errors" | "by_type" | "manual";

export type Direction = "en_to_ru" | "ru_to_en";

// ---------------------------------------------------------------------------
// Session configuration
// ---------------------------------------------------------------------------

export type SessionFilters = {
  lexical_type?: LexicalType | null;
  item_type?: ExtendedItemType | null;
  topic?: string;
  difficulty_min?: number | null;
  difficulty_max?: number | null;
  status?: ExtendedStatus[];
  language_target?: string;
};

export type CreateSessionRequest = {
  mode: SessionMode;
  filters?: SessionFilters;
  target_count?: number;
};

// ---------------------------------------------------------------------------
// Session data
// ---------------------------------------------------------------------------

export type TrainingSession = {
  id: number;
  mode: SessionMode;
  filters_json: string;
  target_count: number;
  item_ids_json: string;
  status: "active" | "completed" | "abandoned";
  correct_count: number;
  wrong_count: number;
  total_questions: number;
  newly_mastered_ids: string;
  newly_difficult_ids: string;
  error_item_ids: string;
  started_at: string;
  ended_at: string | null;
};

export type SessionQuestion = {
  id: number;
  session_id: number;
  item_id: number;
  exercise_type: ExerciseType;
  direction: Direction;
  correct_answer: string;
  distractors_json: string;
  prompt_text: string;
  answer_given: string | null;
  is_correct: number | null; // null = unanswered, 0 = wrong, 1 = correct
  error_type: string | null;
  answered_at: string | null;
  retry_scheduled: number;
  position: number;
};

// ---------------------------------------------------------------------------
// Answer result
// ---------------------------------------------------------------------------

export type AnswerResult = {
  is_correct: boolean;
  error_type: string | null;
  correct_answer: string;
  explanation: string | null;
  next_question: SessionQuestion | null;
  session_complete: boolean;
  newly_mastered: boolean;
  newly_difficult: boolean;
};

// ---------------------------------------------------------------------------
// Progress and statistics
// ---------------------------------------------------------------------------

export type ExerciseTypeStats = {
  shown: number;
  correct: number;
};

export type ItemProgress = {
  id: number;
  item_id: number;
  times_shown: number;
  times_correct: number;
  times_wrong: number;
  current_correct_streak: number;
  current_wrong_streak: number;
  exercise_type_stats: Record<ExerciseType, ExerciseTypeStats>;
  active_recall_successes: number;
  weighted_score: number;
  is_mastered: number;
  mastered_at: string | null;
  is_difficult: number;
  last_shown_at: string | null;
  last_correct_at: string | null;
  last_wrong_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ItemSummary = {
  id: number;
  target_text: string;
  native_text: string;
  item_type: ExtendedItemType;
  error_type?: string | null;
};

export type SessionResults = {
  session_id: number;
  mode: SessionMode;
  total_questions: number;
  correct_count: number;
  wrong_count: number;
  accuracy_pct: number;
  duration_seconds: number | null;
  newly_mastered: ItemSummary[];
  newly_difficult: ItemSummary[];
  error_items: ItemSummary[];
  by_exercise_type: Record<string, ExerciseTypeStats>;
};

export type UserStats = {
  total_items: number;
  mastered: number;
  learning: number;
  difficult: number;
  new: number;
  suspended: number;
  review: number;
  by_lexical_type: Record<string, number>;
  by_item_type: Record<string, number>;
  total_training_sessions: number;
  total_questions_answered: number;
  overall_accuracy_pct: number;
};

// ---------------------------------------------------------------------------
// Extended StudyItem (with new fields from migration)
// ---------------------------------------------------------------------------

export type ExtendedStudyItem = {
  id: number;
  item_type: ExtendedItemType;
  target_text: string;
  native_text: string;
  context_note: string;
  example_sentence: string;
  example_sentence_native: string;
  status: ExtendedStatus;
  ease: number;
  interval_days: number;
  repetitions: number;
  lapses: number;
  next_review_at: string;
  lexical_type: LexicalType | null;
  alternative_translations: string; // JSON
  topic: string;
  difficulty_level: number | null;
  tags: string; // JSON
};

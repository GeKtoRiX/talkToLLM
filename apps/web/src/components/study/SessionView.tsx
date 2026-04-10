import { useState } from "react";
import type { AnswerResult, SessionQuestion, TrainingSession } from "./types";
import { ExerciseContext } from "./ExerciseContext";
import { ExerciseFillBlank } from "./ExerciseFillBlank";
import { ExerciseInput } from "./ExerciseInput";
import { ExerciseMultipleChoice } from "./ExerciseMultipleChoice";

type Props = {
  session: TrainingSession;
  question: SessionQuestion;
  questionsAnswered: number;
  onAnswer: (questionId: number, answer: string) => Promise<AnswerResult>;
  onComplete: () => void;
};

type AnswerState =
  | { phase: "idle" }
  | { phase: "submitting" }
  | { phase: "result"; result: AnswerResult };

const MODE_LABEL: Record<string, string> = {
  auto: "Auto",
  new_only: "New only",
  difficult: "Difficult",
  overdue: "Overdue",
  errors: "Errors",
  by_type: "By type",
  manual: "Manual",
};

export function SessionView({ session, question, questionsAnswered, onAnswer, onComplete }: Props) {
  const [answerState, setAnswerState] = useState<AnswerState>({ phase: "idle" });

  const total = session.total_questions;
  const currentQuestionNum = questionsAnswered + 1;
  const progress = total > 0 ? Math.min(1, questionsAnswered / total) : 0;

  async function handleSubmit(answer: string) {
    setAnswerState({ phase: "submitting" });
    try {
      const result = await onAnswer(question.id, answer);
      setAnswerState({ phase: "result", result });
      // Auto-advance after 1.4s
      setTimeout(() => {
        setAnswerState({ phase: "idle" });
        if (result.session_complete) {
          onComplete();
        }
      }, 1400);
    } catch {
      setAnswerState({ phase: "idle" });
    }
  }

  const isDisabled = answerState.phase !== "idle";

  return (
    <div className="session-view">
      {/* Header bar */}
      <div className="session-header">
        <span className="session-header__mode">
          {MODE_LABEL[session.mode] ?? session.mode}
        </span>
        <span className="session-header__counter">
          {currentQuestionNum} / {total}
        </span>
        <span className="session-header__score">
          {session.correct_count} ✓
        </span>
      </div>

      {/* Progress bar */}
      <div className="session-progress">
        <div
          className="session-progress__bar"
          style={{ width: `${Math.round(progress * 100)}%` }}
        />
      </div>

      {/* Exercise */}
      <div className="session-exercise">
        {question.exercise_type === "mc" && (
          <ExerciseMultipleChoice
            question={question}
            onSubmit={handleSubmit}
            disabled={isDisabled}
          />
        )}
        {question.exercise_type === "input" && (
          <ExerciseInput
            question={question}
            onSubmit={handleSubmit}
            disabled={isDisabled}
          />
        )}
        {question.exercise_type === "context" && (
          <ExerciseContext
            question={question}
            onSubmit={handleSubmit}
            disabled={isDisabled}
          />
        )}
        {question.exercise_type === "fill" && (
          <ExerciseFillBlank
            question={question}
            onSubmit={handleSubmit}
            disabled={isDisabled}
          />
        )}
      </div>

      {/* Result overlay */}
      {answerState.phase === "result" && (
        <div
          className={`session-feedback${answerState.result.is_correct ? " session-feedback--correct" : " session-feedback--wrong"}`}
        >
          <span className="session-feedback__icon">
            {answerState.result.is_correct ? "✓" : "✗"}
          </span>
          {!answerState.result.is_correct && (
            <span className="session-feedback__answer">
              {answerState.result.correct_answer}
            </span>
          )}
          {answerState.result.explanation && (
            <span className="session-feedback__hint">
              {answerState.result.explanation}
            </span>
          )}
          {answerState.result.newly_mastered && (
            <span className="session-feedback__mastered">Mastered!</span>
          )}
        </div>
      )}
    </div>
  );
}

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
  onAdvance: (result: AnswerResult) => void;
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

export function SessionView({ session, question, questionsAnswered, onAnswer, onAdvance }: Props) {
  const [answerState, setAnswerState] = useState<AnswerState>({ phase: "idle" });

  const total = session.total_questions;
  const currentQuestionNum = questionsAnswered + 1;
  const progress = total > 0 ? Math.min(1, questionsAnswered / total) : 0;

  async function handleSubmit(answer: string) {
    setAnswerState({ phase: "submitting" });
    try {
      const result = await onAnswer(question.id, answer);
      setAnswerState({ phase: "result", result });
      // After showing feedback, reset and advance
      setTimeout(() => {
        setAnswerState({ phase: "idle" });
        onAdvance(result);
      }, 1400);
    } catch {
      setAnswerState({ phase: "idle" });
    }
  }

  const isDisabled = answerState.phase !== "idle";
  const result = answerState.phase === "result" ? answerState.result : undefined;
  // Choice exercises (MC, context) show feedback inline on buttons — no overlay needed
  const isChoiceExercise = question.exercise_type === "mc" || question.exercise_type === "context";

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

      {/* Exercise — key={question.id} remounts on each new question, resetting internal state */}
      <div className="session-exercise">
        {question.exercise_type === "mc" && (
          <ExerciseMultipleChoice
            key={question.id}
            question={question}
            onSubmit={handleSubmit}
            disabled={isDisabled}
            result={result}
          />
        )}
        {question.exercise_type === "input" && (
          <ExerciseInput
            key={question.id}
            question={question}
            onSubmit={handleSubmit}
            disabled={isDisabled}
          />
        )}
        {question.exercise_type === "context" && (
          <ExerciseContext
            key={question.id}
            question={question}
            onSubmit={handleSubmit}
            disabled={isDisabled}
            result={result}
          />
        )}
        {question.exercise_type === "fill" && (
          <ExerciseFillBlank
            key={question.id}
            question={question}
            onSubmit={handleSubmit}
            disabled={isDisabled}
          />
        )}
      </div>

      {/* Result slot — always occupies space to prevent layout shift */}
      {!isChoiceExercise && (
        <div className="session-feedback-slot">
          {answerState.phase === "result" && (
            <div
              className={`session-feedback${answerState.result.is_correct ? " session-feedback--correct" : " session-feedback--wrong"}`}
            >
              <span className="session-feedback__circle">
                <span className="session-feedback__symbol">
                  {answerState.result.is_correct ? "✓" : "✕"}
                </span>
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

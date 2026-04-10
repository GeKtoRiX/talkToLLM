import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SessionView } from "./SessionView";
import type { AnswerResult, SessionQuestion, TrainingSession } from "./types";

const SESSION: TrainingSession = {
  id: 1,
  mode: "auto",
  filters_json: "{}",
  target_count: 10,
  item_ids_json: "[]",
  status: "active",
  correct_count: 3,
  wrong_count: 1,
  total_questions: 10,
  newly_mastered_ids: "[]",
  newly_difficult_ids: "[]",
  error_item_ids: "[]",
  started_at: "2026-01-01T00:00:00",
  ended_at: null,
};

function makeQuestion(overrides: Partial<SessionQuestion> = {}): SessionQuestion {
  return {
    id: 1,
    session_id: 1,
    item_id: 10,
    exercise_type: "mc",
    direction: "en_to_ru",
    correct_answer: "мимолётный",
    distractors_json: JSON.stringify(["повсеместный", "загадочный", "немедленный"]),
    prompt_text: "ephemeral",
    answer_given: null,
    is_correct: null,
    error_type: null,
    answered_at: null,
    retry_scheduled: 0,
    position: 0,
    ...overrides,
  };
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("SessionView", () => {
  it("renders progress bar at the correct width", () => {
    render(
      <SessionView
        session={SESSION}
        question={makeQuestion()}
        questionsAnswered={4}
        onAnswer={vi.fn()}
        onComplete={vi.fn()}
      />
    );
    const bar = document.querySelector(".session-progress__bar") as HTMLElement;
    expect(bar.style.width).toBe("40%"); // 4/10
  });

  it("shows question counter in header", () => {
    render(
      <SessionView
        session={SESSION}
        question={makeQuestion()}
        questionsAnswered={4}
        onAnswer={vi.fn()}
        onComplete={vi.fn()}
      />
    );
    // questionsAnswered=4 → currentQuestionNum=5, total=10 → "5 / 10"
    expect(screen.getByText("5 / 10")).toBeInTheDocument();
    // correct count shown with checkmark
    expect(screen.getByText("3 ✓")).toBeInTheDocument();
  });

  it("renders MultipleChoice for exercise_type=mc", () => {
    render(
      <SessionView
        session={SESSION}
        question={makeQuestion({ exercise_type: "mc" })}
        questionsAnswered={0}
        onAnswer={vi.fn()}
        onComplete={vi.fn()}
      />
    );
    // MC renders option buttons
    expect(screen.getAllByRole("button").length).toBeGreaterThanOrEqual(1);
    // prompt text visible
    expect(screen.getByText("ephemeral")).toBeInTheDocument();
  });

  it("renders ExerciseInput for exercise_type=input", () => {
    render(
      <SessionView
        session={SESSION}
        question={makeQuestion({ exercise_type: "input" })}
        questionsAnswered={0}
        onAnswer={vi.fn()}
        onComplete={vi.fn()}
      />
    );
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /submit/i })).toBeInTheDocument();
  });

  it("shows correct feedback overlay after correct answer", async () => {
    const result: AnswerResult = {
      is_correct: true,
      error_type: null,
      correct_answer: "мимолётный",
      explanation: null,
      next_question: null,
      session_complete: false,
      newly_mastered: false,
      newly_difficult: false,
    };
    const onAnswer = vi.fn().mockResolvedValue(result);

    render(
      <SessionView
        session={SESSION}
        question={makeQuestion({ exercise_type: "mc" })}
        questionsAnswered={0}
        onAnswer={onAnswer}
        onComplete={vi.fn()}
      />
    );

    const btns = screen.getAllByRole("button");
    fireEvent.click(btns[0]);

    await waitFor(() => {
      const feedback = document.querySelector(".session-feedback--correct");
      expect(feedback).toBeInTheDocument();
    });
  });

  it("shows wrong feedback overlay with correct answer", async () => {
    const result: AnswerResult = {
      is_correct: false,
      error_type: "full_miss",
      correct_answer: "мимолётный",
      explanation: null,
      next_question: null,
      session_complete: false,
      newly_mastered: false,
      newly_difficult: false,
    };
    const onAnswer = vi.fn().mockResolvedValue(result);

    render(
      <SessionView
        session={SESSION}
        question={makeQuestion({ exercise_type: "mc" })}
        questionsAnswered={0}
        onAnswer={onAnswer}
        onComplete={vi.fn()}
      />
    );

    const btns = screen.getAllByRole("button");
    fireEvent.click(btns[0]);

    await waitFor(() => {
      expect(document.querySelector(".session-feedback--wrong")).toBeInTheDocument();
      expect(document.querySelector(".session-feedback__answer")).toBeInTheDocument();
    });
  });
});

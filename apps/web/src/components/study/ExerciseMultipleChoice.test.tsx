import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExerciseMultipleChoice } from "./ExerciseMultipleChoice";
import type { SessionQuestion } from "./types";

const BASE_QUESTION: SessionQuestion = {
  id: 42,
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
};

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("ExerciseMultipleChoice", () => {
  it("renders the prompt text", () => {
    render(<ExerciseMultipleChoice question={BASE_QUESTION} onSubmit={vi.fn()} />);
    expect(screen.getByText("ephemeral")).toBeInTheDocument();
  });

  it("renders 4 option buttons (correct + 3 distractors)", () => {
    render(<ExerciseMultipleChoice question={BASE_QUESTION} onSubmit={vi.fn()} />);
    const btns = screen.getAllByRole("button");
    expect(btns).toHaveLength(4);
    const texts = btns.map((b) => b.textContent);
    expect(texts).toContain("мимолётный");
    expect(texts).toContain("повсеместный");
  });

  it("calls onSubmit with chosen option on click", () => {
    const onSubmit = vi.fn();
    render(<ExerciseMultipleChoice question={BASE_QUESTION} onSubmit={onSubmit} />);
    const btns = screen.getAllByRole("button");
    fireEvent.click(btns[0]);
    expect(onSubmit).toHaveBeenCalledOnce();
    expect(onSubmit).toHaveBeenCalledWith(btns[0].textContent);
  });

  it("disables all buttons after selection", () => {
    render(<ExerciseMultipleChoice question={BASE_QUESTION} onSubmit={vi.fn()} />);
    const btns = screen.getAllByRole("button");
    fireEvent.click(btns[1]);
    btns.forEach((b) => expect(b).toBeDisabled());
  });

  it("ignores click when disabled prop is true", () => {
    const onSubmit = vi.fn();
    render(<ExerciseMultipleChoice question={BASE_QUESTION} onSubmit={onSubmit} disabled />);
    const btns = screen.getAllByRole("button");
    btns.forEach((b) => fireEvent.click(b));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("still renders with empty distractors_json (falls back to correct_answer only)", () => {
    const q = { ...BASE_QUESTION, distractors_json: "[]" };
    render(<ExerciseMultipleChoice question={q} onSubmit={vi.fn()} />);
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("falls back gracefully on invalid distractors_json", () => {
    const q = { ...BASE_QUESTION, distractors_json: "not json" };
    render(<ExerciseMultipleChoice question={q} onSubmit={vi.fn()} />);
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });
});

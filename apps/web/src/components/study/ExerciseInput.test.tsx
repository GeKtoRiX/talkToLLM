import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExerciseInput } from "./ExerciseInput";
import type { SessionQuestion } from "./types";

const BASE_QUESTION: SessionQuestion = {
  id: 7,
  session_id: 1,
  item_id: 3,
  exercise_type: "input",
  direction: "ru_to_en",
  correct_answer: "ephemeral",
  distractors_json: "[]",
  prompt_text: "мимолётный",
  answer_given: null,
  is_correct: null,
  error_type: null,
  answered_at: null,
  retry_scheduled: 0,
  position: 0,
};

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("ExerciseInput", () => {
  it("renders prompt text", () => {
    render(<ExerciseInput question={BASE_QUESTION} onSubmit={vi.fn()} />);
    expect(screen.getByText("мимолётный")).toBeInTheDocument();
  });

  it("submit button is disabled when input is empty", () => {
    render(<ExerciseInput question={BASE_QUESTION} onSubmit={vi.fn()} />);
    expect(screen.getByRole("button", { name: /submit/i })).toBeDisabled();
  });

  it("submit button enables after typing", () => {
    render(<ExerciseInput question={BASE_QUESTION} onSubmit={vi.fn()} />);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "ephemeral" } });
    expect(screen.getByRole("button", { name: /submit/i })).not.toBeDisabled();
  });

  it("calls onSubmit with trimmed value on button click", () => {
    const onSubmit = vi.fn();
    render(<ExerciseInput question={BASE_QUESTION} onSubmit={onSubmit} />);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "  ephemeral  " } });
    fireEvent.click(screen.getByRole("button", { name: /submit/i }));
    expect(onSubmit).toHaveBeenCalledWith("ephemeral");
  });

  it("calls onSubmit on Enter key press", () => {
    const onSubmit = vi.fn();
    render(<ExerciseInput question={BASE_QUESTION} onSubmit={onSubmit} />);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "ephemeral" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledWith("ephemeral");
  });

  it("does not submit whitespace-only input on Enter", () => {
    const onSubmit = vi.fn();
    render(<ExerciseInput question={BASE_QUESTION} onSubmit={onSubmit} />);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("ignores submit when disabled prop is true", () => {
    const onSubmit = vi.fn();
    render(<ExerciseInput question={BASE_QUESTION} onSubmit={onSubmit} disabled />);
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "ephemeral" } });
    fireEvent.click(screen.getByRole("button", { name: /submit/i }));
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

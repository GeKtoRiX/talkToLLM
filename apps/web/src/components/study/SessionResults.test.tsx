import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SessionResultsView } from "./SessionResults";
import type { SessionResults } from "./types";

const BASE_RESULTS: SessionResults = {
  session_id: 1,
  mode: "auto",
  total_questions: 10,
  correct_count: 8,
  wrong_count: 2,
  accuracy_pct: 80,
  duration_seconds: 95,
  newly_mastered: [],
  newly_difficult: [],
  error_items: [],
  by_exercise_type: {},
};

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("SessionResultsView", () => {
  it("shows accuracy percentage", () => {
    render(<SessionResultsView results={BASE_RESULTS} onStartNew={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByText("80%")).toBeInTheDocument();
  });

  it("shows correct, wrong and total counts", () => {
    render(<SessionResultsView results={BASE_RESULTS} onStartNew={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByText("8")).toBeInTheDocument();  // correct_count
    expect(screen.getByText("2")).toBeInTheDocument();  // wrong_count
    expect(screen.getByText("10")).toBeInTheDocument(); // total_questions
  });

  it("shows duration when present", () => {
    render(<SessionResultsView results={BASE_RESULTS} onStartNew={vi.fn()} onClose={vi.fn()} />);
    // 95 seconds = 1m 35s
    expect(screen.getByText("1m 35s")).toBeInTheDocument();
  });

  it("does not show duration when null", () => {
    const r = { ...BASE_RESULTS, duration_seconds: null };
    render(<SessionResultsView results={r} onStartNew={vi.fn()} onClose={vi.fn()} />);
    expect(screen.queryByText(/\dm \d+s/)).toBeNull();
  });

  it("renders mastered items section when non-empty", () => {
    const r = {
      ...BASE_RESULTS,
      newly_mastered: [{ id: 1, target_text: "ephemeral", native_text: "мимолётный", item_type: "word" as const }],
    };
    render(<SessionResultsView results={r} onStartNew={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByText(/newly mastered/i)).toBeInTheDocument();
    expect(screen.getByText("ephemeral")).toBeInTheDocument();
  });

  it("hides mastered section when empty", () => {
    render(<SessionResultsView results={BASE_RESULTS} onStartNew={vi.fn()} onClose={vi.fn()} />);
    expect(screen.queryByText(/newly mastered/i)).toBeNull();
  });

  it("renders error items section when non-empty", () => {
    const r = {
      ...BASE_RESULTS,
      error_items: [{ id: 2, target_text: "ubiquitous", native_text: "повсеместный", item_type: "word" as const }],
    };
    render(<SessionResultsView results={r} onStartNew={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByText(/needs work/i)).toBeInTheDocument();
    expect(screen.getByText("ubiquitous")).toBeInTheDocument();
  });

  it("calls onStartNew when New Session button is clicked", () => {
    const onStartNew = vi.fn();
    render(<SessionResultsView results={BASE_RESULTS} onStartNew={onStartNew} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /new session/i }));
    expect(onStartNew).toHaveBeenCalledOnce();
  });

  it("calls onClose when Close button is clicked", () => {
    const onClose = vi.fn();
    render(<SessionResultsView results={BASE_RESULTS} onStartNew={vi.fn()} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("shows by_exercise_type breakdown when non-empty", () => {
    const r = {
      ...BASE_RESULTS,
      by_exercise_type: { mc: { shown: 5, correct: 4 }, input: { shown: 5, correct: 4 } },
    };
    render(<SessionResultsView results={r} onStartNew={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByText(/by exercise type/i)).toBeInTheDocument();
    expect(screen.getByText("mc")).toBeInTheDocument();
  });
});

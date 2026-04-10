import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TrainingTab } from "./TrainingTab";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------
const MOCK_SESSION = {
  id: 1,
  mode: "auto",
  filters_json: "{}",
  target_count: 10,
  item_ids_json: "[1]",
  status: "active",
  correct_count: 0,
  wrong_count: 0,
  total_questions: 10,
  newly_mastered_ids: "[]",
  newly_difficult_ids: "[]",
  error_item_ids: "[]",
  started_at: "2026-01-01T00:00:00",
  ended_at: null,
};

const MOCK_QUESTION = {
  id: 1,
  session_id: 1,
  item_id: 1,
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

const MOCK_STATS = {
  total_items: 5,
  mastered: 1,
  learning: 2,
  difficult: 0,
  new: 2,
  suspended: 0,
  review: 0,
  by_lexical_type: {},
  by_item_type: {},
  total_training_sessions: 3,
  total_questions_answered: 30,
  overall_accuracy_pct: 80,
};

const MOCK_RESULTS = {
  session_id: 1,
  mode: "auto",
  total_questions: 10,
  correct_count: 8,
  wrong_count: 2,
  accuracy_pct: 80,
  duration_seconds: 60,
  newly_mastered: [],
  newly_difficult: [],
  error_items: [],
  by_exercise_type: {},
};

// ---------------------------------------------------------------------------
// Fetch stub helpers
// ---------------------------------------------------------------------------
function stubFetch(handlers: Record<string, (url: string, init?: RequestInit) => unknown>) {
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    const u = String(url);
    const method = (init?.method ?? "GET").toUpperCase();

    for (const [pattern, fn] of Object.entries(handlers)) {
      if (u.includes(pattern)) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(fn(u, init)),
        });
      }
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
  }));
}

beforeEach(() => {
  stubFetch({
    "/stats/user": () => MOCK_STATS,
    "/sessions/1/results": () => MOCK_RESULTS,
    "/sessions": () => ({ session: MOCK_SESSION, question: MOCK_QUESTION }),
  });
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe("TrainingTab — config phase", () => {
  it("shows Start Session button in config phase", async () => {
    render(<TrainingTab />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /start session/i })).toBeInTheDocument();
    });
  });

  it("shows mode buttons in FiltersPanel", async () => {
    render(<TrainingTab />);
    await waitFor(() => {
      expect(screen.getByText("Auto (mixed)")).toBeInTheDocument();
      expect(screen.getByText("New only")).toBeInTheDocument();
    });
  });

  it("renders ProgressStats with total items count", async () => {
    render(<TrainingTab />);
    await waitFor(() => {
      expect(screen.getByText("5")).toBeInTheDocument(); // total_items
    });
  });
});

describe("TrainingTab — session phase", () => {
  it("transitions to session view after clicking Start Session", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => {
      // SessionView renders the exercise prompt
      expect(screen.getByText("ephemeral")).toBeInTheDocument();
    });
  });
});

describe("TrainingTab — empty session", () => {
  it("shows error message when API returns no question", async () => {
    vi.unstubAllGlobals();
    stubFetch({
      "/stats/user": () => MOCK_STATS,
      "/sessions": () => ({ session: { ...MOCK_SESSION, total_questions: 0 }, question: null }),
    });
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => {
      expect(screen.getByText(/no items match/i)).toBeInTheDocument();
    });
  });
});

describe("TrainingTab — error state", () => {
  it("shows error message when API call fails", async () => {
    vi.unstubAllGlobals();
    stubFetch({
      "/stats/user": () => MOCK_STATS,
      "/sessions": () => { throw new Error("network error"); },
    });
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.includes("/stats/user")) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(MOCK_STATS) });
      }
      if (u.includes("/sessions")) {
        return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: "Server error" }) });
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
    }));

    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => {
      expect(screen.getByText(/server error/i)).toBeInTheDocument();
    });
  });
});

describe("TrainingTab — results phase", () => {
  it("shows Session Complete after session_complete signal", async () => {
    const answerResult = {
      is_correct: true,
      error_type: null,
      correct_answer: "мимолётный",
      explanation: null,
      next_question: null,
      session_complete: true,
      newly_mastered: false,
      newly_difficult: false,
    };
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      const u = String(url);
      const method = (init?.method ?? "GET").toUpperCase();
      if (u.includes("/stats/user")) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(MOCK_STATS) });
      if (u.includes("/sessions") && method === "POST" && !u.includes("/answer") && !u.includes("/complete")) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ session: MOCK_SESSION, question: MOCK_QUESTION }) });
      }
      if (u.includes("/answer")) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(answerResult) });
      if (u.includes("/results")) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(MOCK_RESULTS) });
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
    }));

    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));

    // Wait for session to load and exercise options to appear
    await waitFor(() => screen.getAllByRole("button").length > 1);
    const btns = screen.getAllByRole("button");
    fireEvent.click(btns[0]);

    await waitFor(() => {
      expect(screen.getByText(/session complete/i)).toBeInTheDocument();
    });
  });
});

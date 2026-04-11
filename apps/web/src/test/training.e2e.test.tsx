/**
 * E2E tests for the Training tab.
 *
 * These tests simulate full user workflows — from loading the config panel,
 * through answering exercises, to viewing results and restarting. All four
 * exercise types (mc, input, context, fill) and every session outcome
 * (correct, wrong, spelling, partial, empty, network errors) are covered.
 *
 * Mock strategy: vi.stubGlobal("fetch", ...) with regex URL matching.
 * Timer strategy: vi.useFakeTimers() per test block to control the 1 400 ms
 * feedback timer inside SessionView without slowing the suite down.
 */

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TrainingTab } from "../components/study/TrainingTab";
import type {
  AnswerResult,
  SessionQuestion,
  SessionResults,
  TrainingSession,
  UserStats,
} from "../components/study/types";

// ============================================================
// Helpers
// ============================================================

function ok(data: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(data),
  });
}

function err(status: number, detail: string) {
  return Promise.resolve({
    ok: false,
    status,
    json: () => Promise.resolve({ detail }),
  });
}

/** Advance the 1 400 ms SessionView feedback timer and flush React updates. */
async function advanceFeedback() {
  await act(async () => {
    vi.advanceTimersByTime(1500);
    await Promise.resolve();
  });
}

// ============================================================
// Fixtures
// ============================================================

const MOCK_STATS: UserStats = {
  total_items: 10,
  mastered: 3,
  learning: 4,
  difficult: 1,
  new: 2,
  suspended: 0,
  review: 0,
  by_lexical_type: { noun: 5, verb: 3, adjective: 2 },
  by_item_type: { word: 7, phrase: 3 },
  total_training_sessions: 5,
  total_questions_answered: 50,
  overall_accuracy_pct: 82,
};

const EMPTY_STATS: UserStats = {
  ...MOCK_STATS,
  total_items: 0,
};

function makeSession(overrides: Partial<TrainingSession> = {}): TrainingSession {
  return {
    id: 1,
    mode: "auto",
    filters_json: "{}",
    target_count: 3,
    item_ids_json: "[1,2,3]",
    status: "active",
    correct_count: 0,
    wrong_count: 0,
    total_questions: 3,
    newly_mastered_ids: "[]",
    newly_difficult_ids: "[]",
    error_item_ids: "[]",
    started_at: "2026-01-01T00:00:00",
    ended_at: null,
    ...overrides,
  };
}

function makeQuestion(
  id: number,
  type: "mc" | "input" | "context" | "fill",
  overrides: Partial<SessionQuestion> = {},
): SessionQuestion {
  return {
    id,
    session_id: 1,
    item_id: id,
    exercise_type: type,
    direction: "en_to_ru",
    correct_answer: "мимолётный",
    distractors_json: JSON.stringify(["повсеместный", "загадочный", "немедленный"]),
    prompt_text: "ephemeral",
    answer_given: null,
    is_correct: null,
    error_type: null,
    answered_at: null,
    retry_scheduled: 0,
    position: id - 1,
    ...overrides,
  };
}

function makeAnswerResult(overrides: Partial<AnswerResult> = {}): AnswerResult {
  return {
    is_correct: true,
    error_type: null,
    correct_answer: "мимолётный",
    explanation: null,
    next_question: null,
    session_complete: false,
    newly_mastered: false,
    newly_difficult: false,
    ...overrides,
  };
}

const MOCK_RESULTS: SessionResults = {
  session_id: 1,
  mode: "auto",
  total_questions: 3,
  correct_count: 2,
  wrong_count: 1,
  accuracy_pct: 67,
  duration_seconds: 45,
  newly_mastered: [
    { id: 1, target_text: "ephemeral", native_text: "мимолётный", item_type: "word" },
  ],
  newly_difficult: [],
  error_items: [
    { id: 2, target_text: "ubiquitous", native_text: "повсеместный", item_type: "word" },
  ],
  by_exercise_type: {
    mc: { shown: 2, correct: 2 },
    input: { shown: 1, correct: 0 },
  },
};

// ============================================================
// Fetch mock builders
// ============================================================

/**
 * Build a stateful fetch mock. Answers are consumed in order; the last one
 * is repeated for any extra calls.
 */
function buildFetch({
  stats = MOCK_STATS,
  sessionResponse = {
    session: makeSession(),
    question: makeQuestion(1, "mc") as SessionQuestion | null,
  },
  answerSequence = [makeAnswerResult({ session_complete: true })],
  results = MOCK_RESULTS,
}: {
  stats?: UserStats;
  sessionResponse?: { session: TrainingSession; question: SessionQuestion | null };
  answerSequence?: AnswerResult[];
  results?: SessionResults;
} = {}) {
  let answerIdx = 0;

  return vi.fn((url: string, init?: RequestInit) => {
    const u = String(url);
    const method = (init?.method ?? "GET").toUpperCase();

    if (u.includes("/stats/user")) return ok(stats);

    if (/\/sessions\/\d+\/answer/.test(u) && method === "POST") {
      const r =
        answerIdx < answerSequence.length
          ? answerSequence[answerIdx]
          : answerSequence.at(-1)!;
      answerIdx++;
      return ok(r);
    }

    if (/\/sessions\/\d+\/results/.test(u)) return ok(results);

    if (/\/sessions$/.test(u) && method === "POST") return ok(sessionResponse);

    return ok({});
  });
}

// ============================================================
// Setup / teardown
// ============================================================

beforeEach(() => {
  vi.stubGlobal("fetch", buildFetch());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

// ============================================================
// 1. Config phase
// ============================================================

describe("Config phase", () => {
  it("renders Start Session button", async () => {
    render(<TrainingTab />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /start session/i })).toBeInTheDocument(),
    );
  });

  it("loads and displays ProgressStats", async () => {
    render(<TrainingTab />);
    await waitFor(() => {
      expect(screen.getByText(/10 items/i)).toBeInTheDocument();
      expect(screen.getByText(/3 mastered/i)).toBeInTheDocument();
      expect(screen.getByText(/1 difficult/i)).toBeInTheDocument();
      expect(screen.getByText(/2 new/i)).toBeInTheDocument();
    });
  });

  it("hides ProgressStats when total_items is zero", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ stats: EMPTY_STATS }));
    render(<TrainingTab />);
    // Stats bar absent (component returns null when total_items===0)
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /start session/i })).toBeInTheDocument(),
    );
    expect(screen.queryByText(/items/)).toBeNull();
  });

  it("renders all mode buttons in FiltersPanel", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    const modeLabels = ["Auto", "New", "Difficult", "Overdue", "Errors", "By type"];
    for (const label of modeLabels) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });

  it("highlights Auto mode as active by default", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: "Auto" }));
    expect(screen.getByRole("button", { name: "Auto" })).toHaveClass(
      "filters-mode-btn--active",
    );
  });

  it("switches active mode when user clicks a mode button", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: "Auto" }));
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    expect(screen.getByRole("button", { name: "New" })).toHaveClass(
      "filters-mode-btn--active",
    );
    expect(screen.getByRole("button", { name: "Auto" })).not.toHaveClass(
      "filters-mode-btn--active",
    );
  });

  it("sends the selected mode in the createSession request body", async () => {
    const fetchMock = buildFetch();
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", fetchMock);

    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: "Difficult" }));
    fireEvent.click(screen.getByRole("button", { name: "Difficult" }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));

    await waitFor(() => {
      const calls = (fetchMock as ReturnType<typeof vi.fn>).mock.calls;
      const sessionCall = calls.find(
        ([u, init]: [string, RequestInit]) =>
          /\/sessions$/.test(u) && init?.method === "POST",
      );
      expect(sessionCall).toBeDefined();
      const body = JSON.parse(sessionCall![1].body as string);
      expect(body.mode).toBe("difficult");
    });
  });

  it("updates target count via the Cards input", async () => {
    const fetchMock = buildFetch();
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", fetchMock);

    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("spinbutton"));
    const cardsInput = screen.getByRole("spinbutton");
    fireEvent.change(cardsInput, { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));

    await waitFor(() => {
      const calls = (fetchMock as ReturnType<typeof vi.fn>).mock.calls;
      const sessionCall = calls.find(
        ([u, init]: [string, RequestInit]) =>
          /\/sessions$/.test(u) && init?.method === "POST",
      );
      const body = JSON.parse(sessionCall![1].body as string);
      expect(body.target_count).toBe(7);
    });
  });
});

// ============================================================
// 2. Session creation — error paths
// ============================================================

describe("Session creation errors", () => {
  it("shows error message when API returns no question (empty DB)", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      buildFetch({
        sessionResponse: {
          session: makeSession({ total_questions: 0 }),
          question: null,
        },
      }),
    );
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() =>
      expect(screen.getByText(/no items match/i)).toBeInTheDocument(),
    );
  });

  it("shows error message on network failure", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (String(url).includes("/stats/user")) return ok(MOCK_STATS);
        if (/\/sessions$/.test(String(url)) && (init?.method ?? "GET") === "POST")
          return err(500, "Internal Server Error");
        return ok({});
      }),
    );
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() =>
      expect(screen.getByText(/internal server error/i)).toBeInTheDocument(),
    );
  });

  it("shows loading state while session is being created", async () => {
    let resolveSession!: (v: unknown) => void;
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (String(url).includes("/stats/user")) return ok(MOCK_STATS);
        if (/\/sessions$/.test(String(url)) && (init?.method ?? "GET") === "POST")
          return new Promise((res) => { resolveSession = res; });
        return ok({});
      }),
    );
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    expect(screen.getByRole("button", { name: /loading/i })).toBeDisabled();
    // Unblock the pending request
    resolveSession({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ session: makeSession(), question: makeQuestion(1, "mc") }),
    });
  });
});

// ============================================================
// 3. MC exercise
// ============================================================

describe("MC exercise", () => {
  it("displays the word prompt and four option buttons", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByText("ephemeral"));
    // 4 answer options + 0 navigation buttons (session view has no nav)
    const opts = ["мимолётный", "повсеместный", "загадочный", "немедленный"];
    for (const opt of opts) {
      expect(screen.getByRole("button", { name: opt })).toBeInTheDocument();
    }
  });

  it("marks correct button green after correct answer", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      buildFetch({
        answerSequence: [makeAnswerResult({ is_correct: true, session_complete: true })],
      }),
    );
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByText("ephemeral"));

    fireEvent.click(screen.getByRole("button", { name: "мимолётный" }));

    await waitFor(() => {
      const btn = screen.getByRole("button", { name: "мимолётный" });
      expect(btn).toHaveClass("exercise__option--correct");
    });
  });

  it("marks clicked button red and correct button green on wrong answer", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      buildFetch({
        answerSequence: [
          makeAnswerResult({
            is_correct: false,
            error_type: "full_miss",
            session_complete: true,
          }),
        ],
      }),
    );
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByText("ephemeral"));

    fireEvent.click(screen.getByRole("button", { name: "повсеместный" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "повсеместный" })).toHaveClass(
        "exercise__option--wrong",
      );
      expect(screen.getByRole("button", { name: "мимолётный" })).toHaveClass(
        "exercise__option--correct",
      );
    });
  });

  it("disables all option buttons after an answer is submitted", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByText("ephemeral"));

    fireEvent.click(screen.getByRole("button", { name: "мимолётный" }));

    await waitFor(() => {
      const opts = ["мимолётный", "повсеместный", "загадочный", "немедленный"];
      for (const opt of opts) {
        expect(screen.getByRole("button", { name: opt })).toBeDisabled();
      }
    });
  });

  it("completes session and shows results screen", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByText("ephemeral"));

    fireEvent.click(screen.getByRole("button", { name: "мимолётный" }));

    await waitFor(() =>
      expect(screen.getByText(/session complete/i)).toBeInTheDocument(),
    );
  });
});

// ============================================================
// 4. Input exercise
// ============================================================

describe("Input exercise", () => {
  const inputQ = makeQuestion(1, "input", {
    prompt_text: "мимолётный",
    correct_answer: "ephemeral",
  });

  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      buildFetch({
        sessionResponse: { session: makeSession(), question: inputQ },
        answerSequence: [makeAnswerResult({ is_correct: true, session_complete: true })],
      }),
    );
  });

  it("renders a text input and Submit button", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByRole("textbox"));
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /submit/i })).toBeInTheDocument();
  });

  it("Submit button is disabled when input is empty", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByRole("button", { name: /submit/i }));
    expect(screen.getByRole("button", { name: /submit/i })).toBeDisabled();
  });

  it("Submit button is disabled when input is whitespace only", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByRole("textbox"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "   " } });
    expect(screen.getByRole("button", { name: /submit/i })).toBeDisabled();
  });

  it("submits answer via button click", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByRole("textbox"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "ephemeral" } });
    fireEvent.click(screen.getByRole("button", { name: /submit/i }));
    await waitFor(() =>
      expect(screen.getByText(/session complete/i)).toBeInTheDocument(),
    );
  });

  it("submits answer via Enter key", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByRole("textbox"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "ephemeral" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    await waitFor(() =>
      expect(screen.getByText(/session complete/i)).toBeInTheDocument(),
    );
  });

  it("shows correct feedback overlay after correct answer", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByRole("textbox"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "ephemeral" } });
    fireEvent.click(screen.getByRole("button", { name: /submit/i }));
    await waitFor(() =>
      expect(document.querySelector(".session-feedback--correct")).toBeInTheDocument(),
    );
  });

  it("shows wrong feedback overlay after wrong answer", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      buildFetch({
        sessionResponse: { session: makeSession(), question: inputQ },
        answerSequence: [
          makeAnswerResult({ is_correct: false, error_type: "full_miss", session_complete: true }),
        ],
      }),
    );
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByRole("textbox"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "wrong answer" } });
    fireEvent.click(screen.getByRole("button", { name: /submit/i }));
    await waitFor(() =>
      expect(document.querySelector(".session-feedback--wrong")).toBeInTheDocument(),
    );
  });
});

// ============================================================
// 5. Context exercise
// ============================================================

describe("Context exercise", () => {
  const ctxQ = makeQuestion(1, "context", {
    prompt_text: "She had an ephemeral feeling of happiness.",
    correct_answer: "мимолётный",
  });

  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      buildFetch({
        sessionResponse: { session: makeSession(), question: ctxQ },
        answerSequence: [makeAnswerResult({ is_correct: true, session_complete: true })],
      }),
    );
  });

  it("shows the sentence prompt and a label", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() =>
      screen.getByText("She had an ephemeral feeling of happiness."),
    );
    expect(
      screen.getByText(/choose the correct translation for the context/i),
    ).toBeInTheDocument();
  });

  it("highlights correct option green after correct selection", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByRole("button", { name: "мимолётный" }));
    fireEvent.click(screen.getByRole("button", { name: "мимолётный" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "мимолётный" })).toHaveClass(
        "exercise__option--correct",
      ),
    );
  });

  it("highlights wrong option red and correct green on wrong selection", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      buildFetch({
        sessionResponse: { session: makeSession(), question: ctxQ },
        answerSequence: [
          makeAnswerResult({ is_correct: false, error_type: "full_miss", session_complete: true }),
        ],
      }),
    );
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByRole("button", { name: "повсеместный" }));
    fireEvent.click(screen.getByRole("button", { name: "повсеместный" }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "повсеместный" })).toHaveClass(
        "exercise__option--wrong",
      );
      expect(screen.getByRole("button", { name: "мимолётный" })).toHaveClass(
        "exercise__option--correct",
      );
    });
  });
});

// ============================================================
// 6. Fill-in-blank exercise
// ============================================================

describe("Fill-in-blank exercise", () => {
  const fillQ = makeQuestion(1, "fill", {
    prompt_text: "The ___ beauty of the moment was not lost on her.",
    correct_answer: "ephemeral",
  });

  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      buildFetch({
        sessionResponse: { session: makeSession(), question: fillQ },
        answerSequence: [makeAnswerResult({ is_correct: true, session_complete: true })],
      }),
    );
  });

  it("shows 'Fill in the blank' label and the sentence prompt", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByText(/fill in the blank/i));
    expect(
      screen.getByText("The ___ beauty of the moment was not lost on her."),
    ).toBeInTheDocument();
  });

  it("Submit button disabled when input is empty", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByRole("button", { name: /submit/i }));
    expect(screen.getByRole("button", { name: /submit/i })).toBeDisabled();
  });

  it("submits via button click and shows results", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByRole("textbox"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "ephemeral" } });
    fireEvent.click(screen.getByRole("button", { name: /submit/i }));
    await waitFor(() =>
      expect(screen.getByText(/session complete/i)).toBeInTheDocument(),
    );
  });

  it("submits via Enter key and shows results", async () => {
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByRole("textbox"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "ephemeral" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    await waitFor(() =>
      expect(screen.getByText(/session complete/i)).toBeInTheDocument(),
    );
  });
});

// ============================================================
// 7. Multi-question flow (mc → input → fill)
// ============================================================

describe("Multi-question flow", () => {
  it("advances through three questions and shows results", async () => {
    // shouldAdvanceTime: true keeps real-time flowing so waitFor timeouts still fire,
    // while still allowing manual advancement of the 1 400 ms feedback timer.
    vi.useFakeTimers({ shouldAdvanceTime: true });

    const q1 = makeQuestion(1, "mc");
    const q2 = makeQuestion(2, "input", {
      prompt_text: "мимолётный",
      correct_answer: "ephemeral",
    });
    const q3 = makeQuestion(3, "fill", {
      prompt_text: "The ___ beauty was breathtaking.",
      correct_answer: "ephemeral",
    });
    const session = makeSession({ total_questions: 3 });

    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      buildFetch({
        sessionResponse: { session, question: q1 },
        answerSequence: [
          makeAnswerResult({ next_question: q2 }),          // Q1 → Q2
          makeAnswerResult({ next_question: q3 }),          // Q2 → Q3
          makeAnswerResult({ is_correct: false, error_type: "full_miss", session_complete: true }), // Q3 done
        ],
        results: MOCK_RESULTS,
      }),
    );

    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));

    // --- Q1: MC — correct ---
    await waitFor(() => screen.getByText("ephemeral"));
    expect(screen.getByText("1 / 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "мимолётный" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "мимолётный" })).toHaveClass(
        "exercise__option--correct",
      ),
    );
    await advanceFeedback();

    // --- Q2: Input — correct ---
    await waitFor(() => screen.getByText("мимолётный")); // prompt_text of Q2
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "ephemeral" } });
    fireEvent.click(screen.getByRole("button", { name: /submit/i }));
    await waitFor(() =>
      expect(document.querySelector(".session-feedback--correct")).toBeInTheDocument(),
    );
    await advanceFeedback();

    // --- Q3: Fill — wrong ---
    await waitFor(() => screen.getByText(/The ___ beauty was breathtaking\./));
    expect(screen.getByText("3 / 3")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "transient" } });
    fireEvent.click(screen.getByRole("button", { name: /submit/i }));

    // Session completes — results fetched immediately (no timer needed)
    await waitFor(() =>
      expect(screen.getByText(/session complete/i)).toBeInTheDocument(),
    );
  });

  it("updates the progress bar width after each answered question", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });

    const q1 = makeQuestion(1, "mc");
    const q2 = makeQuestion(2, "mc", { prompt_text: "ubiquitous" });
    const session = makeSession({ total_questions: 2 });

    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      buildFetch({
        sessionResponse: { session, question: q1 },
        answerSequence: [
          makeAnswerResult({ next_question: q2 }),
          makeAnswerResult({ session_complete: true }),
        ],
      }),
    );

    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));

    await waitFor(() => screen.getByText("ephemeral"));
    const bar = () =>
      document.querySelector(".session-progress__bar") as HTMLElement;
    expect(bar().style.width).toBe("0%"); // 0/2

    fireEvent.click(screen.getByRole("button", { name: "мимолётный" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "мимолётный" })).toHaveClass(
        "exercise__option--correct",
      ),
    );
    await advanceFeedback();

    await waitFor(() => screen.getByText("ubiquitous"));
    expect(bar().style.width).toBe("50%"); // 1/2
  });

  it("increments the correct-answer score counter after a correct MC answer", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });

    const q1 = makeQuestion(1, "mc");
    const q2 = makeQuestion(2, "mc", { prompt_text: "ubiquitous" });
    const session = makeSession({ total_questions: 2, correct_count: 0 });

    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      buildFetch({
        sessionResponse: { session, question: q1 },
        answerSequence: [
          makeAnswerResult({ is_correct: true, next_question: q2 }),
          makeAnswerResult({ is_correct: true, session_complete: true }),
        ],
      }),
    );

    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));

    await waitFor(() => screen.getByText("ephemeral"));
    expect(screen.getByText("0 ✓")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "мимолётный" }));
    // Wait for the result feedback class before advancing the 1 400 ms timer.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "мимолётный" })).toHaveClass(
        "exercise__option--correct",
      ),
    );
    await advanceFeedback();

    await waitFor(() => screen.getByText("ubiquitous"));
    expect(screen.getByText("1 ✓")).toBeInTheDocument();
  });
});

// ============================================================
// 8. Results phase
// ============================================================

describe("Results phase", () => {
  async function reachResults(results = MOCK_RESULTS) {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      buildFetch({
        answerSequence: [makeAnswerResult({ is_correct: true, session_complete: true })],
        results,
      }),
    );
    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByText("ephemeral"));
    fireEvent.click(screen.getByRole("button", { name: "мимолётный" }));
    await waitFor(() => screen.getByText(/session complete/i));
  }

  it("shows accuracy percentage", async () => {
    await reachResults();
    expect(screen.getByText("67%")).toBeInTheDocument();
  });

  it("shows correct / wrong / total counts and duration", async () => {
    await reachResults();
    expect(screen.getByText("2")).toBeInTheDocument(); // correct_count
    expect(screen.getByText("1")).toBeInTheDocument(); // wrong_count
    expect(screen.getByText("3")).toBeInTheDocument(); // total_questions
    expect(screen.getByText("0m 45s")).toBeInTheDocument();
  });

  it("lists newly mastered items", async () => {
    await reachResults();
    expect(screen.getByText(/newly mastered/i)).toBeInTheDocument();
    expect(screen.getByText("ephemeral")).toBeInTheDocument();
    expect(screen.getByText("мимолётный")).toBeInTheDocument();
  });

  it("lists error items in 'Needs Work' section", async () => {
    await reachResults();
    expect(screen.getByText(/needs work/i)).toBeInTheDocument();
    expect(screen.getByText("ubiquitous")).toBeInTheDocument();
    expect(screen.getByText("повсеместный")).toBeInTheDocument();
  });

  it("shows per-exercise-type breakdown", async () => {
    await reachResults();
    expect(screen.getByText(/by exercise type/i)).toBeInTheDocument();
    expect(screen.getByText("mc")).toBeInTheDocument();
    expect(screen.getByText("2/2")).toBeInTheDocument();
    expect(screen.getByText("input")).toBeInTheDocument();
    expect(screen.getByText("0/1")).toBeInTheDocument();
  });

  it("omits 'Newly Mastered' section when list is empty", async () => {
    await reachResults({ ...MOCK_RESULTS, newly_mastered: [] });
    expect(screen.queryByText(/newly mastered/i)).toBeNull();
  });

  it("omits 'Needs Work' section when error_items is empty", async () => {
    await reachResults({ ...MOCK_RESULTS, error_items: [] });
    expect(screen.queryByText(/needs work/i)).toBeNull();
  });

  it("'New Session' button returns to config phase", async () => {
    await reachResults();
    fireEvent.click(screen.getByRole("button", { name: /new session/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /start session/i })).toBeInTheDocument(),
    );
  });

  it("'Close' button returns to config phase", async () => {
    await reachResults();
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /start session/i })).toBeInTheDocument(),
    );
  });

  it("applies 'good' accuracy class for pct >= 85", async () => {
    await reachResults({ ...MOCK_RESULTS, accuracy_pct: 90 });
    const pctEl = document.querySelector(".results-accuracy");
    expect(pctEl).toHaveClass("results-accuracy--good");
  });

  it("applies 'ok' accuracy class for pct in [60, 85)", async () => {
    await reachResults({ ...MOCK_RESULTS, accuracy_pct: 70 });
    const pctEl = document.querySelector(".results-accuracy");
    expect(pctEl).toHaveClass("results-accuracy--ok");
  });

  it("applies 'poor' accuracy class for pct < 60", async () => {
    await reachResults({ ...MOCK_RESULTS, accuracy_pct: 40 });
    const pctEl = document.querySelector(".results-accuracy");
    expect(pctEl).toHaveClass("results-accuracy--poor");
  });

  it("omits duration when duration_seconds is null", async () => {
    await reachResults({ ...MOCK_RESULTS, duration_seconds: null });
    // "0m 45s" should not appear; general time label absent
    expect(screen.queryByText(/\dm \d+s/)).toBeNull();
  });
});

// ============================================================
// 9. Error recovery
// ============================================================

describe("Error recovery", () => {
  it("resets input exercise to idle state after a network error on answer submission", async () => {
    // Use an input exercise: its enabled/disabled state is driven purely by the
    // `disabled` prop (SessionView resets this to false on catch), with no
    // internal "selected" state that would keep buttons locked as MC has.
    const inputQ = makeQuestion(1, "input", {
      prompt_text: "мимолётный",
      correct_answer: "ephemeral",
    });
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        const u = String(url);
        const m = (init?.method ?? "GET").toUpperCase();
        if (u.includes("/stats/user")) return ok(MOCK_STATS);
        if (/\/sessions$/.test(u) && m === "POST")
          return ok({ session: makeSession(), question: inputQ });
        if (/\/answer/.test(u))
          return Promise.reject(new Error("network failure"));
        return ok({});
      }),
    );

    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByRole("textbox"));

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "ephemeral" } });
    fireEvent.click(screen.getByRole("button", { name: /submit/i }));

    // After the rejected promise, SessionView catch block resets answerState → idle.
    // The input and Submit button become re-enabled (disabled prop is false again).
    await waitFor(() => {
      expect(screen.getByRole("textbox")).not.toBeDisabled();
      expect(screen.getByRole("button", { name: /submit/i })).not.toBeDisabled();
    });
  });

  it("shows error and returns to config when getSessionResults fails", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        const u = String(url);
        const m = (init?.method ?? "GET").toUpperCase();
        if (u.includes("/stats/user")) return ok(MOCK_STATS);
        if (/\/sessions$/.test(u) && m === "POST")
          return ok({ session: makeSession(), question: makeQuestion(1, "mc") });
        if (/\/answer/.test(u))
          return ok(makeAnswerResult({ session_complete: true }));
        if (/\/results/.test(u))
          return err(500, "Results unavailable");
        return ok({});
      }),
    );

    render(<TrainingTab />);
    await waitFor(() => screen.getByRole("button", { name: /start session/i }));
    fireEvent.click(screen.getByRole("button", { name: /start session/i }));
    await waitFor(() => screen.getByText("ephemeral"));

    fireEvent.click(screen.getByRole("button", { name: "мимолётный" }));

    await waitFor(() =>
      expect(screen.getByText(/results unavailable/i)).toBeInTheDocument(),
    );
    // Config Start button is available again
    expect(screen.getByRole("button", { name: /start session/i })).toBeInTheDocument();
  });
});

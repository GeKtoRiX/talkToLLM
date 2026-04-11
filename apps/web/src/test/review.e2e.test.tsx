/**
 * E2E tests for the Review tab (StudyPanel).
 *
 * Covers: empty state, front/back card, all four ratings, full queue drain,
 * error handling on load and on submit, stats display, add-word form, and
 * card content (native text, context note, example sentence).
 *
 * Mock strategy: vi.stubGlobal("fetch", ...) with URL substring matching.
 * Review and All Items render through <StudyPanel> so tab navigation is real.
 */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StudyPanel } from "../components/StudyPanel";
import type { StudyItem, StudyStats } from "../components/StudyPanel";

// ============================================================
// Fixtures
// ============================================================

const STATS_EMPTY: StudyStats = {
  new: 0, learning: 0, review: 0, mastered: 0, difficult: 0,
  suspended: 0, due: 0, total_items: 0, total_reviews: 0,
};

const STATS_TWO: StudyStats = {
  new: 2, learning: 1, review: 1, mastered: 0, difficult: 0,
  suspended: 0, due: 2, total_items: 4, total_reviews: 5,
};

const STATS_ONE: StudyStats = {
  ...STATS_TWO, new: 1, due: 1,
};

function makeItem(overrides: Partial<StudyItem> = {}): StudyItem {
  return {
    id: 1,
    item_type: "word",
    target_text: "ephemeral",
    native_text: "мимолётный",
    context_note: "used as adjective",
    example_sentence: "An ephemeral moment.",
    status: "new",
    ease: 2.5,
    interval_days: 1,
    repetitions: 0,
    lapses: 0,
    next_review_at: "2026-01-01T00:00:00",
    ...overrides,
  };
}

const ITEM_1 = makeItem();
const ITEM_2 = makeItem({
  id: 2,
  target_text: "ubiquitous",
  native_text: "повсеместный",
  context_note: "",
  example_sentence: "",
  status: "learning",
  repetitions: 2,
});

// ============================================================
// Fetch mock builders
// ============================================================

/**
 * Build a fetch mock for the Review tab.
 * `reviewResult` is returned for POST /review/:id.
 * After the review call, `statsAfter` is used for subsequent /stats requests.
 */
function buildFetch({
  due = [ITEM_1] as StudyItem[],
  stats = STATS_TWO as StudyStats,
  statsAfter = null as StudyStats | null,
  reviewResult = { ...ITEM_1, repetitions: 1, status: "learning" } as StudyItem,
  addResult = { saved: 1, skipped: 0 } as { saved: number; skipped: number },
  failReview = false,
  failLoad = false,
} = {}) {
  let reviewed = false;

  return vi.fn((url: string, init?: RequestInit) => {
    const u = String(url);
    const method = (init?.method ?? "GET").toUpperCase();

    if (failLoad && method === "GET") {
      return Promise.reject(new Error("Network error"));
    }

    if (method === "DELETE") {
      return Promise.resolve({ ok: true, status: 204, json: () => Promise.resolve(null) });
    }

    if (method === "PATCH") {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({ ...ITEM_1, native_text: "updated" }),
      });
    }

    if (u.includes("/review/") && method === "POST") {
      if (failReview) {
        return Promise.resolve({
          ok: false, status: 500,
          json: () => Promise.resolve({ detail: "Review failed" }),
        });
      }
      reviewed = true;
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(reviewResult) });
    }

    if (u.includes("/api/study/items") && method === "POST") {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(addResult) });
    }

    if (u.includes("/api/study/due")) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(due) });
    }

    if (u.includes("/api/study/stats")) {
      const s = (reviewed && statsAfter) ? statsAfter : stats;
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(s) });
    }

    // /api/study/items (GET) — used by AllItemsView but not Review
    if (u.includes("/api/study/items")) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) });
    }

    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
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
});

// ============================================================
// 1. Initial loading & empty state
// ============================================================

describe("Review tab — loading & empty state", () => {
  it("shows loading text initially", () => {
    render(<StudyPanel />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("shows 'All caught up' when queue is empty", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ due: [], stats: STATS_EMPTY }));
    render(<StudyPanel />);
    await waitFor(() =>
      expect(screen.getByText(/all caught up/i)).toBeInTheDocument(),
    );
  });

  it("shows stats bar in empty state", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ due: [], stats: STATS_EMPTY }));
    render(<StudyPanel />);
    await waitFor(() => screen.getByText(/all caught up/i));
    expect(screen.getByText("0 new")).toBeInTheDocument();
    expect(screen.getByText("0 due")).toBeInTheDocument();
  });

  it("shows Refresh button in empty state", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ due: [], stats: STATS_EMPTY }));
    render(<StudyPanel />);
    await waitFor(() => screen.getByRole("button", { name: /refresh/i }));
  });
});

// ============================================================
// 2. Front card
// ============================================================

describe("Review tab — front card", () => {
  it("shows target text", async () => {
    render(<StudyPanel />);
    await waitFor(() => screen.getByText("ephemeral"));
  });

  it("shows item_type badge", async () => {
    render(<StudyPanel />);
    await waitFor(() => screen.getByText("word"));
  });

  it("shows Show Answer button", async () => {
    render(<StudyPanel />);
    await waitFor(() => screen.getByRole("button", { name: /show answer/i }));
  });

  it("does not show rating buttons on front", async () => {
    render(<StudyPanel />);
    await waitFor(() => screen.getByRole("button", { name: /show answer/i }));
    expect(screen.queryByRole("button", { name: /again/i })).toBeNull();
  });

  it("shows stats bar with queue info", async () => {
    render(<StudyPanel />);
    await waitFor(() => screen.getByText("ephemeral"));
    expect(screen.getByText("2 new")).toBeInTheDocument();
    expect(screen.getByText("1 learning")).toBeInTheDocument();
    expect(screen.getByText("2 due")).toBeInTheDocument();
  });
});

// ============================================================
// 3. Back card (after flip)
// ============================================================

describe("Review tab — back card", () => {
  async function flip() {
    render(<StudyPanel />);
    await waitFor(() => screen.getByRole("button", { name: /show answer/i }));
    fireEvent.click(screen.getByRole("button", { name: /show answer/i }));
  }

  it("shows native text after flip", async () => {
    await flip();
    expect(screen.getByText("мимолётный")).toBeInTheDocument();
  });

  it("shows context note after flip", async () => {
    await flip();
    expect(screen.getByText("used as adjective")).toBeInTheDocument();
  });

  it("shows example sentence after flip", async () => {
    await flip();
    expect(screen.getByText("An ephemeral moment.")).toBeInTheDocument();
  });

  it("shows all four rating buttons", async () => {
    await flip();
    for (const label of ["Again", "Hard", "Good", "Easy"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });

  it("shows item meta (item_type · rep N)", async () => {
    await flip();
    expect(screen.getByText(/word · rep 0/i)).toBeInTheDocument();
  });
});

// ============================================================
// 4. Rating — request body
// ============================================================

describe("Review tab — rating request body", () => {
  async function submitRating(rating: string) {
    const fetchMock = buildFetch();
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", fetchMock);

    render(<StudyPanel />);
    await waitFor(() => screen.getByRole("button", { name: /show answer/i }));
    fireEvent.click(screen.getByRole("button", { name: /show answer/i }));
    fireEvent.click(screen.getByRole("button", { name: rating }));

    await waitFor(() => {
      const calls = (fetchMock as ReturnType<typeof vi.fn>).mock.calls;
      return calls.some(
        ([u, init]: [string, RequestInit]) =>
          u.includes("/review/") && init?.method === "POST",
      );
    });

    const calls = (fetchMock as ReturnType<typeof vi.fn>).mock.calls;
    const reviewCall = calls.find(
      ([u, init]: [string, RequestInit]) =>
        u.includes("/review/") && init?.method === "POST",
    );
    return JSON.parse(reviewCall![1].body as string);
  }

  it("sends rating=again", async () => {
    const body = await submitRating("Again");
    expect(body.rating).toBe("again");
  });

  it("sends rating=hard", async () => {
    const body = await submitRating("Hard");
    expect(body.rating).toBe("hard");
  });

  it("sends rating=good", async () => {
    const body = await submitRating("Good");
    expect(body.rating).toBe("good");
  });

  it("sends rating=easy", async () => {
    const body = await submitRating("Easy");
    expect(body.rating).toBe("easy");
  });
});

// ============================================================
// 5. Full queue drain (2 cards → empty)
// ============================================================

describe("Review tab — full queue drain", () => {
  it("advances to second card after rating, then shows empty state", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      buildFetch({
        due: [ITEM_1, ITEM_2],
        stats: STATS_TWO,
        statsAfter: STATS_EMPTY,
        reviewResult: { ...ITEM_1, repetitions: 1 },
      }),
    );

    render(<StudyPanel />);
    await waitFor(() => screen.getByText("ephemeral"));

    // Rate first card
    fireEvent.click(screen.getByRole("button", { name: /show answer/i }));
    fireEvent.click(screen.getByRole("button", { name: "Good" }));

    // Second card appears
    await waitFor(() => screen.getByText("ubiquitous"));

    // Rate second card
    fireEvent.click(screen.getByRole("button", { name: /show answer/i }));
    fireEvent.click(screen.getByRole("button", { name: "Easy" }));

    // Queue exhausted
    await waitFor(() =>
      expect(screen.getByText(/all caught up/i)).toBeInTheDocument(),
    );
  });

  it("shows correct card metadata (repetitions) for second card", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      buildFetch({
        due: [ITEM_1, ITEM_2],
        stats: STATS_TWO,
        reviewResult: { ...ITEM_1, repetitions: 1 },
      }),
    );

    render(<StudyPanel />);
    await waitFor(() => screen.getByText("ephemeral"));
    fireEvent.click(screen.getByRole("button", { name: /show answer/i }));
    fireEvent.click(screen.getByRole("button", { name: "Good" }));

    await waitFor(() => screen.getByText("ubiquitous"));
    fireEvent.click(screen.getByRole("button", { name: /show answer/i }));
    expect(screen.getByText(/word · rep 2/i)).toBeInTheDocument();
  });
});

// ============================================================
// 6. Error handling — load failure
// ============================================================

describe("Review tab — load error", () => {
  it("shows error banner on network failure", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("Network error"))));
    render(<StudyPanel />);
    await waitFor(() =>
      expect(screen.getByText(/network error/i)).toBeInTheDocument(),
    );
  });

  it("shows Retry button on load failure", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("oops"))));
    render(<StudyPanel />);
    await waitFor(() => screen.getByRole("button", { name: /retry/i }));
  });

  it("reloads queue after clicking Retry", async () => {
    let callCount = 0;
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => {
        callCount++;
        if (callCount <= 2) return Promise.reject(new Error("Temporary failure"));
        // Subsequent calls succeed
        return Promise.resolve({
          ok: true, status: 200,
          json: () => Promise.resolve(
            String(arguments[0]).includes("/due") ? [ITEM_1] : STATS_TWO,
          ),
        });
      }),
    );

    vi.unstubAllGlobals();
    // Fail first, succeed on retry
    let attempt = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => {
        attempt++;
        if (attempt === 1) return Promise.reject(new Error("Temporary failure"));
        const url = String((vi.fn as unknown as { mock: { calls: unknown[][] } }).mock?.calls?.[attempt - 1]?.[0] ?? "");
        void url;
        return Promise.resolve({
          ok: true, status: 200,
          json: () => Promise.resolve([]),
        });
      }),
    );

    // Simpler version: fail once then succeed
    vi.unstubAllGlobals();
    let retried = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => {
        if (!retried) {
          retried = true;
          return Promise.reject(new Error("Temporary failure"));
        }
        return Promise.resolve({
          ok: true, status: 200,
          json: () => Promise.resolve([]),
        });
      }),
    );

    render(<StudyPanel />);
    await waitFor(() => screen.getByRole("button", { name: /retry/i }));
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() =>
      expect(screen.getByText(/all caught up/i)).toBeInTheDocument(),
    );
  });
});

// ============================================================
// 7. Error handling — review submission failure
// ============================================================

describe("Review tab — review submission error", () => {
  it("shows error banner when review POST fails", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ failReview: true }));

    render(<StudyPanel />);
    await waitFor(() => screen.getByRole("button", { name: /show answer/i }));
    fireEvent.click(screen.getByRole("button", { name: /show answer/i }));
    fireEvent.click(screen.getByRole("button", { name: "Good" }));

    await waitFor(() =>
      expect(screen.getByText(/review failed/i)).toBeInTheDocument(),
    );
  });
});

// ============================================================
// 8. Submitting phase
// ============================================================

describe("Review tab — submitting phase", () => {
  it("shows Saving… while review is in flight", async () => {
    let resolve!: (v: unknown) => void;
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        const u = String(url);
        const method = (init?.method ?? "GET").toUpperCase();
        if (u.includes("/review/") && method === "POST") {
          return new Promise((res) => { resolve = res; });
        }
        if (u.includes("/due"))   return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([ITEM_1]) });
        if (u.includes("/stats")) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(STATS_TWO) });
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
      }),
    );

    render(<StudyPanel />);
    await waitFor(() => screen.getByRole("button", { name: /show answer/i }));
    fireEvent.click(screen.getByRole("button", { name: /show answer/i }));
    fireEvent.click(screen.getByRole("button", { name: "Good" }));

    await waitFor(() =>
      expect(screen.getByText(/saving/i)).toBeInTheDocument(),
    );

    // Unblock the pending request so cleanup is clean
    resolve({ ok: true, status: 200, json: () => Promise.resolve({ ...ITEM_1, repetitions: 1 }) });
  });
});

// ============================================================
// 9. Add word form (present in both empty and front-card states)
// ============================================================

describe("Review tab — Add word form", () => {
  it("Add word toggle is visible in empty state", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ due: [], stats: STATS_EMPTY }));
    render(<StudyPanel />);
    await waitFor(() => screen.getByText(/all caught up/i));
    expect(screen.getByRole("button", { name: /add word/i })).toBeInTheDocument();
  });

  it("Add word toggle is visible when a card is shown", async () => {
    render(<StudyPanel />);
    await waitFor(() => screen.getByText("ephemeral"));
    expect(screen.getByRole("button", { name: /add word/i })).toBeInTheDocument();
  });

  it("opens the add form on toggle click", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ due: [], stats: STATS_EMPTY }));
    render(<StudyPanel />);
    await waitFor(() => screen.getByText(/all caught up/i));
    fireEvent.click(screen.getByRole("button", { name: /add word/i }));
    expect(screen.getByLabelText("Word or phrase")).toBeInTheDocument();
  });

  it("shows Saved! feedback after successful add", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      buildFetch({ due: [], stats: STATS_EMPTY, addResult: { saved: 1, skipped: 0 } }),
    );
    render(<StudyPanel />);
    await waitFor(() => screen.getByText(/all caught up/i));
    fireEvent.click(screen.getByRole("button", { name: /add word/i }));
    fireEvent.change(screen.getByLabelText("Word or phrase"), { target: { value: "serendipity" } });
    fireEvent.submit(screen.getByRole("button", { name: /^save$/i }).closest("form")!);
    await waitFor(() => screen.getByText("Saved!"));
  });

  it("shows duplicate message when item already exists", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      buildFetch({ due: [], stats: STATS_EMPTY, addResult: { saved: 0, skipped: 1 } }),
    );
    render(<StudyPanel />);
    await waitFor(() => screen.getByText(/all caught up/i));
    fireEvent.click(screen.getByRole("button", { name: /add word/i }));
    fireEvent.change(screen.getByLabelText("Word or phrase"), { target: { value: "ephemeral" } });
    fireEvent.submit(screen.getByRole("button", { name: /^save$/i }).closest("form")!);
    await waitFor(() => screen.getByText(/already in the list/i));
  });
});

// ============================================================
// 10. Refresh after empty state
// ============================================================

describe("Review tab — Refresh button", () => {
  it("reloads the queue when Refresh is clicked", async () => {
    let reloaded = false;
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        const u = String(url);
        if (u.includes("/due")) {
          const result = reloaded ? [ITEM_1] : [];
          reloaded = true;
          return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(result) });
        }
        if (u.includes("/stats")) {
          return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(STATS_EMPTY) });
        }
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
      }),
    );

    render(<StudyPanel />);
    await waitFor(() => screen.getByText(/all caught up/i));
    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    await waitFor(() => screen.getByText("ephemeral"));
  });
});

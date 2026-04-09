import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StudyPanel } from "./StudyPanel";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------
const ITEM_1: import("./StudyPanel").StudyItem = {
  id: 1,
  item_type: "word",
  target_text: "ephemeral",
  native_text: "мимолётный",
  context_note: "adjective",
  example_sentence: "An ephemeral moment.",
  status: "new",
  ease: 2.5,
  interval_days: 1,
  repetitions: 0,
  lapses: 0,
  next_review_at: "2020-01-01 00:00:00",
};

const ITEM_2: import("./StudyPanel").StudyItem = {
  ...ITEM_1,
  id: 2,
  target_text: "ubiquitous",
  native_text: "повсеместный",
  context_note: "",
  example_sentence: "",
};

const STATS_FULL: import("./StudyPanel").StudyStats = {
  new: 2, learning: 0, review: 0, suspended: 0,
  due: 2, total_items: 2, total_reviews: 0,
};

const STATS_EMPTY: import("./StudyPanel").StudyStats = {
  new: 0, learning: 0, review: 0, suspended: 0,
  due: 0, total_items: 0, total_reviews: 0,
};

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------
function stubFetch(handlers: Record<string, () => unknown>) {
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    const u = String(url);
    const method = (init?.method ?? "GET").toUpperCase();

    if (method === "DELETE") return Promise.resolve({ ok: true, status: 204, json: () => Promise.resolve(null) });
    if (method === "PATCH")  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ...ITEM_1, native_text: "updated" }) });

    for (const [pattern, fn] of Object.entries(handlers)) {
      if (u.includes(pattern)) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(fn()) });
      }
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
  }));
}

function stubReviewFetch(due: typeof ITEM_1[], stats: typeof STATS_EMPTY) {
  stubFetch({
    "/due":   () => due,
    "/stats": () => stats,
    "/items": () => due,
    "/review": () => ({ ...due[0], repetitions: 1, status: "learning" }),
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// Tab navigation
// ---------------------------------------------------------------------------
describe("StudyPanel — tabs", () => {
  it("renders Review and All Items tabs", async () => {
    stubReviewFetch([], STATS_EMPTY);
    render(<StudyPanel />);
    expect(screen.getByRole("button", { name: "Review" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All Items" })).toBeInTheDocument();
  });

  it("defaults to Review tab", async () => {
    stubReviewFetch([], STATS_EMPTY);
    render(<StudyPanel />);
    await waitFor(() => screen.getByText(/all caught up/i));
    // loading text should resolve into review content
    expect(screen.queryByText("No items yet")).toBeNull();
  });

  it("switches to All Items tab", async () => {
    stubFetch({ "/due": () => [], "/stats": () => STATS_EMPTY, "/items": () => [] });
    render(<StudyPanel />);
    fireEvent.click(screen.getByRole("button", { name: "All Items" }));
    await waitFor(() => screen.getByText(/no items yet/i));
  });
});

// ---------------------------------------------------------------------------
// Review tab — empty & cards
// ---------------------------------------------------------------------------
describe("StudyPanel — Review tab / empty", () => {
  it("shows empty state when nothing is due", async () => {
    stubReviewFetch([], STATS_EMPTY);
    render(<StudyPanel />);
    await waitFor(() => screen.getByText(/all caught up/i));
  });

  it("shows stats", async () => {
    stubReviewFetch([], STATS_EMPTY);
    render(<StudyPanel />);
    await waitFor(() => screen.getByText(/all caught up/i));
    expect(screen.getByText("0 new")).toBeInTheDocument();
  });
});

describe("StudyPanel — Review tab / front card", () => {
  it("shows target text", async () => {
    stubReviewFetch([ITEM_1], STATS_FULL);
    render(<StudyPanel />);
    await waitFor(() => screen.getByText("ephemeral"));
  });

  it("shows Show Answer button", async () => {
    stubReviewFetch([ITEM_1], STATS_FULL);
    render(<StudyPanel />);
    await waitFor(() => screen.getByRole("button", { name: /show answer/i }));
  });

  it("does not show rating buttons on front", async () => {
    stubReviewFetch([ITEM_1], STATS_FULL);
    render(<StudyPanel />);
    await waitFor(() => screen.getByRole("button", { name: /show answer/i }));
    expect(screen.queryByRole("button", { name: /again/i })).toBeNull();
  });
});

describe("StudyPanel — Review tab / back card", () => {
  async function showBack() {
    stubReviewFetch([ITEM_1], STATS_FULL);
    render(<StudyPanel />);
    await waitFor(() => screen.getByRole("button", { name: /show answer/i }));
    fireEvent.click(screen.getByRole("button", { name: /show answer/i }));
  }

  it("shows native text after flip", async () => {
    await showBack();
    expect(screen.getByText("мимолётный")).toBeInTheDocument();
  });

  it("shows all four rating buttons", async () => {
    await showBack();
    for (const label of ["Again", "Hard", "Good", "Easy"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });
});

describe("StudyPanel — Review tab / rating", () => {
  it("advances to next card after rating", async () => {
    stubFetch({
      "/due":    () => [ITEM_1, ITEM_2],
      "/stats":  () => STATS_FULL,
      "/review": () => ({ ...ITEM_1, repetitions: 1 }),
      "/items":  () => [],
    });
    render(<StudyPanel />);
    await waitFor(() => screen.getByText("ephemeral"));
    fireEvent.click(screen.getByRole("button", { name: /show answer/i }));
    fireEvent.click(screen.getByRole("button", { name: "Good" }));
    await waitFor(() => screen.getByText("ubiquitous"));
  });
});

// ---------------------------------------------------------------------------
// Add word form (present in both tabs)
// ---------------------------------------------------------------------------
describe("StudyPanel — Add word form", () => {
  it("toggle opens the form", async () => {
    stubReviewFetch([], STATS_EMPTY);
    render(<StudyPanel />);
    await waitFor(() => screen.getByText(/all caught up/i));
    fireEvent.click(screen.getByRole("button", { name: /add word/i }));
    expect(screen.getByLabelText("Word or phrase")).toBeInTheDocument();
  });

  it("shows Saved! on success", async () => {
    stubFetch({
      "/due":   () => [],
      "/stats": () => STATS_EMPTY,
      "/items": () => ({ saved: 1, skipped: 0, ids: [42] }),
    });
    render(<StudyPanel />);
    await waitFor(() => screen.getByText(/all caught up/i));
    fireEvent.click(screen.getByRole("button", { name: /add word/i }));
    fireEvent.change(screen.getByLabelText("Word or phrase"), { target: { value: "serendipity" } });
    fireEvent.submit(screen.getByRole("button", { name: /^save$/i }).closest("form")!);
    await waitFor(() => screen.getByText("Saved!"));
  });

  it("shows duplicate message when skipped", async () => {
    stubFetch({
      "/due":   () => [],
      "/stats": () => STATS_EMPTY,
      "/items": () => ({ saved: 0, skipped: 1, ids: [] }),
    });
    render(<StudyPanel />);
    await waitFor(() => screen.getByText(/all caught up/i));
    fireEvent.click(screen.getByRole("button", { name: /add word/i }));
    fireEvent.change(screen.getByLabelText("Word or phrase"), { target: { value: "dup" } });
    fireEvent.submit(screen.getByRole("button", { name: /^save$/i }).closest("form")!);
    await waitFor(() => screen.getByText(/already in the list/i));
  });
});

// ---------------------------------------------------------------------------
// All Items tab — list, edit, delete
// ---------------------------------------------------------------------------
describe("StudyPanel — All Items tab", () => {
  async function openItemsTab(items: typeof ITEM_1[]) {
    stubFetch({
      "/due":   () => [],
      "/stats": () => STATS_EMPTY,
      "/items": () => items,
    });
    render(<StudyPanel />);
    fireEvent.click(screen.getByRole("button", { name: "All Items" }));
    await waitFor(() => {
      if (items.length > 0) screen.getByText(items[0].target_text);
      else screen.getByText(/no items yet/i);
    });
  }

  it("shows empty message when no items", async () => {
    await openItemsTab([]);
    expect(screen.getByText(/no items yet/i)).toBeInTheDocument();
  });

  it("lists item target text", async () => {
    await openItemsTab([ITEM_1]);
    expect(screen.getByText("ephemeral")).toBeInTheDocument();
  });

  it("shows edit and delete buttons per item", async () => {
    await openItemsTab([ITEM_1]);
    expect(screen.getByRole("button", { name: /edit item/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /delete item/i })).toBeInTheDocument();
  });

  it("opens inline edit form on edit click", async () => {
    await openItemsTab([ITEM_1]);
    fireEvent.click(screen.getByRole("button", { name: /edit item/i }));
    expect(screen.getByLabelText("Target text")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
  });

  it("cancel closes the edit form", async () => {
    await openItemsTab([ITEM_1]);
    fireEvent.click(screen.getByRole("button", { name: /edit item/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(screen.queryByLabelText("Target text")).toBeNull();
  });

  it("saves edit and updates the row", async () => {
    await openItemsTab([ITEM_1]);
    fireEvent.click(screen.getByRole("button", { name: /edit item/i }));
    const targetInput = screen.getByLabelText("Target text") as HTMLInputElement;
    fireEvent.change(targetInput, { target: { value: "ephemeral_edited" } });
    fireEvent.submit(targetInput.closest("form")!);
    await waitFor(() => screen.getByText("updated")); // native_text from stub
  });

  it("removes item from list after delete", async () => {
    await openItemsTab([ITEM_1]);
    fireEvent.click(screen.getByRole("button", { name: /delete item/i }));
    await waitFor(() => expect(screen.queryByText("ephemeral")).toBeNull());
  });
});

// ---------------------------------------------------------------------------
// Error state
// ---------------------------------------------------------------------------
describe("StudyPanel — error state", () => {
  it("shows error message when fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("Network error"))));
    render(<StudyPanel />);
    await waitFor(() => screen.getByText(/network error/i));
  });

  it("shows Retry button on error", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("oops"))));
    render(<StudyPanel />);
    await waitFor(() => screen.getByRole("button", { name: /retry/i }));
  });
});

/**
 * E2E tests for the All Items tab (StudyPanel).
 *
 * Covers: list rendering, empty state, add-word form (success/duplicate/error),
 * part-of-speech select visibility, inline edit (open/cancel/save/error),
 * delete (success/error), load error + retry.
 *
 * Mock strategy: vi.stubGlobal("fetch", ...) with URL/method matching.
 * All tests render through <StudyPanel> and click the "All Items" tab button.
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

function makeItem(overrides: Partial<StudyItem> = {}): StudyItem {
  return {
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
    next_review_at: "2026-01-01T00:00:00",
    lexical_type: "adjective",
    ...overrides,
  };
}

const ITEM_1 = makeItem();
const ITEM_2 = makeItem({
  id: 2,
  item_type: "phrase",
  target_text: "in a nutshell",
  native_text: "вкратце",
  context_note: "",
  example_sentence: "",
  status: "learning",
  lexical_type: null,
});
const ITEM_PHRASAL = makeItem({
  id: 3,
  item_type: "phrasal_verb",
  target_text: "give up",
  native_text: "сдаваться",
  lexical_type: null,
  status: "review",
});

// ============================================================
// Fetch mock builder
// ============================================================

type FetchOptions = {
  items?: StudyItem[];
  patchResult?: Partial<StudyItem>;
  addResult?: { saved: number; skipped: number };
  failItems?: boolean;
  failPatch?: boolean;
  failDelete?: boolean;
};

function buildFetch({
  items = [ITEM_1] as StudyItem[],
  patchResult = { ...ITEM_1, native_text: "updated" } as Partial<StudyItem>,
  addResult = { saved: 1, skipped: 0 } as { saved: number; skipped: number },
  failItems = false,
  failPatch = false,
  failDelete = false,
}: FetchOptions = {}) {
  // Track whether items have been reloaded after add so the refreshed list is returned
  let reloadCount = 0;

  return vi.fn((url: string, init?: RequestInit) => {
    const u = String(url);
    const method = (init?.method ?? "GET").toUpperCase();

    // Training stats — needed if TrainingTab ever renders; safe to return empty
    if (u.includes("/training/")) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
    }

    if (method === "DELETE") {
      if (failDelete) {
        return Promise.resolve({
          ok: false, status: 500,
          json: () => Promise.resolve({ detail: "Delete failed" }),
        });
      }
      return Promise.resolve({ ok: true, status: 204, json: () => Promise.resolve(null) });
    }

    if (method === "PATCH") {
      if (failPatch) {
        return Promise.resolve({
          ok: false, status: 422,
          json: () => Promise.resolve({ detail: "Validation error" }),
        });
      }
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({ ...ITEM_1, ...patchResult }),
      });
    }

    if (u.includes("/api/study/items") && method === "POST") {
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve(addResult),
      });
    }

    if (u.includes("/api/study/items") && method === "GET") {
      if (failItems) {
        return Promise.resolve({
          ok: false, status: 503,
          json: () => Promise.resolve({ detail: "Service unavailable" }),
        });
      }
      reloadCount++;
      // On first load return items; on reload after add include a fresh item
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve(items),
      });
    }

    if (u.includes("/api/study/due")) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) });
    }

    if (u.includes("/api/study/stats")) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(STATS_EMPTY) });
    }

    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
  });
}

/** Helper: render StudyPanel and switch to All Items tab. */
async function openAllItems() {
  render(<StudyPanel />);
  fireEvent.click(screen.getByRole("button", { name: "All Items" }));
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
// 1. Basic rendering
// ============================================================

describe("All Items tab — basic rendering", () => {
  it("shows loading text while fetching", async () => {
    await openAllItems();
    // Loading appears briefly before items arrive
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("shows empty message when no items exist", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ items: [] }));
    await openAllItems();
    await waitFor(() =>
      expect(screen.getByText(/no items yet/i)).toBeInTheDocument(),
    );
  });

  it("lists item target text", async () => {
    await openAllItems();
    await waitFor(() => screen.getByText("ephemeral"));
  });

  it("shows native text in the row", async () => {
    await openAllItems();
    await waitFor(() => screen.getByText("мимолётный"));
  });

  it("shows item_type badge for word item", async () => {
    // ITEM_1 is a word with lexical_type=adjective → badge shows "adjective"
    await openAllItems();
    await waitFor(() => screen.getByText("adjective"));
  });

  it("shows item_type badge for phrase item (no lexical_type)", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ items: [ITEM_2] }));
    await openAllItems();
    await waitFor(() => screen.getByText("phrase"));
  });

  it("shows status badge", async () => {
    await openAllItems();
    await waitFor(() => screen.getByText("new"));
  });

  it("shows edit and delete buttons per item", async () => {
    await openAllItems();
    await waitFor(() => screen.getByRole("button", { name: /edit item/i }));
    expect(screen.getByRole("button", { name: /delete item/i })).toBeInTheDocument();
  });

  it("shows multiple items", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ items: [ITEM_1, ITEM_2] }));
    await openAllItems();
    await waitFor(() => screen.getByText("ephemeral"));
    expect(screen.getByText("in a nutshell")).toBeInTheDocument();
  });
});

// ============================================================
// 2. Add word form
// ============================================================

describe("All Items tab — Add word form", () => {
  async function openForm() {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ items: [] }));
    await openAllItems();
    await waitFor(() => screen.getByText(/no items yet/i));
    fireEvent.click(screen.getByRole("button", { name: /add word/i }));
    await waitFor(() => screen.getByLabelText("Word or phrase"));
  }

  it("toggle opens the form", async () => {
    await openForm();
    expect(screen.getByLabelText("Word or phrase")).toBeInTheDocument();
  });

  it("toggle closes the form on second click", async () => {
    await openForm();
    fireEvent.click(screen.getByRole("button", { name: /add word/i }));
    await waitFor(() =>
      expect(screen.queryByLabelText("Word or phrase")).toBeNull(),
    );
  });

  it("Save button disabled when target text is empty", async () => {
    await openForm();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });

  it("Save button disabled when target text is whitespace only", async () => {
    await openForm();
    fireEvent.change(screen.getByLabelText("Word or phrase"), { target: { value: "   " } });
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });

  it("shows Saving… state while POST is in flight", async () => {
    let resolve!: (v: unknown) => void;
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        const u = String(url);
        const method = (init?.method ?? "GET").toUpperCase();
        if (u.includes("/api/study/items") && method === "POST") {
          return new Promise((res) => { resolve = res; });
        }
        if (u.includes("/api/study/items")) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) });
        if (u.includes("/due"))   return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) });
        if (u.includes("/stats")) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(STATS_EMPTY) });
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
      }),
    );
    await openAllItems();
    await waitFor(() => screen.getByText(/no items yet/i));
    fireEvent.click(screen.getByRole("button", { name: /add word/i }));
    fireEvent.change(screen.getByLabelText("Word or phrase"), { target: { value: "serendipity" } });
    fireEvent.submit(screen.getByRole("button", { name: /^save$/i }).closest("form")!);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /saving/i })).toBeDisabled(),
    );
    // Unblock the pending request
    resolve({ ok: true, status: 200, json: () => Promise.resolve({ saved: 1, skipped: 0 }) });
  });

  it("shows 'Already in the list' when item is a duplicate", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ items: [], addResult: { saved: 0, skipped: 1 } }));
    await openAllItems();
    await waitFor(() => screen.getByText(/no items yet/i));
    fireEvent.click(screen.getByRole("button", { name: /add word/i }));
    fireEvent.change(screen.getByLabelText("Word or phrase"), { target: { value: "ephemeral" } });
    fireEvent.submit(screen.getByRole("button", { name: /^save$/i }).closest("form")!);
    await waitFor(() => screen.getByText(/already in the list/i));
  });

  it("shows error feedback when save API fails", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        const u = String(url);
        const method = (init?.method ?? "GET").toUpperCase();
        if (u.includes("/api/study/items") && method === "POST") {
          return Promise.resolve({
            ok: false, status: 500,
            json: () => Promise.resolve({ detail: "DB error" }),
          });
        }
        if (u.includes("/api/study/items")) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) });
        if (u.includes("/due"))   return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) });
        if (u.includes("/stats")) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(STATS_EMPTY) });
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
      }),
    );
    await openAllItems();
    await waitFor(() => screen.getByText(/no items yet/i));
    fireEvent.click(screen.getByRole("button", { name: /add word/i }));
    fireEvent.change(screen.getByLabelText("Word or phrase"), { target: { value: "test" } });
    fireEvent.submit(screen.getByRole("button", { name: /^save$/i }).closest("form")!);
    await waitFor(() => screen.getByText(/error/i));
  });

  it("shows Part of speech select for word item type", async () => {
    await openForm();
    // Default item_type is "word", so Part of speech should be visible
    expect(screen.getByLabelText("Part of speech")).toBeInTheDocument();
  });

  it("hides Part of speech select when item_type is phrasal_verb", async () => {
    await openForm();
    fireEvent.change(screen.getByLabelText("Item type"), { target: { value: "phrasal_verb" } });
    expect(screen.queryByLabelText("Part of speech")).toBeNull();
  });

  it("hides Part of speech select when item_type is idiom", async () => {
    await openForm();
    fireEvent.change(screen.getByLabelText("Item type"), { target: { value: "idiom" } });
    expect(screen.queryByLabelText("Part of speech")).toBeNull();
  });

  it("sends selected lexical_type in POST body", async () => {
    const fetchMock = buildFetch({ items: [], addResult: { saved: 1, skipped: 0 } });
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", fetchMock);

    await openAllItems();
    await waitFor(() => screen.getByText(/no items yet/i));
    fireEvent.click(screen.getByRole("button", { name: /add word/i }));
    fireEvent.change(screen.getByLabelText("Word or phrase"), { target: { value: "swift" } });
    fireEvent.change(screen.getByLabelText("Part of speech"), { target: { value: "adjective" } });
    fireEvent.submit(screen.getByRole("button", { name: /^save$/i }).closest("form")!);

    await waitFor(() => {
      const calls = (fetchMock as ReturnType<typeof vi.fn>).mock.calls;
      const postCall = calls.find(
        ([u, init]: [string, RequestInit]) =>
          String(u).includes("/api/study/items") && (init?.method ?? "GET") === "POST",
      );
      expect(postCall).toBeDefined();
      const body = JSON.parse(postCall![1].body as string);
      expect(body.items[0].lexical_type).toBe("adjective");
    });
  });

  it("reloads the item list after successful add", async () => {
    let getCallCount = 0;
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        const u = String(url);
        const method = (init?.method ?? "GET").toUpperCase();
        if (u.includes("/api/study/items") && method === "POST") {
          return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ saved: 1, skipped: 0 }) });
        }
        if (u.includes("/api/study/items") && method === "GET") {
          getCallCount++;
          const result = getCallCount >= 2 ? [ITEM_1] : [];
          return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(result) });
        }
        if (u.includes("/due"))   return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) });
        if (u.includes("/stats")) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(STATS_EMPTY) });
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
      }),
    );

    await openAllItems();
    await waitFor(() => screen.getByText(/no items yet/i));
    fireEvent.click(screen.getByRole("button", { name: /add word/i }));
    fireEvent.change(screen.getByLabelText("Word or phrase"), { target: { value: "ephemeral" } });
    fireEvent.submit(screen.getByRole("button", { name: /^save$/i }).closest("form")!);
    await waitFor(() => screen.getByText("ephemeral"));
  });
});

// ============================================================
// 3. Inline edit form
// ============================================================

describe("All Items tab — inline edit form", () => {
  it("opens inline edit form on Edit button click", async () => {
    await openAllItems();
    await waitFor(() => screen.getByRole("button", { name: /edit item/i }));
    fireEvent.click(screen.getByRole("button", { name: /edit item/i }));
    expect(screen.getByLabelText("Target text")).toBeInTheDocument();
  });

  it("edit form pre-fills target text", async () => {
    await openAllItems();
    await waitFor(() => screen.getByRole("button", { name: /edit item/i }));
    fireEvent.click(screen.getByRole("button", { name: /edit item/i }));
    const input = screen.getByLabelText("Target text") as HTMLInputElement;
    expect(input.value).toBe("ephemeral");
  });

  it("edit form pre-fills translation", async () => {
    await openAllItems();
    await waitFor(() => screen.getByRole("button", { name: /edit item/i }));
    fireEvent.click(screen.getByRole("button", { name: /edit item/i }));
    const input = screen.getByLabelText("Translation") as HTMLInputElement;
    expect(input.value).toBe("мимолётный");
  });

  it("edit form shows Cancel button", async () => {
    await openAllItems();
    await waitFor(() => screen.getByRole("button", { name: /edit item/i }));
    fireEvent.click(screen.getByRole("button", { name: /edit item/i }));
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
  });

  it("Cancel closes the edit form without saving", async () => {
    await openAllItems();
    await waitFor(() => screen.getByRole("button", { name: /edit item/i }));
    fireEvent.click(screen.getByRole("button", { name: /edit item/i }));
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    await waitFor(() =>
      expect(screen.queryByLabelText("Target text")).toBeNull(),
    );
    // Original item still visible
    expect(screen.getByText("ephemeral")).toBeInTheDocument();
  });

  it("saves edit and updates the row in-place", async () => {
    await openAllItems();
    await waitFor(() => screen.getByRole("button", { name: /edit item/i }));
    fireEvent.click(screen.getByRole("button", { name: /edit item/i }));
    const input = screen.getByLabelText("Target text");
    fireEvent.change(input, { target: { value: "ephemeral_v2" } });
    fireEvent.submit(input.closest("form")!);
    // patchResult native_text="updated" from buildFetch default
    await waitFor(() => screen.getByText("updated"));
    expect(screen.queryByLabelText("Target text")).toBeNull();
  });

  it("shows error message when PATCH fails", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ failPatch: true }));
    await openAllItems();
    await waitFor(() => screen.getByRole("button", { name: /edit item/i }));
    fireEvent.click(screen.getByRole("button", { name: /edit item/i }));
    const input = screen.getByLabelText("Target text");
    fireEvent.submit(input.closest("form")!);
    await waitFor(() =>
      expect(screen.getByText(/validation error/i)).toBeInTheDocument(),
    );
  });

  it("Part of speech select hidden in edit form for non-word item_type", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ items: [ITEM_PHRASAL] }));
    await openAllItems();
    await waitFor(() => screen.getByRole("button", { name: /edit item/i }));
    fireEvent.click(screen.getByRole("button", { name: /edit item/i }));
    expect(screen.queryByLabelText("Part of speech")).toBeNull();
  });

  it("Part of speech select shown in edit form for word item_type", async () => {
    await openAllItems();
    await waitFor(() => screen.getByRole("button", { name: /edit item/i }));
    fireEvent.click(screen.getByRole("button", { name: /edit item/i }));
    expect(screen.getByLabelText("Part of speech")).toBeInTheDocument();
  });

  it("sends correct PATCH body with updated fields", async () => {
    const fetchMock = buildFetch();
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", fetchMock);

    await openAllItems();
    await waitFor(() => screen.getByRole("button", { name: /edit item/i }));
    fireEvent.click(screen.getByRole("button", { name: /edit item/i }));
    fireEvent.change(screen.getByLabelText("Target text"), { target: { value: "ethereal" } });
    fireEvent.change(screen.getByLabelText("Translation"), { target: { value: "эфирный" } });
    fireEvent.submit(screen.getByLabelText("Target text").closest("form")!);

    await waitFor(() => {
      const calls = (fetchMock as ReturnType<typeof vi.fn>).mock.calls;
      const patchCall = calls.find(
        ([, init]: [string, RequestInit]) =>
          (init?.method ?? "GET").toUpperCase() === "PATCH",
      );
      expect(patchCall).toBeDefined();
      const body = JSON.parse(patchCall![1].body as string);
      expect(body.target_text).toBe("ethereal");
      expect(body.native_text).toBe("эфирный");
    });
  });
});

// ============================================================
// 4. Delete
// ============================================================

describe("All Items tab — delete", () => {
  it("removes item from the list after successful delete", async () => {
    await openAllItems();
    await waitFor(() => screen.getByText("ephemeral"));
    fireEvent.click(screen.getByRole("button", { name: /delete item/i }));
    await waitFor(() =>
      expect(screen.queryByText("ephemeral")).toBeNull(),
    );
  });

  it("shows empty message after deleting the only item", async () => {
    await openAllItems();
    await waitFor(() => screen.getByText("ephemeral"));
    fireEvent.click(screen.getByRole("button", { name: /delete item/i }));
    await waitFor(() =>
      expect(screen.getByText(/no items yet/i)).toBeInTheDocument(),
    );
  });

  it("only removes the clicked item when multiple items exist", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ items: [ITEM_1, ITEM_2] }));
    await openAllItems();
    await waitFor(() => screen.getByText("ephemeral"));
    const deleteButtons = screen.getAllByRole("button", { name: /delete item/i });
    fireEvent.click(deleteButtons[0]);
    await waitFor(() =>
      expect(screen.queryByText("ephemeral")).toBeNull(),
    );
    expect(screen.getByText("in a nutshell")).toBeInTheDocument();
  });

  it("shows error message when delete fails", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ failDelete: true }));
    await openAllItems();
    await waitFor(() => screen.getByText("ephemeral"));
    fireEvent.click(screen.getByRole("button", { name: /delete item/i }));
    await waitFor(() =>
      expect(screen.getByText(/delete failed/i)).toBeInTheDocument(),
    );
  });

  it("keeps item in list when delete fails", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ failDelete: true }));
    await openAllItems();
    await waitFor(() => screen.getByText("ephemeral"));
    fireEvent.click(screen.getByRole("button", { name: /delete item/i }));
    await waitFor(() => screen.getByText(/delete failed/i));
    expect(screen.getByText("ephemeral")).toBeInTheDocument();
  });
});

// ============================================================
// 5. Load error & retry
// ============================================================

describe("All Items tab — load error & retry", () => {
  it("shows error banner when items fetch fails", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ failItems: true }));
    await openAllItems();
    await waitFor(() =>
      expect(screen.getByText(/service unavailable/i)).toBeInTheDocument(),
    );
  });

  it("shows Retry button on load failure", async () => {
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", buildFetch({ failItems: true }));
    await openAllItems();
    await waitFor(() => screen.getByRole("button", { name: /retry/i }));
  });

  it("reloads items after clicking Retry", async () => {
    let attempt = 0;
    vi.unstubAllGlobals();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        const u = String(url);
        const method = (init?.method ?? "GET").toUpperCase();
        if (u.includes("/api/study/items") && method === "GET") {
          attempt++;
          if (attempt === 1) {
            return Promise.resolve({
              ok: false, status: 503,
              json: () => Promise.resolve({ detail: "Service unavailable" }),
            });
          }
          return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([ITEM_1]) });
        }
        if (u.includes("/due"))   return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) });
        if (u.includes("/stats")) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(STATS_EMPTY) });
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
      }),
    );

    await openAllItems();
    await waitFor(() => screen.getByRole("button", { name: /retry/i }));
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => screen.getByText("ephemeral"));
  });
});

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { TrainingTab } from "./study/TrainingTab";

const STUDY_API = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000") + "/api/study";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
export type StudyItem = {
  id: number;
  item_type: "word" | "phrase" | "phrasal_verb" | "idiom" | "collocation";
  target_text: string;
  native_text: string;
  context_note: string;
  example_sentence: string;
  status: "new" | "learning" | "review" | "mastered" | "difficult" | "suspended";
  ease: number;
  interval_days: number;
  repetitions: number;
  lapses: number;
  next_review_at: string;
  // Extended fields (added by training migration)
  lexical_type?: string | null;
  alternative_translations?: string;
  topic?: string;
  difficulty_level?: number | null;
  tags?: string;
  example_sentence_native?: string;
};

export type StudyStats = {
  new: number;
  learning: number;
  review: number;
  mastered: number;
  difficult: number;
  suspended: number;
  due: number;
  total_items: number;
  total_reviews: number;
};

type Rating = "again" | "hard" | "good" | "easy";
type ItemType = "word" | "phrase" | "phrasal_verb" | "idiom" | "collocation";
type ItemStatus = "new" | "learning" | "review" | "mastered" | "difficult" | "suspended";

const LEXICAL_TYPE_OPTIONS = [
  { value: "",              label: "— Part of speech —" },
  { value: "noun",         label: "Noun" },
  { value: "verb",         label: "Verb" },
  { value: "adjective",    label: "Adjective" },
  { value: "adverb",       label: "Adverb" },
  { value: "phrasal_verb", label: "Phrasal verb" },
  { value: "idiom",        label: "Idiom" },
  { value: "collocation",  label: "Collocation" },
  { value: "modal_verb",   label: "Modal verb" },
  { value: "pronoun",      label: "Pronoun" },
  { value: "preposition",  label: "Preposition" },
];

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------
async function apiFetch<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const r = await fetch(input, init);
  if (!r.ok) {
    const detail = await r.json().then((d: { detail?: string }) => d.detail).catch(() => r.statusText);
    throw new Error(String(detail));
  }
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}

const api = {
  due: () => apiFetch<StudyItem[]>(`${STUDY_API}/due?limit=50`),
  stats: () => apiFetch<StudyStats>(`${STUDY_API}/stats`),
  items: (limit = 100, offset = 0) =>
    apiFetch<StudyItem[]>(`${STUDY_API}/items?limit=${limit}&offset=${offset}`),
  review: (id: number, rating: Rating) =>
    apiFetch<StudyItem>(`${STUDY_API}/review/${id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating }),
    }),
  add: (targetText: string, nativeText: string, itemType: ItemType, lexicalType?: string) =>
    apiFetch<{ saved: number; skipped: number }>(`${STUDY_API}/items`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        items: [{ item_type: itemType, target_text: targetText, native_text: nativeText, lexical_type: lexicalType || null }],
      }),
    }),
  update: (id: number, patch: Partial<Pick<StudyItem, "item_type" | "target_text" | "native_text" | "context_note" | "example_sentence" | "status" | "lexical_type">>) =>
    apiFetch<StudyItem>(`${STUDY_API}/items/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  delete: (id: number) =>
    apiFetch<void>(`${STUDY_API}/items/${id}`, { method: "DELETE" }),
};

// ---------------------------------------------------------------------------
// Review state machine
// ---------------------------------------------------------------------------
type ReviewState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "empty"; stats: StudyStats }
  | { phase: "front"; card: StudyItem; queue: StudyItem[]; stats: StudyStats }
  | { phase: "back"; card: StudyItem; queue: StudyItem[]; stats: StudyStats }
  | { phase: "submitting"; card: StudyItem; queue: StudyItem[]; stats: StudyStats; rating: Rating };

type ReviewAction =
  | { type: "LOADED"; queue: StudyItem[]; stats: StudyStats }
  | { type: "ERROR"; message: string }
  | { type: "FLIP" }
  | { type: "SUBMIT"; rating: Rating }
  | { type: "ADVANCED"; updatedItem: StudyItem; nextQueue: StudyItem[]; stats: StudyStats }
  | { type: "RELOAD" }
  | { type: "STATS_REFRESHED"; stats: StudyStats };

function reviewReducer(state: ReviewState, action: ReviewAction): ReviewState {
  switch (action.type) {
    case "LOADED":
      if (action.queue.length === 0) return { phase: "empty", stats: action.stats };
      return { phase: "front", card: action.queue[0], queue: action.queue.slice(1), stats: action.stats };
    case "ERROR":
      return { phase: "error", message: action.message };
    case "FLIP":
      if (state.phase !== "front") return state;
      return { phase: "back", card: state.card, queue: state.queue, stats: state.stats };
    case "SUBMIT":
      if (state.phase !== "back") return state;
      return { phase: "submitting", card: state.card, queue: state.queue, stats: state.stats, rating: action.rating };
    case "ADVANCED": {
      if (state.phase !== "submitting") return state;
      const next = action.nextQueue[0];
      if (!next) return { phase: "empty", stats: action.stats };
      return { phase: "front", card: next, queue: action.nextQueue.slice(1), stats: action.stats };
    }
    case "RELOAD":
      return { phase: "loading" };
    case "STATS_REFRESHED":
      if (state.phase === "loading" || state.phase === "error") return state;
      return { ...state, stats: action.stats };
    default:
      return state;
  }
}

// ---------------------------------------------------------------------------
// AddWordForm
// ---------------------------------------------------------------------------
type AddWordFormProps = { onSaved: () => void };

function AddWordForm({ onSaved }: AddWordFormProps) {
  const [open, setOpen] = useState(false);
  const [targetText, setTargetText] = useState("");
  const [nativeText, setNativeText] = useState("");
  const [itemType, setItemType] = useState<ItemType>("word");
  const [lexicalType, setLexicalType] = useState("");
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "dupe" | "error">("idle");
  const inputRef = useRef<HTMLInputElement>(null);

  const toggle = () => {
    if (open) { setTargetText(""); setNativeText(""); setItemType("word"); setLexicalType(""); setStatus("idle"); }
    setOpen((v) => !v);
    if (!open) setTimeout(() => inputRef.current?.focus(), 50);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = targetText.trim();
    if (!text) return;
    setStatus("saving");
    try {
      const result = await api.add(text, nativeText.trim(), itemType, lexicalType || undefined);
      if (result.skipped > 0 && result.saved === 0) {
        setStatus("dupe");
      } else {
        setStatus("saved");
        setTargetText("");
        setNativeText("");
        onSaved();
        setTimeout(() => { setStatus("idle"); inputRef.current?.focus(); }, 1500);
      }
    } catch {
      setStatus("error");
    }
  };

  return (
    <div className="study-add-wrap">
      <button type="button" className="study-add-toggle" onClick={toggle} aria-expanded={open}>
        <span className="study-add-toggle__icon" aria-hidden="true">{open ? "−" : "+"}</span>
        Add word
      </button>
      {open && (
        <form className="study-add-form" onSubmit={(e) => void handleSubmit(e)}>
          <input ref={inputRef} aria-label="Word or phrase" className="study-add-input" type="text"
            placeholder="Word or phrase…" value={targetText} required
            onChange={(e) => { setTargetText(e.target.value); setStatus("idle"); }} />
          <input aria-label="Translation" className="study-add-input" type="text"
            placeholder="Translation (optional)" value={nativeText}
            onChange={(e) => setNativeText(e.target.value)} />
          <div className="study-add-row">
            <select aria-label="Item type" className="study-add-select" value={itemType}
              onChange={(e) => setItemType(e.target.value as ItemType)}>
              <option value="word">word</option>
              <option value="phrase">phrase</option>
              <option value="phrasal_verb">phrasal verb</option>
              <option value="idiom">idiom</option>
              <option value="collocation">collocation</option>
            </select>
            <select aria-label="Part of speech" className="study-add-select" value={lexicalType}
              onChange={(e) => setLexicalType(e.target.value)}>
              {LEXICAL_TYPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <button type="submit" className="primary-button study-add-submit"
              disabled={status === "saving" || !targetText.trim()}>
              {status === "saving" ? "Saving…" : "Save"}
            </button>
          </div>
          {status === "saved" && <p className="study-add-feedback study-add-feedback--ok">Saved!</p>}
          {status === "dupe"  && <p className="study-add-feedback study-add-feedback--warn">Already in the list.</p>}
          {status === "error" && <p className="study-add-feedback study-add-feedback--err">Error — is the backend running?</p>}
        </form>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// EditItemForm (inline)
// ---------------------------------------------------------------------------
type EditItemFormProps = {
  item: StudyItem;
  onSaved: (updated: StudyItem) => void;
  onCancel: () => void;
};

function EditItemForm({ item, onSaved, onCancel }: EditItemFormProps) {
  const [targetText, setTargetText] = useState(item.target_text);
  const [nativeText, setNativeText] = useState(item.native_text);
  const [contextNote, setContextNote] = useState(item.context_note);
  const [exampleSentence, setExampleSentence] = useState(item.example_sentence);
  const [itemType, setItemType] = useState<ItemType>(item.item_type);
  const [lexicalType, setLexicalType] = useState(item.lexical_type ?? "");
  const [status, setStatus] = useState<ItemStatus>(item.status);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetText.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.update(item.id, {
        target_text: targetText.trim(),
        native_text: nativeText.trim(),
        context_note: contextNote.trim(),
        example_sentence: exampleSentence.trim(),
        item_type: itemType,
        lexical_type: lexicalType || null,
        status,
      });
      onSaved(updated);
    } catch (err) {
      setError(String(err));
      setSaving(false);
    }
  };

  return (
    <form className="study-edit-form" onSubmit={(e) => void handleSubmit(e)}>
      <div className="study-edit-row">
        <input aria-label="Target text" className="study-add-input study-edit-input--target"
          type="text" value={targetText} required
          onChange={(e) => setTargetText(e.target.value)} />
        <select aria-label="Item type" className="study-add-select"
          value={itemType} onChange={(e) => setItemType(e.target.value as ItemType)}>
          <option value="word">word</option>
          <option value="phrase">phrase</option>
          <option value="phrasal_verb">phrasal verb</option>
          <option value="idiom">idiom</option>
          <option value="collocation">collocation</option>
        </select>
        <select aria-label="Part of speech" className="study-add-select"
          value={lexicalType} onChange={(e) => setLexicalType(e.target.value)}>
          {LEXICAL_TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>
      <input aria-label="Translation" className="study-add-input" type="text"
        placeholder="Translation" value={nativeText}
        onChange={(e) => setNativeText(e.target.value)} />
      <input aria-label="Context note" className="study-add-input" type="text"
        placeholder="Context note" value={contextNote}
        onChange={(e) => setContextNote(e.target.value)} />
      <input aria-label="Example sentence" className="study-add-input" type="text"
        placeholder="Example sentence" value={exampleSentence}
        onChange={(e) => setExampleSentence(e.target.value)} />
      <div className="study-edit-row">
        <select aria-label="Status" className="study-add-select"
          value={status} onChange={(e) => setStatus(e.target.value as ItemStatus)}>
          <option value="new">new</option>
          <option value="learning">learning</option>
          <option value="review">review</option>
          <option value="mastered">mastered</option>
          <option value="difficult">difficult</option>
          <option value="suspended">suspended</option>
        </select>
        <div className="study-edit-actions">
          <button type="submit" className="primary-button study-add-submit" disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
          <button type="button" className="secondary-button study-add-submit" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
      {error && <p className="study-add-feedback study-add-feedback--err">{error}</p>}
    </form>
  );
}

// ---------------------------------------------------------------------------
// ItemRow
// ---------------------------------------------------------------------------
type ItemRowProps = {
  item: StudyItem;
  onUpdated: (updated: StudyItem) => void;
  onDeleted: (id: number) => void;
};

function ItemRow({ item, onUpdated, onDeleted }: ItemRowProps) {
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const handleDelete = async () => {
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.delete(item.id);
      onDeleted(item.id);
    } catch (err) {
      setDeleteError(String(err));
      setDeleting(false);
    }
  };

  return (
    <li className="study-item-row">
      {!editing ? (
        <div className="study-item-row__summary">
          <span className="study-item-row__target">{item.target_text}</span>
          {item.native_text && <span className="study-item-row__native">{item.native_text}</span>}
          <div className="study-item-row__badges">
            <span className={`study-badge study-badge--type`}>{item.item_type}</span>
            <span className={`study-badge study-badge--${item.status}`}>{item.status}</span>
          </div>
          <div className="study-item-row__btns">
            <button type="button" className="study-icon-btn" aria-label="Edit item"
              onClick={() => setEditing(true)}>✎</button>
            <button type="button" className="study-icon-btn study-icon-btn--danger"
              aria-label="Delete item" onClick={() => void handleDelete()}
              disabled={deleting}>
              {deleting ? "…" : "✕"}
            </button>
          </div>
        </div>
      ) : (
        <EditItemForm
          item={item}
          onSaved={(updated) => { onUpdated(updated); setEditing(false); }}
          onCancel={() => setEditing(false)}
        />
      )}
      {deleteError && <p className="study-add-feedback study-add-feedback--err">{deleteError}</p>}
    </li>
  );
}

// ---------------------------------------------------------------------------
// AllItemsView
// ---------------------------------------------------------------------------
type AllItemsViewProps = { onStatsChange: () => void };

function AllItemsView({ onStatsChange }: AllItemsViewProps) {
  const [items, setItems] = useState<StudyItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.items();
      setItems(data);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const handleUpdated = (updated: StudyItem) => {
    setItems((prev) => prev.map((it) => (it.id === updated.id ? updated : it)));
    onStatsChange();
  };

  const handleDeleted = (id: number) => {
    setItems((prev) => prev.filter((it) => it.id !== id));
    onStatsChange();
  };

  const handleAdded = () => {
    void load();
    onStatsChange();
  };

  if (loading) return <p className="study-empty-text">Loading…</p>;
  if (error) return (
    <>
      <p className="error-banner">{error}</p>
      <button type="button" className="secondary-button" onClick={() => void load()}>Retry</button>
    </>
  );

  return (
    <>
      <AddWordForm onSaved={handleAdded} />
      {items.length === 0 ? (
        <p className="study-empty-text">No items yet. Add your first word above.</p>
      ) : (
        <ul className="study-item-list">
          {items.map((item) => (
            <ItemRow key={item.id} item={item} onUpdated={handleUpdated} onDeleted={handleDeleted} />
          ))}
        </ul>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// ReviewView
// ---------------------------------------------------------------------------
type ReviewViewProps = { onStatsChange: () => void };

function ReviewView({ onStatsChange }: ReviewViewProps) {
  const [state, dispatch] = useReducer(reviewReducer, { phase: "loading" });

  const load = useCallback(async () => {
    dispatch({ type: "RELOAD" });
    try {
      const [queue, stats] = await Promise.all([api.due(), api.stats()]);
      dispatch({ type: "LOADED", queue, stats });
    } catch (err) {
      dispatch({ type: "ERROR", message: String(err) });
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const refreshStats = useCallback(async () => {
    try {
      const stats = await api.stats();
      dispatch({ type: "STATS_REFRESHED", stats });
      onStatsChange();
    } catch { /* non-critical */ }
  }, [onStatsChange]);

  useEffect(() => {
    if (state.phase !== "submitting") return;
    const { card, queue, rating } = state;
    let cancelled = false;
    void (async () => {
      try {
        const [updatedItem, stats] = await Promise.all([api.review(card.id, rating), api.stats()]);
        if (!cancelled) dispatch({ type: "ADVANCED", updatedItem, nextQueue: queue, stats });
      } catch (err) {
        if (!cancelled) dispatch({ type: "ERROR", message: String(err) });
      }
    })();
    return () => { cancelled = true; };
  }, [state]);

  const renderStats = (stats: StudyStats) => (
    <div className="study-stats">
      <span className="study-stat study-stat--new">{stats.new} new</span>
      <span className="study-stat study-stat--learning">{stats.learning} learning</span>
      <span className="study-stat study-stat--review">{stats.review} review</span>
      <span className="study-stat study-stat--due">{stats.due} due</span>
    </div>
  );

  const renderRatings = (card: StudyItem) => (
    <div className="study-rating-row">
      {(["again", "hard", "good", "easy"] as Rating[]).map((r) => (
        <button key={r} type="button" className={`study-rating-btn study-rating-btn--${r}`}
          onClick={() => dispatch({ type: "SUBMIT", rating: r })}>
          {r.charAt(0).toUpperCase() + r.slice(1)}
        </button>
      ))}
      <span className="study-card__meta">{card.item_type} · rep {card.repetitions}</span>
    </div>
  );

  if (state.phase === "loading") return <p className="study-empty-text">Loading…</p>;

  if (state.phase === "error") return (
    <>
      <p className="error-banner">{state.message}</p>
      <button type="button" className="secondary-button" onClick={() => void load()}>Retry</button>
    </>
  );

  if (state.phase === "empty") return (
    <>
      {renderStats(state.stats)}
      <AddWordForm onSaved={refreshStats} />
      <div className="study-empty">
        <svg className="study-empty__icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        <p className="study-empty-text">All caught up! No items due right now.</p>
        <button type="button" className="secondary-button" onClick={() => void load()}>Refresh</button>
      </div>
    </>
  );

  const { card, stats } = state;

  if (state.phase === "front") return (
    <>
      {renderStats(stats)}
      <AddWordForm onSaved={refreshStats} />
      <div className="study-card study-card--front">
        <p className="study-card__type">{card.item_type}</p>
        <p className="study-card__target">{card.target_text}</p>
        <button type="button" className="primary-button study-flip-btn"
          onClick={() => dispatch({ type: "FLIP" })}>Show Answer</button>
      </div>
    </>
  );

  if (state.phase === "back") return (
    <>
      {renderStats(stats)}
      <AddWordForm onSaved={refreshStats} />
      <div className="study-card study-card--back">
        <p className="study-card__type">{card.item_type}</p>
        <p className="study-card__target">{card.target_text}</p>
        <div className="study-card__divider" />
        {card.native_text && <p className="study-card__native">{card.native_text}</p>}
        {card.context_note && <p className="study-card__note">{card.context_note}</p>}
        {card.example_sentence && <p className="study-card__example"><em>{card.example_sentence}</em></p>}
      </div>
      {renderRatings(card)}
    </>
  );

  // submitting
  return (
    <>
      {renderStats(stats)}
      <div className="study-card study-card--submitting">
        <p className="study-card__target">{card.target_text}</p>
        <p className="study-empty-text">Saving…</p>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// StudyPanel (tabs)
// ---------------------------------------------------------------------------
type Tab = "review" | "items" | "training";

export function StudyPanel() {
  const [tab, setTab] = useState<Tab>("review");
  const [statsVersion, setStatsVersion] = useState(0);

  const bumpStats = useCallback(() => setStatsVersion((v) => v + 1), []);

  return (
    <article className="panel-card study-panel">
      <p className="panel-title">Vocabulary Review</p>

      <div className="study-tabs">
        <button
          type="button"
          className={`study-tab${tab === "review" ? " study-tab--active" : ""}`}
          onClick={() => setTab("review")}
        >
          Review
        </button>
        <button
          type="button"
          className={`study-tab${tab === "items" ? " study-tab--active" : ""}`}
          onClick={() => setTab("items")}
        >
          All Items
        </button>
        <button
          type="button"
          className={`study-tab${tab === "training" ? " study-tab--active" : ""}`}
          onClick={() => setTab("training")}
        >
          Training
        </button>
      </div>

      {tab === "review" && <ReviewView key={`review-${statsVersion}`} onStatsChange={bumpStats} />}
      {tab === "items" && <AllItemsView onStatsChange={bumpStats} />}
      {tab === "training" && <TrainingTab />}
    </article>
  );
}

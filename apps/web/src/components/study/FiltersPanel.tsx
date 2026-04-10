import type { ExtendedItemType, LexicalType, SessionFilters, SessionMode } from "./types";

type Props = {
  mode: SessionMode;
  filters: SessionFilters;
  targetCount: number;
  onChange: (mode: SessionMode, filters: SessionFilters, targetCount: number) => void;
};

const MODES: { value: SessionMode; label: string }[] = [
  { value: "auto", label: "Auto (mixed)" },
  { value: "new_only", label: "New only" },
  { value: "difficult", label: "Difficult" },
  { value: "overdue", label: "Overdue" },
  { value: "errors", label: "Errors" },
  { value: "by_type", label: "By type" },
];

const ITEM_TYPES: { value: ExtendedItemType | ""; label: string }[] = [
  { value: "", label: "All types" },
  { value: "word", label: "Words" },
  { value: "phrase", label: "Phrases" },
  { value: "phrasal_verb", label: "Phrasal verbs" },
  { value: "idiom", label: "Idioms" },
  { value: "collocation", label: "Collocations" },
];

const LEXICAL_TYPES: { value: LexicalType | ""; label: string }[] = [
  { value: "", label: "All parts of speech" },
  { value: "noun", label: "Noun" },
  { value: "verb", label: "Verb" },
  { value: "adjective", label: "Adjective" },
  { value: "adverb", label: "Adverb" },
  { value: "phrasal_verb", label: "Phrasal verb" },
  { value: "idiom", label: "Idiom" },
  { value: "collocation", label: "Collocation" },
  { value: "modal_verb", label: "Modal verb" },
  { value: "pronoun", label: "Pronoun" },
  { value: "preposition", label: "Preposition" },
];

export function FiltersPanel({ mode, filters, targetCount, onChange }: Props) {
  function update(partial: Partial<SessionFilters>) {
    onChange(mode, { ...filters, ...partial }, targetCount);
  }

  function setMode(m: SessionMode) {
    onChange(m, filters, targetCount);
  }

  function setCount(n: number) {
    onChange(mode, filters, n);
  }

  return (
    <div className="filters-panel">
      {/* Mode */}
      <div className="filters-row">
        <label className="filters-label">Mode</label>
        <div className="filters-mode-group">
          {MODES.map((m) => (
            <button
              key={m.value}
              className={`filters-mode-btn${mode === m.value ? " filters-mode-btn--active" : ""}`}
              onClick={() => setMode(m.value)}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {/* Item type */}
      <div className="filters-row">
        <label className="filters-label">Item type</label>
        <select
          className="filters-select"
          value={filters.item_type ?? ""}
          onChange={(e) => update({ item_type: (e.target.value as ExtendedItemType) || undefined })}
        >
          {ITEM_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
      </div>

      {/* Lexical type */}
      <div className="filters-row">
        <label className="filters-label">Part of speech</label>
        <select
          className="filters-select"
          value={filters.lexical_type ?? ""}
          onChange={(e) => update({ lexical_type: (e.target.value as LexicalType) || undefined })}
        >
          {LEXICAL_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
      </div>

      {/* Topic */}
      <div className="filters-row">
        <label className="filters-label">Topic</label>
        <input
          className="filters-input"
          type="text"
          value={filters.topic ?? ""}
          onChange={(e) => update({ topic: e.target.value || undefined })}
          placeholder="Any topic"
        />
      </div>

      {/* Card count */}
      <div className="filters-row">
        <label className="filters-label">Cards</label>
        <input
          className="filters-input filters-input--number"
          type="number"
          min={1}
          max={100}
          value={targetCount}
          onChange={(e) => setCount(Math.max(1, Math.min(100, Number(e.target.value))))}
        />
      </div>
    </div>
  );
}

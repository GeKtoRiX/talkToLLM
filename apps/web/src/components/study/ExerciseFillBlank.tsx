import { useState } from "react";
import type { SessionQuestion } from "./types";

type Props = {
  question: SessionQuestion;
  onSubmit: (answer: string) => void;
  disabled?: boolean;
};

export function ExerciseFillBlank({ question, onSubmit, disabled }: Props) {
  const [value, setValue] = useState("");

  function handleSubmit() {
    if (disabled || !value.trim()) return;
    onSubmit(value.trim());
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") handleSubmit();
  }

  return (
    <div className="exercise exercise--fill">
      <p className="exercise__label">Fill in the blank:</p>
      <p className="exercise__prompt exercise__prompt--sentence">{question.prompt_text}</p>
      <div className="exercise__input-row">
        <input
          className="exercise__text-input"
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          autoFocus
          placeholder="Type the missing word…"
          autoComplete="off"
          spellCheck={false}
        />
        <button
          className="exercise__submit-btn"
          onClick={handleSubmit}
          disabled={disabled || !value.trim()}
        >
          Submit
        </button>
      </div>
    </div>
  );
}

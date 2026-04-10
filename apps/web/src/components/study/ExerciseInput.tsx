import { useRef, useState } from "react";
import type { SessionQuestion } from "./types";

type Props = {
  question: SessionQuestion;
  onSubmit: (answer: string) => void;
  disabled?: boolean;
};

export function ExerciseInput({ question, onSubmit, disabled }: Props) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  function handleSubmit() {
    if (disabled || !value.trim()) return;
    onSubmit(value.trim());
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") handleSubmit();
  }

  return (
    <div className="exercise exercise--input">
      <p className="exercise__label">Type the English word or phrase:</p>
      <p className="exercise__prompt">{question.prompt_text}</p>
      <div className="exercise__input-row">
        <input
          ref={inputRef}
          className="exercise__text-input"
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          autoFocus
          placeholder="Type your answer…"
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

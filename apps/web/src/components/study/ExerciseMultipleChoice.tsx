import { useMemo, useState } from "react";
import type { SessionQuestion } from "./types";

type Props = {
  question: SessionQuestion;
  onSubmit: (answer: string) => void;
  disabled?: boolean;
};

/** Seeded shuffle — stable across renders for the same question */
function shuffleOptions(options: string[], seed: number): string[] {
  const arr = [...options];
  let s = seed;
  for (let i = arr.length - 1; i > 0; i--) {
    s = (s * 1664525 + 1013904223) & 0xffffffff;
    const j = Math.abs(s) % (i + 1);
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

export function ExerciseMultipleChoice({ question, onSubmit, disabled }: Props) {
  const [selected, setSelected] = useState<string | null>(null);

  const options = useMemo(() => {
    let distractors: string[] = [];
    try {
      distractors = JSON.parse(question.distractors_json) as string[];
    } catch {
      distractors = [];
    }
    const all = [question.correct_answer, ...distractors.slice(0, 3)];
    return shuffleOptions(all, question.id);
  }, [question.id, question.correct_answer, question.distractors_json]);

  function handleClick(opt: string) {
    if (disabled || selected !== null) return;
    setSelected(opt);
    onSubmit(opt);
  }

  return (
    <div className="exercise exercise--mc">
      <p className="exercise__prompt">{question.prompt_text}</p>
      <div className="exercise__options">
        {options.map((opt) => (
          <button
            key={opt}
            className={`exercise__option${selected === opt ? " exercise__option--selected" : ""}`}
            onClick={() => handleClick(opt)}
            disabled={disabled || selected !== null}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  );
}

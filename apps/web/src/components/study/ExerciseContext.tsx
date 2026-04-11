import { useMemo, useState } from "react";
import type { AnswerResult, SessionQuestion } from "./types";

type Props = {
  question: SessionQuestion;
  onSubmit: (answer: string) => void;
  disabled?: boolean;
  result?: AnswerResult;
};

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

export function ExerciseContext({ question, onSubmit, disabled, result }: Props) {
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

  function getOptionClass(opt: string): string {
    let cls = "exercise__option";
    if (result) {
      if (opt === question.correct_answer) {
        cls += " exercise__option--correct";
      } else if (opt === selected) {
        cls += " exercise__option--wrong";
      } else {
        cls += " exercise__option--inactive";
      }
    } else if (selected === opt) {
      cls += " exercise__option--selected";
    }
    return cls;
  }

  return (
    <div className="exercise exercise--context">
      <p className="exercise__label">Choose the correct translation for the context:</p>
      <p className="exercise__prompt exercise__prompt--sentence">{question.prompt_text}</p>
      <div className="exercise__options">
        {options.map((opt) => (
          <button
            key={opt}
            className={getOptionClass(opt)}
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

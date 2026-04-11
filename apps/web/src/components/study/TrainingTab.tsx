import { useReducer, useRef } from "react";
import type {
  AnswerResult,
  SessionFilters,
  SessionMode,
  SessionQuestion,
  SessionResults,
  TrainingSession,
} from "./types";
import { trainingApi } from "./api";
import { FiltersPanel } from "./FiltersPanel";
import { SessionView } from "./SessionView";
import { SessionResultsView } from "./SessionResults";
import { ProgressStats } from "./ProgressStats";

// ---------------------------------------------------------------------------
// Phase-machine
// ---------------------------------------------------------------------------

type Phase =
  | { phase: "config" }
  | { phase: "loading" }
  | { phase: "session"; session: TrainingSession; question: SessionQuestion; questionsAnswered: number }
  | { phase: "results"; results: SessionResults }
  | { phase: "error"; message: string };

type Action =
  | { type: "START_LOADING" }
  | { type: "SESSION_READY"; session: TrainingSession; question: SessionQuestion }
  | { type: "SESSION_EMPTY" }
  | { type: "NEXT_QUESTION"; session: TrainingSession; question: SessionQuestion }
  | { type: "SESSION_COMPLETE"; results: SessionResults }
  | { type: "ERROR"; message: string }
  | { type: "RESET" };

function reducer(state: Phase, action: Action): Phase {
  switch (action.type) {
    case "START_LOADING":
      return { phase: "loading" };
    case "SESSION_READY":
      return { phase: "session", session: action.session, question: action.question, questionsAnswered: 0 };
    case "SESSION_EMPTY":
      return { phase: "error", message: "No items match the selected filters. Add more vocabulary or change the mode." };
    case "NEXT_QUESTION":
      if (state.phase !== "session") return state;
      return { phase: "session", session: action.session, question: action.question, questionsAnswered: state.questionsAnswered + 1 };
    case "SESSION_COMPLETE":
      return { phase: "results", results: action.results };
    case "ERROR":
      return { phase: "error", message: action.message };
    case "RESET":
      return { phase: "config" };
    default:
      return state;
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const DEFAULT_MODE: SessionMode = "auto";
const DEFAULT_FILTERS: SessionFilters = {};
const DEFAULT_COUNT = 20;

export function TrainingTab() {
  const [phase, dispatch] = useReducer(reducer, { phase: "config" });
  const phaseRef = useRef<Phase>({ phase: "config" });
  phaseRef.current = phase;

  const [mode, setMode] = useConfigState(DEFAULT_MODE);
  const [filters, setFilters] = useConfigState(DEFAULT_FILTERS);
  const [targetCount, setTargetCount] = useConfigState(DEFAULT_COUNT);

  function handleFiltersChange(m: SessionMode, f: SessionFilters, count: number) {
    setMode(m);
    setFilters(f);
    setTargetCount(count);
  }

  async function handleStart() {
    dispatch({ type: "START_LOADING" });
    try {
      const { session, question } = await trainingApi.createSession({
        mode,
        filters,
        target_count: targetCount,
      });
      if (!question) {
        dispatch({ type: "SESSION_EMPTY" });
      } else {
        dispatch({ type: "SESSION_READY", session, question });
      }
    } catch (err) {
      dispatch({ type: "ERROR", message: err instanceof Error ? err.message : "Failed to start session" });
    }
  }

  async function handleAnswer(questionId: number, answer: string): Promise<AnswerResult> {
    if (phase.phase !== "session") throw new Error("Not in session");
    const result = await trainingApi.submitAnswer(phase.session.id, questionId, answer);

    if (result.session_complete) {
      // Fetch results immediately; SessionView will show feedback for 1.4 s in parallel.
      // handleAdvance is called after the 1.4 s window as a fallback only.
      trainingApi.getSessionResults(phase.session.id)
        .then((results) => dispatch({ type: "SESSION_COMPLETE", results }))
        .catch((err) => dispatch({ type: "ERROR", message: err instanceof Error ? err.message : "Failed to load results" }));
    }
    // next_question case is handled by handleAdvance (called by SessionView after feedback)

    return result;
  }

  function handleAdvance(result: AnswerResult) {
    // Guard: may already have transitioned (e.g. session_complete dispatched above)
    if (phaseRef.current.phase !== "session") return;
    const curr = phaseRef.current;

    if (result.session_complete) {
      // Fallback in case the immediate fetch above failed
      trainingApi.getSessionResults(curr.session.id)
        .then((results) => dispatch({ type: "SESSION_COMPLETE", results }))
        .catch((err) => dispatch({ type: "ERROR", message: err instanceof Error ? err.message : "Failed to load results" }));
    } else if (result.next_question) {
      const updatedSession: TrainingSession = {
        ...curr.session,
        correct_count: curr.session.correct_count + (result.is_correct ? 1 : 0),
        wrong_count: curr.session.wrong_count + (result.is_correct ? 0 : 1),
      };
      dispatch({ type: "NEXT_QUESTION", session: updatedSession, question: result.next_question });
    }
  }

  if (phase.phase === "session") {
    return (
      <SessionView
        session={phase.session}
        question={phase.question}
        questionsAnswered={phase.questionsAnswered}
        onAnswer={handleAnswer}
        onAdvance={handleAdvance}
      />
    );
  }

  if (phase.phase === "results") {
    return (
      <SessionResultsView
        results={phase.results}
        onStartNew={() => dispatch({ type: "RESET" })}
        onClose={() => dispatch({ type: "RESET" })}
      />
    );
  }

  return (
    <div className="training-tab">
      <ProgressStats />

      <FiltersPanel
        mode={mode}
        filters={filters}
        targetCount={targetCount}
        onChange={handleFiltersChange}
      />

      {phase.phase === "error" && (
        <div className="training-error">{phase.message}</div>
      )}

      <div className="training-actions">
        <button
          className="training-start-btn"
          onClick={handleStart}
          disabled={phase.phase === "loading"}
        >
          {phase.phase === "loading" ? "Loading…" : "Start Session"}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tiny helper — useState that survives phase changes (lives outside reducer)
// ---------------------------------------------------------------------------

function useConfigState<T>(initial: T): [T, (v: T) => void] {
  const [val, setVal] = useReducer((_: T, next: T) => next, initial);
  return [val, setVal];
}

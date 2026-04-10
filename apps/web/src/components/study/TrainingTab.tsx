import { useReducer } from "react";
import type {
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

  async function handleAnswer(questionId: number, answer: string) {
    if (phase.phase !== "session") throw new Error("Not in session");
    const result = await trainingApi.submitAnswer(phase.session.id, questionId, answer);
    if (result.session_complete) {
      // Fetch full results then transition
      const results = await trainingApi.getSessionResults(phase.session.id);
      // Small delay so SessionView can show the result overlay first
      setTimeout(() => dispatch({ type: "SESSION_COMPLETE", results }), 0);
    } else if (result.next_question) {
      // Build updated session snapshot with incremented counts
      const updatedSession: TrainingSession = {
        ...phase.session,
        correct_count: phase.session.correct_count + (result.is_correct ? 1 : 0),
        wrong_count: phase.session.wrong_count + (result.is_correct ? 0 : 1),
      };
      dispatch({ type: "NEXT_QUESTION", session: updatedSession, question: result.next_question });
    }
    return result;
  }

  function handleComplete() {
    if (phase.phase !== "session") return;
    trainingApi.getSessionResults(phase.session.id)
      .then((results) => dispatch({ type: "SESSION_COMPLETE", results }))
      .catch((err) => dispatch({ type: "ERROR", message: err instanceof Error ? err.message : "Failed to load results" }));
  }

  if (phase.phase === "session") {
    return (
      <SessionView
        session={phase.session}
        question={phase.question}
        questionsAnswered={phase.questionsAnswered}
        onAnswer={handleAnswer}
        onComplete={handleComplete}
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

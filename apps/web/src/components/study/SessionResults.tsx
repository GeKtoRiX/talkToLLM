import type { SessionResults } from "./types";

type Props = {
  results: SessionResults;
  onStartNew: () => void;
  onClose: () => void;
};

export function SessionResultsView({ results, onStartNew, onClose }: Props) {
  const pct = results.accuracy_pct;
  const pctClass =
    pct >= 85 ? "results-accuracy--good" :
    pct >= 60 ? "results-accuracy--ok" :
    "results-accuracy--poor";

  const durationStr = results.duration_seconds != null
    ? `${Math.floor(results.duration_seconds / 60)}m ${Math.round(results.duration_seconds % 60)}s`
    : null;

  return (
    <div className="session-results">
      <h2 className="results-title">Session Complete</h2>

      <div className={`results-accuracy ${pctClass}`}>
        <span className="results-accuracy__pct">{pct.toFixed(0)}%</span>
        <span className="results-accuracy__label">accuracy</span>
      </div>

      <div className="results-summary">
        <div className="results-stat">
          <span className="results-stat__value results-stat__value--correct">{results.correct_count}</span>
          <span className="results-stat__label">correct</span>
        </div>
        <div className="results-stat">
          <span className="results-stat__value results-stat__value--wrong">{results.wrong_count}</span>
          <span className="results-stat__label">wrong</span>
        </div>
        <div className="results-stat">
          <span className="results-stat__value">{results.total_questions}</span>
          <span className="results-stat__label">total</span>
        </div>
        {durationStr && (
          <div className="results-stat">
            <span className="results-stat__value">{durationStr}</span>
            <span className="results-stat__label">time</span>
          </div>
        )}
      </div>

      {results.newly_mastered.length > 0 && (
        <div className="results-section results-section--mastered">
          <h3 className="results-section__title">⭐ Newly Mastered</h3>
          <ul className="results-items">
            {results.newly_mastered.map((item) => (
              <li key={item.id} className="results-item results-item--mastered">
                <span className="results-item__target">{item.target_text}</span>
                <span className="results-item__native">{item.native_text}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {results.error_items.length > 0 && (
        <div className="results-section results-section--errors">
          <h3 className="results-section__title">Needs Work</h3>
          <ul className="results-items">
            {results.error_items.map((item) => (
              <li key={item.id} className="results-item results-item--error">
                <span className="results-item__target">{item.target_text}</span>
                <span className="results-item__native">{item.native_text}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {Object.keys(results.by_exercise_type).length > 0 && (
        <div className="results-section">
          <h3 className="results-section__title">By Exercise Type</h3>
          <div className="results-exercise-stats">
            {Object.entries(results.by_exercise_type).map(([type, stats]) => (
              <div key={type} className="results-exercise-stat">
                <span className="results-exercise-stat__type">{type}</span>
                <span className="results-exercise-stat__score">
                  {stats.correct}/{stats.shown}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="results-actions">
        <button className="results-btn results-btn--primary" onClick={onStartNew}>
          New Session
        </button>
        <button className="results-btn results-btn--secondary" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}

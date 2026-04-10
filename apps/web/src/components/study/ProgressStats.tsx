import { useEffect, useState } from "react";
import type { UserStats } from "./types";
import { trainingApi } from "./api";

export function ProgressStats() {
  const [stats, setStats] = useState<UserStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    trainingApi.getUserStats()
      .then(setStats)
      .catch(() => setStats(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="progress-stats progress-stats--loading">Loading stats…</div>;
  if (!stats) return null;

  const masteryPct = stats.total_items > 0
    ? Math.round((stats.mastered / stats.total_items) * 100)
    : 0;

  return (
    <div className="progress-stats">
      <div className="progress-stats__grid">
        <div className="progress-stats__cell">
          <span className="progress-stats__value">{stats.total_items}</span>
          <span className="progress-stats__label">Total</span>
        </div>
        <div className="progress-stats__cell progress-stats__cell--mastered">
          <span className="progress-stats__value">{stats.mastered}</span>
          <span className="progress-stats__label">Mastered</span>
        </div>
        <div className="progress-stats__cell progress-stats__cell--difficult">
          <span className="progress-stats__value">{stats.difficult}</span>
          <span className="progress-stats__label">Difficult</span>
        </div>
        <div className="progress-stats__cell">
          <span className="progress-stats__value">{stats.new}</span>
          <span className="progress-stats__label">New</span>
        </div>
        <div className="progress-stats__cell">
          <span className="progress-stats__value">{stats.learning}</span>
          <span className="progress-stats__label">Learning</span>
        </div>
        <div className="progress-stats__cell">
          <span className="progress-stats__value">{stats.total_training_sessions}</span>
          <span className="progress-stats__label">Sessions</span>
        </div>
      </div>

      {stats.total_items > 0 && (
        <div className="progress-stats__mastery-bar">
          <div
            className="progress-stats__mastery-fill"
            style={{ width: `${masteryPct}%` }}
          />
          <span className="progress-stats__mastery-label">{masteryPct}% mastered</span>
        </div>
      )}
    </div>
  );
}

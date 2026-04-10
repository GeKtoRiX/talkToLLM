import { useEffect, useState } from "react";
import type { UserStats } from "./types";
import { trainingApi } from "./api";

export function ProgressStats() {
  const [stats, setStats] = useState<UserStats | null>(null);

  useEffect(() => {
    trainingApi.getUserStats()
      .then(setStats)
      .catch(() => setStats(null));
  }, []);

  if (!stats || stats.total_items === 0) return null;

  const masteryPct = Math.round((stats.mastered / stats.total_items) * 100);

  return (
    <div className="progress-stats">
      <div className="progress-stats__summary">
        <span className="progress-stats__total">{stats.total_items} items</span>
        <span className="progress-stats__sep">·</span>
        <span className="progress-stats__mastered">{stats.mastered} mastered</span>
        {stats.difficult > 0 && (
          <>
            <span className="progress-stats__sep">·</span>
            <span className="progress-stats__difficult">{stats.difficult} difficult</span>
          </>
        )}
        {stats.new > 0 && (
          <>
            <span className="progress-stats__sep">·</span>
            <span className="progress-stats__new">{stats.new} new</span>
          </>
        )}
      </div>

      <div className="progress-stats__bar-wrap">
        <div className="progress-stats__bar">
          <div
            className="progress-stats__fill"
            style={{ width: `${masteryPct}%` }}
          />
        </div>
        <span className="progress-stats__pct">{masteryPct}%</span>
      </div>
    </div>
  );
}

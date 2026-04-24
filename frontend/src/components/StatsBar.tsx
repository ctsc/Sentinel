import { memo } from "react";
import { SOURCE_COLORS, formatRelativeTime } from "../utils/types";

interface Props {
  totalEvents: number;
  eventsPerMinute: number;
  connected: boolean;
  sourcesActive: string[];
  sourceCounts: Record<string, number>;
  lastEventTime: string | null;
}

function StatsBar({
  totalEvents,
  eventsPerMinute,
  connected,
  sourcesActive,
  sourceCounts,
  lastEventTime,
}: Props) {
  return (
    <div className="stats-bar">
      <span>
        <span className={`status-dot ${connected ? "connected" : ""}`} />
        {connected ? "LIVE" : "DISCONNECTED"}
      </span>
      <span>Events: {totalEvents.toLocaleString()}</span>
      <span>Events/min: {eventsPerMinute}</span>
      <span className="stats-sources">
        {sourcesActive.length > 0
          ? sourcesActive.map((s) => (
              <span key={s} className="stats-source-item">
                <span
                  className="stats-source-dot"
                  style={{ background: SOURCE_COLORS[s] || "#888" }}
                />
                {s}
                {sourceCounts[s] != null && (
                  <span className="stats-source-count">{sourceCounts[s]}</span>
                )}
              </span>
            ))
          : "No sources"}
      </span>
      {lastEventTime && (
        <span className="stats-last-event">
          Last event: {formatRelativeTime(lastEventTime)}
        </span>
      )}
    </div>
  );
}

export default memo(StatsBar);

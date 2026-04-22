import { useMemo } from "react";
import type { SentinelEvent } from "../utils/types";
import { SOURCE_COLORS, formatRelativeTime } from "../utils/types";

interface Props {
  totalEvents: number;
  eventsPerMinute: number;
  connected: boolean;
  sourcesActive: string[];
  events: SentinelEvent[];
  lastEventTime: string | null;
}

export default function StatsBar({
  totalEvents,
  eventsPerMinute,
  connected,
  sourcesActive,
  events,
  lastEventTime,
}: Props) {
  const sourceCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const e of events) {
      counts[e.source] = (counts[e.source] || 0) + 1;
    }
    return counts;
  }, [events]);

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

interface Props {
  totalEvents: number;
  eventsPerMinute: number;
  connected: boolean;
  sourcesActive: string[];
}

export default function StatsBar({
  totalEvents,
  eventsPerMinute,
  connected,
  sourcesActive,
}: Props) {
  return (
    <div className="stats-bar">
      <span>
        <span className={`status-dot ${connected ? "connected" : ""}`} />
        {connected ? "LIVE" : "DISCONNECTED"}
      </span>
      <span>Events: {totalEvents.toLocaleString()}</span>
      <span>Events/min: {eventsPerMinute}</span>
      <span>
        Sources: {sourcesActive.length > 0 ? sourcesActive.join(", ") : "—"}
      </span>
    </div>
  );
}

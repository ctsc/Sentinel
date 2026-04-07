import type { SentinelEvent } from "../utils/types";
import { EVENT_TYPE_COLORS } from "../utils/types";

interface Props {
  event: SentinelEvent | null;
  onClose: () => void;
}

export default function EventPanel({ event, onClose }: Props) {
  if (!event) return null;

  const typeColor = EVENT_TYPE_COLORS[event.event_type ?? "other"] ?? [150, 150, 150];

  return (
    <div className="event-panel">
      <button className="event-panel-close" onClick={onClose}>
        &times;
      </button>
      <h3>{event.title ?? "Untitled Event"}</h3>
      <div className="event-meta">
        <span
          className="event-type-badge"
          style={{
            backgroundColor: `rgba(${typeColor[0]}, ${typeColor[1]}, ${typeColor[2]}, 0.25)`,
            color: `rgb(${typeColor[0]}, ${typeColor[1]}, ${typeColor[2]})`,
          }}
        >
          {event.event_type ?? "other"}
        </span>
        <span>{event.source.toUpperCase()}</span>
        <span>{new Date(event.timestamp).toLocaleString()}</span>
      </div>
      <p className="event-text">{event.raw_text}</p>

      {event.geo?.location_name && (
        <p className="event-location">
          {event.geo.location_name}
          {event.geo.country_code && ` (${event.geo.country_code})`}
        </p>
      )}

      {event.confidence != null && (
        <p className="event-confidence">
          Confidence: {(event.confidence * 100).toFixed(0)}%
          {event.severity != null && ` | Severity: ${event.severity}/10`}
        </p>
      )}

      {event.entities && event.entities.length > 0 && (
        <p className="event-entities">
          Entities: {event.entities.join(", ")}
        </p>
      )}

      {event.source_url && (
        <a
          href={event.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="event-source-link"
        >
          View Source &rarr;
        </a>
      )}
    </div>
  );
}

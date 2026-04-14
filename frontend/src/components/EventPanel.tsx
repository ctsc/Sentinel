import type { SentinelEvent } from "../utils/types";
import { EVENT_TYPE_COLORS, classifyEvent, getEventTitle } from "../utils/types";

interface Props {
  event: SentinelEvent | null;
  onClose: () => void;
  onLocate?: (event: SentinelEvent) => void;
}

export default function EventPanel({ event, onClose, onLocate }: Props) {
  if (!event) return null;

  const type = classifyEvent(event);
  const typeColor = EVENT_TYPE_COLORS[type] ?? [150, 150, 150];
  const canLocate =
    event.geo?.lat != null && event.geo?.lon != null && onLocate != null;

  return (
    <div className="event-panel">
      <button className="event-panel-close" onClick={onClose}>
        &times;
      </button>
      <h3>{getEventTitle(event)}</h3>
      <div className="event-meta">
        <span
          className="event-type-badge"
          style={{
            backgroundColor: `rgba(${typeColor[0]}, ${typeColor[1]}, ${typeColor[2]}, 0.25)`,
            color: `rgb(${typeColor[0]}, ${typeColor[1]}, ${typeColor[2]})`,
          }}
        >
          {type}
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

      <div className="event-panel-actions">
        {canLocate && (
          <button
            className="event-locate-btn"
            onClick={() => onLocate!(event)}
          >
            Locate on map
          </button>
        )}
        {event.source_url && event.source_url.startsWith("http") ? (
          <a
            href={event.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="event-source-link"
          >
            View Source &rarr;
          </a>
        ) : (
          <span className="event-source-missing">No source link available</span>
        )}
      </div>
    </div>
  );
}

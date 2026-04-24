import { memo, useMemo, useState } from "react";
import type { SentinelEvent } from "../utils/types";

interface Props {
  events: SentinelEvent[];
  onEventClick: (event: SentinelEvent) => void;
}

const MAX_VISIBLE = 200;

function EventsSidebar({ events, onEventClick }: Props) {
  const [sortOrder, setSortOrder] = useState<"newest" | "oldest">("newest");
  const [locationFilter, setLocationFilter] = useState("");

  const visible = useMemo(() => {
    const q = locationFilter.trim().toLowerCase();
    const filtered = q
      ? events.filter((e) => {
          const loc = (e.geo?.location_name ?? "").toLowerCase();
          const cc = (e.geo?.country_code ?? "").toLowerCase();
          return loc.includes(q) || cc.includes(q);
        })
      : events;
    const sorted = [...filtered].sort((a, b) => {
      const ta = new Date(a.timestamp ?? 0).getTime();
      const tb = new Date(b.timestamp ?? 0).getTime();
      return sortOrder === "newest" ? tb - ta : ta - tb;
    });
    return sorted.slice(0, MAX_VISIBLE);
  }, [events, sortOrder, locationFilter]);

  return (
    <aside className="events-sidebar">
      <header className="sidebar-header">
        <span className="sidebar-title">LIVE FEED</span>
        <span className="sidebar-count">{visible.length}</span>
      </header>

      <div className="sidebar-controls">
        <select
          className="filter-select"
          value={sortOrder}
          onChange={(e) => setSortOrder(e.target.value as "newest" | "oldest")}
        >
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
        </select>
        <input
          className="sidebar-search"
          placeholder="Filter by location…"
          value={locationFilter}
          onChange={(e) => setLocationFilter(e.target.value)}
        />
      </div>

      <ul className="sidebar-list">
        {visible.map((e) => {
          const type = e._type ?? "other";
          const color = e._color ?? [150, 150, 150];
          const when = e.timestamp
            ? new Date(e.timestamp).toLocaleString(undefined, {
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })
            : "";
          return (
            <li
              key={e.event_id}
              className="sidebar-item"
              onClick={() => onEventClick(e)}
              style={{ borderLeftColor: `rgb(${color[0]},${color[1]},${color[2]})` }}
            >
              <div className="sidebar-item-top">
                <span className="sidebar-item-type" style={{ color: `rgb(${color[0]},${color[1]},${color[2]})` }}>
                  {type}
                </span>
                <span className="sidebar-item-time">{when}</span>
              </div>
              <div className="sidebar-item-title">{e._title ?? e.title ?? e.raw_text}</div>
              <div className="sidebar-item-meta">
                {e.geo?.location_name ?? e.geo?.country_code ?? "—"}
                <span className="sidebar-item-source"> · {e.source}</span>
              </div>
            </li>
          );
        })}
        {visible.length === 0 && (
          <li className="sidebar-empty">No events match.</li>
        )}
      </ul>
    </aside>
  );
}

export default memo(EventsSidebar);

import { useState, useMemo, useCallback, useRef, useEffect } from "react";
import MapViewComponent, { type MapViewHandle } from "./components/MapView";
import FilterBar from "./components/FilterBar";
import StatsBar from "./components/StatsBar";
import EventPanel from "./components/EventPanel";
import EventsSidebar from "./components/EventsSidebar";
import useWebSocket from "./hooks/useWebSocket";
import useEvents from "./hooks/useEvents";
import useThrottledSourceCounts from "./hooks/useThrottledSourceCounts";
import type { SentinelEvent } from "./utils/types";
import { EVENT_TYPE_COLORS } from "./utils/types";
import "./App.css";

const ALL_TYPES = new Set(Object.keys(EVENT_TYPE_COLORS));
const ALL_SOURCES = new Set(["gdelt", "acled", "rss", "bluesky", "wikipedia"]);
const HISTORY_HOURS = 168;    // 7 days
const HISTORY_LIMIT = 3000;   // pre-seed cap

function App() {
  const { events: wsEvents, connected, eventsPerMinute, lastEventTime, reconnecting } = useWebSocket();
  const { events: historyEvents, fetchEvents } = useEvents();

  useEffect(() => {
    fetchEvents({ hours: String(HISTORY_HOURS), limit: String(HISTORY_LIMIT) });
  }, [fetchEvents]);

  // Both sources are pre-enriched and pre-deduped within themselves; the only
  // cross-source overlap is history ∩ live, which we drop here.
  const liveEvents = useMemo(() => {
    const seen = new Set<string>();
    const combined: SentinelEvent[] = [];
    for (const ev of wsEvents) {
      if (seen.has(ev.event_id)) continue;
      seen.add(ev.event_id);
      combined.push(ev);
    }
    for (const ev of historyEvents) {
      if (seen.has(ev.event_id)) continue;
      seen.add(ev.event_id);
      combined.push(ev);
    }
    return combined;
  }, [wsEvents, historyEvents]);

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [selectedEvent, setSelectedEvent] = useState<SentinelEvent | null>(null);
  const mapRef = useRef<MapViewHandle | null>(null);

  const handleLocate = useCallback((event: SentinelEvent) => {
    if (event.geo?.lat != null && event.geo?.lon != null) {
      mapRef.current?.flyTo(event.geo.lon, event.geo.lat, 7);
    }
  }, []);

  const [activeTypes, setActiveTypes] = useState<Set<string>>(ALL_TYPES);
  const [activeSources, setActiveSources] = useState<Set<string>>(ALL_SOURCES);
  const [showHeatmap, setShowHeatmap] = useState(true);

  const filteredEvents = useMemo(() => {
    return liveEvents.filter(
      (e) => activeTypes.has(e._type ?? "other") && activeSources.has(e.source)
    );
  }, [liveEvents, activeTypes, activeSources]);

  const handleToggleSource = useCallback((source: string) => {
    setActiveSources((prev) => {
      const next = new Set(prev);
      if (next.has(source)) next.delete(source);
      else next.add(source);
      return next;
    });
  }, []);

  const sourceCounts = useThrottledSourceCounts(liveEvents, 2000);
  const sourcesActive = useMemo(
    () => Object.keys(sourceCounts),
    [sourceCounts]
  );

  const handleToggleType = useCallback((type: string) => {
    setActiveTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }, []);

  const handleToggleHeatmap = useCallback(() => {
    setShowHeatmap((prev) => !prev);
  }, []);

  const handleEventClick = useCallback((event: SentinelEvent) => {
    setSelectedEvent(event);
  }, []);

  const handleCloseEvent = useCallback(() => setSelectedEvent(null), []);
  const handleToggleSidebar = useCallback(
    () => setSidebarCollapsed((v) => !v),
    []
  );

  return (
    <div className="app">
      {reconnecting && (
        <div className="reconnect-banner">Reconnecting to live feed...</div>
      )}
      <FilterBar
        activeTypes={activeTypes}
        onToggleType={handleToggleType}
        showHeatmap={showHeatmap}
        onToggleHeatmap={handleToggleHeatmap}
        activeSources={activeSources}
        onToggleSource={handleToggleSource}
      />
      <MapViewComponent
        ref={mapRef}
        events={filteredEvents}
        showHeatmap={showHeatmap}
        onEventClick={handleEventClick}
      />
      {liveEvents.length === 0 && (
        <div className="empty-state">
          <div className="empty-state-pulse" />
          <p className="empty-state-text">Connecting to live feeds...</p>
        </div>
      )}
      <button
        className="sidebar-toggle"
        onClick={handleToggleSidebar}
        title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
      >
        {sidebarCollapsed ? "◀" : "▶"}
      </button>
      {!sidebarCollapsed && (
        <EventsSidebar
          events={filteredEvents}
          onEventClick={handleEventClick}
        />
      )}
      <EventPanel
        event={selectedEvent}
        onClose={handleCloseEvent}
        onLocate={handleLocate}
      />
      <StatsBar
        totalEvents={liveEvents.length}
        eventsPerMinute={eventsPerMinute}
        connected={connected}
        sourcesActive={sourcesActive}
        sourceCounts={sourceCounts}
        lastEventTime={lastEventTime}
      />
    </div>
  );
}

export default App;

import { useState, useMemo, useCallback, useRef } from "react";
import MapViewComponent, { type MapViewHandle } from "./components/MapView";
import FilterBar from "./components/FilterBar";
import StatsBar from "./components/StatsBar";
import EventPanel from "./components/EventPanel";
import EventsSidebar from "./components/EventsSidebar";
import useWebSocket from "./hooks/useWebSocket";
import type { SentinelEvent } from "./utils/types";
import { EVENT_TYPE_COLORS, classifyEvent } from "./utils/types";
import "./App.css";

const ALL_TYPES = new Set(Object.keys(EVENT_TYPE_COLORS));
const ALL_SOURCES = new Set(["gdelt", "acled", "rss", "bluesky", "wikipedia"]);

function App() {
  const { events: liveEvents, connected, eventsPerMinute } = useWebSocket();
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
      (e) => activeTypes.has(classifyEvent(e)) && activeSources.has(e.source)
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

  const sourcesActive = useMemo(() => {
    const sources = new Set(liveEvents.map((e) => e.source));
    return Array.from(sources);
  }, [liveEvents]);

  const handleToggleType = useCallback((type: string) => {
    setActiveTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  }, []);

  const handleToggleHeatmap = useCallback(() => {
    setShowHeatmap((prev) => !prev);
  }, []);

  const handleEventClick = useCallback((event: SentinelEvent) => {
    setSelectedEvent(event);
  }, []);

  return (
    <div className="app">
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
      <EventsSidebar
        events={filteredEvents}
        onEventClick={handleEventClick}
      />
      <EventPanel
        event={selectedEvent}
        onClose={() => setSelectedEvent(null)}
        onLocate={handleLocate}
      />
      <StatsBar
        totalEvents={liveEvents.length}
        eventsPerMinute={eventsPerMinute}
        connected={connected}
        sourcesActive={sourcesActive}
      />
    </div>
  );
}

export default App;

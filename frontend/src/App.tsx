import { useState, useMemo, useCallback } from "react";
import MapViewComponent from "./components/MapView";
import FilterBar from "./components/FilterBar";
import StatsBar from "./components/StatsBar";
import EventPanel from "./components/EventPanel";
import useWebSocket from "./hooks/useWebSocket";
import type { SentinelEvent } from "./utils/types";
import { EVENT_TYPE_COLORS } from "./utils/types";
import "./App.css";

const ALL_TYPES = new Set(Object.keys(EVENT_TYPE_COLORS));

function App() {
  const { events: liveEvents, connected, eventsPerMinute } = useWebSocket();
  const [selectedEvent, setSelectedEvent] = useState<SentinelEvent | null>(null);
  const [activeTypes, setActiveTypes] = useState<Set<string>>(ALL_TYPES);
  const [showHeatmap, setShowHeatmap] = useState(true);

  const filteredEvents = useMemo(() => {
    return liveEvents.filter((e) => activeTypes.has(e.event_type ?? "other"));
  }, [liveEvents, activeTypes]);

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
      />
      <MapViewComponent
        events={filteredEvents}
        showHeatmap={showHeatmap}
        onEventClick={handleEventClick}
      />
      <EventPanel
        event={selectedEvent}
        onClose={() => setSelectedEvent(null)}
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

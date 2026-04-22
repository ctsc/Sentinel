import { useState, useEffect, useRef, useCallback } from "react";
import type { SentinelEvent } from "../utils/types";

const WS_URL =
  import.meta.env.VITE_WS_URL ||
  `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws/live`;
const MAX_EVENTS = 15000;

interface UseWebSocketReturn {
  events: SentinelEvent[];
  connected: boolean;
  eventsPerMinute: number;
  lastEventTime: string | null;
  reconnecting: boolean;
}

export default function useWebSocket(): UseWebSocketReturn {
  const [events, setEvents] = useState<SentinelEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [lastEventTime, setLastEventTime] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const hadConnectionRef = useRef(false);
  const eventCountRef = useRef(0);
  const [eventsPerMinute, setEventsPerMinute] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setEventsPerMinute(eventCountRef.current);
      eventCountRef.current = 0;
    }, 60000);
    return () => clearInterval(interval);
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      setReconnecting(false);
      hadConnectionRef.current = true;
    };

    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        if (data.type === "events" && Array.isArray(data.events)) {
          // Backend enriches events with coords, event_type, severity, confidence.
          // Still drop any that fell through geocoding — those can't be placed.
          const newEvents = (data.events as SentinelEvent[]).filter(
            (e) => e.geo?.lat != null && e.geo?.lon != null
          );
          if (newEvents.length === 0) return;
          eventCountRef.current += newEvents.length;
          const latest = newEvents[newEvents.length - 1];
          if (latest.timestamp) setLastEventTime(latest.timestamp);

          setEvents((prev) => {
            const combined = [...prev, ...newEvents];
            if (combined.length > MAX_EVENTS) {
              return combined.slice(combined.length - MAX_EVENTS);
            }
            return combined;
          });
        }
      } catch {
        // Ignore parse errors
      }
    };

    ws.onclose = () => {
      setConnected(false);
      if (hadConnectionRef.current) setReconnecting(true);
      setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
    };
  }, [connect]);

  return { events, connected, eventsPerMinute, lastEventTime, reconnecting };
}

import { useState, useCallback } from "react";
import type { SentinelEvent } from "../utils/types";
import { enrichEvent } from "../utils/types";

const API_URL = import.meta.env.VITE_API_URL || "/api";

interface UseEventsReturn {
  events: SentinelEvent[];
  loading: boolean;
  error: string | null;
  fetchEvents: (params?: Record<string, string>) => Promise<void>;
}

export default function useEvents(): UseEventsReturn {
  const [events, setEvents] = useState<SentinelEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchEvents = useCallback(async (params?: Record<string, string>) => {
    setLoading(true);
    setError(null);

    try {
      const query = params
        ? "?" + new URLSearchParams(params).toString()
        : "";
      const response = await fetch(`${API_URL}/events${query}`);

      if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
      }

      const data: SentinelEvent[] = await response.json();
      const enriched: SentinelEvent[] = [];
      for (const ev of data) {
        const e = enrichEvent(ev);
        if (e) enriched.push(e);
      }
      setEvents(enriched);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  return { events, loading, error, fetchEvents };
}

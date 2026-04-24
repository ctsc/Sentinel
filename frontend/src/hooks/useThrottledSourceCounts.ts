import { useEffect, useRef, useState } from "react";
import type { SentinelEvent } from "../utils/types";

/**
 * Counts events per source, but only updates the returned value every
 * `intervalMs` milliseconds. This lets StatsBar show source counts without
 * forcing a full O(n) walk of the events array on every WebSocket tick.
 */
export default function useThrottledSourceCounts(
  events: SentinelEvent[],
  intervalMs: number = 2000
): Record<string, number> {
  const latest = useRef(events);
  latest.current = events;

  const [counts, setCounts] = useState<Record<string, number>>({});

  useEffect(() => {
    const tick = () => {
      const next: Record<string, number> = {};
      for (const e of latest.current) {
        next[e.source] = (next[e.source] || 0) + 1;
      }
      setCounts(next);
    };
    tick();
    const id = setInterval(tick, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);

  return counts;
}

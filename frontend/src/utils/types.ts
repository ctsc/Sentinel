/** Unified event schema — matches Kafka message format after NLP enrichment. */
export interface SentinelEvent {
  event_id: string;
  source: "gdelt" | "acled" | "rss" | "bluesky" | "wikipedia" | "telegram";
  raw_text: string;
  title: string | null;
  timestamp: string; // ISO8601
  source_url: string | null;
  geo: {
    lat: number | null;
    lon: number | null;
    country_code: string | null;
    location_name: string | null;
  };
  metadata: Record<string, unknown>;
  // NLP-enriched fields
  event_type?: "conflict" | "protest" | "disaster" | "political" | "terrorism" | "other";
  confidence?: number;
  entities?: string[];
  severity?: number;
  dedupe_hash?: string;
}

/** Event type color mapping for scatter layer. */
export const EVENT_TYPE_COLORS: Record<string, [number, number, number]> = {
  conflict: [255, 50, 50],     // red
  protest: [255, 220, 50],     // yellow
  disaster: [255, 150, 30],    // orange
  political: [50, 120, 255],   // blue
  terrorism: [180, 50, 255],   // purple
  other: [150, 150, 150],      // gray
};

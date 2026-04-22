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

/** Generate a display title for any event — falls back to first sentence/snippet of raw_text. */
export function getEventTitle(e: SentinelEvent): string {
  const t = (e.title ?? "").trim();
  if (t) return t;

  const text = (e.raw_text ?? "").trim();
  if (text) {
    // Try first sentence; cap length
    const firstSentence = text.split(/(?<=[.!?])\s/)[0]?.trim() ?? text;
    const snippet = firstSentence.length > 110
      ? firstSentence.slice(0, 107).trimEnd() + "…"
      : firstSentence;
    return snippet;
  }

  // Last-resort label so nothing reads "Untitled"
  const where = e.geo?.location_name ?? e.geo?.country_code;
  const src = (e.source ?? "event").toUpperCase();
  return where ? `${src} report from ${where}` : `${src} report`;
}

/** Unicode symbol per event type — minimal geometric glyphs. */
export const EVENT_TYPE_ICONS: Record<string, string> = {
  conflict: "▲",   // up triangle — escalation
  protest: "●",    // filled circle
  disaster: "◆",   // diamond
  political: "■",  // square
  terrorism: "✕",  // crisp X
  other: "·",      // tiny dot
};

/**
 * Infer an event_type from raw producer output when the consumer hasn't
 * classified yet. GDELT uses CAMEO codes (18x/19x = conflict, 14x = protest,
 * etc.); ACLED uses named event_type strings. Everything else falls back to
 * keyword sniffing on title/text.
 */
export function classifyEvent(e: SentinelEvent): string {
  if (e.event_type) return e.event_type;

  const meta = (e.metadata ?? {}) as Record<string, unknown>;

  // ACLED: explicit event_type in metadata
  if (e.source === "acled") {
    const t = String(meta.event_type ?? "").toLowerCase();
    if (t.includes("protest")) return "protest";
    if (t.includes("riot")) return "protest";
    if (t.includes("battle") || t.includes("violence") || t.includes("armed")) return "conflict";
    if (t.includes("explosion") || t.includes("remote")) return "terrorism";
    if (t.includes("strategic")) return "political";
    return "conflict";
  }

  // GDELT: CAMEO event code — 14=protest, 17-19=conflict/war, 20=unconv violence
  if (e.source === "gdelt") {
    const code = String(meta.event_code ?? meta.EventCode ?? "");
    const root = code.slice(0, 2);
    if (root === "14") return "protest";
    if (root === "17" || root === "18" || root === "19") return "conflict";
    if (root === "20") return "terrorism";
    return "political";
  }

  // RSS/Bluesky/Wikipedia: keyword sniff on title + raw_text
  const hay = ((e.title ?? "") + " " + (e.raw_text ?? "")).toLowerCase();
  if (/\b(earthquake|tsunami|hurricane|typhoon|flood|wildfire|eruption)\b/.test(hay)) return "disaster";
  if (/\b(protest|riot|demonstration|march|unrest)\b/.test(hay)) return "protest";
  if (/\b(terror|bomb|attack|explosion|assassinat|hostage|suicide)\b/.test(hay)) return "terrorism";
  if (/\b(war|conflict|missile|airstrike|troops|soldiers|invasion|offensive|combat|battle|ceasefire)\b/.test(hay)) return "conflict";
  if (/\b(election|sanction|treaty|parliament|summit|diplomat)\b/.test(hay)) return "political";
  return "other";
}

/** Source brand colors for visual identification. */
export const SOURCE_COLORS: Record<string, string> = {
  gdelt: "#4488ff",
  acled: "#ff4444",
  rss: "#44cc66",
  bluesky: "#0085ff",
  wikipedia: "#999999",
  telegram: "#0088cc",
};

/** Format a timestamp as relative time ("3 min ago", "2h ago", etc.). */
export function formatRelativeTime(iso: string): string {
  const now = Date.now();
  const then = new Date(iso).getTime();
  if (isNaN(then)) return "";
  const diffSec = Math.max(0, Math.floor((now - then) / 1000));

  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const mins = Math.floor(diffSec / 60);
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

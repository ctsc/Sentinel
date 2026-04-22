import { ScatterplotLayer } from "@deck.gl/layers";
import type { SentinelEvent } from "../utils/types";
import { EVENT_TYPE_COLORS, classifyEvent } from "../utils/types";

/**
 * Two-layer "glowing dot" scatter:
 *   - event-glow: large translucent halo scaled to severity (non-pickable)
 *   - event-core: small opaque dot centered on the event (pickable)
 *
 * Both share event type color. Looks like real dashboards (liveuamap,
 * flightradar) rather than the old unicode-glyph approach.
 */
export function createScatterLayers(
  data: SentinelEvent[],
  onClick?: (info: { object?: SentinelEvent }) => void
) {
  const filtered = data.filter(
    (e) => e.geo?.lat != null && e.geo?.lon != null
  );

  const trigger = [filtered.length];

  const glow = new ScatterplotLayer<SentinelEvent>({
    id: "event-glow",
    data: filtered,
    pickable: false,
    radiusUnits: "pixels",
    radiusMinPixels: 6,
    radiusMaxPixels: 22,
    getPosition: (d) => [d.geo.lon!, d.geo.lat!],
    getRadius: (d) => 6 + Math.min((d.severity ?? 5) * 1.4, 14),
    getFillColor: (d) => {
      const c = EVENT_TYPE_COLORS[classifyEvent(d)] ?? [150, 150, 150];
      const sev = d.severity ?? 5;
      // More severe → a touch more visible halo
      const alpha = 40 + Math.min(sev * 4, 40);
      return [c[0], c[1], c[2], alpha];
    },
    stroked: false,
    updateTriggers: {
      getPosition: trigger,
      getRadius: trigger,
      getFillColor: trigger,
    },
  });

  const core = new ScatterplotLayer<SentinelEvent>({
    id: "event-core",
    data: filtered,
    pickable: true,
    radiusUnits: "pixels",
    radiusMinPixels: 2.5,
    radiusMaxPixels: 7,
    getPosition: (d) => [d.geo.lon!, d.geo.lat!],
    getRadius: (d) => 2.5 + Math.min((d.severity ?? 5) * 0.4, 4),
    getFillColor: (d) => {
      const c = EVENT_TYPE_COLORS[classifyEvent(d)] ?? [180, 180, 180];
      return [c[0], c[1], c[2], 235];
    },
    stroked: true,
    lineWidthUnits: "pixels",
    getLineWidth: 1,
    getLineColor: [10, 10, 26, 180], // matches the dark map bg for clean edge
    onClick: onClick as unknown as () => void,
    updateTriggers: {
      getPosition: trigger,
      getRadius: trigger,
      getFillColor: trigger,
    },
  });

  return [glow, core];
}

import { ScatterplotLayer } from "@deck.gl/layers";
import type { SentinelEvent } from "../utils/types";

/**
 * Two-layer "glowing dot" scatter:
 *   - event-glow: large translucent halo scaled to severity (non-pickable)
 *   - event-core: small opaque dot centered on the event (pickable)
 *
 * Sized in meters so dots shrink to sub-pixel at world zoom (letting the
 * heatmap dominate) and grow as you zoom in. Colors/positions read from
 * the precomputed `_color` / `_position` fields — no classifier calls on
 * the render path.
 */
export function createScatterLayers(
  data: SentinelEvent[],
  onClick?: (info: { object?: SentinelEvent }) => void
) {
  const glow = new ScatterplotLayer<SentinelEvent>({
    id: "event-glow",
    data,
    pickable: false,
    radiusUnits: "meters",
    radiusMinPixels: 0,   // invisible at world zoom
    radiusMaxPixels: 28,
    getPosition: (d) => d._position ?? [d.geo.lon ?? 0, d.geo.lat ?? 0],
    getRadius: (d) => 25000 + Math.min((d.severity ?? 5) * 6000, 40000),
    getFillColor: (d) => {
      const c = d._color ?? [150, 150, 150];
      const sev = d.severity ?? 5;
      const alpha = 40 + Math.min(sev * 4, 40);
      return [c[0], c[1], c[2], alpha];
    },
    stroked: false,
  });

  const core = new ScatterplotLayer<SentinelEvent>({
    id: "event-core",
    data,
    pickable: true,
    radiusUnits: "meters",
    radiusMinPixels: 0,   // invisible at world zoom
    radiusMaxPixels: 8,
    getPosition: (d) => d._position ?? [d.geo.lon ?? 0, d.geo.lat ?? 0],
    getRadius: (d) => 10000 + Math.min((d.severity ?? 5) * 2500, 20000),
    getFillColor: (d) => {
      const c = d._color ?? [180, 180, 180];
      return [c[0], c[1], c[2], 235];
    },
    stroked: true,
    lineWidthUnits: "pixels",
    getLineWidth: 1,
    getLineColor: [10, 10, 26, 180],
    onClick: onClick as unknown as () => void,
  });

  return [glow, core];
}

import { HeatmapLayer } from "@deck.gl/aggregation-layers";
import type { SentinelEvent } from "../utils/types";

export function createHeatmapLayer(data: SentinelEvent[]) {
  const filtered = data.filter(
    (e) => e.geo?.lat != null && e.geo?.lon != null
  );

  return new HeatmapLayer<SentinelEvent>({
    id: "heatmap-layer",
    data: filtered,
    getPosition: (d) => [d.geo.lon!, d.geo.lat!],
    getWeight: (d) => Math.max(d.severity ?? 5, 3),
    radiusPixels: 70,
    intensity: 1.8,
    threshold: 0.02,
    opacity: 0.7,
    aggregation: "SUM",
    debounceTimeout: 200,
    // Cool blue → green → yellow → red ramp. Solid RGB values (no alpha) so
    // deck.gl handles transparency via opacity prop above.
    colorRange: [
      [40, 80, 200],     // deep blue (low)
      [40, 200, 200],    // teal
      [80, 220, 120],    // green
      [255, 220, 60],    // yellow
      [255, 130, 30],    // orange
      [220, 30, 30],     // red (hot)
    ],
    updateTriggers: {
      getPosition: [data.length],
      getWeight: [data.length],
    },
  });
}

import { HeatmapLayer } from "@deck.gl/aggregation-layers";
import type { SentinelEvent } from "../utils/types";

export function createHeatmapLayer(data: SentinelEvent[]) {
  return new HeatmapLayer<SentinelEvent>({
    id: "heatmap-layer",
    data,
    getPosition: (d) => d._position ?? [d.geo.lon ?? 0, d.geo.lat ?? 0],
    getWeight: (d) => Math.max(d.severity ?? 5, 3),
    radiusPixels: 70,
    intensity: 1.8,
    threshold: 0.02,
    opacity: 0.7,
    aggregation: "SUM",
    debounceTimeout: 200,
    // Cool blue → green → yellow → red ramp.
    colorRange: [
      [40, 80, 200],
      [40, 200, 200],
      [80, 220, 120],
      [255, 220, 60],
      [255, 130, 30],
      [220, 30, 30],
    ],
  });
}

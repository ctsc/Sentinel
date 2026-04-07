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
    getWeight: (d) => d.severity ?? 5,
    radiusPixels: 60,
    intensity: 1.5,
    threshold: 0.1,
    opacity: 0.6,
    updateTriggers: {
      getPosition: [data.length],
      getWeight: [data.length],
    },
  });
}

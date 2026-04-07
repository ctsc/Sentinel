import { ScatterplotLayer } from "@deck.gl/layers";
import type { SentinelEvent } from "../utils/types";
import { EVENT_TYPE_COLORS } from "../utils/types";

export function createScatterLayer(
  data: SentinelEvent[],
  onClick?: (info: { object?: SentinelEvent }) => void
) {
  const filtered = data.filter(
    (e) => e.geo?.lat != null && e.geo?.lon != null
  );

  return new ScatterplotLayer<SentinelEvent>({
    id: "scatter-layer",
    data: filtered,
    pickable: true,
    opacity: 0.8,
    stroked: true,
    filled: true,
    radiusScale: 1,
    radiusMinPixels: 4,
    radiusMaxPixels: 20,
    lineWidthMinPixels: 1,
    getPosition: (d) => [d.geo.lon!, d.geo.lat!],
    getRadius: (d) => (d.severity ?? 5) * 800,
    getFillColor: (d) => {
      const color = EVENT_TYPE_COLORS[d.event_type ?? "other"] ?? [150, 150, 150];
      return [...color, 200] as [number, number, number, number];
    },
    getLineColor: [255, 255, 255, 80],
    onClick: onClick as unknown as () => void,
    updateTriggers: {
      getPosition: [data.length],
      getFillColor: [data.length],
    },
  });
}

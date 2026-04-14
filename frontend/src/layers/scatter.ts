import { TextLayer } from "@deck.gl/layers";
import type { SentinelEvent } from "../utils/types";
import { EVENT_TYPE_COLORS, EVENT_TYPE_ICONS, classifyEvent } from "../utils/types";

export function createScatterLayer(
  data: SentinelEvent[],
  onClick?: (info: { object?: SentinelEvent }) => void
) {
  const filtered = data.filter(
    (e) => e.geo?.lat != null && e.geo?.lon != null
  );

  return new TextLayer<SentinelEvent>({
    id: "event-symbols",
    data: filtered,
    pickable: true,
    sizeUnits: "pixels",
    sizeScale: 1,
    characterSet: Object.values(EVENT_TYPE_ICONS).join("") + " ",
    getPosition: (d) => [d.geo.lon!, d.geo.lat!],
    getText: (d) => EVENT_TYPE_ICONS[classifyEvent(d)] ?? "·",
    getSize: (d) => 12 + Math.min((d.severity ?? 5) * 0.8, 8),
    getColor: (d) => {
      const c = EVENT_TYPE_COLORS[classifyEvent(d)] ?? [200, 200, 200];
      return [c[0], c[1], c[2], 245];
    },
    fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
    fontWeight: 600,
    outlineWidth: 1,
    outlineColor: [0, 0, 0, 220],
    fontSettings: { sdf: true, fontSize: 64, buffer: 4 },
    onClick: onClick as unknown as () => void,
    updateTriggers: {
      getText: [data.length],
      getColor: [data.length],
      getPosition: [data.length],
    },
  });
}

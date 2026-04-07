import { ArcLayer } from "@deck.gl/layers";
import type { SentinelEvent } from "../utils/types";

interface ArcData {
  source: [number, number];
  target: [number, number];
}

export function createArcLayer(data: SentinelEvent[]) {
  const arcData: ArcData[] = [];
  const withCoords = data.filter(
    (e) => e.geo?.lat != null && e.geo?.lon != null
  );

  const recent = withCoords.slice(-200);

  for (let i = 0; i < recent.length - 1; i++) {
    const a = recent[i];
    const b = recent[i + 1];
    if (a.source === b.source) {
      arcData.push({
        source: [a.geo.lon!, a.geo.lat!],
        target: [b.geo.lon!, b.geo.lat!],
      });
    }
  }

  return new ArcLayer<ArcData>({
    id: "arc-layer",
    data: arcData,
    getSourcePosition: (d) => d.source,
    getTargetPosition: (d) => d.target,
    getSourceColor: [0, 255, 200, 100],
    getTargetColor: [0, 255, 200, 40],
    getWidth: 1,
    opacity: 0.4,
  });
}

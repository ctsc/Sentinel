import { useMemo } from "react";
import DeckGL from "@deck.gl/react";
import { MapView as DeckMapView } from "@deck.gl/core";
import Map from "react-map-gl/mapbox";
import "mapbox-gl/dist/mapbox-gl.css";
import type { SentinelEvent } from "../utils/types";
import { createScatterLayer } from "../layers/scatter";
import { createHeatmapLayer } from "../layers/heatmap";

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN ?? "";

const INITIAL_VIEW_STATE = {
  longitude: 30,
  latitude: 20,
  zoom: 2.5,
  pitch: 0,
  bearing: 0,
};

interface Props {
  events: SentinelEvent[];
  showHeatmap: boolean;
  onEventClick: (event: SentinelEvent) => void;
}

export default function MapViewComponent({ events, showHeatmap, onEventClick }: Props) {
  const layers = useMemo(() => {
    const result = [];

    if (showHeatmap) {
      result.push(createHeatmapLayer(events));
    }

    result.push(
      createScatterLayer(events, (info) => {
        if (info.object) {
          onEventClick(info.object);
        }
      })
    );

    return result;
  }, [events, showHeatmap, onEventClick]);

  return (
    <DeckGL
      initialViewState={INITIAL_VIEW_STATE}
      controller={true}
      views={new DeckMapView()}
      layers={layers}
      style={{ position: "absolute", width: "100%", height: "100%" }}
    >
      <Map
        mapboxAccessToken={MAPBOX_TOKEN}
        mapStyle="mapbox://styles/mapbox/dark-v11"
      />
    </DeckGL>
  );
}

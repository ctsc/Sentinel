import { forwardRef, useCallback, useImperativeHandle, useMemo, useState } from "react";
import DeckGL from "@deck.gl/react";
import { MapView as DeckMapView, FlyToInterpolator } from "@deck.gl/core";
import Map from "react-map-gl/mapbox";
import "mapbox-gl/dist/mapbox-gl.css";
import type { SentinelEvent } from "../utils/types";
import { createScatterLayer } from "../layers/scatter";
import { createHeatmapLayer } from "../layers/heatmap";

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN ?? "";

interface ViewState {
  longitude: number;
  latitude: number;
  zoom: number;
  pitch: number;
  bearing: number;
  transitionDuration?: number | "auto";
  transitionInterpolator?: FlyToInterpolator;
}

const INITIAL_VIEW_STATE: ViewState = {
  longitude: 30,
  latitude: 20,
  zoom: 2.5,
  pitch: 0,
  bearing: 0,
};

export interface MapViewHandle {
  flyTo: (lon: number, lat: number, zoom?: number) => void;
}

interface Props {
  events: SentinelEvent[];
  showHeatmap: boolean;
  onEventClick: (event: SentinelEvent) => void;
}

const MapViewComponent = forwardRef<MapViewHandle, Props>(
  ({ events, showHeatmap, onEventClick }, ref) => {
    const [viewState, setViewState] = useState<ViewState>(INITIAL_VIEW_STATE);

    useImperativeHandle(
      ref,
      () => ({
        flyTo: (lon: number, lat: number, zoom = 6) => {
          setViewState((prev) => ({
            ...prev,
            longitude: lon,
            latitude: lat,
            zoom,
            transitionDuration: 1500,
            transitionInterpolator: new FlyToInterpolator({ speed: 1.6 }),
          }));
        },
      }),
      []
    );

    const handleViewStateChange = useCallback(
      ({ viewState: next }: { viewState: Record<string, unknown> }) => {
        setViewState({
          longitude: next.longitude as number,
          latitude: next.latitude as number,
          zoom: next.zoom as number,
          pitch: (next.pitch as number) ?? 0,
          bearing: (next.bearing as number) ?? 0,
        });
      },
      []
    );

    const layers = useMemo(() => {
      const result = [];
      if (showHeatmap) result.push(createHeatmapLayer(events));
      result.push(
        createScatterLayer(events, (info) => {
          if (info.object) onEventClick(info.object);
        })
      );
      return result;
    }, [events, showHeatmap, onEventClick]);

    return (
      <DeckGL
        viewState={viewState}
        onViewStateChange={handleViewStateChange}
        controller={true}
        views={new DeckMapView()}
        layers={layers}
        style={{ position: "absolute", width: "100%", height: "100%" }}
      >
        <Map
          mapboxAccessToken={MAPBOX_TOKEN}
          mapStyle="mapbox://styles/mapbox/dark-v11"
          projection="mercator"
        />
      </DeckGL>
    );
  }
);

MapViewComponent.displayName = "MapViewComponent";

export default MapViewComponent;

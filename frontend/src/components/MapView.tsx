import { forwardRef, useCallback, useImperativeHandle, useMemo, useState } from "react";
import DeckGL from "@deck.gl/react";
import { MapView as DeckMapView, FlyToInterpolator } from "@deck.gl/core";
import Map from "react-map-gl/mapbox";
import "mapbox-gl/dist/mapbox-gl.css";
import type { SentinelEvent } from "../utils/types";
import { classifyEvent, getEventTitle } from "../utils/types";
import { createScatterLayers } from "../layers/scatter";
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
      const scatterLayers = createScatterLayers(events, (info) => {
        if (info.object) onEventClick(info.object);
      });
      return showHeatmap
        ? [createHeatmapLayer(events), ...scatterLayers]
        : scatterLayers;
    }, [events, showHeatmap, onEventClick]);

    const getTooltip = useCallback(({ object }: { object?: SentinelEvent }) => {
      if (!object) return null;
      const title = getEventTitle(object);
      const type = classifyEvent(object);
      return {
        html: `<div style="padding:6px 10px;font-size:12px;max-width:280px;line-height:1.4"><strong style="text-transform:uppercase;font-size:10px;letter-spacing:1px;opacity:0.7">${type}</strong><br/>${title}</div>`,
        style: {
          backgroundColor: "rgba(10,10,26,0.92)",
          color: "#e6e6f0",
          border: "1px solid rgba(0,255,200,0.3)",
          borderRadius: "4px",
          fontSize: "12px",
        },
      };
    }, []);

    return (
      <DeckGL
        viewState={viewState}
        onViewStateChange={handleViewStateChange}
        controller={true}
        views={new DeckMapView()}
        layers={layers}
        getTooltip={getTooltip as never}
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

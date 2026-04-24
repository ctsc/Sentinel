import { memo } from "react";
import { EVENT_TYPE_COLORS } from "../utils/types";

const EVENT_TYPES = Object.keys(EVENT_TYPE_COLORS) as Array<keyof typeof EVENT_TYPE_COLORS>;

interface Props {
  activeTypes: Set<string>;
  onToggleType: (type: string) => void;
  showHeatmap: boolean;
  onToggleHeatmap: () => void;
  activeSources: Set<string>;
  onToggleSource: (source: string) => void;
}

const ALL_SOURCES = ["gdelt", "acled", "rss", "bluesky", "wikipedia"];

function FilterBar({
  activeTypes,
  onToggleType,
  showHeatmap,
  onToggleHeatmap,
  activeSources,
  onToggleSource,
}: Props) {
  return (
    <div className="filter-bar">
      <span className="filter-bar-title">SENTINEL</span>

      <div className="filter-group">
        {ALL_SOURCES.map((src) => {
          const active = activeSources.has(src);
          return (
            <button
              key={src}
              className={`filter-chip ${active ? "active" : ""}`}
              style={{
                borderColor: "#88aaff",
                backgroundColor: active ? "rgba(136, 170, 255, 0.2)" : "transparent",
                color: active ? "#88aaff" : "#8a8a9a",
              }}
              onClick={() => onToggleSource(src)}
            >
              {src}
            </button>
          );
        })}
      </div>

      <div className="filter-group">
        {EVENT_TYPES.map((type) => {
          const color = EVENT_TYPE_COLORS[type];
          const active = activeTypes.has(type);
          return (
            <button
              key={type}
              className={`filter-chip ${active ? "active" : ""}`}
              style={{
                borderColor: `rgb(${color[0]}, ${color[1]}, ${color[2]})`,
                backgroundColor: active
                  ? `rgba(${color[0]}, ${color[1]}, ${color[2]}, 0.25)`
                  : "transparent",
                color: active
                  ? `rgb(${color[0]}, ${color[1]}, ${color[2]})`
                  : "#8a8a9a",
              }}
              onClick={() => onToggleType(type)}
            >
              {type}
            </button>
          );
        })}
      </div>

      <button
        className={`filter-chip ${showHeatmap ? "active" : ""}`}
        style={{
          borderColor: "#00ffc8",
          backgroundColor: showHeatmap ? "rgba(0, 255, 200, 0.2)" : "transparent",
          color: showHeatmap ? "#00ffc8" : "#8a8a9a",
        }}
        onClick={onToggleHeatmap}
      >
        Heatmap
      </button>
    </div>
  );
}

export default memo(FilterBar);

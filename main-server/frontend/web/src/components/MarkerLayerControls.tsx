import { OTHER_LAYER_KEY } from "../features/mapEditor/constants";
import type { MarkerLayers } from "../hooks/useMarkerLayers";

/** 맵 마커 레이어 토글 UI (PHASE_41) — 타입별 체크박스 + 모두 켜기/끄기 + 연결 화살표. */
export function MarkerLayerControls({
  layers,
  colors,
  arrowLabel = "연결 화살표",
  className,
  showLabelToggle = true,
}: {
  layers: MarkerLayers;
  colors: Record<string, string>;
  arrowLabel?: string;
  className?: string;
  showLabelToggle?: boolean;
}) {
  return (
    <div className={`map-layers${className ? ` ${className}` : ""}`}>
      <div className="map-layers-head">
        <span className="map-layers-title">레이어</span>
        <button type="button" className="rowbtn" onClick={layers.allOn}>모두 켜기</button>
        <button type="button" className="rowbtn" onClick={layers.allOff}>모두 끄기</button>
        {showLabelToggle ? (
          <label className="switch-line">
            <input type="checkbox" checked={layers.showLabels} onChange={(e) => layers.setShowLabels(e.target.checked)} />
            이름 표시
          </label>
        ) : null}
        <label className="switch-line">
          <input type="checkbox" checked={layers.showArrows} onChange={(e) => layers.setShowArrows(e.target.checked)} />
          <i className="dock-scan-legend-swatch" /> {arrowLabel}
        </label>
      </div>
      <div className="map-layers-types">
        {layers.types.map(([key, label]) => (
          <label key={key} className="layer-chip">
            <input type="checkbox" checked={layers.isKeyVisible(key)} onChange={() => layers.toggleType(key)} />
            <i style={{ background: key === OTHER_LAYER_KEY ? "var(--text-muted)" : colors[key] || "var(--text-muted)" }} />
            {label}
          </label>
        ))}
      </div>
    </div>
  );
}

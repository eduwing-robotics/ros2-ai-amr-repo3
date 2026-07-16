import { useEffect, useId, useRef, useState } from "react";
import { OTHER_LAYER_KEY } from "../features/mapEditor/constants";
import type { MarkerLayers } from "../hooks/useMarkerLayers";

/** 맵 마커 레이어 토글 UI — 타입별 체크박스 + 모두 켜기/끄기 + 연결 화살표. */
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

/** 맵 위 플로팅 레이어 버튼 + 팝오버. 설정을 맵 모서리에 붙이고 하단 밴드 공간을 회수한다. */
export function MapLayersPopover({
  layers,
  colors,
  arrowLabel,
  visibleCount,
  totalCount,
  showLabelToggle = true,
}: {
  layers: MarkerLayers;
  colors: Record<string, string>;
  arrowLabel?: string;
  visibleCount: number;
  totalCount: number;
  showLabelToggle?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        toggleRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="map-layers-popover" ref={rootRef} data-map-overlay>
      <button
        ref={toggleRef}
        type="button"
        className="map-layers-toggle"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`마커 레이어, 표시 ${visibleCount}/${totalCount}, ${open ? "펼쳐짐" : "접힘"}`}
        onClick={() => setOpen((v) => !v)}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 3 3 8l9 5 9-5-9-5z M3 12l9 5 9-5 M3 16l9 5 9-5" />
        </svg>
        레이어
        <span className="map-layers-count">{visibleCount}/{totalCount}</span>
      </button>
      <div id={panelId} className="map-layers-panel" role="group" aria-label="마커 레이어 설정" hidden={!open}>
        <MarkerLayerControls layers={layers} colors={colors} arrowLabel={arrowLabel} showLabelToggle={showLabelToggle} />
      </div>
    </div>
  );
}

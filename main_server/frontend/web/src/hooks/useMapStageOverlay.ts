import { useEffect, useMemo, useRef, useState } from "react";

/** 맵 스테이지 DOM 크기를 측정해 overlay 마커를 화면 px 고정으로 그릴 때 쓰는 배율. */
export function useMapStageOverlay(mapWidth?: number, mapHeight?: number) {
  const stageRef = useRef<HTMLDivElement>(null);
  const [stageSize, setStageSize] = useState<{ w: number; h: number } | null>(null);

  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      setStageSize({ w: entry.contentRect.width, h: entry.contentRect.height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [mapWidth, mapHeight]);

  const overlayScale = useMemo(() => {
    if (!stageSize || !mapWidth || !mapHeight) return null;
    return Math.min(stageSize.w / (mapWidth || 1000), stageSize.h / (mapHeight || 800));
  }, [stageSize, mapWidth, mapHeight]);

  const overlayReady = overlayScale != null && Number.isFinite(overlayScale) && overlayScale > 0;
  const u = overlayReady ? 1 / overlayScale : 1;

  return { stageRef, stageSize, overlayScale, overlayReady, u };
}

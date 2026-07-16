import { useCallback, useMemo, useState } from "react";
import { MARKER_LAYER_TYPES, layerKeyForType } from "../features/mapEditor/constants";

/** 맵 마커 레이어 가시성 상태. 타입별 표시/숨김 + 연결 화살표 토글, localStorage 영속. */
interface Stored {
  hidden: string[];
  arrows: boolean;
  labels: boolean;
}

function readStored(key: string): Stored {
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      const p = JSON.parse(raw) as Partial<Stored>;
      return {
        hidden: Array.isArray(p.hidden) ? p.hidden : [],
        arrows: p.arrows !== false,
        labels: p.labels === true,
      };
    }
  } catch {
    /* 무시 */
  }
  return { hidden: [], arrows: true, labels: false };
}

export interface MarkerLayers {
  types: [string, string][];
  isVisible: (waypointType: string) => boolean;
  isKeyVisible: (key: string) => boolean;
  toggleType: (key: string) => void;
  allOn: () => void;
  allOff: () => void;
  showArrows: boolean;
  setShowArrows: (v: boolean) => void;
  showLabels: boolean;
  setShowLabels: (v: boolean) => void;
}

export function useMarkerLayers(storageKey: string): MarkerLayers {
  const [state, setState] = useState<Stored>(() => readStored(storageKey));

  const update = useCallback((fn: (s: Stored) => Stored) => {
    setState((s) => {
      const next = fn(s);
      try {
        localStorage.setItem(storageKey, JSON.stringify(next));
      } catch {
        /* 무시 */
      }
      return next;
    });
  }, [storageKey]);

  const hidden = useMemo(() => new Set(state.hidden), [state.hidden]);

  const isKeyVisible = useCallback((key: string) => !hidden.has(key), [hidden]);
  const isVisible = useCallback((t: string) => !hidden.has(layerKeyForType(t)), [hidden]);

  const toggleType = useCallback((key: string) => update((s) => {
    const set = new Set(s.hidden);
    if (set.has(key)) set.delete(key);
    else set.add(key);
    return { ...s, hidden: [...set] };
  }), [update]);

  const allOn = useCallback(() => update((s) => ({ ...s, hidden: [] })), [update]);
  const allOff = useCallback(() => update((s) => ({ ...s, hidden: MARKER_LAYER_TYPES.map(([k]) => k) })), [update]);
  const setShowArrows = useCallback((v: boolean) => update((s) => ({ ...s, arrows: v })), [update]);
  const setShowLabels = useCallback((v: boolean) => update((s) => ({ ...s, labels: v })), [update]);

  return {
    types: MARKER_LAYER_TYPES,
    isVisible,
    isKeyVisible,
    toggleType,
    allOn,
    allOff,
    showArrows: state.arrows,
    setShowArrows,
    showLabels: state.labels,
    setShowLabels,
  };
}

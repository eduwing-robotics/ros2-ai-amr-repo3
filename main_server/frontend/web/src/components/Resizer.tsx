import { useCallback, useEffect, useRef, type RefObject } from "react";

export type ResizerOrientation = "horizontal" | "vertical";

export type ResizerProps = {
  orientation: ResizerOrientation;
  storageKey: string;
  cssVar: string;
  containerRef: RefObject<HTMLElement | null>;
  defaultSize: number;
  min: number;
  max: number;
  /** 거터 기준 크기가 늘어나는 패널: leading=거터 왼쪽/위, trailing=오른쪽/아래 */
  adjacent: "leading" | "trailing";
  className?: string;
};

function clamp(n: number, min: number, max: number) {
  return Math.min(max, Math.max(min, n));
}

function readStored(key: string, fallback: number, min: number, max: number) {
  try {
    const raw = localStorage.getItem(key);
    if (raw != null) {
      const n = Number(raw);
      if (Number.isFinite(n)) return clamp(n, min, max);
    }
  } catch {
    /* localStorage unavailable */
  }
  return fallback;
}

/** 패널 경계 드래그 거터 — CSS 변수 갱신 + localStorage 지속 */
export function Resizer({
  orientation,
  storageKey,
  cssVar,
  containerRef,
  defaultSize,
  min,
  max,
  adjacent,
  className = "",
}: ResizerProps) {
  const sizeRef = useRef(readStored(storageKey, defaultSize, min, max));
  const dragRef = useRef<{ start: number; startSize: number } | null>(null);
  const liveRef = useRef(sizeRef.current);

  const applySize = useCallback(
    (size: number) => {
      const next = clamp(size, min, max);
      sizeRef.current = next;
      liveRef.current = next;
      const el = containerRef.current;
      if (el) el.style.setProperty(cssVar, `${next}px`);
      try {
        localStorage.setItem(storageKey, String(next));
      } catch {
        /* ignore */
      }
    },
    [containerRef, cssVar, storageKey, min, max],
  );

  useEffect(() => {
    applySize(sizeRef.current);
  }, [applySize]);

  const deltaSign = adjacent === "leading" ? 1 : -1;

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = {
      start: orientation === "horizontal" ? e.clientX : e.clientY,
      startSize: sizeRef.current,
    };
    document.body.classList.add("layout-resizing");
  };

  const endDrag = () => {
    dragRef.current = null;
    document.body.classList.remove("layout-resizing");
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    const pos = orientation === "horizontal" ? e.clientX : e.clientY;
    const delta = (pos - dragRef.current.start) * deltaSign;
    applySize(dragRef.current.startSize + delta);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 40 : 12;
    const horiz = orientation === "horizontal";
    if (horiz && e.key === "ArrowLeft") {
      e.preventDefault();
      applySize(sizeRef.current - step * deltaSign);
    } else if (horiz && e.key === "ArrowRight") {
      e.preventDefault();
      applySize(sizeRef.current + step * deltaSign);
    } else if (!horiz && e.key === "ArrowUp") {
      e.preventDefault();
      applySize(sizeRef.current - step * deltaSign);
    } else if (!horiz && e.key === "ArrowDown") {
      e.preventDefault();
      applySize(sizeRef.current + step * deltaSign);
    } else if (e.key === "Home") {
      e.preventDefault();
      applySize(defaultSize);
    }
  };

  return (
    <div
      role="separator"
      aria-orientation={orientation}
      aria-valuenow={liveRef.current}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-label="패널 크기 조절"
      tabIndex={0}
      title="드래그로 크기 조절 · 더블클릭 초기화 · 화살표 키 미세 조절"
      className={`layout-resizer layout-resizer--${orientation} ${className}`.trim()}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onDoubleClick={() => applySize(defaultSize)}
      onKeyDown={onKeyDown}
    />
  );
}

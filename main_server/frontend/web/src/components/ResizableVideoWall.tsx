import { Children, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

type Axis = "column" | "row";
type DragState = { axis: Axis; index: number; start: number; weights: number[] } | null;

const MIN_TRACK = 0.12;

function equalTracks(count: number) {
  return Array.from({ length: Math.max(1, count) }, () => 1 / Math.max(1, count));
}

function normalize(values: number[]) {
  const total = values.reduce((sum, value) => sum + value, 0) || 1;
  return values.map((value) => value / total);
}

function storedTracks(key: string, count: number) {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) ?? "[]");
    if (Array.isArray(parsed) && parsed.length === count && parsed.every((value) => Number.isFinite(value))) {
      return normalize(parsed);
    }
  } catch {
    // Storage is optional.
  }
  return equalTracks(count);
}

export function ResizableVideoWall({ children }: { children: ReactNode }) {
  const items = Children.toArray(children);
  const wallRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragState>(null);
  const [size, setSize] = useState({ width: 1, height: 1 });

  const columns = useMemo(() => {
    if (items.length <= 1) return 1;
    const aspect = Math.max(.55, Math.min(2.4, size.width / size.height));
    const targetAspect = 16 / 9;
    let best = { columns: 1, score: Number.POSITIVE_INFINITY };
    for (let candidate = 1; candidate <= items.length; candidate += 1) {
      const candidateRows = Math.ceil(items.length / candidate);
      const cellAspect = aspect * candidateRows / candidate;
      const emptyCells = candidate * candidateRows - items.length;
      const score = Math.abs(Math.log(cellAspect / targetAspect)) + emptyCells * .42;
      if (score < best.score) best = { columns: candidate, score };
    }
    return best.columns;
  }, [items.length, size.height, size.width]);
  const rows = Math.max(1, Math.ceil(items.length / columns));
  const storageBase = `lms.camera-wall.${items.length}.${columns}x${rows}`;
  const [columnTracks, setColumnTracks] = useState(() => equalTracks(columns));
  const [rowTracks, setRowTracks] = useState(() => equalTracks(rows));

  useEffect(() => {
    const wall = wallRef.current;
    if (!wall) return;
    const update = () => setSize({ width: wall.clientWidth || 1, height: wall.clientHeight || 1 });
    update();
    const observer = new ResizeObserver(update);
    observer.observe(wall);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    setColumnTracks(storedTracks(`${storageBase}.columns`, columns));
    setRowTracks(storedTracks(`${storageBase}.rows`, rows));
  }, [columns, rows, storageBase]);

  const persist = (axis: Axis, tracks: number[]) => {
    try {
      localStorage.setItem(`${storageBase}.${axis === "column" ? "columns" : "rows"}`, JSON.stringify(tracks));
    } catch {
      // Storage is optional.
    }
  };

  const startDrag = (axis: Axis, index: number, event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = {
      axis,
      index,
      start: axis === "column" ? event.clientX : event.clientY,
      weights: [...(axis === "column" ? columnTracks : rowTracks)],
    };
    document.body.classList.add("camera-wall-resizing");
  };

  const moveDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    const extent = drag.axis === "column" ? size.width : size.height;
    const position = drag.axis === "column" ? event.clientX : event.clientY;
    const delta = (position - drag.start) / Math.max(1, extent);
    const pairTotal = drag.weights[drag.index] + drag.weights[drag.index + 1];
    const lower = Math.min(MIN_TRACK, pairTotal / 3);
    const nextLeading = Math.max(lower, Math.min(pairTotal - lower, drag.weights[drag.index] + delta));
    const next = [...drag.weights];
    next[drag.index] = nextLeading;
    next[drag.index + 1] = pairTotal - nextLeading;
    if (drag.axis === "column") setColumnTracks(next);
    else setRowTracks(next);
  };

  const endDrag = () => {
    const drag = dragRef.current;
    if (!drag) return;
    persist(drag.axis, drag.axis === "column" ? columnTracks : rowTracks);
    dragRef.current = null;
    document.body.classList.remove("camera-wall-resizing");
  };

  const cumulative = (tracks: number[], index: number) =>
    tracks.slice(0, index + 1).reduce((sum, value) => sum + value, 0) * 100;

  return (
    <div
      ref={wallRef}
      className="camera-video-wall"
      style={{
        gridTemplateColumns: columnTracks.map((track) => `minmax(0, ${track}fr)`).join(" "),
        gridTemplateRows: rowTracks.map((track) => `minmax(0, ${track}fr)`).join(" "),
      }}
    >
      {items}
      {columnTracks.slice(0, -1).map((_, index) => (
        <div
          key={`column-${index}`}
          className="camera-wall-divider camera-wall-divider--column"
          style={{ left: `${cumulative(columnTracks, index)}%` }}
          role="separator"
          aria-label={`카메라 열 ${index + 1} 크기 조절`}
          aria-orientation="vertical"
          onPointerDown={(event) => startDrag("column", index, event)}
          onPointerMove={moveDrag}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
        />
      ))}
      {rowTracks.slice(0, -1).map((_, index) => (
        <div
          key={`row-${index}`}
          className="camera-wall-divider camera-wall-divider--row"
          style={{ top: `${cumulative(rowTracks, index)}%` }}
          role="separator"
          aria-label={`카메라 행 ${index + 1} 크기 조절`}
          aria-orientation="horizontal"
          onPointerDown={(event) => startDrag("row", index, event)}
          onPointerMove={moveDrag}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
        />
      ))}
    </div>
  );
}

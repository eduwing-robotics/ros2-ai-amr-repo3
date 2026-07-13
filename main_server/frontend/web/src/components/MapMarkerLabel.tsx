/** 마커 이름 라벨 — pill 배경, pointer-events 없음. */
export function labelOffsetForType(type: string): { x: number; y: number } {
  switch (type) {
    case "approach":
      return { x: 14, y: -9 };
    case "storage":
      return { x: 12, y: -10 };
    case "inbound":
    case "outbound":
    case "pickup":
    case "dropoff":
      return { x: 12, y: -9 };
    case "home":
    case "charge":
      return { x: 11, y: -8 };
    default:
      return { x: 11, y: -7 };
  }
}

export function MapMarkerLabel({ name, type, className = "" }: { name: string; type: string; className?: string }) {
  const { x, y } = labelOffsetForType(type);
  const width = Math.max(28, name.length * 6.4 + 10);
  return (
    <g className={`zone-marker-label${className ? ` ${className}` : ""}`} pointerEvents="none">
      <rect className="marker-label-pill" x={x} y={y - 11} width={width} height={15} rx={7.5} />
      <text className="map-label marker-label-text" x={x + 5} y={y}>{name}</text>
    </g>
  );
}

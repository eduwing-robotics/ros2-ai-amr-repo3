interface BatteryIndicatorProps {
  value?: number | null;
  showLabel?: boolean;
  className?: string;
}

type BatteryLevel = "unknown" | "good" | "medium" | "warn" | "low" | "critical";

function batteryValue(value?: number | null): number | null {
  if (value == null || !Number.isFinite(Number(value))) return null;
  return Math.min(100, Math.max(0, Number(value)));
}

function batteryLevel(value: number | null): BatteryLevel {
  if (value == null) return "unknown";
  if (value <= 10) return "critical";
  if (value <= 20) return "low";
  if (value <= 35) return "warn";
  if (value <= 60) return "medium";
  return "good";
}

export function BatteryIndicator({ value, showLabel = false, className = "" }: BatteryIndicatorProps) {
  const normalized = batteryValue(value);
  const level = batteryLevel(normalized);
  const text = normalized == null ? "—" : `${Math.round(normalized)}%`;

  return (
    <span className={`battery-indicator battery-${level}${className ? ` ${className}` : ""}`} aria-label={`배터리 ${text}`}>
      {showLabel ? <span className="battery-label">배터리</span> : null}
      <span className="battery-icon" aria-hidden="true"><i style={{ width: `${normalized ?? 0}%` }} /></span>
      <span className="battery-value mono">{text}</span>
      {normalized != null && normalized <= 20 ? <span className="battery-alert" aria-hidden="true">⚠</span> : null}
    </span>
  );
}

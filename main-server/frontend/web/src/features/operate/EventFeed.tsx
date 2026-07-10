import { useMemo } from "react";
import { eventDotClass } from "../../lib/format";
import type { AppEvent } from "../../types";

export function EventFeed({ events, limit = 6 }: { events: AppEvent[]; limit?: number }) {
  const rows = useMemo(
    () => [...events]
      .sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")))
      .slice(0, limit),
    [events, limit],
  );

  if (rows.length === 0) return <div className="event-feed empty">최근 이벤트 없음</div>;

  return (
    <div className="event-feed" aria-label="실시간 알람">
      {rows.map((ev, i) => {
        const tone = eventDotClass(ev);
        return (
          <div key={`${ev.created_at}-${i}`} className={`event-feed-row ${tone}`}>
            <span className="mono event-time">{ev.created_at ? new Date(String(ev.created_at)).toLocaleTimeString() : "-"}</span>
            <span className="event-type">{ev.event_type ?? "EVENT"}</span>
            <span className="event-msg">{ev.message ?? ""}</span>
          </div>
        );
      })}
    </div>
  );
}

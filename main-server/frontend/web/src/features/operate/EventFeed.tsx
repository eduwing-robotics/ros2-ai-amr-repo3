import { useMemo } from "react";
import { eventDotClass, eventKey } from "../../lib/format";
import type { AppEvent } from "../../types";

export function EventFeed({
  events,
  limit = 6,
  ackedKeys,
  onAckAll,
}: {
  events: AppEvent[];
  limit?: number;
  ackedKeys: Set<string>;
  onAckAll: () => void;
}) {
  const rows = useMemo(
    () => [...events]
      .sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")))
      .slice(0, limit),
    [events, limit],
  );

  if (rows.length === 0) return <div className="event-feed empty">최근 이벤트 없음</div>;

  const unackedCount = rows.filter((event) => !ackedKeys.has(eventKey(event))).length;

  return (
    <div className="event-feed" aria-label="실시간 알람">
      <div className="event-feed-actions">
        <span>{unackedCount ? `미확인 ${unackedCount}` : "모두 확인됨"}</span>
        <button type="button" className="rowbtn" onClick={onAckAll} disabled={!unackedCount}>모두 확인</button>
      </div>
      {rows.map((ev, i) => {
        const tone = eventDotClass(ev);
        const acked = ackedKeys.has(eventKey(ev));
        return (
          <div key={`${ev.created_at}-${i}`} className={`event-feed-row ${tone}${acked ? " acked" : ""}`}>
            <span className="mono event-time">{ev.created_at ? new Date(String(ev.created_at)).toLocaleTimeString() : "-"}</span>
            <span className="event-type">{ev.event_type ?? "EVENT"}{acked ? <span className="event-ack-chip">확인됨</span> : null}</span>
            <span className="event-msg">{ev.message ?? ""}</span>
          </div>
        );
      })}
    </div>
  );
}

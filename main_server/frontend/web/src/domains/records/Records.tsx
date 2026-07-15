import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { type Column } from "../../components/DataTable";
import { FilterableTable } from "../../components/FilterableTable";
import { Pill } from "../../components/Pill";
import { cell, eventDotClass, eventTypeLabel, formatServerTime, shortId } from "../../lib/format";
import { useEvents, useItemChangeLogs, useMovementCommandRecords, useTaskLogs } from "./useEvents";
import type { ItemChangeLogRecord, RobotCommandRecord, TaskLogRecord } from "../../types";
import type { TimelineEvent } from "./useEvents";

const PAGE_SIZE = 25;

type TabKey = "events" | "tasks" | "movement" | "inventory";

const TAB_LABELS: Record<TabKey, string> = {
  events: "감사 이벤트",
  tasks: "작업 완료 (task_logs)",
  movement: "이동 증거",
  inventory: "재고 변경",
};

function paginate<T>(rows: T[], page: number) {
  const start = (page - 1) * PAGE_SIZE;
  return rows.slice(start, start + PAGE_SIZE);
}

function EventsTab({ rows }: { rows: TimelineEvent[] }) {
  const [typeFilter, setTypeFilter] = useState("");
  const [robotFilter, setRobotFilter] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(1);

  const types = useMemo(() => [...new Set(rows.map((r) => r.event_type).filter(Boolean))].sort(), [rows]);
  const robots = useMemo(() => [...new Set(rows.map((r) => r.robot_id).filter(Boolean))].sort(), [rows]);

  const filtered = useMemo(() => rows.filter((r) => {
    if (typeFilter && r.event_type !== typeFilter) return false;
    if (robotFilter && r.robot_id !== robotFilter) return false;
    if (from && (r.created_at ?? "") < from) return false;
    if (to && (r.created_at ?? "") > `${to}T23:59:59`) return false;
    return true;
  }), [rows, typeFilter, robotFilter, from, to]);

  const pageRows = paginate(filtered, page);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));

  const columns: Column<TimelineEvent>[] = [
    { header: "등급", cell: (r) => { const level = eventDotClass(r); return <span className={`event-severity event-severity--${level}`}><i aria-hidden="true" />{level === "err" ? "위험" : level === "warn" ? "주의" : "정보"}</span>; } },
    { header: "시각", className: "mono", cell: (r) => <span title={cell(r.created_at)}>{formatServerTime(r.created_at)}</span> },
    { header: "유형", cell: (r) => <span title={cell(r.event_type)}>{eventTypeLabel(r.event_type)}</span> },
    { header: "출처", cell: (r) => cell(r.source ?? r.layer ?? "evidence_events") },
    { header: "로봇", cell: (r) => cell(r.robot_id) },
    { header: "메시지", cell: (r) => cell(r.message) },
  ];

  return (
    <>
      <div className="toolbar records-filters">
        <select className="filter" value={typeFilter} onChange={(e) => { setTypeFilter(e.target.value); setPage(1); }}>
          <option value="">유형: 전체</option>
          {types.map((t) => <option key={t} value={t}>{eventTypeLabel(t)}</option>)}
        </select>
        <select className="filter" value={robotFilter} onChange={(e) => { setRobotFilter(e.target.value); setPage(1); }}>
          <option value="">로봇: 전체</option>
          {robots.map((id) => <option key={id} value={id!}>{id}</option>)}
        </select>
        <label className="date-filter">from<input type="date" value={from} onChange={(e) => { setFrom(e.target.value); setPage(1); }} /></label>
        <label className="date-filter">to<input type="date" value={to} onChange={(e) => { setTo(e.target.value); setPage(1); }} /></label>
        <span className="rowcount">{filtered.length}건</span>
      </div>
      <FilterableTable columns={columns} rows={pageRows} getKey={(r, i) => r.event_id ?? i}
        searchFields={["created_at", "event_type", "message", "robot_id"]} statusField="event_type"
        emptyText="이벤트 없음" rowClassName={(row) => `event-row event-row--${eventDotClass(row)}`} />
      <Pager page={page} total={totalPages} onChange={setPage} />
    </>
  );
}

function TasksTab() {
  const { data: rows = [], isLoading } = useTaskLogs(200);
  const [page, setPage] = useState(1);
  const pageRows = paginate(rows, page);
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const columns: Column<TaskLogRecord>[] = [
    { header: "task", cell: (r) => r.task_id },
    { header: "유형", cell: (r) => r.task_type },
    { header: "결과", cell: (r) => <Pill status={r.result} /> },
    { header: "요약", cell: (r) => cell(r.summary) },
    { header: "완료", className: "mono", cell: (r) => <span title={cell(r.finished_at)}>{formatServerTime(r.finished_at)}</span> },
  ];
  if (isLoading) return <div className="empty">불러오는 중…</div>;
  return (
    <>
      <FilterableTable columns={columns} rows={pageRows} getKey={(r) => r.id}
        searchFields={["task_id", "task_type", "result", "summary"]} statusField="result"
        emptyText="task_logs 없음" />
      <Pager page={page} total={totalPages} onChange={setPage} />
    </>
  );
}

function MovementTab({ rows }: { rows: RobotCommandRecord[] }) {
  const [page, setPage] = useState(1);
  const pageRows = paginate(rows, page);
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const columns: Column<RobotCommandRecord>[] = [
    { header: "시각", className: "mono", cell: (r) => <span title={r.created_at}>{formatServerTime(r.created_at)}</span> },
    { header: "로봇", cell: (r) => r.robot_id },
    { header: "명령", cell: (r) => r.command },
    { header: "상태", cell: (r) => <Pill status={r.status} /> },
    { header: "id", className: "mono", cell: (r) => shortId(r.command_id) },
  ];
  return (
    <>
      <p className="muted-hint">source: <code>evidence_events</code> (movement projection) · API: <code>GET /movement-commands</code></p>
      <FilterableTable columns={columns} rows={pageRows} getKey={(r) => r.command_id}
        searchFields={["created_at", "robot_id", "command", "status"]} statusField="status"
        emptyText="이동 증거 없음" />
      <Pager page={page} total={totalPages} onChange={setPage} />
    </>
  );
}

function InventoryChangesTab() {
  const { data: rows = [], isLoading } = useItemChangeLogs(200);
  const [page, setPage] = useState(1);
  const pageRows = paginate(rows, page);
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const columns: Column<ItemChangeLogRecord>[] = [
    { header: "시각", className: "mono", cell: (r) => <span title={cell(r.changed_at)}>{formatServerTime(r.changed_at)}</span> },
    { header: "품목", cell: (r) => cell(r.item_code) },
    { header: "슬롯", cell: (r) => cell(r.slot_id) },
    { header: "층", cell: (r) => cell(r.floor ?? 1) },
    { header: "유형", cell: (r) => <span title={cell(r.event_type)}>{eventTypeLabel(r.event_type)}</span> },
    { header: "이전", cell: (r) => cell(r.quantity_before) },
    { header: "이후", cell: (r) => cell(r.quantity_after) },
    { header: "사유", cell: (r) => cell(r.reason) },
  ];
  if (isLoading) return <div className="empty">불러오는 중…</div>;
  return (
    <>
      <p className="muted-hint">source: <code>item_change_logs</code> (append-only) · API: <code>GET /item-change-logs</code></p>
      <FilterableTable columns={columns} rows={pageRows} getKey={(r) => r.id}
        searchFields={["changed_at", "item_code", "slot_id", "event_type", "reason"]} statusField="event_type"
        emptyText="재고 변경 이력 없음" />
      <Pager page={page} total={totalPages} onChange={setPage} />
    </>
  );
}

function Pager({ page, total, onChange }: { page: number; total: number; onChange: (p: number) => void }) {
  if (total <= 1) return null;
  return (
    <div className="pager">
      <button className="btn secondary" disabled={page <= 1} onClick={() => onChange(page - 1)}>이전</button>
      <span>{page} / {total}</span>
      <button className="btn secondary" disabled={page >= total} onClick={() => onChange(page + 1)}>다음</button>
    </div>
  );
}

export function Records({
  variant = "full",
  initialTab,
}: {
  variant?: "full" | "operate";
  initialTab?: string;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabs: TabKey[] = variant === "operate"
    ? ["events", "tasks"]
    : ["events", "tasks", "movement", "inventory"];
  const tabParam = (searchParams.get("tab") ?? initialTab ?? "events") as TabKey;
  const tab = tabs.includes(tabParam) ? tabParam : tabs[0];

  const { data: events = [], isLoading: eventsLoading } = useEvents();
  const { data: movements = [] } = useMovementCommandRecords();

  const setTab = (t: TabKey) => {
    const next = new URLSearchParams(searchParams);
    next.set("tab", t);
    setSearchParams(next, { replace: true });
  };

  return (
    <div className={`records-page${variant === "operate" ? " records-compact" : ""}`}>
      {variant === "full" ? (
        <div className="ops-heading">
          <div>
            <h2>기록</h2>
            <p>감사 이벤트·작업 완료·이동 증거·재고 변경 — DB source 테이블 기반 read-only 조회</p>
          </div>
        </div>
      ) : null}
      <div className="tab-bar">
        {tabs.map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>
      <div className="panel records-panel">
        {tab === "events" && (eventsLoading ? <div className="empty">불러오는 중…</div> : <EventsTab rows={events} />)}
        {tab === "tasks" && <TasksTab />}
        {tab === "movement" && <MovementTab rows={movements} />}
        {tab === "inventory" && <InventoryChangesTab />}
      </div>
    </div>
  );
}

import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { type Column } from "../../components/DataTable";
import { FilterableTable } from "../../components/FilterableTable";
import { Pill } from "../../components/Pill";
import { cell, eventDotClass, eventTypeLabel, formatServerTime, shortId } from "../../lib/format";
import { useEvents, useItemChangeLogs, useMovementCommandRecords, useTaskLogs } from "./useEvents";
import { useCommLogs } from "../../hooks/useCommLogs";
import type { CommLog } from "../../hooks/useCommLogs";
import type { ItemChangeLogRecord, RobotCommandRecord, TaskLogRecord } from "../../types";
import type { TimelineEvent } from "./useEvents";
import { summarizePollMetrics } from "./recordMetrics";

const PAGE_SIZE = 25;

type TabKey = "events" | "tasks" | "inventory" | "communications";

const TAB_LABELS: Record<TabKey, string> = {
  events: "운영 이벤트",
  tasks: "작업 이력",
  inventory: "재고 이력",
  communications: "시스템 상태",
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
  const [view, setView] = useState<"tasks" | "movement">("tasks");
  const { data: rows = [], isLoading } = useTaskLogs(200, view === "tasks");
  const { data: movements = [] } = useMovementCommandRecords(200, view === "movement");
  const [page, setPage] = useState(1);
  const pageRows = paginate(rows, page);
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const columns: Column<TaskLogRecord>[] = [
    { header: "작업", cell: (r) => r.task_id },
    { header: "유형", cell: (r) => r.task_type },
    { header: "결과", cell: (r) => <Pill status={r.result} /> },
    { header: "요약", cell: (r) => cell(r.summary) },
    { header: "완료", className: "mono", cell: (r) => <span title={cell(r.finished_at)}>{formatServerTime(r.finished_at)}</span> },
  ];
  if (view === "movement") return <>
    <RecordKindSwitch view={view} onChange={setView} />
    <MovementHistory rows={movements} />
  </>;
  if (isLoading) return <div className="empty">불러오는 중…</div>;
  return (
    <>
      <RecordKindSwitch view={view} onChange={setView} />
      <FilterableTable columns={columns} rows={pageRows} getKey={(r) => r.id}
        searchFields={["task_id", "task_type", "result", "summary"]} statusField="result"
        emptyText="완료된 작업 이력 없음" />
      <Pager page={page} total={totalPages} onChange={setPage} />
    </>
  );
}

function RecordKindSwitch({ view, onChange }: { view: "tasks" | "movement"; onChange: (view: "tasks" | "movement") => void }) {
  return <div className="toolbar records-filters records-kind-switch">
    <button type="button" className={view === "tasks" ? "btn active" : "btn secondary"} onClick={() => onChange("tasks")}>작업 결과</button>
    <button type="button" className={view === "movement" ? "btn active" : "btn secondary"} onClick={() => onChange("movement")}>이동 명령</button>
  </div>;
}

function MovementHistory({ rows }: { rows: RobotCommandRecord[] }) {
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
      <FilterableTable columns={columns} rows={pageRows} getKey={(r) => r.command_id}
        searchFields={["created_at", "robot_id", "command", "status"]} statusField="status"
        emptyText="이동 명령 이력 없음" />
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
      <FilterableTable columns={columns} rows={pageRows} getKey={(r) => r.id}
        searchFields={["changed_at", "item_code", "slot_id", "event_type", "reason"]} statusField="event_type"
        emptyText="재고 변경 이력 없음" />
      <Pager page={page} total={totalPages} onChange={setPage} />
    </>
  );
}

const heartbeatLabel = (status?: string | number) => ({
  initial_connected: "최초 연결",
  initial_unreachable: "최초 실패",
  recovered: "연결 복구",
  unreachable: "연결 끊김",
} as Record<string, string>)[String(status || "")] || String(status || "—");

const communicationResultLabel = (row: CommLog) => {
  if (row.heartbeat) return heartbeatLabel(row.status);
  if (row.status === "auth_error") return "인증 오류";
  if (row.status === "auth_recovered") return "인증 복구";
  const code = typeof row.status === "number" ? row.status : Number(row.status);
  if (code >= 200 && code < 300) return "요청 성공";
  if (code === 400) return "잘못된 요청";
  if (code === 401) return "인증 필요";
  if (code === 403) return "접근 거부";
  if (code === 404) return "대상을 찾을 수 없음";
  if (code === 408) return "응답 시간 초과";
  if (code === 409) return "요청 충돌";
  if (code === 429) return "요청 한도 초과";
  if (code >= 500) return "연동 서버 오류";
  const status = String(row.status || "");
  if (status === "unreachable") return "서버 연결 실패";
  if (status === "timeout") return "응답 시간 초과";
  if (status === "invalid_json" || status === "invalid_response") return "잘못된 서버 응답";
  return row.ok ? "요청 성공" : "요청 실패";
};

const communicationTargetLabel = (row: CommLog) => ({
  image: "영상 이미지",
  overlay: "영상 분석 정보",
  frame_stream: "원본 영상 스트림",
  overlay_stream: "분석 영상 스트림",
  heartbeat: "연결 상태",
  webrtc_offer: "WebRTC 연결",
} as Record<string, string>)[String(row.target || "")] || String(row.source || row.target || "—");

function CommunicationsTab() {
  const [service, setService] = useState("");
  const { data, isLoading } = useCommLogs(service, 200);
  const rows = data?.logs ?? [];
  const metrics = data?.poll_metrics ?? [];
  const metricSummary = summarizePollMetrics(metrics);
  const columns: Column<CommLog>[] = [
    { header: "시각", className: "mono", cell: (r) => <span title={cell(r.finished_at || r.started_at)}>{formatServerTime(r.finished_at || r.started_at)}</span> },
    { header: "서비스", cell: (r) => cell(r.service) },
    { header: "대상", cell: (r) => <span title={cell(r.source || r.target)}>{communicationTargetLabel(r)}</span> },
    { header: "결과", cell: (r) => <span title={r.status == null ? "" : "원본 상태: " + String(r.status)}><Pill status={r.ok ? "ok" : "error"} /> {communicationResultLabel(r)}</span> },
    { header: "내용", cell: (r) => cell(r.detail) },
    { header: "반복", className: "mono", cell: (r) => r.heartbeat || r.status === "auth_error" ? String(r.repeat_count || 1) + "회" : "—" },
    { header: "최근 확인", className: "mono", cell: (r) => r.heartbeat || r.status === "auth_error" ? formatServerTime(r.last_checked_at) : "—" },
    { header: "응답 시간", className: "mono", cell: (r) => r.elapsed_ms == null ? "—" : <>{r.elapsed_ms} ms</> },
  ];
  return <>
    <div className="toolbar records-filters">
      <select className="filter" aria-label="서비스 필터" value={service} onChange={(e) => setService(e.target.value)}>
        <option value="">서비스: 전체</option>
        <option value="movement">Movement</option>
        <option value="vision">Vision</option>
        <option value="camera">Camera</option>
      </select>
      <span className="rowcount">운영 사건 {rows.length}건</span>
      <span className="rowcount">폴링 {metricSummary.requests.toLocaleString()}회 · 성공률 {metricSummary.successRate}% · 평균 {metricSummary.averageMs}ms</span>
    </div>
    {isLoading ? <div className="empty">불러오는 중…</div> : <FilterableTable columns={columns} rows={rows}
      getKey={(r, i) => [r.started_at, r.service, i].join("-")}
      searchFields={["started_at", "finished_at", "service", "source", "target", "status", "detail", "url"]} statusField="status"
      emptyText="통신 기록 없음" />}
  </>;
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
    : ["events", "tasks", "inventory", "communications"];
  const tabParam = (searchParams.get("tab") ?? initialTab ?? "events") as TabKey;
  const tab = tabs.includes(tabParam) ? tabParam : tabs[0];

  const { data: events = [], isLoading: eventsLoading } = useEvents(200, tab === "events");

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
            <p>운영 이벤트·작업·재고·시스템 상태를 시간순으로 조회합니다</p>
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
        {tab === "inventory" && <InventoryChangesTab />}
        {tab === "communications" && <CommunicationsTab />}
      </div>
    </div>
  );
}

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Drawer } from "../../components/Drawer";
import { Resizer } from "../../components/Resizer";
import { CollapsiblePanel } from "../../components/CollapsiblePanel";
import { OPERATE_SLIM_NAV, routePath } from "../../app/menus";
import { useStatus } from "../../hooks/useStatus";
import { useEmergency } from "../../hooks/useEmergency";
import { useRobotConnectivity } from "../../hooks/useRobotConnectivity";
import { eventDotClass, eventKey, eventTypeLabel } from "../../lib/format";
import { DashboardMap } from "../map/DashboardMap";
import { LiveCamera } from "../vision/LiveCamera";
import { Teleop } from "../movement/Teleop";
import { MapGotoOperate } from "../movement/MapGotoOperate";
import { WorkOrderForm } from "./WorkOrderForm";
import { WorkOrderQueue } from "./WorkOrderQueue";
import { TaskRecoveryBanner, useRecoveryAttentionTasks } from "./TaskRecoveryPanel";
import { InventoryView } from "./InventoryView";
import { Records } from "../records/Records";
import { RobotMonitorCard } from "./RobotMonitorCard";
import { GotoTargetProvider } from "./GotoTargetContext";
import type { AppEvent, CameraHealth, CameraSource, MovementHealth, Robot } from "../../types";

const camerasForRobot = (robotId: string, cameras: CameraSource[]) => cameras.filter((camera) => camera.robot_id === robotId);
const globalCameras = (cameras: CameraSource[]) => cameras.filter((camera) => !camera.robot_id);

function EventFeed({ events, limit = 6 }: { events: AppEvent[]; limit?: number }) {
  const rows = [...events]
    .sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")))
    .slice(0, limit);
  if (!rows.length) return <div className="event-feed empty">최근 이벤트 없음</div>;
  return (
    <div className="event-feed" aria-label="실시간 알람">
      {rows.map((event, index) => (
        <div key={`${event.created_at}-${index}`} className={`event-feed-row ${eventDotClass(event)}`}>
          <span className="mono event-time">{event.created_at ? new Date(String(event.created_at)).toLocaleTimeString() : "-"}</span>
          <span className="event-type" title={event.event_type ?? undefined}>{eventTypeLabel(event.event_type)}</span>
          <span className="event-msg">{event.message ?? ""}</span>
        </div>
      ))}
    </div>
  );
}

/* 상단 KPI 글랜스 스트립 (ISA-101 L1: 2초 스캔) — 평상시 무채색, 이상 시에만 좌보더+배경 강조.
   상태는 색+텍스트 병기(색 단독 금지). 값은 비례 숫자(스탯 타일 규격). */
function OperatorKpiStrip({
  robotsTotal,
  onlineCount,
  emergencyCount,
  activeTaskCount,
  queuedTaskCount,
  runningTaskCount,
  recoveryCount,
  errCount,
  warnCount,
  tasksOpen,
  onToggleTasks,
  alarmsOpen,
  onToggleAlarms,
}: {
  robotsTotal: number;
  onlineCount: number;
  emergencyCount: number;
  activeTaskCount: number;
  queuedTaskCount: number;
  runningTaskCount: number;
  recoveryCount: number;
  errCount: number;
  warnCount: number;
  tasksOpen: boolean;
  onToggleTasks: () => void;
  alarmsOpen: boolean;
  onToggleAlarms: () => void;
}) {
  const robotState = robotsTotal > 0 && onlineCount === 0 ? " err" : onlineCount < robotsTotal ? " warn" : "";
  // 확인(ack)된 알람은 색·카운트에서 제외 — 미확인 알람만 강조
  const alarmState = errCount ? " err" : warnCount ? " warn" : "";
  const alarmCount = errCount + warnCount;
  return (
    <div className="operator-kpi-strip" role="group" aria-label="현황 요약">
      <div className={`kpi-tile${robotState}`}>
        <span className="kpi-label">로봇 연결</span>
        <span className="kpi-value">
          {onlineCount}
          <span className="kpi-value-sub"> / {robotsTotal}</span>
        </span>
        <span className="kpi-hint">
          {robotsTotal === 0 ? "등록된 로봇 없음" : onlineCount < robotsTotal ? `${robotsTotal - onlineCount}대 오프라인` : "전체 온라인"}
        </span>
      </div>
      <button
        type="button"
        className={`kpi-tile kpi-tile-btn${recoveryCount ? " warn" : ""}`}
        onClick={onToggleTasks}
        aria-expanded={tasksOpen}
        aria-controls="operator-tasks-workspace"
      >
        <span className="kpi-label">작업</span>
        <span className="kpi-value">{activeTaskCount}</span>
        <span className="kpi-hint">
          예약 {queuedTaskCount} · 진행 {runningTaskCount}
          {recoveryCount ? ` · 복구 ${recoveryCount}` : ""}
        </span>
      </button>
      <button
        type="button"
        className={`kpi-tile kpi-tile-btn${alarmState}`}
        onClick={onToggleAlarms}
        aria-expanded={alarmsOpen}
        aria-controls="operator-alarm-panel"
        aria-label={`알람, 미확인 ${alarmCount}건, ${alarmsOpen ? "펼쳐짐" : "접힘"}`}
      >
        <span className="kpi-label">알람 {alarmsOpen ? "⌄" : "⌃"}</span>
        <span className="kpi-value">{alarmCount}</span>
        <span className="kpi-hint">{alarmCount ? `위험 ${errCount} · 주의 ${warnCount}` : "이상 없음"}</span>
      </button>
      <div className={`kpi-tile${emergencyCount ? " err" : ""}`}>
        <span className="kpi-label">E-STOP</span>
        <span className="kpi-value">{emergencyCount ? `${emergencyCount}대` : "정상"}</span>
        <span className="kpi-hint">{emergencyCount ? "비상 정지 발동" : "비상 정지 없음"}</span>
      </div>
    </div>
  );
}

/* 알람 확인(ack) 상태 — 확인한 이벤트 키를 localStorage에 보관해 새로고침에도 유지.
   현재 스냅샷에 없는 키는 저장 시 정리해 무한 증가를 막는다. */
const ALARM_ACK_STORAGE_KEY = "lms.alarms.acked";

function loadAckedAlarmKeys(): Set<string> {
  try {
    const raw = localStorage.getItem(ALARM_ACK_STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed.map(String) : []);
  } catch {
    return new Set();
  }
}

/* 알람 확장 패널 — KPI 알람 타일 클릭으로 열리는 err/warn 이벤트 목록 + 모두 확인 */
function AlarmPanel({
  alarms,
  ackedKeys,
  unackedCount,
  onAckAll,
}: {
  alarms: AppEvent[];
  ackedKeys: Set<string>;
  unackedCount: number;
  onAckAll: () => void;
}) {
  return (
    <section className="operator-alarm-panel panel" id="operator-alarm-panel" aria-label="알람 이벤트">
      <div className="operator-alarm-head">
        <h2>알람 이벤트{unackedCount ? ` · 미확인 ${unackedCount}` : ""}</h2>
        <button type="button" className="rowbtn" onClick={onAckAll} disabled={!unackedCount}>
          모두 확인
        </button>
      </div>
      {alarms.length === 0 ? (
        <div className="event-feed empty">알람 이벤트 없음</div>
      ) : (
        <div className="event-feed">
          {alarms.map((event) => {
            const key = eventKey(event);
            const acked = ackedKeys.has(key);
            return (
              <div key={key} className={`event-feed-row ${eventDotClass(event)}${acked ? " acked" : ""}`}>
                <span className="mono event-time">
                  {event.created_at ? new Date(String(event.created_at)).toLocaleTimeString() : "-"}
                </span>
                <span className="event-type" title={event.event_type ?? undefined}>
                  {eventTypeLabel(event.event_type)}
                  {acked ? <span className="event-ack-chip">확인됨</span> : null}
                </span>
                <span className="event-msg">{event.message ?? ""}</span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

/* 역할 규칙: 드로어(좌) = 실행(폼·컨트롤 — 입출고·수동조작), 하단 탭 = 조회(테이블·이력 — 작업·재고·기록) */
type DrawerKey = "inout" | "control" | null;
type TrayPanelKey = "tasks" | "inventory" | "records";

function resolveDrawer(section: string | undefined, drawerParam: string | null): DrawerKey {
  if (section === "inout") return "inout";
  if (drawerParam === "inout") return "inout";
  if (drawerParam === "control") return "control";
  return null;
}

function resolveTrayPanel(section: string | undefined, panelParam: string | null): TrayPanelKey | null {
  if (panelParam === "tasks" || section === "tasks") return "tasks";
  if (panelParam === "inventory") return "inventory";
  if (panelParam === "records") return "records";
  return null;
}

function useNarrowOperatorLayout() {
  const query = "(max-width: 1200px)";
  const [matches, setMatches] = useState(() => (
    typeof window !== "undefined" && window.matchMedia(query).matches
  ));

  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return matches;
}

function OperatorNavIcon({ label }: { label: string }) {
  const path = label === "관제"
    ? "M3 13h4v8H3z M10 3h4v18h-4z M17 8h4v13h-4z"
    : label === "입출고"
      ? "M4 7h12 M12 3l4 4-4 4 M20 17H8 M12 13l-4 4 4 4"
      : label === "조작"
        ? "M9 3h6v6h6v6h-6v6H9v-6H3V9h6z M12 7v0 M12 17v0 M7 12h0 M17 12h0"
        : label === "작업"
          ? "M5 4h14v16H5z M8 8h8 M8 12h8 M8 16h5"
          : label === "재고"
            ? "M4 7l8-4 8 4v10l-8 4-8-4z M4 7l8 4 8-4 M12 11v10"
            : "M6 3h12v18H6z M9 8h6 M9 12h6 M9 16h4";
  return (
    <svg className="slim-nav-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d={path} />
    </svg>
  );
}

export function OperatorShell() {
  const navigate = useNavigate();
  const { section } = useParams();
  const [searchParams] = useSearchParams();
  const drawer = resolveDrawer(section, searchParams.get("drawer"));
  const trayPanel = resolveTrayPanel(section, searchParams.get("panel"));
  const taskPanelOpen = trayPanel === "tasks";
  const trayOpen = trayPanel !== null;
  const isNarrowLayout = useNarrowOperatorLayout();
  const { data, isLoading, isError, error, refetch } = useStatus();
  const { emergencyRobots, isRobotEmergency } = useEmergency();
  const { data: recoveryTasks = [] } = useRecoveryAttentionTasks();
  const taskWorkspaceToggleRef = useRef<HTMLButtonElement>(null);
  const taskFocusRequestedRef = useRef(false);

  const robots = data?.robots ?? [];
  const cameras = data?.camera_sources ?? [];
  const tasks = data?.tasks ?? [];
  const events = useMemo(() => data?.events ?? [], [data?.events]);
  const globalCams = globalCameras(cameras);
  const cameraOnline = Boolean(((data?.system ?? {}) as { camera_health?: CameraHealth }).camera_health?.ok);
  const { onlineCount } = useRobotConnectivity(robots);

  // 드로어(실행)와 하단 탭(조회)은 독립 축 — 서로 열림 상태를 보존한다.
  const toggleTrayPanel = useCallback((key: TrayPanelKey) => {
    if (key === "tasks" && trayPanel !== "tasks") taskFocusRequestedRef.current = true;
    const drawerParam = searchParams.get("drawer");
    const keepDrawer = drawerParam ? `drawer=${drawerParam}` : "";
    if (trayPanel === key) {
      navigate(keepDrawer ? `/operate/control?${keepDrawer}` : "/operate/control");
    } else {
      navigate(`/operate/control?${keepDrawer ? `${keepDrawer}&` : ""}panel=${key}`);
    }
  }, [navigate, trayPanel, searchParams]);

  // 드로어도 토글 — 다시 누르면 닫히고, 하단 탭(panel) 상태는 건드리지 않는다.
  const toggleDrawer = useCallback((key: Exclude<DrawerKey, null>) => {
    const panel = searchParams.get("panel");
    const keepPanel = panel ? `panel=${panel}` : "";
    if (drawer === key) {
      navigate(keepPanel ? `/operate/control?${keepPanel}` : "/operate/control");
    } else {
      navigate(`/operate/control?drawer=${key}${keepPanel ? `&${keepPanel}` : ""}`);
    }
  }, [navigate, drawer, searchParams]);

  const goNav = (route: string) => {
    const panelMatch = route.match(/panel=(\w+)/);
    if (panelMatch) {
      toggleTrayPanel(panelMatch[1] as TrayPanelKey);
      return;
    }
    const drawerMatch = route.match(/drawer=(\w+)/);
    if (drawerMatch) {
      toggleDrawer(drawerMatch[1] as Exclude<DrawerKey, null>);
      return;
    }
    navigate(routePath(route));
  };

  const closeDrawer = useCallback(() => {
    const panel = searchParams.get("panel");
    navigate(panel ? `/operate/control?panel=${panel}` : "/operate/control");
  }, [navigate, searchParams]);

  const drawerTitle = drawer === "inout" ? "입출고" : drawer === "control" ? "수동 조작 · 맵 이동" : "";

  const isActiveNav = (route: string) => {
    const base = route.split("?")[0];
    const current = section === "control" || !section ? "control" : section;
    const panelMatch = route.match(/panel=(\w+)/);
    if (panelMatch) return trayPanel === panelMatch[1];
    if (route.includes("drawer=inout")) return drawer === "inout";
    if (route.includes("drawer=control")) return drawer === "control";
    if (route === "operate/control") return current === "control" && drawer === null && trayPanel === null;
    return `operate/${current}` === base;
  };

  const robotEmergency = (robotId: string) =>
    Boolean((data?.movement_health?.[robotId] as MovementHealth | undefined)?.is_emergency);

  const stageRef = useRef<HTMLDivElement>(null);
  const mapColumnRef = useRef<HTMLDivElement>(null);
  const mapWrapRef = useRef<HTMLDivElement>(null);
  const insightBandRef = useRef<HTMLDivElement>(null);
  const allRobotsEmergency = robots.length > 0 && emergencyRobots.length >= robots.length;
  const movementAvailable = Object.values(data?.movement_health ?? {}).some((health) => health.ok);
  const activeTaskCount = tasks.filter(
    (t) => !["DONE", "COMPLETED", "CANCELLED"].includes(String(t.status || "").toUpperCase()),
  ).length;

  const queuedTaskCount = tasks.filter((t) =>
    ["PENDING", "QUEUED", "RESERVED", "PLANNED", "CREATED"].includes(String(t.status || "").toUpperCase()),
  ).length;
  const runningTaskCount = Math.max(0, activeTaskCount - queuedTaskCount);

  // 알람(err/warn) 이벤트 — 최신순. 확인(ack)된 알람은 카운트·강조색에서 제외한다.
  const [alarmsOpen, setAlarmsOpen] = useState(false);
  const [ackedAlarmKeys, setAckedAlarmKeys] = useState<Set<string>>(loadAckedAlarmKeys);
  const alarmEvents = useMemo(
    () =>
      events
        .filter((ev) => eventDotClass(ev) !== "off")
        .sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? ""))),
    [events],
  );
  const alarmCounts = useMemo(() => {
    let err = 0;
    let warn = 0;
    for (const ev of alarmEvents) {
      if (ackedAlarmKeys.has(eventKey(ev))) continue;
      if (eventDotClass(ev) === "err") err += 1;
      else warn += 1;
    }
    return { err, warn };
  }, [alarmEvents, ackedAlarmKeys]);

  const acknowledgeAlarms = useCallback(() => {
    // 현재 스냅샷의 알람 키만 저장 — 지나간 이벤트 키가 무한히 쌓이지 않게 정리
    const next = new Set(alarmEvents.map((ev) => eventKey(ev)));
    setAckedAlarmKeys(next);
    try {
      localStorage.setItem(ALARM_ACK_STORAGE_KEY, JSON.stringify([...next]));
    } catch {
      // 저장 실패(시크릿 모드 등)해도 세션 내 확인 상태는 유지된다
    }
  }, [alarmEvents]);

  useEffect(() => {
    if (section === "inout") {
      navigate("/operate/control?drawer=inout", { replace: true });
      return;
    }
    if (section === "tasks") {
      navigate("/operate/control?panel=tasks", { replace: true });
      return;
    }
    // 레거시 URL: 재고·기록은 드로어→하단 탭으로, 수동 조작은 하단 탭→드로어로 이동했다.
    const drawerParam = searchParams.get("drawer");
    const panelParam = searchParams.get("panel");
    if (drawerParam === "records" || drawerParam === "inventory") {
      navigate(`/operate/control?panel=${drawerParam}`, { replace: true });
    } else if (panelParam === "control") {
      navigate("/operate/control?drawer=control", { replace: true });
    }
  }, [navigate, section, searchParams]);

  useEffect(() => {
    if (!taskPanelOpen || !taskFocusRequestedRef.current) return;
    taskFocusRequestedRef.current = false;
    const timer = window.setTimeout(() => {
      insightBandRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      taskWorkspaceToggleRef.current?.focus({ preventScroll: true });
    }, 120);
    return () => window.clearTimeout(timer);
  }, [taskPanelOpen]);

  return (
    <GotoTargetProvider>
      <div className="operator-shell">
        <nav className="slim-nav" aria-label="운영 메뉴">
          {OPERATE_SLIM_NAV.map((it) => {
            const active = isActiveNav(it.route);
            const opensDrawer = it.route.includes("drawer=");
            const panelKey = it.route.match(/panel=(\w+)/)?.[1] ?? null;
            const badge = it.label === "작업" ? activeTaskCount : 0;
            const controlsTaskPanel = panelKey === "tasks";
            const navLabel = controlsTaskPanel
              ? `작업, 진행 중 ${badge}건, ${taskPanelOpen ? "펼쳐짐" : "접힘"}`
              : it.label === "조작"
                ? `수동 조작 · 맵 이동${movementAvailable ? "" : ", Movement 오프라인"}`
                : it.label;
            const ariaControls = controlsTaskPanel
              ? "operator-tasks-workspace"
              : panelKey
                ? `operator-${panelKey}-content`
                : opensDrawer
                  ? "operator-context-drawer"
                  : undefined;
            return (
              <Fragment key={it.key}>
                {/* 실행(드로어) ↔ 조회(하단 탭) 그룹 경계 */}
                {it.label === "입출고" || it.label === "작업" ? <span className="slim-nav-sep" aria-hidden="true" /> : null}
                <button
                  type="button"
                  className={active ? "active" : ""}
                  title={navLabel}
                  aria-label={navLabel}
                  aria-current={active && !panelKey ? "page" : undefined}
                  aria-controls={ariaControls}
                  aria-expanded={panelKey ? trayPanel === panelKey : opensDrawer ? active : undefined}
                  onClick={() => goNav(it.route)}
                >
                  <OperatorNavIcon label={it.label} />
                  <span className="slim-nav-label">{it.label}</span>
                  {badge > 0 ? <span className="slim-nav-badge" aria-hidden="true">{badge > 99 ? "99+" : badge}</span> : null}
                </button>
              </Fragment>
            );
          })}
        </nav>

        <div className={`operator-stage${drawer ? " drawer-open" : ""}`} ref={stageRef}>
          {drawer && isNarrowLayout ? (
            <div className="drawer-scrim" aria-hidden="true" onClick={closeDrawer} />
          ) : null}
          {drawer ? (
            <Drawer
              id="operator-context-drawer"
              title={drawerTitle}
              onClose={closeDrawer}
              className={`operator-drawer${drawer === "inout" ? " inout-drawer" : ""}`}
              modal={isNarrowLayout}
            >
              {drawer === "inout" ? (
                <WorkOrderForm
                  onClose={closeDrawer}
                  disabled={allRobotsEmergency}
                  emergencyRobots={emergencyRobots}
                  onSubmitted={() => {
                    // 실행(드로어) 결과가 조회(하단 작업 큐)에 나타나는 피드백 루프
                    if (trayPanel !== "tasks") navigate("/operate/control?drawer=inout&panel=tasks", { replace: true });
                  }}
                />
              ) : null}
              {drawer === "control" ? (
                <>
                  {!movementAvailable ? (
                    <div className="inline-alert warn operator-movement-warning" role="status">
                      Movement 서버에 연결할 수 없습니다. 수동 조작과 맵 이동을 사용할 수 없습니다.
                    </div>
                  ) : null}
                  <div className="operator-control-bar-inner">
                    <Teleop
                      robots={robots}
                      disabled={!movementAvailable}
                      isRobotEmergency={isRobotEmergency}
                      keyboardEnabled={drawer === "control"}
                    />
                    <MapGotoOperate robots={robots} disabled={!movementAvailable} isRobotEmergency={isRobotEmergency} />
                  </div>
                </>
              ) : null}
            </Drawer>
          ) : null}
          {drawer && !isNarrowLayout ? (
            <Resizer
              className="layout-resizer--drawer"
              orientation="horizontal"
              storageKey="lms.layout.operator-drawer"
              cssVar="--operator-drawer-w"
              containerRef={stageRef}
              defaultSize={360}
              min={280}
              max={520}
              adjacent="leading"
            />
          ) : null}

          <div className="operator-main">
            {emergencyRobots.length > 0 ? (
              <div className="inline-alert err operator-status-banner emergency-banner">
                비상 정지 활성 — {emergencyRobots.join(", ")} — 해당 로봇의 이동·입출고·수동 조작이 비활성화됩니다.
                해제는 헤더 ESTOP 해제 버튼을 사용하세요.
              </div>
            ) : null}
            {isError ? (
              <div className="inline-alert warn operator-status-banner">
                상태 조회 실패: {(error as Error)?.message}
                <button type="button" className="btn secondary slim" onClick={() => refetch()}>재시도</button>
              </div>
            ) : null}
            {isLoading && !data ? <div className="panel operator-map-loading">맵 불러오는 중…</div> : null}
            <OperatorKpiStrip
              robotsTotal={robots.length}
              onlineCount={onlineCount}
              emergencyCount={emergencyRobots.length}
              activeTaskCount={activeTaskCount}
              queuedTaskCount={queuedTaskCount}
              runningTaskCount={runningTaskCount}
              recoveryCount={recoveryTasks.length}
              errCount={alarmCounts.err}
              warnCount={alarmCounts.warn}
              tasksOpen={taskPanelOpen}
              onToggleTasks={() => toggleTrayPanel("tasks")}
              alarmsOpen={alarmsOpen}
              onToggleAlarms={() => setAlarmsOpen((open) => !open)}
            />
            {alarmsOpen ? (
              <AlarmPanel
                alarms={alarmEvents}
                ackedKeys={ackedAlarmKeys}
                unackedCount={alarmCounts.err + alarmCounts.warn}
                onAckAll={acknowledgeAlarms}
              />
            ) : null}
            <div className="operator-map-column" ref={mapColumnRef}>
              <div className="operator-map-wrap" ref={mapWrapRef}>
                <div className="operator-map-stage-wrap">
                  <DashboardMap gotoMode={!allRobotsEmergency} />
                </div>
                {globalCams.length > 0 ? (
                  <>
                    <Resizer
                      className="layout-resizer--cam"
                      orientation="horizontal"
                      storageKey="lms.layout.operator-cam"
                      cssVar="--operator-cam-w"
                      containerRef={mapWrapRef}
                      defaultSize={280}
                      min={200}
                      max={1600}
                      adjacent="trailing"
                    />
                    <div className="operator-map-camrail" aria-label="전역 카메라">
                      <h2 className="operator-map-camrail-head">전역 카메라</h2>
                      <LiveCamera cameras={globalCams} />
                    </div>
                  </>
                ) : null}
              </div>
              {trayOpen ? (
                <Resizer
                  key={trayPanel}
                  className="layout-resizer--band"
                  orientation="vertical"
                  storageKey="lms.layout.operator-band"
                  cssVar="--operator-band-h"
                  containerRef={mapColumnRef}
                  defaultSize={300}
                  min={160}
                  max={560}
                  adjacent="trailing"
                />
              ) : (
                /* 트레이 접힘 시엔 같은 경계로 맵 높이 상한(--map-cap 소스)을 조절 — 사용자별 지속 */
                <Resizer
                  key="map-height"
                  className="layout-resizer--band"
                  orientation="vertical"
                  storageKey="lms.layout.operator-map-h"
                  cssVar="--operator-map-h"
                  containerRef={mapColumnRef}
                  defaultSize={Math.round(Math.min(820, Math.max(360, (typeof window !== "undefined" ? window.innerHeight : 1080) * 0.62)))}
                  min={280}
                  max={900}
                  adjacent="leading"
                />
              )}
              <div
                className={`operator-insight-band ${trayOpen ? "open" : "collapsed"}`}
                id="operator-tasks-workspace"
                ref={insightBandRef}
                aria-label="작업 · 재고 · 기록 워크스페이스"
              >
                <div className="task-tray-bar">
                  <button
                    ref={taskWorkspaceToggleRef}
                    type="button"
                    className={`task-workspace-summary task-tray-tab${taskPanelOpen ? " active" : ""}${recoveryTasks.length ? " warn" : ""}`}
                    aria-expanded={taskPanelOpen}
                    aria-controls="operator-tasks-content"
                    aria-label={`작업 워크스페이스, 활성 ${activeTaskCount}건, 예약 ${queuedTaskCount}건, 진행 ${runningTaskCount}건, 복구 ${recoveryTasks.length}건, ${taskPanelOpen ? "펼쳐짐" : "접힘"}`}
                    onClick={() => toggleTrayPanel("tasks")}
                  >
                    <span className="task-workspace-title">작업 큐</span>
                    <span className="task-workspace-counts">
                      <span>활성 <b>{activeTaskCount}</b></span>
                      <span>예약 <b>{queuedTaskCount}</b></span>
                      <span>진행 <b>{runningTaskCount}</b></span>
                      {recoveryTasks.length ? <span className="task-recovery-count">복구 <b>{recoveryTasks.length}</b></span> : null}
                    </span>
                  </button>
                  <button
                    type="button"
                    className={`task-tray-tab${trayPanel === "inventory" ? " active" : ""}`}
                    aria-expanded={trayPanel === "inventory"}
                    aria-controls="operator-inventory-content"
                    aria-label={`재고, ${trayPanel === "inventory" ? "펼쳐짐" : "접힘"}`}
                    onClick={() => toggleTrayPanel("inventory")}
                  >
                    <span className="task-workspace-title">재고</span>
                  </button>
                  <button
                    type="button"
                    className={`task-tray-tab${trayPanel === "records" ? " active" : ""}`}
                    aria-expanded={trayPanel === "records"}
                    aria-controls="operator-records-content"
                    aria-label={`기록, ${trayPanel === "records" ? "펼쳐짐" : "접힘"}`}
                    onClick={() => toggleTrayPanel("records")}
                  >
                    <span className="task-workspace-title">기록</span>
                  </button>
                  <span className="task-workspace-action" aria-hidden="true">
                    {trayOpen ? "⌄ 접기" : "⌃ 펼치기"}
                  </span>
                </div>
                <div
                  id="operator-tasks-content"
                  className="task-workspace-content"
                  hidden={trayPanel !== "tasks"}
                >
                  <TaskRecoveryBanner />
                  <WorkOrderQueue />
                </div>
                <div
                  id="operator-inventory-content"
                  className="task-workspace-content"
                  hidden={trayPanel !== "inventory"}
                >
                  {trayPanel === "inventory" ? <InventoryView /> : null}
                </div>
                <div
                  id="operator-records-content"
                  className="task-workspace-content"
                  hidden={trayPanel !== "records"}
                >
                  {trayPanel === "records" ? <Records variant="operate" /> : null}
                </div>
              </div>
            </div>
          </div>

          <Resizer
            className="layout-resizer--rail"
            orientation="horizontal"
            storageKey="lms.layout.operator-rail"
            cssVar="--operator-rail-w"
            containerRef={stageRef}
            defaultSize={360}
            min={220}
            max={720}
            adjacent="trailing"
          />

          <aside className="operator-right-rail">
            {/* : 좁으면 상/하(카메라 위·알람 아래), 넓으면(≥600px) 좌/우 2컬럼 반응형 */}
            <div className="operator-rail-split">
              <div className="rail-region rail-region--monitor">
                <div className="robot-monitor-rail panel">
                  <div className="robot-monitor-rail-head">
                    <h2>로봇 모니터</h2>
                    <span className="robot-monitor-connectivity" title="pose 신선도 기준">
                      <span className={`dot ${onlineCount > 0 ? "on" : "off"}`} aria-hidden="true" />
                      로봇 {onlineCount}/{robots.length} 연결
                    </span>
                  </div>
                  <div className="rail-list robot-monitor-list">
                    {robots.length === 0 ? (
                      <div className="empty">로봇 없음</div>
                    ) : (
                      robots.map((r: Robot) => (
                        <RobotMonitorCard
                          key={r.robot_id}
                          robot={r}
                          cameras={camerasForRobot(r.robot_id, cameras)}
                          health={data?.movement_health?.[r.robot_id] as MovementHealth | undefined}
                          tasks={tasks}
                          emergency={robotEmergency(r.robot_id)}
                          cameraOnline={cameraOnline}
                        />
                      ))
                    )}
                  </div>
                </div>
              </div>

              <div className="rail-region rail-region--alarm">
                <CollapsiblePanel
                  title={events.length ? `알람 · 이벤트 (${events.length})` : "알람 · 이벤트"}
                  defaultOpen
                  className="robot-monitor-events"
                >
                  <EventFeed events={events} limit={30} />
                </CollapsiblePanel>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </GotoTargetProvider>
  );
}

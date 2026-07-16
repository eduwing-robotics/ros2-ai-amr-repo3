import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Drawer } from "../../components/Drawer";
import { Resizer } from "../../components/Resizer";
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
import { GotoTargetProvider } from "./GotoTargetContext";
import { FleetMissionDock } from "./FleetMissionDock";
import { RobotStatusDetails } from "./RobotStatusCard";
import { BatteryIndicator } from "../../components/BatteryIndicator";
import { Pill } from "../../components/Pill";
import type { CameraHealth, MovementHealth } from "../../types";
import { taskLifecycleOf } from "./taskLifecycle";


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
      <div className={`kpi-tile${recoveryCount ? " warn" : ""}`}>
        <span className="kpi-label">활성 작업</span>
        <span className="kpi-value">{activeTaskCount}</span>
        <span className="kpi-hint">
          예약 {queuedTaskCount} · 진행 {runningTaskCount}
          {recoveryCount ? ` · 복구 ${recoveryCount}` : ""}
        </span>
      </div>
      <div className={`kpi-tile${alarmState}`}>
        <span className="kpi-label">미확인 알람</span>
        <span className="kpi-value">{alarmCount}</span>
        <span className="kpi-hint">{alarmCount ? `위험 ${errCount} · 주의 ${warnCount}` : "이상 없음"}</span>
      </div>
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

/* 역할 규칙: 실행은 우측 문맥, 조회 목적지는 중앙 워크스페이스를 전환한다. */
type DrawerKey = "inout" | "control" | null;
type TrayPanelKey = "tasks" | "inventory" | "records";

function resolveDrawer(section: string | undefined, drawerParam: string | null): DrawerKey {
  if (section === "inout") return "inout";
  if (drawerParam === "inout") return "inout";
  if (drawerParam === "control") return "control";
  return null;
}

function resolveTrayPanel(section: string | undefined, panelParam: string | null): TrayPanelKey | null {
  if (section === "tasks" || panelParam === "tasks") return "tasks";
  if (section === "inventory" || panelParam === "inventory") return "inventory";
  if (section === "events" || section === "records" || panelParam === "records") return "records";
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
  const isNarrowLayout = useNarrowOperatorLayout();
  const { data, isLoading, isError, error, refetch } = useStatus();
  const { emergencyRobots, isRobotEmergency } = useEmergency();
  const { data: recoveryTasks = [] } = useRecoveryAttentionTasks();
  const liveSplitRef = useRef<HTMLDivElement>(null);
  const workbenchRef = useRef<HTMLDivElement>(null);

  const robots = data?.robots ?? [];
  const cameras = data?.camera_sources ?? [];
  const selectedRobotParam = searchParams.get("robot");
  const selectedRobot = robots.find((robot) => robot.robot_id === selectedRobotParam) ?? robots[0] ?? null;
  const selectedRobotId = selectedRobot?.robot_id ?? "";
  const [cameraRobotId, setCameraRobotId] = useState<string | null>(null);
  const cameraRobot = robots.find((robot) => robot.robot_id === cameraRobotId) ?? null;
  const cameraRobotSources = cameraRobotId ? cameras.filter((camera) => camera.robot_id === cameraRobotId) : [];
  const tasks = useMemo(() => data?.tasks ?? [], [data?.tasks]);
  const events = useMemo(() => data?.events ?? [], [data?.events]);
  const cameraOnline = Boolean(((data?.system ?? {}) as { camera_health?: CameraHealth }).camera_health?.ok);
  const { onlineCount } = useRobotConnectivity(robots);

  const workspaceSection = trayPanel === "tasks"
    ? "tasks"
    : trayPanel === "inventory"
      ? "inventory"
      : trayPanel === "records"
        ? "events"
        : "control";
  const workspacePath = "/operate/" + workspaceSection;

  const toggleTrayPanel = useCallback((key: TrayPanelKey) => {
    navigate("/operate/" + (key === "records" ? "events" : key));
  }, [navigate]);

  const contextPath = useCallback((nextDrawer: DrawerKey, robotId = selectedRobotId) => {
    const params = new URLSearchParams();
    if (robotId) params.set("robot", robotId);
    if (nextDrawer) params.set("drawer", nextDrawer);
    const query = params.toString();
    return workspacePath + (query ? `?${query}` : "");
  }, [selectedRobotId, workspacePath]);

  const toggleDrawer = useCallback((key: Exclude<DrawerKey, null>) => {
    navigate(contextPath(drawer === key ? null : key));
  }, [contextPath, drawer, navigate]);

  const selectRobot = useCallback((robotId: string) => {
    navigate(contextPath(drawer, robotId), { replace: true });
  }, [contextPath, drawer, navigate]);

  const openRobotControl = useCallback((robotId: string) => {
    navigate(contextPath("control", robotId));
  }, [contextPath, navigate]);

  const goNav = (route: string) => {
    const drawerMatch = route.match(/drawer=(\w+)/);
    if (drawerMatch) {
      toggleDrawer(drawerMatch[1] as Exclude<DrawerKey, null>);
      return;
    }
    navigate(routePath(route));
  };

  const closeDrawer = useCallback(() => {
    navigate(contextPath(null));
  }, [contextPath, navigate]);

  const drawerTitle = drawer === "inout" ? "입출고 요청" : drawer === "control" ? "수동 조작 · 맵 이동" : "";
  const pageMeta = trayPanel === "tasks"
    ? { title: "작업", description: "예약·진행·복구 작업을 조회하고 배정합니다." }
    : trayPanel === "inventory"
      ? { title: "재고", description: "품목과 슬롯별 현재 재고를 조회합니다." }
      : trayPanel === "records"
        ? { title: "이벤트", description: "운영 경고와 명령·작업 이력을 확인합니다." }
        : { title: "운영 개요", description: "현재 플로어 상태와 진행 중인 작업을 한 화면에서 확인합니다." };

  const isActiveNav = (route: string) => {
    const base = route.split("?")[0];
    const current = section === "control" || !section ? "control" : section;
    const panelMatch = route.match(/panel=(\w+)/);
    if (panelMatch) return trayPanel === panelMatch[1];
    if (route.includes("drawer=inout")) return drawer === "inout";
    if (route.includes("drawer=control")) return drawer === "control";
    if (route === "operate/control") return current === "control" && trayPanel === null;
    return `operate/${current}` === base;
  };

  const robotEmergency = (robotId: string) =>
    Boolean((data?.movement_health?.[robotId] as MovementHealth | undefined)?.is_emergency);

  const allRobotsEmergency = robots.length > 0 && emergencyRobots.length >= robots.length;
  const movementAvailable = Object.values(data?.movement_health ?? {}).some((health) => health.ok);
  const taskLifecycleCounts = useMemo(() => {
    const counts = { queued: 0, running: 0, recovery: 0 };
    for (const task of tasks) {
      const lifecycle = taskLifecycleOf(task.status);
      if (lifecycle === "queued" || lifecycle === "running" || lifecycle === "recovery") counts[lifecycle] += 1;
    }
    return counts;
  }, [tasks]);
  const queuedTaskCount = taskLifecycleCounts.queued;
  const runningTaskCount = taskLifecycleCounts.running;
  const activeTaskCount = queuedTaskCount + runningTaskCount + taskLifecycleCounts.recovery;

  // 알람(err/warn) 이벤트 — 최신순. 확인(ack)된 알람은 카운트·강조색에서 제외한다.
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
  const firstUnackedAlarm = alarmEvents.find((event) => !ackedAlarmKeys.has(eventKey(event)));

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
    const panelParam = searchParams.get("panel");
    if (panelParam === "tasks" || panelParam === "inventory" || panelParam === "records") {
      const target = panelParam === "records" ? "events" : panelParam;
      const drawerParam = searchParams.get("drawer");
      navigate("/operate/" + target + (drawerParam ? "?drawer=" + drawerParam : ""), { replace: true });
    } else if (panelParam === "control") {
      navigate("/operate/control?drawer=control", { replace: true });
    }
  }, [navigate, section, searchParams]);

  return (
    <GotoTargetProvider>
      <div className="operator-shell">
        <nav className="slim-nav" aria-label="운영 메뉴">
          <div className="operator-activity-rail">
            <div className="operator-nav-brand" aria-label="AMR Control">
              <span className="operator-nav-mark">AMR</span>
            </div>
            {OPERATE_SLIM_NAV.map((item) => {
              const active = isActiveNav(item.route);
              const badge = item.label === "작업" ? activeTaskCount : item.label === "이벤트" ? alarmCounts.err + alarmCounts.warn : 0;
              return (
                <button
                  type="button"
                  className={active ? "active" : ""}
                  title={item.label}
                  aria-label={item.label}
                  aria-current={active ? "page" : undefined}
                  aria-controls="operator-primary-pane operator-workspace-main"
                  onClick={() => goNav(item.route)}
                  key={item.key}
                >
                  <OperatorNavIcon label={item.label} />
                  <span className="slim-nav-label">{item.label}</span>
                  {badge > 0 ? <span className="slim-nav-badge" aria-hidden="true">{badge > 99 ? "99+" : badge}</span> : null}
                </button>
              );
            })}
            <span className="operator-nav-spacer" />
            <button type="button" className="operator-admin-link" aria-label="관리 공간" onClick={() => navigate("/admin/map")}>
              <OperatorNavIcon label="관리" />
              <span className="slim-nav-label">관리</span>
            </button>
            <div className="operator-user-chip" title="운영자 · 현장 제어 권한">
              <span className="operator-user-avatar">OP</span>
            </div>
          </div>
          <aside className="operator-primary-pane" id="operator-primary-pane" aria-label={`${pageMeta.title} 문맥`}>
            <header><span className="operator-eyebrow">PRIMARY VIEW</span><h2>{pageMeta.title}</h2><p>{pageMeta.description}</p></header>
            {workspaceSection === "control" ? (
              <div className="operator-primary-groups">
                <section><h3>실시간 관제</h3><p>맵과 전역 카메라를 같은 작업면에서 비교합니다.</p></section>
                <section className="operator-primary-metrics">
                  <span><b>{onlineCount}/{robots.length}</b> 로봇 연결</span>
                  <span><b>{activeTaskCount}</b> 활성 작업</span>
                  <span className={alarmCounts.err ? "err" : alarmCounts.warn ? "warn" : ""}><b>{alarmCounts.err + alarmCounts.warn}</b> 미확인 알람</span>
                </section>
                <section><h3>선택 규칙</h3><p>지도 마커·우측 로봇·하단 작업 행을 선택하면 같은 로봇 문맥이 강조됩니다.</p></section>
              </div>
            ) : workspaceSection === "tasks" ? (
              <div className="operator-primary-groups"><section><h3>작업 큐</h3><p>예약·진행·복구 작업을 우선순위 순으로 관리합니다.</p></section><section className="operator-primary-metrics"><span><b>{queuedTaskCount}</b> 예약</span><span><b>{runningTaskCount}</b> 진행</span><span className={recoveryTasks.length ? "warn" : ""}><b>{recoveryTasks.length}</b> 복구</span></section></div>
            ) : workspaceSection === "inventory" ? (
              <div className="operator-primary-groups"><section><h3>재고 조회</h3><p>품목별·슬롯별 재고와 가용 수량을 중앙 테이블에서 비교합니다.</p></section></div>
            ) : (
              <div className="operator-primary-groups"><section><h3>운영 이벤트</h3><p>위험과 주의 이벤트를 우선 확인하고 명령·작업 이력을 추적합니다.</p></section><section className="operator-primary-metrics"><span className={alarmCounts.err ? "err" : ""}><b>{alarmCounts.err}</b> 위험</span><span className={alarmCounts.warn ? "warn" : ""}><b>{alarmCounts.warn}</b> 주의</span></section></div>
            )}
            <footer><span className="dot on" aria-hidden="true" /> 물류센터 A · 1층</footer>
          </aside>
        </nav>

        <div className={`operator-stage${drawer ? " drawer-open" : ""}`}>
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
                  onSubmitted={() => refetch()}
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
                      robots={selectedRobot ? [selectedRobot] : []}
                      disabled={!movementAvailable}
                      isRobotEmergency={isRobotEmergency}
                      keyboardEnabled={drawer === "control"}
                    />
                    <MapGotoOperate robots={selectedRobot ? [selectedRobot] : []} disabled={!movementAvailable} isRobotEmergency={isRobotEmergency} />
                  </div>
                </>
              ) : null}
            </Drawer>
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
            {firstUnackedAlarm ? (
              <div className={`operator-priority-alert ${eventDotClass(firstUnackedAlarm)}`} role="status">
                <strong>{eventTypeLabel(firstUnackedAlarm.event_type)}</strong>
                <span>{firstUnackedAlarm.message ?? "확인이 필요한 이벤트가 있습니다."}</span>
                <span className="operator-alert-spacer" />
                <button type="button" className="rowbtn ghost" onClick={acknowledgeAlarms}>확인</button>
                <button type="button" className="rowbtn ghost" onClick={() => toggleTrayPanel("records")}>이벤트 보기</button>
              </div>
            ) : null}
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
            />
            <div className="operator-main-workbench" ref={workbenchRef}>
              <div className="operator-live-split" ref={liveSplitRef}>
                <div className="operator-primary-workspace">
                  {trayPanel === "tasks" ? (
                    <section className="operator-workspace" id="operator-workspace-main" aria-label="작업 워크스페이스">
                      <TaskRecoveryBanner />
                      <WorkOrderQueue />
                    </section>
                  ) : trayPanel === "inventory" ? (
                    <section className="operator-workspace" id="operator-workspace-main" aria-label="재고 워크스페이스">
                      <InventoryView />
                    </section>
                  ) : trayPanel === "records" ? (
                    <section className="operator-workspace" id="operator-workspace-main" aria-label="이벤트 워크스페이스">
                      <Records variant="operate" />
                    </section>
                  ) : (
                    <div className="operator-map-wrap" id="operator-workspace-main">
                      <div className="operator-map-stage-wrap">
                        <DashboardMap
                          gotoMode={drawer === "control" && !allRobotsEmergency}
                          selectedRobotId={selectedRobotId}
                          onRobotSelect={selectRobot}
                        />
                      </div>
                    </div>
                  )}
                </div>
                <Resizer className="operator-live-resizer" orientation="horizontal" storageKey="lms.layout.operator-map-width" cssVar="--operator-map-w" containerRef={liveSplitRef} defaultSize={720} min={420} max={1100} adjacent="leading" />
                <section className="operator-global-camera panel" aria-label="전역 카메라 및 전체 카메라 Grid">
                  <div className="operator-global-camera-head">
                    <div><h2>카메라 관제</h2><span className={`operator-camera-state ${cameraOnline ? "online" : "offline"}`}>{cameraOnline ? "LIVE" : "OFFLINE"}</span></div>
                    <span className="muted">Grid = 전체 소스</span>
                  </div>
                  <div className="operator-global-camera-body">
                    {cameras.length > 0 ? <LiveCamera cameras={cameras} /> : <div className="operator-camera-empty"><strong>전역 카메라가 등록되지 않았습니다.</strong><span>관리 공간에서 로봇에 귀속되지 않은 카메라 소스를 등록하세요.</span></div>}
                  </div>
                </section>
              </div>
              <Resizer className="operator-dock-resizer" orientation="vertical" storageKey="lms.layout.operator-task-queue-height" cssVar="--operator-dock-h" containerRef={workbenchRef} defaultSize={240} min={170} max={520} adjacent="trailing" />
              <FleetMissionDock robots={robots} selectedRobotId={selectedRobotId} onRobotSelect={selectRobot} />
            </div>
          </div>
          <aside className="operator-right-rail" aria-label="전체 로봇 상태와 명령">
            <section className="operator-fleet-panel panel">
              <header className="operator-fleet-head">
                <div><span className="operator-eyebrow">SECONDARY VIEW</span><h2>전체 로봇</h2></div>
                <span className="robot-monitor-connectivity"><span className={`dot ${onlineCount > 0 ? "on" : "off"}`} aria-hidden="true" />{onlineCount}/{robots.length} 연결</span>
              </header>
              {!movementAvailable ? (
                <div className="operator-fleet-warning" role="status">Movement 서버 오프라인 · 로봇 조작을 사용할 수 없습니다.</div>
              ) : null}
              <div className="operator-fleet-list">
                {robots.length === 0 ? <div className="empty">등록된 로봇이 없습니다.</div> : robots.map((robot) => {
                  const selected = selectedRobotId === robot.robot_id;
                  return (
                    <article className={`operator-fleet-card${selected ? " selected" : ""}${robotEmergency(robot.robot_id) ? " emergency" : ""}`} key={robot.robot_id}>
                      <button type="button" className="operator-fleet-select" onClick={() => { selectRobot(robot.robot_id); setCameraRobotId(robot.robot_id); }}>
                        <span><strong>{robot.display_name || robot.robot_id}</strong><small className="mono">{robot.robot_id}</small></span>
                        {robotEmergency(robot.robot_id) ? <span className="pill err">ESTOP</span> : <Pill status={robot.status} />}
                        <BatteryIndicator value={robot.battery} />
                      </button>
                      <RobotStatusDetails robot={robot} health={data?.movement_health?.[robot.robot_id] as MovementHealth | undefined} tasks={tasks} />
                      <button
                        type="button"
                        className="rowbtn operator-robot-command"
                        disabled={!movementAvailable || robotEmergency(robot.robot_id) || workspaceSection !== "control"}
                        title={workspaceSection !== "control" ? "수동 조작은 관제 목적지에서 사용합니다" : !movementAvailable ? "Movement 서버 오프라인" : `${robot.robot_id} 수동 조작`}
                        onClick={() => openRobotControl(robot.robot_id)}
                      >
                        조작 →
                      </button>
                    </article>
                  );
                })}
              </div>
            </section>
          </aside>
          {cameraRobot ? (
            <section className="operator-robot-camera-drawer panel" role="region" aria-label={`${cameraRobot.display_name || cameraRobot.robot_id} 카메라`}>
              <header><div><span className="operator-eyebrow">ROBOT CAMERA</span><h2>{cameraRobot.display_name || cameraRobot.robot_id}</h2></div><button type="button" className="rowbtn" aria-label="로봇 카메라 닫기" onClick={() => setCameraRobotId(null)}>닫기</button></header>
              <div className="operator-robot-camera-content">{cameraRobotSources.length ? <LiveCamera cameras={cameraRobotSources} /> : <div className="operator-camera-empty"><strong>등록된 로봇 카메라가 없습니다.</strong><span>관리 · 로봇 & 카메라에서 {cameraRobot.robot_id} 귀속 소스를 등록하세요.</span></div>}</div>
            </section>
          ) : null}
        </div>
      </div>
    </GotoTargetProvider>
  );
}

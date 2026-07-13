import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Drawer } from "../../components/Drawer";
import { Resizer } from "../../components/Resizer";
import { CollapsiblePanel } from "../../components/CollapsiblePanel";
import { OPERATE_SLIM_NAV, routePath } from "../../app/menus";
import { useStatus } from "../../hooks/useStatus";
import { useEmergency } from "../../hooks/useEmergency";
import { useRobotConnectivity } from "../../hooks/useRobotConnectivity";
import { eventDotClass, eventTypeLabel } from "../../lib/format";
import { DashboardMap } from "../map/DashboardMap";
import { LiveCamera } from "../vision/LiveCamera";
import { Teleop } from "../movement/Teleop";
import { MapGotoOperate } from "../movement/MapGotoOperate";
import { WorkOrderForm } from "./WorkOrderForm";
import { TaskQueue } from "./TaskQueue";
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

type DrawerKey = "inout" | "records" | "inventory" | null;
type TrayPanelKey = "tasks" | "control";

function resolveDrawer(section: string | undefined, drawerParam: string | null): DrawerKey {
  if (section === "inout") return "inout";
  if (drawerParam === "inout") return "inout";
  if (drawerParam === "records") return "records";
  if (drawerParam === "inventory") return "inventory";
  return null;
}

function resolveTrayPanel(section: string | undefined, panelParam: string | null): TrayPanelKey | null {
  if (panelParam === "tasks" || section === "tasks") return "tasks";
  if (panelParam === "control") return "control";
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
  const events = data?.events ?? [];
  const globalCams = globalCameras(cameras);
  const cameraOnline = Boolean(((data?.system ?? {}) as { camera_health?: CameraHealth }).camera_health?.ok);
  const { onlineCount } = useRobotConnectivity(robots);

  const toggleTrayPanel = useCallback((key: TrayPanelKey) => {
    if (key === "tasks" && trayPanel !== "tasks") taskFocusRequestedRef.current = true;
    navigate(trayPanel === key ? "/operate/control" : `/operate/control?panel=${key}`);
  }, [navigate, trayPanel]);

  const goNav = (route: string) => {
    if (route.includes("panel=tasks")) {
      toggleTrayPanel("tasks");
      return;
    }
    navigate(routePath(route));
  };

  const closeDrawer = useCallback(() => navigate("/operate/control"), [navigate]);

  const drawerTitle = drawer === "inout" ? "입출고" : drawer === "records" ? "기록" : drawer === "inventory" ? "재고" : "";

  const isActiveNav = (route: string) => {
    const base = route.split("?")[0];
    const current = section === "control" || !section ? "control" : section;
    if (route.includes("panel=tasks")) return taskPanelOpen;
    if (route.includes("drawer=inout")) return drawer === "inout";
    if (route.includes("drawer=records")) return drawer === "records";
    if (route.includes("drawer=inventory")) return drawer === "inventory";
    if (route === "operate/control") return current === "control" && drawer === null && !taskPanelOpen;
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

  useEffect(() => {
    if (section === "inout") {
      navigate("/operate/control?drawer=inout", { replace: true });
    } else if (section === "tasks") {
      navigate("/operate/control?panel=tasks", { replace: true });
    }
  }, [navigate, section]);

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
            const badge = it.label === "작업" ? activeTaskCount : 0;
            const controlsTaskPanel = it.route.includes("panel=tasks");
            const navLabel = controlsTaskPanel
              ? `작업, 진행 중 ${badge}건, ${taskPanelOpen ? "펼쳐짐" : "접힘"}`
              : it.label;
            return (
              <button
                key={it.key}
                type="button"
                className={active ? "active" : ""}
                title={navLabel}
                aria-label={navLabel}
                aria-current={active && !controlsTaskPanel ? "page" : undefined}
                aria-controls={controlsTaskPanel ? "operator-tasks-workspace" : opensDrawer ? "operator-context-drawer" : undefined}
                aria-expanded={controlsTaskPanel ? taskPanelOpen : opensDrawer ? active : undefined}
                onClick={() => goNav(it.route)}
              >
                <OperatorNavIcon label={it.label} />
                <span className="slim-nav-label">{it.label}</span>
                {badge > 0 ? <span className="slim-nav-badge" aria-hidden="true">{badge > 99 ? "99+" : badge}</span> : null}
              </button>
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
                <WorkOrderForm onClose={closeDrawer} disabled={allRobotsEmergency} emergencyRobots={emergencyRobots} />
              ) : null}
              {drawer === "inventory" ? <InventoryView /> : null}
              {drawer === "records" ? <Records variant="operate" /> : null}
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
                      max={560}
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
                  storageKey={trayPanel === "control" ? "lms.layout.operator-band-control" : "lms.layout.operator-band"}
                  cssVar="--operator-band-h"
                  containerRef={mapColumnRef}
                  defaultSize={trayPanel === "control" ? 480 : 300}
                  min={160}
                  max={560}
                  adjacent="trailing"
                />
              ) : null}
              <div
                className={`operator-insight-band ${trayOpen ? "open" : "collapsed"}`}
                id="operator-tasks-workspace"
                ref={insightBandRef}
                aria-label="작업 · 수동 조작 워크스페이스"
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
                    className={`task-tray-tab${trayPanel === "control" ? " active" : ""}`}
                    aria-expanded={trayPanel === "control"}
                    aria-controls="operator-control-content"
                    aria-label={`수동 조작 · 맵 이동${movementAvailable ? "" : ", Movement 오프라인"}, ${trayPanel === "control" ? "펼쳐짐" : "접힘"}`}
                    onClick={() => toggleTrayPanel("control")}
                  >
                    <span className="task-workspace-title">수동 조작 · 맵 이동</span>
                    {!movementAvailable ? <span className="tray-tab-dot" aria-hidden="true" /> : null}
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
                  <TaskQueue />
                </div>
                <div
                  id="operator-control-content"
                  className="task-workspace-content control-workspace"
                  hidden={trayPanel !== "control"}
                >
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
                      keyboardEnabled={trayPanel === "control"}
                    />
                    <MapGotoOperate robots={robots} disabled={!movementAvailable} isRobotEmergency={isRobotEmergency} />
                  </div>
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
                  <EventFeed events={events} />
                </CollapsiblePanel>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </GotoTargetProvider>
  );
}

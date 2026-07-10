import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Drawer } from "../../components/Drawer";
import { Resizer } from "../../components/Resizer";
import { CollapsiblePanel } from "../../components/CollapsiblePanel";
import { OPERATE_SLIM_NAV, routePath } from "../../app/menus";
import { useStatus } from "../../hooks/useStatus";
import { useEmergency } from "../../hooks/useEmergency";
import { useRobotConnectivity } from "../../hooks/useRobotConnectivity";
import { camerasForRobot, globalCameras } from "../../lib/cameraMapping";
import { DashboardMap } from "../dashboard/DashboardMap";
import { LiveCamera } from "../control/LiveCamera";
import { Teleop } from "../control/Teleop";
import { MapGotoOperate } from "../control/MapGotoOperate";
import { WorkOrderForm } from "./WorkOrderForm";
import { TaskQueue } from "./TaskQueue";
import { TaskRecoveryBanner } from "./TaskRecoveryPanel";
import { InventoryView } from "./InventoryView";
import { Records } from "../records/Records";
import { EventFeed } from "./EventFeed";
import { RobotMonitorCard } from "./RobotMonitorCard";
import { GotoTargetProvider } from "./GotoTargetContext";
import type { MovementHealth, Robot } from "../../types";

type DrawerKey = "inout" | "records" | "inventory" | null;

function resolveDrawer(section: string | undefined, drawerParam: string | null): DrawerKey {
  if (section === "inout") return "inout";
  if (drawerParam === "records") return "records";
  if (drawerParam === "inventory") return "inventory";
  return null;
}

export function OperatorShell() {
  const navigate = useNavigate();
  const { section } = useParams();
  const [searchParams] = useSearchParams();
  const drawer = resolveDrawer(section, searchParams.get("drawer"));
  const { data, isLoading, isError, error, refetch } = useStatus();
  const { emergencyRobots, isRobotEmergency } = useEmergency();

  const robots = data?.robots ?? [];
  const cameras = data?.camera_sources ?? [];
  const tasks = data?.tasks ?? [];
  const events = data?.events ?? [];
  const globalCams = globalCameras(cameras);
  const { onlineCount } = useRobotConnectivity(robots);

  const goNav = (route: string) => {
    navigate(routePath(route));
  };

  const closeDrawer = () => navigate("/operate/control");

  const drawerTitle = drawer === "inout" ? "입출고" : drawer === "records" ? "기록" : drawer === "inventory" ? "재고" : "";

  const isActiveNav = (route: string) => {
    const base = route.split("?")[0];
    const current = section === "control" || !section ? "control" : section;
    if (route.includes("drawer=records")) return drawer === "records";
    if (route.includes("drawer=inventory")) return drawer === "inventory";
    return `operate/${current}` === base;
  };

  const robotEmergency = (robotId: string) =>
    Boolean((data?.movement_health?.[robotId] as MovementHealth | undefined)?.is_emergency);

  const stageRef = useRef<HTMLDivElement>(null);
  const mapColumnRef = useRef<HTMLDivElement>(null);
  const mapWrapRef = useRef<HTMLDivElement>(null);
  const insightBandRef = useRef<HTMLDivElement>(null);
  const [controlPanelOpen, setControlPanelOpen] = useState(false);
  const [insightTab, setInsightTab] = useState<"tasks" | "inventory">("tasks");
  const allRobotsEmergency = robots.length > 0 && emergencyRobots.length >= robots.length;
  const activeTaskCount = tasks.filter(
    (t) => !["DONE", "COMPLETED", "CANCELLED"].includes(String(t.status || "").toUpperCase()),
  ).length;

  const scrollToTaskWorkspace = () => {
    insightBandRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  useEffect(() => {
    if (section !== "tasks") return;
    setInsightTab("tasks");
    const timer = window.setTimeout(scrollToTaskWorkspace, 120);
    return () => window.clearTimeout(timer);
  }, [section]);

  return (
    <GotoTargetProvider>
      <div className="operator-shell">
        <nav className="slim-nav" aria-label="운영 메뉴">
          {OPERATE_SLIM_NAV.map((it) => (
            <button
              key={it.key}
              type="button"
              className={isActiveNav(it.route) ? "active" : ""}
              title={it.label}
              onClick={() => goNav(it.route)}
            >
              <span className="slim-nav-label">{it.label}</span>
            </button>
          ))}
        </nav>

        <div className={`operator-stage${drawer ? " drawer-open" : ""}`} ref={stageRef}>
          {drawer ? (
            <Drawer title={drawerTitle} onClose={closeDrawer} className="operator-drawer">
              {drawer === "inout" ? (
                <WorkOrderForm onClose={closeDrawer} disabled={allRobotsEmergency} emergencyRobots={emergencyRobots} />
              ) : null}
              {drawer === "inventory" ? <InventoryView /> : null}
              {drawer === "records" ? <Records variant="operate" /> : null}
            </Drawer>
          ) : null}
          {drawer ? (
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
              <Resizer
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
              <div
                className="operator-insight-band"
                id="operator-tasks-workspace"
                ref={insightBandRef}
                aria-label="실시간 물품정보 및 작업 큐"
              >
                <div className="insight-tabs tab-bar" role="tablist" aria-label="실시간 영역 전환">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={insightTab === "tasks"}
                    className={insightTab === "tasks" ? "active" : ""}
                    onClick={() => setInsightTab("tasks")}
                  >
                    작업{activeTaskCount > 0 ? <span className="seg-count">{activeTaskCount}</span> : null}
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={insightTab === "inventory"}
                    className={insightTab === "inventory" ? "active" : ""}
                    onClick={() => setInsightTab("inventory")}
                  >
                    재고
                  </button>
                </div>
                <div className="insight-tab-panel">
                  {insightTab === "tasks" ? (
                    <>
                      <TaskRecoveryBanner />
                      <TaskQueue />
                    </>
                  ) : (
                    <InventoryView compact />
                  )}
                </div>
              </div>
              <div className="operator-control-bar" aria-label="수동 조작 및 맵 이동">
                <CollapsiblePanel
                  title="수동 조작 · 맵 이동"
                  defaultOpen={false}
                  className="operator-control-panel"
                  onOpenChange={setControlPanelOpen}
                >
                  <div className="operator-control-bar-inner">
                    <Teleop
                      robots={robots}
                      isRobotEmergency={isRobotEmergency}
                      keyboardEnabled={controlPanelOpen}
                    />
                    <MapGotoOperate robots={robots} isRobotEmergency={isRobotEmergency} />
                  </div>
                </CollapsiblePanel>
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
            {/* PHASE_55-F: 좁으면 상/하(카메라 위·알람 아래), 넓으면(≥600px) 좌/우 2컬럼 반응형 */}
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

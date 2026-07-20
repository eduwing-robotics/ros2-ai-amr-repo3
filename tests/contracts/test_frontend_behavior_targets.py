"""Dependency-free source contracts for accepted frontend behavior.

Existing behavior locks stay green. Accepted c37/G001 targets stay red until the
corresponding G003 implementation lands; they must not be represented as deferred
or absent behavior merely because this scope excludes a browser-test dependency.
"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "main-server" / "frontend" / "web"
SRC = WEB / "src"


def source(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def is_forbidden_browser_test_package(name: str) -> bool:
    return (
        name == "vitest"
        or name.startswith("@vitest/")
        or name == "jsdom"
        or name in {"playwright", "playwright-core"}
        or name.startswith("@playwright/")
        or name.startswith("@testing-library/")
    )


def test_frontend_dependency_and_build_gate_remains_unchanged() -> None:
    manifest = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((WEB / "package-lock.json").read_text(encoding="utf-8"))
    declared = set().union(*(
        manifest.get(key, {})
        for key in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
    ))
    locked = {
        key.rsplit("node_modules/", 1)[-1]
        for key in lock.get("packages", {})
        if "node_modules/" in key
    }

    assert not any(is_forbidden_browser_test_package(name) for name in declared)
    assert not any(is_forbidden_browser_test_package(name) for name in locked)
    assert "test" not in manifest.get("scripts", {})
    assert manifest["scripts"]["typecheck"] == "tsc -p tsconfig.json"
    assert manifest["scripts"]["lint"] == "eslint src"
    assert manifest["scripts"]["build"] == "tsc -p tsconfig.json && vite build"
    assert lock["lockfileVersion"] == 3
    assert lock["packages"][""]["dependencies"] == manifest["dependencies"]
    assert lock["packages"][""]["devDependencies"] == manifest["devDependencies"]


def test_route_drawer_work_order_and_recovery_contracts_remain_explicit() -> None:
    menus = source("app/menus.ts")
    shell = source("features/operate/OperatorShell.tsx")
    drawer = source("components/Drawer.tsx")
    result = source("features/operate/WorkOrderForm.tsx")
    queue = source("features/operate/taskQueueModel.ts")
    recovery = source("features/operate/TaskRecoveryPanel.tsx")
    recovery_api = source("lib/recovery.ts")

    assert 'item("operate/inventory", "재고")' in menus
    assert 'item("operate/events", "이벤트")' in menus
    assert 'searchParams.get("drawer")' in shell
    assert "navigate(contextPath(null))" in shell
    assert 'e.key === "Escape"' in drawer and 'triggerRef.current' in drawer
    assert "작업 생성됨 · 자동 시작 실패" in result and "start_failed" in result
    assert 'to="/operate/tasks"' in result and "FleetMissionDock" in shell
    assert 's === "QUEUED" || s === "ASSIGNED"' in queue
    assert "진행 중 작업" in queue and "취소되지 않습니다" in queue
    assert "checks.site_clear && checks.pose_ok && checks.cargo_ok" in recovery
    assert 'cargo !== "UNKNOWN"' in recovery
    assert 'orchestration_phase === "RECOVERY_RUNNING"' in recovery
    assert 'RecoveryStrategy = "safe_move" | "manual_abort"' in recovery_api
    assert 'useState<RecoveryStrategy>("safe_move")' in recovery
    assert 'id: "safe_move"' in recovery and 'id: "manual_abort"' in recovery
    assert "기존 작업은 자동으로 재개하지 않습니다" in recovery
    assert "로봇 정지가 확인된 경우에만 작업을 중단합니다" in recovery
    assert "safe_replan" not in recovery_api + recovery
    assert '"restart"' not in recovery_api + recovery


def test_drawer_focus_trap_inert_and_label_wiring_target() -> None:
    """G001 F028/UI-02 target, adapted to the current component paths."""

    drawer = source("components/Drawer.tsx")
    shell = source("features/operate/OperatorShell.tsx")

    assert "useId" in drawer and "const titleId = useId()" in drawer
    assert "modal?: boolean" in drawer and "id?: string" in drawer
    assert 'el.setAttribute("inert", "")' in drawer
    assert 'el.removeAttribute("inert")' in drawer
    assert 'e.key !== "Tab" || !modal || !panel' in drawer
    assert "const first = focusable[0]" in drawer
    assert "const last = focusable[focusable.length - 1]" in drawer
    assert "first.focus()" in drawer and "last.focus()" in drawer
    assert 'role={modal ? "dialog" : "region"}' in drawer
    assert "aria-modal={modal ? true : undefined}" in drawer
    assert "aria-labelledby={titleId}" in drawer and "tabIndex={-1}" in drawer
    assert "const isNarrowLayout = useNarrowOperatorLayout()" in shell
    assert 'className="drawer-scrim"' in shell
    assert 'id="operator-context-drawer"' in shell
    assert "modal={isNarrowLayout}" in shell


def test_estop_clear_active_unknown_and_unknown_robot_ui_target() -> None:
    """G001 F016/UI-05 target, adapted to the current safety helper split."""

    controls = source("components/EstopControls.tsx")
    emergency = source("hooks/useEmergency.ts")
    safety = source("lib/safety.ts")

    assert 'state?: "clear" | "active" | "partial" | "failed" | "unknown"' in safety
    assert "partial?: boolean" in safety and "unknown_robots?: string[]" in safety
    assert "active_robots?: string[]" in safety
    assert 'apiSend<EstopResult>("/robots/estop-all", "POST")' in safety
    assert 'apiSend<EstopResult>("/robots/clear-estop-all", "POST")' in safety
    assert 'type EstopState = "clear" | "active" | "unknown"' in emergency
    assert "data?.system?.estop as EstopSummary" in emergency
    assert 'state: "active" | "clear" | "unknown" | "disabled"' in emergency
    assert 'row.state === "active"' in emergency
    assert 'row.state === "unknown"' in emergency
    assert "const estopPartial = summary?.partial === true" in emergency
    assert 'summary?.state === "disabled" ? "clear"' in emergency
    assert "const legacyEmergencyRobots = useMemo" in emergency
    assert "const legacyUnknownRobots = useMemo" in emergency
    assert "data?.robots ?? []" in emergency
    assert "!legacyActiveSet.has(robot.robot_id)" in emergency
    assert "summary ? reportedRobots.active : legacyEmergencyRobots" in emergency
    assert "summary ? reportedRobots.unknown : legacyUnknownRobots" in emergency
    assert 'summary?.state ?? (emergencyRobots.length ? "active" : "unknown")' in emergency
    assert 'summary?.state ?? (emergencyRobots.length ? "active" : "clear")' not in emergency
    assert 'const isEmergency = estopState === "active" || estopState === "unknown"' in emergency
    assert "new Set([...emergencyRobots, ...unknownRobots])" in emergency
    assert "blockedRobotSet.has(robotId)" in emergency
    assert "estopState, estopPartial, emergencyRobots, unknownRobots" in emergency
    assert "const { estopState, estopPartial, unknownRobots } = useEmergency()" in controls
    assert ".filter((r) => !r.ok)" in controls
    assert "비상 정지 요청됨 — 확인 실패" in controls
    assert 'result.state === "partial" || result.partial' in controls
    assert "일부 해제 · 상태 미확인" in controls
    assert "Movement 해제 실패" in controls
    assert "비상 정지 해제됨 — 작업은 복구 선택 필요" in controls
    assert 'estopState === "unknown"' in controls
    assert "ESTOP 미확인 ${unknownRobots.length}" in controls
    assert "ESTOP 일부 활성" in controls
    assert "ESTOP 활성 · 미확인 ${unknownRobots.length}" in controls
    assert 'const canClearEstop = estopState === "active" && unknownRobots.length === 0' in controls
    assert "{canClearEstop ? (" in controls
    assert 'onClick={() => void triggerEstop()}' in controls
    assert '["recovery-needs-attention"]' in controls
    assert "recovery-awaiting-operator" not in controls


def test_map_route_planning_guards_coordinate_mismatch_and_readiness() -> None:
    dashboard = source("features/dashboard/DashboardMap.tsx")
    goto = source("features/control/MapGotoOperate.tsx")
    runtime = source("lib/mapRuntime.ts")

    assert "onPointerDown={onStagePointerDown}" in dashboard
    assert "gotoCtx.setMapId(map.map_id)" in dashboard
    assert "gotoCtx.setTarget({ x: w.x, y: w.y" in dashboard
    assert "runtimeMismatch || mapIdMismatch" in goto
    assert "navState?.robot_online === false" in goto
    assert "navState?.command_accepting === false" in goto
    assert "localization?.localized === false" in goto
    assert 'command: "stop"' in goto and 'source: "operate_goto_stop"' in goto
    assert 'asset_status === "mismatch"' in runtime
    assert "배경은 유지하고 overlay는 참고용으로 표시" in runtime


def test_disabled_robots_are_monitored_but_not_offered_for_operations() -> None:
    shell = source("features/operate/OperatorShell.tsx")
    work_order = source("features/operate/WorkOrderForm.tsx")
    assert "const enabledRobots = useMemo(() => robots.filter((robot) => robot.enabled), [robots])" in shell
    assert "enabledRobots.length > 0 && enabledRobots.every" in shell
    assert "selectedRobotOperational" in shell
    assert "<Teleop" in shell and "<MapGotoOperate" in shell
    assert "allRobots.filter((robot) => robot.enabled)" in work_order
    assert "useRobots" in work_order
    assert "<FleetMissionDock" in shell and "robots={robots}" in shell


def test_pose_quality_and_connectivity_are_separate_from_server_health() -> None:
    formatting = source("lib/format.ts")
    connectivity = source("hooks/useRobotConnectivity.ts")
    layout = source("components/Layout.tsx")

    assert "MAX_PLAUSIBLE_AGE_SEC = 86_400" in formatting
    assert "Number.isFinite(numericSourceAge)" in formatting
    assert 'if (ageSec <= 1) return { state: "live"' in formatting
    assert 'if (ageSec <= 3) return { state: "stale"' in formatting
    assert "useRobotPoses(undefined, 2000)" in connectivity
    assert 'state === "live" || state === "stale"' in connectivity
    assert 'queryKey: ["status"]' in source("hooks/useStatus.ts")
    assert "useRobotConnectivity(robots)" in layout
    assert "onlineCount" in layout and "movementHealth" in layout


def test_map_legend_keeps_connection_and_localization_visually_separate() -> None:
    dashboard = source("features/dashboard/DashboardMap.tsx")

    assert 'sync?.api_ok === false || sync?.robot_online === false ? "none" : "live"' in dashboard
    assert 'sync?.localized === false ? "위치 확인 중"' in dashboard
    assert 'className={`pose-chip ${connectionState}' in dashboard
    assert "awaiting_new_amcl_sample" not in dashboard


def test_dock_overlay_labels_the_physical_marker_not_the_approach_point() -> None:
    overlay = source("features/mapEditor/DockPairOverlay.tsx")

    assert 'className="dock-physical-marker"' in overlay
    assert 'transform={`translate(${dockPx.x} ${dockPx.y}) scale(${u})`}' in overlay
    scan_group = overlay.split('className={`dock-scan-marker', 1)[1].split('</g>', 1)[0]
    assert "dock-scan-dot" in scan_group
    assert "dock-scan-badge" not in scan_group


def test_camera_transport_retry_and_staleness_watchdog_contracts() -> None:
    transport = source("lib/visionTransport.ts")
    camera = source("features/control/LiveCamera.tsx")

    assert 'transport.kind !== "webrtc"' in transport
    assert 'status === "fallback_required"' in transport
    assert "webrtc_not_media_only" in transport
    assert "MJPEG_STALE_THRESHOLD_SEC = 5" in transport
    assert "MJPEG_RECONNECT_DELAYS_MS = [1000, 2000, 4000, 10000]" in transport
    assert "scheduleMjpegReconnect" in camera
    assert "if (reconnectTimerRef.current) return" in camera
    assert "const scheduleNext = () =>" in camera
    assert "beginMjpegStream(nextAttempt)" in camera
    assert "scheduleNext()" in camera
    assert "liveStreamUrlWithBust(source, kind, maxFps, view, Date.now())" in camera
    assert "mjpegBackoffRef.current = 0" in camera
    assert "age !== null && age >= MJPEG_STALE_THRESHOLD_SEC" in camera
    assert "WebRTC 실패 → MJPEG" in camera


def test_alarm_acknowledgement_is_local_presentation_state_target() -> None:
    """G001 F031/UI-10 target, wired through the current split EventFeed path."""

    shell = source("features/operate/OperatorShell.tsx")
    alerts = source("hooks/useCriticalAlerts.ts")

    assert "seenEvents" in alerts and "playAlertBeep" in alerts
    assert "flashTitle" in alerts and 'toast(`경보 — ${m}`' in alerts
    assert 'const ALARM_ACK_STORAGE_KEY = "lms.alarms.acked"' in shell
    assert "localStorage.getItem(ALARM_ACK_STORAGE_KEY)" in shell
    assert "const [ackedAlarmKeys, setAckedAlarmKeys] = useState<Set<string>>(loadAckedAlarmKeys)" in shell
    assert "const acknowledgeAlarms = useCallback" in shell
    assert "localStorage.setItem(ALARM_ACK_STORAGE_KEY" in shell
    assert "ackedAlarmKeys.has(eventKey(event))" in shell
    assert "firstUnackedAlarm" in shell
    assert "onClick={acknowledgeAlarms}" in shell
    assert "확인" in shell and "이벤트 보기" in shell


def test_work_order_safe_stop_is_visible_idempotent_and_reports_results() -> None:
    """F011: active orders expose one guarded stop request and actionable feedback."""

    hooks = source("hooks/useWorkOrders.ts")
    queue = source("features/operate/TaskQueue.tsx")
    row = source("features/operate/TaskQueueOrderRow.tsx")
    types = source("types/warehouse.ts")

    assert "export function useStopWorkOrder()" in hooks
    assert '`/work-orders/${orderId}/stop`' in hooks
    assert 'status: "CANCEL_REQUESTED" | "AWAITING_OPERATOR"' in hooks
    assert "onMutate: (orderId)" in hooks and "안전 중단 요청 전송 중" in hooks
    assert 'result.status === "AWAITING_OPERATOR"' in hooks
    assert "result.accepted" in hooks and "중단 요청이 거부되었습니다" in hooks
    assert '["work-orders"]' in hooks and '["recovery-needs-attention"]' in hooks
    assert "recovery-awaiting-operator" not in hooks
    assert "const stopWorkOrder = useStopWorkOrder()" in queue
    assert "stopWorkOrder.variables === o.order_id" in queue
    assert "await stopWorkOrder.mutateAsync(order.order_id)" in queue
    assert "stopPending: boolean" in row
    assert "disabled={cancelPending || stopPending}" in row
    assert "중단 요청 중" in row and "안전 중단" in row and "복귀 중단" in row
    assert "business_completed?: boolean" in types


def test_ordered_approach_routes_have_editor_api_types_and_numbered_overlay() -> None:
    """F018: transit steps round-trip through the route API and retain server order on-map."""

    scenario = source("hooks/useScenarioData.ts")
    actions = source("features/mapEditor/useMapEditorActions.ts")
    editor = source("features/mapEditor/MapEditor.tsx")
    stage = source("features/mapEditor/MapStage.tsx")
    overlay = source("features/mapEditor/ApproachRouteOverlay.tsx")
    types = source("types/scenario.ts")

    assert 'apiSend("/waypoint-routes", "POST", body)' in scenario
    assert 'apiSend(`/waypoint-routes/${encodeURIComponent(id)}`, "DELETE")' in scenario
    assert "upsertWaypointRoute" in scenario and "deleteWaypointRoute" in scenario
    assert 'selected?.waypoint_type === "transit"' in actions
    assert 'z.waypoint_type !== "approach"' in actions
    assert "m.upsertWaypointRoute.mutateAsync" in actions
    assert "m.deleteWaypointRoute.mutateAsync(linkScanId)" in editor
    assert "route_target_id?: string | null" in types
    assert "approach_waypoint_ids?: string[]" in types
    assert '<ApproachRouteOverlay map={map} zones={zones} />' in stage
    assert "target.approach_waypoint_ids ?? []" in overlay
    assert ".map((stepId, index)" in overlay
    assert "{index + 1}" in overlay
    assert 'markerEnd="url(#approachRouteArrow)"' in overlay


def test_webrtc_requires_a_decoded_frame_and_keeps_layout_switches_live() -> None:
    """F030: decode must be real and changing grid/single must not suspend a visible stream."""

    transport = source("lib/visionTransport.ts")
    camera = source("features/control/LiveCamera.tsx")
    styles = source("styles/base.css")

    assert "WEBRTC_FIRST_FRAME_TIMEOUT_MS = 5000" in transport
    assert "export function waitForFirstVideoFrame" in transport
    assert "HTMLMediaElement.HAVE_CURRENT_DATA" in transport
    assert "webrtc_first_frame_timeout" in transport
    assert "onConnectionLost?: (state: RTCPeerConnectionState)" in transport
    assert 'pc.connectionState === "disconnected"' in transport
    assert 'pc.connectionState === "failed"' in transport
    assert "let cleaned = false" in transport and "if (cleaned) return" in transport
    assert "WEBRTC_RETRY_DELAYS_MS = [5000, 15000, 30000, 60000]" in camera
    assert "const [webrtcRetryToken, setWebrtcRetryToken]" in camera
    assert "const streamKeyRef = useRef" in camera
    assert "streamKeyRef.current !== streamKey" in camera
    assert "webrtcRetryAttemptRef.current = 0" in camera
    assert "await waitForFirstVideoFrame(video)" in camera
    assert "const handleWebRtcLost" in camera and "WebRTC 연결 끊김 → MJPEG" in camera
    assert "IntersectionObserver" not in camera
    assert "화면 밖 —" not in camera
    assert "clearWebRtcRetry()" in camera
    assert 'if (kind !== "overlay") return;' in camera
    assert "videoEl.videoWidth > 0" in transport
    assert "videoEl.videoHeight > 0" in transport
    assert 'videoEl.addEventListener("resize", onFrame)' in transport
    assert 'mediaTrack?.addEventListener("ended", handleMediaEnded)' in camera
    assert 'video.addEventListener("emptied", handleMediaEnded)' in camera
    assert 'activeTrack.readyState !== "live"' in camera
    assert 'className={`cam-live cam-live-video${mode === "webrtc" ? " is-active" : ""}`}' in camera
    assert 'hidden={mode !== "mjpeg"}' in camera
    assert "video.srcObject = null" not in camera
    assert "video.cam-live-video:not(.is-active)" in styles

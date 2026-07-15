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
    result = source("features/operate/WorkOrderResultNotice.tsx")
    queue = source("features/operate/taskQueueModel.ts")
    recovery = source("features/operate/TaskRecoveryPanel.tsx")

    assert 'operate/control?drawer=inventory' in menus
    assert 'operate/control?drawer=records' in menus
    assert 'searchParams.get("drawer")' in shell
    assert 'navigate("/operate/control")' in shell
    assert 'e.key === "Escape"' in drawer and 'triggerRef.current' in drawer
    assert "일부만 즉시 시작됨" in result and 'to="/operate/tasks"' in result
    assert 's === "QUEUED" || s === "ASSIGNED"' in queue
    assert "진행 중 작업" in queue and "취소되지 않습니다" in queue
    assert "checks.site_clear && checks.pose_ok && checks.cargo_ok" in recovery
    assert 'cargo !== "UNKNOWN"' in recovery
    assert 'orchestration_phase === "RECOVERY_RUNNING"' in recovery


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

    assert 'state?: "clear" | "partial" | "failed" | "unknown"' in safety
    assert "partial?: boolean" in safety and "unknown_robots?: string[]" in safety
    assert 'apiSend<EstopResult>("/robots/estop-all", "POST")' in safety
    assert 'apiSend<EstopResult>("/robots/clear-estop-all", "POST")' in safety
    assert 'type EstopState = "clear" | "active" | "unknown"' in emergency
    assert "estop_summary" in emergency
    assert "const unknownRobots = summary?.unknown_robots ?? []" in emergency
    assert 'const estopState: EstopState = summary?.state ?? (emergencyRobots.length ? "active" : "clear")' in emergency
    assert 'const isEmergency = estopState !== "clear"' in emergency
    assert "estopState, emergencyRobots, unknownRobots" in emergency
    assert "const { isEmergency, estopState, unknownRobots } = useEmergency()" in controls
    assert ".filter((r) => !r.ok)" in controls
    assert "비상 정지 요청됨 — 확인 실패" in controls
    assert 'result.state === "partial" || result.partial' in controls
    assert "일부 해제 · 상태 미확인" in controls
    assert "Movement 해제 실패" in controls
    assert "비상 정지 해제됨 — 작업은 복구 선택 필요" in controls
    assert 'estopState === "unknown"' in controls
    assert "ESTOP 미확인 ${unknownRobots.length}" in controls


def test_map_route_planning_guards_coordinate_mismatch_and_readiness() -> None:
    dashboard = source("features/dashboard/DashboardMap.tsx")
    goto = source("features/control/MapGotoOperate.tsx")
    runtime = source("lib/mapRuntime.ts")

    assert "onPointerDown={gotoMode ? onGotoStageDown : undefined}" in dashboard
    assert "gotoCtx.setMapId(map.map_id)" in dashboard
    assert "gotoCtx.setTarget(null)" in dashboard
    assert "runtimeMismatch || mapIdMismatch" in goto
    assert "navState?.robot_online === false" in goto
    assert "navState?.command_accepting === false" in goto
    assert "localization?.localized === false" in goto
    assert 'command: "stop"' in goto and 'source: "operate_goto_stop"' in goto
    assert 'asset_status === "mismatch"' in runtime
    assert "배경은 유지하고 overlay는 참고용으로 표시" in runtime


def test_pose_quality_and_connectivity_are_separate_from_server_health() -> None:
    formatting = source("lib/format.ts")
    connectivity = source("hooks/useRobotConnectivity.ts")
    layout = source("components/Layout.tsx")

    assert "MAX_PLAUSIBLE_AGE_SEC = 86_400" in formatting
    assert "Number.isFinite(sourceAge)" in formatting
    assert 'if (ageSec <= 1) return { state: "live"' in formatting
    assert 'if (ageSec <= 3) return { state: "stale"' in formatting
    assert 'queryKey: ["robot-poses", "header-all"]' in connectivity
    assert 'state === "live" || state === "stale"' in connectivity
    assert 'queryKey: ["status"]' in source("hooks/useStatus.ts")
    assert "useRobotConnectivity(robots)" in layout
    assert "onlineCount" in layout and "movementHealth" in layout


def test_camera_transport_retry_and_staleness_watchdog_contracts() -> None:
    transport = source("lib/visionTransport.ts")
    camera = source("features/control/LiveCamera.tsx")

    assert 'transport.kind !== "webrtc"' in transport
    assert 'status === "fallback_required"' in transport
    assert "webrtc_not_media_only" in transport
    assert "MJPEG_STALE_THRESHOLD_SEC = 5" in transport
    assert "MJPEG_RECONNECT_DELAYS_MS = [1000, 2000, 4000, 10000]" in transport
    assert "scheduleMjpegReconnect" in camera
    assert "mjpegBackoffRef.current = 0" in camera
    assert "sinceLoadSec >= MJPEG_STALE_THRESHOLD_SEC" in camera
    assert "WebRTC 실패 → MJPEG" in camera


def test_alarm_acknowledgement_is_local_presentation_state_target() -> None:
    """G001 F031/UI-10 target, wired through the current split EventFeed path."""

    feed = source("features/operate/EventFeed.tsx")
    shell = source("features/operate/OperatorShell.tsx")
    alerts = source("hooks/useCriticalAlerts.ts")

    assert ".sort((a, b)" in feed and ".slice(0, limit)" in feed
    assert 'aria-label="실시간 알람"' in feed
    assert "eventDotClass(ev)" in feed
    assert "seenEvents" in alerts and "playAlertBeep" in alerts
    assert "flashTitle" in alerts and 'toast(`경보 — ${m}`' in alerts
    assert 'const ALARM_ACK_STORAGE_KEY = "lms.alarms.acked"' in shell
    assert "localStorage.getItem(ALARM_ACK_STORAGE_KEY)" in shell
    assert "const [ackedAlarmKeys, setAckedAlarmKeys] = useState<Set<string>>(loadAckedAlarmKeys)" in shell
    assert "const acknowledgeAlarms = useCallback" in shell
    assert "localStorage.setItem(ALARM_ACK_STORAGE_KEY" in shell
    assert "ackedKeys={ackedAlarmKeys}" in shell
    assert "onAckAll={acknowledgeAlarms}" in shell
    assert "ackedKeys: Set<string>" in feed and "onAckAll: () => void" in feed
    assert "ackedKeys.has(eventKey(" in feed
    assert "onClick={onAckAll}" in feed
    assert "모두 확인" in feed and "확인됨" in feed

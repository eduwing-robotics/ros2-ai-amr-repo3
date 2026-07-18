import { Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { MODES, isOperateArea, modeForRoute, routePath, type ModeDef } from "../app/menus";
import { useStatus } from "../hooks/useStatus";
import { useRobotConnectivity } from "../hooks/useRobotConnectivity";
import { useProbes } from "../hooks/useCommLogs";
import { useFeedback } from "./FeedbackProvider";
import { useEmergency } from "../hooks/useEmergency";
import { useCriticalAlerts } from "../hooks/useCriticalAlerts";
import { useEvents } from "../domains/records/useEvents";
import { Clock } from "./Clock";
import { EstopControls } from "./EstopControls";
import { AdminShell } from "./AdminShell";
import { ThemeToggle } from "./ThemeToggle";
import type { CameraHealth } from "../types";

// 운영/관리 2모드 셸. 운영(operate/*)은 OperatorShell 풀폭, 관리는 사이드바+콘텐츠.
export function Layout() {
  const navigate = useNavigate();
  // 라우트가 /operate/:section, /admin/:section, /records/:tab 으로 분리돼 있어
  // :area 파라미터가 없으므로 pathname에서 직접 첫 세그먼트를 읽는다.
  const { section: sectionParam, tab: tabParam } = useParams();
  const { pathname } = useLocation();
  const areaKey = pathname.split("/").filter(Boolean)[0] ?? "";
  const sectionKey = areaKey === "records" ? undefined : sectionParam;
  const recordsTab = areaKey === "records" ? tabParam : undefined;
  const mode = modeForRoute(areaKey, sectionKey);
  const currentRoute = areaKey === "records" ? `records/${recordsTab ?? "events"}` : `${areaKey}/${sectionKey}`;
  const operateShell = isOperateArea(areaKey);
  const { data: status, isError } = useStatus();
  const { data: events = [] } = useEvents(30, true, 2000);
  const { emergencyRobots } = useEmergency();
  const { toast } = useFeedback();
  const { probeMovement, probeCamera } = useProbes();
  const qc = useQueryClient();

  const robots = status?.robots ?? [];

  // 전역 능동 경보(소리·탭 타이틀 점멸·토스트) — 모든 화면에서 상시 동작.
  useCriticalAlerts({ events, robots, emergencyRobots });
  const liveOk = !!status && !isError;
  const { onlineCount, robotTitle } = useRobotConnectivity(robots);

  const movementHealthMap = status?.movement_health ?? {};
  const movementHealth = Object.values(movementHealthMap);
  const movementDryRun = movementHealth.some((h) => h.dry_run);
  const movementOnline = movementHealth.length > 0 && movementHealth.some((h) => h.ok && !h.dry_run);
  const movementOffline = movementHealth.length > 0 && movementHealth.every((h) => !h.ok);
  const movementLabel = movementDryRun ? "드라이런" : movementOnline ? "연결" : movementOffline ? "오프라인" : "대기";
  // ISA-101 예외만 색상: 정상(연결)=무채색 quiet, 이상(드라이런·오프라인)=warn
  const movementBadge = movementDryRun ? "warn" : movementOnline ? "quiet" : movementOffline ? "warn" : "off";
  const movementIcon = movementDryRun ? "⚠" : movementOnline ? "●" : movementOffline ? "⚠" : "·";
  const movementAttn = movementLabel === "대기" || movementLabel === "오프라인";

  const cameraHealth = ((status?.system ?? {}) as { camera_health?: CameraHealth }).camera_health;
  const cameraOnline = !!cameraHealth?.ok;
  const cameraLabel = cameraOnline ? "서버 연결" : cameraHealth ? "서버 오프라인" : "서버 대기";
  const cameraBadge = cameraOnline ? "quiet" : cameraHealth ? "warn" : "off";
  const cameraIcon = cameraOnline ? "●" : cameraHealth ? "⚠" : "·";
  const cameraAttn = !cameraOnline;

  const retryMovement = () => {
    if (probeMovement.isPending) return;
    probeMovement.mutate(undefined, {
      onSuccess: (res) => {
        const anyOk = Object.values(res.movement_health ?? {}).some((h) => h.ok);
        toast(anyOk ? "이동 서버 응답 확인" : "이동 서버 무응답", anyOk ? "ok" : "err");
        qc.invalidateQueries({ queryKey: ["status"] });
      },
      onError: (e) => toast(`이동 probe 실패: ${(e as Error).message}`, "err"),
    });
  };
  const retryCamera = () => {
    if (probeCamera.isPending) return;
    probeCamera.mutate(undefined, {
      onSuccess: (res) => {
        toast(res.content_type ? "카메라 응답 확인" : "카메라 응답 없음", res.content_type ? "ok" : "err");
        qc.invalidateQueries({ queryKey: ["status"] });
      },
      onError: (e) => toast(`카메라 probe 실패: ${(e as Error).message}`, "err"),
    });
  };

  const goMode = (m: ModeDef) => navigate(routePath(m.items[0].route));

  return (
    <div className="shell" data-mode={mode.key}>
      <header className="header chrome">
        <div className="brand">
          <strong>물류센터 A · {mode.title}</strong>
        </div>
        <nav className="mode-tabs">
          {MODES.map((m) => (
            <button key={m.key} type="button" className={`mode-tab ${m.accent}${m.key === mode.key ? " active" : ""}`} onClick={() => goMode(m)}>
              {m.label}
            </button>
          ))}
        </nav>
        <div className="header-right">
          {liveOk ? (
            <div className="livestat header-main-status"><span className="dot on" aria-hidden="true" /><span>Main 정상</span></div>
          ) : (
            <button type="button" className="livestat err header-status-action" onClick={() => navigate("/admin/system")} title="Main 연결 오류 · 시스템 진단 열기">
              <span className="dot off" aria-hidden="true" /><span>Main 연결 대기 · 시스템 보기</span>
            </button>
          )}
          <div className="badges">
            <button
              type="button"
              className={`badge ${movementBadge}${movementAttn ? " attn" : ""}${probeMovement.isPending ? " probing" : ""}`}
              title={`클릭=연결 재시도\n${movementHealth.map((h) => String(h.error || h.base_url || h.mode || "")).filter(Boolean).join(" | ") || "상태 정보 없음"}`}
              onClick={retryMovement}
              disabled={probeMovement.isPending}
            >
              <span className="badge-icon" aria-hidden="true">{probeMovement.isPending ? "↻" : movementIcon}</span>이동 {probeMovement.isPending ? "확인 중…" : movementLabel}
            </button>
            <button
              type="button"
              className={`badge ${cameraBadge}${cameraAttn ? " attn" : ""}${probeCamera.isPending ? " probing" : ""}`}
              title={`클릭=연결 재시도\n${String(cameraHealth?.error || cameraHealth?.base_url || "상태 정보 없음")}`}
              onClick={retryCamera}
              disabled={probeCamera.isPending}
            >
              <span className="badge-icon" aria-hidden="true">{probeCamera.isPending ? "↻" : cameraIcon}</span>카메라 {probeCamera.isPending ? "확인 중…" : cameraLabel}
            </button>
          </div>
          {!operateShell ? (
            <div className={`livestat${liveOk ? (robots.length > 0 && onlineCount === 0 ? " warn" : "") : " err"}`} title={liveOk ? robotTitle : "서버 응답 없음"}>
              <span className={`dot ${liveOk ? (onlineCount > 0 ? "on" : "warn") : "off"}`} aria-hidden="true" />
              <span>{liveOk ? `로봇 ${onlineCount}/${robots.length}` : "연결 대기"}</span>
            </div>
          ) : null}
          <div className="livestat"><Clock /></div>
          <ThemeToggle />
          <EstopControls />
        </div>
      </header>

      <div className="body" data-layout={operateShell ? "operate" : "admin"}>
        {operateShell ? <main className="content content-operate"><Outlet /></main> : <AdminShell mode={mode} currentRoute={currentRoute} />}
      </div>
    </div>
  );
}

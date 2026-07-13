import { useRef } from "react";
import { Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { MODES, isOperateArea, modeForRoute, routePath, type ModeDef } from "../app/menus";
import { useStatus } from "../hooks/useStatus";
import { useRobotConnectivity } from "../hooks/useRobotConnectivity";
import { useProbes } from "../hooks/useCommLogs";
import { useFeedback } from "./FeedbackProvider";
import { useEmergency } from "../hooks/useEmergency";
import { useCriticalAlerts } from "../hooks/useCriticalAlerts";
import { Clock } from "./Clock";
import { EstopControls } from "./EstopControls";
import { Resizer } from "./Resizer";
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
  const bodyRef = useRef<HTMLDivElement>(null);
  const { data: status, isError } = useStatus();
  const { isEmergency, emergencyRobots } = useEmergency();
  const { toast } = useFeedback();
  const { probeMovement, probeCamera } = useProbes();
  const qc = useQueryClient();

  const robots = status?.robots ?? [];

  // 전역 능동 경보(소리·탭 타이틀 점멸·토스트) — 모든 화면에서 상시 동작.
  useCriticalAlerts({ events: status?.events ?? [], robots, emergencyRobots });
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
  const cameraLabel = cameraOnline ? "연결" : cameraHealth ? "오프라인" : "대기";
  const cameraBadge = cameraOnline ? "quiet" : cameraHealth ? "warn" : "off";
  const cameraIcon = cameraOnline ? "●" : cameraHealth ? "⚠" : "·";
  const cameraAttn = cameraLabel === "대기" || cameraLabel === "오프라인";

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
          <strong>창고 로봇 관제</strong>
        </div>
        <nav className="mode-tabs">
          {MODES.map((m) => (
            <button key={m.key} type="button" className={`mode-tab ${m.accent}${m.key === mode.key ? " active" : ""}`} onClick={() => goMode(m)}>
              {m.label}
            </button>
          ))}
        </nav>
        <div className="header-right">
          <ThemeToggle />
          <EstopControls />
          {isEmergency ? <span className="badge err emergency-badge"><span className="badge-icon" aria-hidden="true">⛔</span>비상 정지</span> : null}
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
          <div className="livestat"><Clock /></div>
          <div
            className={`livestat${liveOk ? (robots.length > 0 && onlineCount === 0 ? " warn" : "") : " err"}`}
            title={liveOk ? robotTitle : "서버 응답 없음"}
          >
            <span className={`dot ${liveOk ? (onlineCount > 0 ? "on" : "warn") : "off"}`} aria-hidden="true" />
            <span>{liveOk ? `로봇 ${onlineCount}/${robots.length}` : "연결 대기"}</span>
          </div>
        </div>
      </header>

      <div className="body" data-layout={operateShell ? "operate" : "admin"} ref={bodyRef}>
        {!operateShell ? (
          <>
            <aside className={`side ${mode.accent}`}>
              <div className="side-title">{mode.title}</div>
              <div>
                {mode.items.map((it) => (
                  <button
                    key={it.key}
                    type="button"
                    className={it.route === currentRoute || it.route.startsWith(currentRoute) ? "active" : ""}
                    onClick={() => navigate(routePath(it.route))}
                  >
                    {it.label}
                  </button>
                ))}
              </div>
            </aside>
            <Resizer
              className="layout-resizer--sidebar"
              orientation="horizontal"
              storageKey="lms.layout.admin-sidebar"
              cssVar="--admin-side-w"
              containerRef={bodyRef}
              defaultSize={220}
              min={160}
              max={360}
              adjacent="leading"
            />
          </>
        ) : null}

        <main className={`content${operateShell ? " content-operate" : ""}`}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

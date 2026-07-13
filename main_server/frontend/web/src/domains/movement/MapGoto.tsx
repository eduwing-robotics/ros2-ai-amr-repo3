import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useMaps } from "../../hooks/useScenarioData";
import { useRobotPoses } from "../../hooks/useRobotPoses";
import { useMapStageOverlay } from "../../hooks/useMapStageOverlay";
import { clientToPixel, degToRad, pixelToWorld, radToDeg, worldToPixel, yawFromPixel } from "../../lib/coords";
import { missionGoto, missionGotoPreview, missionStatus, movementCommandTrace, movementMapState, robotLocalization, robotNavState, setRobotInitialPose } from "../../lib/missions";
import { isMapRuntimeMismatch, mapAssetWarning, runtimeBadgeLabel } from "../../lib/mapRuntime";
import { shortId } from "../../lib/format";
import type { MissionStatusResponse, Robot } from "../../types";

// 마커 크기(화면 px). 운영 화면에서는 고정값만 사용한다.
const MARKER_PX = 10;

// 수동조작: 맵 위 한 점을 찍어 Nav2 goToPose 로 이동(테스트). 시나리오 저장 없이 즉석 1지점 미션.
// 브라우저는 Main API(/robot-commands)를 호출하고, Main 이 Movement→Nav2 로 전달한다.
export function MapGoto({ robots }: { robots: Robot[] }) {
  const { data: maps = [] } = useMaps();
  const [robotId, setRobotId] = useState("");
  const [target, setTarget] = useState<{ x: number; y: number } | null>(null);
  const [yawDeg, setYawDeg] = useState("0");
  const [commandId, setCommandId] = useState("");
  const [activeCommandId, setActiveCommandId] = useState("");
  const [status, setStatus] = useState("맵에서 도착 지점을 클릭/드래그 하세요.");
  const [trail, setTrail] = useState<{ x: number; y: number }[]>([]);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"goto" | "initial_pose">("goto");
  const [guide, setGuide] = useState<{ left: number; top: number; x: number; y: number } | null>(null);
  const dragKind = useRef<null | "move" | "yaw">(null);
  const targetRef = useRef(target);
  useEffect(() => { targetRef.current = target; }, [target]);

  const map = maps[0] ?? null;
  const runtimeMismatch = isMapRuntimeMismatch(map);
  const renderMap = map;
  const { stageRef, overlayReady, u } = useMapStageOverlay(renderMap?.width, renderMap?.height);
  const { data: poses = [] } = useRobotPoses(map?.map_id, 250);
  const robot = robotId || robots[0]?.robot_id || "";
  const selectedPose = poses.find((p) => p.robot_id === robot);
  const { data: mapState } = useQuery({
    queryKey: ["movement-map-state"],
    queryFn: movementMapState,
    refetchInterval: 3000,
  });
  const { data: localization } = useQuery({
    queryKey: ["robot-localization", robot],
    queryFn: () => robotLocalization(robot),
    enabled: Boolean(robot),
    refetchInterval: 1000,
  });
  const { data: navState } = useQuery({
    queryKey: ["robot-nav-state", robot],
    queryFn: () => robotNavState(robot),
    enabled: Boolean(robot),
    refetchInterval: 1500,
  });
  const initialPoseRequired = navState?.action_required === "set_initial_pose";
  useEffect(() => {
    if (mode === "initial_pose" && !initialPoseRequired) setMode("goto");
  }, [initialPoseRequired, mode]);
  const traceCommandId = activeCommandId || commandId;
  const { data: commandTrace } = useQuery({
    queryKey: ["movement-command-trace", traceCommandId, robot],
    queryFn: () => movementCommandTrace(traceCommandId, robot),
    enabled: Boolean(traceCommandId && robot),
    refetchInterval: activeCommandId ? 1500 : 5000,
  });
  const activeMapId = mapState?.active_map_id || map?.runtime_map_id || "";
  const assetWarning = mapAssetWarning(map);
  const mapIdMismatch = Boolean(map?.map_id && activeMapId && map.map_id !== activeMapId);
  const robotBlocked = navState?.robot_online === false || navState?.command_accepting === false || localization?.localized === false;
  const blockedReason = robotBlocked
    ? navState?.robot_online === false
      ? "robot offline"
      : localization?.localized === false
        ? localization.reason || "localization not ready"
        : navState?.command_accepting === false
          ? navState.reason || "command not accepting"
          : ""
    : "";

  // 마커(이동) / 방향(yaw) 드래그 — 전역 포인터 추적. 드래그 중 커서 옆에 world 좌표 가이드.
  useEffect(() => {
    if (!renderMap) return;
    const onMove = (e: PointerEvent) => {
      const stage = stageRef.current;
      if (!stage || !dragKind.current) return;
      const rect = stage.getBoundingClientRect();
      const px = clientToPixel(stage, renderMap, e.clientX, e.clientY);
      if (!px) { setGuide(null); return; }
      if (dragKind.current === "yaw") {
        const t = targetRef.current;
        if (t) {
          const c = worldToPixel(renderMap, t.x, t.y);
          setYawDeg(String(Math.round(radToDeg(yawFromPixel(c.x, c.y, px.x, px.y)))));
        }
        return;
      }
      const w = pixelToWorld(renderMap, px.x, px.y);
      setTarget(w);
      setGuide({ left: e.clientX - rect.left, top: e.clientY - rect.top, x: w.x, y: w.y });
    };
    const onUp = () => { dragKind.current = null; setGuide(null); };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    return () => { document.removeEventListener("pointermove", onMove); document.removeEventListener("pointerup", onUp); };
  }, [renderMap, stageRef]);

  // 빈 곳을 누르면 그 지점에 목표를 찍고 바로 드래그 이동을 시작한다(click 대신 pointerdown — 핸들 뗀 위치로 튀는 문제 방지).
  const onStageDown = (e: React.PointerEvent) => {
    if ((e.target as Element).closest("[data-goto]")) return;
    const stage = stageRef.current;
    if (!stage || !renderMap) return;
    const rect = stage.getBoundingClientRect();
    const px = clientToPixel(stage, renderMap, e.clientX, e.clientY);
    if (!px) return;
    const w = pixelToWorld(renderMap, px.x, px.y);
    setTarget(w);
    dragKind.current = "move";
    setGuide({ left: e.clientX - rect.left, top: e.clientY - rect.top, x: w.x, y: w.y });
  };

  const body = () => {
    if (!robot) throw new Error("로봇을 선택하세요.");
    if (!map) throw new Error("맵이 없습니다.");
    if (!target) throw new Error("도착 지점을 먼저 클릭하세요.");
    if (robotBlocked) throw new Error(`로봇 준비 안 됨: ${blockedReason}`);
    return {
      robot_id: robot, map_id: map.map_id, x: target.x, y: target.y, yaw: degToRad(Number(yawDeg) || 0)
    };
  };
  const summarize = (label: string, r: MissionStatusResponse) => {
    const resp = (r.response || {}) as Record<string, unknown>;
    const accepted = resp.accepted;
    const state = resp.state ?? resp.status;
    setCommandId(r.command_id || "");
    setStatus(`${label}: ${shortId(r.command_id)} · accepted=${accepted === undefined ? "-" : accepted ? "OK" : "NO"}${state ? ` · ${state}` : ""}`);
    return String(state || "");
  };
  const runInitialPose = async () => {
    setBusy(true);
    try {
      if (!robot) throw new Error("로봇을 선택하세요.");
      if (!map) throw new Error("맵이 없습니다.");
      if (!target) throw new Error("맵에서 위치를 먼저 클릭하세요.");
      await setRobotInitialPose(robot, {
        map_id: map.map_id,
        x: target.x,
        y: target.y,
        yaw: degToRad(Number(yawDeg) || 0),
      });
      setStatus(`initial pose 전송 완료: x ${target.x.toFixed(3)} y ${target.y.toFixed(3)}`);
    } catch (e) {
      const msg = (e as Error).message;
      if (msg.includes("movement_initial_pose_api_missing")) {
        setStatus("Movement 서버가 Initial Pose 설정을 지원하지 않습니다.");
      } else {
        setStatus(`initial pose 실패: ${msg}`);
      }
    } finally {
      setBusy(false);
    }
  };

  const traceFlow = useMemo(() => {
    if (!commandTrace?.callbacks?.length) return commandTrace?.state || null;
    const types = [...commandTrace.callbacks].reverse().map((c) => String((c as { event_type?: string }).event_type || "").replace("MOVEMENT_COMMAND_", ""));
    return types.length ? types.join(" → ") : commandTrace.state || null;
  }, [commandTrace]);

  const run = async (kind: "preview" | "go") => {
    setBusy(true);
    try {
      const b = body();
        setStatus(`${kind === "go" ? "이동" : "PREVIEW"} 전송 중…`);
        const r = await (kind === "go" ? missionGoto(b) : missionGotoPreview(b));
        summarize(kind === "go" ? "이동 요청" : "PREVIEW", r);
        if (kind === "go") {
          setActiveCommandId(r.command_id || "");
          setTrail(selectedPose ? [{ x: selectedPose.x, y: selectedPose.y }] : []);
        }
    } catch (e) {
      setStatus(`실패: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!activeCommandId || !selectedPose) return;
    setTrail((cur) => {
      const last = cur[cur.length - 1];
      if (last && Math.hypot(last.x - selectedPose.x, last.y - selectedPose.y) < 0.03) return cur;
      return [...cur.slice(-120), { x: selectedPose.x, y: selectedPose.y }];
    });
  }, [activeCommandId, selectedPose]);

  useEffect(() => {
    if (!activeCommandId || !robot) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const r = await missionStatus(activeCommandId, robot);
        if (cancelled) return;
        const state = summarize("STATUS", r);
        if (["DONE", "FAILED", "CANCELED", "CANCELLED", "STOPPED"].includes(state)) setActiveCommandId("");
      } catch (e) {
        if (!cancelled) setStatus(`상태 조회 실패: ${(e as Error).message}`);
      }
    };
    void tick();
    const id = window.setInterval(tick, 1000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [activeCommandId, robot]);

  const tp = renderMap && target ? worldToPixel(renderMap, target.x, target.y) : null;
  const yaw = degToRad(Number(yawDeg) || 0);
  const U = (px: number) => px * u;
  const ringR = U(MARKER_PX), dotR = U(MARKER_PX * 0.28), handleR = U(MARKER_PX * 0.72), yawLen = U(MARKER_PX * 3.2);
  const robotScale = U(MARKER_PX / 7);
  const trailPoints = renderMap ? trail.map((pt) => worldToPixel(renderMap, pt.x, pt.y)).map((pt) => `${pt.x},${pt.y}`).join(" ") : "";
  const targetLine = renderMap && selectedPose && target ? [worldToPixel(renderMap, selectedPose.x, selectedPose.y), worldToPixel(renderMap, target.x, target.y)] : null;

  return (
    <div className="panel">
      <h2>맵 기반 이동 · Nav2 테스트</h2>
      <div className="toolbar">
        <select className="filter" value={robot} onChange={(e) => setRobotId(e.target.value)}>
          {robots.length === 0 ? <option value="">로봇 없음</option> : robots.map((r) => <option key={r.robot_id} value={r.robot_id}>{r.robot_id}</option>)}
        </select>
        <input className="search mono goto-yaw-input" type="number" step="1" title="도착 방향(도)" placeholder="방향(°)" value={yawDeg} onChange={(e) => setYawDeg(e.target.value)} />
        <button className="rowbtn" onClick={() => { setTarget(null); setStatus(mode === "initial_pose" ? "맵에서 initial pose 위치를 클릭하세요." : "맵에서 도착 지점을 클릭/드래그 하세요."); }}>지점 지우기</button>
        <button type="button" className={mode === "goto" ? "rowbtn primary" : "rowbtn"} onClick={() => setMode("goto")}>이동 모드</button>
        {initialPoseRequired ? (
          <button type="button" className={mode === "initial_pose" ? "rowbtn primary" : "rowbtn"} onClick={() => { setMode("initial_pose"); setStatus("맵에서 initial pose 위치를 클릭하세요."); }}>Initial Pose</button>
        ) : null}
        <span className="rowcount mono">
          {selectedPose
            ? `현재 x ${selectedPose.x.toFixed(3)} · y ${selectedPose.y.toFixed(3)} · yaw ${radToDeg(selectedPose.yaw || 0).toFixed(1)}° · age ${selectedPose.age_sec?.toFixed(2) ?? "-"}s`
            : "현재 위치 없음"}
        </span>
      </div>

      <div className={`goto-diagnostics ${robotBlocked ? "warn" : "ok"}`}>
        <span className="runtime-badge">{runtimeBadgeLabel(map, activeMapId)}</span>
        <span>UI map <b>{map?.map_id || "—"}</b>{mapIdMismatch ? " (id ≠ runtime, 명령은 runtime 기준)" : ""}</span>
        <span>robot <b>{navState?.robot_online === false ? "offline" : navState?.robot_online ? "online" : "unknown"}</b></span>
        <span>localized <b>{localization?.localized ? "true" : localization?.localized === false ? "false" : "unknown"}</b></span>
        <span>pose <b>{localization?.pose_state || "unknown"}</b></span>
        <span>nav <b>{navState?.navigator_status || "unknown"}</b></span>
        {blockedReason ? <span className="diag-reason">{blockedReason}</span> : null}
        {assetWarning ? <span className="diag-reason">{assetWarning}</span> : null}
        {runtimeMismatch ? <span className="diag-reason">좌표계 불일치 — 배경 유지, overlay 참고용</span> : null}
      </div>
      {commandTrace ? (
        <div className="goto-trace">
          <span className="mono">cmd {shortId(commandTrace.command_id)}</span>
          <span>state <b>{commandTrace.state || "unknown"}</b></span>
          {traceFlow ? <span>flow <b>{traceFlow}</b></span> : null}
          <span>source <b>{commandTrace.source}</b></span>
          <span>callbacks <b>{commandTrace.callback_count}</b></span>
          {commandTrace.polling_error ? <span className="diag-reason">{commandTrace.polling_error}</span> : null}
        </div>
      ) : null}

      <div className={`map-stage map-stage-md goto-stage${runtimeMismatch ? " mismatch" : ""}`} ref={stageRef} onPointerDown={onStageDown}>
        {!renderMap ? <div className="map-empty">맵 데이터 없음</div> : (
          <>
            {renderMap.image_url ? <img src={renderMap.image_url} alt={renderMap.name} /> : null}
            <svg viewBox={`0 0 ${renderMap.width || 1000} ${renderMap.height || 800}`} preserveAspectRatio="xMidYMid meet">
              {targetLine ? <line className="goto-yaw" x1={targetLine[0].x} y1={targetLine[0].y} x2={targetLine[1].x} y2={targetLine[1].y} /> : null}
              {trailPoints ? <polyline className={`map-path${runtimeMismatch ? " mismatch" : ""}`} points={trailPoints} /> : null}
              {overlayReady ? poses.map((p) => {
                const pt = worldToPixel(renderMap, p.x, p.y);
                const yawDegR = -((p.yaw || 0) * 180) / Math.PI;
                return (
                  <g key={p.robot_id} className={runtimeMismatch ? "map-pose mismatch" : "map-pose"} transform={`translate(${pt.x} ${pt.y}) rotate(${yawDegR}) scale(${robotScale})`}>
                    <polygon className={`map-robot live${runtimeMismatch ? " mismatch" : ""}`} points="9,0 -7,5 -5,0 -7,-5" />
                  </g>
                );
              }) : null}
              {tp && overlayReady ? (
                <g data-goto>
                  <line className="goto-yaw" x1={tp.x} y1={tp.y} x2={tp.x + yawLen * Math.cos(yaw)} y2={tp.y - yawLen * Math.sin(yaw)} />
                  <circle className="goto-yaw-handle" data-goto-handle cx={tp.x + yawLen * Math.cos(yaw)} cy={tp.y - yawLen * Math.sin(yaw)} r={handleR}
                    onPointerDown={(e) => { e.stopPropagation(); e.preventDefault(); dragKind.current = "yaw"; setGuide(null); }} />
                  <circle className="goto-ring" cx={tp.x} cy={tp.y} r={ringR}
                    onPointerDown={(e) => { e.stopPropagation(); dragKind.current = "move"; }} />
                  <circle className="goto-dot" cx={tp.x} cy={tp.y} r={dotR} />
                </g>
              ) : null}
            </svg>
            {guide ? <div className="cursor-guide mono" style={{ left: guide.left, top: guide.top }}>x {guide.x.toFixed(2)} · y {guide.y.toFixed(2)}</div> : null}
            {target ? <div className="stage-coords mono">목표 x {target.x.toFixed(2)} · y {target.y.toFixed(2)} · {Math.round(Number(yawDeg) || 0)}°</div> : null}
          </>
        )}
      </div>

      <div className="btnbar">
        {mode === "initial_pose" ? (
          <button className="btn" disabled={busy || !target || robotBlocked} onClick={runInitialPose}>Initial Pose 전송</button>
        ) : (
          <>
            <button className="btn secondary" disabled={busy || robotBlocked} onClick={() => run("preview")}>Preview</button>
            <button className="btn" disabled={busy || robotBlocked} onClick={() => run("go")}>이동</button>
          </>
        )}
      </div>
      <div className="status-line mono">{status}</div>
    </div>
  );
}

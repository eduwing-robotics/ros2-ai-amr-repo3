import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useMaps } from "../../hooks/useScenarioData";
import { useAdminMutations } from "../../hooks/useAdminData";
import { useFeedback } from "../../components/FeedbackProvider";
import { useGotoTarget } from "../operate/GotoTargetContext";
import { radToDeg, degToRad } from "../../lib/coords";
import { missionGoto, movementMapState, robotLocalization, robotNavState } from "../../lib/missions";
import { isMapRuntimeMismatch, mapAssetWarning, runtimeBadgeLabel } from "../../lib/mapRuntime";
import { shortId } from "../../lib/format";
import type { Robot } from "../../types";

export function MapGotoOperate({
  robots,
  disabled,
  isRobotEmergency,
}: {
  robots: Robot[];
  disabled?: boolean;
  isRobotEmergency?: (robotId: string) => boolean;
}) {
  const { target, mapId, setTarget, markActive, clearTarget } = useGotoTarget();
  const { data: maps = [] } = useMaps();
  const { teleop } = useAdminMutations();
  const { toast } = useFeedback();
  const [status, setStatus] = useState("맵을 클릭해 목적지를 지정하세요.");
  const [busy, setBusy] = useState(false);
  const [kx, setKx] = useState("");
  const [ky, setKy] = useState("");
  const [kyaw, setKyaw] = useState("");
  const robot = robots[0]?.robot_id || "";
  const map = useMemo(() => maps.find((m) => m.map_id === mapId) ?? null, [maps, mapId]);
  const runtimeMismatch = isMapRuntimeMismatch(map);
  const assetWarning = mapAssetWarning(map);
  const { data: mapState } = useQuery({
    queryKey: ["movement-map-state"],
    queryFn: movementMapState,
    refetchInterval: 5000,
  });
  const { data: localization } = useQuery({
    queryKey: ["robot-localization", robot],
    queryFn: () => robotLocalization(robot),
    enabled: Boolean(robot),
    refetchInterval: 2000,
  });
  const { data: navState } = useQuery({
    queryKey: ["robot-nav-state", robot],
    queryFn: () => robotNavState(robot),
    enabled: Boolean(robot),
    refetchInterval: 2000,
  });
  const activeMapId = mapState?.active_map_id || "";
  const mapIdMismatch = Boolean(mapId && activeMapId && mapId !== activeMapId);
  const robotBlocked = Boolean(disabled) || Boolean(robot && isRobotEmergency?.(robot));
  const readinessBlocked =
    navState?.robot_online === false
    || navState?.command_accepting === false
    || localization?.localized === false;
  const blockedReason = robotBlocked
    ? disabled ? "맵 이동 불가" : "비상 정지 중 — 맵 이동 불가"
    : runtimeMismatch || mapIdMismatch
      ? assetWarning || "좌표계 불일치 — 이동 전 맵 정렬을 확인하세요"
      : readinessBlocked
        ? navState?.robot_online === false
          ? "로봇 오프라인"
          : localization?.localized === false
            ? localization.reason || "위치 미확정(localized=false)"
            : navState?.command_accepting === false
              ? navState.reason || "명령 수신 불가"
              : "이동 준비 안 됨"
        : null;
  const gotoBlocked = Boolean(blockedReason);

  useEffect(() => {
    if (!target) return;
    setKx(target.x.toFixed(2));
    setKy(target.y.toFixed(2));
    setKyaw(radToDeg(target.yaw ?? 0).toFixed(0));
  }, [target]);

  const go = async () => {
    if (gotoBlocked) { setStatus(blockedReason || "이동 불가"); return; }
    if (!robot) { setStatus("로봇을 선택하세요."); return; }
    if (!mapId || !target) { setStatus("맵에서 목적지를 클릭하세요."); return; }
    setBusy(true);
    try {
      const r = await missionGoto({
        robot_id: robot,
        map_id: mapId,
        x: target.x,
        y: target.y,
        yaw: target.yaw ?? 0,
      });
      markActive(robot, r.command_id);
      setStatus(`이동 중: ${shortId(r.command_id)} · 목적지는 도착까지 맵에 유지됩니다.`);
      toast(`이동 요청 전송 (${shortId(r.command_id)})`, "ok");
    } catch (e) {
      const msg = (e as Error).message;
      setStatus(`실패: ${msg}`);
      toast(`이동 실패: ${msg}`, "err");
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    if (!robot) return;
    setBusy(true);
    try {
      await teleop.mutateAsync({ robot_id: robot, command: "stop", hold: false, source: "operate_goto_stop" });
      clearTarget();
      setStatus(`정지: ${robot}`);
      toast("이동 정지", "info");
    } catch (e) {
      const msg = (e as Error).message;
      setStatus(`정지 실패: ${msg}`);
      toast(`정지 실패: ${msg}`, "err");
    } finally {
      setBusy(false);
    }
  };

  const applyKeyboardTarget = () => {
    const x = parseFloat(kx);
    const y = parseFloat(ky);
    const yawDeg = parseFloat(kyaw);
    if (Number.isNaN(x) || Number.isNaN(y)) {
      toast("x/y 좌표를 숫자로 입력하세요.", "err");
      return;
    }
    setTarget({ x, y, yaw: Number.isNaN(yawDeg) ? 0 : degToRad(yawDeg) });
    setStatus("키보드 목표 적용됨 — 이동 버튼으로 전송");
  };

  return (
    <div className="panel map-goto-minimal">
      <h2>맵 이동</h2>
      {blockedReason && !disabled ? (
        <p className="inline-alert warn compact-alert">{blockedReason}</p>
      ) : null}
      <div className="toolbar">
        <span className="rowcount runtime-badge">{runtimeBadgeLabel(map, activeMapId)}</span>
        <span className="rowcount mono">UI map {mapId || "—"}</span>
        <span className="goto-robot-context"><b>{robots[0]?.display_name || robot || "로봇 없음"}</b>{robot ? <code>{robot}</code> : null}</span>
        <button type="button" className="btn" disabled={gotoBlocked || busy || !target} onClick={() => void go()}>이동</button>
        <button type="button" className="btn danger" disabled={robotBlocked || busy} onClick={() => void stop()}>정지</button>
      </div>
      <div className="toolbar goto-kb-row">
        <label className="field-inline">x<input className="filter narrow" value={kx} onChange={(e) => setKx(e.target.value)} disabled={gotoBlocked} /></label>
        <label className="field-inline">y<input className="filter narrow" value={ky} onChange={(e) => setKy(e.target.value)} disabled={gotoBlocked} /></label>
        <label className="field-inline">yaw°<input className="filter narrow" value={kyaw} onChange={(e) => setKyaw(e.target.value)} disabled={gotoBlocked} /></label>
        <button type="button" className="btn" disabled={gotoBlocked} onClick={applyKeyboardTarget}>목표 적용</button>
      </div>
      <div className="status-line mono">
        {target
          ? `목표 x ${target.x.toFixed(2)} · y ${target.y.toFixed(2)} · yaw ${radToDeg(target.yaw ?? 0).toFixed(0)}°`
          : "목표 없음"}
        {" · "}
        {target ? "핸들 끌어 방향 지정 · " : ""}
        {status}
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { arucoLatest } from "../../lib/aruco";
import { postManualDrive } from "../../lib/robotCommands";
import { useEmergency } from "../../hooks/useEmergency";
import type { Robot, TeleopCommand } from "../../types";

/** 수동 ArUco 정렬 테스트 — aruco/latest readout + manual_drive teleop(PHASE_19). */
export function ArucoManualTest({ robots }: { robots: Robot[] }) {
  const { isEmergency } = useEmergency();
  const [robotId, setRobotId] = useState("");
  const [markerId, setMarkerId] = useState("101");
  const [polling, setPolling] = useState(false);
  const [teleopStatus, setTeleopStatus] = useState("");

  const robot = robotId || robots[0]?.robot_id || "";
  const marker = Number(markerId) || 0;

  const { data, error, isFetching, dataUpdatedAt } = useQuery({
    queryKey: ["aruco-latest", robot, marker],
    queryFn: () => arucoLatest(robot, marker),
    enabled: polling && Boolean(robot) && marker > 0,
    refetchInterval: polling ? 500 : false,
  });

  useEffect(() => {
    if (robots.length && !robotId) setRobotId(robots[0].robot_id);
  }, [robots, robotId]);

  const detection = data?.detections?.find((d) => d.marker_id === marker) ?? data?.detections?.[0];

  const sendTeleop = async (command: TeleopCommand, hold: boolean) => {
    if (isEmergency) {
      setTeleopStatus("비상 정지 중 — 수동 조작 불가");
      return;
    }
    if (!robot) {
      setTeleopStatus("로봇을 선택하세요.");
      return;
    }
    try {
      await postManualDrive({ robot_id: robot, command, hold, source: "aruco_manual_test" });
      setTeleopStatus(`${hold ? "hold" : "stop"}: ${command}`);
    } catch (e) {
      setTeleopStatus(`teleop 실패: ${(e as Error).message}`);
    }
  };

  const holdBtn = (command: TeleopCommand, label: string) => (
    <button
      type="button"
      className="movebtn"
      disabled={isEmergency || !robot}
      onPointerDown={(e) => { e.preventDefault(); void sendTeleop(command, true); }}
      onPointerUp={() => void sendTeleop("stop", false)}
      onPointerLeave={() => void sendTeleop("stop", false)}
    >
      {label}
    </button>
  );

  return (
    <div className="panel aruco-manual-test">
      <h2>수동 ArUco 정렬</h2>
      <p className="muted">`GET /aruco/latest` 검출값을 보며 `manual_drive`로 미세 정렬. 자동 정렬 실행은 명령 envelope 시험 패널의 `aruco_align`을 사용.</p>
      <div className="fields compact-fields">
        <div className="field">
          <span className="chip">로봇</span>
          <select className="filter" value={robot} disabled={isEmergency} onChange={(e) => setRobotId(e.target.value)}>
            <option value="">선택</option>
            {robots.map((r) => (
              <option key={r.robot_id} value={r.robot_id}>{r.robot_id}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <span className="chip">marker_id</span>
          <input
            className="search mono"
            type="number"
            min={0}
            value={markerId}
            onChange={(e) => setMarkerId(e.target.value)}
          />
        </div>
        <div className="field">
          <span className="chip">폴링</span>
          <label className="switch-line">
            <input
              type="checkbox"
              checked={polling}
              disabled={!robot || marker <= 0}
              onChange={(e) => setPolling(e.target.checked)}
            />
            500ms 갱신
          </label>
        </div>
      </div>

      <div className="aruco-readout mono">
        {error ? (
          <span className="inline-alert err">조회 실패: {(error as Error).message}</span>
        ) : !polling ? (
          <span className="muted">폴링을 켜면 검출값이 표시됩니다.</span>
        ) : isFetching && !data ? (
          <span>검출 조회 중…</span>
        ) : detection ? (
          <>
            <span>center_error_norm <b>{detection.center_error_norm?.toFixed(4) ?? "—"}</b></span>
            <span>marker_width_px <b>{detection.marker_width_px ?? "—"}</b></span>
            <span>estimated_distance_m <b>{detection.estimated_distance_m?.toFixed(3) ?? "—"}</b></span>
            <span className="muted">source {data?.source ?? "—"} · {new Date(dataUpdatedAt).toLocaleTimeString()}</span>
          </>
        ) : (
          <span className="inline-alert warn">검출 없음 — 마커 {marker}가 카메라에 보이는지 확인하세요.</span>
        )}
      </div>

      <div className="aruco-teleop-row">
        <span className="chip">teleop</span>
        <div className="controller manual compact">
          <span className="ghost" />
          {holdBtn("forward", "▲")}
          <span className="ghost" />
          {holdBtn("left", "◀")}
          <button type="button" className="movebtn stop" disabled={isEmergency || !robot} onClick={() => void sendTeleop("stop", false)}>■</button>
          {holdBtn("right", "▶")}
          <span className="ghost" />
          {holdBtn("backward", "▼")}
          <span className="ghost" />
        </div>
      </div>
      {teleopStatus ? <div className="status-line mono">{teleopStatus}</div> : null}
    </div>
  );
}

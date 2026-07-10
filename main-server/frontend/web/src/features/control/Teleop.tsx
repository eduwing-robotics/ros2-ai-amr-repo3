import { useCallback, useEffect, useRef, useState } from "react";
import { useAdminMutations } from "../../hooks/useAdminData";
import { useFeedback } from "../../components/FeedbackProvider";
import { shortId } from "../../lib/format";
import type { Robot, TeleopCommand } from "../../types";

const KEY_MAP: Record<string, TeleopCommand> = {
  ArrowUp: "forward",
  ArrowDown: "backward",
  ArrowLeft: "left",
  ArrowRight: "right",
  w: "forward",
  s: "backward",
  a: "left",
  d: "right",
  " ": "stop",
};

// 수동 조작 패널 (레거시 대시보드 teleop). 버튼 누름=hold 시작, 떼면 정지.
export function Teleop({
  robots,
  disabled,
  keyboardEnabled = true,
  isRobotEmergency,
}: {
  robots: Robot[];
  disabled?: boolean;
  keyboardEnabled?: boolean;
  isRobotEmergency?: (robotId: string) => boolean;
}) {
  const { teleop } = useAdminMutations();
  const { toast } = useFeedback();
  const [robotId, setRobotId] = useState("");
  const [status, setStatus] = useState("로봇을 선택하고 방향 버튼을 누르세요.");
  const holdingRef = useRef(false);
  const stopSentRef = useRef(false);
  const activePointerRef = useRef<number | null>(null);
  const robot = robotId || robots[0]?.robot_id || "";
  const robotBlocked = Boolean(disabled) || Boolean(robot && isRobotEmergency?.(robot));

  const send = useCallback(async (command: TeleopCommand, hold: boolean) => {
    if (robotBlocked) { setStatus("비상 정지 중 — 수동 조작 불가"); return; }
    if (!robot) { setStatus("전송 실패: 선택 가능한 로봇이 없습니다."); return; }
    const label = command === "stop" ? "정지" : hold ? "시작" : "전송";
    setStatus(`${label}: ${robot} / ${command} · 전송 중`);
    try {
      const r = await teleop.mutateAsync({ robot_id: robot, command, hold, source: "dashboard_manual_ui" });
      setStatus(`${label} 완료: ${r.robot_id} / ${r.command} / ${shortId(r.command_id)} / ${r.movement_mode}`);
    } catch (e) {
      const msg = (e as Error).message;
      setStatus(`전송 실패: ${msg}`);
      toast(`수동 조작 실패: ${msg}`, "err");
    }
  }, [robotBlocked, robot, teleop, toast]);

  const ensureStop = useCallback(() => {
    if (stopSentRef.current || !holdingRef.current) return;
    stopSentRef.current = true;
    holdingRef.current = false;
    activePointerRef.current = null;
    void send("stop", false);
  }, [send]);

  const beginHold = useCallback((command: TeleopCommand, pointerId?: number) => {
    stopSentRef.current = false;
    holdingRef.current = true;
    if (pointerId !== undefined) activePointerRef.current = pointerId;
    void send(command, true);
  }, [send]);

  useEffect(() => {
    if (!keyboardEnabled) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (robotBlocked || e.repeat) return;
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      const cmd = KEY_MAP[e.key];
      if (!cmd) return;
      e.preventDefault();
      if (cmd === "stop") {
        ensureStop();
        return;
      }
      beginHold(cmd);
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (!holdingRef.current) return;
      if (!KEY_MAP[e.key] || e.key === " ") return;
      ensureStop();
    };
    const onBlur = () => ensureStop();
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onBlur);
      ensureStop();
    };
  }, [beginHold, ensureStop, keyboardEnabled, robotBlocked]);

  const releasePointer = useCallback((pointerId: number) => {
    if (activePointerRef.current !== null && activePointerRef.current !== pointerId) return;
    ensureStop();
  }, [ensureStop]);

  const holdBtn = (command: TeleopCommand, label: string, cls = "movebtn") => (
    <button
      className={cls}
      disabled={robotBlocked}
      onPointerDown={(e) => {
        e.preventDefault();
        if (robotBlocked) return;
        e.currentTarget.setPointerCapture(e.pointerId);
        beginHold(command, e.pointerId);
      }}
      onPointerUp={(e) => releasePointer(e.pointerId)}
      onPointerCancel={(e) => releasePointer(e.pointerId)}
      onLostPointerCapture={(e) => releasePointer(e.pointerId)}
      onPointerLeave={(e) => {
        if (e.currentTarget.hasPointerCapture(e.pointerId)) return;
        releasePointer(e.pointerId);
      }}
    >
      {label}
    </button>
  );

  return (
    <div className="panel">
      <h2>수동 조작</h2>
      <div className="toolbar">
        <select className="filter" value={robot} disabled={robotBlocked} onChange={(e) => setRobotId(e.target.value)}>
          {robots.length === 0 ? <option value="">로봇 없음</option> : robots.map((r) => <option key={r.robot_id} value={r.robot_id}>{r.robot_id}</option>)}
        </select>
      </div>
      <div className="controller manual">
        <span className="ghost" />
        {holdBtn("forward", "▲")}
        <span className="ghost" />
        {holdBtn("left", "◀")}
        <button className="movebtn stop" disabled={robotBlocked} onClick={() => void send("stop", false)}>■</button>
        {holdBtn("right", "▶")}
        <span className="ghost" />
        {holdBtn("backward", "▼")}
        <span className="ghost" />
      </div>
      <div className="status-line" id="teleopStatus">{status}</div>
      <p className="hint-text">{keyboardEnabled ? "화살표키·WASD로도 조작 (hold)" : "키보드 조작은 패널을 펼친 뒤에만 활성화됩니다."}</p>
    </div>
  );
}

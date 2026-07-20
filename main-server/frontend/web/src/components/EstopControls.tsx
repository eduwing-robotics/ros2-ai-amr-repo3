import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { robotClearEstop, robotEstopAll, type EstopResult } from "../lib/safety";
import { useEmergency } from "../hooks/useEmergency";
import { useFeedback } from "./FeedbackProvider";

function failedRobotSummary(result: EstopResult) {
  return result.robots
    .filter((r) => !r.ok)
    .map((r) => r.robot_id + (r.error ? " (" + r.error + ")" : ""))
    .join(", ");
}

export function EstopControls() {
  const { estopState, emergencyRobots, unknownRobots } = useEmergency();
  const queryClient = useQueryClient();
  const { confirm, toast } = useFeedback();
  const [busy, setBusy] = useState(false);
  const canClearEstop = estopState === "active" && emergencyRobots.length > 0;

  const refreshSafety = async () => {
    await queryClient.invalidateQueries({ queryKey: ["status"] });
    await queryClient.invalidateQueries({ queryKey: ["recovery-needs-attention"] });
  };

  const triggerEstop = async () => {
    setBusy(true);
    try {
      const result = await robotEstopAll();
      await refreshSafety();
      if (result.ok) {
        toast("비상 정지 — 전 로봇 정지", "err");
      } else {
        toast("비상 정지 요청됨 — 확인 실패: " + (failedRobotSummary(result) || "unknown"), "err");
      }
    } catch (e) {
      toast(`ESTOP 실패: ${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  };

  const clearEstop = async (robotId: string) => {
    const ok = await confirm({
      title: `${robotId} 비상 정지 해제`,
      message:
        `${robotId}의 비상 정지만 해제합니다.\n` +
        "다른 로봇의 정지 상태는 변경하지 않습니다.\n" +
        "해제 후 작업은 자동 재개되지 않습니다.",
      confirmLabel: "해제",
      danger: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      const result = await robotClearEstop(robotId);
      await refreshSafety();
      if (!result.ok) {
        throw new Error(`Movement 해제 실패: ${failedRobotSummary(result) || robotId}`);
      }
      toast(`${robotId} 비상 정지 해제됨 — 작업은 복구 선택 필요`, "ok");
    } catch (e) {
      toast(`${robotId} 해제 실패: ${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="estop-controls">
      {canClearEstop ? (
        <>
          {emergencyRobots.map((robotId) => (
            <button
              key={robotId}
              type="button"
              className="estop-btn active"
              disabled={busy}
              onClick={() => void clearEstop(robotId)}
              title={`${robotId} 비상 정지만 해제`}
            >
              {robotId} 해제
            </button>
          ))}
          {unknownRobots.length > 0 ? (
            <span className="pill warn" title={`상태 미확인: ${unknownRobots.join(", ")}`}>
              미확인 {unknownRobots.length}
            </span>
          ) : null}
        </>
      ) : (
        <button
          type="button"
          className={estopState === "unknown" ? "estop-btn active" : "estop-btn"}
          disabled={busy}
          onClick={() => void triggerEstop()}
          title="전 로봇 즉시 정지"
        >
          {estopState === "unknown" ? `ESTOP 미확인 ${unknownRobots.length}` : "ESTOP"}
        </button>
      )}
    </div>
  );
}

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiSend } from "../lib/api";
import { useEmergency } from "../hooks/useEmergency";
import { useFeedback } from "./FeedbackProvider";

interface EstopResult {
  ok: boolean;
  state?: "clear" | "partial" | "failed" | "unknown";
  partial?: boolean;
  unknown_robots?: string[];
  robots: { robot_id: string; ok: boolean; error?: string; response?: unknown }[];
}

const robotEstopAll = () => apiSend<EstopResult>("/robots/estop-all", "POST");
const robotClearEstopAll = () => apiSend<EstopResult>("/robots/clear-estop-all", "POST");
const CLEAR_CONFIRM_MESSAGE =
  "비상 정지를 해제하시겠습니까?\n해제 후 로봇이 자동으로 재개되지는 않습니다.\n현장 안전과 적재 상태를 확인한 뒤 복구 방식을 선택하세요.";

function failedRobotSummary(result: EstopResult) {
  return result.robots
    .filter((r) => !r.ok)
    .map((r) => r.robot_id + (r.error ? " (" + r.error + ")" : ""))
    .join(", ");
}

export function EstopControls() {
  const { isEmergency, estopState, unknownRobots } = useEmergency();
  const queryClient = useQueryClient();
  const { confirm, toast } = useFeedback();
  const [busy, setBusy] = useState(false);

  const refreshSafety = async () => {
    await queryClient.invalidateQueries({ queryKey: ["status"] });
    await queryClient.invalidateQueries({ queryKey: ["recovery-awaiting-operator"] });
  };

  const triggerEstop = async () => {
    setBusy(true);
    try {
      const result = await robotEstopAll();
      await refreshSafety();
      toast(result.ok ? "비상 정지 — 전 로봇 정지" : "비상 정지 요청됨 — 확인 실패: " + (failedRobotSummary(result) || "unknown"), "err");
    } catch (e) {
      toast(`ESTOP 실패: ${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  };

  const clearEstop = async () => {
    const confirmed = await confirm({
      title: "비상 정지 해제",
      message: CLEAR_CONFIRM_MESSAGE,
      confirmLabel: "해제",
      danger: true,
    });
    if (!confirmed) return;
    setBusy(true);
    try {
      const result = await robotClearEstopAll();
      await refreshSafety();
      if (result.state === "partial" || result.partial) {
        toast(`일부 해제 · 상태 미확인: ${(result.unknown_robots ?? []).join(", ") || "unknown"}`, "err");
      } else if (!result.ok) {
        throw new Error("Movement 해제 실패: " + (failedRobotSummary(result) || "unknown"));
      } else {
        toast("비상 정지 해제됨 — 작업은 복구 선택 필요", "ok");
      }
    } catch (e) {
      toast(`해제 실패: ${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="estop-controls">
      {isEmergency ? (
        <button type="button" className="estop-btn active" disabled={busy} onClick={() => void clearEstop()} title="클릭하여 해제 또는 미확인 상태 재조회">
          {estopState === "unknown" ? `ESTOP 미확인 ${unknownRobots.length}` : "ESTOP 활성"}
        </button>
      ) : (
        <button type="button" className="estop-btn" disabled={busy} onClick={() => void triggerEstop()} title="전 로봇 즉시 정지">
          ESTOP
        </button>
      )}
    </div>
  );
}

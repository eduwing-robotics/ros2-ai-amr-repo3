import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { robotClearEstopAll, robotEstopAll, type EstopResult } from "../lib/safety";
import { useEmergency } from "../hooks/useEmergency";
import { useFeedback } from "./FeedbackProvider";

const CLEAR_CONFIRM_MESSAGE =
  "비상 정지를 해제하시겠습니까?\n해제 후 로봇이 자동으로 재개되지는 않습니다.\n현장 안전과 적재 상태를 확인한 뒤 복구 방식을 선택하세요.";

function failedRobotSummary(result: EstopResult) {
  return result.robots
    .filter((r) => !r.ok)
    .map((r) => r.robot_id + (r.error ? " (" + r.error + ")" : ""))
    .join(", ");
}

export function EstopControls() {
  const { isEmergency } = useEmergency();
  const queryClient = useQueryClient();
  const { confirm, toast } = useFeedback();
  const [busy, setBusy] = useState(false);

  const triggerEstop = async () => {
    setBusy(true);
    try {
      const result = await robotEstopAll();
      await queryClient.invalidateQueries({ queryKey: ["status"] });
      await queryClient.invalidateQueries({ queryKey: ["recovery-needs-attention"] });
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

  const clearEstop = async () => {
    const ok = await confirm({
      title: "비상 정지 해제",
      message: CLEAR_CONFIRM_MESSAGE,
      confirmLabel: "해제",
      danger: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      const result = await robotClearEstopAll();
      await queryClient.invalidateQueries({ queryKey: ["status"] });
      await queryClient.invalidateQueries({ queryKey: ["recovery-needs-attention"] });
      if (!result.ok) {
        throw new Error("Movement 해제 실패: " + (failedRobotSummary(result) || "unknown"));
      }
      toast("비상 정지 해제됨 — 작업은 복구 선택 필요", "ok");
    } catch (e) {
      toast(`해제 실패: ${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="estop-controls">
      {isEmergency ? (
        <button
          type="button"
          className="estop-btn active"
          disabled={busy}
          onClick={() => void clearEstop()}
          title="클릭하여 해제"
        >
          ESTOP 활성
        </button>
      ) : (
        <button type="button" className="estop-btn" disabled={busy} onClick={() => void triggerEstop()} title="전 로봇 즉시 정지">
          ESTOP
        </button>
      )}
    </div>
  );
}

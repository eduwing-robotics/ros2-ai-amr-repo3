import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Panel } from "../../components/Panel";
import { Button } from "../../components/Button";
import {
  executeRecovery,
  fetchNeedsAttentionTasks,
  previewRecovery,
  type CargoState,
  type RecoveryContext,
  type RecoveryStrategy,
} from "../../lib/recovery";
import { useFeedback } from "../../components/FeedbackProvider";

const CARGO_OPTIONS: { id: CargoState; label: string }[] = [
  { id: "LOADED", label: "적재됨" },
  { id: "EMPTY", label: "비어 있음" },
  { id: "UNKNOWN", label: "확인 필요" },
];
const STRATEGY_OPTIONS: { id: RecoveryStrategy; label: string }[] = [
  { id: "safe_move", label: "안전지점으로 이동" },
  { id: "manual_abort", label: "로봇 정지 후 작업 중단" },
];

function RecoveryPanel({ ctx }: { ctx: RecoveryContext }) {
  const { toast } = useFeedback();
  const queryClient = useQueryClient();
  const [cargo, setCargo] = useState<CargoState>("UNKNOWN");
  const [strategy, setStrategy] = useState<RecoveryStrategy>("safe_move");
  const [checks, setChecks] = useState({
    site_clear: false,
    pose_ok: false,
    cargo_ok: false,
  });
  const [busy, setBusy] = useState(false);

  const allChecks = checks.site_clear && checks.pose_ok && checks.cargo_ok;
  const hasKnownCargo = cargo !== "UNKNOWN";
  const isRecoveryRunning = ctx.orchestration_phase === "RECOVERY_RUNNING";
  const canExecute = !isRecoveryRunning && allChecks && hasKnownCargo;

  const executeLabel =
    strategy === "safe_move" ? "안전지점 이동 실행" : "정지 확인 후 작업 중단";

  const strategyHint =
    strategy === "safe_move"
      ? "설정된 안전지점으로 이동합니다. 기존 작업은 자동으로 재개하지 않습니다."
      : "로봇 정지가 확인된 경우에만 작업을 중단합니다. 필요하면 새 입출고 요청을 생성하세요.";

  const onPreview = async () => {
    try {
      const plan = await previewRecovery(ctx.task_id, { cargo_state: cargo, strategy });
      toast(`복구 미리보기: ${plan.steps.length}단계`, "ok");
    } catch (e) {
      toast(`미리보기 실패: ${(e as Error).message}`, "err");
    }
  };

  const onExecute = async () => {
    setBusy(true);
    try {
      const result = await executeRecovery(ctx.task_id, { cargo_state: cargo, strategy, checks });
      await queryClient.invalidateQueries({ queryKey: ["recovery-needs-attention"] });
      const message = typeof result.message === "string" ? result.message : "복구 명령 전송됨";
      toast(message, "ok");
    } catch (e) {
      toast(`복구 실행 실패: ${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="recovery-panel">
      <p className="recovery-banner">
        {ctx.orchestration_phase === "RECOVERY_RUNNING"
          ? "복구 이동 진행 중"
          : "복구 필요"} — task #{ctx.task_id} · robot {ctx.assigned_robot_id ?? "—"} · step{" "}
        {ctx.last_step_kind ?? ctx.last_leg_kind ?? "—"}
      </p>
      <div className="recovery-checks">
        <label>
          <input
            type="checkbox"
            checked={checks.site_clear}
            onChange={(e) => setChecks((c) => ({ ...c, site_clear: e.target.checked }))}
          />
          현장 위험 해소 확인
        </label>
        <label>
          <input
            type="checkbox"
            checked={checks.pose_ok}
            onChange={(e) => setChecks((c) => ({ ...c, pose_ok: e.target.checked }))}
          />
          로봇 위치/방향 확인
        </label>
        <label>
          <input
            type="checkbox"
            checked={checks.cargo_ok}
            onChange={(e) => setChecks((c) => ({ ...c, cargo_ok: e.target.checked }))}
          />
          적재 상태 확인
        </label>
      </div>
      <div className="recovery-row">
        <span>적재 상태</span>
        {CARGO_OPTIONS.map((opt) => (
          <label key={opt.id}>
            <input
              type="radio"
              name={`cargo-${ctx.task_id}`}
              checked={cargo === opt.id}
              onChange={() => setCargo(opt.id)}
            />
            {opt.label}
          </label>
        ))}
      </div>
      <div className="recovery-row">
        <span>복구 방식</span>
        {STRATEGY_OPTIONS.map((opt) => (
          <label key={opt.id}>
            <input
              type="radio"
              name={`strategy-${ctx.task_id}`}
              checked={strategy === opt.id}
              onChange={() => setStrategy(opt.id)}
            />
            {opt.label}
          </label>
        ))}
      </div>
      <p className="muted recovery-strategy-hint">{strategyHint}</p>
      {!hasKnownCargo && (
        <p className="muted recovery-strategy-hint">적재 상태를 확인해야 복구 단계를 실행할 수 있습니다.</p>
      )}
      <div className="recovery-actions">
        <Button type="button" variant="secondary" disabled={!hasKnownCargo || busy} onClick={() => void onPreview()}>
          단계 미리보기
        </Button>
        <Button type="button" disabled={!canExecute || busy} onClick={() => void onExecute()}>
          {executeLabel}
        </Button>
      </div>
    </div>
  );
}

export function TaskRecoveryBanner() {
  const { data: tasks = [] } = useQuery({
    queryKey: ["recovery-needs-attention"],
    queryFn: fetchNeedsAttentionTasks,
    refetchInterval: 5000,
  });

  if (!tasks.length) return null;

  return (
    <Panel title="작업 복구">
      {tasks.map((ctx) => (
        <RecoveryPanel key={ctx.task_id} ctx={ctx} />
      ))}
    </Panel>
  );
}

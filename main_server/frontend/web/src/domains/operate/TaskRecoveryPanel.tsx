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
} from "./recovery";
import { useFeedback } from "../../components/FeedbackProvider";
import { describeApiError } from "../../lib/apiErrors";

const CARGO_OPTIONS: CargoState[] = ["LOADED", "EMPTY", "UNKNOWN"];
const STRATEGY_OPTIONS: { id: RecoveryStrategy; label: string }[] = [
  { id: "safe_move", label: "안전 위치로 이동" },
  { id: "manual_abort", label: "작업 종료 및 수동 회수" },
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
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof previewRecovery>> | null>(null);

  const allChecks = checks.site_clear && checks.pose_ok && checks.cargo_ok;
  const isRecoveryRunning = ctx.orchestration_phase === "RECOVERY_RUNNING";
  const canExecute =
    !isRecoveryRunning &&
    allChecks &&
    cargo !== "UNKNOWN";

  const executeLabel =
    strategy === "safe_move"
      ? "안전 위치 이동 실행"
      : "작업 종료 실행";

  const strategyHint =
    strategy === "safe_move"
      ? "지정된 HOME 안전 위치로 이동합니다. 자동 하역과 기존 작업 재개는 수행하지 않습니다."
      : "로봇 정지를 확인한 뒤 작업을 종료합니다. 화물은 현장에서 수동 회수합니다.";

  const onPreview = async () => {
    try {
      const plan = await previewRecovery(ctx.task_id, { cargo_state: cargo, strategy });
      setPreview(plan);
    } catch (e) {
      toast(`미리보기 실패: ${describeApiError(e)}`, "err");
    }
  };

  const onExecute = async () => {
    setBusy(true);
    try {
      const result = await executeRecovery(ctx.task_id, { cargo_state: cargo, strategy, checks });
      await queryClient.invalidateQueries({ queryKey: ["recovery-awaiting-operator"] });
      const message = typeof result.message === "string" ? result.message : "복구 명령 전송됨";
      toast(message, "ok");
    } catch (e) {
      toast(`복구 실행 실패: ${describeApiError(e)}`, "err");
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
          <label key={opt}>
            <input
              type="radio"
              name={`cargo-${ctx.task_id}`}
              checked={cargo === opt}
              onChange={() => { setCargo(opt); setPreview(null); }}
            />
            {opt}
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
              onChange={() => { setStrategy(opt.id); setPreview(null); }}
            />
            {opt.label}
          </label>
        ))}
      </div>
      <p className="muted recovery-strategy-hint">{strategyHint}</p>
      {cargo === "UNKNOWN" ? <p className="inline-alert warn compact-alert">적재 상태를 먼저 확인해야 복구를 실행할 수 있습니다.</p> : null}
      {preview ? (
        <div className="recovery-preview" aria-live="polite">
          <strong>복구 예정 단계</strong>
          <ol>
            {preview.steps.map((step, index) => {
              const params = step.params as Record<string, unknown> | undefined;
              return (
                <li key={index}>
                  {String(step.label ?? step.action ?? step.kind ?? `단계 ${index + 1}`)}
                  {params?.x != null && params?.y != null ? <span className="mono"> · x {String(params.x)} / y {String(params.y)}</span> : null}
                </li>
              );
            })}
          </ol>
          {(preview.limitations ?? []).map((line) => <p className="muted" key={line}>※ {line}</p>)}
        </div>
      ) : null}
      <div className="recovery-actions">
        <Button type="button" variant="secondary" disabled={cargo === "UNKNOWN" || busy} onClick={() => void onPreview()}>
          단계 미리보기
        </Button>
        <Button type="button" disabled={!canExecute || busy} onClick={() => void onExecute()}>
          {executeLabel}
        </Button>
      </div>
    </div>
  );
}

export function useRecoveryAttentionTasks() {
  return useQuery({
    queryKey: ["recovery-awaiting-operator"],
    queryFn: fetchNeedsAttentionTasks,
    refetchInterval: 5000,
  });
}

export function TaskRecoveryBanner() {
  const { data: tasks = [] } = useRecoveryAttentionTasks();

  if (!tasks.length) return null;

  return (
    <Panel title="작업 복구">
      {tasks.map((ctx) => (
        <RecoveryPanel key={ctx.task_id} ctx={ctx} />
      ))}
    </Panel>
  );
}

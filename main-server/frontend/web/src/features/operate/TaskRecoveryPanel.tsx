import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Panel } from "../../components/Panel";
import { Button } from "../../components/Button";
import {
  executeRecovery,
  cancelEvidenceOnly,
  fetchNeedsAttentionTasks,
  previewRecovery,
  retryEvidenceOnly,
  retryTaskEvidence,
  type CargoState,
  type RecoveryContext,
  type RecoveryStrategy,
} from "../../lib/recovery";
import { robotClearEstop } from "../../lib/safety";
import { restartRobotLocalization } from "../../lib/missions";
import { shortId } from "../../lib/format";
import { useFeedback } from "../../components/FeedbackProvider";

const CARGO_OPTIONS: { id: CargoState; label: string }[] = [
  { id: "LOADED", label: "적재됨" },
  { id: "EMPTY", label: "비어 있음" },
  { id: "UNKNOWN", label: "확인 필요" },
];
const STRATEGY_OPTIONS: { id: RecoveryStrategy; label: string }[] = [
  { id: "resume_task", label: "원래 작업 계속" },
  { id: "safe_move", label: "안전지점으로 이동" },
  { id: "manual_abort", label: "로봇 정지 후 작업 중단" },
];

function resumeUnavailableLabel(reason?: string | null) {
  if (reason === "resume_step_kind_requires_manual_recovery") return "현재 도킹·리프트 단계는 상태를 확인한 뒤 수동 복구해야 합니다.";
  if (reason === "resume_step_state_not_retryable") return "현재 단계 상태는 자동 재시도할 수 없습니다.";
  if (reason === "resume_interrupted_command_id_missing") return "중단된 이동 명령을 식별할 수 없어 자동 재시도를 차단했습니다.";
  return "현재 단계는 원래 작업 자동 재개 대상이 아닙니다.";
}

function evidenceResultLabel(result?: string | null) {
  if (result === "PASS") return "통과";
  if (result === "FAIL") return "불일치";
  if (result === "UNCERTAIN" || result === "NO_DECISION") return "증거 부족";
  return "확인 필요";
}

function evidenceActionLabel(operation?: unknown) {
  const normalized = String(operation ?? "").trim().toUpperCase().replace("DROPOFF", "DROP_OFF");
  return normalized === "PRE_DROP_OFF"
    ? { check: "하역 전 적재 확인", retry: "하역 전 적재 다시 확인" }
    : { check: "적재 확인", retry: "적재 다시 확인" };
}

const RECOVERY_ERROR_LABELS: Record<string, string> = {
  recovery_blocked_active_safety_stop:
    "이 작업의 안전정지 기록이 아직 열려 있습니다. 해당 로봇 E-stop을 해제한 뒤 다시 실행하세요.",
  recovery_live_health_unsafe:
    "Nav가 E-stop 해제 상태를 확인하지 못했습니다. 해당 로봇 상태를 재확인한 뒤 다시 실행하세요.",
  recovery_live_health_unavailable:
    "Nav 실시간 상태를 읽을 수 없습니다. 연결이 복구된 뒤 다시 실행하세요.",
  resume_interrupted_command_state_unavailable:
    "재기동 전 이동 명령의 종료 여부를 확인할 수 없어 복구를 차단했습니다.",
  resume_interrupted_command_still_active:
    "이전 이동 명령이 아직 활성 상태라 새 복구 명령을 보내지 않았습니다.",
};

function recoveryErrorDetail(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function recoveryErrorLabel(detail: string) {
  return RECOVERY_ERROR_LABELS[detail] ?? detail;
}

function EvidenceOnlyRecoveryPanel({ ctx }: { ctx: RecoveryContext }) {
  const { toast } = useFeedback();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const evidence = ctx.evidence ?? {};
  const evidenceLabel = evidenceActionLabel(evidence.operation);

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["recovery-needs-attention"] }),
      queryClient.invalidateQueries({ queryKey: ["tasks"] }),
    ]);
  };

  const retry = async () => {
    setBusy(true);
    try {
      const result = await retryEvidenceOnly(ctx.task_id);
      await refresh();
      const decision = (result.decision ?? {}) as Record<string, unknown>;
      toast(decision.approved === true ? `${evidenceLabel.check} 통과` : `${evidenceLabel.check} 조건과 맞지 않습니다`, decision.approved === true ? "ok" : "err");
    } catch (e) {
      toast(`${evidenceLabel.retry} 실패: ${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!confirm(`비물리 시험 task #${ctx.task_id}을 중단할까요?\n실제 재고에는 영향이 없습니다.`)) return;
    setBusy(true);
    try {
      await cancelEvidenceOnly(ctx.task_id);
      await refresh();
      toast("비물리 증거 시험을 중단했습니다", "ok");
    } catch (e) {
      toast(`시험 중단 실패: ${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="recovery-panel evidence-only-recovery">
      <p className="recovery-banner">비물리 {evidenceLabel.check} 필요 — task #{ctx.task_id}</p>
      <p><strong>{evidenceResultLabel(evidence.result)}</strong> · {evidence.operation ?? "evidence checkpoint"}</p>
      <p className="muted">
        구역 {evidence.vision_zone_id ?? "—"} · 기대 마커 {evidence.expected_marker_id ?? "—"} · 이유 {evidence.reason_code ?? ctx.hold_reason ?? "—"}
      </p>
      <p className="muted">NONPHYSICAL · 물리 리프트 검증 아님 · 재고 변경 없음</p>
      <div className="recovery-actions">
        <Button type="button" variant="secondary" disabled={busy} onClick={() => navigate("/operate/control")}>카메라 보기</Button>
        <Button type="button" disabled={busy} onClick={() => void retry()}>{evidenceLabel.retry}</Button>
        <Button type="button" variant="secondary" disabled={busy} onClick={() => void cancel()}>시험 중단</Button>
      </div>
    </div>
  );
}

function RecoveryPanel({ ctx }: { ctx: RecoveryContext }) {
  const { confirm, toast } = useFeedback();
  const queryClient = useQueryClient();
  const [cargo, setCargo] = useState<CargoState>("UNKNOWN");
  const [strategy, setStrategy] = useState<RecoveryStrategy>(
    ctx.resume_available ? "resume_task" : "safe_move",
  );
  const [checks, setChecks] = useState({
    site_clear: false,
    pose_ok: false,
    cargo_ok: false,
  });
  const [busy, setBusy] = useState(false);
  const [blockReason, setBlockReason] = useState<string | null>(null);

  const allChecks = checks.site_clear && checks.pose_ok && checks.cargo_ok;
  const hasKnownCargo = cargo !== "UNKNOWN";
  const isRecoveryRunning = ctx.orchestration_phase === "RECOVERY_RUNNING";
  const canExecute =
    !isRecoveryRunning
    && allChecks
    && hasKnownCargo
    && (strategy !== "resume_task" || ctx.resume_available === true);
  const isEvidenceHold = ctx.hold_reason === "evidence_gate";
  const evidenceLabel = evidenceActionLabel(ctx.evidence?.operation);

  const executeLabel = strategy === "resume_task"
    ? "원래 작업 계속"
    : strategy === "safe_move"
      ? "안전지점 이동 실행"
      : "정지 확인 후 작업 중단";

  const strategyHint = strategy === "resume_task"
    ? "중단된 Task와 목적지는 유지하고 현재 이동 단계를 새 명령으로 다시 실행합니다."
    : strategy === "safe_move"
      ? "원래 작업을 재개하지 않고 설정된 안전지점으로 이동합니다."
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
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["recovery-needs-attention"] }),
        queryClient.invalidateQueries({ queryKey: ["tasks"] }),
      ]);
      setBlockReason(null);
      const message = typeof result.message === "string" ? result.message : "복구 명령 전송됨";
      toast(message, "ok");
    } catch (e) {
      const detail = recoveryErrorDetail(e);
      setBlockReason(detail);
      toast(`복구 실행 실패: ${recoveryErrorLabel(detail)}`, "err");
    } finally {
      setBusy(false);
    }
  };

  const clearRobotSafetyStop = async () => {
    const robotId = ctx.assigned_robot_id;
    if (!robotId) return;
    const ok = await confirm({
      title: `${robotId} E-stop 해제`,
      message:
        "해당 로봇의 E-stop과 연결된 안전정지 기록만 해제합니다. 작업은 자동 재개되지 않으며, 상태 확인 후 ‘원래 작업 계속’을 다시 눌러야 합니다.",
      confirmLabel: "해제 및 재확인",
      danger: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      const result = await robotClearEstop(robotId);
      if (!result.ok) throw new Error("Movement가 E-stop 해제를 확인하지 못했습니다.");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["status"] }),
        queryClient.invalidateQueries({ queryKey: ["recovery-needs-attention"] }),
        queryClient.invalidateQueries({ queryKey: ["tasks"] }),
      ]);
      setBlockReason(null);
      toast(`${robotId} E-stop 해제 확인 — 작업은 아직 보류 중입니다`, "ok");
    } catch (e) {
      toast(`E-stop 해제 실패: ${recoveryErrorLabel(recoveryErrorDetail(e))}`, "err");
    } finally {
      setBusy(false);
    }
  };

  const restartLocalization = async () => {
    const robotId = ctx.assigned_robot_id;
    if (!robotId) return;
    const ok = await confirm({
      title: `${robotId} 위치 다시 찾기`,
      message:
        "로봇이 정지한 상태에서 들어 옮겼거나 현재 위치 추정이 잘못됐을 때 사용합니다. 로봇은 움직이지 않으며, 작업은 자동 재개되지 않습니다.",
      confirmLabel: "위치 다시 찾기",
    });
    if (!ok) return;
    setBusy(true);
    try {
      const result = await restartRobotLocalization(robotId);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["status"] }),
        queryClient.invalidateQueries({ queryKey: ["robot-localization", robotId] }),
        queryClient.invalidateQueries({ queryKey: ["recovery-needs-attention"] }),
      ]);
      toast(`위치 복구 명령 접수 (${shortId(result.command_id)}) · 작업은 계속 보류 중`, "ok");
    } catch (e) {
      toast(`위치 다시 찾기 실패: ${recoveryErrorLabel(recoveryErrorDetail(e))}`, "err");
    } finally {
      setBusy(false);
    }
  };

  const onRetryEvidence = async () => {
    setBusy(true);
    try {
      const result = await retryTaskEvidence(ctx.task_id, checks);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["recovery-needs-attention"] }),
        queryClient.invalidateQueries({ queryKey: ["tasks"] }),
      ]);
      const decision = (result.decision ?? {}) as Record<string, unknown>;
      toast(decision.approved === true ? `${evidenceLabel.check} 통과` : `${evidenceLabel.check} 조건과 맞지 않습니다`, decision.approved === true ? "ok" : "err");
    } catch (e) {
      toast(`${evidenceLabel.retry} 실패: ${(e as Error).message}`, "err");
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
      {ctx.execution_mode === "synthetic_hil" ? (
        <p className="muted recovery-strategy-hint">가상 리프트 시험 · 결과는 NONPHYSICAL이며 물리 lift 합격이나 재고 변경에 사용되지 않습니다.</p>
      ) : null}
      {isEvidenceHold ? (
        <p>
          <strong>{ctx.item_name ?? ctx.item_code ?? "품목 확인 필요"}</strong>
          {ctx.item_code && ctx.item_name ? <span className="muted"> ({ctx.item_code})</span> : null}
          <span className="muted"> · 기대 ArUco {ctx.evidence?.expected_marker_id == null ? "미지정" : `A${ctx.evidence.expected_marker_id}`} · {evidenceResultLabel(ctx.evidence?.result)}</span>
        </p>
      ) : null}
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
              disabled={opt.id === "resume_task" && ctx.resume_available !== true}
              onChange={() => setStrategy(opt.id)}
            />
            {opt.label}
          </label>
        ))}
      </div>
      <p className="muted recovery-strategy-hint">{strategyHint}</p>
      {blockReason ? (
        <p className="muted recovery-strategy-hint" role="alert">
          {recoveryErrorLabel(blockReason)}
        </p>
      ) : null}
      {!ctx.resume_available ? (
        <p className="muted recovery-strategy-hint">{resumeUnavailableLabel(ctx.resume_block_reason)}</p>
      ) : null}
      {isEvidenceHold ? (
        <p className="muted recovery-strategy-hint">{evidenceLabel.check} 불일치로 보류되었습니다. 현장·자세·적재 상태를 확인한 뒤 같은 단계를 다시 판정할 수 있습니다.</p>
      ) : null}
      {!hasKnownCargo && (
        <p className="muted recovery-strategy-hint">적재 상태를 확인해야 복구 단계를 실행할 수 있습니다.</p>
      )}
      <div className="recovery-actions">
        {ctx.assigned_robot_id ? (
          <Button type="button" variant="secondary" disabled={busy} onClick={() => void restartLocalization()}>
            위치 다시 찾기
          </Button>
        ) : null}
        {ctx.assigned_robot_id && (
          blockReason === "recovery_blocked_active_safety_stop"
          || blockReason === "recovery_live_health_unsafe"
        ) ? (
          <Button type="button" variant="secondary" disabled={busy} onClick={() => void clearRobotSafetyStop()}>
            {ctx.assigned_robot_id} E-stop 해제·상태 재확인
          </Button>
        ) : null}
        {isEvidenceHold ? (
          <Button type="button" disabled={!allChecks || busy} onClick={() => void onRetryEvidence()}>
            {evidenceLabel.retry}
          </Button>
        ) : null}
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

export function useRecoveryAttentionTasks() {
  return useQuery({
    queryKey: ["recovery-needs-attention"],
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
        ctx.execution_mode === "evidence_only"
          ? <EvidenceOnlyRecoveryPanel key={ctx.task_id} ctx={ctx} />
          : <RecoveryPanel key={ctx.task_id} ctx={ctx} />
      ))}
    </Panel>
  );
}

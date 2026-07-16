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

function evidenceResultLabel(result?: string | null) {
  if (result === "PASS") return "통과";
  if (result === "FAIL") return "불일치";
  if (result === "UNCERTAIN" || result === "NO_DECISION") return "증거 부족";
  return "확인 필요";
}

function EvidenceOnlyRecoveryPanel({ ctx }: { ctx: RecoveryContext }) {
  const { toast } = useFeedback();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const evidence = ctx.evidence ?? {};

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
      toast(decision.approved === true ? "증거 확인 통과" : "증거가 아직 조건과 맞지 않습니다", decision.approved === true ? "ok" : "err");
    } catch (e) {
      toast(`증거 재확인 실패: ${(e as Error).message}`, "err");
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
      <p className="recovery-banner">비물리 증거 확인 필요 — task #{ctx.task_id}</p>
      <p><strong>{evidenceResultLabel(evidence.result)}</strong> · {evidence.operation ?? "evidence checkpoint"}</p>
      <p className="muted">
        구역 {evidence.vision_zone_id ?? "—"} · 기대 마커 {evidence.expected_marker_id ?? "—"} · 이유 {evidence.reason_code ?? ctx.hold_reason ?? "—"}
      </p>
      <p className="muted">NONPHYSICAL · 물리 리프트 검증 아님 · 재고 변경 없음</p>
      <div className="recovery-actions">
        <Button type="button" variant="secondary" disabled={busy} onClick={() => navigate("/operate/control")}>카메라 보기</Button>
        <Button type="button" disabled={busy} onClick={() => void retry()}>증거 다시 확인</Button>
        <Button type="button" variant="secondary" disabled={busy} onClick={() => void cancel()}>시험 중단</Button>
      </div>
    </div>
  );
}

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
  const isEvidenceHold = ctx.hold_reason === "evidence_gate";

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

  const onRetryEvidence = async () => {
    setBusy(true);
    try {
      const result = await retryTaskEvidence(ctx.task_id, checks);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["recovery-needs-attention"] }),
        queryClient.invalidateQueries({ queryKey: ["tasks"] }),
      ]);
      const decision = (result.decision ?? {}) as Record<string, unknown>;
      toast(decision.approved === true ? "증거 확인 통과" : "증거가 아직 조건과 맞지 않습니다", decision.approved === true ? "ok" : "err");
    } catch (e) {
      toast(`증거 재확인 실패: ${(e as Error).message}`, "err");
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
      {isEvidenceHold ? (
        <p className="muted recovery-strategy-hint">증거 불일치로 보류되었습니다. 현장·자세·적재 상태를 확인한 뒤 같은 증거 단계를 다시 판정할 수 있습니다.</p>
      ) : null}
      {!hasKnownCargo && (
        <p className="muted recovery-strategy-hint">적재 상태를 확인해야 복구 단계를 실행할 수 있습니다.</p>
      )}
      <div className="recovery-actions">
        {isEvidenceHold ? (
          <Button type="button" disabled={!allChecks || busy} onClick={() => void onRetryEvidence()}>
            증거 다시 확인
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

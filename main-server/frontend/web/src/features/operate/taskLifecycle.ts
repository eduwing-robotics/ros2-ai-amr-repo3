/** 운영 UI에서 사용하는 작업 생명주기 그룹. 서버의 원본 status 값은 보존한다. */
export type TaskLifecycle =
  | "queued"
  | "running"
  | "recovery"
  | "succeeded"
  | "failed"
  | "cancelled";

const STATUS_BY_LIFECYCLE: Record<TaskLifecycle, ReadonlySet<string>> = {
  queued: new Set(["CREATED", "PENDING", "PLANNED", "QUEUED", "RESERVED", "ASSIGNED"]),
  running: new Set(["RUNNING", "IN_PROGRESS", "CANCEL_REQUESTED"]),
  recovery: new Set(["AWAITING_OPERATOR", "RECOVERY_REQUIRED", "RECOVERY_RUNNING"]),
  succeeded: new Set(["DONE", "COMPLETED"]),
  failed: new Set(["FAILED", "ABORTED", "REJECTED"]),
  cancelled: new Set(["CANCELLED", "CANCELED", "STOPPED"]),
};

export function normalizeTaskStatus(status?: string | null): string {
  return String(status ?? "").trim().toUpperCase();
}

export function taskLifecycleOf(status?: string | null): TaskLifecycle {
  const normalized = normalizeTaskStatus(status);
  for (const lifecycle of Object.keys(STATUS_BY_LIFECYCLE) as TaskLifecycle[]) {
    if (STATUS_BY_LIFECYCLE[lifecycle].has(normalized)) return lifecycle;
  }

  // 알 수 없는 상태를 활성으로 추정하면 종료 작업이 진행 중으로 보일 수 있으므로 실패 종료로 취급한다.
  return "failed";
}

export function isActiveTaskStatus(status?: string | null): boolean {
  const lifecycle = taskLifecycleOf(status);
  return lifecycle === "queued" || lifecycle === "running" || lifecycle === "recovery";
}

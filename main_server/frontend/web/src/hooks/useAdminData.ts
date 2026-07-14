import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../lib/api";
import { describeApiError } from "../lib/apiErrors";
import { postManualDrive } from "../lib/robotCommands";
import { useFeedback } from "../components/FeedbackProvider";
import type {
  CameraSourceUpsert,
  RobotUpsert,
  RobotTask,
  RobotTaskCreate,
  TeleopRequest,
} from "../types";

// --- DB 테이블 브라우저 ---
export interface DbTableInfo {
  table_name: string;
  row_count: number;
  readonly: boolean;
}
export interface DbColumn {
  name: string;
  type?: string;
  pk?: boolean;
}
export interface DbRows {
  table_name: string;
  columns: DbColumn[];
  rows: Record<string, unknown>[];
  readonly: boolean;
}

export const useDbTables = () =>
  useQuery({ queryKey: ["db-tables"], queryFn: () => apiGet<DbTableInfo[]>("/db/tables") });

export const useDbRows = (table: string | undefined, limit: number) =>
  useQuery({
    queryKey: ["db-rows", table, limit],
    queryFn: () => apiGet<DbRows>(`/db/tables/${encodeURIComponent(table!)}/rows?limit=${limit}`),
    enabled: !!table,
  });

export interface RobotTaskStartResult {
  task: RobotTask;
  mission: {
    robot_id: string;
    command_id?: string | null;
    response: Record<string, unknown>;
  };
}

// --- 변경 동작 (성공 시 /status 스냅샷 + 관련 쿼리 무효화) ---
export function useAdminMutations() {
  const qc = useQueryClient();
  const { toast } = useFeedback();
  const refresh = () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ["status"] }),
      qc.invalidateQueries({ queryKey: ["robots"] }),
    ]);
  const onMutError = (label: string) => (e: Error) => toast(`${label} 실패: ${describeApiError(e)}`, "err");
  const onMutOk = (label: string) => () => toast(`${label} 완료`, "ok");

  const saveRobot = useMutation({
    mutationFn: (body: RobotUpsert) => apiSend("/robots", "POST", body),
    onSuccess: refresh,
  });
  const deleteRobot = useMutation({
    mutationFn: (id: string) => apiSend(`/robots/${encodeURIComponent(id)}`, "DELETE"),
    onSuccess: refresh,
  });
  const saveCamera = useMutation({
    mutationFn: (body: CameraSourceUpsert) => apiSend("/camera-sources", "POST", body),
    onSuccess: refresh,
  });
  const deleteCamera = useMutation({
    mutationFn: (id: string) => apiSend(`/camera-sources/${encodeURIComponent(id)}`, "DELETE"),
    onSuccess: refresh,
  });
  const createTask = useMutation({
    mutationFn: (body: RobotTaskCreate) => apiSend<RobotTask>("/tasks", "POST", body),
    onSuccess: refresh,
  });
  const assignTask = useMutation({
    mutationFn: (v: { taskId: number; robotId: string }) =>
      apiSend(`/tasks/${v.taskId}/assign`, "POST", { robot_id: v.robotId }),
    onSuccess: () => {
      void Promise.all([
        refresh(),
        qc.invalidateQueries({ queryKey: ["work-orders"] }),
        qc.invalidateQueries({ queryKey: ["tasks"] }),
      ]);
      onMutOk("작업 배정")();
    },
    onError: onMutError("작업 배정"),
  });
  const autoAssignTasks = useMutation({
    mutationFn: () => apiSend<{ assigned: { task_id: number; robot_id: string }[]; queued_remaining: number; not_ready?: number }>("/tasks/auto-assign", "POST"),
    onSuccess: (result) => {
      void Promise.all([
        refresh(),
        qc.invalidateQueries({ queryKey: ["work-orders"] }),
        qc.invalidateQueries({ queryKey: ["tasks"] }),
      ]);
      const n = result.assigned?.length ?? 0;
      const suffix = result.not_ready ? ` · 준비 안 된 로봇 ${result.not_ready}대 제외` : "";
      toast(n > 0 ? `자동 배정 ${n}건${suffix}` : `배정 가능한 작업 없음${suffix}`, n > 0 ? "ok" : "info");
    },
    onError: onMutError("자동 배정"),
  });
  const autoAssignAndStartTasks = useMutation({
    mutationFn: () => apiSend<{ assigned: { task_id: number; robot_id: string }[]; started?: number[]; start_failed?: { task_id: number; detail: unknown }[]; not_ready?: number }>("/tasks/auto-assign-and-start", "POST"),
    onSuccess: (result) => {
      void Promise.all([
        refresh(),
        qc.invalidateQueries({ queryKey: ["work-orders"] }),
        qc.invalidateQueries({ queryKey: ["tasks"] }),
      ]);
      const assigned = result.assigned?.length ?? 0;
      const started = result.started?.length ?? 0;
      const failed = result.start_failed?.length ?? 0;
      if (assigned === 0) {
        toast(`배정 가능한 작업 없음${result.not_ready ? ` · 준비 안 된 로봇 ${result.not_ready}대` : ""}`, "info");
      } else {
        toast(`자동 배정 ${assigned}건 · 시작 ${started}건${failed ? ` · 시작 실패 ${failed}건` : ""}`, failed ? "err" : "ok");
      }
    },
    onError: onMutError("자동 배정 후 시작"),
  });
  const startRobotTask = useMutation({
    mutationFn: (taskId: number) => apiSend<RobotTaskStartResult>(`/tasks/${taskId}/start-mission`, "POST"),
    onSuccess: () => {
      void Promise.all([
        refresh(),
        qc.invalidateQueries({ queryKey: ["work-orders"] }),
        qc.invalidateQueries({ queryKey: ["tasks"] }),
      ]);
      onMutOk("로봇 작업 시작")();
    },
    onError: onMutError("로봇 작업 시작"),
  });
  const completeTask = useMutation({
    mutationFn: (taskId: number) => apiSend(`/tasks/${taskId}/complete`, "POST"),
    onSuccess: refresh,
  });
  const cancelTask = useMutation({
    mutationFn: (taskId: number) => apiSend(`/tasks/${taskId}/cancel`, "POST"),
    onSuccess: () => { void refresh(); toast("작업 취소됨", "ok"); },
    onError: onMutError("작업 취소"),
  });
  const teleop = useMutation({
    mutationFn: (body: TeleopRequest) => postManualDrive(body),
    onSuccess: refresh,
  });

  return { saveRobot, deleteRobot, saveCamera, deleteCamera, createTask, assignTask, autoAssignTasks, autoAssignAndStartTasks, startRobotTask, completeTask, cancelTask, teleop };
}

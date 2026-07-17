import { apiSend } from "./api";

export interface EstopResult {
  ok: boolean;
  state?: "clear" | "active" | "partial" | "failed" | "unknown";
  partial?: boolean;
  unknown_robots?: string[];
  active_robots?: string[];
  robots: { robot_id: string; ok: boolean; error?: string; response?: unknown }[];
}

export const robotEstopAll = () => apiSend<EstopResult>("/robots/estop-all", "POST");
export const robotClearEstopAll = () => apiSend<EstopResult>("/robots/clear-estop-all", "POST");
export const robotClearEstop = (robotId: string) =>
  apiSend<EstopResult>(`/robots/${encodeURIComponent(robotId)}/clear-estop`, "POST");

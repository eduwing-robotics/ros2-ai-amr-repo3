import { apiSend } from "./api";

export interface EstopResult {
  ok: boolean;
  robots: { robot_id: string; ok: boolean; error?: string; response?: unknown }[];
}

export const robotEstopAll = () => apiSend<EstopResult>("/robot/estop", "POST");
export const robotClearEstopAll = () => apiSend<EstopResult>("/robot/clear_estop", "POST");

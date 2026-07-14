import { useMutation, useQuery } from "@tanstack/react-query";
import { apiGet, apiSend } from "../lib/api";
import type { RobotCommandRecord } from "../types";

export interface CommLog {
  service?: string;
  target?: string;
  method?: string;
  url?: string;
  source?: string;
  started_at?: string;
  finished_at?: string;
  ok?: boolean;
  status?: string;
  detail?: string;
  elapsed_ms?: number;
}

interface CommLogsResponse {
  logs: CommLog[];
  movement_commands: RobotCommandRecord[];
}

export const useCommLogs = (service: string, limit: number) =>
  useQuery({
    queryKey: ["comm-logs", service, limit],
    queryFn: () => {
      const q = `${service ? `?service=${encodeURIComponent(service)}&` : "?"}limit=${limit}`;
      return apiGet<CommLogsResponse>(`/comm/logs${q}`);
    },
    refetchInterval: 5000,
  });

export const useProbes = () => {
  const probeMovement = useMutation({
    mutationFn: () => apiSend<{ movement_health: Record<string, { ok: boolean; error?: string }> }>("/comm/probe/movement", "POST"),
  });
  const probeCamera = useMutation({
    mutationFn: () => apiSend<{ content_type?: string; body?: string }>("/comm/probe/camera", "POST"),
  });
  return { probeMovement, probeCamera };
};

// MJPEG 라이브 스트림 URL. Main 서버가 vision bridge 를 프록시한다(브라우저는 Main origin 만 본다).
export const liveStreamUrl = (
  source: string,
  kind: "overlay" | "frame",
  maxFps = 15,
  view = "full",
): string => {
  const qs = new URLSearchParams({
    source,
    view,
    max_fps: String(maxFps),
  });
  return `/api/v1/vision/${kind}/stream?${qs}`;
};

/** MJPEG 재연결 시 죽은 keep-alive 회피용 캐시버스터. */
export const liveStreamUrlWithBust = (
  source: string,
  kind: "overlay" | "frame",
  maxFps: number,
  view: string,
  bust: number,
): string => `${liveStreamUrl(source, kind, maxFps, view)}&_t=${bust}`;

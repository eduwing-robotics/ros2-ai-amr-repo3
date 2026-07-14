import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../../lib/api";

export interface TimelineEvent {
  event_id?: number;
  event_type: string;
  task_id?: number | null;
  robot_id?: string | null;
  command_id?: string | null;
  message?: string;
  payload?: Record<string, unknown>;
  created_at?: string;
  source?: string;
  layer?: string;
}

export function useTaskLogs(limit = 200) {
  return useQuery({
    queryKey: ["task-logs", limit],
    queryFn: () => apiGet<import("../../types").TaskLogRecord[]>(`/task-logs?limit=${limit}`),
    refetchInterval: 5000,
  });
}

export function useItemChangeLogs(limit = 200) {
  return useQuery({
    queryKey: ["item-change-logs", limit],
    queryFn: () => apiGet<import("../../types").ItemChangeLogRecord[]>(`/item-change-logs?limit=${limit}`),
    refetchInterval: 5000,
  });
}

export function useEvents(limit = 200) {
  return useQuery({
    queryKey: ["events", limit],
    queryFn: () => apiGet<TimelineEvent[]>(`/events?limit=${limit}`),
    refetchInterval: 5000,
  });
}

export function useMovementCommandRecords(limit = 200) {
  return useQuery({
    queryKey: ["movement-commands", limit],
    queryFn: () => apiGet<import("../../types").RobotCommandRecord[]>(`/movement-commands?limit=${limit}`),
    refetchInterval: 5000,
  });
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiSend } from "../lib/api";
import type {
  MapImportResult,
  MapRecord,
  MapUpsert,
  Robot,
  Waypoint,
  WaypointUpsert,
} from "../types";

export function mapImportMessage(r: MapImportResult): string {
  const n = r.count ?? r.maps?.length ?? 0;
  const skipped = r.skipped ?? [];
  const removed = r.removed ?? [];
  let msg = `맵 ${n}개를 불러왔습니다.`;
  if (skipped.length) msg += `\n건너뜀 ${skipped.length}개:\n` + skipped.map((s) => `· ${s.yaml} — ${s.reason}`).join("\n");
  if (removed.length) msg += `\n정리됨(파일 없음) ${removed.length}개:\n` + removed.map((m) => `· ${m.map_id}`).join("\n");
  return msg;
}

export const useMaps = () =>
  useQuery({ queryKey: ["maps"], queryFn: () => apiGet<MapRecord[]>("/maps") });

export const useRobots = () =>
  useQuery({ queryKey: ["robots"], queryFn: () => apiGet<Robot[]>("/robots") });

export const useWaypoints = (mapId: string | undefined) =>
  useQuery({
    queryKey: ["waypoints", mapId],
    queryFn: () => apiGet<Waypoint[]>(`/waypoints?map_id=${encodeURIComponent(mapId!)}`),
    enabled: !!mapId,
  });

export const useAllWaypoints = () =>
  useQuery({ queryKey: ["waypoints", "all"], queryFn: () => apiGet<Waypoint[]>("/waypoints") });

export function useScenarioMutations() {
  const qc = useQueryClient();
  const invalidate = (keys: string[]) =>
    Promise.all(keys.map((k) => qc.invalidateQueries({ queryKey: [k] })));

  const upsertWaypoint = useMutation({
    mutationFn: (body: WaypointUpsert) => apiSend("/waypoints", "POST", body),
    onSuccess: () => invalidate(["waypoints"]),
  });
  const deleteWaypoint = useMutation({
    mutationFn: (id: string) => apiSend(`/waypoints/${encodeURIComponent(id)}`, "DELETE"),
    onSuccess: () => invalidate(["waypoints"]),
  });
  const disableWaypoint = useMutation({
    mutationFn: (id: string) => apiSend(`/waypoints/${encodeURIComponent(id)}/disable`, "POST"),
    onSuccess: () => invalidate(["waypoints"]),
  });
  const forceDeleteWaypoint = useMutation({
    mutationFn: (id: string) => apiSend(`/waypoints/${encodeURIComponent(id)}/force-delete`, "POST"),
    onSuccess: () => invalidate(["waypoints", "inventory", "tasks", "work-orders"]),
  });
  const upsertMap = useMutation({
    mutationFn: (body: MapUpsert) => apiSend("/maps", "POST", body),
    onSuccess: () => invalidate(["maps"]),
  });
  const importMaps = useMutation({
    mutationFn: () => apiSend<MapImportResult>("/maps/import-folder", "POST"),
    onSuccess: () => invalidate(["maps", "waypoints"]),
  });

  return { upsertWaypoint, deleteWaypoint, disableWaypoint, forceDeleteWaypoint, upsertMap, importMaps };
}

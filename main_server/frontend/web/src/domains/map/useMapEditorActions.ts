import { useCallback } from "react";
import type { ToastKind } from "../../components/Toast";
import type { Waypoint, ZoneType } from "../../types";
import { ApiError } from "../../lib/api";
import { isHelperWaypoint, HELPER_WAYPOINT_TYPES, scanWaypointIdFor, yawScanToDock } from "../../lib/dockPairs";
import { degToRad } from "../../lib/coords";
import { helperForScan } from "../../lib/scanMarker";
import { proposeZoneIdentity } from "../../lib/zoneIdentity";
import type { useScenarioMutations } from "../../hooks/useScenarioData";

type Mutations = ReturnType<typeof useScenarioMutations>;

type Feedback = {
  toast: (message: string, kind?: ToastKind) => void;
  confirm: (opts: {
    title: string;
    message: string;
    confirmLabel?: string;
    cancelLabel?: string;
    danger?: boolean;
  }) => Promise<boolean>;
};

interface UseMapEditorActionsOptions {
  selectedMapId: string;
  zones: Waypoint[];
  zoneType: ZoneType;
  zoneName: string;
  zoneYaw: string;
  editZoneId: string;
  setEditZoneId: (id: string) => void;
  setZoneName: (name: string) => void;
  setLinkScanId: (id: string | null) => void;
  setLinkError: (msg: string | null) => void;
  m: Mutations;
  feedback: Feedback;
}

export function useMapEditorActions({
  selectedMapId,
  zones,
  zoneType,
  zoneName,
  zoneYaw,
  editZoneId,
  setEditZoneId,
  setZoneName,
  setLinkScanId,
  setLinkError,
  m,
  feedback,
}: UseMapEditorActionsOptions) {
  const zoneById = useCallback((id: string) => zones.find((z) => z.waypoint_id === id) ?? null, [zones]);

  const notifyError = useCallback((e: unknown) => {
    feedback.toast((e as Error).message, "err");
  }, [feedback]);

  const upsertZone = useCallback((fields: {
    waypoint_id: string; map_id: string; name: string; x: number; y: number; yaw: number;
    waypoint_type: string; scan_waypoint_id?: string | null; aruco_marker_id?: number | null; dock_mode?: string | null;
  }) => m.upsertWaypoint.mutateAsync(fields), [m]);

  const createZoneAt = useCallback(async (world: { x: number; y: number }) => {
    const { waypoint_id, name: defaultName } = proposeZoneIdentity(zoneType, zones);
    const name = zoneName.trim() || defaultName;
    const manualYaw = zoneType !== "approach" && !HELPER_WAYPOINT_TYPES.has(zoneType);
    const yaw = manualYaw ? degToRad(Number(zoneYaw) || 0) : 0;
    await m.upsertWaypoint.mutateAsync({
      waypoint_id,
      map_id: selectedMapId,
      name,
      x: world.x,
      y: world.y,
      yaw,
      waypoint_type: zoneType,
    });
    setZoneName("");
  }, [m, selectedMapId, zoneName, zoneType, zoneYaw, zones, setZoneName]);

  const moveZone = useCallback(async (id: string, world: { x: number; y: number }) => {
    const z = zoneById(id);
    if (!z) return;

    if (z.waypoint_type === "approach") {
      const helper = helperForScan(id, zones);
      const yaw = helper ? yawScanToDock(world, helper) : (z.yaw || 0);
      await upsertZone({
        waypoint_id: z.waypoint_id,
        map_id: z.map_id,
        name: z.name,
        x: world.x,
        y: world.y,
        yaw,
        waypoint_type: z.waypoint_type,
        aruco_marker_id: z.aruco_marker_id,
        dock_mode: z.dock_mode ?? "none",
      });
      return;
    }

    await upsertZone({
      waypoint_id: z.waypoint_id,
      map_id: z.map_id,
      name: z.name,
      x: world.x,
      y: world.y,
      yaw: z.yaw || 0,
      waypoint_type: z.waypoint_type,
      scan_waypoint_id: z.scan_waypoint_id,
      aruco_marker_id: z.aruco_marker_id,
      dock_mode: z.dock_mode ?? "none",
    });

    if (isHelperWaypoint(z) && z.scan_waypoint_id) {
      const scan = zoneById(z.scan_waypoint_id);
      if (scan) {
        const yaw = yawScanToDock({ x: scan.x, y: scan.y }, { x: world.x, y: world.y });
        await upsertZone({
          waypoint_id: scan.waypoint_id,
          map_id: scan.map_id,
          name: scan.name,
          x: scan.x,
          y: scan.y,
          yaw,
          waypoint_type: scan.waypoint_type,
          aruco_marker_id: scan.aruco_marker_id,
          dock_mode: scan.dock_mode ?? "none",
        });
      }
    }
  }, [upsertZone, zoneById, zones]);

  const setZoneYawValue = useCallback(async (id: string, yaw: number) => {
    const z = zoneById(id);
    if (!z || z.waypoint_type === "approach" || isHelperWaypoint(z)) return;
    await m.upsertWaypoint.mutateAsync({
      waypoint_id: z.waypoint_id,
      map_id: z.map_id,
      name: z.name,
      x: z.x,
      y: z.y,
      yaw,
      waypoint_type: z.waypoint_type,
      scan_waypoint_id: z.scan_waypoint_id,
      aruco_marker_id: z.aruco_marker_id,
      dock_mode: z.dock_mode ?? "none",
    });
  }, [m, zoneById]);

  const deleteZoneNow = useCallback(async (id: string) => {
    try {
      await m.deleteWaypoint.mutateAsync(id);
      if (editZoneId === id) setEditZoneId("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        let detail: unknown = e.message;
        try {
          detail = JSON.parse(e.message).detail;
        } catch {
          /* plain */
        }
        if (detail && typeof detail === "object" && (detail as { error?: string }).error === "marker_in_use") {
          const u = detail as { inventory_quantity?: number; tasks_from?: number; tasks_to?: number };
          const ok = await feedback.confirm({
            title: "마커 삭제",
            danger: true,
            confirmLabel: "삭제",
            message: [
              "이 위치는 재고/작업 데이터에서 사용 중입니다.",
              `삭제 시 재고 row(수량 ${u.inventory_quantity ?? 0})는 정리됩니다.`,
              `작업 참조 from ${u.tasks_from ?? 0} / to ${u.tasks_to ?? 0}건은 location을 비워둡니다.`,
              "관리자가 이후 작업 위치를 수동으로 다시 기입할 수 있습니다.",
              "그래도 마커를 삭제할까요?",
            ].join("\n"),
          });
          if (ok) {
            await m.forceDeleteWaypoint.mutateAsync(id);
            if (editZoneId === id) setEditZoneId("");
          }
          return;
        }
      }
      notifyError(e);
    }
  }, [editZoneId, feedback, m, notifyError, setEditZoneId]);

  const linkScanToHelper = useCallback(async (scanId: string, helperId: string) => {
    const scan = zoneById(scanId);
    const helper = zoneById(helperId);
    if (!scan || scan.waypoint_type !== "approach") throw new Error("스캔(approach) 마커만 출발점이 될 수 있습니다.");
    if (!helper || !isHelperWaypoint(helper)) throw new Error("대상은 helper(입고·출고·선반·대기/복귀·충전) 마커여야 합니다.");
    const usedByOtherScans = new Set(
      zones
        .filter((z) => z.waypoint_type === "approach" && z.waypoint_id !== scanId && z.aruco_marker_id != null)
        .map((z) => z.aruco_marker_id as number),
    );
    let marker = scan.aruco_marker_id ?? 0;
    if (!Number.isFinite(marker) || marker < 1 || usedByOtherScans.has(marker)) {
      marker = 1;
      while (usedByOtherScans.has(marker)) marker += 1;
    }
    const yaw = yawScanToDock(scan, helper);

    for (const z of zones) {
      if (z.waypoint_id !== helperId && z.scan_waypoint_id === scanId) {
        await m.upsertWaypoint.mutateAsync({
          waypoint_id: z.waypoint_id,
          map_id: z.map_id,
          name: z.name,
          x: z.x,
          y: z.y,
          yaw: z.yaw,
          waypoint_type: z.waypoint_type,
          scan_waypoint_id: null,
          aruco_marker_id: null,
          dock_mode: "none",
        });
      }
    }

    await m.upsertWaypoint.mutateAsync({
      waypoint_id: scanId,
      map_id: scan.map_id,
      name: scan.name,
      x: scan.x,
      y: scan.y,
      yaw,
      waypoint_type: "approach",
      aruco_marker_id: marker,
      dock_mode: "none",
    });
    await m.upsertWaypoint.mutateAsync({
      waypoint_id: helper.waypoint_id,
      map_id: helper.map_id,
      name: helper.name,
      x: helper.x,
      y: helper.y,
      yaw: helper.yaw,
      waypoint_type: helper.waypoint_type,
      scan_waypoint_id: scanId,
      aruco_marker_id: marker,
      dock_mode: "aruco",
    });
    setLinkScanId(null);
    setLinkError(null);
  }, [m, setLinkError, setLinkScanId, zoneById, zones]);

  const handleLinkMarkerClick = useCallback((linkScanId: string | null, zoneId: string) => {
    setLinkError(null);
    const z = zoneById(zoneId);
    if (!z) return;

    if (!linkScanId) {
      if (z.waypoint_type === "approach" || z.waypoint_type === "transit") {
        setLinkScanId(zoneId);
        return;
      }
      if (isHelperWaypoint(z)) {
        setLinkError("스캔(approach)이 없습니다. 구역 추가 모드에서 스캔을 배치한 뒤, 스캔→helper 순으로 클릭하세요.");
        return;
      }
      setLinkError("경유(transit), 스캔(approach) 또는 helper 마커만 연결할 수 있습니다.");
      return;
    }

    const selected = zoneById(linkScanId);
    if (selected?.waypoint_type === "transit") {
      if (z.waypoint_type !== "approach") {
        setLinkError("경유 지점의 대상은 스캔(approach) 마커여야 합니다.");
        return;
      }
      m.upsertWaypointRoute.mutateAsync({ waypoint_id: selected.waypoint_id, target_location_id: z.waypoint_id })
        .then(() => { setLinkScanId(null); setLinkError(null); })
        .catch((e) => setLinkError((e as Error).message));
      return;
    }

    if (zoneId === linkScanId) {
      setLinkError("같은 마커는 연결할 수 없습니다.");
      return;
    }
    if (z.waypoint_type === "approach") {
      setLinkError("스캔↔스캔 연결은 불가합니다. helper 마커를 클릭하세요.");
      setLinkScanId(zoneId);
      return;
    }
    if (isHelperWaypoint(z)) {
      linkScanToHelper(linkScanId, zoneId).catch((e) => setLinkError((e as Error).message));
      return;
    }
    setLinkError("두 번째 클릭은 helper(입고·출고·선반·대기/복귀·충전) 마커여야 합니다.");
  }, [linkScanToHelper, m.upsertWaypointRoute, setLinkError, setLinkScanId, zoneById]);

  const updateScanAruco = useCallback(async (scanId: string, markerId: number) => {
    const scan = zoneById(scanId);
    if (!scan || scan.waypoint_type !== "approach") return;
    await m.upsertWaypoint.mutateAsync({
      waypoint_id: scan.waypoint_id,
      map_id: scan.map_id,
      name: scan.name,
      x: scan.x,
      y: scan.y,
      yaw: scan.yaw,
      waypoint_type: "approach",
      aruco_marker_id: markerId,
      dock_mode: scan.dock_mode ?? "none",
    });
    const helper = helperForScan(scanId, zones);
    if (helper) {
      await m.upsertWaypoint.mutateAsync({
        waypoint_id: helper.waypoint_id,
        map_id: helper.map_id,
        name: helper.name,
        x: helper.x,
        y: helper.y,
        yaw: helper.yaw,
        waypoint_type: helper.waypoint_type,
        scan_waypoint_id: scanId,
        aruco_marker_id: markerId,
        dock_mode: "aruco",
      });
    }
  }, [m, zoneById, zones]);

  const clearDockPair = useCallback(async (dockId: string) => {
    const dock = zoneById(dockId);
    if (!dock) return;
    const scanId = dock.scan_waypoint_id || scanWaypointIdFor(dockId);
    if (scanId) {
      await m.deleteWaypoint.mutateAsync(scanId).catch(() => { /* may not exist */ });
    }
    await m.upsertWaypoint.mutateAsync({
      waypoint_id: dock.waypoint_id,
      map_id: dock.map_id,
      name: dock.name,
      x: dock.x,
      y: dock.y,
      yaw: dock.yaw,
      waypoint_type: dock.waypoint_type,
      scan_waypoint_id: null,
      dock_mode: "none",
    });
  }, [m, zoneById]);

  const saveZoneRow = useCallback(async (
    z: Waypoint,
    fields: { name: string; x: number; y: number; yaw: number; waypoint_type: string; scan_waypoint_id?: string | null; aruco_marker_id?: number | null; dock_mode?: string | null },
  ) => {
    const payload = { waypoint_id: z.waypoint_id, map_id: z.map_id, ...fields };
    if (z.waypoint_type === "approach") {
      const helper = helperForScan(z.waypoint_id, zones);
      payload.yaw = helper
        ? yawScanToDock({ x: payload.x, y: payload.y }, helper)
        : (z.yaw ?? 0);
    }
    await m.upsertWaypoint.mutateAsync(payload);
    if (isHelperWaypoint(z) && z.scan_waypoint_id && (fields.x !== z.x || fields.y !== z.y)) {
      const scan = zoneById(z.scan_waypoint_id);
      if (scan) {
        await upsertZone({
          waypoint_id: scan.waypoint_id,
          map_id: scan.map_id,
          name: scan.name,
          x: scan.x,
          y: scan.y,
          yaw: yawScanToDock({ x: scan.x, y: scan.y }, { x: fields.x, y: fields.y }),
          waypoint_type: scan.waypoint_type,
          aruco_marker_id: scan.aruco_marker_id,
          dock_mode: scan.dock_mode ?? "none",
        });
      }
    }
    setEditZoneId("");
  }, [m, setEditZoneId, upsertZone, zoneById, zones]);

  return {
    zoneById,
    notifyError,
    createZoneAt,
    moveZone,
    setZoneYawValue,
    deleteZoneNow,
    linkScanToHelper,
    handleLinkMarkerClick,
    updateScanAruco,
    clearDockPair,
    saveZoneRow,
  };
}

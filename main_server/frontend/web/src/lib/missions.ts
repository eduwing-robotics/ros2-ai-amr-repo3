// 미션 호출(명령형). 캐시 대상이 아니라 편집기에서 직접 호출하고 결과를 표시한다.
import { apiGet, apiSend } from "./api";
import { getRobotCommand, postRobotCommand } from "./robotCommands";
import type { InitialPoseRequest, MissionGotoRequest, MissionStatusResponse, MovementCommandTrace, MovementMapState, MovementSyncStatus, RobotLocalization, RobotNavState } from "../types";

const gotoEnvelope = (body: MissionGotoRequest, dryRun: boolean) =>
  postRobotCommand({
    robot_id: body.robot_id,
    kind: "move_to_point",
    command_id: body.command_id,
    dry_run: dryRun,
    params: { map_id: body.map_id, x: body.x, y: body.y, yaw: body.yaw ?? 0 },
  }).then((r) => ({
    robot_id: r.robot_id,
    command_id: r.command_id,
    response: r.response,
  } satisfies MissionStatusResponse));

// 맵 위 임의 좌표 1지점 이동(Nav2 goToPose 테스트).
export const missionGotoPreview = (body: MissionGotoRequest) => gotoEnvelope(body, true);

export const missionGoto = (body: MissionGotoRequest) => gotoEnvelope(body, false);

export const missionStatus = (commandId: string, robotId: string) =>
  getRobotCommand(commandId, robotId).then((r) => ({
    robot_id: r.robot_id,
    command_id: r.command_id,
    response: r.response,
  } satisfies MissionStatusResponse));

export const robotLocalization = (robotId: string) =>
  apiGet<RobotLocalization>(`/robots/${encodeURIComponent(robotId)}/localization`);

export const robotNavState = (robotId: string) =>
  apiGet<RobotNavState>(`/robots/${encodeURIComponent(robotId)}/nav-state`);

export const movementMapState = () =>
  apiGet<MovementMapState>("/movement/map-state");

export const movementCommandTrace = (commandId: string, robotId?: string) =>
  apiGet<MovementCommandTrace>(
    `/movement/commands/${encodeURIComponent(commandId)}/trace${robotId ? `?robot_id=${encodeURIComponent(robotId)}` : ""}`,
  );

export const movementSyncStatus = () => apiGet<MovementSyncStatus>("/movement/sync-status");

export const setRobotInitialPose = (robotId: string, body: InitialPoseRequest) =>
  apiSend<{ ok: boolean; robot_id: string; response: Record<string, unknown> }>(
    `/robots/${encodeURIComponent(robotId)}/initial-pose`,
    "POST",
    body,
  );

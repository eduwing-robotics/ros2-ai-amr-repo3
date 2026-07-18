/**
 * 책임: UI의 이동·초기 자세 요청을 Main command API로 변환한다.
 * 비책임: Nav2 실행, command 완료 판정, 서버 상태 소유.
 */
import { apiGet, apiSend } from "./api";
import { postRobotCommand } from "./robotCommands";
import type { InitialPoseRequest, MoveToPointRequest, MovementCommandTrace, MovementMapState, MovementSyncStatus, RobotLocalization, RobotNavState } from "../types";

const sendMoveToPoint = (body: MoveToPointRequest, dryRun: boolean) =>
  postRobotCommand({
    robot_id: body.robot_id,
    kind: "move_to_point",
    command_id: body.command_id,
    dry_run: dryRun,
    params: { map_id: body.map_id, x: body.x, y: body.y, yaw: body.yaw ?? 0 },
  });

/** 반환은 Main의 이동 명령 접수 결과이며 Nav2 도착을 의미하지 않는다. */
export const moveToPoint = (body: MoveToPointRequest) => sendMoveToPoint(body, false);

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

/** @param body `map` frame 기준 자세(m·rad); 반환은 Movement 접수 결과다. */
export const setRobotInitialPose = (robotId: string, body: InitialPoseRequest) =>
  apiSend<{ ok: boolean; robot_id: string; response: Record<string, unknown> }>(
    `/robots/${encodeURIComponent(robotId)}/initial-pose`,
    "POST",
    body,
  );

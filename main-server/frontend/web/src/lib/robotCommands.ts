// Robot command envelope (PHASE_12-B) — 이동·수동조작·estop 단일 API.
import { apiGet, apiSend } from "./api";
import type { JsonObject, TeleopRequest, TeleopResponse } from "../types";

export type RobotCommandKind = "move_to_point" | "dock_transfer" | "aruco_align" | "manual_drive" | "estop";

export const ROBOT_COMMAND_KINDS: RobotCommandKind[] = [
  "move_to_point",
  "dock_transfer",
  "aruco_align",
  "manual_drive",
  "estop",
];

export const ALIGN_FINALS = ["hold", "return_approach"] as const;
export type AlignFinal = (typeof ALIGN_FINALS)[number];

export const DOCK_ACTIONS = ["load", "unload"] as const;
export type DockAction = (typeof DOCK_ACTIONS)[number];

export const MANUAL_COMMANDS = ["forward", "backward", "left", "right", "stop"] as const;
export type ManualCommand = (typeof MANUAL_COMMANDS)[number];

export const ESTOP_OPS = ["stop", "clear"] as const;
export type EstopOp = (typeof ESTOP_OPS)[number];

export const DEFAULT_ALIGN_TOLERANCE_XY = 0.02;
export const DEFAULT_ALIGN_TOLERANCE_YAW = 2;

/** kind별 명령 입력 — 운영 미션과 관리 기능이 공유한다. */
export interface RobotCommandFormValues {
  mapId: string;
  x: string;
  y: string;
  yaw: string;
  arucoId: string;
  action: string;
  level: string;
  liftHeightMm: string;
  liftTimeoutSec: string;
  homeOnUnload: boolean;
  final: AlignFinal;
  xy: string;
  yawDeg: string;
  manualCommand: string;
  hold: boolean;
  estopOp: string;
}

export const defaultRobotCommandFormValues = (): RobotCommandFormValues => ({
  mapId: "robot2_map",
  x: "0",
  y: "0",
  yaw: "0",
  arucoId: "1",
  action: "load",
  level: "1",
  liftHeightMm: "",
  liftTimeoutSec: "",
  homeOnUnload: false,
  final: "hold",
  xy: String(DEFAULT_ALIGN_TOLERANCE_XY),
  yawDeg: String(DEFAULT_ALIGN_TOLERANCE_YAW),
  manualCommand: "left",
  hold: false,
  estopOp: "stop",
});

export function buildRobotCommandParams(kind: RobotCommandKind, v: RobotCommandFormValues): JsonObject {
  if (kind === "move_to_point") {
    return { map_id: v.mapId, x: Number(v.x), y: Number(v.y), yaw: Number(v.yaw) || 0 };
  }
  if (kind === "dock_transfer") {
    const params: JsonObject = {
      aruco_marker_id: Number(v.arucoId),
      action: v.action,
      level: Number(v.level) || 1,
    };
    if (v.liftHeightMm.trim()) params.lift_height_mm = Number(v.liftHeightMm);
    if (v.liftTimeoutSec.trim()) params.lift_timeout_sec = Number(v.liftTimeoutSec);
    if (v.homeOnUnload) params.home_on_unload = true;
    return params;
  }
  if (kind === "aruco_align") {
    return {
      aruco_marker_id: Number(v.arucoId),
      final: v.final,
      tolerance: {
        xy_m: Number(v.xy) || DEFAULT_ALIGN_TOLERANCE_XY,
        yaw_deg: Number(v.yawDeg) || DEFAULT_ALIGN_TOLERANCE_YAW,
      },
    };
  }
  if (kind === "manual_drive") return { command: v.manualCommand, hold: v.hold };
  return { op: v.estopOp };
}

export function buildRobotCommandRequest(
  robotId: string,
  kind: RobotCommandKind,
  dryRun: boolean,
  form: RobotCommandFormValues,
): RobotCommandRequest {
  return {
    robot_id: robotId,
    kind,
    dry_run: dryRun,
    params: buildRobotCommandParams(kind, form),
  };
}

export interface RobotCommandRequest {
  robot_id: string;
  kind: RobotCommandKind;
  command_id?: string | null;
  task_id?: number | null;
  dry_run?: boolean;
  params?: JsonObject;
  callback_url?: string | null;
}

export interface RobotCommandResponse {
  command_id: string;
  robot_id: string;
  kind: string;
  dry_run?: boolean;
  accepted?: boolean;
  response: JsonObject;
}

export const ROBOT_COMMAND_GATE_KINDS: RobotCommandKind[] = ["dock_transfer", "aruco_align"];

export const robotCommandGateHint =
  "선행 move_to_point가 ARRIVED 상태여야 실행됩니다. gate 없으면 Movement가 409로 거절합니다.";

export const postRobotCommand = (body: RobotCommandRequest) =>
  apiSend<RobotCommandResponse>("/robot-commands", "POST", body);

export const getRobotCommand = (commandId: string, robotId: string) =>
  apiGet<RobotCommandResponse>(
    `/robot-commands/${encodeURIComponent(commandId)}?robot_id=${encodeURIComponent(robotId)}`,
  );

const teleopFromEnvelope = (r: RobotCommandResponse, fallbackCommand: string): TeleopResponse => {
  const inner = r.response;
  return {
    accepted: r.accepted ?? Boolean(inner.accepted ?? true),
    command_id: r.command_id,
    robot_id: r.robot_id,
    command: String(inner.command ?? fallbackCommand),
    movement_mode: String(inner.movement_mode ?? ""),
  };
};

/** 수동 조작(teleop) — POST /robot-commands kind=manual_drive */
export const postManualDrive = (body: TeleopRequest) =>
  postRobotCommand({
    robot_id: body.robot_id,
    kind: "manual_drive",
    params: { command: body.command, hold: body.hold ?? false },
  }).then((r) => teleopFromEnvelope(r, body.command));

/** 단일 로봇 비상 정지/해제 — POST /robot-commands kind=estop */
export const postRobotEstop = (robotId: string, op: "stop" | "clear") =>
  postRobotCommand({
    robot_id: robotId,
    kind: "estop",
    params: { op },
  });

export const robotEstop = (robotId: string) => postRobotEstop(robotId, "stop");
export const robotClearEstop = (robotId: string) => postRobotEstop(robotId, "clear");

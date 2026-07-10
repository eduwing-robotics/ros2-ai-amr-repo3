import type { CameraSource } from "../types";

/** robot_id 일치 카메라 목록(현장 1:1, 다중 시 방어용). */
export function camerasForRobot(robotId: string, cameras: CameraSource[]): CameraSource[] {
  return cameras.filter((c) => c.robot_id === robotId);
}

/** robot_id 없는 전역 카메라(global_cam_* 등). */
export function globalCameras(cameras: CameraSource[]): CameraSource[] {
  return cameras.filter((c) => !c.robot_id);
}

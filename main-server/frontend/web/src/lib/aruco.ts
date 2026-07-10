import { apiGet } from "./api";

export interface ArucoDetection {
  marker_id: number;
  center_error_norm?: number | null;
  marker_width_px?: number | null;
  estimated_distance_m?: number | null;
}

export interface ArucoLatestResponse {
  robot_id: string;
  marker_id: number;
  detections: ArucoDetection[];
  source?: string;
}

export const arucoLatest = (robotId: string, markerId: number) =>
  apiGet<ArucoLatestResponse>(
    `/aruco/latest?robot_id=${encodeURIComponent(robotId)}&marker_id=${markerId}`,
  );

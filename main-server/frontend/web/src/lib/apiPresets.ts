/** API 콘솔 예시 프리셋 (PHASE_49-C). */

export interface ApiPreset {
  id: string;
  label: string;
  description: string;
  method: "POST";
  path: string;
  body: Record<string, unknown>;
  pathParams?: Record<string, string>;
  queryParams?: Record<string, string>;
  dangerous?: boolean;
}

export const API_PRESETS: ApiPreset[] = [
  {
    id: "robot-command-goto",
    label: "robot-commands · 좌표 이동",
    description: "맵 좌표 1점 Nav2 goto.",
    method: "POST",
    path: "/api/v1/robot-commands",
    dangerous: true,
    body: {
      robot_id: "tb3_1",
      kind: "move_to_point",
      dry_run: false,
      params: { map_id: "robot2_map", x: 1.0, y: 0.5, yaw: 0.0 },
    },
  },
  {
    id: "teleop-hold",
    label: "teleop · 좌회전 hold",
    description: "레거시 teleop API (envelope 대신 직접).",
    method: "POST",
    path: "/api/v1/teleop",
    dangerous: true,
    body: { robot_id: "tb3_1", command: "left", hold: true, source: "api_console" },
  },
  {
    id: "initial-pose",
    label: "initial-pose · 맵 원점",
    description: "로봇 초기 pose 설정.",
    method: "POST",
    path: "/api/v1/robots/{robot_id}/initial-pose",
    pathParams: { robot_id: "tb3_1" },
    dangerous: true,
    body: { map_id: "robot2_map", x: 0, y: 0, yaw: 0, source: "api_console" },
  },
  {
    id: "work-order-inbound",
    label: "work-orders · 입고 예약",
    description: "입고 work order 생성(auto_start=false).",
    method: "POST",
    path: "/api/v1/work-orders",
    body: {
      operation: "inbound",
      item_code: "ITEM001",
      quantity: 1,
      auto_start: false,
      priority: 0,
      created_by: "api_console",
    },
  },
  {
    id: "inventory-upsert",
    label: "inventory · 슬롯 수량",
    description: "슬롯별 재고 수량 upsert.",
    method: "POST",
    path: "/api/v1/inventory",
    body: { slot_id: "slot_a1", item_code: "ITEM001", quantity: 1 },
  },
  {
    id: "storage-slot",
    label: "storage-slots · 슬롯 등록",
    description: "waypoint 연결 보관 슬롯.",
    method: "POST",
    path: "/api/v1/storage-slots",
    body: {
      slot_id: "slot_a1",
      waypoint_id: "wp_inbound_1",
      label: "A-1",
      capacity: 1,
      sort_order: 0,
      approach_group: "",
      enabled: true,
    },
  },
  {
    id: "waypoint-upsert",
    label: "waypoints · 구역 마커",
    description: "맵 waypoint 생성/수정.",
    method: "POST",
    path: "/api/v1/waypoints",
    body: {
      waypoint_id: "wp_test_1",
      map_id: "robot2_map",
      name: "테스트",
      x: 1.0,
      y: 0.5,
      yaw: 0,
      waypoint_type: "storage",
      dock_mode: "none",
    },
  },
  {
    id: "robot-commands-dock-load",
    label: "robot-commands · dock_transfer load dry_run",
    description: "적재 dock_transfer 검증 — level·lift override 예시.",
    method: "POST",
    path: "/api/v1/robot-commands",
    dangerous: true,
    body: {
      robot_id: "tb3_2",
      kind: "dock_transfer",
      dry_run: true,
      params: {
        aruco_marker_id: 0,
        action: "load",
        level: 2,
        lift_height_mm: 50,
        lift_timeout_sec: 30,
      },
    },
  },
  {
    id: "robot-commands-dock-unload",
    label: "robot-commands · dock_transfer unload dry_run",
    description: "하역 dock_transfer 검증 — home_on_unload 예시.",
    method: "POST",
    path: "/api/v1/robot-commands",
    dangerous: true,
    body: {
      robot_id: "tb3_2",
      kind: "dock_transfer",
      dry_run: true,
      params: {
        aruco_marker_id: 0,
        action: "unload",
        level: 1,
        home_on_unload: true,
      },
    },
  },
  {
    id: "robot-commands-aruco",
    label: "robot-commands · aruco_align dry_run",
    description: "통합 envelope aruco_align 검증.",
    method: "POST",
    path: "/api/v1/robot-commands",
    dangerous: true,
    body: {
      robot_id: "tb3_1",
      kind: "aruco_align",
      dry_run: true,
      params: {
        aruco_marker_id: 1,
        final: "hold",
        tolerance: { xy_m: 0.02, yaw_deg: 2 },
      },
    },
  },
];

export function presetsFor(method: string, path: string): ApiPreset[] {
  const m = method.toUpperCase();
  return API_PRESETS.filter((p) => p.method === m && p.path === path);
}

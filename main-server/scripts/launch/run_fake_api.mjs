#!/usr/bin/env node
/**
 * Fake API server — 실제 백엔드 없이 프론트 UI 확인용.
 * Node.js 내장 http 모듈만 사용 (외부 패키지 불필요).
 *
 * 사용법:
 *   node scripts/launch/run_fake_api.mjs          ← 백엔드(:8088) 대신 실행
 *   cd frontend/web && npm run dev     ← Vite가 /api → :8088 로 프록시
 *
 * 중지: Ctrl+C
 */

import http from "http";
import { URL } from "url";

const PORT = Number(process.env.LMS_API_PORT || 8088);

// ============================================================
// 유틸
// ============================================================

function ts() {
  return new Date().toISOString().replace("T", " ").slice(0, 19);
}

// 1×1 투명 PNG (맵 이미지 placeholder)
const TRANSPARENT_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

function json(res, status, data) {
  const body = JSON.stringify(data);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,PATCH,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Content-Length": Buffer.byteLength(body),
  });
  res.end(body);
}

const ok      = (res, data) => json(res, 200, data);
const created = (res, data) => json(res, 201, data);
const msg     = (res, m)    => ok(res, { ok: true, message: m });
const notFound = (res, p)   => json(res, 404, { detail: `Mock: 경로 없음 [${p}]` });

// ============================================================
// Mock 데이터
// ============================================================

const ROBOTS = [
  { robot_id: "tb3_1", display_name: "로봇 1호", status: "IDLE",    battery: 92, current_task_id: null, last_command_id: null,        last_seen_at: ts() },
  { robot_id: "tb3_2", display_name: "로봇 2호", status: "RUNNING", battery: 78, current_task_id: 12,   last_command_id: "cmd-abc123", last_seen_at: ts() },
];

const CAMERA_SOURCES = [
  { source_id: "cam_1", label: "카메라 1", robot_id: "tb3_1", status: "active",        stream_url: null },
  { source_id: "cam_2", label: "카메라 2", robot_id: "tb3_2", status: "not_connected", stream_url: null },
  { source_id: "global_cam_01", label: "Global Camera 01", robot_id: null, status: "not_connected", stream_url: null },
];

const MOVEMENT_HEALTH = {
  tb3_1: { ok: true,  dry_run: false, mode: "real", service: "movement", robot_name: "tb3_1", base_url: "http://tb3_1:8080", error: null },
  tb3_2: { ok: true,  dry_run: false, mode: "real", service: "movement", robot_name: "tb3_2", base_url: "http://tb3_2:8080", error: null },
};

// /events (TimelineEvent[] — event_id + payload 필수)
const EVENTS = [
  { event_id: 8, event_type: "mission_done",       task_id: 12, robot_id: "tb3_2", command_id: "cmd-abc123", message: "task #12 입고 완료 — BOX_A ×2",        payload: {}, created_at: "2026-06-23 10:34:52" },
  { event_id: 7, event_type: "pose_stale",          task_id: null, robot_id: "tb3_1", command_id: null,         message: "tb3_1 위치 신호 5초 초과 — 재수신 대기", payload: {}, created_at: "2026-06-23 10:32:10" },
  { event_id: 6, event_type: "task_started",        task_id: 12, robot_id: "tb3_2", command_id: null,         message: "task #12 시작 — 슬롯 A2 배정, tb3_2",  payload: {}, created_at: "2026-06-23 10:31:05" },
  { event_id: 5, event_type: "work_order_created",  task_id: null, robot_id: null,    command_id: null,         message: "work_order #8 생성 (입고 BOX_A ×2)",   payload: {}, created_at: "2026-06-23 10:30:48" },
  { event_id: 4, event_type: "mission_failed",      task_id: 11, robot_id: "tb3_1", command_id: "cmd-xyz789", message: "tb3_1 경로 차단 — 재시도 대기 중",     payload: {}, created_at: "2026-06-23 10:28:33" },
  { event_id: 3, event_type: "mission_done",        task_id: 11, robot_id: "tb3_1", command_id: "cmd-xyz789", message: "task #11 출고 완료 — PAL_B ×1",        payload: {}, created_at: "2026-06-23 10:25:14" },
  { event_id: 2, event_type: "robot_idle",          task_id: null, robot_id: "tb3_1", command_id: null,         message: "tb3_1 대기 상태 전환",                  payload: {}, created_at: "2026-06-23 10:24:00" },
  { event_id: 1, event_type: "task_started",        task_id: 11, robot_id: "tb3_1", command_id: null,         message: "task #11 시작 — 슬롯 B1 배정, tb3_1",  payload: {}, created_at: "2026-06-23 10:20:30" },
];

// /movement-commands (MovementCommand[])
const MOVEMENT_COMMANDS = [
  { command_id: "cmd-abc123", robot_id: "tb3_2", command_type: "mission", command: "mission", status: "RUNNING", request_payload: {}, response_payload: {}, created_at: "2026-06-23 10:31:05" },
  { command_id: "cmd-xyz789", robot_id: "tb3_1", command_type: "goto",    command: "goto",    status: "DONE",    request_payload: {}, response_payload: {}, created_at: "2026-06-23 10:20:30" },
];

const TASKS = [
  { task_id: 12, task_type: "inbound",  preset_name: "입고 루틴 A", status: "RUNNING", priority: 1, assigned_robot_id: "tb3_2", from_location: "입고장",  to_location: "보관 A2", created_by: "operator", created_at: "2026-06-23 10:31:00", updated_at: ts() },
  { task_id: 11, task_type: "outbound", preset_name: "출고 루틴 B", status: "DONE",    priority: 1, assigned_robot_id: "tb3_1", from_location: "보관 B1", to_location: "출고장",  created_by: "operator", created_at: "2026-06-23 10:20:00", updated_at: "2026-06-23 10:25:14" },
  { task_id: 13, task_type: "inbound",  preset_name: "입고 루틴 A", status: "QUEUED",  priority: 1, assigned_robot_id: null,    from_location: null,      to_location: null,      created_by: "operator", created_at: "2026-06-23 10:35:00", updated_at: ts() },
];

const ITEMS = [
  { item_code: "BOX_A",  item_name: "표준 박스 A", unit: "ea", created_at: "2026-06-22", updated_at: "2026-06-22" },
  { item_code: "PAL_B",  item_name: "팔레트 B",    unit: "ea", created_at: "2026-06-22", updated_at: "2026-06-22" },
  { item_code: "TRAY_C", item_name: "트레이 C",    unit: "ea", created_at: "2026-06-22", updated_at: "2026-06-22" },
];

const STORAGE_SLOTS = [
  { slot_id: "slot-a1", waypoint_id: "wp-a1", label: "A1", capacity: 3, sort_order: 1, approach_group: "", enabled: true },
  { slot_id: "slot-a2", waypoint_id: "wp-a2", label: "A2", capacity: 3, sort_order: 2, approach_group: "", enabled: true },
  { slot_id: "slot-b1", waypoint_id: "wp-b1", label: "B1", capacity: 2, sort_order: 3, approach_group: "", enabled: true },
  { slot_id: "slot-b2", waypoint_id: "wp-b2", label: "B2", capacity: 2, sort_order: 4, approach_group: "", enabled: true },
];

const INVENTORY = [
  { slot_id: "slot-a1", item_code: "BOX_A",  quantity: 2, item_name: "표준 박스 A", unit: "ea", slot_label: "A1", capacity: 3, updated_at: ts() },
  { slot_id: "slot-a2", item_code: "BOX_A",  quantity: 0, item_name: "표준 박스 A", unit: "ea", slot_label: "A2", capacity: 3, updated_at: ts() },
  { slot_id: "slot-b1", item_code: "PAL_B",  quantity: 1, item_name: "팔레트 B",    unit: "ea", slot_label: "B1", capacity: 2, updated_at: ts() },
  { slot_id: "slot-b2", item_code: "TRAY_C", quantity: 0, item_name: "트레이 C",    unit: "ea", slot_label: "B2", capacity: 2, updated_at: ts() },
];

// image_url → 실제 백엔드와 동일한 경로
const MAPS = [
  {
    map_id: "main-map", name: "Main_map",
    image_url: "/api/v1/map-assets/main-map/image.png",
    resolution: 0.05, origin_x: -5.0, origin_y: -5.0, origin_yaw: 0,
    width: 200, height: 200, frame_id: "map",
    created_at: "2026-06-22 12:00:00", updated_at: "2026-06-22 12:00:00",
  },
];

const WAYPOINTS = [
  { waypoint_id: "wp-inbound",  map_id: "main-map", name: "입고장",  x:  2.3,  y:  1.1,  yaw: 1.57,  waypoint_type: "inbound",  created_at: ts(), updated_at: ts() },
  { waypoint_id: "wp-outbound", map_id: "main-map", name: "출고장",  x: -1.5,  y:  2.0,  yaw: -1.57, waypoint_type: "outbound", created_at: ts(), updated_at: ts() },
  { waypoint_id: "wp-a1",       map_id: "main-map", name: "보관 A1", x:  0.8,  y: -0.5,  yaw: 0,     waypoint_type: "storage",  created_at: ts(), updated_at: ts() },
  { waypoint_id: "wp-a2",       map_id: "main-map", name: "보관 A2", x:  1.2,  y: -0.5,  yaw: 0,     waypoint_type: "storage",  created_at: ts(), updated_at: ts() },
  { waypoint_id: "wp-b1",       map_id: "main-map", name: "보관 B1", x: -0.8,  y: -1.0,  yaw: 3.14,  waypoint_type: "storage",  created_at: ts(), updated_at: ts() },
  { waypoint_id: "wp-home",     map_id: "main-map", name: "대기/홈", x:  0.0,  y:  0.0,  yaw: 0,     waypoint_type: "home",     created_at: ts(), updated_at: ts() },
  { waypoint_id: "wp-charge",   map_id: "main-map", name: "충전",    x: -2.0,  y:  0.5,  yaw: 0,     waypoint_type: "charge",   created_at: ts(), updated_at: ts() },
];

const PRESETS = [
  {
    preset_id: "preset-1", name: "입고 루틴 A", map_id: "main-map", description: "입고장 → 보관 A1 → 홈 복귀",
    steps: [
      { seq: 1, waypoint_id: "wp-inbound", action_type: "pickup",  params: { lift_height: 0.05 } },
      { seq: 2, waypoint_id: "wp-a1",      action_type: "dropoff", params: {} },
      { seq: 3, waypoint_id: "wp-home",    action_type: "move",    params: {} },
    ],
    created_at: ts(), updated_at: ts(),
  },
  {
    preset_id: "preset-2", name: "출고 루틴 B", map_id: "main-map", description: "보관 B1 → 출고장 → 홈 복귀",
    steps: [
      { seq: 1, waypoint_id: "wp-b1",       action_type: "pickup",  params: { lift_height: 0.05 } },
      { seq: 2, waypoint_id: "wp-outbound", action_type: "dropoff", params: {} },
      { seq: 3, waypoint_id: "wp-home",     action_type: "move",    params: {} },
    ],
    created_at: ts(), updated_at: ts(),
  },
];

// WorkOrderTask — order_id 필드 필수
const WORK_ORDERS = [
  {
    order_id: 8, operation: "inbound", item_code: "BOX_A", quantity: 2, status: "RUNNING",
    created_by: "operator", created_at: "2026-06-23 10:30:48", updated_at: ts(),
    tasks: [{ order_id: 8, task_id: 12, slot_id: "slot-a2", quantity: 2, status: "RUNNING", assigned_robot_id: "tb3_2", command_id: "cmd-abc123" }],
    mission_results: [],
  },
  {
    order_id: 7, operation: "outbound", item_code: "PAL_B", quantity: 1, status: "DONE",
    created_by: "operator", created_at: "2026-06-23 10:15:00", updated_at: "2026-06-23 10:25:14",
    tasks: [{ order_id: 7, task_id: 11, slot_id: "slot-b1", quantity: 1, status: "DONE", assigned_robot_id: "tb3_1", command_id: "cmd-xyz789" }],
    mission_results: [],
  },
  {
    order_id: 9, operation: "inbound", item_code: "BOX_A", quantity: 1, status: "QUEUED",
    created_by: "operator", created_at: "2026-06-23 10:35:00", updated_at: ts(),
    tasks: [{ order_id: 9, task_id: 13, slot_id: null, quantity: 1, status: "QUEUED", assigned_robot_id: null, command_id: null }],
    mission_results: [],
  },
];

const ROBOT_POSES = [
  { robot_id: "tb3_1", map_id: "main-map", x:  50.5, y:  60.3, yaw: 0.0,  source: "amcl", age_sec: 1.2, received_at: ts(), reported_at: ts() },
  { robot_id: "tb3_2", map_id: "main-map", x: 110.8, y:  80.2, yaw: 1.57, source: "amcl", age_sec: 0.8, received_at: ts(), reported_at: ts() },
];

function fakePlannedPaths() {
  return ROBOT_POSES.map((pose) => ({
    robot_id: pose.robot_id,
    map_id: pose.map_id,
    label: "Nav2",
    points: [
      { x: pose.x, y: pose.y },
      { x: pose.x + 12, y: pose.y },
      { x: pose.x + 12, y: pose.y + 8 },
      { x: pose.x + 20, y: pose.y + 8 },
    ],
  }));
}

const COMM_LOGS_RESPONSE = {
  logs: [
    { service: "movement", target: "tb3_2", method: "POST", url: "http://tb3_2:8080/missions",  source: "mission", started_at: "2026-06-23 10:31:05", finished_at: "2026-06-23 10:31:05", ok: true,  status: "200", detail: null, elapsed_ms: 45 },
    { service: "movement", target: "tb3_1", method: "GET",  url: "http://tb3_1:8080/health",    source: "probe",   started_at: "2026-06-23 10:30:00", finished_at: "2026-06-23 10:30:00", ok: true,  status: "200", detail: null, elapsed_ms: 12 },
    { service: "camera",   target: null,    method: "GET",  url: "http://cam-host:8088/health", source: "probe",   started_at: "2026-06-23 10:29:50", finished_at: "2026-06-23 10:29:50", ok: false, status: "503", detail: "연결 거부", elapsed_ms: 5001 },
  ],
  movement_commands: MOVEMENT_COMMANDS,
  counts: { logs: 3, movement_commands: 2 },
};

const DB_TABLES = [
  { table_name: "items",             row_count: 3,   readonly: false },
  { table_name: "robots",            row_count: 2,   readonly: false },
  { table_name: "locations",         row_count: 10,  readonly: false },
  { table_name: "inventory",         row_count: 4,   readonly: false },
  { table_name: "tasks",             row_count: 3,   readonly: false },
  { table_name: "commands",          row_count: 12,  readonly: false },
  { table_name: "evidence_events",   row_count: 24,  readonly: true  },
  { table_name: "safety_stops",      row_count: 0,   readonly: true  },
  { table_name: "item_change_logs",  row_count: 8,   readonly: true  },
  { table_name: "task_logs",         row_count: 2,   readonly: true  },
  { table_name: "maps",              row_count: 1,   readonly: false },
  { table_name: "cameras",           row_count: 3,   readonly: false },
];

const STATUS_SNAPSHOT = {
  system: {
    mode: "MANUAL",
    movement_mode: "real",
    camera_mode: "configured",
    camera: { host: "cam-host", api_base_url: "http://cam-host:8088" },
    camera_health: { ok: true, base_url: "http://cam-host:8088", checked_at: ts() },
    vision: { api_base_url: "http://cam-host:8088", stream_base_url: "http://cam-host:8088" },
  },
  movement_health: MOVEMENT_HEALTH,
  robots: ROBOTS,
  camera_sources: CAMERA_SOURCES,
  movement_commands: MOVEMENT_COMMANDS,
  events: EVENTS.slice(0, 6),
  tasks: TASKS,
};

// ============================================================
// 라우터
// ============================================================

function missionResp(body) {
  return { robot_id: body?.robot_id ?? "tb3_1", command_id: `cmd-fake-${Date.now()}`, response: { accepted: true, status: "ok" } };
}

function robotCommandResp(body) {
  const commandId = body?.command_id ?? `cmd-fake-${Date.now()}`;
  return {
    command_id: commandId,
    robot_id: body?.robot_id ?? "tb3_1",
    kind: body?.kind ?? "move_to_point",
    dry_run: Boolean(body?.dry_run),
    accepted: true,
    response: { accepted: true, status: body?.dry_run ? "PREVIEWED" : "ACCEPTED", state: "RUNNING" },
  };
}

function route(method, pathname, qp, body, res) {
  // Health
  if (pathname === "/health") return ok(res, { status: "ok", mode: "fake" });
  if (!pathname.startsWith("/api/v1")) return notFound(res, pathname);
  const p = pathname.slice("/api/v1".length) || "/";

  // ── 시스템 설정 / 상태 ─────────────────────────────────────
  if (method === "GET" && p === "/system/external-config")
    return ok(res, { public_base_url: "http://localhost:8088", movement: { mode: "real" }, camera: { host: "cam-host", api_base_url: "http://cam-host:8088" }, vision: {} });
  if (method === "GET" && p === "/status") return ok(res, STATUS_SNAPSHOT);

  // ── 맵 ────────────────────────────────────────────────────
  if (method === "GET"  && p === "/maps")             return ok(res, MAPS);
  if (method === "POST" && p === "/maps")             return msg(res, "맵 저장됨");
  if (method === "GET"  && p === "/map-assets")       return ok(res, MAPS.map((m) => ({ map_id: m.map_id, name: m.name, yaml: `${m.map_id}.yaml` })));
  if (method === "POST" && p === "/maps/import-folder") return ok(res, { ok: true, count: 0, maps: MAPS, skipped: [], removed: [] });
  // 맵 이미지 (실제 백엔드 경로: /map-assets/{map_id}/image.png)
  if (method === "GET"  && /^\/map-assets\/[^/]+\/image\.png$/.test(p)) {
    res.writeHead(200, { "Content-Type": "image/png", "Content-Length": TRANSPARENT_PNG.length, "Access-Control-Allow-Origin": "*" });
    return res.end(TRANSPARENT_PNG);
  }

  // ── 로봇 pose ──────────────────────────────────────────────
  if (method === "GET" && p === "/robot-poses") return ok(res, ROBOT_POSES);

  // ── Movement ──────────────────────────────────────────────
  if (method === "GET"  && p === "/movement/map-state")
    return ok(res, { ok: true, active_map_id: "main-map", frame_id: "map", resolution: 0.05, source: "main_server" });
  if (method === "GET"  && p === "/movement/sync-status")
    return ok(res, {
      robots: ROBOTS.map((r) => ({ robot_id: r.robot_id, localized: true, pose_state: "live", reason: null, action_required: null })),
      map_state: { active_map_id: "main-map" },
      movement_logs: [],
      planned_paths: fakePlannedPaths(),
    });
  if (method === "GET"  && p === "/movement/health") return ok(res, MOVEMENT_HEALTH);

  if (method === "GET" && p === "/aruco/latest") {
    const robotId = qp.get("robot_id") ?? "tb3_1";
    const markerId = Number(qp.get("marker_id") ?? 101);
    return ok(res, {
      robot_id: robotId,
      marker_id: markerId,
      detections: [{
        marker_id: markerId,
        center_error_norm: 0.085,
        marker_width_px: 74,
        estimated_distance_m: 0.29,
      }],
      source: "fake",
    });
  }

  // movement/commands/{id}/trace
  if (method === "GET" && /^\/movement\/commands\/[^/]+\/trace$/.test(p)) {
    const cid = p.split("/")[3];
    return ok(res, { command_id: cid, robot_id: "tb3_2", state: "RUNNING", command: MOVEMENT_COMMANDS[0], callbacks: [], callback_count: 0, last_callback_at: null, polling: null, polling_error: null, source: "fake" });
  }

  // ── 로봇 ──────────────────────────────────────────────────
  if (method === "GET"  && p === "/robots")                                     return ok(res, ROBOTS);
  if (method === "POST" && p === "/robots")                                     return msg(res, "로봇 저장됨");
  if (method === "DELETE" && /^\/robots\/[^/]+$/.test(p))                      return msg(res, "로봇 삭제됨");
  // 로봇별 진단
  if (method === "GET"  && /^\/robots\/[^/]+\/localization$/.test(p)) {
    const rid = p.split("/")[2];
    return ok(res, { robot_id: rid, robot_name: rid, ok: true, base_url: `http://${rid}:8080`, robot_online: true, command_accepting: true, localized: true, localization_required: false, pose_state: "live", reason: "ok", action_required: null, source: "fake" });
  }
  if (method === "GET"  && /^\/robots\/[^/]+\/nav-state$/.test(p)) {
    const rid = p.split("/")[2];
    return ok(res, { ok: true, robot_id: rid, robot_name: rid, base_url: `http://${rid}:8080`, robot_online: true, command_accepting: true, nav2_ready: true, navigator_status: "idle", mission_status: null, is_emergency: false, localized: true, reason: "ok", action_required: null });
  }
  if (method === "POST" && /^\/robots\/[^/]+\/initial-pose$/.test(p)) {
    const rid = p.split("/")[2];
    return ok(res, { ok: true, robot_id: rid, response: { accepted: true } });
  }

  // ── 카메라 소스 ────────────────────────────────────────────
  if (method === "GET"  && p === "/camera-sources")                            return ok(res, CAMERA_SOURCES);
  if (method === "POST" && p === "/camera-sources")                            return msg(res, "카메라 저장됨");
  if (method === "DELETE" && /^\/camera-sources\/[^/]+$/.test(p))             return msg(res, "카메라 삭제됨");

  // ── 통신 로그 ─────────────────────────────────────────────
  if (method === "GET"  && p === "/comm/logs")                                 return ok(res, COMM_LOGS_RESPONSE);
  if (method === "POST" && p === "/comm/probe/movement")                       return ok(res, { movement_health: MOVEMENT_HEALTH });
  if (method === "POST" && p === "/comm/probe/camera")                         return ok(res, { ok: true, content_type: "application/json", body: "{\"status\":\"fake\"}" });

  // ── 품목 ──────────────────────────────────────────────────
  if (method === "GET"  && p === "/items")                                     return ok(res, ITEMS);
  if (method === "POST" && p === "/items")                                     return msg(res, "품목 저장됨");
  if (method === "DELETE" && /^\/items\/[^/]+$/.test(p))                      return msg(res, "품목 삭제됨");

  // ── 보관 슬롯 ─────────────────────────────────────────────
  if (method === "GET"  && p === "/storage-slots")                             return ok(res, STORAGE_SLOTS);
  if (method === "POST" && p === "/storage-slots")                             return msg(res, "슬롯 저장됨");
  if (method === "DELETE" && /^\/storage-slots\/[^/]+$/.test(p))              return msg(res, "슬롯 삭제됨");

  // ── 재고 ──────────────────────────────────────────────────
  if (method === "GET"  && p === "/inventory")                                 return ok(res, INVENTORY);
  if (method === "POST" && p === "/inventory")                                 return msg(res, "재고 반영됨");

  // ── Work Orders ───────────────────────────────────────────
  if (method === "GET"  && p === "/work-orders")                               return ok(res, WORK_ORDERS);
  if (method === "POST" && p === "/work-orders") {
    const order = {
      order_id: 100 + Math.floor(Math.random() * 900),
      operation: body?.operation ?? "inbound",
      item_code: body?.item_code ?? "BOX_A",
      quantity: body?.quantity ?? 1,
      status: "QUEUED",
      created_by: "operator",
      created_at: ts(), updated_at: ts(),
      tasks: [],
      mission_results: [],
    };
    return created(res, order);
  }
  if (method === "GET"  && /^\/work-orders\/\d+$/.test(p))                    return ok(res, WORK_ORDERS[0]);

  // ── 작업(Tasks) ───────────────────────────────────────────
  if (method === "GET"  && p.startsWith("/tasks") && !p.includes("/")) {
    const lim = parseInt(qp.get("limit") ?? "50");
    return ok(res, TASKS.slice(0, lim));
  }
  if (method === "POST" && p === "/tasks")                                     return created(res, { task_id: 99, ...body, status: "QUEUED", created_at: ts() });
  if (method === "POST" && p === "/tasks/auto-assign")                         return ok(res, { assigned: [], queued_remaining: 1, idle_remaining: 1 });
  if (method === "POST" && /^\/tasks\/\d+\//.test(p))                         return ok(res, { ok: true, message: "처리됨" });

  // ── Teleop (legacy) / Robot commands envelope ─────────────
  if (method === "POST" && p === "/teleop")
    return ok(res, { accepted: true, command_id: `cmd-teleop-${Date.now()}`, robot_id: body?.robot_id ?? "tb3_1", command: body?.command ?? "stop", movement_mode: "fake" });
  if (method === "POST" && p === "/robot-commands")
    return ok(res, robotCommandResp(body));
  if (method === "GET" && /^\/robot-commands\/[^/]+$/.test(p)) {
    const cid = p.split("/")[2];
    const robotId = qp.get("robot_id") ?? "tb3_2";
    return ok(res, robotCommandResp({ robot_id: robotId, command_id: cid, kind: "move_to_point", dry_run: false }));
  }
  if (method === "POST" && p === "/robot/estop")
    return ok(res, { ok: true, robots: ROBOTS.map((r) => ({ robot_id: r.robot_id, ok: true, response: { is_emergency: true } })) });
  if (method === "POST" && p === "/robot/clear_estop")
    return ok(res, { ok: true, robots: ROBOTS.map((r) => ({ robot_id: r.robot_id, ok: true, response: { is_emergency: false } })) });

  // ── 구역(Waypoints) ──────────────────────────────────────
  if (method === "GET"  && p === "/waypoints")                                 return ok(res, WAYPOINTS);
  if (method === "POST" && p === "/waypoints")                                 return msg(res, "구역 저장됨");
  if (method === "DELETE" && /^\/waypoints\/[^/]+$/.test(p))                  return msg(res, "구역 삭제됨");

  // ── 미션 ─────────────────────────────────────────────────
  if (method === "POST" && p === "/missions/goto/preview")                     return ok(res, missionResp(body));   // missionGotoPreview
  if (method === "POST" && p === "/missions/goto")                             return ok(res, missionResp(body));   // missionGoto
  if (method === "GET"  && /^\/missions\/[^/]+$/.test(p)) {
    const cid = p.split("/")[2];
    return ok(res, { robot_id: body?.robot_id ?? "tb3_2", command_id: cid, response: { status: "RUNNING", accepted: true } });
  }

  // ── 기록 ─────────────────────────────────────────────────
  if (method === "GET" && p === "/events") {
    const lim = parseInt(qp.get("limit") ?? "50");
    return ok(res, EVENTS.slice(0, lim));
  }
  if (method === "GET" && p === "/movement-commands") {
    const lim = parseInt(qp.get("limit") ?? "50");
    return ok(res, MOVEMENT_COMMANDS.slice(0, lim));
  }

  // ── DB 테이블 브라우저 ────────────────────────────────────
  if (method === "GET" && p === "/db/tables") return ok(res, DB_TABLES);
  if (method === "GET" && /^\/db\/tables\/[^/]+\/rows$/.test(p)) {
    const tbl = p.split("/")[3];
    const lim = parseInt(qp.get("limit") ?? "100");
    const DATA_MAP = {
      robots: { columns: [{ name: "robot_id" }, { name: "display_name" }, { name: "status" }, { name: "battery" }], rows: ROBOTS },
      camera_sources: { columns: [{ name: "source_id" }, { name: "label" }, { name: "robot_id" }, { name: "status" }], rows: CAMERA_SOURCES },
      items: { columns: [{ name: "item_code" }, { name: "item_name" }, { name: "unit" }], rows: ITEMS },
      storage_slots: { columns: [{ name: "slot_id" }, { name: "label" }, { name: "capacity" }, { name: "sort_order" }], rows: STORAGE_SLOTS },
      inventory: { columns: [{ name: "slot_id" }, { name: "item_code" }, { name: "quantity" }], rows: INVENTORY },
      events: { columns: [{ name: "event_id" }, { name: "event_type" }, { name: "message" }, { name: "created_at" }], rows: EVENTS },
      tasks: { columns: [{ name: "task_id" }, { name: "task_type" }, { name: "status" }, { name: "assigned_robot_id" }], rows: TASKS },
    };
    const d = DATA_MAP[tbl] ?? { columns: [{ name: "id" }], rows: [] };
    return ok(res, { table_name: tbl, columns: d.columns, rows: d.rows.slice(0, lim), readonly: true });
  }

  // ── Vision ───────────────────────────────────────────────
  if (method === "GET" && p === "/vision/streams") {
    const source = qp.get("source") || "global_cam_01";
    const view = qp.get("view") || "full";
    return ok(res, {
      source_id: source,
      view,
      primary_stream_plane: "http_mjpeg_gateway",
      candidate_stream_plane: "webrtc",
      stream_transports: [
        { kind: "mjpeg", configured: true, healthy: true, status: "ready" },
        {
          kind: "webrtc",
          configured: false,
          healthy: false,
          status: "candidate",
          sidecar: { status: "not_configured", offer_url: null, whep_url: null },
        },
      ],
    });
  }
  if (method === "POST" && /^\/vision\/streams\/[^/]+\/webrtc\/offer$/.test(p)) {
    return ok(res, {
      status: "fallback_required",
      reason: "sidecar_not_configured",
      selected_transport: "mjpeg",
      media_only: true,
    });
  }
  if (method === "GET" && /^\/vision\/(overlay|frame)\/stream$/.test(p)) {
    res.writeHead(200, {
      "Content-Type": "multipart/x-mixed-replace; boundary=frame",
      "Access-Control-Allow-Origin": "*",
    });
    return res.end("--frame\r\nContent-Type: image/jpeg\r\n\r\n(fake mjpeg)\r\n");
  }
  if (p.startsWith("/vision")) {
    res.writeHead(200, { "Content-Type": "text/plain", "Access-Control-Allow-Origin": "*" });
    return res.end("(fake vision — dev mode)");
  }

  return notFound(res, p);
}

// ============================================================
// 서버 시작
// ============================================================

const server = http.createServer((req, res) => {
  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,PATCH,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type,Authorization",
    });
    return res.end();
  }

  const url    = new URL(req.url, `http://localhost:${PORT}`);
  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", () => {
    let body = {};
    try { body = JSON.parse(Buffer.concat(chunks).toString() || "{}"); } catch { /* form or empty */ }
    try {
      route(req.method, url.pathname, url.searchParams, body, res);
    } catch (e) {
      console.error("Route error:", e.message, e.stack);
      json(res, 500, { detail: e.message });
    }
  });
});

server.listen(PORT, () => {
  console.log("\n" + "─".repeat(54));
  console.log("  🟢  Fake API  →  http://localhost:" + PORT);
  console.log("─".repeat(54));
  console.log("\n  [1] 이 창은 그대로 두고, 새 터미널에서:\n");
  console.log("       cd frontend/web && npm run dev");
  console.log("\n  [2] 브라우저:  http://localhost:5173");
  console.log("\n  [중지]  Ctrl+C\n");
});

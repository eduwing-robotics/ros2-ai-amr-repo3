import type { Page, Route } from "@playwright/test";

// Single reusable Main API test boundary for browser acceptance tests.

export const robot = { robot_id: "tb3_1", display_name: "AMR 1", status: "IDLE", battery: 80 };
export const item = { item_code: "bolt", item_name: "볼트", active: true };
export const slot = { slot_id: "S01", label: "슬롯 1", waypoint_id: "dock_1", capacity: 10, sort_order: 1, approach_group: "A", enabled: true };
export const inbound = { waypoint_id: "in_1", map_id: "map", name: "입고", x: 1, y: 1, yaw: 0, waypoint_type: "inbound", scan_waypoint_id: "scan_1" };
export const outbound = { ...inbound, waypoint_id: "out_1", name: "출고", waypoint_type: "outbound" };
export const map = { map_id: "map", name: "테스트 맵", width: 1000, height: 800, resolution: 0.05, origin_x: 0, origin_y: 0, image_url: "" };

type State = {
  emergency?: boolean;
  estopUnknown?: boolean;
  movementOk?: boolean;
  workOrders?: unknown[];
  inventory?: unknown[];
  recoveryTasks?: unknown[];
  tasks?: unknown[];
  cameraSources?: unknown[];
  cameraOnline?: boolean;
  events?: unknown[];
  robotBattery?: number | null;
  robots?: Array<typeof robot>;
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

export async function mockMainApi(page: Page, state: State = {}) {
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname.replace("/api/v1", "");
    const responseRobot = { ...robot, battery: state.robotBattery === undefined ? robot.battery : state.robotBattery };
    const responseRobots = state.robots ?? [responseRobot];
    const movementHealth = Object.fromEntries(responseRobots.map((entry) => [
      entry.robot_id,
      { ok: state.movementOk ?? true, is_emergency: Boolean(state.emergency) },
    ]));
    if (path === "/status") return json(route, {
      system: {
        ...(state.cameraOnline ? { camera_health: { ok: true } } : {}),
        ...(state.estopUnknown ? { estop_summary: { state: "unknown", active_robots: [], unknown_robots: [responseRobot.robot_id] } } : {}),
      },
      robots: responseRobots,
      camera_sources: state.cameraSources ?? [],
      tasks: state.tasks ?? [],
      events: state.events ?? [],
      movement_health: movementHealth,
    });
    if (path === "/robots") return json(route, responseRobots);
    if (path === "/items") return json(route, [item]);
    if (path === "/storage-slots") return json(route, [slot]);
    if (path.startsWith("/inventory")) return json(route, state.inventory ?? []);
    if (path.startsWith("/waypoints")) return json(route, [inbound, outbound]);
    if (path.startsWith("/work-orders/preview")) return json(route, { operation: "inbound", item_code: item.item_code, quantity: 1, slots: [{ slot_id: "S01", floor: 1, slot_label: "슬롯 1" }], zone: inbound });
    if (path === "/work-orders" && req.method() === "POST") return json(route, { order_id: 101, operation: "inbound", item_code: item.item_code, quantity: 1, status: "QUEUED", tasks: [] });
    if (/^\/work-orders\/\d+\/stop$/.test(path) && req.method() === "POST") return json(route, {
      order_id: Number(path.split("/")[2]),
      status: "CANCEL_REQUESTED",
      accepted: true,
      command_id: "cmd-stop-1",
      cargo_state: "EMPTY",
      business_completed: false,
    }, 202);
    if (path.startsWith("/work-orders")) return json(route, state.workOrders ?? []);
    if (path === "/robot/estop" || path === "/robot/clear_estop") return json(route, { ok: true, succeeded: ["tb3_1"], failed: [] });
    if (path.includes("/priority") || path.includes("/cancel")) return json(route, { ok: true });
    if (path.startsWith("/maps")) return json(route, [map]);
    if (path.startsWith("/robot-poses")) return json(route, []);
    if (path === "/movement/sync-status") return json(route, {
      robots: responseRobots.map((entry) => ({ robot_id: entry.robot_id, localized: true, pose_state: "fresh" })),
      map_state: { ok: true, active_map_id: map.map_id },
      movement_logs: [],
      planned_paths: [],
    });
    if (path === "/movement/map-state") return json(route, {
      ok: state.movementOk ?? true,
      active_map_id: map.map_id,
    });
    if (/^\/robots\/[^/]+\/localization$/.test(path)) return json(route, {
      robot_id: robot.robot_id,
      ok: state.movementOk ?? true,
      robot_online: state.movementOk ?? true,
      command_accepting: state.movementOk ?? true,
      localized: true,
      pose_state: "fresh",
    });
    if (/^\/robots\/[^/]+\/nav-state$/.test(path)) return json(route, {
      robot_id: robot.robot_id,
      ok: state.movementOk ?? true,
      robot_online: state.movementOk ?? true,
      command_accepting: state.movementOk ?? true,
      localized: true,
    });
    if (path === "/vision/streams") return json(route, {
      stream_transports: [{ kind: "webrtc", configured: false, status: "not_configured" }],
    });
    if (path === "/vision/overlay/latest") return json(route, { staleness_sec: 0 });
    if (path === "/vision/overlay/latest/image") return route.fulfill({ status: 404, body: "" });
    if (path === "/tasks/recovery/awaiting-operator") return json(route, state.recoveryTasks ?? []);
    if (/^\/tasks\/\d+\/recovery\/preview$/.test(path)) return json(route, {
      task_id: 1,
      strategy: "safe_move",
      cargo_state: "LOADED",
      executable: true,
      steps: [{ kind: "move_to_point", label: "safe:HOME_01", params: { x: 0.5, y: 0.4 } }],
      limitations: ["자동 하역 및 기존 작업 재개는 수행하지 않습니다."],
    });
    if (path.startsWith("/comm/logs")) return json(route, { logs: [], movement_commands: [] });
    if (path.startsWith("/events") || path.startsWith("/api-logs") || path.startsWith("/movement-commands") || path.startsWith("/task-logs") || path.startsWith("/item-change-logs")) return json(route, []);
    if (path.startsWith("/cameras") || path.startsWith("/camera-sources")) return json(route, []);
    throw new Error(`Unhandled Main API mock: ${req.method()} ${path}`);
  });
}

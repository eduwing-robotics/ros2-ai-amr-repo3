import { expect, test } from "@playwright/test";
import { mockMainApi } from "../support/mainApi";

const globalCamera = { source_id: "CAM_GLOBAL_1", label: "창고 전역", robot_id: null, status: "ONLINE" };

const runningOrder = {
  order_id: 41,
  operation: "inbound",
  item_code: "bolt",
  quantity: 1,
  status: "RUNNING",
  tasks: [{
    order_id: 41,
    task_id: 9,
    quantity: 1,
    status: "RUNNING",
    assigned_robot_id: "tb3_1",
    progress: {
      phase: "RUNNING",
      current_step_index: 1,
      steps: [
        { step_index: 0, kind: "leave_dock", status: "DONE" },
        { step_index: 1, kind: "move_to_point", transfer_action: "load", status: "RUNNING" },
        { step_index: 2, kind: "dock_transfer", transfer_action: "load", status: "WAITING" },
      ],
    },
  }],
};

test("입출고 우측 문맥을 열어도 맵·전역 카메라·하단 작업 바는 이동하지 않는다", async ({ page }, testInfo) => {
  await mockMainApi(page, {
    cameraOnline: true,
    cameraSources: [globalCamera],
    workOrders: [runningOrder],
    tasks: [{ task_id: 9, task_type: "INBOUND", status: "RUNNING", assigned_robot_id: "tb3_1" }],
  });
  await page.goto("/operate/control");

  const map = page.locator(".operator-map-stage-wrap");
  const camera = page.getByRole("region", { name: "전역 카메라 및 전체 카메라 Grid" });
  const missionDock = page.getByRole("region", { name: "작업 큐, 할당 로봇, 타임라인과 안전 중지" });
  const mapBefore = await map.boundingBox();
  const cameraBefore = await camera.boundingBox();
  const dockBefore = await missionDock.boundingBox();
  expect(mapBefore).not.toBeNull();
  expect(cameraBefore).not.toBeNull();
  expect(dockBefore).not.toBeNull();
  expect(cameraBefore!.x).toBeGreaterThanOrEqual(mapBefore!.x + mapBefore!.width);
  expect(Math.abs(cameraBefore!.y - mapBefore!.y)).toBeLessThanOrEqual(1);
  expect(Math.abs(cameraBefore!.height - mapBefore!.height)).toBeLessThanOrEqual(1);

  await page.getByRole("button", { name: "새 요청 만들기" }).click();
  const drawer = page.getByRole("region", { name: "입출고" });
  const mapAfter = await map.boundingBox();
  const cameraAfter = await camera.boundingBox();
  const dockAfter = await missionDock.boundingBox();
  const drawerBox = await drawer.boundingBox();
  expect(mapAfter).not.toBeNull();
  expect(cameraAfter).not.toBeNull();
  expect(dockAfter).not.toBeNull();
  expect(drawerBox).not.toBeNull();
  expect(Math.abs(mapAfter!.width - mapBefore!.width)).toBeLessThanOrEqual(1);
  expect(Math.abs(cameraAfter!.x - cameraBefore!.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(dockAfter!.y - dockBefore!.y)).toBeLessThanOrEqual(1);
  expect(drawerBox!.x).toBeGreaterThanOrEqual(cameraAfter!.x + cameraAfter!.width);
  await page.screenshot({ path: testInfo.outputPath("operations-spatial-v4.png"), fullPage: true });
});

test("1440x900에서도 맵과 전역 카메라가 나란히 보이고 작업 바가 뷰포트에 유지된다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockMainApi(page, { cameraOnline: true, cameraSources: [globalCamera], workOrders: [runningOrder] });
  await page.goto("/operate/control");

  const mapBox = await page.locator(".operator-map-stage-wrap").boundingBox();
  const cameraBox = await page.getByRole("region", { name: "전역 카메라 및 전체 카메라 Grid" }).boundingBox();
  const dockBox = await page.getByRole("region", { name: "작업 큐, 할당 로봇, 타임라인과 안전 중지" }).boundingBox();
  expect(mapBox).not.toBeNull();
  expect(cameraBox).not.toBeNull();
  expect(dockBox).not.toBeNull();
  expect(cameraBox!.x).toBeGreaterThanOrEqual(mapBox!.x + mapBox!.width);
  expect(mapBox!.width).toBeGreaterThan(400);
  expect(cameraBox!.width).toBeGreaterThan(280);
  expect(dockBox!.y + dockBox!.height).toBeLessThanOrEqual(900);
});

test("좌측 Activity 버튼은 좌측 문맥과 중앙 목적지를 함께 전환한다", async ({ page }) => {
  await mockMainApi(page, { cameraOnline: true, cameraSources: [globalCamera] });
  await page.goto("/operate/control");

  const nav = page.getByRole("navigation", { name: "운영 메뉴" });
  const primary = page.locator("#operator-primary-pane");
  for (const [label, route, workspace, context] of [
    ["작업", "/operate/tasks", "작업 워크스페이스", "작업 문맥"],
    ["재고", "/operate/inventory", "재고 워크스페이스", "재고 문맥"],
    ["이벤트", "/operate/events", "이벤트 워크스페이스", "이벤트 문맥"],
  ] as const) {
    await nav.getByRole("button", { name: label, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(route + "$"));
    await expect(primary).toHaveAttribute("aria-label", context);
    await expect(page.locator("#operator-workspace-main")).toHaveAttribute("aria-label", workspace);
    await expect(page.getByRole("region", { name: "전역 카메라 및 전체 카메라 Grid" })).toBeVisible();
  }
});

test("좌측에는 목적지만, 우측에는 모든 로봇과 로봇별 명령을 둔다", async ({ page }) => {
  await mockMainApi(page, {
    movementOk: true,
    robots: [
      { robot_id: "tb3_1", display_name: "AMR 1", status: "RUNNING", battery: 80 },
      { robot_id: "tb3_2", display_name: "AMR 2", status: "IDLE", battery: 64 },
      { robot_id: "tb3_3", display_name: "AMR 3", status: "CHARGING", battery: 42 },
    ],
  });
  await page.goto("/operate/control");

  const nav = page.getByRole("navigation", { name: "운영 메뉴" });
  await expect(nav.getByRole("button", { name: "입출고", exact: true })).toHaveCount(0);
  await expect(nav.getByRole("button", { name: "조작", exact: true })).toHaveCount(0);
  await expect(page.getByRole("complementary", { name: "전체 로봇 상태와 명령" })).toBeVisible();
  await expect(page.locator(".operator-fleet-card")).toHaveCount(3);
  await expect(page.locator(".operator-fleet-card").getByRole("button", { name: "조작 →" })).toHaveCount(3);
  await expect(page.getByRole("button", { name: "새 요청 만들기" })).toBeVisible();
});

test("하단 작업 큐는 할당 로봇과 실제 Movement 단계 및 안전 중지를 제공한다", async ({ page }) => {
  await mockMainApi(page, { workOrders: [runningOrder] });
  await page.goto("/operate/control");

  const dock = page.getByRole("region", { name: "작업 큐, 할당 로봇, 타임라인과 안전 중지" });
  await expect(dock.getByText("Task #9")).toBeVisible();
  await expect(dock.getByLabel("Task 9 진행도 1/3")).toBeVisible();
  await expect(dock.getByText("적재 이동")).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept());
  const stopRequest = page.waitForRequest((request) => request.url().endsWith("/api/v1/work-orders/41/stop") && request.method() === "POST");
  await dock.getByRole("button", { name: "작업 안전 중지" }).click();
  await stopRequest;
  await expect(page.getByText(/안전 중단 요청 전송 중/)).toBeVisible();
});


test("맵·카메라·작업 큐는 크기 조절되고 Grid와 이벤트 등급을 명시한다", async ({ page }) => {
  await mockMainApi(page, {
    cameraOnline: true,
    cameraSources: [
      globalCamera,
      { source_id: "CAM_ROBOT_1", label: "AMR 1 전방", robot_id: "tb3_1", status: "ONLINE" },
    ],
    workOrders: [runningOrder],
    events: [
      { event_id: 1, created_at: "2026-07-15T10:00:00", event_type: "ESTOP", message: "비상 정지" },
      { event_id: 2, created_at: "2026-07-15T10:01:00", event_type: "POSE_STALE", message: "연결 지연" },
    ],
  });
  await page.goto("/operate/control");

  await expect(page.locator(".operator-live-resizer")).toBeVisible();
  await expect(page.locator(".operator-dock-resizer")).toBeVisible();
  await expect(page.locator(".cam-name-overlay", { hasText: "창고 전역" })).toBeVisible();
  await expect(page.locator(".cam-name-overlay", { hasText: "AMR 1 전방" })).toBeVisible();
  await expect(page.locator(".operator-selected-camera")).toHaveCount(0);

  await page.getByRole("navigation", { name: "운영 메뉴" }).getByRole("button", { name: "이벤트", exact: true }).click();
  await expect(page.locator(".event-severity--err").getByText("위험")).toBeVisible();
  await expect(page.locator(".event-severity--warn").getByText("주의")).toBeVisible();
  await expect(page.locator(".event-row--err")).toHaveCount(1);
  await expect(page.locator(".event-row--warn")).toHaveCount(1);
});


test("Adobe Industrial Signal 토큰과 위험·주의 비색상 단서가 적용된다", async ({ page }) => {
  await mockMainApi(page, {
    events: [
      { event_id: 1, created_at: "2026-07-15T10:00:00", event_type: "ROBOT_ESTOP", message: "비상 정지" },
      { event_id: 2, created_at: "2026-07-15T10:01:00", event_type: "POSE_STALE", message: "위치 수신 지연" },
    ],
  });
  await page.goto("/operate/events");

  const tokens = await page.evaluate(() => {
    const style = getComputedStyle(document.documentElement);
    return {
      blue: style.getPropertyValue("--adobe-blue").trim(),
      cyan: style.getPropertyValue("--adobe-cyan").trim(),
      teal: style.getPropertyValue("--adobe-teal").trim(),
      yellow: style.getPropertyValue("--adobe-yellow").trim(),
      orange: style.getPropertyValue("--adobe-orange").trim(),
    };
  });
  expect(tokens).toEqual({ blue: "#0673b9", cyan: "#27bbd8", teal: "#08a399", yellow: "#f7d000", orange: "#e84314" });
  await expect(page.locator(".event-row--err .event-severity", { hasText: "위험" })).toBeVisible();
  await expect(page.locator(".event-row--warn .event-severity", { hasText: "주의" })).toBeVisible();
  await expect(page.locator(".event-row--err td").first()).toHaveCSS("box-shadow", /rgb/);
});

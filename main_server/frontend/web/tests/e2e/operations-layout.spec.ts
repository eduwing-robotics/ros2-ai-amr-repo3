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

test("입출고 메뉴는 요청·참조 맵 복합 작업면으로 전환하고 카메라·하단 작업 바를 유지한다", async ({ page }, testInfo) => {
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

  await page.getByRole("navigation", { name: "운영 메뉴" }).getByRole("button", { name: "입출고", exact: true }).click();
  const workspace = page.getByRole("region", { name: "입출고 요청과 위치 확인 맵" });
  const referenceMap = page.getByRole("region", { name: "입출고 위치 확인 맵" });
  const cameraAfter = await camera.boundingBox();
  const dockAfter = await missionDock.boundingBox();
  const workspaceBox = await workspace.boundingBox();
  const referenceMapBox = await referenceMap.boundingBox();
  const referenceStageBox = await referenceMap.locator(".map-stage").boundingBox();
  expect(workspaceBox).not.toBeNull();
  expect(referenceMapBox).not.toBeNull();
  expect(referenceStageBox).not.toBeNull();
  expect(cameraAfter).not.toBeNull();
  expect(dockAfter).not.toBeNull();
  expect(referenceMapBox!.x).toBeGreaterThanOrEqual(workspaceBox!.x);
  expect(referenceMapBox!.y).toBeGreaterThan(workspaceBox!.y);
  expect(referenceStageBox!.y).toBeGreaterThanOrEqual(referenceMapBox!.y);
  expect(referenceStageBox!.y + referenceStageBox!.height).toBeLessThanOrEqual(referenceMapBox!.y + referenceMapBox!.height);
  expect(Math.abs(cameraAfter!.x - cameraBefore!.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(dockAfter!.y - dockBefore!.y)).toBeLessThanOrEqual(1);
  await expect(workspace.locator(".zone-marker.work-order-focused")).toHaveCount(1);
  await workspace.getByLabel("품목").selectOption("bolt");
  await expect(workspace.locator(".zone-marker.work-order-focused")).toHaveCount(2);
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
  await expect(nav.getByRole("button", { name: "입출고", exact: true })).toBeVisible();
  await expect(nav.getByRole("button", { name: "조작", exact: true })).toHaveCount(0);
  await expect(page.getByRole("complementary", { name: "전체 로봇 상태와 명령" })).toBeVisible();
  await expect(page.locator(".operator-fleet-card")).toHaveCount(3);
  await expect(page.locator(".operator-fleet-card").getByRole("button", { name: "조작 →" })).toHaveCount(3);
  await expect(page.getByRole("button", { name: "새 요청 만들기" })).toHaveCount(0);
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
      { source_id: "CAM_AISLE_2", label: "2번 통로", robot_id: null, status: "ONLINE" },
      { source_id: "CAM_DOCK_1", label: "입출고장", robot_id: null, status: "ONLINE" },
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
  await expect(page.locator(".camera-video-wall > .cam-tile")).toHaveCount(4);
  await expect(page.locator(".camera-wall-divider--column")).toHaveCount(1);
  await expect(page.locator(".camera-wall-divider--row")).toHaveCount(1);
  await expect(page.locator(".camera-video-wall .cam-tile-head, .camera-video-wall .cam-tile-foot")).toHaveCount(0);

  await page.getByRole("navigation", { name: "운영 메뉴" }).getByRole("button", { name: "이벤트", exact: true }).click();
  await expect(page.locator(".event-severity--err").getByText("위험")).toBeVisible();
  await expect(page.locator(".event-severity--warn").getByText("주의")).toBeVisible();
  await expect(page.locator(".event-row--err")).toHaveCount(1);
  await expect(page.locator(".event-row--warn")).toHaveCount(1);
});


test("Adobe Electric Indigo 토큰과 위험·주의 비색상 단서가 적용된다", async ({ page }) => {
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
      indigo: style.getPropertyValue("--adobe-indigo").trim(),
      violet: style.getPropertyValue("--adobe-violet").trim(),
      cyan: style.getPropertyValue("--adobe-cyan").trim(),
      green: style.getPropertyValue("--adobe-green").trim(),
      orange: style.getPropertyValue("--adobe-orange").trim(),
    };
  });
  expect(tokens).toEqual({ indigo: "#4f46e5", violet: "#7c3aed", cyan: "#06b6d4", green: "#16a34a", orange: "#f97316" });
  await expect(page.locator(".event-row--err .event-severity", { hasText: "위험" })).toBeVisible();
  await expect(page.locator(".event-row--warn .event-severity", { hasText: "주의" })).toBeVisible();
  await expect(page.locator(".event-row--err td").first()).toHaveCSS("box-shadow", /rgb/);
});


test("하단 기본 큐는 진행·예약만 강조하고 종료 작업은 기록 탭으로 분리한다", async ({ page }) => {
  const queuedOrder = { order_id: 42, operation: "outbound", item_code: "nut", quantity: 2, status: "QUEUED", tasks: [] };
  const completedOrder = { ...runningOrder, order_id: 40, status: "COMPLETED", tasks: [{ ...runningOrder.tasks[0], order_id: 40, task_id: 8, status: "COMPLETED", progress: { ...runningOrder.tasks[0].progress, phase: "COMPLETED" } }] };
  await mockMainApi(page, { workOrders: [completedOrder, queuedOrder, runningOrder] });
  await page.goto("/operate/control");

  const dock = page.getByRole("region", { name: "작업 큐, 할당 로봇, 타임라인과 안전 중지" });
  await expect(dock.getByText("작업 #41")).toBeVisible();
  await expect(dock.getByText("작업 #42")).toBeVisible();
  await expect(dock.getByText("작업 #40")).toHaveCount(0);
  await expect(dock.locator(".fleet-mission-row.is-running")).toHaveCount(1);
  await expect(dock.getByText("LIVE")).toBeVisible();

  await dock.getByRole("tab", { name: "작업 기록" }).click();
  await expect(dock.getByText("작업 #40")).toBeVisible();
  await expect(dock.getByText("작업 #41")).toHaveCount(0);
  await expect(dock.locator(".fleet-mission-row.is-history")).toHaveCount(1);
});

test("전체 로봇 선택은 큰 로봇 카메라 문맥을 열고 수동 조작은 중복 선택기를 두지 않는다", async ({ page }) => {
  await mockMainApi(page, {
    cameraSources: [{ source_id: "CAM_ROBOT_1", label: "AMR 1 전방", robot_id: "tb3_1", status: "ONLINE" }],
  });
  await page.goto("/operate/control");

  await page.locator(".operator-fleet-select").click();
  const camera = page.getByRole("region", { name: "AMR 1 카메라" });
  await expect(camera).toBeVisible();
  await expect(camera.locator(".cam-name-overlay", { hasText: "AMR 1 전방" })).toBeVisible();
  await camera.getByRole("button", { name: "로봇 카메라 닫기" }).click();
  await expect(camera).toHaveCount(0);

  await page.getByRole("button", { name: "조작 →" }).click();
  const manual = page.getByRole("region", { name: /수동 조작/ });
  await expect(manual.locator(".teleop-target")).toContainText("AMR 1");
  await expect(manual.locator(".teleop-target select")).toHaveCount(0);
});

test("맵 Goto 목표는 창을 닫아도 이동 중 임시 마커로 유지되고 도착 시 제거된다", async ({ page }) => {
  const state = { movementOk: true, navMissionStatus: "" };
  await mockMainApi(page, state);
  await page.goto("/operate/control");
  await page.getByRole("button", { name: "조작 →" }).click();

  const map = page.locator(".operator-map-stage-wrap .map-stage");
  const box = await map.boundingBox();
  expect(box).not.toBeNull();
  await map.click({ position: { x: Math.floor(box!.width * .55), y: Math.floor(box!.height * .45) } });
  await expect(page.locator("[data-goto-phase='draft']")).toBeVisible();
  await page.locator(".map-goto-minimal").getByRole("button", { name: "이동", exact: true }).click();
  await expect(page.locator("[data-goto-phase='active']")).toBeVisible();

  await page.getByRole("region", { name: "수동 조작 · 맵 이동" }).getByRole("button", { name: "닫기" }).click();
  await expect(page.locator("[data-goto-phase='active']")).toBeVisible();
  state.navMissionStatus = "SUCCEEDED";
  await expect(page.locator("[data-goto-target]")).toHaveCount(0, { timeout: 7000 });
});


test("품목별 재고는 저장 위치를 표시하고 슬롯별 재고는 선택 위치를 맵에서 강조한다", async ({ page }) => {
  await mockMainApi(page, { inventory: [{ slot_id: "S01", item_code: "bolt", item_name: "볼트", quantity: 3, floor: 1 }] });
  await page.goto("/operate/inventory");

  const workspace = page.getByRole("region", { name: "재고 워크스페이스" });
  await expect(workspace.getByRole("columnheader", { name: "저장 위치" })).toBeVisible();
  await expect(workspace.getByRole("row", { name: /볼트.*슬롯 1 · 1층.*3/ })).toBeVisible();
  await workspace.getByPlaceholder("품목 검색").fill("슬롯 1");
  await expect(workspace.getByRole("row", { name: /볼트.*슬롯 1 · 1층.*3/ })).toBeVisible();
  await workspace.getByPlaceholder("품목 검색").fill("");

  await workspace.getByRole("tab", { name: "슬롯별" }).click();
  const referenceMap = page.getByRole("region", { name: "슬롯 위치 확인 맵" });
  await expect(referenceMap).toBeVisible();
  await workspace.getByRole("row", { name: /슬롯 1 1층/ }).click();
  await expect(referenceMap.locator(".zone-marker.work-order-focused")).toHaveCount(1);
  await expect(workspace.getByRole("row", { name: /슬롯 1 1층/ })).toHaveAttribute("aria-selected", "true");

  await workspace.getByRole("tab", { name: "품목별" }).click();
  await expect(referenceMap).toHaveCount(0);
});

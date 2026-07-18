// 기능 책임: 운영·관리 레이아웃과 조작 차단의 브라우저 계약을 검증한다. 비책임: 실제 Main 연동.
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

test("2층 입고 슬롯 선택은 폼 갱신 후에도 맵 강조를 유지한다", async ({ page }) => {
  await mockMainApi(page);
  await page.goto("/operate/control?drawer=inout");
  const workspace = page.getByRole("region", { name: "입출고 요청과 위치 확인 맵" });
  const referenceMap = page.getByRole("region", { name: "입출고 위치 확인 맵" });
  await workspace.getByRole("button", { name: "직접 지정" }).click();
  await workspace.getByLabel("품목").selectOption("bolt");
  await workspace.getByLabel(/^층/).selectOption("2");
  await workspace.getByLabel(/^보관 슬롯/).selectOption("S01");
  await expect(workspace.getByLabel(/^보관 슬롯/)).toHaveValue("S01");
  await expect(referenceMap.locator(".zone-marker.work-order-focused.zone-storage")).toHaveCount(1);
  await page.waitForTimeout(1800);
  await expect(workspace.getByLabel(/^보관 슬롯/)).toHaveValue("S01");
  await expect(referenceMap.locator(".zone-marker.work-order-focused.zone-storage")).toHaveCount(1);
});

test("2층 출고 슬롯 선택은 폼 갱신 후에도 맵 강조를 유지한다", async ({ page }) => {
  await mockMainApi(page, { inventory: [{ slot_id: "S01", item_code: "bolt", item_name: "볼트", quantity: 3, floor: 2 }] });
  await page.goto("/operate/control?drawer=inout");
  const workspace = page.getByRole("region", { name: "입출고 요청과 위치 확인 맵" });
  const referenceMap = page.getByRole("region", { name: "입출고 위치 확인 맵" });
  await workspace.getByRole("button", { name: "출고 재고 반출", exact: true }).click();
  await workspace.getByRole("button", { name: "직접 지정" }).click();
  await workspace.getByLabel("품목").selectOption("bolt");
  await workspace.getByLabel(/^층/).selectOption("2");
  await workspace.getByLabel(/^보관 슬롯/).selectOption("S01");
  await expect(workspace.getByLabel(/^보관 슬롯/)).toHaveValue("S01");
  await expect(referenceMap.locator(".zone-marker.work-order-focused.zone-storage")).toHaveCount(1);
  await page.waitForTimeout(1800);
  await expect(workspace.getByLabel(/^보관 슬롯/)).toHaveValue("S01");
  await expect(referenceMap.locator(".zone-marker.work-order-focused.zone-storage")).toHaveCount(1);
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

  await nav.getByRole("button", { name: "작업", exact: true }).click();
  const unavailableControl = page.locator(".operator-command-tooltip").first();
  await expect(unavailableControl.getByRole("button", { name: "조작 →" })).toBeDisabled();
  await expect(unavailableControl).toHaveAttribute("data-tooltip", "수동 조작은 관제 화면에서 사용할 수 있습니다.");
  await expect(unavailableControl).toHaveAttribute("tabindex", "0");
});

test("작업 워크스페이스는 요약 열을 통합하고 배정 입력을 확장 명령 바로 공개한다", async ({ page }) => {
  const queuedOrder = {
    order_id: 44,
    operation: "inbound",
    item_code: "bolt",
    quantity: 2,
    status: "QUEUED",
    tasks: [{ order_id: 44, task_id: 11, quantity: 2, status: "QUEUED", assigned_robot_id: null, slot_id: "S01" }],
  };
  await mockMainApi(page, { workOrders: [queuedOrder] });
  await page.goto("/operate/tasks");

  const workspace = page.getByRole("region", { name: "작업 워크스페이스" });
  const table = workspace.locator("table");
  await expect(table.getByRole("columnheader")).toHaveCount(6);
  await expect(workspace.getByRole("combobox", { name: "로봇 선택" })).toHaveCount(0);
  await expect(workspace.getByText("볼트")).toBeVisible();
  await expect(workspace.getByText("2개", { exact: true })).toBeVisible();
  const summaryCells = workspace.locator(".work-order-primary");
  await expect(summaryCells).toHaveCount(2);
  await expect(summaryCells.first()).toHaveCSS("flex-direction", "row");
  await expect(workspace.locator(".work-order-context")).toHaveCSS("flex-direction", "row");

  await workspace.getByRole("button", { name: "배정", exact: true }).click();
  const commandBar = workspace.locator(".task-queue-nested");
  await expect(commandBar.getByRole("combobox", { name: "로봇 선택" })).toBeVisible();
  await expect(commandBar.getByRole("button", { name: "배정", exact: true })).toBeVisible();
  const actionWrap = await commandBar.locator(".task-queue-actions").evaluate((element) => getComputedStyle(element).flexWrap);
  expect(actionWrap).toBe("nowrap");
  await expect(commandBar).not.toContainText("입고");
  await expect(commandBar).not.toContainText("2개");
  await expect(commandBar).not.toContainText("tb3_1");
});

test("좌측 작업 기록 행도 완료·진행·취소 상태 배경을 구분한다", async ({ page }) => {
  const completed = { ...runningOrder, order_id: 45, status: "COMPLETED", tasks: [{ ...runningOrder.tasks[0], order_id: 45, task_id: 12, status: "COMPLETED" }] };
  const cancelled = { ...runningOrder, order_id: 46, status: "CANCELLED", tasks: [{ ...runningOrder.tasks[0], order_id: 46, task_id: 13, status: "CANCELLED" }] };
  await mockMainApi(page, { workOrders: [runningOrder, completed, cancelled] });
  await page.goto("/operate/tasks");

  const table = page.getByRole("region", { name: "작업 워크스페이스" }).locator(".clean-table");
  const successRow = table.locator("tbody > tr[data-status-tone=success]");
  const progressRow = table.locator("tbody > tr[data-status-tone=progress]");
  const cancelledRow = table.locator("tbody > tr[data-status-tone=cancelled]");
  await expect(successRow).toHaveCount(1);
  await expect(progressRow).toHaveCount(1);
  await expect(cancelledRow).toHaveCount(1);
  const colors = await Promise.all([successRow, progressRow, cancelledRow].map((row) => row.evaluate((element) => getComputedStyle(element).backgroundColor)));
  expect(new Set(colors).size).toBe(3);
  const sideCancelledStyle = await cancelledRow.evaluate((element) => ({ background: getComputedStyle(element).backgroundColor, shadow: getComputedStyle(element).boxShadow }));

  await page.goto("/operate/control");
  const dock = page.getByRole("region", { name: "작업 큐, 할당 로봇, 타임라인과 안전 중지" });
  await dock.getByRole("tab", { name: "작업 기록" }).click();
  const bottomCancelledRow = dock.locator(".fleet-task-row[data-status-tone=cancelled]");
  await expect(bottomCancelledRow).toHaveCount(1);
  const bottomCancelledStyle = await bottomCancelledRow.evaluate((element) => ({ background: getComputedStyle(element).backgroundColor, shadow: getComputedStyle(element).boxShadow }));
  expect(bottomCancelledStyle).toEqual(sideCancelledStyle);
});

test("하단 작업 큐는 할당 로봇과 실제 Movement 단계 및 안전 중지를 제공한다", async ({ page }) => {
  await mockMainApi(page, { workOrders: [runningOrder] });
  await page.goto("/operate/control");

  const dock = page.getByRole("region", { name: "작업 큐, 할당 로봇, 타임라인과 안전 중지" });
  await expect(dock.getByText("Task #9")).toBeVisible();
  await expect(dock.getByLabel("Task 9 진행도 1/3")).toBeVisible();
  await expect(dock.getByText("적재 이동")).toBeVisible();
  const runningRow = dock.locator(".fleet-task-row").first();
  await expect(runningRow).toHaveCSS("grid-template-areas", /summary.*assignee.*action.*progress/);
  const rowOverflow = await runningRow.evaluate((element) => element.scrollWidth - element.clientWidth);
  expect(rowOverflow).toBeLessThanOrEqual(1);

  page.once("dialog", (dialog) => dialog.accept());
  const stopRequest = page.waitForRequest((request) => request.url().endsWith("/api/v1/work-orders/41/stop") && request.method() === "POST");
  await dock.getByRole("button", { name: "작업 안전 중지" }).click();
  await stopRequest;
  await expect(page.getByText(/안전 중단 요청 전송 중/)).toBeVisible();
});


test("할당됐지만 시작 전인 작업은 실행 중과 구분하고 일반 취소한다", async ({ page }) => {
  const assignedOrder = {
    ...runningOrder,
    order_id: 43,
    status: "ASSIGNED",
    tasks: [{ ...runningOrder.tasks[0], order_id: 43, task_id: 10, status: "ASSIGNED", command_id: null, progress: undefined }],
  };
  await mockMainApi(page, { workOrders: [assignedOrder] });
  await page.goto("/operate/control");

  const dock = page.getByRole("region", { name: "작업 큐, 할당 로봇, 타임라인과 안전 중지" });
  await expect(dock).toContainText("실행 중 0 · 할당 대기 1 · 미할당 0");
  const assignedRow = dock.locator(".fleet-task-row").first();
  await expect(assignedRow).toContainText("Task #10");
  await expect(assignedRow.locator(".fleet-task-progress")).toContainText("실행 전 · 단계 대기");
  await expect(assignedRow).not.toContainText("우선순위");
  const assignedBox = await assignedRow.boundingBox();
  expect(assignedBox).not.toBeNull();
  expect(assignedBox!.height).toBeGreaterThanOrEqual(60);
  await expect(dock.getByRole("button", { name: "작업 안전 중지" })).toHaveCount(0);

  page.once("dialog", (dialog) => dialog.accept());
  const cancelRequest = page.waitForRequest((request) => request.url().endsWith("/api/v1/tasks/10/cancel") && request.method() === "POST");
  await dock.getByRole("button", { name: "대기 작업 취소" }).click();
  await cancelRequest;
  await expect(page.getByText("작업 취소됨")).toBeVisible();
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


test("운영과 관리 탭은 동일한 상태 색상 tone 정책을 사용한다", async ({ page }) => {
  await mockMainApi(page, { workOrders: [runningOrder] });
  await page.goto("/operate/control");

  await expect(page.locator(".pill[title=RUNNING]").first()).toHaveAttribute("data-status-tone", "progress");
  await expect(page.locator(".pill[title=IDLE]").first()).toHaveAttribute("data-status-tone", "waiting");

  await page.goto("/admin/system");
  await expect(page.locator(".pill[title=ok]").first()).toHaveAttribute("data-status-tone", "success");
  await expect(page.locator(".pill[title=online]").first()).toHaveAttribute("data-status-tone", "success");
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
  const cancelledOrder = { ...runningOrder, order_id: 39, operation: "outbound", status: "CANCELLED", tasks: [{ ...runningOrder.tasks[0], order_id: 39, task_id: 7, status: "CANCELLED", progress: { ...runningOrder.tasks[0].progress, phase: "CANCELLED" } }] };
  await mockMainApi(page, { workOrders: [cancelledOrder, completedOrder, queuedOrder, runningOrder] });
  await page.goto("/operate/control");

  const dock = page.getByRole("region", { name: "작업 큐, 할당 로봇, 타임라인과 안전 중지" });
  await expect(dock.getByText("Task #9")).toBeVisible();
  await expect(dock.getByText("작업 #42")).toBeVisible();
  await expect(dock.getByText("Task #8")).toHaveCount(0);
  await expect(dock.locator(".fleet-task-row.is-running")).toHaveCount(1);
  await expect(dock.getByText("LIVE")).toBeVisible();

  await dock.getByRole("tab", { name: "작업 기록" }).click();
  await expect(dock.getByText("Task #8")).toBeVisible();
  await expect(dock.getByLabel("Task 8 진행도 1/3")).toBeVisible();
  await expect(dock.getByText("Task #9")).toHaveCount(0);
  const historyRows = dock.locator(".fleet-task-row.is-history");
  await expect(historyRows).toHaveCount(2);
  const inboundCompleted = historyRows.filter({ hasText: "Task #8" });
  const outboundCancelled = historyRows.filter({ hasText: "Task #7" });
  await expect(inboundCompleted).toHaveAttribute("data-operation", "inbound");
  await expect(inboundCompleted).toHaveAttribute("data-history-status", "COMPLETED");
  await expect(outboundCancelled).toHaveAttribute("data-operation", "outbound");
  await expect(outboundCancelled).toHaveAttribute("data-history-status", "CANCELLED");
  await expect(outboundCancelled.locator(".pill[title=CANCELLED]")).toHaveAttribute("data-status-tone", "cancelled");
  const backgrounds = await Promise.all([inboundCompleted, outboundCancelled].map((row) => row.evaluate((element) => getComputedStyle(element).backgroundColor)));
  expect(backgrounds[0]).not.toBe(backgrounds[1]);
});

test("전체 로봇 선택은 큰 로봇 카메라 문맥을 열고 수동 조작은 중복 선택기를 두지 않는다", async ({ page }) => {
  await mockMainApi(page, {
    cameraSources: [{ source_id: "CAM_ROBOT_1", label: "AMR 1 전방", robot_id: "tb3_1", status: "ONLINE" }],
  });
  await page.goto("/operate/control");

  await page.locator(".operator-fleet-card").click({ position: { x: 12, y: 70 } });
  const camera = page.getByRole("region", { name: "AMR 1 카메라" });
  await expect(camera).toBeVisible();
  await expect(camera.locator(".cam-name-overlay", { hasText: "AMR 1 전방" })).toBeVisible();
  await page.getByRole("button", { name: "조작 →" }).click();
  await expect(camera).toHaveCount(0);
  const manual = page.getByRole("region", { name: /수동 조작/ });
  await expect(manual.locator(".teleop-target")).toContainText("AMR 1");
  await expect(manual.locator(".teleop-target select")).toHaveCount(0);
});

test("맵 Goto 목표는 창을 닫아도 이동 중 임시 마커로 유지되고 도착 시 제거된다", async ({ page }) => {
  const state = { movementOk: true, navigatorStatus: "" };
  await mockMainApi(page, state);
  await page.goto("/operate/control");
  await page.getByRole("button", { name: "조작 →" }).click();
  await page.getByRole("tab", { name: "맵 이동" }).click();

  const map = page.locator(".operator-map-stage-wrap .map-stage");
  const box = await map.boundingBox();
  expect(box).not.toBeNull();
  await map.click({ position: { x: Math.floor(box!.width * .55), y: Math.floor(box!.height * .45) } });
  await expect(page.locator("[data-goto-phase='draft']")).toBeVisible();
  await page.locator(".map-goto-minimal").getByRole("button", { name: "이동", exact: true }).click();
  await expect(page.locator("[data-goto-phase='active']")).toBeVisible();

  await page.getByRole("region", { name: "수동 조작 · 맵 이동" }).getByRole("button", { name: "닫기" }).click();
  await expect(page.locator("[data-goto-phase='active']")).toBeVisible();
  state.navigatorStatus = "SUCCEEDED";
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


const responsiveViewports = [
  { name: "FHD 관제실", width: 1920, height: 1080 },
  { name: "일반 데스크톱", width: 1440, height: 900 },
  { name: "저높이 노트북", width: 1366, height: 768 },
  { name: "최소 데스크톱", width: 1280, height: 720 },
  { name: "소형 모니터", width: 1024, height: 768 },
] as const;

for (const viewport of responsiveViewports) {
  test(viewport.name + " " + viewport.width + "x" + viewport.height + "에서 전역 전환과 핵심 작업면을 생략하지 않는다", async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await mockMainApi(page, { cameraOnline: true, cameraSources: [globalCamera] });
    await page.goto("/operate/control");

    const modeTabs = page.locator("header").getByRole("button").filter({ hasText: /^(운영|관리)$/ });
    await expect(modeTabs).toHaveCount(2);
    await expect(page.getByRole("navigation", { name: "운영 메뉴" }).getByRole("button", { name: "관리 공간" })).toHaveCount(0);
    await expect(page.locator(".operator-map-stage-wrap .map-stage")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);

    await page.getByRole("navigation", { name: "운영 메뉴" }).getByRole("button", { name: "입출고", exact: true }).click();
    const workspace = page.getByRole("region", { name: "입출고 요청과 위치 확인 맵" });
    const referenceMap = page.getByRole("region", { name: "입출고 위치 확인 맵" });
    await expect(workspace).toBeVisible();
    await expect(referenceMap).toBeVisible();
    const mapBox = await referenceMap.locator(".map-stage").boundingBox();
    expect(mapBox).not.toBeNull();
    expect(mapBox!.width).toBeGreaterThan(200);
    expect(mapBox!.height).toBeGreaterThanOrEqual(200);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);

    await page.locator("header").getByRole("button", { name: "관리", exact: true }).click();
    await expect(page.getByRole("navigation", { name: "관리 영역" }).getByRole("button", { name: "운영", exact: true })).toHaveCount(0);
    await expect(page.locator("header").getByRole("button", { name: "운영", exact: true })).toBeVisible();
  });
}


test("운영·관리 전환 전후 헤더 탭과 좌측 패널 치수를 동일하게 유지한다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockMainApi(page);
  await page.goto("/operate/control");

  const headerTabs = page.locator("header .mode-tab");
  const operateTabs = await headerTabs.evaluateAll((tabs) => tabs.map((tab) => {
    const rect = tab.getBoundingClientRect();
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
  }));
  const operateActivity = await page.locator(".operator-activity-rail").boundingBox();
  const operateContext = await page.locator(".operator-primary-pane").boundingBox();
  const operateLeft = await page.locator(".slim-nav").boundingBox();

  await page.locator("header").getByRole("button", { name: "관리", exact: true }).click();
  const adminTabs = await headerTabs.evaluateAll((tabs) => tabs.map((tab) => {
    const rect = tab.getBoundingClientRect();
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
  }));
  const adminActivity = await page.locator(".admin-activity-rail").boundingBox();
  const adminContext = await page.locator(".admin-context-pane").boundingBox();
  const adminLeftWidth = (adminActivity?.width ?? 0) + (adminContext?.width ?? 0);

  expect(operateTabs).toHaveLength(2);
  expect(adminTabs).toHaveLength(2);
  for (let index = 0; index < operateTabs.length; index += 1) {
    expect(Math.abs(operateTabs[index].x - adminTabs[index].x)).toBeLessThanOrEqual(1);
    expect(Math.abs(operateTabs[index].y - adminTabs[index].y)).toBeLessThanOrEqual(1);
    expect(Math.abs(operateTabs[index].width - adminTabs[index].width)).toBeLessThanOrEqual(1);
    expect(Math.abs(operateTabs[index].height - adminTabs[index].height)).toBeLessThanOrEqual(1);
  }
  expect(operateActivity).not.toBeNull();
  expect(operateContext).not.toBeNull();
  expect(operateLeft).not.toBeNull();
  expect(adminActivity).not.toBeNull();
  expect(adminContext).not.toBeNull();
  expect(Math.abs(operateActivity!.width - adminActivity!.width)).toBeLessThanOrEqual(1);
  expect(Math.abs(operateContext!.width - adminContext!.width)).toBeLessThanOrEqual(1);
  expect(Math.abs(operateLeft!.width - adminLeftWidth)).toBeLessThanOrEqual(1);
});


test("관리 기록은 운영 이력 4개 영역과 공통 관리 사이드바를 사용한다", async ({ page }) => {
  await page.goto("/records/events");
  await expect(page.getByRole("button", { name: "운영 이벤트" })).toBeVisible();
  await expect(page.getByRole("button", { name: "작업 이력" })).toBeVisible();
  await expect(page.getByRole("button", { name: "재고 이력" })).toBeVisible();
  await expect(page.getByRole("button", { name: "시스템 상태" })).toBeVisible();
  await expect(page.locator(".admin-context-pane")).toBeVisible();
  const railBox = await page.locator(".admin-activity-rail").boundingBox();
  const contextBox = await page.locator(".admin-context-pane").boundingBox();
  const workbenchBox = await page.locator(".admin-workbench").boundingBox();
  expect(railBox?.width).toBe(68);
  expect(contextBox?.width).toBe(180);
  expect(workbenchBox?.x).toBe(248);
  expect(workbenchBox?.width).toBeGreaterThan(1600);

  await page.getByRole("button", { name: "작업 이력" }).click();
  await expect(page.getByRole("button", { name: "작업 결과" })).toBeVisible();
  await expect(page.getByRole("button", { name: "이동 명령" })).toBeVisible();

  await page.getByRole("button", { name: "시스템 상태" }).click();
  await expect(page.getByRole("combobox", { name: "서비스 필터" })).toBeVisible();
  await expect(page.getByText("통신 기록", { exact: true })).toHaveCount(0);
});


test("Movement OFFLINE이 DB RUNNING보다 우선하고 조작을 차단한다", async ({ page }) => {
  await mockMainApi(page, {
    movementOk: true,
    robots: [{
      robot_id: "tb3_2",
      display_name: "AMR 2",
      status: "RUNNING",
      battery: 64,
      operational_status: "OFFLINE",
      task_status: "RUNNING",
      operational_reason: "movement_or_robot_offline",
      command_enabled: false,
    }],
    tasks: [{ task_id: 57, task_type: "INBOUND", status: "RUNNING", assigned_robot_id: "tb3_2" }],
  });
  await page.goto("/operate/control");

  const fleet = page.locator(".operator-fleet-card").filter({ hasText: "tb3_2" });
  await expect(fleet.locator(".pill[title=OFFLINE]")).toHaveText("오프라인");
  await expect(fleet.getByText("입고 작업 수행 중 연결 끊김")).toBeVisible();
  await expect(fleet.getByText("명령 실행 불가")).toBeVisible();
  await expect(fleet.getByRole("button", { name: "조작 →" })).toBeDisabled();
  await expect(fleet.locator(".pill[title=RUNNING]")).toHaveCount(0);
});


test("실행 가능한 로봇이 없으면 작업 큐 배정 시작을 차단한다", async ({ page }) => {
  await mockMainApi(page, {
    movementOk: false,
    robots: [{
      robot_id: "tb3_2", display_name: "AMR 2", status: "IDLE", battery: 64,
      operational_status: "OFFLINE", task_status: "IDLE", command_enabled: false,
    }],
    workOrders: [{
      order_id: 88, operation: "inbound", item_code: "bolt", quantity: 1, status: "QUEUED",
      tasks: [{ order_id: 88, task_id: 88, quantity: 1, status: "QUEUED", assigned_robot_id: null }],
    }],
  });
  await page.goto("/operate/tasks");
  await expect(page.getByText("실행 가능한 로봇이 없습니다")).toBeVisible();
  await expect(page.getByRole("button", { name: "▶ 배정·시작" })).toBeDisabled();
});


test("카메라 전체 연결이 개별 stale source를 가리지 않는다", async ({ page }) => {
  await mockMainApi(page, {
    cameraOnline: true,
    cameraSources: [
      { source_id: "cam_live", label: "정상 카메라", robot_id: null, status: "online" },
      { source_id: "cam_stale", label: "지연 카메라", robot_id: "tb3_2", status: "stale", last_frame_age_s: 120 },
    ],
  });
  await page.goto("/operate/control");
  await expect(page.locator(".operator-camera-state")).toHaveText("1/2 LIVE · 1 STALE");
  await expect(page.locator(".operator-global-camera").getByText("1/2 LIVE", { exact: true })).toBeVisible();
  await page.locator(".operator-global-camera").getByRole("button", { name: "단일" }).click();
  const cameraSelect = page.locator(".operator-global-camera").getByRole("combobox").first();
  await expect(cameraSelect.locator("option").nth(0)).toHaveText("정상 카메라 (cam_live) · ● 정상");
  await expect(cameraSelect.locator("option").nth(1)).toHaveText("지연 카메라 (cam_stale) · ▲ 지연");

  await page.goto("/admin/devices");
  const liveRow = page.locator("table tr").filter({ hasText: "cam_live" });
  const staleRow = page.locator("table tr").filter({ hasText: "cam_stale" });
  await expect(liveRow.getByText("● 정상")).toBeVisible();
  await expect(liveRow.getByText("스트림 정상")).toBeVisible();
  await expect(staleRow.getByText("▲ 지연")).toBeVisible();
  await expect(staleRow.getByText("2분 전")).toBeVisible();
});

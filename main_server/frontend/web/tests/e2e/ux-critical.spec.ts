import { expect, test } from "@playwright/test";
import { item, mockMainApi, robot, slot } from "../support/mainApi";

test("WEB-01 입고 요청은 중복 제출을 막고 결과를 표시한다", async ({ page }) => {
  await mockMainApi(page);
  await page.goto("/operate/control?drawer=inout");
  await page.getByLabel("품목").selectOption(item.item_code);
  const execute = page.getByRole("button", { name: /요청 실행/ });
  await execute.click({ force: true });
  await expect(page.getByText(/작업 접수됨 · 로봇 배정 대기/).first()).toBeVisible();
  await expect(page.getByText(/5초마다 자동 재시도/).first()).toBeVisible();
});

test("WEB-01 자동 시작 성공은 로봇과 command ID를 표시한다", async ({ page }) => {
  await mockMainApi(page);
  await page.route("**/api/v1/work-orders", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      order_id: 102,
      operation: "inbound",
      item_code: item.item_code,
      quantity: 1,
      status: "RUNNING",
      tasks: [{ task_id: 102, status: "RUNNING", assigned_robot_id: robot.robot_id, command_id: "cmd-102" }],
      mission_results: [{ command_id: "cmd-102", robot_id: robot.robot_id }],
    }),
  }));
  await page.goto("/operate/control?drawer=inout");
  await page.getByLabel("품목").selectOption(item.item_code);
  await page.getByRole("button", { name: /요청 실행/ }).click();
  await expect(page.getByText(/작업 실행 시작됨/).first()).toBeVisible();
  await expect(page.getByText(/cmd cmd-102/).first()).toBeVisible();
  await expect(page.getByText(/robot tb3_1/).first()).toBeVisible();
});

test("WEB-01 자동 시작 실패는 생성 성공과 실행 실패를 구분한다", async ({ page }) => {
  await mockMainApi(page);
  await page.route("**/api/v1/work-orders", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      order_id: 103,
      operation: "inbound",
      item_code: item.item_code,
      quantity: 1,
      status: "ASSIGNED",
      tasks: [{ task_id: 103, status: "ASSIGNED", assigned_robot_id: robot.robot_id }],
      start_failed: [{ task_id: 103, detail: "robot_not_accepting" }],
    }),
  }));
  await page.goto("/operate/control?drawer=inout");
  await page.getByLabel("품목").selectOption(item.item_code);
  await page.getByRole("button", { name: /요청 실행/ }).click();
  await expect(page.getByText(/작업 생성됨 · 자동 시작 실패/).first()).toBeVisible();
  await expect(page.getByText(/task #103: robot_not_accepting/)).toBeVisible();
});

test("WEB-02 재고 부족 오류는 입력과 재고 보기 동작을 유지한다", async ({ page }) => {
  await mockMainApi(page, { inventory: [{ slot_id: slot.slot_id, item_code: item.item_code, quantity: 1, floor: 1 }] });
  await page.route("**/api/v1/work-orders", (route) => route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: { error: "insufficient_inventory" } }) }));
  await page.goto("/operate/control?drawer=inout");
  await page.getByRole("button", { name: "출고 재고 반출", exact: true }).click();
  await page.getByLabel("품목").selectOption(item.item_code);
  await page.getByLabel("수량").fill("1", { force: true });
  await page.getByRole("button", { name: /요청 실행/ }).click({ force: true });
  await expect(page.getByText(/재고가 부족/)).toBeAttached();
  await expect(page.getByRole("link", { name: "재고 보기" })).toBeAttached();
  await expect(page.getByLabel("수량")).toHaveValue("1");
});

test("WEB-03 ESTOP은 운영 명령을 차단하고 해제 확인을 요구한다", async ({ page }) => {
  await mockMainApi(page, { emergency: true });
  await page.goto("/operate/control?drawer=inout");
  await expect(page.getByRole("button", { name: /요청 실행/ })).toBeDisabled();
  // 수동 조작이 밴드→드로어로 이동해 숨은 텍스트가 사라졌으므로, 가시적인 비상 배너로 확인한다.
  await expect(page.getByText(/비상 정지 활성/).first()).toBeVisible();
  await page.getByRole("button", { name: "ESTOP 활성" }).click();
  await expect(page.getByRole("alertdialog")).toBeVisible();
});

test("WEB-04 실행 작업은 중단 요청 중과 Movement 전달 결과를 표시한다", async ({ page }) => {
  await mockMainApi(page, { workOrders: [{ order_id: 7, operation: "inbound", status: "RUNNING", priority: 10, business_completed: false, tasks: [{ task_id: 8, status: "RUNNING", assigned_robot_id: robot.robot_id }] }] });
  await page.route("**/api/v1/work-orders/7/stop", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 300));
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({ order_id: 7, status: "CANCEL_REQUESTED", accepted: true, command_id: "cmd-stop-7", cargo_state: "EMPTY", business_completed: false }),
    });
  });
  await page.goto("/operate/tasks");
  page.once("dialog", async (dialog) => {
    expect(dialog.message()).toContain("안전 중단");
    await dialog.accept();
  });
  await page.getByRole("button", { name: "안전 중단" }).click();
  await expect(page.getByRole("button", { name: "중단 요청 중…" })).toBeDisabled();
  await expect(page.getByText(/중단 요청 전달됨 · cmd cmd-stop-7/)).toBeVisible();
});

test("WEB-04 활성 명령이 유실된 작업은 정지 확인 후 복구 패널을 표시한다", async ({ page }) => {
  await mockMainApi(page, {
    workOrders: [{ order_id: 7, operation: "inbound", status: "RUNNING", business_completed: false, tasks: [{ task_id: 7, status: "RUNNING", assigned_robot_id: robot.robot_id }] }],
    recoveryTasks: [{ task_id: 7, status: "RUNNING", orchestration_phase: "AWAITING_OPERATOR", awaiting_operator: true, assigned_robot_id: robot.robot_id, last_step_kind: "leave_dock" }],
  });
  await page.route("**/api/v1/work-orders/7/stop", (route) => route.fulfill({
    status: 202,
    contentType: "application/json",
    body: JSON.stringify({ order_id: 7, status: "AWAITING_OPERATOR", accepted: true, command_id: null, cargo_state: "UNKNOWN", business_completed: false }),
  }));
  await page.goto("/operate/tasks");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "안전 중단" }).click();
  await expect(page.getByText(/로봇 정지 확인됨 · 작업 복구 패널/)).toBeVisible();
  await expect(page.getByText(/복구 필요.*task #7/)).toBeVisible();
});

test("WEB-04 중단 전송 실패는 원인을 즉시 표시한다", async ({ page }) => {
  await mockMainApi(page, { workOrders: [{ order_id: 7, operation: "inbound", status: "RUNNING", business_completed: false, tasks: [{ task_id: 8, status: "RUNNING", assigned_robot_id: robot.robot_id }] }] });
  await page.route("**/api/v1/work-orders/7/stop", (route) => route.fulfill({
    status: 502,
    contentType: "application/json",
    body: JSON.stringify({ detail: "Movement timeout" }),
  }));
  await page.goto("/operate/tasks");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "안전 중단" }).click();
  await expect(page.getByText(/안전 중단 실패: Movement timeout/)).toBeVisible();
});

test("WEB-05 관리자 품목은 저장 요청 후 목록에 반영된다", async ({ page }) => {
  await mockMainApi(page);
  await page.goto("/admin/warehouse");
  await expect(page.getByText(item.item_name).first()).toBeVisible();
  await page.getByRole("button", { name: "슬롯", exact: true }).click();
  await expect(page.getByText(slot.label).first()).toBeVisible();
});

test("WEB-06 지연된 입고 요청은 중복 제출을 차단한다", async ({ page }) => {
  await mockMainApi(page);
  let createCount = 0;
  await page.route("**/api/v1/work-orders", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    createCount += 1;
    await new Promise((resolve) => setTimeout(resolve, 300));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ order_id: 102, operation: "inbound", item_code: item.item_code, quantity: 1, status: "QUEUED", tasks: [] }),
    });
  });
  await page.goto("/operate/control?drawer=inout");
  await page.getByLabel("품목").selectOption(item.item_code);
  const execute = page.getByRole("button", { name: /요청 실행/ });
  await execute.click();
  await expect(page.getByRole("button", { name: "요청 중" })).toBeDisabled();
  await expect(page.getByRole("button", { name: /요청 실행/ })).toBeVisible();
  expect(createCount).toBe(1);
});

const workOrderErrors = [
  ["no_available_slot", /빈 슬롯이 없습니다/],
  ["capacity_exceeded", /슬롯 용량을 초과/],
  ["robot_offline", /연결할 수 없습니다/],
  ["robot_not_localized", /초기 위치 설정 필요/],
] as const;

for (const [code, message] of workOrderErrors) {
  test(`WEB-07 업무 오류 ${code}를 운영자 메시지로 표시한다`, async ({ page }) => {
    await mockMainApi(page);
    await page.route("**/api/v1/work-orders", (route) => route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({ detail: { error: code } }),
    }));
    await page.goto("/operate/control?drawer=inout");
    await page.getByLabel("품목").selectOption(item.item_code);
    await page.getByRole("button", { name: /요청 실행/ }).click();
    await expect(page.getByText(message)).toBeAttached();
  });
}

test("WEB-08 예약 작업이 없으면 배치 실행을 막고 이유를 표시한다", async ({ page }) => {
  await mockMainApi(page, { workOrders: [] });
  await page.goto("/operate/control");
  await page.locator(".slim-nav").getByRole("button", { name: /작업/ }).click();
  await expect(page.getByRole("button", { name: "자동 배정" })).toBeDisabled();
  await expect(page.getByRole("button", { name: /배정·시작/ })).toBeDisabled();
  await expect(page.getByText("배정할 예약 작업이 없습니다")).toBeVisible();
});

test("WEB-09 Movement 오프라인이면 수동 방향 조작을 막는다", async ({ page }) => {
  await mockMainApi(page, { movementOk: false });
  await page.goto("/operate/control");
  await expect(page.getByRole("button", { name: "조작 →", exact: true })).toBeDisabled();
  await expect(page.getByText(/Movement 서버 오프라인/)).toBeVisible();
  await expect(page.getByText(/Movement 서버 오프라인/)).toHaveCount(1);
});

test("WEB-10 맵 편집 액션은 선택한 구역에만 표시한다", async ({ page }) => {
  await mockMainApi(page);
  await page.goto("/admin/map");
  await expect(page.getByRole("button", { name: "수정" })).toHaveCount(0);
  await page.getByRole("row", { name: /입고/ }).click();
  await expect(page.getByRole("button", { name: "수정" })).toHaveCount(1);
  await expect(page.getByText(/구역을 선택하면 상세 작업/)).toHaveCount(0);
});

test("WEB-11 복구는 적재 확인 전 차단하고 두 가지 방식만 제공한다", async ({ page }) => {
  await mockMainApi(page, {
    recoveryTasks: [{
      task_id: 1,
      status: "RUNNING",
      orchestration_phase: "AWAITING_OPERATOR",
      awaiting_operator: true,
      assigned_robot_id: robot.robot_id,
      last_step_kind: "move_to_point",
    }],
  });
  await page.goto("/operate/control");
  await expect(page.locator(".operator-kpi-strip .kpi-tile").filter({ hasText: "활성 작업" })).toContainText("복구 1");
  await page.locator(".slim-nav").getByRole("button", { name: /작업/ }).click();
  await expect(page.getByText("안전 위치로 이동", { exact: true })).toBeVisible();
  await expect(page.getByText("작업 종료 및 수동 회수", { exact: true })).toBeVisible();
  await expect(page.getByText("처음부터 다시 시작")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "단계 미리보기" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "안전 위치 이동 실행" })).toBeDisabled();
  await page.getByLabel("LOADED").check();
  await page.getByRole("button", { name: "단계 미리보기" }).click();
  await expect(page.getByText("safe:HOME_01")).toBeVisible();
  await expect(page.getByText(/자동 하역 및 기존 작업 재개/)).toBeVisible();
});

test("WEB-12 좌측 입출고 메뉴는 요청·위치 확인 작업면을 열고 작업 수를 유지한다", async ({ page }) => {
  await mockMainApi(page, { tasks: [{ task_id: 9, task_type: "INBOUND", priority: 10, status: "RUNNING" }] });
  await page.goto("/operate/control");
  const inoutNav = page.getByRole("navigation", { name: "운영 메뉴" }).getByRole("button", { name: "입출고", exact: true });
  const taskNav = page.locator(".slim-nav").getByRole("button", { name: "작업", exact: true });
  await expect(taskNav).toContainText("1");

  await inoutNav.click();
  await expect(page).toHaveURL(new RegExp("/operate/control\\?robot=tb3_1&drawer=inout$"));
  await expect(inoutNav).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("region", { name: "입출고 요청과 위치 확인 맵" })).toBeVisible();
  await expect(page.getByRole("region", { name: "입출고 위치 확인 맵" })).toBeVisible();
  await expect(page.getByRole("region", { name: "전역 카메라" })).toBeVisible();
  await page.getByRole("button", { name: "취소" }).click();
  await expect(page).toHaveURL(new RegExp("/operate/control\\?robot=tb3_1$"));
});

test("WEB-13 좁은 화면 드로어는 배경을 차단하는 모달로 동작한다", async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 800 });
  await mockMainApi(page);
  await page.goto("/operate/control?drawer=inout");
  const dialog = page.getByRole("dialog", { name: "입출고" });
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  await expect(page.locator(".operator-main")).toHaveAttribute("inert", "");
  await expect(page.getByRole("button", { name: "닫기" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByRole("button", { name: "취소" })).toBeFocused();
  await page.locator(".drawer-scrim").click({ position: { x: 800, y: 400 } });
  await expect(page).toHaveURL(/\/operate\/control\?robot=tb3_1$/);
});

test("WEB-14 이전 입출고 URL은 canonical 드로어 URL로 교체된다", async ({ page }) => {
  await mockMainApi(page);
  await page.goto("/operate/inout");
  await expect(page).toHaveURL(/\/operate\/control\?drawer=inout$/);
});

test("WEB-15 작업 메뉴는 중앙 작업 워크스페이스로 전환한다", async ({ page }) => {
  await mockMainApi(page, { tasks: [{ task_id: 9, task_type: "INBOUND", priority: 10, status: "RUNNING" }] });
  await page.goto("/operate/control");
  const nav = page.locator(".slim-nav");

  await nav.getByRole("button", { name: /작업/ }).click();
  await expect(page).toHaveURL(new RegExp("/operate/tasks$"));
  await expect(page.locator("#operator-workspace-main")).toHaveAttribute("aria-label", "작업 워크스페이스");
  await expect(page.getByRole("button", { name: "자동 배정" })).toBeVisible();
  await expect(page.locator(".operator-insight-band")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "전역 카메라" })).toBeVisible();

  await nav.getByRole("button", { name: "관제", exact: true }).click();
  await expect(page).toHaveURL(new RegExp("/operate/control$"));
  await expect(page.locator(".operator-map-stage-wrap")).toBeVisible();
  await expect(page.getByRole("region", { name: "작업 큐, 할당 로봇, 타임라인과 안전 중지" })).toBeVisible();
});

test("WEB-17 KPI는 읽기 전용이고 이벤트 명령은 현재 경고 문맥에 둔다", async ({ page }) => {
  await mockMainApi(page, {
    events: [
      { id: 1, created_at: "2026-07-14T09:00:00Z", event_type: "ROBOT_ESTOP", message: "tb3_1 비상 정지" },
      { id: 2, created_at: "2026-07-14T09:01:00Z", event_type: "MOVEMENT_RESULT", message: "이동 timeout" },
      { id: 3, created_at: "2026-07-14T09:02:00Z", event_type: "MOVEMENT_ROBOT_STATUS", message: "error" },
      { id: 4, created_at: "2026-07-14T09:03:00Z", event_type: "POSE_RECOVERED", message: "POSE_RECOVERED: stale -> live" },
      { id: 5, created_at: "2026-07-14T09:04:00Z", event_type: "POSE_STALE", message: "POSE_STALE: live -> stale", payload: { pose: { quality_reasons: ["SOURCE_DELAY"], source_age_sec: 3.1 } } },
    ],
  });
  await page.goto("/operate/control");

  const alarmTile = page.locator(".operator-kpi-strip .kpi-tile").filter({ hasText: "미확인 알람" });
  const map = page.locator(".operator-map-stage-wrap");
  const before = await map.boundingBox();
  await expect(alarmTile).toHaveClass(/err/);
  await expect(alarmTile.locator(".kpi-value")).toHaveText("2");
  await expect(alarmTile).not.toHaveAttribute("role", "button");

  await page.locator(".operator-priority-alert").getByRole("button", { name: "이벤트 보기" }).click();
  await expect(page).toHaveURL(new RegExp("/operate/events$"));
  await expect(page.locator("#operator-workspace-main")).toHaveAttribute("aria-label", "이벤트 워크스페이스");
  await expect(page.getByRole("region", { name: "전역 카메라" })).toBeVisible();

  await page.getByRole("button", { name: "관제", exact: true }).click();
  const returned = await map.boundingBox();
  expect(returned?.y).toBe(before?.y);

  await page.locator(".operator-priority-alert").getByRole("button", { name: "확인", exact: true }).click();
  await expect(alarmTile).not.toHaveClass(/err|warn/);
  await expect(alarmTile.locator(".kpi-value")).toHaveText("0");
});
test("WEB-18 운영 지도와 관리자 Goto는 공통 런타임 캔버스를 사용한다", async ({ page }) => {
  await mockMainApi(page);

  await page.goto("/operate/control");
  const operatorMap = page.locator(".operator-map-wrap .map-stage");
  await expect(operatorMap.locator(":scope > .map-zoom-layer")).toHaveCount(1);

  await page.goto("/admin/devices");
  const adminGotoMap = page.locator(".goto-stage");
  await expect(adminGotoMap.locator(":scope > .map-zoom-layer")).toHaveCount(1);
  await adminGotoMap.click();
  await expect(adminGotoMap.locator("[data-goto-target]")).toHaveCount(1);
});

test("WEB-19 배터리 미수신은 대시와 회색 게이지로 표시한다", async ({ page }) => {
  await mockMainApi(page, { robotBattery: null });
  await page.goto("/operate/control");

  const batteries = page.locator(".battery-indicator");
  await expect(batteries.first()).toHaveClass(/battery-unknown/);
  await expect(batteries.first()).toContainText("—");
  await expect(batteries.first()).not.toContainText("100%");
});

test("WEB-16 WebRTC 대기 영상 요소는 hidden으로 제거되지 않는다", async ({ page }) => {
  await mockMainApi(page, {
    cameraOnline: true,
    cameraSources: [{
      source_id: "tb3_1_picam",
      label: "AMR 1 Camera",
      robot_id: robot.robot_id,
      status: "online",
      stream_url: "",
    }],
  });
  await page.goto("/operate/control");

  const video = page.locator(".cam-tile video").first();
  await expect(video).toBeAttached();
  await expect(video).not.toHaveAttribute("hidden", "");
  expect(await video.evaluate((element) => getComputedStyle(element).display)).not.toBe("none");
});


test("WEB-20 Main 오류 상태만 시스템 진단 이동을 제공한다", async ({ page }) => {
  await mockMainApi(page, { statusError: true });
  await page.goto("/operate/control");

  const action = page.getByRole("button", { name: /Main 연결 대기 · 시스템 보기/ });
  await expect(action).toBeVisible();
  await action.click();
  await expect(page).toHaveURL(new RegExp("/admin/system$"));
});

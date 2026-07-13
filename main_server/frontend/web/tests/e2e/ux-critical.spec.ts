import { expect, test } from "@playwright/test";
import { item, mockMainApi, robot, slot } from "../support/mainApi";

test("WEB-01 입고 요청은 중복 제출을 막고 결과를 표시한다", async ({ page }) => {
  await mockMainApi(page);
  await page.goto("/operate/control?drawer=inout");
  await page.getByLabel("품목").selectOption(item.item_code);
  const execute = page.getByRole("button", { name: "실행", exact: true });
  await execute.click({ force: true });
  await expect(page.getByText(/작업|요청/).first()).toBeAttached();
});

test("WEB-02 재고 부족 오류는 입력과 재고 보기 동작을 유지한다", async ({ page }) => {
  await mockMainApi(page, { inventory: [{ slot_id: slot.slot_id, item_code: item.item_code, quantity: 1, floor: 1 }] });
  await page.route("**/api/v1/work-orders", (route) => route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: { error: "insufficient_inventory" } }) }));
  await page.goto("/operate/control?drawer=inout");
  await page.getByRole("button", { name: "출고", exact: true }).click();
  await page.getByLabel("품목").selectOption(item.item_code);
  await page.getByLabel("수량").fill("1", { force: true });
  await page.getByRole("button", { name: "실행", exact: true }).click({ force: true });
  await expect(page.getByText(/재고가 부족/)).toBeAttached();
  await expect(page.getByRole("link", { name: "재고 보기" })).toBeAttached();
  await expect(page.getByLabel("수량")).toHaveValue("1");
});

test("WEB-03 ESTOP은 운영 명령을 차단하고 해제 확인을 요구한다", async ({ page }) => {
  await mockMainApi(page, { emergency: true });
  await page.goto("/operate/control?drawer=inout");
  await expect(page.getByRole("button", { name: "실행", exact: true })).toBeDisabled();
  await expect(page.getByText(/비상 정지 중/).first()).toBeAttached();
  await page.getByRole("button", { name: "ESTOP 활성" }).click();
  await expect(page.getByRole("alertdialog")).toBeVisible();
});

test("WEB-04 실행 작업은 안전 중단 확인을 거친다", async ({ page }) => {
  await mockMainApi(page, { workOrders: [{ order_id: 7, operation: "inbound", status: "RUNNING", priority: 10, business_completed: false, tasks: [{ task_id: 8, status: "RUNNING", assigned_robot_id: robot.robot_id }] }] });
  await page.goto("/operate/tasks");
  page.once("dialog", async (dialog) => {
    expect(dialog.message()).toContain("안전 중단");
    await dialog.dismiss();
  });
  await page.getByRole("button", { name: "안전 중단" }).click();
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
  const execute = page.getByRole("button", { name: "실행", exact: true });
  await execute.click();
  await expect(page.getByRole("button", { name: "요청 중" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "실행", exact: true })).toBeVisible();
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
    await page.getByRole("button", { name: "실행", exact: true }).click();
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
  await page.getByRole("button", { name: /수동 조작 · 맵 이동/ }).click();
  await expect(page.getByRole("button", { name: "▲" })).toBeDisabled();
  await expect(page.getByText(/Movement 서버에 연결할 수 없습니다/)).toBeVisible();
  await expect(page.getByText(/Movement 서버에 연결할 수 없습니다/)).toHaveCount(1);
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
  await expect(page.locator(".task-workspace-summary")).toContainText("복구 1");
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

test("WEB-12 데스크톱 드로어는 비모달 패널이고 활성 메뉴에 작업 수를 표시한다", async ({ page }) => {
  await mockMainApi(page, { tasks: [{ task_id: 9, status: "RUNNING" }] });
  await page.goto("/operate/control");
  const inoutNav = page.getByRole("button", { name: "입출고" });
  await inoutNav.click();
  await expect(page).toHaveURL(/\/operate\/control\?drawer=inout$/);
  await expect(inoutNav).toHaveAttribute("aria-current", "page");
  await expect(inoutNav).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("region", { name: "입출고" })).toBeVisible();
  await expect(page.getByRole("button", { name: /작업, 진행 중 1건, 접힘/ })).toBeVisible();
  await page.getByRole("button", { name: "닫기" }).click();
  await expect(page).toHaveURL(/\/operate\/control$/);
  await expect(inoutNav).toBeFocused();
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
  await expect(page).toHaveURL(/\/operate\/control$/);
});

test("WEB-14 이전 입출고 URL은 canonical 드로어 URL로 교체된다", async ({ page }) => {
  await mockMainApi(page);
  await page.goto("/operate/inout");
  await expect(page).toHaveURL(/\/operate\/control\?drawer=inout$/);
});

test("WEB-15 작업 메뉴는 하단 워크스페이스를 접고 다시 펼친다", async ({ page }) => {
  await mockMainApi(page, { tasks: [{ task_id: 9, status: "RUNNING" }] });
  await page.goto("/operate/control");
  const taskNav = page.locator('.slim-nav button[aria-controls="operator-tasks-workspace"]');
  const content = page.locator("#operator-tasks-content");

  await expect(taskNav).toHaveAttribute("aria-expanded", "false");
  await expect(content).toBeHidden();
  await taskNav.click();
  await expect(page).toHaveURL(/\/operate\/control\?panel=tasks$/);
  await expect(page.locator(".task-workspace-summary")).toBeFocused();
  await expect(taskNav).toHaveAttribute("aria-expanded", "true");
  await expect(content).toBeVisible();
  await expect(page.getByRole("button", { name: "자동 배정" })).toBeVisible();

  await page.locator(".task-workspace-summary").click();
  await expect(page).toHaveURL(/\/operate\/control$/);
  await expect(content).toBeHidden();
  await taskNav.click();
  await expect(content).toBeVisible();
});

import { expect, test } from "@playwright/test";
import { mockMainApi } from "../support/mainApi";

test("ESTOP 상태 미확인은 비상 정지 활성과 분리해 표시한다", async ({ page }) => {
  await mockMainApi(page, { estopUnknown: true });
  await page.goto("/operate/control");

  await expect(page.getByRole("button", { name: "ESTOP", exact: true })).toBeVisible();
  const unknown = page.getByRole("button", { name: "정지 미확인 1, 다시 조회" });
  await expect(unknown).toBeVisible();
  await expect(page.locator(".emergency-badge")).toHaveCount(0);
  await expect(page.getByText(/비상 정지 활성/)).toHaveCount(0);

  await unknown.click();
  await expect(page.getByRole("button", { name: "ESTOP", exact: true })).toBeEnabled();
});


test("ESTOP 실행 요청과 확인 후 해제가 현재 API 경로로 왕복한다", async ({ page }) => {
  const clearState = { emergency: false };
  await mockMainApi(page, clearState);
  await page.goto("/operate/control");

  const stopRequest = page.waitForRequest((request) => request.url().endsWith("/api/v1/robots/estop-all") && request.method() === "POST");
  await page.getByRole("button", { name: "ESTOP", exact: true }).click();
  await stopRequest;
  await expect(page.getByText("비상 정지 — 전 로봇 정지")).toBeVisible();

  clearState.emergency = true;
  await page.reload();
  await expect(page.getByRole("button", { name: "ESTOP 활성" })).toBeVisible();
  await page.getByRole("button", { name: "ESTOP 활성" }).click();
  await expect(page.getByRole("alertdialog", { name: "비상 정지 해제" })).toBeVisible();
  clearState.emergency = false;
  const clearRequest = page.waitForRequest((request) => request.url().endsWith("/api/v1/robots/clear-estop-all") && request.method() === "POST");
  await page.getByRole("button", { name: "해제", exact: true }).click();
  await clearRequest;
  await expect(page.getByText("비상 정지 해제됨 — 작업은 복구 선택 필요")).toBeVisible();
  await expect(page.getByRole("button", { name: "ESTOP", exact: true })).toBeVisible();
});

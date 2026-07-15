import { expect, test } from "@playwright/test";
import { mockMainApi } from "../support/mainApi";

test("ESTOP 상태 미확인은 비상 정지 활성과 분리해 표시한다", async ({ page }) => {
  await mockMainApi(page, { estopUnknown: true });
  await page.goto("/operate/control");

  await expect(page.getByRole("button", { name: "ESTOP", exact: true })).toBeVisible();
  const unknown = page.getByRole("button", { name: "ESTOP 상태 미확인 1대, 다시 조회" });
  await expect(unknown).toBeVisible();
  await expect(page.locator(".emergency-badge")).toHaveCount(0);
  await expect(page.getByText(/비상 정지 활성/)).toHaveCount(0);

  await unknown.click();
  await expect(page.getByRole("button", { name: "ESTOP", exact: true })).toBeEnabled();
});

import { expect, test } from "@playwright/test";
import { mockMainApi } from "../support/mainApi";

test("입출고 문맥을 열어도 지도와 전역 카메라는 같은 위치에 유지된다", async ({ page }, testInfo) => {
  await mockMainApi(page, {
    cameraOnline: true,
    cameraSources: [{
      source_id: "CAM_GLOBAL_1",
      label: "창고 전역",
      robot_id: null,
      status: "ONLINE",
    }],
    tasks: [{ task_id: 9, status: "RUNNING", assigned_robot_id: "tb3_1" }],
    events: [{
      event_type: "robot_pose_stale",
      message: "tb3_1 Pose 수신 상태를 확인하세요.",
      created_at: "2026-07-15T10:00:00Z",
    }],
  });
  await page.goto("/operate/control");

  const map = page.locator(".operator-map-stage-wrap");
  const globalCamera = page.getByRole("region", { name: "전역 카메라" });
  await expect(map).toBeVisible();
  await expect(globalCamera).toBeVisible();

  const mapBefore = await map.boundingBox();
  const cameraBefore = await globalCamera.boundingBox();
  expect(mapBefore).not.toBeNull();
  expect(cameraBefore).not.toBeNull();
  expect(cameraBefore!.y + cameraBefore!.height).toBeLessThanOrEqual(1080);

  await page.locator(".slim-nav").getByRole("button", { name: "입출고", exact: true }).click();
  const drawer = page.getByRole("region", { name: "입출고" });
  await expect(drawer).toBeVisible();
  await expect(map).toBeVisible();
  await expect(globalCamera).toBeVisible();

  const mapAfter = await map.boundingBox();
  const cameraAfter = await globalCamera.boundingBox();
  const drawerBox = await drawer.boundingBox();
  expect(mapAfter).not.toBeNull();
  expect(cameraAfter).not.toBeNull();
  expect(drawerBox).not.toBeNull();
  expect(Math.abs(mapAfter!.width - mapBefore!.width)).toBeLessThanOrEqual(1);
  expect(Math.abs(cameraAfter!.y - cameraBefore!.y)).toBeLessThanOrEqual(1);
  expect(drawerBox!.x).toBeGreaterThan(mapAfter!.x + mapAfter!.width);
  expect(drawerBox!.y + drawerBox!.height).toBeLessThanOrEqual(cameraAfter!.y);

  await page.screenshot({ path: testInfo.outputPath("operations-redesign.png"), fullPage: true });
});

test("1440x900에서도 입출고 문맥과 전역 카메라가 한 뷰포트에 유지된다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockMainApi(page, {
    cameraOnline: true,
    cameraSources: [{
      source_id: "CAM_GLOBAL_1",
      label: "창고 전역",
      robot_id: null,
      status: "ONLINE",
    }],
  });
  await page.goto("/operate/control?drawer=inout");

  const map = page.locator(".operator-map-stage-wrap");
  const drawer = page.getByRole("region", { name: "입출고" });
  const globalCamera = page.getByRole("region", { name: "전역 카메라" });
  await expect(map).toBeVisible();
  await expect(drawer).toBeVisible();
  await expect(globalCamera).toBeVisible();

  const cameraBox = await globalCamera.boundingBox();
  const drawerBox = await drawer.boundingBox();
  expect(cameraBox).not.toBeNull();
  expect(drawerBox).not.toBeNull();
  expect(cameraBox!.y + cameraBox!.height).toBeLessThanOrEqual(900);
  expect(drawerBox!.y + drawerBox!.height).toBeLessThanOrEqual(cameraBox!.y);
});

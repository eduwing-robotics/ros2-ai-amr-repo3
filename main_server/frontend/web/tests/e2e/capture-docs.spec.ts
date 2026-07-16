import path from "node:path";
import { test } from "@playwright/test";

const screens = {
  "operate-control.png": "/operate/control",
  "operate-inout.png": "/operate/control?drawer=inout",
  "operate-inventory.png": "/operate/inventory",
  "operate-tasks.png": "/operate/tasks",
  "operate-records.png": "/operate/events",
  "records-events.png": "/records/events",
  "admin-map.png": "/admin/map",
  "admin-warehouse.png": "/admin/warehouse",
  "admin-devices.png": "/admin/devices",
  "admin-system.png": "/admin/system",
} as const;

test("capture current documentation screens", async ({ page }) => {
  for (const [filename, route] of Object.entries(screens)) {
    const separator = route.includes("?") ? "&" : "?";
    await page.goto("http://localhost:8088" + route + separator + "docshot=20260716", {
      waitUntil: "domcontentloaded",
    });
    await page.locator(".shell").waitFor({ state: "visible" });
    await page.waitForTimeout(1000);
    await page.locator("body").evaluate((body) => {
      body.setAttribute("data-docshot", "current");
    });
    await page.screenshot({
      path: path.resolve(process.cwd(), "../../docs/assets/screens/current", filename),
    });
  }
});

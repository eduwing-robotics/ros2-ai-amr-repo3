import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  reporter: "list",
  testIgnore: process.env.LMS_CAPTURE_DOCS === "1" ? [] : "**/capture-docs.spec.ts",
  use: {
    baseURL: "http://127.0.0.1:4173",
    channel: "chrome",
    viewport: { width: 1920, height: 1080 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4173",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: true,
  },
});

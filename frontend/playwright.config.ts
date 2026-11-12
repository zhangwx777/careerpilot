import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  fullyParallel: false,
  reporter: "list",
  outputDir: "../build/plan-execution/browser-results",
  use: { baseURL: "http://127.0.0.1:18765", screenshot: "only-on-failure", trace: "retain-on-failure" },
  webServer: {
    command: `${process.env.E2E_PYTHON ?? "python"} ../backend/tests/browser_server.py`,
    url: "http://127.0.0.1:18765/api/applications",
    timeout: 90000,
    reuseExistingServer: false,
  },
});

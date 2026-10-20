import { defineConfig, devices } from "@playwright/test";

// E2E runs against an ISOLATED Compose project (scripts/e2e.*), never the owner's workspace:
//   docker compose -p decisionops-e2e --env-file <test env> up -d   (APP_PORT=8097)
// Specs run in file order with one worker: j01 creates the owner that later journeys sign in as.
export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: [["list"], ["json", { outputFile: "test-results/e2e-results.json" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8097",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    ...devices["Desktop Chrome"],
  },
});

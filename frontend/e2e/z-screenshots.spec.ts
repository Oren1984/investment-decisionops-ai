import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "@playwright/test";

// Documentation screenshots, captured from the read-only DEMO instance (synthetic data only, plan §20).
// Never concept images; never the owner's workspace; no credentials are visible after sign-in.
// Run on purpose: SCREENSHOTS=1 npx playwright test z-screenshots
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "screenshots");
const SHOTS: [string, string][] = [
  ["overview", "/demo/"], ["markets", "/demo/markets"], ["portfolio", "/demo/portfolio"], ["decisions", "/demo/decisions"],
  ["orders", "/demo/orders"], ["library", "/demo/library"], ["collaboration", "/demo/collaboration"], ["help", "/demo/help"],
];

test("capture documentation screenshots from the demo", async ({ page }) => {
  test.skip(process.env.SCREENSHOTS !== "1", "Set SCREENSHOTS=1 to refresh docs/screenshots");
  mkdirSync(OUT, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/demo/");
  await page.getByLabel("Email").fill(process.env.E2E_DEMO_EMAIL ?? "demo@example.com");
  await page.getByLabel("Password").fill(process.env.E2E_DEMO_PASSWORD ?? "demo-read-only");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("navigation", { name: "Main" }).waitFor();
  for (const [name, path] of SHOTS) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(600);
    await page.screenshot({ path: join(OUT, `${name}.png`) });
  }
  const decision = page.getByRole("link", { name: /Add to NVDA/ }).first();
  await page.goto("/demo/decisions");
  await decision.click();
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: join(OUT, "decision-evidence.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/demo/");
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: join(OUT, "overview-mobile.png") });
});

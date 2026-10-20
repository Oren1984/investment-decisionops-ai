import { expect, test } from "@playwright/test";
import { api, newOwnerCreds } from "./helpers";

// J1 First run: setup token → create owner → home location → Mock mode with a synthetic portfolio.
test("J1 first run creates the owner with a one-time setup token", async ({ page }) => {
  const token = process.env.E2E_SETUP_TOKEN;
  test.skip(!token, "E2E_SETUP_TOKEN is required (scripts/e2e sets it for the isolated stack)");
  const status = await api(page.context(), "GET", "/auth/status");
  test.skip(!status.json.setup_required, "The isolated stack already has an owner (J1 runs on a fresh stack only)");

  const creds = newOwnerCreds();
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Set up your workspace" })).toBeVisible();
  await page.getByLabel("Setup token").fill("wrong-token");
  await page.getByLabel("Your name").fill("E2E Owner");
  await page.getByLabel("Email").fill(creds.email);
  await page.getByLabel("Password", { exact: true }).fill(creds.password);
  await page.getByLabel("Confirm password").fill(creds.password);
  await page.getByLabel("Home timezone").selectOption("Asia/Jerusalem");
  await page.getByRole("button", { name: "Create owner account" }).click();
  await expect(page.getByText(/setup token is invalid or expired/i)).toBeVisible();

  await page.getByLabel("Setup token").fill(token!);
  await page.getByRole("button", { name: "Create owner account" }).click();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await expect(page.getByTitle(/Trading mode/)).toContainText("MOCK");
  await expect(page.getByTitle("Market data freshness")).toContainText("Synthetic");
  await expect(page.getByLabel("Clocks")).toContainText("Jerusalem");

  // The token works once.
  const again = await api(page.context(), "POST", "/auth/setup", { setup_token: token, email: "x@example.com", display_name: "X", password: "another-long-password", timezone: "UTC" });
  expect(again.status).toBe(409);

  await page.goto("/portfolio");
  await expect(page.getByText(/Synthetic/).first()).toBeVisible();
});

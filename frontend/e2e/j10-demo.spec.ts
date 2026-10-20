import { expect, test } from "@playwright/test";
import { api, ownerCreds } from "./helpers";

// J10 Local demo visitor: sign in with the published demo account → read-only synthetic workspace with banner →
// no uploads/orders/invites/settings changes; direct API writes → 403; the owner cannot sign in to the demo.
const DEMO = { email: process.env.E2E_DEMO_EMAIL ?? "demo@example.com", password: process.env.E2E_DEMO_PASSWORD ?? "demo-read-only" };

test("J10 demo sign-in, read-only UI and API, isolation from the owner workspace", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Enter the read-only demo" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to the demo" })).toBeVisible();
  await page.getByLabel("Email").fill(DEMO.email);
  await page.getByLabel("Password").fill(DEMO.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("note").filter({ hasText: "Read-only demo" })).toBeVisible();

  await page.goto("/demo/library");
  await expect(page.locator("label[for=upload]")).toHaveCount(0);
  await page.goto("/demo/orders");
  await expect(page.getByRole("button", { name: "New order ticket" })).toHaveCount(0);
  await page.goto("/demo/decisions");
  await expect(page.getByRole("link", { name: /Add to NVDA/ }).first()).toBeVisible(); // synthetic demo data

  for (const [method, path, body] of [["POST", "/orders", {}], ["POST", "/decisions", { title: "x" }], ["POST", "/invitations", {}],
    ["PUT", "/settings/preferences", {}], ["POST", "/orders/stop", { engaged: true }],
    ["POST", "/meetings", { title: "x", starts_at: "2026-11-02T09:00:00Z", provider: "manual", link_provider: "google_meet", join_url: "https://meet.google.com/abc-defg-hij" }]] as const) {
    const r = await api(page.context(), method, path, body, "/demo/api");
    expect(r.status, `${method} ${path}`).toBe(403);
  }
  const owner = await api(page.context(), "POST", "/auth/login", ownerCreds(), "/demo/api");
  expect(owner.status).toBe(401);
  const demoOnMain = await api(page.context(), "POST", "/auth/login", DEMO);
  expect(demoOnMain.status).toBe(401);
  // The demo session does not authenticate the main workspace.
  expect((await api(page.context(), "GET", "/decisions")).status).toBe(401);

  await page.getByRole("button", { name: "Sign out of demo" }).click();
  await expect.poll(async () => (await api(page.context(), "GET", "/decisions", undefined, "/demo/api")).status).toBe(401);
});

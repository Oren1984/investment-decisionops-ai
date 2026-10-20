import { expect, type Page, test } from "@playwright/test";
import { api, signIn } from "./helpers";

// J13 Sign-out: the session ends server-side, the sign-in screen appears at once without a reload, and neither
// browser Back nor a protected URL brings the private screen back. Owner and demo.
const DEMO = { email: process.env.E2E_DEMO_EMAIL ?? "demo@example.com", password: process.env.E2E_DEMO_PASSWORD ?? "demo-read-only" };

/** Marks the loaded document; a full page reload would lose the mark. */
async function markDocument(page: Page) {
  await page.evaluate(() => ((window as unknown as { __sameDocument: boolean }).__sameDocument = true));
}
async function sameDocument(page: Page) {
  return page.evaluate(() => (window as unknown as { __sameDocument?: boolean }).__sameDocument === true);
}

test("J13 owner sign-out shows sign-in at once; Back and protected URLs stay signed out", async ({ page }) => {
  await signIn(page);
  await page.goto("/");
  await page.getByRole("link", { name: "Portfolio" }).first().click();
  await expect(page.getByRole("heading", { name: "Portfolio", level: 1 })).toBeVisible();
  await markDocument(page);

  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible({ timeout: 5000 });
  expect(await sameDocument(page), "no manual or automatic reload was needed").toBe(true);
  await expect(page.getByRole("heading", { name: "Portfolio", level: 1 })).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
  await expect(page).toHaveURL(/\/$/);

  expect((await api(page.context(), "GET", "/auth/me")).status, "session ended server-side").toBe(401);
  expect((await api(page.context(), "GET", "/portfolio")).status).toBe(401);

  await page.goBack();
  await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
  for (const path of ["/portfolio", "/orders", "/settings"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: "Sign in", exact: true }), path).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
  }
});

test("J13 demo sign-out returns to the demo sign-in; Back and protected URLs stay signed out", async ({ page }) => {
  await page.goto("/demo/");
  await page.getByLabel("Email").fill(DEMO.email);
  await page.getByLabel("Password").fill(DEMO.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("note").filter({ hasText: "Read-only demo" })).toBeVisible();
  await page.getByRole("link", { name: "Orders" }).first().click();
  await expect(page.getByRole("heading", { name: /orders/i, level: 1 })).toBeVisible();
  await markDocument(page);

  await page.getByRole("button", { name: "Sign out of demo" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to the demo" })).toBeVisible({ timeout: 5000 });
  expect(await sameDocument(page)).toBe(true);
  await expect(page).toHaveURL(/\/demo\/?$/); // router basename "/demo": the demo sign-in, not the owner app
  await expect(page.getByRole("note").filter({ hasText: "Read-only demo" })).toHaveCount(0);
  expect((await api(page.context(), "GET", "/auth/me", undefined, "/demo/api")).status).toBe(401);

  await page.goBack();
  await expect(page.getByRole("heading", { name: "Sign in to the demo" })).toBeVisible();
  for (const path of ["/demo/orders", "/demo/portfolio"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: "Sign in to the demo" }), path).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
  }
});

import { expect, test } from "@playwright/test";
import { api, confirmStepUp, signIn } from "./helpers";

// J7 Order (Mock): ticket → preview → step-up approval → submit → events → partial fill → fill / reconciliation.
test("J7 Mock order: preview, step-up approval, duplicate-safe submit, partial fill", async ({ page }) => {
  await signIn(page);
  await page.goto("/orders");
  await page.getByRole("button", { name: "New order ticket" }).click();
  const dialog = page.getByRole("dialog", { name: "New order ticket" });
  await dialog.getByLabel("Instrument (tradable in this scope)").selectOption({ label: /^AAPL/ } as never).catch(async () => {
    const opt = dialog.getByLabel("Instrument (tradable in this scope)").locator("option", { hasText: "AAPL" }).first();
    await dialog.getByLabel("Instrument (tradable in this scope)").selectOption(await opt.getAttribute("value") ?? "");
  });
  await dialog.getByLabel("Quantity").fill("10");
  await dialog.getByLabel("Mock scenario (simulation only)").selectOption("partial_fill");
  await dialog.getByRole("button", { name: "Create ticket" }).click();
  await page.waitForURL(/\/orders\/[0-9a-f-]{36}$/);
  const id = page.url().split("/").pop()!;

  await page.getByRole("button", { name: "Preview" }).click();
  await expect(page.getByText(/Limit and safety checks \(\d+\/\d+ passed\)/)).toBeVisible();
  await expect(page.getByText("Estimated commission")).toBeVisible();
  await page.getByRole("button", { name: "Approve this exact order" }).click();
  await confirmStepUp(page);
  await expect(page.getByText("approved").first()).toBeVisible();

  await page.getByRole("button", { name: "Submit to broker" }).click();
  await expect.poll(async () => (await api(page.context(), "GET", `/orders/${id}`)).json.status, { timeout: 60_000 })
    .toMatch(/^(acknowledged|partially_filled)$/);
  const dup = await api(page.context(), "POST", `/orders/${id}/submit`);
  expect(dup.json.duplicate).toBe(true); // a repeated submit never sends a second order

  // The worker reconciles every few seconds: the partial fill arrives from a (simulated) execution report.
  await expect.poll(async () => (await api(page.context(), "GET", `/orders/${id}`)).json.status, { timeout: 90_000, intervals: [2000] })
    .toMatch(/^(partially_filled|filled)$/);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Order events" })).toBeVisible();
  await expect(page.getByText(/Partially filled/).first()).toBeVisible();
  const o = (await api(page.context(), "GET", `/orders/${id}`)).json;
  expect(o.executions.length).toBeGreaterThanOrEqual(1);
});

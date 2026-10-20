import { expect, test } from "@playwright/test";
import { api, maybeConfirmStepUp, signIn, stepUpViaApi } from "./helpers";

// J8 Stop: engage → submissions and agent runs blocked → plain explanation → separate tracked cancel-open-orders workflow.
test("J8 Stop blocks submissions and runs; cancel-open-orders is a separate tracked step", async ({ page }) => {
  await signIn(page);
  const ctx = page.context();
  // An approved order waiting for submission, and one open order at the (simulated) broker.
  const mk = async (scenario: string) => {
    const quotes = (await api(ctx, "GET", "/markets/quotes")).json as { id: string; symbol: string; quote: { price: number } }[];
    const msft = quotes.find((q) => q.symbol === "MSFT")!;
    const t = (await api(ctx, "POST", "/orders", { instrument_id: msft.id, side: "buy", quantity: 1, order_type: "limit", limit_price: Math.round(msft.quote.price * 100) / 100, mock_scenario: scenario })).json;
    await api(ctx, "POST", `/orders/${t.id}/preview`);
    await stepUpViaApi(page);
    expect((await api(ctx, "POST", `/orders/${t.id}/approve`)).status).toBe(200);
    return t.id as string;
  };
  const openId = await mk("fill_after_cancel");
  expect((await api(ctx, "POST", `/orders/${openId}/submit`)).status).toBe(200);
  const pendingId = await mk("success");

  await page.goto("/orders");
  await page.getByRole("button", { name: "Engage stop" }).click();
  const dlg = page.getByRole("dialog", { name: "Engage the stop?" });
  await expect(dlg).toContainText("does not cancel orders the broker has already accepted");
  await dlg.getByLabel("Reason (optional)").fill("E2E drill");
  await dlg.getByRole("button", { name: "Engage stop now" }).click();
  await expect(page.getByText("Stop engaged").first()).toBeVisible();

  const blocked = await api(ctx, "POST", `/orders/${pendingId}/submit`);
  expect(blocked.status).toBe(409);
  expect(blocked.json.code).toBe("stop_engaged");
  const decisions = (await api(ctx, "GET", "/decisions")).json as { id: string }[];
  const run = await api(ctx, "POST", `/decisions/${decisions[0].id}/runs`, { mode: "deterministic" });
  expect(run.status).toBe(409);

  // Stop does not cancel accepted orders: that is the separate, tracked workflow.
  expect((await api(ctx, "GET", `/orders/${openId}`)).json.status).toMatch(/acknowledged|partially_filled/);
  await page.getByRole("button", { name: "Cancel open orders…" }).click();
  await page.getByRole("button", { name: "Send cancel requests" }).click();
  await expect.poll(async () => (await api(ctx, "GET", `/orders/${openId}`)).json.status, { timeout: 60_000 }).toMatch(/cancel_requested|filled|cancelled/);

  await page.getByRole("button", { name: "Release stop" }).click();
  await page.getByRole("dialog", { name: "Release the stop?" }).getByRole("button", { name: "Release stop" }).click();
  await maybeConfirmStepUp(page); // step-up may still be fresh from the approvals above
  await expect.poll(async () => (await api(ctx, "GET", "/orders/broker")).json.stop.engaged, { timeout: 15_000 }).toBe(false);
});

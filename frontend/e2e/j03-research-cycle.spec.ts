import { expect, test } from "@playwright/test";
import { api, signIn, waitForDecisionStatus } from "./helpers";

// J3 Deterministic research cycle: question → Mock run → workflow bar → labelled evidence → decision → frozen snapshot.
test("J3 deterministic research cycle ends in a recorded, frozen decision", async ({ page }) => {
  await signIn(page);
  await page.goto("/decisions/new");
  await page.getByLabel("Short title").fill("E2E: add to NVDA?");
  await page.getByLabel("Question").fill("Should I add to NVDA after the data-center growth, given export-restriction risks?");
  await page.locator("label", { hasText: /^NVDA/ }).first().click();
  await page.getByRole("button", { name: "Create and start research" }).click();
  await page.waitForURL(/\/decisions\/[0-9a-f-]{36}$/);
  const id = page.url().split("/").pop()!;

  await expect(page.getByLabel("Workflow status")).toBeVisible();
  await waitForDecisionStatus(page, id, ["ready_for_decision"]);
  await page.reload();
  await expect(page.getByText("Simulated").first()).toBeVisible();
  await expect(page.getByText("Computed").first()).toBeVisible();

  await page.getByRole("tab", { name: "Decide" }).click();
  await page.getByLabel("Decision").selectOption("accept");
  await page.getByLabel("Rationale").fill("Thesis and sizing fit the policy; export risk accepted at this weight.");
  await page.getByRole("button", { name: /Record decision/i }).click();
  await waitForDecisionStatus(page, id, ["decided"], 15_000);

  const ev = await api(page.context(), "GET", `/decisions/${id}/evidence`);
  expect(ev.json.integrity_status).toBe("verified");
  expect(ev.json.verification.ok).toBe(true);
  test.info().annotations.push({ type: "decision", description: id });
});

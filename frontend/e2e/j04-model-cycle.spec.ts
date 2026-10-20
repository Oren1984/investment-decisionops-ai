import { expect, test } from "@playwright/test";
import { api, signIn, waitForDecisionStatus } from "./helpers";

// J4 Model-enabled cycle on the local Ollama model: model-labelled outputs, cancel mid-run, resume without duplicates.
// Takes several minutes on CPU inference. Skipped (and reported as such) when no local model is ready.
test("J4 model-enabled cycle: cancel mid-run, then resume without duplicate steps", async ({ page }) => {
  test.setTimeout(30 * 60_000);
  await signIn(page);
  const agents = await api(page.context(), "GET", "/agents/status?probe=true");
  test.skip(!agents.json.modes.model, `Local model not ready: ${agents.json.model?.reason ?? "unknown"}`);

  await page.goto("/decisions/new");
  await page.getByLabel("Short title").fill("E2E model run: NVDA");
  await page.getByLabel("Question").fill("Should I add to NVDA given export-restriction risks and its valuation?");
  await page.locator("label", { hasText: /^NVDA/ }).first().click();
  await page.getByLabel(/Model-enabled/).check();
  await page.getByRole("button", { name: "Create and start research" }).click();
  await page.waitForURL(/\/decisions\/[0-9a-f-]{36}$/);
  const id = page.url().split("/").pop()!;
  const detail = await api(page.context(), "GET", `/decisions/${id}`);
  const runId: string = detail.json.workflow.run.id;

  // Wait until at least one model step has succeeded and another is running, then cancel from the workspace.
  await expect.poll(async () => {
    const r = (await api(page.context(), "GET", `/runs/${runId}`)).json;
    return r.steps.filter((s: { status: string }) => s.status === "succeeded").length >= 2 && r.status === "running";
  }, { timeout: 10 * 60_000, intervals: [3000] }).toBe(true);
  await page.goto(`/decisions/${id}/runs/${runId}`);
  await page.getByRole("button", { name: "Cancel run" }).click();
  await expect.poll(async () => (await api(page.context(), "GET", `/runs/${runId}`)).json.status, { timeout: 5 * 60_000, intervals: [2000] }).toBe("cancelled");
  const before = (await api(page.context(), "GET", `/runs/${runId}`)).json.steps.filter((s: { status: string }) => s.status === "succeeded").map((s: { step: string }) => s.step);

  await page.reload();
  await page.getByRole("button", { name: "Resume from last completed step" }).click();
  await waitForDecisionStatus(page, id, ["ready_for_decision", "blocked"], 20 * 60_000);
  const run = (await api(page.context(), "GET", `/runs/${runId}`)).json;
  expect(run.status).toBe("succeeded");
  expect(run.model_name).toBeTruthy();
  expect(run.model_digest).toBeTruthy();
  const succeeded: string[] = run.steps.filter((s: { status: string }) => s.status === "succeeded").map((s: { step: string }) => s.step);
  expect(new Set(succeeded).size, "no step succeeded twice").toBe(succeeded.length);
  for (const step of before) expect(succeeded).toContain(step); // completed steps were kept, not re-run
  expect(run.steps.some((s: { output_kind: string; prompt_version: string | null }) => s.output_kind === "model" && s.prompt_version)).toBe(true);

  await page.goto(`/decisions/${id}`);
  await expect(page.getByText("Model-generated").first()).toBeVisible();
});

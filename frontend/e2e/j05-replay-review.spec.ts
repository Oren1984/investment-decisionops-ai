import { expect, test } from "@playwright/test";
import { api, signIn } from "./helpers";

// J5 Replay and review: replay from the frozen snapshot, review assumptions, grade process and outcome separately, lesson.
test("J5 replay a decided decision and record a review with a lesson", async ({ page }) => {
  await signIn(page);
  const list = (await api(page.context(), "GET", "/decisions")).json as { id: string; status: string; title: string }[];
  const decided = list.find((d) => d.status === "decided" && d.title.startsWith("E2E"));
  test.skip(!decided, "Needs the decision recorded in J3");
  await page.goto(`/decisions/${decided!.id}`);

  await page.getByRole("tab", { name: "Replay" }).click();
  await expect(page.getByText(/verified/i).first()).toBeVisible();

  await page.getByRole("tab", { name: "Review & lessons" }).click();
  const review = page.getByRole("tabpanel");
  const held = review.getByRole("combobox", { name: /^Did A\d+ hold\?$/ });
  expect(await held.count()).toBeGreaterThan(0);
  await review.getByRole("textbox", { name: /^Observation for A1$/ }).fill("Data-center growth continued.");
  await held.first().selectOption("yes");
  await review.getByLabel("Return %").fill("4.2");
  await review.getByLabel("Benchmark %").fill("2.1");
  await review.getByLabel("Notes").fill("Process followed the checklist; outcome helped by the market.");
  await review.getByLabel("Lesson", { exact: true }).fill("Size semiconductor adds below the policy cap even when conviction is high.");
  await review.getByRole("button", { name: "Save review" }).click();
  await expect(page.getByText("Size semiconductor adds below the policy cap").first()).toBeVisible();

  const replay = (await api(page.context(), "GET", `/decisions/${decided!.id}/replay`)).json;
  expect(replay.verification.ok).toBe(true);
  const detail = (await api(page.context(), "GET", `/decisions/${decided!.id}`)).json;
  expect(detail.events.some((e: { kind: string }) => /review/.test(e.kind))).toBe(true);
});

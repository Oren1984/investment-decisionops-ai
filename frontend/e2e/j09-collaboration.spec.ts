import { expect, test } from "@playwright/test";
import { randomBytes } from "node:crypto";
import { api, signIn } from "./helpers";

// J9 Broker collaboration: invite → collaborator sets a password → share decision → comment → meeting in both
// timezones with an external Zoom link → revoke → access ends immediately.
test("J9 invite, share, comment, meeting, revoke", async ({ page, browser }) => {
  await signIn(page);
  const email = `broker-${Date.now()}@example.com`;
  await page.goto("/collaboration");
  await page.getByRole("tab", { name: "People" }).click();
  await page.getByLabel("Name").fill("Dana (E2E broker)");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Their timezone").selectOption("Europe/London");
  await page.getByRole("button", { name: "Create invitation link" }).click();
  const link = await page.locator("code", { hasText: "/invite/" }).first().textContent();
  expect(link).toContain("/invite/");

  const collabCtx = await browser.newContext();
  const collab = await collabCtx.newPage();
  await collab.goto(new URL(link!).pathname);
  await collab.getByLabel("Choose a password").fill(`collab-${randomBytes(8).toString("hex")}`);
  await collab.getByRole("button", { name: "Accept invitation" }).click();
  await expect(collab).toHaveURL(/\/shared/);

  const people = (await api(page.context(), "GET", "/people")).json as { id: string; email: string }[];
  const grantee = people.find((p) => p.email === email)!;
  const decision = ((await api(page.context(), "GET", "/decisions")).json as { id: string; title: string }[])[0];
  const share = await api(page.context(), "POST", "/shares", { object_type: "decision", object_id: decision.id, grantee_id: grantee.id, permission: "comment" });
  expect(share.status).toBe(200);

  await collab.goto(`/shared/decision/${decision.id}`);
  await expect(collab.getByText(decision.title).first()).toBeVisible();
  await collab.getByRole("textbox").last().fill("Looks reasonable; watch the export rules.");
  await collab.getByRole("button", { name: "Post" }).click();
  await expect(collab.getByText("Looks reasonable; watch the export rules.")).toBeVisible();

  // Meeting shown in each participant's timezone, with a manual (external) Zoom link.
  const m = await api(page.context(), "POST", "/meetings", {
    title: "E2E broker call", starts_at: "2026-11-02T09:00:00Z", timezone: "Asia/Jerusalem", provider: "manual", link_provider: "zoom",
    join_url: "https://us02web.zoom.us/j/123456789", participants: [{ name: "Dana", timezone: "Europe/London", user_id: grantee.id }],
  });
  expect(m.status).toBe(200);
  await page.goto(`/meetings/${m.json.id}`);
  await expect(page.getByText(/Jerusalem/).first()).toBeVisible();
  await expect(page.getByText(/London/).first()).toBeVisible();
  await expect(page.getByRole("link", { name: /Open meeting in Zoom/ })).toHaveAttribute("href", /zoom\.us/);

  // Revoke the share: the collaborator loses access on the next request.
  await api(page.context(), "DELETE", `/shares/${share.json.id}`);
  const denied = await api(collabCtx, "GET", `/shared/decisions/${decision.id}`);
  expect([403, 404]).toContain(denied.status);
  await collab.reload();
  await expect(collab.getByText(decision.title)).toHaveCount(0);
  await collabCtx.close();
});

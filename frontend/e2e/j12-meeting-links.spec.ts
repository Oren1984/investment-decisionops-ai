import { expect, test } from "@playwright/test";
import { api, signIn } from "./helpers";

// J12 Meeting links (decision D-A): schedule with a Microsoft Teams link → edit to Google Meet (a mismatched and an
// unsafe link are refused) → "Open meeting" opens the link in a new tab without an opener → the demo stays read-only.
// External meeting hosts are intercepted, so no real meeting service is contacted.
const DEMO = { email: process.env.E2E_DEMO_EMAIL ?? "demo@example.com", password: process.env.E2E_DEMO_PASSWORD ?? "demo-read-only" };
const TEAMS = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_e2e%40thread.v2/0";
const MEET = "https://meet.google.com/abc-defg-hij";

test("J12 meeting links: Zoom, Google Meet, Teams and other https links; edit; open in a new tab", async ({ page, context }) => {
  for (const host of ["https://teams.microsoft.com/**", "https://meet.google.com/**"]) {
    await context.route(host, (route) => route.fulfill({ status: 200, contentType: "text/html", body: "<title>meeting</title>external meeting" }));
  }
  await signIn(page);
  await page.goto("/collaboration");
  await page.getByRole("tab", { name: "Meetings" }).click();
  const title = `E2E link meeting ${Date.now()}`;

  await page.getByRole("button", { name: "Schedule meeting" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Title").fill(title);
  await dialog.getByLabel("Meeting type").selectOption("manual");
  await dialog.getByLabel("Meeting provider").selectOption("teams");
  await dialog.getByLabel("Meeting link").fill(TEAMS);
  await dialog.getByRole("button", { name: "Save meeting" }).click();
  await expect(dialog).toHaveCount(0);

  const card = page.locator("section").filter({ has: page.getByRole("heading", { name: title, exact: true }) });
  const teamsLink = card.getByRole("link", { name: /Open meeting in Microsoft Teams/ });
  await expect(teamsLink).toHaveAttribute("href", TEAMS);
  await expect(teamsLink).toHaveAttribute("target", "_blank");
  await expect(teamsLink).toHaveAttribute("rel", /noopener/);

  // Edit: a link that does not match the chosen provider, then an unsafe one, are refused with a clear reason.
  await card.getByRole("button", { name: "Edit meeting" }).click();
  await dialog.getByLabel("Meeting provider").selectOption("google_meet");
  await dialog.getByLabel("Meeting link").fill("https://zoom.us/j/123");
  await dialog.getByRole("button", { name: "Save meeting" }).click();
  await expect(dialog.getByText(/This is not a Google Meet link/)).toBeVisible();
  await dialog.getByLabel("Meeting provider").selectOption("other");
  await dialog.getByLabel("Meeting link").fill("javascript:alert(1)");
  await dialog.getByRole("button", { name: "Save meeting" }).click();
  await expect(dialog.getByText(/Only https meeting links are allowed/)).toBeVisible();
  await dialog.getByLabel("Meeting provider").selectOption("google_meet");
  await dialog.getByLabel("Meeting link").fill(MEET);
  await dialog.getByRole("button", { name: "Save meeting" }).click();
  await expect(dialog).toHaveCount(0);

  const meetLink = card.getByRole("link", { name: /Open meeting in Google Meet/ });
  await expect(meetLink).toHaveAttribute("href", MEET);
  const [popup] = await Promise.all([page.waitForEvent("popup"), meetLink.click()]);
  await popup.waitForLoadState();
  expect(popup.url()).toBe(MEET);
  expect(await popup.evaluate(() => window.opener)).toBeNull(); // noopener: the meeting page cannot reach this app
  await popup.close();

  // The saved link survives a reload and is the same on the companion page.
  const meetings = (await api(context, "GET", "/meetings")).json as { id: string; title: string; join_url: string; link_provider: string }[];
  const saved = meetings.find((m) => m.title === title)!;
  expect([saved.join_url, saved.link_provider]).toEqual([MEET, "google_meet"]);
  await page.goto(`/meetings/${saved.id}`);
  await expect(page.getByRole("link", { name: /Open meeting in Google Meet/ })).toHaveAttribute("href", MEET);
  await api(context, "DELETE", `/meetings/${saved.id}`);
});

test("J12 demo: meeting links are visible but cannot be added or edited", async ({ browser }) => {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto("/demo/");
  await page.getByLabel("Email").fill(DEMO.email);
  await page.getByLabel("Password").fill(DEMO.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("navigation", { name: "Main" }).waitFor();
  await page.goto("/demo/collaboration");
  await page.getByRole("tab", { name: "Meetings" }).click();
  await expect(page.getByRole("link", { name: /Open meeting in Zoom/ }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Schedule meeting" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Edit meeting" })).toHaveCount(0);
  const meetings = (await api(ctx, "GET", "/meetings", undefined, "/demo/api")).json as { id: string }[];
  const put = await api(ctx, "PUT", `/meetings/${meetings[0].id}`, { title: "x", starts_at: "2026-11-02T09:00:00Z", provider: "manual", link_provider: "google_meet", join_url: MEET }, "/demo/api");
  expect(put.status).toBe(403);
  await ctx.close();
});

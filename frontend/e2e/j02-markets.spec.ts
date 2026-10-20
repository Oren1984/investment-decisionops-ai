import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

// J2 Global market check: picking a venue updates the venue clock, session state, countdown and date difference.
test("J2 venue clock, session state and calendar follow the selected venue", async ({ page }) => {
  await signIn(page);
  await page.goto("/markets");
  const clocks = page.getByLabel("Clocks");
  await clocks.getByLabel("Venue").selectOption("XTKS");
  await expect(clocks).toContainText("UTC+9");
  await expect(clocks.getByText(/^(open|closed|break|pre_open|holiday|weekend)$/i).first()).toBeVisible();
  await expect(clocks.getByText(/(Opens|Closes|Resumes|Lunch break) in \d/)).toBeVisible();

  await clocks.getByLabel("Venue").selectOption("XNYS");
  await expect(clocks).toContainText(/UTC-[45]/);
  await expect(page.getByRole("heading", { name: /calendar/i }).first()).toBeVisible();
});

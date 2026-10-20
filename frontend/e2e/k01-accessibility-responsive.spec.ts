import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { api, noHorizontalOverflow, signIn } from "./helpers";

const PAGES = ["/", "/markets", "/portfolio", "/decisions", "/orders", "/collaboration", "/library", "/settings", "/help"];
const VIEWPORTS = [
  { width: 360, height: 780 }, { width: 768, height: 1024 }, { width: 1280, height: 800 }, { width: 1920, height: 1080 },
];

test.describe("accessibility (axe, WCAG 2.1 A/AA)", () => {
  for (const path of [...PAGES, "/decisions/new"]) {
    test(`no serious or critical violations on ${path}`, async ({ page }) => {
      await signIn(page);
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(serious.map((v) => `${v.id}: ${v.help} (${v.nodes.length}) e.g. ${v.nodes[0]?.target.join(" ")}`)).toEqual([]);
    });
  }

  test("sign-in pages and the demo have no serious violations", async ({ page }) => {
    for (const path of ["/", "/demo/"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
      expect(results.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
    }
  });

  test("keyboard: skip link and main navigation are reachable", async ({ page }) => {
    await signIn(page);
    await page.goto("/");
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("#main")).toBeVisible();
  });
});

test.describe("responsive layouts", () => {
  for (const vp of VIEWPORTS) {
    test(`no horizontal overflow at ${vp.width}px`, async ({ page }) => {
      await page.setViewportSize(vp);
      await signIn(page);
      for (const path of PAGES) {
        await page.goto(path);
        await page.waitForLoadState("networkidle");
        await noHorizontalOverflow(page, `${path} @${vp.width}px`);
      }
      if (vp.width < 1024) {
        await page.getByRole("button", { name: "Open navigation" }).click();
        await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
      }
    });
  }
});

test("Help Center: every contextual help link resolves to an article", async ({ page }) => {
  await signIn(page);
  const articles = (await api(page.context(), "GET", "/help")).json as { slug: string }[];
  const slugs = new Set(articles.map((a) => a.slug));
  const seen = new Set<string>();
  for (const path of PAGES) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    for (const href of await page.locator('a[href^="/help/"]').evaluateAll((as) => as.map((a) => a.getAttribute("href")!))) {
      seen.add(href.replace("/help/", "").split("#")[0]);
    }
  }
  expect(seen.size).toBeGreaterThan(3);
  expect([...seen].filter((s) => !slugs.has(s))).toEqual([]);
  await page.goto(`/help/${[...seen][0]}`);
  await expect(page.locator("article, main").first()).toBeVisible();
});

test("charts render with data on the market and portfolio pages", async ({ page }) => {
  await signIn(page);
  await page.goto("/markets");
  await expect(page.locator("canvas").first()).toBeVisible();
  await page.goto("/portfolio");
  await expect(page.locator("svg.recharts-surface, canvas").first()).toBeVisible();
});

// Developer helper: screenshot pages and print console errors. Usage: node e2e/peek.mjs <outdir> <path...>
import { chromium } from "@playwright/test";

const [outDir, ...paths] = process.argv.slice(2);
const base = process.env.BASE_URL ?? "http://127.0.0.1:8087";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("console", (m) => m.type() === "error" && console.log("console error:", m.text()));
page.on("pageerror", (e) => console.log("page error:", e.message));
for (const p of paths) {
  await page.goto(base + p, { waitUntil: "networkidle" });
  await page.waitForTimeout(800);
  const file = `${outDir}/${p.replace(/[^a-z0-9]+/gi, "_") || "root"}.png`;
  await page.screenshot({ path: file, fullPage: true });
  console.log("shot", p, "->", file);
}
await browser.close();

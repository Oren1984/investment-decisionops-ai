import { expect, test } from "@playwright/test";
import { api, signIn } from "./helpers";

// J6 Knowledge: upload → ingestion → ask → cited passages → delete (choice 1, effects shown) → retrieval excludes it.
test("J6 upload, cited answer, remove from library, then no longer retrieved", async ({ page }) => {
  await signIn(page);
  await page.goto("/library");
  const word = `Quorvex${Date.now().toString(36)}`;
  await page.locator("#upload").setInputFiles({
    name: `${word}-note.md`, mimeType: "text/markdown",
    buffer: Buffer.from(`# ${word} supplier note\n\n## Contract\n\nThe ${word} supply contract covers advanced packaging capacity through 2028. It reduces the risk of shortages for accelerator production.\n`),
  });
  const row = page.getByRole("row", { name: new RegExp(word) });
  await expect(row).toContainText("ready", { timeout: 60_000 });

  await page.getByLabel("Question").fill(`What does the ${word} supply contract cover?`);
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByText(/advanced packaging capacity/).first()).toBeVisible();
  await expect(page.getByText("Evidence checks")).toBeVisible();
  await expect(page.getByText(`${word}-note (§ Contract)`).first()).toBeVisible(); // citation: document and section

  await row.getByRole("button", { name: "Delete…" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(/Affected decisions/).first()).toBeVisible();
  await expect(dialog.getByText(/Backups clear after about/)).toBeVisible();
  await dialog.getByRole("button", { name: "Remove from Library" }).click();
  await expect(page.getByRole("row", { name: new RegExp(word) })).toHaveCount(0);

  const after = await api(page.context(), "GET", `/library/ask?q=${encodeURIComponent(`${word} supply contract`)}`);
  const hits = after.json.retrieval.hits as { text: string; document_title: string }[];
  expect(hits.filter((h) => h.text.includes(word) || h.document_title.includes(word))).toEqual([]); // removed doc never retrieved
});

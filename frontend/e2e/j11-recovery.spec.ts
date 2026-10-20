import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { api, maybeConfirmStepUp, ownerCreds, signIn, stepUpViaApi, totp, updateOwnerCreds } from "./helpers";

// J11 Recovery: TOTP with recovery codes, and the owner CLI password reset inside the container.
test("J11 TOTP sign-in, recovery code, and CLI password reset", async ({ page, browser }) => {
  await signIn(page);
  if (ownerCreds().totpSecret) { // re-run on the same stack: start from TOTP off
    await stepUpViaApi(page);
    expect((await api(page.context(), "POST", "/auth/totp/disable")).status).toBe(200);
    updateOwnerCreds({ totpSecret: undefined });
  }
  await page.goto("/settings");
  await page.getByRole("button", { name: "Set up authenticator app" }).click();
  await maybeConfirmStepUp(page);
  const secret = (await page.locator("code").filter({ hasText: /^[A-Z2-7]{16,}$/ }).first().textContent())!.trim();
  await page.getByLabel("Authenticator code").fill(totp(secret));
  await page.getByRole("button", { name: "Verify and enable" }).click();
  await expect(page.getByText("Recovery codes (shown once)")).toBeVisible();
  const codes = await page.locator("ul.font-mono li").allTextContents();
  expect(codes.length).toBeGreaterThanOrEqual(8);
  updateOwnerCreds({ totpSecret: secret });
  const { email, password } = ownerCreds();

  const fresh = await browser.newContext();
  const noCode = await api(fresh, "POST", "/auth/login", { email, password });
  expect(noCode.json.code).toBe("totp_required");
  expect((await api(fresh, "POST", "/auth/login", { email, password, totp_code: totp(secret) })).status).toBe(200);
  const recovery = await browser.newContext();
  expect((await api(recovery, "POST", "/auth/login", { email, password, recovery_code: codes[0] })).status).toBe(200);
  const reused = await browser.newContext();
  expect((await api(reused, "POST", "/auth/login", { email, password, recovery_code: codes[0] })).status).toBe(401); // one use

  // Owner CLI reset inside the API container of the isolated stack (prints a one-time password; never logged here).
  const project = process.env.E2E_COMPOSE_PROJECT ?? "decisionops-e2e";
  const out = execFileSync("docker", ["compose", "-p", project, "exec", "-T", "api", "python", "-m", "app.cli", "reset-owner-password"], { encoding: "utf-8" });
  const newPassword = out.match(/Temporary password for \S+: (\S+)/)?.[1];
  expect(newPassword, "CLI prints a temporary password").toBeTruthy();
  const afterReset = await browser.newContext();
  expect((await api(afterReset, "POST", "/auth/login", { email, password })).status).toBe(401); // old password gone
  // The reset changes the password only; the authenticator stays required.
  expect((await api(afterReset, "POST", "/auth/login", { email, password: newPassword })).json.code).toBe("totp_required");
  expect((await api(afterReset, "POST", "/auth/login", { email, password: newPassword, totp_code: totp(secret) })).status).toBe(200);
  updateOwnerCreds({ password: newPassword! });
  for (const c of [fresh, recovery, reused, afterReset]) await c.close();
});

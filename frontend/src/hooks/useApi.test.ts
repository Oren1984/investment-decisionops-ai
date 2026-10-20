import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, post } from "../api/client";
import { useStepUp } from "../store/ui";
import { mockFetch } from "../test-utils";
import { withStepUp } from "./useApi";

afterEach(() => vi.unstubAllGlobals());

describe("withStepUp", () => {
  it("asks for step-up once and retries the action after confirmation", async () => {
    let attempts = 0;
    const action = vi.fn(async () => {
      attempts += 1;
      if (attempts === 1) throw new ApiError(401, "step_up_required", "Confirm it's you");
      return "done";
    });
    const pending = withStepUp(action);
    await vi.waitFor(() => expect(useStepUp.getState().open).toBe(true));
    useStepUp.getState().finish(true);
    await expect(pending).resolves.toBe("done");
    expect(action).toHaveBeenCalledTimes(2);
  });

  it("does not retry when the owner cancels, and passes other errors through", async () => {
    const action = vi.fn(async () => {
      throw new ApiError(401, "step_up_required", "Confirm it's you");
    });
    const pending = withStepUp(action);
    await vi.waitFor(() => expect(useStepUp.getState().open).toBe(true));
    useStepUp.getState().finish(false);
    await expect(pending).rejects.toMatchObject({ code: "step_up_required" });
    expect(action).toHaveBeenCalledTimes(1);
    await expect(withStepUp(async () => { throw new ApiError(409, "stop_engaged", "Stop"); })).rejects.toMatchObject({ code: "stop_engaged" });
  });
});

describe("api client", () => {
  it("sends the CSRF token on writes and maps errors to actionable messages", async () => {
    document.cookie = "dops_csrf=tok123";
    const calls = mockFetch([
      { method: "POST", path: "/api/orders/o1/submit", status: 409, body: { code: "approval_expired", message: "The approval expired.", help_slug: "approvals-and-stop" } },
    ]);
    const err = await post("/orders/o1/submit").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 409, code: "approval_expired", helpSlug: "approvals-and-stop" });
    expect(calls[0].headers["X-CSRF-Token"]).toBe("tok123");
  });

  it("reports an unreachable server as a network error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(post("/anything")).rejects.toMatchObject({ code: "network_error", status: 0 });
  });
});

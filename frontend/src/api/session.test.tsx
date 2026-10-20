import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { clearClientSession, signOut } from "./session";
import type { AuthStatus } from "./types";
import { mockFetch } from "../test-utils";

const signedIn: AuthStatus = { profile: "owner", setup_required: false, authenticated: true, user: { id: "u1", email: "o@example.com", display_name: "Owner", role: "owner" } as AuthStatus["user"] };

function Gate() {
  // Same key and staleTime as App's useAuth: nothing refetches it on its own during the test.
  const auth = useQuery<AuthStatus>({ queryKey: ["auth"], queryFn: async () => signedIn, staleTime: 60_000 });
  return <p>{auth.data?.authenticated ? "private workspace" : "sign-in screen"}</p>;
}

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["auth"], signedIn);
  qc.setQueryData(["portfolio"], { total: 952_322 });
  render(
    <QueryClientProvider client={qc}>
      <Gate />
    </QueryClientProvider>,
  );
  return qc;
}

describe("sign-out", () => {
  it("switches a mounted app to the sign-in screen and drops private cached data", async () => {
    const qc = setup();
    expect(screen.getByText("private workspace")).toBeTruthy();
    await act(() => clearClientSession(qc));
    expect(await screen.findByText("sign-in screen")).toBeTruthy();
    expect(qc.getQueryData(["portfolio"])).toBeUndefined();
  });

  it("calls the logout endpoint and clears the client even if the request fails", async () => {
    const calls = mockFetch([{ method: "POST", path: "/api/auth/logout", status: 500, body: { code: "x", message: "down" } }]);
    const qc = setup();
    await act(() => signOut(qc).catch(() => undefined));
    expect(calls.map((c) => `${c.method} ${c.url}`)).toContain("POST /api/auth/logout");
    expect(await screen.findByText("sign-in screen")).toBeTruthy();
  });
});

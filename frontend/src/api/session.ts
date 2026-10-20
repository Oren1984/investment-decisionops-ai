import type { QueryClient } from "@tanstack/react-query";
import { isDemo, post } from "./client";
import type { AuthStatus } from "./types";

/**
 * Drops every cached server response and marks the client signed out. App renders the sign-in screen from the
 * ["auth"] entry, so it is overwritten rather than removed: removing it (qc.clear()) left the mounted App holding
 * the old "authenticated" result until a manual reload.
 */
export async function clearClientSession(qc: QueryClient) {
  await qc.cancelQueries();
  const prev = qc.getQueryData<AuthStatus>(["auth"]);
  qc.setQueryData<AuthStatus>(["auth"], {
    profile: prev?.profile ?? (isDemo ? "demo" : "owner"),
    setup_required: false,
    authenticated: false,
    user: null,
  });
  qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
}

/** Ends the server session (owner, collaborator or demo), then clears the client even if the request failed. */
export async function signOut(qc: QueryClient) {
  try {
    await post("/auth/logout");
  } finally {
    await clearClientSession(qc);
  }
}

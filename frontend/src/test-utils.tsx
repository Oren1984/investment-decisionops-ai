import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

export function renderWithProviders(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

type Route = { method?: string; path: string; status?: number; body: unknown };

/** Minimal fetch fake: matches by method + path suffix and records every call. */
export function mockFetch(routes: Route[]) {
  const calls: { method: string; url: string; body: unknown; headers: Record<string, string> }[] = [];
  const fn = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    calls.push({ method, url, body: init.body ? JSON.parse(String(init.body)) : undefined, headers: (init.headers ?? {}) as Record<string, string> });
    const r = routes.find((x) => (x.method ?? "GET") === method && url.endsWith(x.path));
    if (!r) return new Response(JSON.stringify({ code: "not_found", message: "no route" }), { status: 404 });
    return new Response(JSON.stringify(r.body), { status: r.status ?? 200 });
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

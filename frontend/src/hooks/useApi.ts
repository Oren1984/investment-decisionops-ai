import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from "@tanstack/react-query";
import { ApiError, api, get } from "../api/client";
import { useStepUp } from "../store/ui";

export function useApi<T>(key: unknown[], path: string | null, options: Partial<UseQueryOptions<T, ApiError>> = {}) {
  return useQuery<T, ApiError>({
    queryKey: key,
    queryFn: ({ signal }) => get<T>(path as string, signal),
    enabled: path !== null && (options.enabled ?? true),
    ...options,
  });
}

/** Runs an action; if the backend requires step-up authentication, asks for it and retries once. */
export async function withStepUp<T>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn();
  } catch (e) {
    if (e instanceof ApiError && e.code === "step_up_required") {
      const ok = await useStepUp.getState().request();
      if (ok) return fn();
    }
    throw e;
  }
}

export function useAction<TBody = unknown, TResult = unknown>(
  method: "POST" | "PUT" | "PATCH" | "DELETE",
  path: string | ((body: TBody) => string),
  opts: { invalidate?: unknown[][]; stepUp?: boolean; onSuccess?: (r: TResult) => void } = {},
) {
  const qc = useQueryClient();
  return useMutation<TResult, ApiError, TBody>({
    mutationFn: (body: TBody) => {
      const url = typeof path === "function" ? path(body) : path;
      const call = () => api<TResult>(url, { method, body: method === "DELETE" ? undefined : (body ?? {}) });
      return opts.stepUp ? withStepUp(call) : call();
    },
    onSuccess: (r) => {
      for (const k of opts.invalidate ?? []) qc.invalidateQueries({ queryKey: k });
      opts.onSuccess?.(r);
    },
  });
}

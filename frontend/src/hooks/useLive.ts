import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { apiBase, get } from "../api/client";

/** Server-Sent Events → query invalidation. Access is re-checked server-side on every event. */
export function useLiveUpdates(enabled: boolean) {
  const qc = useQueryClient();
  const pending = useRef<number | null>(null);
  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;
    const es = new EventSource(`${apiBase}/events`, { withCredentials: true });
    const flush = () => {
      pending.current = null;
      qc.invalidateQueries();
    };
    es.addEventListener("change", () => {
      if (pending.current === null) pending.current = window.setTimeout(flush, 400);
    });
    // The server ends the stream when the session behind it ends. That also happens after step-up and password
    // changes, which rotate the session: the browser then reconnects by itself with the new cookie (retry: 5 s).
    // If the user is really signed out, the reconnect gets 401 and EventSource stops; the auth refetch shows sign-in.
    es.addEventListener("session_ended", () => {
      qc.invalidateQueries({ queryKey: ["auth"] });
    });
    return () => {
      es.close();
      if (pending.current !== null) window.clearTimeout(pending.current);
    };
  }, [enabled, qc]);
}

/** Server-time offset so countdowns use the server clock, not the browser's. */
let offsetMs = 0;
export function serverNow(): Date {
  return new Date(Date.now() + offsetMs);
}

export function useServerClock(tickMs = 1000): Date {
  const [now, setNow] = useState(serverNow());
  useEffect(() => {
    let cancelled = false;
    const sync = async () => {
      try {
        const started = Date.now();
        const t = await get<{ epoch_ms: number }>("/time");
        const rtt = Date.now() - started;
        if (!cancelled) offsetMs = t.epoch_ms + rtt / 2 - Date.now();
      } catch {
        /* keep last offset */
      }
    };
    sync();
    const s = window.setInterval(sync, 5 * 60 * 1000);
    const t = window.setInterval(() => setNow(serverNow()), tickMs);
    return () => {
      cancelled = true;
      window.clearInterval(s);
      window.clearInterval(t);
    };
  }, [tickMs]);
  return now;
}

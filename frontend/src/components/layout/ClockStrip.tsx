import type { Me, Venue, VenueState } from "../../api/types";
import { useApi } from "../../hooks/useApi";
import { useServerClock } from "../../hooks/useLive";
import { dayDifference, fmtClock, fmtDay, fmtDuration, utcOffsetLabel } from "../../lib/format";
import { useUi } from "../../store/ui";
import { Badge, HelpLink } from "../ui";

const EVENT_LABEL: Record<string, string> = { opens: "Opens in", closes: "Closes in", resumes: "Resumes in", break_starts: "Lunch break in" };

/** Home clock | selected venue clock | session state + countdown | date difference. Informational only. */
export function ClockStrip({ compact }: { compact?: boolean }) {
  const now = useServerClock(1000);
  const { venue, setVenue } = useUi();
  const me = useApi<{ user: Me | null }>(["auth"], "/auth/status");
  const venues = useApi<Venue[]>(["venues"], "/markets/venues", { staleTime: Infinity });
  const state = useApi<VenueState>(["venue-state", venue], `/calendar/venues/${venue}/state`, { refetchInterval: 60_000 });
  const home = state.data?.home_timezone ?? me.data?.user?.timezone ?? "Asia/Jerusalem";
  const v = venues.data?.find((x) => x.mic === venue);
  const venueZone = v?.timezone ?? "America/New_York";
  const diff = dayDifference(now, home, venueZone);
  const next = state.data?.next_event;
  const remaining = next ? (new Date(next.at).getTime() - now.getTime()) / 1000 : null;

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-line/60 px-3 py-1.5 text-xs md:px-4" aria-label="Clocks">
      <div className="flex items-baseline gap-1.5">
        <span className="text-muted">Home</span>
        <span className="num font-medium">{fmtClock(now, home)}</span>
        <span className="text-muted">
          {fmtDay(now, home)} · {home.split("/").pop()?.replace("_", " ")} {utcOffsetLabel(now, home)}
        </span>
      </div>
      {!compact && (
        <>
          <div className="flex items-center gap-1.5">
            <label htmlFor="venue-select" className="text-muted">
              Venue
            </label>
            <select id="venue-select" value={venue} onChange={(e) => setVenue(e.target.value)} className="rounded border border-line bg-surface-2 px-1.5 py-0.5 text-xs">
              {(venues.data ?? []).map((x) => (
                <option key={x.mic} value={x.mic}>
                  {x.short} ({x.mic})
                </option>
              ))}
            </select>
            <span className="num font-medium">{fmtClock(now, venueZone)}</span>
            <span className="text-muted">
              {fmtDay(now, venueZone)} · {utcOffsetLabel(now, venueZone)}
            </span>
            {diff !== 0 && <Badge tone="accent" title="Calendar date at the venue compared with home">{diff > 0 ? `+${diff} day` : `${diff} day`}</Badge>}
          </div>
          {state.data && (
            <div className="flex items-center gap-1.5">
              <Badge tone={state.data.state === "open" ? "good" : state.data.state === "break" ? "warn" : "neutral"}>{state.data.state}</Badge>
              {state.data.reason && <span className="text-muted">{state.data.reason}</span>}
              {next && remaining !== null && (
                <span className="num">
                  {EVENT_LABEL[next.kind] ?? next.kind} {fmtDuration(remaining)}
                </span>
              )}
              <HelpLink slug="clocks-and-calendars" />
            </div>
          )}
        </>
      )}
    </div>
  );
}

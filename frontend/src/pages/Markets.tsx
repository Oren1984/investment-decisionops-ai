import { useState } from "react";
import type { Body } from "../api/contract";
import { isDemo } from "../api/client";
import type { Feed, Instrument, Venue, VenueState } from "../api/types";
import { PriceChart } from "../components/charts/PriceChart";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, KeyValue, Loading, Notice, PageHeader, Select, StatusBadge, Table, Td, Th, TextField } from "../components/ui";
import { useAction, useApi } from "../hooks/useApi";
import { useServerClock } from "../hooks/useLive";
import { fmtAgo, fmtDuration, fmtNum, fmtPct, fmtTime } from "../lib/format";
import { useUi } from "../store/ui";

type SessionRow = { date: string; open: { utc: string; local: string }; close: { utc: string; local: string }; break_start: { local: string } | null; break_end: { local: string } | null; early_close: boolean };
type EventItem = { id: string; kind: string; title: string; starts_at: string; ends_at?: string | null; source: string; source_name?: string; venue_mic?: string; all_day?: boolean };
type Timer = { id: string; label: string; started_at: string; ends_at: string; duration_minutes: number; stopped_at: string | null; note: string };
type Watchlist = { id: string; name: string; instrument_ids: string[] };

export default function Markets() {
  const { venue, setVenue } = useUi();
  const venues = useApi<Venue[]>(["venues"], "/markets/venues", { staleTime: Infinity });
  const v = venues.data?.find((x) => x.mic === venue);
  return (
    <>
      <PageHeader title="Markets and calendar" subtitle="Exchange-correct clocks, sessions, holidays and synthetic quotes. Pick a venue, not a country." help="clocks-and-calendars" />
      <div className="mb-4 flex flex-wrap gap-1.5" role="tablist" aria-label="Venues">
        {(venues.data ?? []).map((x) => (
          <button key={x.mic} role="tab" aria-selected={x.mic === venue} onClick={() => setVenue(x.mic)} className={`rounded-md border px-3 py-1.5 text-sm ${x.mic === venue ? "border-accent bg-accent/10" : "border-line text-muted hover:text-fg"}`}>
            {x.short} <span className="text-xs text-muted">{x.mic}</span>
          </button>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="flex flex-col gap-4 xl:col-span-2">
          {v && <VenueCard venue={v} />}
          <InstrumentsCard venue={venue} />
          <CalendarCard venue={venue} />
        </div>
        <div className="flex flex-col gap-4">
          <ResearchTimerCard />
          <FeedsCard />
          <MatrixCard venues={venues.data ?? []} />
        </div>
      </div>
    </>
  );
}

function VenueCard({ venue }: { venue: Venue }) {
  const now = useServerClock(1000);
  const state = useApi<VenueState>(["venue-state", venue.mic], `/calendar/venues/${venue.mic}/state`, { refetchInterval: 30_000 });
  const today = new Date();
  const start = today.toISOString().slice(0, 10);
  const end = new Date(today.getTime() + 14 * 86400_000).toISOString().slice(0, 10);
  const sessions = useApi<{ sessions: SessionRow[]; holidays: { date: string; name: string }[]; source: { version: string; note: string } }>(
    ["sessions", venue.mic, start], `/calendar/venues/${venue.mic}/sessions?start=${start}&end=${end}`,
  );
  const s = state.data;
  const remaining = s?.next_event ? (new Date(s.next_event.at).getTime() - now.getTime()) / 1000 : null;
  return (
    <Card title={`${venue.name} (${venue.mic})`} id="venue" actions={s && <StatusBadge status={s.state === "open" ? "fresh" : s.state === "break" ? "stale" : "neutral"} label={s.state} />}>
      {state.isLoading && <Loading />}
      <ErrorState error={state.error} />
      {s && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <KeyValue
            items={[
              ["Local time", <span className="num">{new Intl.DateTimeFormat("en-GB", { timeZone: venue.timezone, dateStyle: "medium", timeStyle: "medium" }).format(now)}</span>],
              ["Timezone", `${venue.timezone} (UTC${s.utc_offset_minutes >= 0 ? "+" : ""}${(s.utc_offset_minutes / 60).toString()})`],
              ["Date vs home", s.date_difference_days === 0 ? "Same calendar day" : `${s.date_difference_days > 0 ? "+" : ""}${s.date_difference_days} day vs ${s.home_timezone}`],
              ["State", <span>{s.state}{s.reason ? ` — ${s.reason}` : ""}</span>],
              ["Next", s.next_event && remaining !== null ? <span className="num">{s.next_event.kind.replace("_", " ")} in {fmtDuration(remaining)} ({fmtTime(s.next_event.at, venue.timezone)} local)</span> : "—"],
              ["Today", s.today ? `${s.today.open.local}–${s.today.close.local}${s.today.break_start ? ` · break ${s.today.break_start.local}–${s.today.break_end?.local}` : ""}${s.today.early_close ? " · shortened" : ""}` : "No session today"],
              ["Execution", venue.execution_scope],
            ]}
          />
          <div>
            <p className="mb-1.5 text-xs font-medium text-muted">Next sessions (venue local time)</p>
            {sessions.isLoading && <Loading />}
            <ul className="num flex flex-col gap-0.5 text-sm">
              {(sessions.data?.sessions ?? []).slice(0, 8).map((x) => (
                <li key={x.date} className="flex justify-between gap-2">
                  <span>{x.date}</span>
                  <span>
                    {x.open.local}–{x.close.local}
                    {x.break_start ? ` (break ${x.break_start.local}–${x.break_end?.local})` : ""}
                    {x.early_close ? " · shortened" : ""}
                  </span>
                </li>
              ))}
            </ul>
            {(sessions.data?.holidays ?? []).length > 0 && (
              <p className="mt-2 text-xs text-warn">Holidays: {sessions.data!.holidays.map((h) => `${h.date} ${h.name}`).join("; ")}</p>
            )}
            {sessions.data && <p className="mt-2 text-[11px] text-muted">Computed offline from exchange_calendars {sessions.data.source.version}. {sessions.data.source.note}</p>}
          </div>
        </div>
      )}
    </Card>
  );
}

function InstrumentsCard({ venue }: { venue: string }) {
  const quotes = useApi<Instrument[]>(["quotes"], "/markets/quotes", { refetchInterval: 60_000 });
  const lists = useApi<Watchlist[]>(["watchlists"], "/markets/watchlists");
  const rows = (quotes.data ?? []).filter((i) => i.venue_mic === venue);
  const [chartId, setChartId] = useState<string | null>(null);
  const selected = chartId ?? rows[0]?.id ?? null;
  const hist = useApi<{ bars: { time: string; open: number; high: number; low: number; close: number }[]; instrument: Instrument; label: string }>(
    ["history", selected], selected ? `/markets/instruments/${selected}/history?days=120` : null,
  );
  const wl = lists.data?.[0];
  const update = useAction<Body<"WatchlistIn">>("PUT", `/markets/watchlists/${wl?.id}`, { invalidate: [["watchlists"]] });
  const toggle = (id: string) => {
    if (!wl) return;
    const ids = wl.instrument_ids.includes(id) ? wl.instrument_ids.filter((x) => x !== id) : [...wl.instrument_ids, id];
    update.mutate({ name: wl.name, instrument_ids: ids });
  };
  return (
    <Card title="Instruments" id="instruments" help="markets-and-venues">
      {quotes.isLoading && <Loading />}
      {quotes.data && rows.length === 0 && <EmptyState title="No instruments for this venue" />}
      {rows.length > 0 && (
        <Table caption="Instruments and synthetic quotes">
          <thead>
            <tr>
              <Th>Symbol</Th>
              <Th>Name</Th>
              <Th right>Price</Th>
              <Th right>Change</Th>
              <Th>Data</Th>
              <Th>Tradable</Th>
              <Th>Watch</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((i) => (
              <tr key={i.id} className={i.id === selected ? "bg-surface-2" : ""}>
                <Td>
                  <button className="font-medium text-accent hover:underline" onClick={() => setChartId(i.id)}>
                    {i.symbol}
                  </button>
                </Td>
                <Td>{i.name}</Td>
                <Td right>
                  {fmtNum(i.quote?.price, i.kind === "fx" ? 4 : 2)} <span className="text-xs text-muted">{i.currency}</span>
                </Td>
                <Td right className={(i.quote?.change_pct ?? 0) >= 0 ? "text-good" : "text-bad"}>
                  {fmtPct(i.quote?.change_pct)}
                </Td>
                <Td>
                  <Badge tone={i.quote?.freshness === "fresh" ? "simulated" : "bad"} title={`As of ${fmtTime(i.quote?.as_of)}`}>
                    {i.quote?.freshness === "fresh" ? `${i.quote.label} · ${fmtAgo(i.quote.as_of)}` : `Stale · ${fmtAgo(i.quote?.as_of)}`}
                  </Badge>
                </Td>
                <Td>{i.tradable ? <Badge tone="good">Tradable</Badge> : <Badge title={i.not_tradable_reason ?? ""}>{i.kind === "index" ? "Reference index" : "Reference only"}</Badge>}</Td>
                <Td>
                  <button disabled={isDemo || !wl} aria-pressed={wl?.instrument_ids.includes(i.id)} onClick={() => toggle(i.id)} className="text-accent disabled:opacity-40" aria-label={`Toggle ${i.symbol} on watchlist`}>
                    {wl?.instrument_ids.includes(i.id) ? "★" : "☆"}
                  </button>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {rows.some((r) => !r.tradable) && <p className="mt-2 text-xs text-muted">Hover a “Reference” badge to see why it cannot be traded through the first broker.</p>}
      {hist.data && (
        <div className="mt-4">
          <PriceChart bars={hist.data.bars} symbol={hist.data.instrument.symbol} label={hist.data.label} height={240} />
        </div>
      )}
    </Card>
  );
}

function CalendarCard({ venue }: { venue: string }) {
  const [start] = useState(() => new Date());
  const end = new Date(start.getTime() + 14 * 86400_000);
  const q = useApi<EventItem[]>(["calendar", venue], `/calendar/events?start=${start.toISOString()}&end=${end.toISOString()}&venues=${venue}`);
  const [form, setForm] = useState<{ title: string; when: string; kind: Body<"EventIn">["kind"] }>({ title: "", when: "", kind: "reminder" });
  const add = useAction<Body<"EventIn">>("POST", "/calendar/events", { invalidate: [["calendar"], ["events-upcoming"]], onSuccess: () => setForm({ title: "", when: "", kind: "reminder" }) });
  const items = (q.data ?? []).filter((e) => e.kind !== "session" || e.venue_mic === venue).slice(0, 40);
  return (
    <Card title="Calendar (next 14 days)" id="calendar" help="clocks-and-calendars">
      <div className="mb-3 flex flex-wrap gap-2 text-xs">
        <Badge tone="computed">Computed: exchange sessions/holidays</Badge>
        <Badge>You: user-entered</Badge>
        <Badge tone="warn">Mock: synthetic events</Badge>
        <Badge tone="accent">External: confirmed feed (none configured)</Badge>
      </div>
      {q.isLoading && <Loading />}
      <ErrorState error={q.error} />
      <ul className="flex max-h-80 flex-col gap-1 overflow-y-auto text-sm" tabIndex={0} aria-label="Upcoming calendar events">
        {items.map((e) => (
          <li key={e.id} className="flex items-center justify-between gap-2 border-b border-line/40 py-1">
            <span className="flex min-w-0 items-center gap-2">
              <Badge tone={e.kind === "holiday" ? "warn" : e.kind === "meeting" ? "accent" : "neutral"}>{e.kind}</Badge>
              <span className="truncate">{e.title}</span>
            </span>
            <span className="flex shrink-0 items-center gap-2">
              <span className="num text-xs text-muted">{e.all_day ? e.starts_at : fmtTime(e.starts_at)}</span>
              <Badge tone={e.source === "computed" ? "computed" : e.source === "mock" ? "warn" : "neutral"} title={e.source_name}>
                {e.source === "user" ? "You" : e.source}
              </Badge>
            </span>
          </li>
        ))}
      </ul>
      {!isDemo && (
        <form
          className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1fr)_190px_130px_auto]"
          onSubmit={(e) => {
            e.preventDefault();
            if (!form.title || !form.when) return;
            add.mutate({ kind: form.kind, title: form.title, starts_at: new Date(form.when).toISOString(), timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });
          }}
        >
          <Input aria-label="Event title" placeholder="Add a reminder or economic event" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <Input aria-label="Date and time" type="datetime-local" value={form.when} onChange={(e) => setForm({ ...form, when: e.target.value })} />
          <Select aria-label="Kind" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as Body<"EventIn">["kind"] })}>
            <option value="reminder">Reminder</option>
            <option value="economic">Economic event</option>
            <option value="research_cycle">Research cycle</option>
          </Select>
          <Button type="submit" busy={add.isPending}>
            Add
          </Button>
        </form>
      )}
      {add.error && <p className="mt-1 text-xs text-bad">{add.error.message}</p>}
    </Card>
  );
}

function ResearchTimerCard() {
  const now = useServerClock(1000);
  const timers = useApi<Timer[]>(["timers"], "/timers");
  const [label, setLabel] = useState("Research cycle");
  const [minutes, setMinutes] = useState("45");
  const start = useAction<Body<"TimerIn">>("POST", "/timers", { invalidate: [["timers"]] });
  const stop = useAction<{ id: string }>("POST", (b) => `/timers/${b.id}/stop`, { invalidate: [["timers"]] });
  const active = (timers.data ?? []).find((t) => !t.stopped_at && new Date(t.ends_at) > now);
  return (
    <Card title="Research timer" id="timer" help="clocks-and-calendars">
      <Notice>Informational only. A timer or countdown never authorizes or submits an order.</Notice>
      {active ? (
        <div className="mt-3 flex items-center justify-between gap-2">
          <div>
            <p className="text-sm">{active.label}</p>
            <p className="num text-2xl font-semibold">{fmtDuration((new Date(active.ends_at).getTime() - now.getTime()) / 1000)}</p>
          </div>
          {!isDemo && (
            <Button size="sm" onClick={() => stop.mutate({ id: active.id })}>
              Stop
            </Button>
          )}
        </div>
      ) : (
        !isDemo && (
          <form
            className="mt-3 flex flex-col gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              start.mutate({ label, duration_minutes: Number(minutes) });
            }}
          >
            <TextField label="Label" value={label} onChange={(e) => setLabel(e.target.value)} />
            <Field label="Minutes" htmlFor="tmin">
              <Input id="tmin" type="number" min={1} max={1440} value={minutes} onChange={(e) => setMinutes(e.target.value)} />
            </Field>
            <Button type="submit" variant="primary" busy={start.isPending}>
              Start timer
            </Button>
          </form>
        )
      )}
    </Card>
  );
}

function FeedsCard() {
  const q = useApi<Feed[]>(["feeds"], "/markets/feeds", { refetchInterval: 30_000 });
  const label: Record<string, string> = { fresh: "Fresh", stale: "Stale", not_configured: "Not configured", error: "Error" };
  return (
    <Card title="Data feeds" id="feeds" help="alert-stale-feed">
      <ul className="flex flex-col gap-2 text-sm">
        {(q.data ?? []).map((f) => (
          <li key={f.key} className="flex flex-col gap-0.5">
            <span className="flex items-center justify-between gap-2">
              <span>{f.name}</span>
              <StatusBadge status={f.state} label={label[f.state]} />
            </span>
            <span className="text-xs text-muted">
              {f.state === "stale" ? `Stale since ${fmtTime(f.stale_since)} — last data kept and labelled; retrying.` : f.state === "not_configured" ? String(f.meta?.note ?? "Not configured.") : `Last update ${fmtAgo(f.last_success_at)}`}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function MatrixCard({ venues }: { venues: Venue[] }) {
  return (
    <Card title="Supported-market matrix" id="matrix" help="markets-and-venues">
      <ul className="flex flex-col gap-2 text-sm">
        {venues.map((v) => (
          <li key={v.mic}>
            <span className="font-medium">
              {v.short} ({v.mic})
            </span>{" "}
            <span className="text-xs text-muted">
              {v.timezone}
              {v.has_lunch_break ? " · lunch break" : ""}
            </span>
            <p className="text-xs text-muted">{v.execution_scope}</p>
          </li>
        ))}
      </ul>
    </Card>
  );
}

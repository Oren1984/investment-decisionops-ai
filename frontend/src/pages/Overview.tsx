import { useState } from "react";
import { Link } from "react-router-dom";
import type { DecisionSummary, Instrument, Order, Portfolio, Run } from "../api/types";
import { ExposureChart } from "../components/charts/ExposureChart";
import { PriceChart } from "../components/charts/PriceChart";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, PageHeader, Stat, StatusBadge } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { fmtAgo, fmtMoney, fmtNum, fmtPct, fmtTime } from "../lib/format";

type Watchlist = { id: string; name: string; instrument_ids: string[] };
type EventItem = { id: string; kind: string; title: string; starts_at: string; source: string; source_name?: string; venue_mic?: string };
type AlertRow = { id: string; kind: string; severity: string; message: string; help_slug: string };

export default function Overview() {
  return (
    <>
      <PageHeader title="Overview" subtitle="Portfolio context, markets, agent activity and what needs your attention." help="getting-started" />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="flex flex-col gap-4 xl:col-span-2">
          <PortfolioCard />
          <ChartCard />
        </div>
        <div className="flex flex-col gap-4">
          <AttentionCard />
          <WatchlistCard />
        </div>
        <DecisionsCard />
        <AgentActivityCard />
        <UpcomingCard />
      </div>
    </>
  );
}

function PortfolioCard() {
  const q = useApi<Portfolio>(["portfolio"], "/portfolio", { refetchInterval: 60_000 });
  return (
    <Card title="Portfolio" actions={q.data && <Badge tone="simulated">{q.data.label}</Badge>} help="portfolio-and-exposure" id="ov-portfolio">
      {q.isLoading && <Loading />}
      <ErrorState error={q.error} retry={() => q.refetch()} />
      {q.data && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
          <div className="flex flex-col gap-3">
            <Stat label={`Total value (${q.data.home_currency})`} value={fmtMoney(q.data.total_home, q.data.home_currency)} sub={`As of ${fmtTime(q.data.as_of)}${q.data.fx_as_of ? ` · FX ${fmtTime(q.data.fx_as_of)}` : ""}`} />
            <Stat label="Positions" value={q.data.positions.filter((p) => p.kind === "position").length} sub={`+ ${q.data.manual_holdings.length} manual holding(s)`} />
            <Link to="/portfolio" className="text-sm text-accent hover:underline">
              Open portfolio →
            </Link>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <ExposureChart data={q.data.exposure.currency} currency={q.data.home_currency} title="Exposure by currency" />
            <ExposureChart data={q.data.exposure.asset_class} currency={q.data.home_currency} title="Exposure by asset class" />
          </div>
        </div>
      )}
    </Card>
  );
}

function ChartCard() {
  const lists = useApi<Watchlist[]>(["watchlists"], "/markets/watchlists");
  const quotes = useApi<Instrument[]>(["quotes"], "/markets/quotes", { refetchInterval: 60_000 });
  const [picked, setPicked] = useState<string | null>(null);
  const first = lists.data?.[0]?.instrument_ids?.[0];
  const id = picked ?? first ?? quotes.data?.find((i) => i.symbol === "SPY")?.id ?? null;
  const hist = useApi<{ bars: { time: string; open: number; high: number; low: number; close: number }[]; instrument: Instrument; label: string }>(
    ["history", id], id ? `/markets/instruments/${id}/history?days=180` : null,
  );
  const options = (lists.data?.[0]?.instrument_ids ?? []).map((iid) => quotes.data?.find((q) => q.id === iid)).filter(Boolean) as Instrument[];
  return (
    <Card
      title="Market chart"
      id="ov-chart"
      actions={
        <select aria-label="Instrument" className="rounded border border-line bg-surface-2 px-1.5 py-0.5 text-xs" value={id ?? ""} onChange={(e) => setPicked(e.target.value)}>
          {options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.symbol}
            </option>
          ))}
        </select>
      }
    >
      {hist.isLoading && <Loading />}
      <ErrorState error={hist.error} />
      {hist.data && <PriceChart bars={hist.data.bars} symbol={hist.data.instrument.symbol} label={hist.data.label} />}
    </Card>
  );
}

function WatchlistCard() {
  const lists = useApi<Watchlist[]>(["watchlists"], "/markets/watchlists");
  const quotes = useApi<Instrument[]>(["quotes"], "/markets/quotes", { refetchInterval: 60_000 });
  const ids = lists.data?.[0]?.instrument_ids ?? [];
  const rows = ids.map((id) => quotes.data?.find((q) => q.id === id)).filter(Boolean) as Instrument[];
  return (
    <Card title={lists.data?.[0]?.name ?? "Watchlist"} id="ov-watch" help="markets-and-venues">
      {(lists.isLoading || quotes.isLoading) && <Loading />}
      {lists.data && rows.length === 0 && <EmptyState title="No instruments on your watchlist">Add some on the Markets page.</EmptyState>}
      <ul className="flex flex-col divide-y divide-line/60">
        {rows.map((i) => (
          <li key={i.id} className="flex items-center justify-between gap-2 py-1.5 text-sm">
            <span className="flex min-w-0 items-center gap-2">
              <span className="font-medium">{i.symbol}</span>
              <span className="truncate text-xs text-muted">{i.venue_mic}</span>
              {!i.tradable && <Badge title={i.not_tradable_reason ?? ""}>{i.kind === "index" ? "Index" : "Ref"}</Badge>}
            </span>
            <span className="flex items-center gap-2">
              <span className="num">{fmtNum(i.quote?.price, i.kind === "fx" ? 4 : 2)}</span>
              <span className={`num w-16 text-right text-xs ${(i.quote?.change_pct ?? 0) >= 0 ? "text-good" : "text-bad"}`}>{fmtPct(i.quote?.change_pct)}</span>
              <Badge tone={i.quote?.freshness === "fresh" ? "simulated" : "bad"} title={`As of ${fmtTime(i.quote?.as_of)}`}>
                {i.quote?.freshness === "fresh" ? i.quote.label : "stale"}
              </Badge>
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function DecisionsCard() {
  const q = useApi<DecisionSummary[]>(["decisions"], "/decisions");
  const counts: Record<string, number> = {};
  for (const d of q.data ?? []) counts[d.status_label] = (counts[d.status_label] ?? 0) + 1;
  return (
    <Card title="Decisions" id="ov-decisions" actions={<Link to="/decisions/new"><Button size="sm" variant="primary">New question</Button></Link>}>
      {q.isLoading && <Loading />}
      {q.data && q.data.length === 0 && <EmptyState title="No decisions yet" action={<Link className="text-sm text-accent" to="/decisions/new">Ask your first question →</Link>} />}
      <div className="mb-3 flex flex-wrap gap-1.5">
        {Object.entries(counts).map(([k, n]) => (
          <Badge key={k}>
            {k}: {n}
          </Badge>
        ))}
      </div>
      <ul className="flex flex-col gap-1.5">
        {(q.data ?? []).slice(0, 5).map((d) => (
          <li key={d.id} className="flex items-center justify-between gap-2 text-sm">
            <Link to={`/decisions/${d.id}`} className="truncate hover:underline">
              {d.title}
            </Link>
            <span className="flex shrink-0 items-center gap-1.5">
              {d.checks && <span className="num text-xs text-muted">{d.checks.passed}/{d.checks.total} checks</span>}
              <StatusBadge status={d.status} label={d.status_label} />
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function AgentActivityCard() {
  const q = useApi<(Run & { decision_title: string })[]>(["runs-recent"], "/runs/recent", { refetchInterval: 15_000 });
  return (
    <Card title="Agent activity" id="ov-agents" help="agents-and-labels">
      {q.isLoading && <Loading />}
      {q.data && q.data.length === 0 && <EmptyState title="No runs yet">Runs start when you ask a question.</EmptyState>}
      <ul className="flex flex-col gap-1.5">
        {(q.data ?? []).map((r) => (
          <li key={r.id} className="flex items-center justify-between gap-2 text-sm">
            <Link to={`/decisions/${r.decision_id}/runs/${r.id}`} className="truncate hover:underline">
              {r.decision_title}
            </Link>
            <span className="flex shrink-0 items-center gap-1.5">
              <Badge tone={r.mode === "model" ? "model" : "computed"}>{r.mode}</Badge>
              <StatusBadge status={r.status} />
              <span className="text-xs text-muted">{fmtAgo(r.created_at)}</span>
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function UpcomingCard() {
  const start = new Date();
  const end = new Date(start.getTime() + 7 * 86400_000);
  const q = useApi<EventItem[]>(["events-upcoming"], `/calendar/events?start=${start.toISOString()}&end=${end.toISOString()}&venues=XNYS,XTAE`);
  const items = (q.data ?? []).filter((e) => e.kind !== "session").slice(0, 8);
  return (
    <Card title="Upcoming events (7 days)" id="ov-events" help="clocks-and-calendars">
      {q.isLoading && <Loading />}
      {q.data && items.length === 0 && <EmptyState title="Nothing scheduled" />}
      <ul className="flex flex-col gap-1.5">
        {items.map((e) => (
          <li key={e.id} className="flex items-center justify-between gap-2 text-sm">
            <span className="truncate">{e.title}</span>
            <span className="flex shrink-0 items-center gap-1.5">
              <span className="text-xs text-muted">{e.kind === "holiday" ? e.starts_at : fmtTime(e.starts_at)}</span>
              <Badge tone={e.source === "mock" ? "warn" : e.source === "computed" ? "computed" : "neutral"}>{e.source === "user" ? "You" : e.source}</Badge>
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function AttentionCard() {
  const orders = useApi<Order[]>(["orders"], "/orders", { refetchInterval: 15_000 });
  const alerts = useApi<AlertRow[]>(["alerts"], "/ops/alerts", { refetchInterval: 30_000 });
  const open = (orders.data ?? []).filter((o) => ["acknowledged", "partially_filled", "uncertain", "reconciling", "cancel_requested", "approved", "pending_approval"].includes(o.status));
  return (
    <Card title="Needs attention" id="ov-attention" help="orders-and-reconciliation">
      {(alerts.data ?? []).length === 0 && open.length === 0 && <p className="text-sm text-muted">No open orders or alerts.</p>}
      <ul className="flex flex-col gap-1.5">
        {(alerts.data ?? []).slice(0, 4).map((a) => (
          <li key={a.id} className="flex items-start justify-between gap-2 text-sm">
            <span className={a.severity === "critical" ? "text-bad" : "text-warn"}>{a.message}</span>
            <Link className="shrink-0 text-xs text-accent hover:underline" to={`/help/${a.help_slug}`}>
              Fix
            </Link>
          </li>
        ))}
        {open.slice(0, 5).map((o) => (
          <li key={o.id} className="flex items-center justify-between gap-2 text-sm">
            <Link to={`/orders/${o.id}`} className="truncate hover:underline">
              {o.side.toUpperCase()} {o.quantity} {o.instrument.symbol}
            </Link>
            <StatusBadge status={o.status} />
          </li>
        ))}
      </ul>
    </Card>
  );
}

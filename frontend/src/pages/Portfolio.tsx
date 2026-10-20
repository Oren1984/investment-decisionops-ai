import { useState } from "react";
import type { Body } from "../api/contract";
import { isDemo } from "../api/client";
import type { Portfolio, PortfolioRow } from "../api/types";
import { ExposureChart } from "../components/charts/ExposureChart";
import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Loading, PageHeader, Select, Stat, Table, Td, TextField, Th, Field } from "../components/ui";
import { useAction, useApi } from "../hooks/useApi";
import { fmtMoney, fmtNum, fmtPct, fmtTime } from "../lib/format";

export default function PortfolioPage() {
  const q = useApi<Portfolio>(["portfolio"], "/portfolio", { refetchInterval: 60_000 });
  const [editing, setEditing] = useState<PortfolioRow | "new" | null>(null);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  const p = q.data!;
  const positions = p.positions.filter((r) => r.kind === "position");
  const cash = p.positions.filter((r) => r.kind === "cash");
  return (
    <>
      <PageHeader
        title="Portfolio"
        subtitle={`${p.mode.toUpperCase()} mode · values in ${p.home_currency} · as of ${fmtTime(p.as_of)}${p.fx_as_of ? ` · FX as of ${fmtTime(p.fx_as_of)}` : ""}`}
        help="portfolio-and-exposure"
        actions={<Badge tone="simulated">{p.label}</Badge>}
      />
      <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Card>
          <Stat label="Total value" value={fmtMoney(p.total_home, p.home_currency)} />
        </Card>
        <Card>
          <Stat label="Broker positions" value={positions.length} sub={`${cash.length} cash balance(s)`} />
        </Card>
        <Card>
          <Stat label="Manual holdings" value={p.manual_holdings.length} sub="Assets held outside the broker" />
        </Card>
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="flex flex-col gap-4 xl:col-span-2">
          <Card title="Positions" id="positions" actions={<Badge tone="simulated">{p.label}</Badge>}>
            {positions.length === 0 ? (
              <EmptyState title="No positions" />
            ) : (
              <Table caption="Positions">
                <thead>
                  <tr>
                    <Th>Symbol</Th>
                    <Th>Venue</Th>
                    <Th right>Qty</Th>
                    <Th right>Avg cost</Th>
                    <Th right>Price</Th>
                    <Th right>Unrealized</Th>
                    <Th right>Value ({p.home_currency})</Th>
                    <Th right>Weight</Th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((r) => (
                    <tr key={r.instrument_id}>
                      <Td>
                        <span className="font-medium">{r.symbol}</span>
                        <span className="block text-xs text-muted">{r.name}</span>
                      </Td>
                      <Td>{r.venue_mic}</Td>
                      <Td right>{fmtNum(r.quantity, 0)}</Td>
                      <Td right>
                        {fmtNum(r.avg_cost)} <span className="text-xs text-muted">{r.currency}</span>
                      </Td>
                      <Td right>
                        {fmtNum(r.price)}
                        {r.quote?.freshness === "stale" && <Badge tone="bad" className="ml-1">stale</Badge>}
                      </Td>
                      <Td right className={(r.unrealized_pct ?? 0) >= 0 ? "text-good" : "text-bad"}>
                        {fmtPct(r.unrealized_pct)}
                      </Td>
                      <Td right>{fmtMoney(r.value_home)}</Td>
                      <Td right>{fmtNum(r.weight_pct, 1)}%</Td>
                    </tr>
                  ))}
                  {cash.map((r) => (
                    <tr key={r.symbol}>
                      <Td>
                        <span className="font-medium">{r.name}</span>
                      </Td>
                      <Td>—</Td>
                      <Td right />
                      <Td right />
                      <Td right />
                      <Td right />
                      <Td right>{fmtMoney(r.value_home)}</Td>
                      <Td right>{fmtNum(r.weight_pct, 1)}%</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
          <Card
            title="Manual holdings"
            id="manual"
            help="portfolio-and-exposure"
            actions={!isDemo && <Button size="sm" onClick={() => setEditing("new")}>Add holding</Button>}
          >
            <p className="mb-3 text-xs text-muted">Labelled “Manual”: for example TASE shares at an Israeli bank (outside the first broker's scope). You enter the value; it is not live data.</p>
            {p.manual_holdings.length === 0 ? (
              <EmptyState title="No manual holdings" />
            ) : (
              <Table caption="Manual holdings">
                <thead>
                  <tr>
                    <Th>Name</Th>
                    <Th>Venue</Th>
                    <Th right>Qty</Th>
                    <Th right>Unit value</Th>
                    <Th right>Value ({p.home_currency})</Th>
                    <Th>Value as of</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {p.manual_holdings.map((r) => (
                    <tr key={r.id}>
                      <Td>
                        {r.name} <Badge>Manual</Badge>
                      </Td>
                      <Td>{r.venue_mic ?? "—"}</Td>
                      <Td right>{fmtNum(r.quantity, 0)}</Td>
                      <Td right>
                        {fmtNum(r.unit_value)} {r.currency}
                      </Td>
                      <Td right>{fmtMoney(r.value_home)}</Td>
                      <Td>{fmtTime(r.value_as_of)}</Td>
                      <Td>
                        {!isDemo && (
                          <Button size="sm" variant="ghost" onClick={() => setEditing(r)}>
                            Edit
                          </Button>
                        )}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </div>
        <div className="flex flex-col gap-4">
          <Card title="Exposure" id="exposure">
            <div className="flex flex-col gap-4">
              <ExposureChart data={p.exposure.asset_class} currency={p.home_currency} title="By asset class" />
              <ExposureChart data={p.exposure.currency} currency={p.home_currency} title="By currency" />
              <ExposureChart data={p.exposure.venue} currency={p.home_currency} title="By venue" />
            </div>
          </Card>
        </div>
      </div>
      {editing && <ManualDialog row={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function ManualDialog({ row, onClose }: { row: PortfolioRow | null; onClose: () => void }) {
  const [f, setF] = useState({
    name: row?.name ?? "", symbol: row?.symbol && row.symbol !== row.name ? row.symbol : "", venue_mic: row?.venue_mic ?? "XTAE",
    asset_class: row?.asset_class ?? "equity", currency: row?.currency ?? "ILS", quantity: String(row?.quantity ?? ""),
    unit_value: String(row?.unit_value ?? ""), notes: row?.notes ?? "",
  });
  const save = useAction<Body<"ManualIn">>(row ? "PUT" : "POST", row ? `/portfolio/manual-holdings/${row.id}` : "/portfolio/manual-holdings", {
    invalidate: [["portfolio"]], onSuccess: onClose,
  });
  const remove = useAction("DELETE", `/portfolio/manual-holdings/${row?.id}`, { invalidate: [["portfolio"]], onSuccess: onClose });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={row ? "Edit manual holding" : "Add manual holding"} description="Values you enter are labelled Manual and are never treated as live market data.">
      <form
        className="grid grid-cols-1 gap-3 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate({ ...f, symbol: f.symbol || null, quantity: Number(f.quantity), unit_value: Number(f.unit_value), notes: f.notes || null });
        }}
      >
        <div className="sm:col-span-2">
          <TextField label="Name" value={f.name} onChange={set("name")} required />
        </div>
        <TextField label="Symbol (optional)" value={f.symbol} onChange={set("symbol")} />
        <TextField label="Venue MIC (optional)" value={f.venue_mic} onChange={set("venue_mic")} />
        <Field label="Asset class" htmlFor="ac">
          <Select id="ac" value={f.asset_class} onChange={set("asset_class")}>
            {["equity", "fund", "bond", "cash", "other"].map((x) => (
              <option key={x}>{x}</option>
            ))}
          </Select>
        </Field>
        <TextField label="Currency" value={f.currency} onChange={set("currency")} maxLength={3} required />
        <TextField label="Quantity" type="number" step="any" value={f.quantity} onChange={set("quantity")} required />
        <TextField label="Unit value" type="number" step="any" value={f.unit_value} onChange={set("unit_value")} required />
        <div className="sm:col-span-2">
          <TextField label="Notes" value={f.notes} onChange={set("notes")} />
        </div>
        {(save.error || remove.error) && <p className="text-sm text-bad sm:col-span-2">{(save.error ?? remove.error)!.message}</p>}
        <div className="flex justify-between gap-2 sm:col-span-2">
          {row ? (
            <Button type="button" variant="danger" busy={remove.isPending} onClick={() => remove.mutate(undefined)}>
              Delete
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" busy={save.isPending}>
              Save
            </Button>
          </div>
        </div>
      </form>
    </Dialog>
  );
}

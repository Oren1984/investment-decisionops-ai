import { useState } from "react";
import type { Body } from "../api/contract";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { isDemo, post } from "../api/client";
import type { BrokerInfo, DecisionSummary, Instrument, Order } from "../api/types";
import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Field, Input, Loading, Notice, PageHeader, Select, StatusBadge, Table, Td, Th } from "../components/ui";
import { useAction, useApi, withStepUp } from "../hooks/useApi";
import { fmtNum, fmtTime } from "../lib/format";
import type { ApiError } from "../api/client";

type Recon = { id: string; trigger: string; started_at: string; checked: number; changed: number; mismatches: number; details: { order_id: string; from: string; to: string; mismatch: string | null }[] };

export default function Orders() {
  const [params, setParams] = useSearchParams();
  const broker = useApi<BrokerInfo>(["broker"], "/orders/broker", { refetchInterval: 15_000 });
  const orders = useApi<Order[]>(["orders"], "/orders", { refetchInterval: 4000 });
  const recon = useApi<Recon[]>(["recon"], "/orders/reconcile/history", { refetchInterval: 15_000 });
  const reconcile = useAction("POST", "/orders/reconcile/run", { invalidate: [["orders"], ["recon"]] });
  const cancelOpen = useAction("POST", "/orders/cancel-open", { invalidate: [["orders"]] });
  const [confirmCancelAll, setConfirmCancelAll] = useState(false);
  const newOpen = params.get("new") === "1";
  const b = broker.data;
  return (
    <>
      <PageHeader
        title="Broker and orders"
        subtitle="Preview → payload-bound approval (step-up, 5-minute expiry) → controlled submission → reconciliation with broker state."
        help="approvals-and-stop"
        actions={
          !isDemo && (
            <Button variant="primary" onClick={() => setParams({ new: "1" })}>
              New order ticket
            </Button>
          )
        }
      />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="flex flex-col gap-4 xl:col-span-2">
          <Card title="Orders" id="orders" help="orders-and-reconciliation">
            {orders.isLoading && <Loading />}
            <ErrorState error={orders.error} />
            {orders.data?.length === 0 && <EmptyState title="No orders in this mode yet">Create a ticket to preview an order. Nothing is sent without your approval.</EmptyState>}
            {(orders.data ?? []).length > 0 && (
              <Table caption="Orders">
                <thead>
                  <tr>
                    <Th>Order</Th>
                    <Th>Type</Th>
                    <Th right>Filled</Th>
                    <Th>Status</Th>
                    <Th>Scenario</Th>
                    <Th>Updated</Th>
                  </tr>
                </thead>
                <tbody>
                  {orders.data!.map((o) => (
                    <tr key={o.id}>
                      <Td>
                        <Link to={`/orders/${o.id}`} className="font-medium hover:underline">
                          {o.side.toUpperCase()} {fmtNum(o.quantity, 0)} {o.instrument.symbol}
                        </Link>
                        <span className="block text-[11px] text-muted">{o.client_order_id}</span>
                      </Td>
                      <Td>
                        {o.order_type}
                        {o.limit_price ? ` @ ${fmtNum(o.limit_price)}` : ""} · {o.tif}
                      </Td>
                      <Td right>
                        {fmtNum(o.filled_quantity, 0)}/{fmtNum(o.quantity, 0)}
                      </Td>
                      <Td>
                        <StatusBadge status={o.status} />
                      </Td>
                      <Td>{o.mock_scenario ? <Badge tone="simulated">{o.mock_scenario.replace(/_/g, " ")}</Badge> : "—"}</Td>
                      <Td>{fmtTime(o.updated_at)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
          <Card title="Reconciliation" id="recon" help="orders-and-reconciliation" actions={!isDemo && <Button size="sm" busy={reconcile.isPending} onClick={() => reconcile.mutate(undefined)}>Reconcile now</Button>}>
            <p className="mb-2 text-xs text-muted">Runs every 30 s and on demand. The broker is the source of truth for fills; uncertain submissions are resolved here before any retry.</p>
            <ul className="flex flex-col gap-2 text-sm">
              {(recon.data ?? []).slice(0, 8).map((r) => (
                <li key={r.id} className="rounded border border-line p-2">
                  <p className="text-xs text-muted">
                    {fmtTime(r.started_at)} · {r.trigger} · checked {r.checked} · changed {r.changed}
                    {r.mismatches ? <span className="text-bad"> · {r.mismatches} mismatch(es)</span> : null}
                  </p>
                  {r.details.map((d, i) => (
                    <p key={i} className="text-xs">
                      <Link to={`/orders/${d.order_id}`} className="hover:underline">
                        {d.from} → {d.to}
                      </Link>
                      {d.mismatch && <span className="text-bad"> — {d.mismatch}</span>}
                    </p>
                  ))}
                </li>
              ))}
              {recon.data?.length === 0 && <li className="text-muted">No changes recorded yet.</li>}
            </ul>
          </Card>
        </div>
        <div className="flex flex-col gap-4">
          <Card title="Broker connection" id="broker" help="ibkr-setup">
            {b && (
              <div className="flex flex-col gap-2 text-sm">
                <p className="flex items-center gap-2">
                  <Badge tone={b.mode === "mock" ? "warn" : "accent"}>{b.mode}</Badge>
                  <StatusBadge status={b.connection.status} />
                </p>
                <p className="text-muted">{b.connection.detail}</p>
                {b.mode === "mock" && <Notice tone="warn">Mock mode: a simulated broker. Success here never counts as verification of a real broker.</Notice>}
                <p className="text-xs text-muted">{b.live.message}</p>
              </div>
            )}
          </Card>
          <Card title="Stop and cancellation" id="stop" help="approvals-and-stop">
            <p className="text-sm">
              Stop is <strong>{b?.stop.engaged ? "ENGAGED" : "released"}</strong>
              {b?.stop.engaged && b.stop.reason ? ` (${b.stop.reason})` : ""}. Use the Stop button in the header.
            </p>
            <p className="mt-1 text-xs text-muted">Stop blocks new submissions and agent runs. It does not reverse fills or cancel accepted orders.</p>
            {!isDemo && (
              <Button className="mt-3" size="sm" variant="danger" onClick={() => setConfirmCancelAll(true)}>
                Cancel open orders…
              </Button>
            )}
            {cancelOpen.data != null && <p className="mt-2 text-xs text-muted">Cancel requests sent; follow each order's status (tracked).</p>}
          </Card>
          {b?.mode === "mock" && (
            <Card title="Mock scenarios" id="scenarios" help="orders-and-reconciliation">
              <ul className="flex flex-col gap-1.5 text-sm">
                {Object.entries(b.scenarios).map(([k, v]) => (
                  <li key={k}>
                    <Badge tone="simulated">{k.replace(/_/g, " ")}</Badge> <span className="text-xs text-muted">{v}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
      {newOpen && <NewTicketDialog onClose={() => setParams({})} broker={b} />}
      <Dialog open={confirmCancelAll} onOpenChange={setConfirmCancelAll} title="Cancel all open orders?" description="Sends a tracked cancel request for every acknowledged or partially filled order in this mode. Some may fill before the cancel arrives.">
        <div className="flex justify-end gap-2">
          <Button onClick={() => setConfirmCancelAll(false)}>Keep them</Button>
          <Button variant="danger" busy={cancelOpen.isPending} onClick={() => cancelOpen.mutate(undefined, { onSuccess: () => setConfirmCancelAll(false) })}>
            Send cancel requests
          </Button>
        </div>
      </Dialog>
    </>
  );
}

function NewTicketDialog({ onClose, broker }: { onClose: () => void; broker?: BrokerInfo }) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const instruments = useApi<Instrument[]>(["quotes"], "/markets/quotes");
  const decisions = useApi<DecisionSummary[]>(["decisions"], "/decisions");
  const tradable = (instruments.data ?? []).filter((i) => i.tradable);
  const presetSymbol = params.get("symbol");
  const [f, setF] = useState({
    instrument_id: "", side: params.get("side") ?? "buy", quantity: "10", order_type: "limit", limit_price: "", stop_price: "", tif: "DAY",
    decision_id: params.get("decision") ?? "", mock_scenario: "success",
  });
  const instrumentId = f.instrument_id || tradable.find((i) => i.symbol === presetSymbol)?.id || tradable[0]?.id || "";
  const inst = tradable.find((i) => i.id === instrumentId);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      type T = Body<"TicketIn">;
      const body: T = {
        instrument_id: instrumentId, side: f.side as T["side"], quantity: Number(f.quantity), order_type: f.order_type as T["order_type"], tif: f.tif as T["tif"],
        limit_price: ["limit", "stop_limit"].includes(f.order_type) ? Number(f.limit_price || inst?.quote?.price) : null,
        stop_price: ["stop", "stop_limit"].includes(f.order_type) ? Number(f.stop_price) : null,
        decision_id: f.decision_id || null, mock_scenario: broker?.mode === "mock" ? (f.mock_scenario as T["mock_scenario"]) : null,
      };
      const t = await withStepUp(() => post<Order>("/orders", body));
      navigate(`/orders/${t.id}`);
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title="New order ticket" description="Creating a ticket sends nothing. You will see a full preview before approving." wide>
      <form
        className="grid grid-cols-1 gap-3 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <Field label="Instrument (tradable in this scope)" htmlFor="inst">
          <Select id="inst" value={instrumentId} onChange={set("instrument_id")}>
            {tradable.map((i) => (
              <option key={i.id} value={i.id}>
                {i.symbol} — {i.name} ({i.venue_mic}) · last {fmtNum(i.quote?.price, i.kind === "fx" ? 4 : 2)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Side" htmlFor="side">
          <Select id="side" value={f.side} onChange={set("side")}>
            <option value="buy">Buy</option>
            <option value="sell">Sell (long-only: up to what you hold)</option>
          </Select>
        </Field>
        <Field label="Quantity" htmlFor="qty">
          <Input id="qty" type="number" min="0" step="any" value={f.quantity} onChange={set("quantity")} />
        </Field>
        <Field label="Order type" htmlFor="ot">
          <Select id="ot" value={f.order_type} onChange={set("order_type")}>
            <option value="limit">Limit</option>
            <option value="market">Market</option>
            <option value="stop">Stop</option>
            <option value="stop_limit">Stop-limit</option>
          </Select>
        </Field>
        {["limit", "stop_limit"].includes(f.order_type) && (
          <Field label="Limit price" htmlFor="lp" hint={inst?.quote?.price ? `Last synthetic quote: ${fmtNum(inst.quote.price)}` : undefined}>
            <Input id="lp" type="number" step="any" placeholder={String(inst?.quote?.price ?? "")} value={f.limit_price} onChange={set("limit_price")} />
          </Field>
        )}
        {["stop", "stop_limit"].includes(f.order_type) && (
          <Field label="Stop price" htmlFor="sp">
            <Input id="sp" type="number" step="any" value={f.stop_price} onChange={set("stop_price")} />
          </Field>
        )}
        <Field label="Time in force" htmlFor="tif">
          <Select id="tif" value={f.tif} onChange={set("tif")}>
            <option value="DAY">DAY</option>
            <option value="GTC">GTC</option>
          </Select>
        </Field>
        <Field label="Linked decision (optional)" htmlFor="dec">
          <Select id="dec" value={f.decision_id} onChange={set("decision_id")}>
            <option value="">None</option>
            {(decisions.data ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.title}
              </option>
            ))}
          </Select>
        </Field>
        {broker?.mode === "mock" && (
          <Field label="Mock scenario (simulation only)" htmlFor="scn">
            <Select id="scn" value={f.mock_scenario} onChange={set("mock_scenario")}>
              {Object.keys(broker.scenarios).map((k) => (
                <option key={k} value={k}>
                  {k.replace(/_/g, " ")}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <div className="sm:col-span-2">
          <ErrorState error={error} />
        </div>
        <div className="flex justify-end gap-2 sm:col-span-2">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" busy={busy}>
            Create ticket
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

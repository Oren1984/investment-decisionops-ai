import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { isDemo, post } from "../api/client";
import type { Order, OrderPreview } from "../api/types";
import { Badge, Button, Card, ErrorState, KeyValue, Loading, Notice, PageHeader, StatusBadge } from "../components/ui";
import { useApi, withStepUp } from "../hooks/useApi";
import { useServerClock } from "../hooks/useLive";
import { fmtDuration, fmtMoney, fmtNum, fmtTime } from "../lib/format";
import { useQueryClient } from "@tanstack/react-query";
import type { ApiError } from "../api/client";

export default function OrderDetail() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const now = useServerClock(1000);
  const q = useApi<Order>(["order", id], `/orders/${id}`, { refetchInterval: 3000 });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [note, setNote] = useState<string | null>(null);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const o = q.data!;
  const p = o.preview;

  const act = async (name: string, path: string, stepUp = false) => {
    setBusy(name);
    setError(null);
    setNote(null);
    try {
      const call = () => post<Order>(`/orders/${id}/${path}`);
      const res = stepUp ? await withStepUp(call) : await call();
      if (res?.duplicate) setNote(res.note ?? "Duplicate request: the existing order was returned.");
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setBusy(null);
      qc.invalidateQueries({ queryKey: ["order", id] });
      qc.invalidateQueries({ queryKey: ["orders"] });
    }
  };
  const expiresIn = o.approval?.status === "active" ? (new Date(o.approval.expires_at).getTime() - now.getTime()) / 1000 : null;
  const canPreview = ["draft", "previewed", "expired", "blocked", "invalidated", "pending_approval"].includes(o.status);
  const canApprove = ["previewed", "pending_approval"].includes(o.status) && p?.all_checks_passed;
  const canSubmit = o.status === "approved";
  const canCancel = ["draft", "previewed", "pending_approval", "approved", "acknowledged", "partially_filled", "invalidated", "expired", "blocked"].includes(o.status);

  return (
    <>
      <PageHeader
        title={`${o.side.toUpperCase()} ${fmtNum(o.quantity, 0)} ${o.instrument.symbol}`}
        subtitle={
          <span>
            {o.client_order_id} · {o.mode.toUpperCase()} · {o.broker} · account {o.account_id}
            {o.decision_id && (
              <>
                {" · "}
                <Link to={`/decisions/${o.decision_id}`} className="text-accent hover:underline">
                  linked decision
                </Link>
              </>
            )}
          </span>
        }
        help="approvals-and-stop"
        actions={
          <>
            <StatusBadge status={o.status} />
            {o.mock_scenario && <Badge tone="simulated">Scenario: {o.mock_scenario.replace(/_/g, " ")}</Badge>}
          </>
        }
      />
      {o.status === "uncertain" || o.status === "reconciling" ? (
        <div className="mb-4">
          <Notice tone="warn" title="Outcome uncertain">
            The broker did not confirm this submission. It will not be retried until reconciliation (by order reference) resolves it. If confirmed not found after the grace period, you may resubmit explicitly.
          </Notice>
        </div>
      ) : null}
      {o.status === "submitting" && (
        <div className="mb-4">
          <Notice tone="accent">Submitting… A fill is never assumed from submission; fills come only from broker execution reports.</Notice>
        </div>
      )}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="flex flex-col gap-4 xl:col-span-2">
          <Card title="Order preview" help="approvals-and-stop" actions={p && <Badge tone={p.label === "Simulated" ? "simulated" : "accent"}>{p.label}</Badge>}>
            {!p && <p className="text-sm text-muted">No preview yet. Preview checks limits, data freshness, session state and estimated costs.</p>}
            {p && <OrderPreviewView p={p} />}
            {!isDemo && (
              <div className="mt-4 flex flex-wrap gap-2 border-t border-line pt-3">
                {canPreview && (
                  <Button busy={busy === "preview"} onClick={() => act("preview", "preview")}>
                    {p ? "Preview again" : "Preview"}
                  </Button>
                )}
                {canApprove && (
                  <Button variant="primary" busy={busy === "approve"} onClick={() => act("approve", "approve", true)}>
                    Approve this exact order
                  </Button>
                )}
                {canSubmit && (
                  <Button variant="primary" busy={busy === "submit"} onClick={() => act("submit", "submit")}>
                    Submit to broker
                  </Button>
                )}
                {canCancel && (
                  <Button variant="danger" busy={busy === "cancel"} onClick={() => act("cancel", "cancel")}>
                    {["acknowledged", "partially_filled"].includes(o.status) ? "Request cancel" : "Discard ticket"}
                  </Button>
                )}
                {o.status === "not_found" && (
                  <Button busy={busy === "resubmit"} onClick={() => act("resubmit", "resubmit")}>
                    Prepare resubmission (new order ID)
                  </Button>
                )}
              </div>
            )}
            {o.approval && (
              <p className="mt-2 text-xs text-muted">
                Approval {o.approval.status}
                {expiresIn !== null && expiresIn > 0 ? ` · expires in ${fmtDuration(expiresIn)}` : ""}
                {expiresIn !== null && expiresIn <= 0 ? " · expired (submission will be refused)" : ""} · bound to payload {o.approval.payload_hash.slice(0, 12)}… Any material edit invalidates it.
              </p>
            )}
            {note && <p className="mt-2 text-sm text-warn">{note}</p>}
            <div className="mt-2">
              <ErrorState error={error} />
            </div>
          </Card>
          <Card title="Executions" help="orders-and-reconciliation">
            <ul className="text-sm">
              {(o.executions ?? []).map((x) => (
                <li key={x.exec_id} className="num flex justify-between border-b border-line/50 py-1">
                  <span>{fmtTime(x.at, undefined, { second: "2-digit" })}</span>
                  <span>
                    {fmtNum(x.quantity, 0)} @ {fmtNum(x.price)} {x.commission != null && <span className="text-xs text-muted">fee {fmtNum(x.commission)}</span>}
                  </span>
                </li>
              ))}
              {(o.executions ?? []).length === 0 && <li className="text-muted">No executions. Fills appear only from broker execution reports.</li>}
            </ul>
            <p className="mt-2 text-xs text-muted">
              Filled {fmtNum(o.filled_quantity, 0)} of {fmtNum(o.quantity, 0)}
              {o.avg_fill_price ? ` · average ${fmtNum(o.avg_fill_price)}` : ""}
            </p>
          </Card>
        </div>
        <Card title="Order events">
          <ol className="flex flex-col gap-2 border-l border-line pl-3 text-sm">
            {(o.events ?? []).map((e, i) => (
              <li key={i}>
                <span className="text-xs text-muted">{fmtTime(e.at, undefined, { second: "2-digit" })}</span> <StatusBadge status={e.to} />
                <p className="text-xs">{e.message}</p>
              </li>
            ))}
          </ol>
        </Card>
      </div>
    </>
  );
}

/** What the owner approves: the exact payload, costs (or UNKNOWN), freshness, session and every limit check. */
export function OrderPreviewView({ p }: { p: OrderPreview }) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <KeyValue
        items={[
          ["Mode / broker", `${p.mode.toUpperCase()} · ${p.broker} · ${p.account_id}`],
          ["Instrument", `${p.instrument.symbol} — ${p.instrument.name}`],
          ["Identifier / venue", `${p.instrument.broker_instrument_id ?? "(assigned by broker)"} · ${p.instrument.venue_mic}`],
          ["Currency", p.currency],
          ["Side / quantity", `${p.side.toUpperCase()} ${fmtNum(p.quantity, 0)}`],
          ["Order type", `${p.order_type}${p.limit_price ? ` · limit ${fmtNum(p.limit_price)}` : ""}${p.stop_price ? ` · stop ${fmtNum(p.stop_price)}` : ""}`],
          ["Time in force", p.tif],
          ["Estimated commission", p.estimated_commission.unknown ? <Badge tone="warn">Unknown</Badge> : `${fmtNum(p.estimated_commission.amount)} ${p.estimated_commission.currency} (${p.estimated_commission.label})`],
        ]}
      />
      <KeyValue
        items={[
          ["Notional", `${fmtMoney(p.notional.amount, p.notional.currency, 2)}`],
          ["In home currency", `${fmtMoney(p.notional.home_amount, p.notional.home_currency, 2)} @ ${p.notional.fx_rate} (FX ${fmtTime(p.notional.fx_as_of)})`],
          ["Quote", `${fmtNum(p.quote.price)} · ${p.quote.label} · as of ${fmtTime(p.quote.as_of, undefined, { second: "2-digit" })} (${p.quote.freshness})`],
          ["Venue session", `${p.session.state}${p.session.reason ? ` — ${p.session.reason}` : ""}`],
          ["Linked decision", p.linked_decision ? p.linked_decision.title : "None"],
          ["Payload hash", <code className="text-[11px]">{p.payload_hash.slice(0, 20)}…</code>],
        ]}
      />
      <div className="md:col-span-2">
        <p className="mb-1.5 text-sm font-medium">
          Limit and safety checks ({p.limit_checks.filter((c) => c.passed).length}/{p.limit_checks.length} passed)
        </p>
        <ul className="grid grid-cols-1 gap-1 text-sm sm:grid-cols-2">
          {p.limit_checks.map((c) => (
            <li key={c.key} className="flex gap-2">
              <span aria-hidden className={c.passed ? "text-good" : "text-bad"}>
                {c.passed ? "✓" : "✗"}
              </span>
              <span>
                <span className="sr-only">{c.passed ? "Passed: " : "Failed: "}</span>
                {c.name}
                <span className="block text-xs text-muted">{c.detail}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

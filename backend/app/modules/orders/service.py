"""Controlled execution. Every control is enforced here in the backend (PROJECT_PLAN §12.4):
mode separation, Live gate, payload-bound approval with expiry and step-up, idempotency, limits, stale-data block,
uncertain outcomes → reconciliation before retry, fills only from broker reports, stop control, tracked cancels."""

import hashlib
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit
from app.core.authz import Principal, require_step_up
from app.core.clock import utcnow
from app.core.db import notify
from app.core.errors import AppError, Conflict, NotFound
from app.core.logging import correlation_id, get_logger
from app.core.security import canonical_json, new_token
from app.modules.brokers.base import OrderSpec
from app.modules.brokers.registry import get_adapter
from app.modules.calendar.sessions import session_state
from app.modules.decisions.models import Decision, DecisionEvent
from app.modules.markets.models import Instrument, QuoteSnapshot
from app.modules.markets.quotes import fx_rate, quote_view
from app.modules.orders.models import (
    CancelBatch,
    Execution,
    OrderApproval,
    OrderEvent,
    OrderTicket,
    ReconciliationRun,
    StopState,
)
from app.modules.portfolio.models import CashBalance, Position
from app.modules.portfolio.service import get_portfolio, valuation
from app.modules.settings.service import get_setting, home_currency, trading_mode

log = get_logger("orders")

MATERIAL_FIELDS = ("instrument_id", "side", "quantity", "order_type", "limit_price", "stop_price", "tif", "account_id")
OPEN_STATES = ("acknowledged", "partially_filled", "cancel_requested")
RECONCILE_STATES = ("submitting", "uncertain", "reconciling", "acknowledged", "partially_filled", "cancel_requested")
FINAL_STATES = ("filled", "cancelled", "rejected", "cancel_rejected")
LIVE_DISABLED_MESSAGE = ("Live trading is disabled. Activation would require LIVE_TRADING_ENABLED, owner TOTP, "
                         "re-authentication, a checklist acknowledgement and completed Paper verification — and it is "
                         "not authorized in this build.")


# ---------- helpers ----------

def _n(value) -> str:
    """Human-readable decimal without trailing zeros."""
    return format(Decimal(value).normalize(), "f")


def _event(db: Session, t: OrderTicket, to_status: str, message: str, details: dict | None = None,
           actor: Principal | None = None) -> None:
    frm = t.status
    t.status = to_status
    db.add(OrderEvent(ticket_id=t.id, at=utcnow(), from_status=frm, to_status=to_status, message=message,
                      details=details or {}, correlation_id=correlation_id.get()))
    audit.record(db, f"order.{to_status}", actor=actor, object_type="order", object_id=t.id,
                 details={"from": frm, "mode": t.mode, **({"reason": details.get("reason")} if details and
                                                         details.get("reason") else {})})
    notify(db, "events", f"order:order:{t.id}")


def stop_state(db: Session) -> StopState:
    s = db.get(StopState, 1)
    if s is None:
        s = StopState(id=1, engaged=False)
        db.add(s)
        db.flush()
    return s


def payload_of(t: OrderTicket) -> dict:
    return {"mode": t.mode, "broker": t.broker, "account_id": t.account_id, "instrument_id": str(t.instrument_id),
            "side": t.side, "quantity": str(Decimal(t.quantity).normalize()), "order_type": t.order_type,
            "limit_price": str(Decimal(t.limit_price).normalize()) if t.limit_price is not None else None,
            "stop_price": str(Decimal(t.stop_price).normalize()) if t.stop_price is not None else None,
            "tif": t.tif, "client_order_id": t.client_order_id}


def payload_hash(t: OrderTicket) -> str:
    return hashlib.sha256(canonical_json(payload_of(t)).encode()).hexdigest()


def _spec(db: Session, t: OrderTicket, inst: Instrument, ref_price: Decimal) -> OrderSpec:
    return OrderSpec(client_order_id=t.client_order_id, account_id=t.account_id, symbol=inst.symbol,
                     venue_mic=inst.venue_mic, currency=inst.currency, broker_instrument_id=inst.broker_instrument_id,
                     side=t.side, quantity=Decimal(t.quantity), order_type=t.order_type, limit_price=t.limit_price,
                     stop_price=t.stop_price, tif=t.tif, reference_price=ref_price, scenario=t.mock_scenario)


def _ensure_mode_allowed(mode: str) -> None:
    if mode == "live":
        raise AppError("live_not_authorized", LIVE_DISABLED_MESSAGE, status_code=403, help_slug="modes")


# ---------- tickets ----------

def create_ticket(db: Session, principal: Principal, data: dict) -> OrderTicket:
    mode = trading_mode(db)
    _ensure_mode_allowed(mode)
    inst = db.get(Instrument, data["instrument_id"])
    if inst is None:
        raise NotFound("Instrument")
    if not inst.tradable:
        raise AppError("not_tradable", f"{inst.symbol} is not tradable: {inst.not_tradable_reason or 'reference only'}.",
                       status_code=422, help_slug="markets-and-venues")
    adapter = get_adapter(db, mode)
    conn = adapter.connection_status()
    if mode != "mock" and conn["status"] != "connected":
        raise AppError("broker_disconnected", f"Broker disconnected: {conn['detail']}", status_code=409,
                       help_slug="ibkr-setup")
    if data.get("mock_scenario") and mode != "mock":
        raise AppError("mock_only", "Simulation scenarios exist only in Mock mode.", status_code=422)
    _validate_shape(data)
    t = OrderTicket(mode=mode, broker=adapter.name, account_id=conn["account_id"] or "unknown",
                    decision_id=data.get("decision_id"), instrument_id=inst.id, side=data["side"],
                    quantity=Decimal(str(data["quantity"])), order_type=data["order_type"],
                    limit_price=data.get("limit_price"), stop_price=data.get("stop_price"), tif=data.get("tif", "DAY"),
                    client_order_id=f"DOPS-{new_token(9)}", status="draft",
                    mock_scenario=data.get("mock_scenario") if mode == "mock" else None,
                    created_by=principal.user_id)
    db.add(t)
    db.flush()
    db.add(OrderEvent(ticket_id=t.id, at=utcnow(), from_status=None, to_status="draft",
                      message="Ticket created.", details={"client_order_id": t.client_order_id},
                      correlation_id=correlation_id.get()))
    audit.record(db, "order.ticket_created", actor=principal, object_type="order", object_id=t.id,
                 details={"mode": mode})
    if t.decision_id:
        d = db.get(Decision, t.decision_id)
        if d is not None and d.status == "decided":
            d.status = "execution_linked"
        if d is not None:
            db.add(DecisionEvent(decision_id=d.id, at=utcnow(), kind="order_linked",
                                 summary=f"Order ticket created ({t.side} {t.quantity} {inst.symbol}, {mode}).",
                                 details={"order_id": str(t.id)}))
    return t


def _validate_shape(data: dict) -> None:
    ot = data["order_type"]
    if Decimal(str(data["quantity"])) <= 0:
        raise AppError("invalid_quantity", "Quantity must be positive.", status_code=422)
    if ot in ("limit", "stop_limit") and not data.get("limit_price"):
        raise AppError("limit_required", "A limit price is required for this order type.", status_code=422)
    if ot in ("stop", "stop_limit") and not data.get("stop_price"):
        raise AppError("stop_required", "A stop price is required for this order type.", status_code=422)
    if ot == "market" and (data.get("limit_price") or data.get("stop_price")):
        raise AppError("unexpected_price", "Market orders take no limit or stop price.", status_code=422)


def get_ticket(db: Session, ticket_id: uuid.UUID, *, lock: bool = False) -> OrderTicket:
    stmt = select(OrderTicket).where(OrderTicket.id == ticket_id)
    if lock:
        stmt = stmt.with_for_update()
    t = db.scalar(stmt)
    if t is None:
        raise NotFound("Order")
    return t


def edit_ticket(db: Session, principal: Principal, t: OrderTicket, changes: dict) -> OrderTicket:
    if t.status not in ("draft", "previewed", "pending_approval", "approved", "invalidated", "expired", "blocked"):
        raise Conflict("not_editable", "This order can no longer be edited.")
    material = {k: v for k, v in changes.items() if k in MATERIAL_FIELDS and v is not None}
    merged = {"order_type": t.order_type, "quantity": t.quantity, "limit_price": t.limit_price,
              "stop_price": t.stop_price, **material}
    if "order_type" in material and material["order_type"] == "market":
        merged["limit_price"] = merged["stop_price"] = None
        t.limit_price = t.stop_price = None
    _validate_shape(merged)
    for k, v in material.items():
        setattr(t, k, Decimal(str(v)) if k in ("quantity", "limit_price", "stop_price") else v)
    if "mock_scenario" in changes and t.mode == "mock":
        t.mock_scenario = changes["mock_scenario"]
    invalidated = 0
    for a in db.scalars(select(OrderApproval).where(OrderApproval.ticket_id == t.id, OrderApproval.status == "active")):
        a.status = "invalidated"
        invalidated += 1
    t.preview, t.previewed_at = None, None
    if invalidated:
        _event(db, t, "invalidated", "Material edit: the approval is no longer valid.", actor=principal)
    _event(db, t, "draft", "Edited. Preview again before approval.", {"fields": sorted(material)}, actor=principal)
    return t


# ---------- preview ----------

def _limit_checks(db: Session, t: OrderTicket, inst: Instrument, ref_price: Decimal, notional_home: Decimal,
                  quote: dict, session: dict) -> list[dict]:
    limits = get_setting(db, "limits")
    checks = []

    def add(key, name, passed, detail):
        checks.append({"key": key, "name": name, "passed": bool(passed), "detail": detail})

    add("notional", "Order value within your per-order limit", notional_home <= limits["max_order_notional_home"],
        f"{notional_home:,.0f} vs limit {limits['max_order_notional_home']:,} {home_currency(db)}")
    val = valuation(db, t.mode)
    total = Decimal(str(val["total_home"] or 0))
    current = sum((Decimal(str(r["value_home"])) for r in val["positions"] if r.get("instrument_id") == str(inst.id)),
                  Decimal(0))
    after = current + (notional_home if t.side == "buy" else -notional_home)
    pct = (after / total * 100) if total else Decimal(0)
    add("position_pct", "Position size within your portfolio limit", t.side == "sell" or pct <= limits["max_position_pct"],
        f"After the trade: {pct:.1f}% of portfolio (limit {limits['max_position_pct']}%)")
    day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today = db.scalar(select(func.count()).select_from(OrderTicket).where(
        OrderTicket.mode == t.mode, OrderTicket.submitted_at >= day_start))
    add("orders_per_day", "Daily order count within limit", today < limits["max_orders_per_day"],
        f"{today} submitted today (limit {limits['max_orders_per_day']})")
    allow = limits["allowlist"].get(t.mode) or []
    add("allowlist", "Instrument allowed in this mode", not allow or inst.symbol in allow,
        "All tradable instruments allowed" if not allow else f"Allowlist: {', '.join(allow)}")
    if t.limit_price is not None and quote.get("price"):
        dev = abs(Decimal(t.limit_price) / Decimal(str(quote["price"])) - 1) * 100
        add("price_collar", "Limit price within the price collar", dev <= limits["price_collar_pct"],
            f"{dev:.2f}% from the last quote (collar {limits['price_collar_pct']}%)")
    if t.order_type == "market" and limits["block_market_orders_outside_session"]:
        add("session", "Market orders only while the venue is open", session["state"] == "open",
            f"Venue is {session['state']}" + (f" ({session['reason']})" if session.get("reason") else ""))
    if t.side == "sell":
        portfolio = get_portfolio(db, t.mode)
        held = Decimal(0)
        if portfolio:
            pos = db.scalar(select(Position).where(Position.portfolio_id == portfolio.id,
                                                   Position.instrument_id == inst.id))
            held = pos.quantity if pos else Decimal(0)
        add("long_only", "Long-only: you hold enough to sell", Decimal(t.quantity) <= held,
            f"Held {_n(held)}, selling {_n(t.quantity)} (no short selling in this scope)")
    add("quote_fresh", "Quote is fresh", quote["freshness"] == "fresh",
        f"Quote age {quote.get('age_seconds')} s ({quote['freshness']})")
    return checks


def build_preview(db: Session, t: OrderTicket, *, at_submission: bool = False) -> dict:
    inst = db.get(Instrument, t.instrument_id)
    q = db.get(QuoteSnapshot, inst.id)
    quote = quote_view(inst, q)
    if at_submission and t.mode == "mock" and t.mock_scenario == "stale_quote":
        quote = {**quote, "freshness": "stale"}  # Mock scenario: the quote goes stale between approval and submit
    ref_price = Decimal(t.limit_price or t.stop_price or (q.price if q else inst.reference_price))
    notional = Decimal(t.quantity) * ref_price
    home = home_currency(db)
    rate, fx_as_of = fx_rate(db, inst.currency, home)
    notional_home = (notional * rate).quantize(Decimal("0.01"))
    sess = session_state(inst.venue_mic, utcnow())
    adapter = get_adapter(db, t.mode)
    pv = adapter.preview(_spec(db, t, inst, ref_price))
    checks = _limit_checks(db, t, inst, ref_price, notional_home, quote, sess)
    decision = db.get(Decision, t.decision_id) if t.decision_id else None
    return {
        "mode": t.mode, "broker": t.broker, "account_id": t.account_id,
        "instrument": {"symbol": inst.symbol, "name": inst.name, "broker_instrument_id": inst.broker_instrument_id,
                       "venue_mic": inst.venue_mic},
        "currency": inst.currency, "side": t.side, "quantity": float(t.quantity), "order_type": t.order_type,
        "limit_price": float(t.limit_price) if t.limit_price is not None else None,
        "stop_price": float(t.stop_price) if t.stop_price is not None else None, "tif": t.tif,
        "estimated_commission": {"amount": float(pv.commission) if pv.commission is not None else None,
                                 "currency": pv.commission_currency, "label": pv.label, "detail": pv.detail,
                                 "unknown": pv.commission is None},
        "notional": {"amount": float(notional.quantize(Decimal('0.01'))), "currency": inst.currency,
                     "home_amount": float(notional_home), "home_currency": home, "fx_rate": float(rate),
                     "fx_as_of": fx_as_of.isoformat() if fx_as_of else None,
                     "reference_price": float(ref_price)},
        "quote": quote, "session": {"state": sess["state"], "reason": sess["reason"], "next_event": sess["next_event"]},
        "limit_checks": checks, "all_checks_passed": all(c["passed"] for c in checks),
        "linked_decision": {"id": str(decision.id), "title": decision.title} if decision else None,
        "client_order_id": t.client_order_id, "payload_hash": payload_hash(t),
        "label": "Simulated" if t.mode == "mock" else "Broker",
        "mock_scenario": t.mock_scenario,
    }


def preview(db: Session, principal: Principal, t: OrderTicket) -> dict:
    if t.status not in ("draft", "previewed", "expired", "blocked", "invalidated", "pending_approval"):
        raise Conflict("not_previewable", "This order is past the preview stage.")
    _ensure_mode_allowed(t.mode)
    p = build_preview(db, t)
    t.preview, t.previewed_at = p, utcnow()
    _event(db, t, "previewed", "Preview generated." + ("" if p["all_checks_passed"] else " Some checks failed."),
           {"all_checks_passed": p["all_checks_passed"]}, actor=principal)
    return p


# ---------- approval ----------

def approve(db: Session, principal: Principal, t: OrderTicket) -> OrderApproval:
    if t.status not in ("previewed", "pending_approval"):
        raise Conflict("not_approvable", "Preview the order before approving it.")
    if not t.preview or not t.preview.get("all_checks_passed"):
        raise Conflict("checks_failed", "Resolve the failed checks before approving.",
                       details={"checks": [c for c in (t.preview or {}).get("limit_checks", []) if not c["passed"]]})
    if t.preview["payload_hash"] != payload_hash(t):
        raise Conflict("preview_outdated", "The order changed after the preview. Preview again.")
    if t.status == "previewed":
        _event(db, t, "pending_approval", "Approval requested.", actor=principal)
    require_step_up(principal)
    expiry = get_settings().approval_expiry_minutes
    a = OrderApproval(ticket_id=t.id, payload_hash=payload_hash(t), approved_by=principal.user_id,
                      approved_at=utcnow(), expires_at=utcnow() + timedelta(minutes=expiry), status="active")
    db.add(a)
    _event(db, t, "approved", f"Approved for this exact payload; expires in {expiry} minutes.",
           {"payload_hash": a.payload_hash}, actor=principal)
    return a


# ---------- submission ----------

def _block(db: Session, t: OrderTicket, reason: str, code: str, actor: Principal, help_slug: str) -> None:
    _event(db, t, "blocked", reason, {"reason": code}, actor=actor)
    db.commit()
    raise AppError(code, reason, status_code=409, help_slug=help_slug)


def submit(db: Session, principal: Principal, ticket_id: uuid.UUID) -> tuple[OrderTicket, bool]:
    """Returns (ticket, duplicate). A repeated submit never sends a second order."""
    t = get_ticket(db, ticket_id, lock=True)  # row lock = idempotency lock
    if t.status not in ("approved",):
        if t.status in RECONCILE_STATES + FINAL_STATES + ("not_found",):
            return t, True
        raise Conflict("not_approved", "Approve the order (step-up required) before submitting.",
                       help_slug="approvals-and-stop")
    _ensure_mode_allowed(t.mode)
    approval = db.scalar(select(OrderApproval).where(OrderApproval.ticket_id == t.id, OrderApproval.status == "active")
                         .order_by(OrderApproval.approved_at.desc()))
    if approval is None:
        _event(db, t, "invalidated", "No valid approval.", actor=principal)
        db.commit()
        raise Conflict("approval_missing", "The approval is missing or invalid. Preview and approve again.")
    if approval.expires_at <= utcnow():
        approval.status = "expired"
        _event(db, t, "expired", "The approval expired before submission.", actor=principal)
        db.commit()
        raise Conflict("approval_expired", "The approval expired. Preview again and re-approve.",
                       help_slug="approvals-and-stop")
    if approval.payload_hash != payload_hash(t):
        approval.status = "invalidated"
        _event(db, t, "invalidated", "Payload differs from the approved payload.", actor=principal)
        db.commit()
        raise Conflict("approval_mismatch", "The order differs from what you approved. Preview and approve again.")
    if stop_state(db).engaged:
        _block(db, t, "Stop is engaged: new submissions are blocked.", "stop_engaged", principal, "approvals-and-stop")
    fresh = build_preview(db, t, at_submission=True)  # re-check limits, freshness and session at the moment of submission
    if fresh["quote"]["freshness"] != "fresh":
        _block(db, t, f"Stale data: the {fresh['instrument']['symbol']} quote is {fresh['quote']['freshness']} "
               f"(as of {fresh['quote']['as_of']}). Refresh data and preview again.", "stale_data", principal,
               "approvals-and-stop")
    failed = [c for c in fresh["limit_checks"] if not c["passed"]]
    if failed:
        _block(db, t, "Limit check failed at submission: " + "; ".join(f"{c['name']} ({c['detail']})" for c in failed),
               "limit_breach", principal, "approvals-and-stop")
    approval.status = "used"
    t.submitted_at = utcnow()
    _event(db, t, "submitting", "Submitting to the broker.", {"client_order_id": t.client_order_id}, actor=principal)
    db.commit()  # persist 'submitting' BEFORE contacting the broker; a crash here is reconciled, never resent

    inst = db.get(Instrument, t.instrument_id)
    adapter = get_adapter(db, t.mode)
    try:
        result = adapter.submit(_spec(db, t, inst, Decimal(str(fresh["notional"]["reference_price"]))))
    except Exception as exc:  # noqa: BLE001 - any failure after send is an uncertain outcome
        log.warning("submit_exception", order_id=str(t.id), error=exc.__class__.__name__)
        from app.modules.brokers.base import SubmitResult

        result = SubmitResult("uncertain", None, f"Outcome unknown: {exc.__class__.__name__}")
    t = get_ticket(db, ticket_id, lock=True)
    if result.status == "accepted":
        t.broker_order_id = result.broker_order_id
        _event(db, t, "acknowledged", "Acknowledged by the broker." + (f" {result.reason}" if result.reason else ""),
               {"broker_order_id": result.broker_order_id}, actor=principal)
    elif result.status == "rejected":
        t.last_error = result.reason
        _event(db, t, "rejected", result.reason or "Rejected by the broker.", {"reason": "broker_rejected"},
               actor=principal)
    else:
        t.last_error = result.reason
        _event(db, t, "uncertain", (result.reason or "Outcome unknown.") + " No retry until reconciliation resolves it.",
               {"reason": "uncertain"}, actor=principal)
    return t, False


# ---------- cancellation ----------

def cancel(db: Session, principal: Principal | None, t: OrderTicket) -> OrderTicket:
    if t.status in ("draft", "previewed", "pending_approval", "approved", "invalidated", "expired", "blocked"):
        for a in db.scalars(select(OrderApproval).where(OrderApproval.ticket_id == t.id, OrderApproval.status == "active")):
            a.status = "invalidated"
        _event(db, t, "cancelled", "Cancelled before submission.", actor=principal)
        return t
    if t.status not in ("acknowledged", "partially_filled"):
        raise Conflict("not_cancellable", f"An order in state '{t.status}' cannot be cancelled now.")
    _event(db, t, "cancel_requested", "Cancel requested; waiting for the broker.", actor=principal)
    res = get_adapter(db, t.mode).cancel(t.client_order_id, t.broker_order_id)
    if res["status"] != "requested":
        _event(db, t, "cancel_rejected", res.get("reason") or "Cancel rejected by the broker.",
               {"reason": "cancel_rejected"}, actor=principal)
    return t


def resubmit_after_not_found(db: Session, principal: Principal, t: OrderTicket) -> OrderTicket:
    if t.status != "not_found":
        raise Conflict("not_resubmittable", "Only orders confirmed NOT FOUND after reconciliation can be resubmitted.")
    old = t.client_order_id
    t.client_order_id = f"DOPS-{new_token(9)}"
    t.preview, t.previewed_at, t.submitted_at, t.broker_order_id = None, None, None, None
    _event(db, t, "draft", "Resubmission prepared with a new client order ID (explicit owner action).",
           {"previous_client_order_id": old}, actor=principal)
    return t


# ---------- stop control ----------

def set_stop(db: Session, principal: Principal, engaged: bool, reason: str | None) -> StopState:
    s = stop_state(db)
    if not engaged:
        require_step_up(principal)
    s.engaged, s.changed_at, s.changed_by, s.reason = engaged, utcnow(), principal.user_id, reason
    audit.record(db, "stop.engaged" if engaged else "stop.released", actor=principal, object_type="stop",
                 object_id=1, details={"reason": reason})
    notify(db, "events", "stop:stop:1")
    return s


def start_cancel_batch(db: Session, principal: Principal) -> CancelBatch:
    mode = trading_mode(db)
    open_ids = [str(t.id) for t in db.scalars(select(OrderTicket).where(OrderTicket.mode == mode,
                                                                       OrderTicket.status.in_(("acknowledged", "partially_filled"))))]
    batch = CancelBatch(mode=mode, created_by=principal.user_id, ticket_ids=open_ids, results={})
    db.add(batch)
    db.flush()
    for tid in open_ids:
        t = get_ticket(db, uuid.UUID(tid), lock=True)
        try:
            cancel(db, principal, t)
            batch.results = {**batch.results, tid: t.status}
        except AppError as exc:
            batch.results = {**batch.results, tid: f"skipped: {exc.message}"}
    audit.record(db, "orders.cancel_open_orders", actor=principal, object_type="cancel_batch", object_id=batch.id,
                 details={"orders": len(open_ids)})
    return batch


# ---------- reconciliation (also processes broker events) ----------

def _apply_executions(db: Session, t: OrderTicket, state) -> int:
    new = 0
    known = {e.broker_exec_id for e in db.scalars(select(Execution).where(Execution.ticket_id == t.id))}
    inst = db.get(Instrument, t.instrument_id)
    for e in state.executions:
        if e["exec_id"] in known:
            continue
        qty, price = Decimal(e["qty"]), Decimal(e["price"])
        db.add(Execution(ticket_id=t.id, broker_exec_id=e["exec_id"], quantity=qty, price=price,
                         commission=Decimal(e["commission"]) if e.get("commission") else None,
                         at=e["at"]))
        _apply_fill_to_portfolio(db, t, inst, qty, price, Decimal(e["commission"] or 0) if e.get("commission") else Decimal(0))
        new += 1
    return new


def _apply_fill_to_portfolio(db: Session, t: OrderTicket, inst: Instrument, qty: Decimal, price: Decimal,
                             fee: Decimal) -> None:
    """Mock mode: the simulated broker's fills update the synthetic portfolio (broker is the source of truth)."""
    if t.mode != "mock":
        return
    portfolio = get_portfolio(db, "mock")
    if portfolio is None:
        return
    pos = db.scalar(select(Position).where(Position.portfolio_id == portfolio.id, Position.instrument_id == inst.id))
    signed = qty if t.side == "buy" else -qty
    if pos is None:
        pos = Position(portfolio_id=portfolio.id, instrument_id=inst.id, quantity=Decimal(0), avg_cost=price,
                       as_of=utcnow())
        db.add(pos)
    if t.side == "buy":
        total = pos.quantity * pos.avg_cost + qty * price
        pos.quantity = pos.quantity + qty
        pos.avg_cost = (total / pos.quantity).quantize(Decimal("0.000001"))
    else:
        pos.quantity = pos.quantity + signed
    pos.as_of = utcnow()
    cash = db.scalar(select(CashBalance).where(CashBalance.portfolio_id == portfolio.id,
                                               CashBalance.currency == inst.currency))
    if cash is None:
        cash = CashBalance(portfolio_id=portfolio.id, currency=inst.currency, amount=Decimal(0), as_of=utcnow())
        db.add(cash)
    cash.amount = cash.amount - signed * price - fee
    cash.as_of = utcnow()


def reconcile_ticket(db: Session, t: OrderTicket, adapter, trigger: str) -> dict | None:
    state = adapter.order_status(t.client_order_id)
    grace = timedelta(seconds=get_settings().reconciliation_grace_seconds)
    before = t.status
    mismatch = None
    if not state.found:
        if t.status in ("submitting", "uncertain", "reconciling"):
            if t.status != "reconciling":
                _event(db, t, "reconciling", "Reconciling with the broker by order reference.")
            if t.submitted_at and utcnow() - t.submitted_at >= grace:
                _event(db, t, "not_found", "Confirmed NOT FOUND at the broker after the grace period. You may "
                       "resubmit as a new, explicit action.")
        elif t.status in OPEN_STATES:
            mismatch = "Order is open locally but unknown to the broker."
        return _result(t, before, mismatch)
    if t.status in ("submitting", "uncertain", "reconciling"):
        if t.status != "reconciling":
            _event(db, t, "reconciling", "Reconciling with the broker by order reference.")
        t.broker_order_id = state.broker_order_id
        _event(db, t, "acknowledged", "Reconciliation found the order at the broker.",
               {"broker_order_id": state.broker_order_id})
    new_execs = _apply_executions(db, t, state)
    t.filled_quantity = state.filled
    t.avg_fill_price = state.avg_price
    if state.status == "filled" and t.status != "filled":
        msg = "Filled before the cancel took effect." if t.status == "cancel_requested" else "Filled."
        _event(db, t, "filled", msg, {"filled": str(state.filled), "executions": new_execs})
    elif state.status == "partially_filled" and t.status in ("acknowledged", "partially_filled") and new_execs:
        _event(db, t, "partially_filled", f"Partially filled: {_n(state.filled)} of {_n(t.quantity)}.",
               {"filled": str(state.filled)})
    elif state.status == "cancelled" and t.status != "cancelled":
        if t.status not in ("cancel_requested",):
            mismatch = "Broker shows the order cancelled without a local cancel request."
        _event(db, t, "cancelled", "Cancelled at the broker." + (f" Partially filled {_n(state.filled)}." if state.filled else ""))
    elif state.status == "rejected" and t.status not in ("rejected",):
        _event(db, t, "rejected", state.reason or "Rejected by the broker.")
    elif t.status in FINAL_STATES and state.status in ("working", "partially_filled"):
        mismatch = f"Local state '{t.status}' but the broker shows '{state.status}'."
    return _result(t, before, mismatch)


def _result(t: OrderTicket, before: str, mismatch: str | None) -> dict | None:
    if before == t.status and mismatch is None:
        return None
    return {"order_id": str(t.id), "from": before, "to": t.status, "mismatch": mismatch}


def reconcile(db: Session, mode: str, trigger: str) -> ReconciliationRun:
    run = ReconciliationRun(id=uuid.uuid4(), mode=mode, started_at=utcnow(), trigger=trigger, checked=0, changed=0,
                            mismatches=0, details=[])
    try:
        adapter = get_adapter(db, mode)
    except AppError:
        run.finished_at = utcnow()
        return run
    if mode == "mock":
        from app.modules.brokers.mock import advance

        advance(db)
        db.flush()
    details = []
    tickets = list(db.scalars(select(OrderTicket).where(OrderTicket.mode == mode,
                                                        OrderTicket.status.in_(RECONCILE_STATES))))
    for t in tickets:
        r = reconcile_ticket(db, t, adapter, trigger)
        if r:
            details.append(r)
    run.checked = len(tickets)
    run.changed = sum(1 for d in details if d["from"] != d["to"])
    run.mismatches = sum(1 for d in details if d["mismatch"])
    run.details = details
    run.finished_at = utcnow()
    if trigger != "events" or run.changed or run.mismatches:
        db.add(run)  # frequent event polls are persisted only when something changed
    if run.mismatches:
        from app.modules.ops.alerts import raise_alert

        raise_alert(db, "reconciliation_mismatch", f"reconciliation:{run.id}", "critical",
                    f"Reconciliation found {run.mismatches} mismatch(es) between local orders and the broker.",
                    "alert-reconciliation-mismatch", {"details": details[:10]})
        audit.record(db, "orders.reconciliation_mismatch", object_type="reconciliation_run", object_id=run.id,
                     details={"mismatches": run.mismatches})
    return run


def ticket_out(db: Session, t: OrderTicket, *, events: bool = False) -> dict:
    inst = db.get(Instrument, t.instrument_id)
    approval = db.scalar(select(OrderApproval).where(OrderApproval.ticket_id == t.id)
                         .order_by(OrderApproval.approved_at.desc()))
    out = {"id": str(t.id), "mode": t.mode, "broker": t.broker, "account_id": t.account_id,
           "decision_id": str(t.decision_id) if t.decision_id else None,
           "instrument": {"id": str(inst.id), "symbol": inst.symbol, "name": inst.name, "venue_mic": inst.venue_mic,
                          "currency": inst.currency},
           "side": t.side, "quantity": float(t.quantity), "order_type": t.order_type,
           "limit_price": float(t.limit_price) if t.limit_price is not None else None,
           "stop_price": float(t.stop_price) if t.stop_price is not None else None, "tif": t.tif,
           "client_order_id": t.client_order_id, "status": t.status, "broker_order_id": t.broker_order_id,
           "filled_quantity": float(t.filled_quantity), "avg_fill_price": float(t.avg_fill_price) if t.avg_fill_price else None,
           "mock_scenario": t.mock_scenario, "preview": t.preview, "previewed_at": t.previewed_at,
           "submitted_at": t.submitted_at, "last_error": t.last_error, "created_at": t.created_at,
           "updated_at": t.updated_at,
           "approval": {"status": approval.status, "expires_at": approval.expires_at, "payload_hash": approval.payload_hash,
                        "approved_at": approval.approved_at} if approval else None}
    if events:
        out["events"] = [{"at": e.at, "from": e.from_status, "to": e.to_status, "message": e.message,
                          "details": e.details} for e in db.scalars(select(OrderEvent).where(
                              OrderEvent.ticket_id == t.id).order_by(OrderEvent.at, OrderEvent.id))]
        out["executions"] = [{"exec_id": x.broker_exec_id, "quantity": float(x.quantity), "price": float(x.price),
                              "commission": float(x.commission) if x.commission is not None else None, "at": x.at}
                             for x in db.scalars(select(Execution).where(Execution.ticket_id == t.id)
                                                 .order_by(Execution.at))]
    return out

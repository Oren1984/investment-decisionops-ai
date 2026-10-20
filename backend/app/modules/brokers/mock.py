"""Mock broker: a simulated broker 'side' with explicit failure scenarios. Its success never counts as real broker
verification. Scenarios: success, rejection, partial_fill, timeout, disconnect_after_send, duplicate_request,
fill_after_cancel, stale_quote (the last one is enforced on our side before submission)."""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.security import new_token
from app.modules.brokers.base import BrokerOrderState, OrderSpec, Preview, SubmitResult
from app.modules.brokers.models import MockBrokerOrder

SCENARIOS = {
    "success": "Accepted, then filled in full.",
    "rejection": "Rejected by the (simulated) broker.",
    "partial_fill": "Accepted, partially filled, then filled.",
    "timeout": "No acknowledgement before timeout; the broker did receive it (reconciliation finds it).",
    "disconnect_after_send": "Connection lost after sending; the broker never received it (reconciliation: not found).",
    "duplicate_request": "The submit is sent twice; idempotency returns the existing order.",
    "fill_after_cancel": "Stays working; a cancel request arrives too late and the order fills first.",
    "stale_quote": "The quote is marked stale; the backend blocks submission.",
}
MOCK_ACCOUNT = "MOCK-0001"


class MockAdapter:
    name = "mock"
    mode = "mock"

    def __init__(self, db: Session):
        self.db = db

    def capabilities(self) -> dict:
        return {"venues": ["XNYS", "XNAS", "FXSP", "XLON", "XETR", "XTKS"], "instrument_types": ["equity", "etf", "fx"],
                "order_types": ["market", "limit", "stop", "stop_limit"], "tifs": ["DAY", "GTC"],
                "preview_costs": True, "label": "Simulated"}

    def connection_status(self) -> dict:
        return {"status": "connected", "account_id": MOCK_ACCOUNT, "detail": "Simulated broker (Mock mode)."}

    def list_accounts(self) -> list[dict]:
        return [{"account_id": MOCK_ACCOUNT, "type": "cash", "label": "Simulated"}]

    def get_balances(self) -> list[dict]:
        return []  # balances live in the Mock portfolio

    def get_positions(self) -> list[dict]:
        return []

    def get_open_orders(self) -> list[dict]:
        rows = self.db.scalars(select(MockBrokerOrder).where(MockBrokerOrder.status.in_(("working", "partially_filled"))))
        return [{"order_ref": r.order_ref, "broker_order_id": r.broker_order_id, "status": r.status} for r in rows]

    def get_executions(self, since) -> list[dict]:
        out = []
        for r in self.db.scalars(select(MockBrokerOrder)):
            out.extend(e for e in r.executions if e["at"] >= since.isoformat())
        return out

    def lookup_instrument(self, symbol: str, venue_mic: str, currency: str) -> dict | None:
        return {"broker_instrument_id": f"MOCK:{venue_mic}:{symbol}", "symbol": symbol, "venue_mic": venue_mic,
                "currency": currency, "tradable": venue_mic in self.capabilities()["venues"]}

    def preview(self, order: OrderSpec) -> Preview:
        notional = order.quantity * (order.limit_price or order.reference_price)
        fee = max(Decimal("1.00"), (notional * Decimal("0.0005")).quantize(Decimal("0.01")))
        return Preview(commission=fee, commission_currency=order.currency, label="Simulated estimate",
                       detail="Mock fee model: 0.05% of notional, minimum 1.00.")

    def submit(self, order: OrderSpec) -> SubmitResult:
        existing = self.db.scalar(select(MockBrokerOrder).where(MockBrokerOrder.order_ref == order.client_order_id))
        if existing is not None:  # broker-side duplicate protection by orderRef
            return SubmitResult("accepted", existing.broker_order_id, "Duplicate orderRef: existing order returned")
        scenario = order.scenario or "success"
        if scenario == "rejection":
            return SubmitResult("rejected", None, "Simulated rejection: insufficient buying power for this order.")
        if scenario == "disconnect_after_send":
            return SubmitResult("uncertain", None, "Connection lost after sending (simulated). Outcome unknown.")
        row = MockBrokerOrder(order_ref=order.client_order_id, broker_order_id=f"MB-{new_token(6)}",
                              instrument_id=_instrument_id(self.db, order), side=order.side, quantity=order.quantity,
                              price=order.limit_price or order.reference_price, status="working", scenario=scenario,
                              updated_at=utcnow())
        self.db.add(row)
        self.db.flush()
        if scenario == "timeout":
            return SubmitResult("uncertain", None, "No acknowledgement before timeout (simulated). Outcome unknown.")
        return SubmitResult("accepted", row.broker_order_id)

    def cancel(self, client_order_id: str, broker_order_id: str | None) -> dict:
        row = self.db.scalar(select(MockBrokerOrder).where(MockBrokerOrder.order_ref == client_order_id))
        if row is None or row.status in ("filled", "cancelled", "rejected"):
            return {"status": "rejected", "reason": "Order is not open at the broker."}
        row.cancel_requested = True
        row.updated_at = utcnow()
        return {"status": "requested"}

    def order_status(self, client_order_id: str) -> BrokerOrderState:
        row = self.db.scalar(select(MockBrokerOrder).where(MockBrokerOrder.order_ref == client_order_id))
        if row is None:
            return BrokerOrderState(found=False)
        avg = None
        if row.executions:
            qty = sum(Decimal(e["qty"]) for e in row.executions)
            avg = sum(Decimal(e["qty"]) * Decimal(e["price"]) for e in row.executions) / qty
        return BrokerOrderState(found=True, status=row.status, filled=row.filled, avg_price=avg,
                                broker_order_id=row.broker_order_id, executions=list(row.executions))


def _instrument_id(db: Session, order: OrderSpec):
    from app.modules.markets.models import Instrument

    return db.scalar(select(Instrument.id).where(Instrument.symbol == order.symbol,
                                                 Instrument.venue_mic == order.venue_mic))


def _fill(row: MockBrokerOrder, qty: Decimal) -> None:
    now = utcnow()
    exec_id = f"MX-{new_token(6)}"
    fee = max(Decimal("1.00"), (qty * row.price * Decimal("0.0005")).quantize(Decimal("0.01")))
    row.executions = [*row.executions, {"exec_id": exec_id, "qty": str(qty), "price": str(row.price),
                                        "at": now.isoformat(), "commission": str(fee)}]
    row.filled = row.filled + qty
    row.status = "filled" if row.filled >= row.quantity else "partially_filled"
    row.updated_at = now


def advance(db: Session) -> int:
    """Progress simulated broker orders over time (called by the worker every few seconds)."""
    now = utcnow()
    changed = 0
    for row in db.scalars(select(MockBrokerOrder).where(MockBrokerOrder.status.in_(("working", "partially_filled")))):
        age = now - row.created_at
        if row.scenario == "fill_after_cancel":
            if row.cancel_requested:
                _fill(row, row.quantity - row.filled)  # the fill wins the race against the cancel
                changed += 1
            continue
        if row.cancel_requested:
            row.status, row.updated_at = "cancelled", now
            changed += 1
            continue
        if row.scenario == "partial_fill":
            if row.filled == 0 and age >= timedelta(seconds=2):
                _fill(row, (row.quantity * Decimal("0.4")).quantize(Decimal("1")) or Decimal(1))
                changed += 1
            elif row.filled > 0 and age >= timedelta(seconds=90):
                _fill(row, row.quantity - row.filled)
                changed += 1
            continue
        if age >= timedelta(seconds=2):
            _fill(row, row.quantity - row.filled)
            changed += 1
    return changed

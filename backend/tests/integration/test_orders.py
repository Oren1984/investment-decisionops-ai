"""Orders in Mock mode (plan §12.4, §17): approval binding and expiry (FrozenClock), idempotent submit, stale data,
Stop, limits, broker rejection, uncertain outcomes → reconciliation → NOT FOUND → explicit resubmit, partial fills,
the cancel/fill race and the cancel-open batch. Limits are set directly because the session DB is shared."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.clock import Clock, FrozenClock, set_clock, utcnow
from app.core.db import db_session
from tests.conftest import instrument_id


@pytest.fixture(autouse=True)
def clean_state():
    from app.modules.markets.quotes import refresh_mock_quotes
    from app.modules.orders.models import StopState
    from app.modules.settings.service import DEFAULTS, put_setting

    with db_session() as db:
        refresh_mock_quotes(db)
        put_setting(db, "limits", {**DEFAULTS["limits"], "max_orders_per_day": 500})
        stop = db.get(StopState, 1)
        if stop is not None:
            stop.engaged = False
    yield
    set_clock(Clock())


def advance(seconds: float) -> FrozenClock:
    clock = FrozenClock(utcnow() + timedelta(seconds=seconds))
    set_clock(clock)
    return clock


def quote_price(symbol: str) -> Decimal:
    from app.modules.markets.models import Instrument, QuoteSnapshot

    with db_session() as db:
        inst = db.scalar(select(Instrument).where(Instrument.symbol == symbol))
        return Decimal(db.get(QuoteSnapshot, inst.id).price).quantize(Decimal("0.01"))


def ticket(owner, scenario="success", symbol="AAPL", qty=2, **extra) -> dict:
    r = owner.post("/api/orders", {"instrument_id": instrument_id(owner, symbol), "side": "buy", "quantity": qty,
                                   "order_type": "limit", "limit_price": str(quote_price(symbol)),
                                   "mock_scenario": scenario, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def approved(owner, scenario="success", **kw) -> dict:
    t = ticket(owner, scenario, **kw)
    p = owner.post(f"/api/orders/{t['id']}/preview")
    assert p.status_code == 200 and p.json()["preview"]["all_checks_passed"], p.text
    owner.step_up()
    a = owner.post(f"/api/orders/{t['id']}/approve")
    assert a.status_code == 200 and a.json()["status"] == "approved", a.text
    return a.json()


def submit(owner, tid):
    return owner.post(f"/api/orders/{tid}/submit")


def reconcile(owner):
    r = owner.post("/api/orders/reconcile/run")
    assert r.status_code == 200, r.text
    return r.json()


def status(owner, tid) -> dict:
    return owner.get(f"/api/orders/{tid}").json()


def broker_orders(client_order_id: str) -> int:
    from app.modules.brokers.models import MockBrokerOrder

    with db_session() as db:
        return db.scalar(select(func.count()).select_from(MockBrokerOrder)
                         .where(MockBrokerOrder.order_ref == client_order_id))


def test_success_fill_and_duplicate_submit_sends_once(owner):
    t = approved(owner)
    r = submit(owner, t["id"])
    assert r.status_code == 200 and r.json()["status"] == "acknowledged" and r.json()["duplicate"] is False
    again = submit(owner, t["id"])
    assert again.status_code == 200 and again.json()["duplicate"] is True
    assert broker_orders(t["client_order_id"]) == 1

    advance(5)
    reconcile(owner)
    done = status(owner, t["id"])
    assert done["status"] == "filled" and done["filled_quantity"] == 2
    assert len(done["executions"]) == 1
    reconcile(owner)  # executions are applied once, by broker exec ID
    assert len(status(owner, t["id"])["executions"]) == 1


def test_approval_requires_step_up(owner):
    t = ticket(owner)
    owner.post(f"/api/orders/{t['id']}/preview")
    r = owner.post(f"/api/orders/{t['id']}/approve")  # fresh login: no step-up yet
    assert r.status_code == 401 and r.json()["code"] == "step_up_required"
    assert status(owner, t["id"])["status"] == "pending_approval"
    assert submit(owner, t["id"]).json()["code"] == "not_approved"


def test_approval_expires(owner):
    t = approved(owner)
    advance(6 * 60)
    r = submit(owner, t["id"])
    assert r.status_code == 409 and r.json()["code"] == "approval_expired"
    s = status(owner, t["id"])
    assert s["status"] == "expired" and s["approval"]["status"] == "expired"
    assert broker_orders(t["client_order_id"]) == 0


def test_material_edit_invalidates_approval(owner):
    t = approved(owner)
    r = owner.patch(f"/api/orders/{t['id']}", {"quantity": 3})
    assert r.status_code == 200 and r.json()["status"] == "draft"
    assert r.json()["approval"]["status"] == "invalidated"
    assert any(e["to"] == "invalidated" for e in r.json()["events"])
    assert submit(owner, t["id"]).json()["code"] == "not_approved"


def test_stale_quote_blocks_approval_and_submission(owner):
    sym_id = instrument_id(owner, "MSFT")
    t = ticket(owner, symbol="MSFT")
    owner.step_up()
    assert owner.post(f"/api/markets/instruments/{sym_id}/simulate-stale", {"stale": True}).status_code == 200
    p = owner.post(f"/api/orders/{t['id']}/preview").json()["preview"]
    assert not p["all_checks_passed"] and not next(c for c in p["limit_checks"] if c["key"] == "quote_fresh")["passed"]
    r = owner.post(f"/api/orders/{t['id']}/approve")
    assert r.status_code == 409 and r.json()["code"] == "checks_failed"
    owner.post(f"/api/markets/instruments/{sym_id}/simulate-stale", {"stale": False})

    # The Mock 'stale_quote' scenario: fresh at approval, stale at the moment of submission.
    t2 = approved(owner, "stale_quote")
    r = submit(owner, t2["id"])
    assert r.status_code == 409 and r.json()["code"] == "stale_data"
    assert status(owner, t2["id"])["status"] == "blocked"
    assert broker_orders(t2["client_order_id"]) == 0


def test_stop_blocks_submission_and_release_needs_step_up(owner, anon):
    t = approved(owner)
    assert owner.post("/api/orders/stop", {"engaged": True, "reason": "test"}).status_code == 200
    r = submit(owner, t["id"])
    assert r.status_code == 409 and r.json()["code"] == "stop_engaged"
    assert broker_orders(t["client_order_id"]) == 0
    from tests.conftest import OWNER_EMAIL, OWNER_PASSWORD

    fresh = anon
    fresh.post("/api/auth/login", {"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    assert fresh.post("/api/orders/stop", {"engaged": False}).json()["code"] == "step_up_required"
    owner.step_up()
    assert owner.post("/api/orders/stop", {"engaged": False}).json()["engaged"] is False


def test_limit_breach_at_submission(owner):
    from app.modules.settings.service import DEFAULTS, put_setting

    t = approved(owner)
    with db_session() as db:
        put_setting(db, "limits", {**DEFAULTS["limits"], "max_orders_per_day": 500, "max_order_notional_home": 1})
    r = submit(owner, t["id"])
    assert r.status_code == 409 and r.json()["code"] == "limit_breach"
    assert status(owner, t["id"])["status"] == "blocked"


def test_broker_rejection(owner):
    t = approved(owner, "rejection")
    r = submit(owner, t["id"])
    assert r.status_code == 200 and r.json()["status"] == "rejected" and "insufficient" in r.json()["last_error"]


def test_disconnect_after_send_reconciles_to_not_found_then_explicit_resubmit(owner):
    t = approved(owner, "disconnect_after_send")
    assert submit(owner, t["id"]).json()["status"] == "uncertain"
    assert submit(owner, t["id"]).json()["duplicate"] is True  # no retry while uncertain
    reconcile(owner)
    assert status(owner, t["id"])["status"] == "reconciling"  # inside the grace period
    advance(61)
    reconcile(owner)
    s = status(owner, t["id"])
    assert s["status"] == "not_found" and broker_orders(t["client_order_id"]) == 0
    r = owner.post(f"/api/orders/{t['id']}/resubmit")
    assert r.status_code == 200 and r.json()["status"] == "draft"
    assert r.json()["client_order_id"] != t["client_order_id"]


def test_timeout_is_found_by_reconciliation(owner):
    t = approved(owner, "timeout")
    assert submit(owner, t["id"]).json()["status"] == "uncertain"
    reconcile(owner)
    assert status(owner, t["id"])["status"] == "acknowledged"
    advance(5)
    reconcile(owner)
    assert status(owner, t["id"])["status"] == "filled"


def test_partial_fill_then_full(owner):
    t = approved(owner, "partial_fill", qty=10)
    submit(owner, t["id"])
    advance(3)
    reconcile(owner)
    s = status(owner, t["id"])
    assert s["status"] == "partially_filled" and s["filled_quantity"] == 4
    advance(91)
    reconcile(owner)
    s = status(owner, t["id"])
    assert s["status"] == "filled" and s["filled_quantity"] == 10 and len(s["executions"]) == 2


def test_fill_wins_race_against_cancel(owner):
    t = approved(owner, "fill_after_cancel")
    submit(owner, t["id"])
    r = owner.post(f"/api/orders/{t['id']}/cancel")
    assert r.json()["status"] == "cancel_requested"
    reconcile(owner)
    s = status(owner, t["id"])
    assert s["status"] == "filled" and any("before the cancel" in e["message"] for e in s["events"])


def test_cancel_open_batch(owner):
    t = approved(owner, "partial_fill", qty=10)
    submit(owner, t["id"])
    r = owner.post("/api/orders/cancel-open")
    assert r.status_code == 200 and t["id"] in r.json()["orders"]
    assert r.json()["results"][t["id"]] == "cancel_requested"
    reconcile(owner)
    assert status(owner, t["id"])["status"] == "cancelled"


def test_cancel_before_submission_and_live_mode_blocked(owner):
    t = approved(owner)
    r = owner.post(f"/api/orders/{t['id']}/cancel")
    assert r.json()["status"] == "cancelled" and r.json()["approval"]["status"] == "invalidated"
    owner.step_up()
    r = owner.put("/api/settings/trading-mode", {"mode": "live"})
    assert r.status_code == 403 and r.json()["code"] == "live_not_authorized"
    r = owner.put("/api/settings/trading-mode", {"mode": "paper"})
    assert r.status_code == 409 and r.json()["code"] == "broker_not_configured"

"""Adapter-independent BrokerAdapter contract (plan §12.2), run against MockAdapter and against IbkrAdapter with a
fake IB client. IBKR Paper itself stays "Implemented but externally unverified" (no account or gateway, D1)."""

import itertools
import secrets
from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.db import db_session
from app.modules.brokers.base import BrokerOrderState, OrderSpec, Preview
from app.modules.brokers.ibkr import IbkrAdapter
from app.modules.brokers.mock import MockAdapter


class FakeIb:
    """Same interface as IbAsyncClient; behaves like a minimal IB Gateway."""

    def __init__(self, *, fail_connect=False, place_error=None, place_status="Submitted", commission=1.25):
        self.connected = False
        self.fail_connect, self.place_error, self.place_status = fail_connect, place_error, place_status
        self.commission = commission
        self._ids = itertools.count(100)
        self._trades: list[dict] = []
        self._fills: list[dict] = []
        self.placed = 0

    def connect(self, host, port, client_id, timeout):
        if self.fail_connect:
            raise ConnectionError("gateway down")
        self.connected = True

    def is_connected(self):
        return self.connected

    def managed_accounts(self):
        return ["DU1234567"]

    def account_values(self):
        return [{"tag": "CashBalance", "value": "1000", "currency": "USD", "account": "DU1234567"},
                {"tag": "CashBalance", "value": "1000", "currency": "BASE", "account": "DU1234567"}]

    def positions(self):
        return []

    def qualify(self, symbol, sec_type, exchange, currency):
        return {"conid": 265598, "symbol": symbol, "exchange": exchange, "currency": currency}

    def what_if(self, contract, order):
        return {"commission": self.commission, "currency": "USD"}

    def place(self, contract, order):
        if self.place_error:
            raise self.place_error
        self.placed += 1
        t = {"order_id": next(self._ids), "perm_id": 1, "ref": order["ref"], "status": self.place_status,
             "filled": 0, "avg_price": 0}
        self._trades.append(t)
        return {"order_id": t["order_id"], "perm_id": 1, "status": t["status"]}

    def cancel(self, order_id):
        for t in self._trades:
            if t["order_id"] == order_id:
                t["status"] = "Cancelled"

    def trades(self):
        return [dict(t) for t in self._trades]

    def fills(self):
        return list(self._fills)

    # test driver
    def fill(self, ref, qty, price):
        t = next(t for t in self._trades if t["ref"] == ref)
        self._fills.append({"exec_id": f"E{secrets.token_hex(3)}", "ref": ref, "qty": qty, "price": price,
                            "at": "2026-10-19T14:00:00+00:00", "commission": 1.0})
        t["filled"] += qty
        t["avg_price"] = price
        t["status"] = "Filled" if t["filled"] >= 5 else "Submitted"


def _spec(ref=None, qty="5"):
    return OrderSpec(client_order_id=ref or f"DOPS-{secrets.token_hex(5)}", account_id="ACC", symbol="AAPL",
                     venue_mic="XNAS", currency="USD", broker_instrument_id="265598", side="buy",
                     quantity=Decimal(qty), order_type="limit", limit_price=Decimal("190.50"), stop_price=None,
                     tif="DAY", reference_price=Decimal("190.50"))


class MockDriver:
    def __init__(self, db):
        self.adapter = MockAdapter(db)
        self.db = db

    def fill(self, ref):
        from app.core.clock import Clock, FrozenClock, set_clock, utcnow
        from app.modules.brokers.mock import advance

        set_clock(FrozenClock(utcnow() + timedelta(seconds=10)))
        try:
            advance(self.db)
        finally:
            set_clock(Clock())


class IbDriver:
    def __init__(self):
        self.fake = FakeIb()
        self.adapter = IbkrAdapter(self.fake, mode="paper", host="127.0.0.1", port=4002, client_id=17)

    def fill(self, ref):
        self.fake.fill(ref, 5, 190.5)


@pytest.fixture(params=["mock", "ibkr-fake"])
def driver(request, database):
    if request.param == "mock":
        with db_session() as db:
            yield MockDriver(db)
    else:
        yield IbDriver()


def test_contract_capabilities_and_connection(driver):
    caps = driver.adapter.capabilities()
    assert {"venues", "instrument_types", "order_types", "tifs", "preview_costs", "label"} <= set(caps)
    assert {"market", "limit", "stop", "stop_limit"} <= set(caps["order_types"])
    conn = driver.adapter.connection_status()
    assert conn["status"] == "connected" and conn["account_id"]


def test_contract_lookup_and_preview(driver):
    inst = driver.adapter.lookup_instrument("AAPL", "XNAS", "USD")
    assert inst["venue_mic"] == "XNAS" and inst["broker_instrument_id"] and inst["tradable"] is True
    p = driver.adapter.preview(_spec())
    assert isinstance(p, Preview) and p.label
    assert p.commission is None or p.commission > 0


def test_contract_submit_is_idempotent_by_client_order_id(driver):
    spec = _spec()
    first = driver.adapter.submit(spec)
    second = driver.adapter.submit(spec)
    assert first.status == second.status == "accepted"
    assert first.broker_order_id == second.broker_order_id


def test_contract_status_fills_and_cancel(driver):
    assert driver.adapter.order_status("DOPS-unknown") == BrokerOrderState(found=False)
    assert driver.adapter.cancel("DOPS-unknown", None)["status"] == "rejected"
    spec = _spec()
    driver.adapter.submit(spec)
    st = driver.adapter.order_status(spec.client_order_id)
    assert st.found and st.status == "working"
    driver.fill(spec.client_order_id)
    st = driver.adapter.order_status(spec.client_order_id)
    assert st.status == "filled" and st.filled == Decimal(5)
    assert st.executions and {"exec_id", "qty", "price", "at"} <= set(st.executions[0])
    assert driver.adapter.cancel(spec.client_order_id, st.broker_order_id)["status"] == "rejected"

    open_spec = _spec()
    driver.adapter.submit(open_spec)
    assert driver.adapter.cancel(open_spec.client_order_id, None)["status"] == "requested"


# ---------- IBKR-specific failure behaviour ----------

def test_ibkr_not_configured_and_disconnected():
    a = IbkrAdapter(FakeIb(), mode="paper", host=None, port=4002, client_id=17)
    assert a.connection_status()["status"] == "not_configured"
    down = IbkrAdapter(FakeIb(fail_connect=True), mode="paper", host="127.0.0.1", port=4002, client_id=17)
    assert down.connection_status()["status"] == "disconnected"
    with pytest.raises(ValueError):
        IbkrAdapter(FakeIb(), mode="mock", host="127.0.0.1", port=4002, client_id=17)


def test_ibkr_uncertain_rejected_and_unknown_costs():
    timeout = IbkrAdapter(FakeIb(place_error=TimeoutError()), mode="paper", host="h", port=1, client_id=1)
    assert timeout.submit(_spec()).status == "uncertain"
    inactive = IbkrAdapter(FakeIb(place_status="Inactive"), mode="paper", host="h", port=1, client_id=1)
    assert inactive.submit(_spec()).status == "rejected"
    sentinel = IbkrAdapter(FakeIb(commission=1.7976931348623157e308), mode="paper", host="h", port=1, client_id=1)
    p = sentinel.preview(_spec())
    assert p.commission is None and p.label == "Unknown"
    assert IbkrAdapter(FakeIb(), mode="paper", host="h", port=1, client_id=1).lookup_instrument(
        "7203", "XTKS", "JPY") is not None
    assert IbkrAdapter(FakeIb(), mode="paper", host="h", port=1, client_id=1).lookup_instrument(
        "LUMI", "XTAE", "ILS") is None  # TASE is outside the adapter's venue map


def test_registry_never_builds_live_or_unconfigured_paper():
    from app.core.errors import AppError
    from app.modules.brokers.registry import get_adapter

    with db_session() as db:
        with pytest.raises(AppError) as live:
            get_adapter(db, "live")
        assert live.value.code == "live_not_authorized"
        with pytest.raises(AppError) as paper:
            get_adapter(db, "paper")
        assert paper.value.code == "broker_not_configured"

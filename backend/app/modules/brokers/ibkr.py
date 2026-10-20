"""Interactive Brokers adapter (TWS API through IB Gateway, client library ib_async).

STATUS: Implemented but externally unverified. It is contract-tested against a fake client only. No IBKR account,
gateway or subscription is configured or assumed (owner decision D1). Live trading is disabled and not authorized.

The adapter talks to an `IbClient` interface; `IbAsyncClient` is the real implementation, and the contract tests
use a fake with the same interface. The IBKR `orderRef` carries our client_order_id for idempotency and
reconciliation.
"""

from decimal import Decimal
from typing import Protocol

from app.modules.brokers.base import BrokerOrderState, OrderSpec, Preview, SubmitResult

IB_EXCHANGE = {"XNYS": "SMART", "XNAS": "SMART", "XLON": "LSE", "XETR": "IBIS", "XTKS": "TSEJ", "FXSP": "IDEALPRO"}
STATUS_MAP = {"PendingSubmit": "working", "ApiPending": "working", "PreSubmitted": "working", "Submitted": "working",
              "PendingCancel": "cancel_pending", "ApiCancelled": "cancelled", "Cancelled": "cancelled",
              "Filled": "filled", "Inactive": "rejected"}
ORDER_TYPE = {"market": "MKT", "limit": "LMT", "stop": "STP", "stop_limit": "STP LMT"}


class IbClient(Protocol):
    def connect(self, host: str, port: int, client_id: int, timeout: float) -> None: ...
    def is_connected(self) -> bool: ...
    def managed_accounts(self) -> list[str]: ...
    def account_values(self) -> list[dict]: ...
    def positions(self) -> list[dict]: ...
    def qualify(self, symbol: str, sec_type: str, exchange: str, currency: str) -> dict | None: ...
    def what_if(self, contract: dict, order: dict) -> dict: ...
    def place(self, contract: dict, order: dict) -> dict: ...
    def cancel(self, order_id: int) -> None: ...
    def trades(self) -> list[dict]: ...
    def fills(self) -> list[dict]: ...


class IbAsyncClient:
    """Thin wrapper over ib_async.IB. Requires a running, logged-in IB Gateway (manual 2FA)."""

    def __init__(self):
        from ib_async import IB

        self.ib = IB()

    def connect(self, host: str, port: int, client_id: int, timeout: float) -> None:
        self.ib.connect(host, port, clientId=client_id, timeout=timeout, readonly=False)

    def is_connected(self) -> bool:
        return self.ib.isConnected()

    def managed_accounts(self) -> list[str]:
        return list(self.ib.managedAccounts())

    def account_values(self) -> list[dict]:
        return [{"tag": v.tag, "value": v.value, "currency": v.currency, "account": v.account}
                for v in self.ib.accountValues()]

    def positions(self) -> list[dict]:
        return [{"symbol": p.contract.symbol, "conid": p.contract.conId, "qty": p.position, "avg_cost": p.avgCost,
                 "currency": p.contract.currency, "account": p.account} for p in self.ib.positions()]

    def _contract(self, c: dict):
        from ib_async import Contract

        return Contract(conId=int(c["conid"]), exchange=c.get("exchange", "SMART"))

    def _order(self, o: dict):
        from ib_async import Order

        return Order(action=o["action"], totalQuantity=float(o["qty"]), orderType=o["type"], lmtPrice=o.get("lmt") or 0,
                     auxPrice=o.get("aux") or 0, tif=o["tif"], orderRef=o["ref"], account=o["account"],
                     whatIf=o.get("what_if", False))

    def qualify(self, symbol: str, sec_type: str, exchange: str, currency: str) -> dict | None:
        from ib_async import Contract

        details = self.ib.reqContractDetails(Contract(symbol=symbol, secType=sec_type, exchange=exchange,
                                                      currency=currency))
        if not details:
            return None
        c = details[0].contract
        return {"conid": c.conId, "symbol": c.symbol, "exchange": c.exchange, "currency": c.currency}

    def what_if(self, contract: dict, order: dict) -> dict:
        state = self.ib.whatIfOrder(self._contract(contract), self._order({**order, "what_if": True}))
        return {"commission": getattr(state, "commission", None), "currency": getattr(state, "commissionCurrency", None)}

    def place(self, contract: dict, order: dict) -> dict:
        trade = self.ib.placeOrder(self._contract(contract), self._order(order))
        return {"order_id": trade.order.orderId, "perm_id": trade.order.permId, "status": trade.orderStatus.status}

    def cancel(self, order_id: int) -> None:
        for t in self.ib.trades():
            if t.order.orderId == order_id:
                self.ib.cancelOrder(t.order)

    def trades(self) -> list[dict]:
        return [{"order_id": t.order.orderId, "perm_id": t.order.permId, "ref": t.order.orderRef,
                 "status": t.orderStatus.status, "filled": t.orderStatus.filled,
                 "avg_price": t.orderStatus.avgFillPrice} for t in self.ib.trades()]

    def fills(self) -> list[dict]:
        return [{"exec_id": f.execution.execId, "ref": f.execution.orderRef, "qty": f.execution.shares,
                 "price": f.execution.price, "at": f.time.isoformat(),
                 "commission": getattr(f.commissionReport, "commission", None)} for f in self.ib.fills()]


class IbkrAdapter:
    name = "ibkr"

    def __init__(self, client: IbClient, *, mode: str, host: str | None, port: int, client_id: int,
                 account_id: str | None = None):
        if mode not in ("paper", "live"):
            raise ValueError("IbkrAdapter supports paper or live configurations only")
        self.client = client
        self.mode = mode
        self.host, self.port, self.client_id = host, port, client_id
        self.account_id = account_id

    def _ensure(self) -> None:
        if not self.host:
            raise ConnectionError("IBKR is not configured")
        if not self.client.is_connected():
            self.client.connect(self.host, self.port, self.client_id, timeout=10)

    def capabilities(self) -> dict:
        return {"venues": ["XNYS", "XNAS", "FXSP"], "instrument_types": ["equity", "etf", "fx"],
                "order_types": ["market", "limit", "stop", "stop_limit"], "tifs": ["DAY", "GTC"],
                "preview_costs": True, "label": "Broker what-if (when configured)",
                "note": "Proposed first verified scope: US stocks/ETFs and FX spot. Other venues unverified."}

    def connection_status(self) -> dict:
        if not self.host:
            return {"status": "not_configured", "account_id": None,
                    "detail": "IBKR is not configured. See Help → IBKR setup."}
        try:
            self._ensure()
            accounts = self.client.managed_accounts()
            return {"status": "connected", "account_id": self.account_id or (accounts[0] if accounts else None),
                    "detail": f"IB Gateway at {self.host}:{self.port}"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "disconnected", "account_id": None, "detail": f"Broker disconnected: {exc.__class__.__name__}"}

    def list_accounts(self) -> list[dict]:
        self._ensure()
        return [{"account_id": a, "type": "unknown"} for a in self.client.managed_accounts()]

    def get_balances(self) -> list[dict]:
        self._ensure()
        return [{"currency": v["currency"], "amount": v["value"]} for v in self.client.account_values()
                if v["tag"] == "CashBalance" and v["currency"] != "BASE"]

    def get_positions(self) -> list[dict]:
        self._ensure()
        return self.client.positions()

    def get_open_orders(self) -> list[dict]:
        self._ensure()
        return [{"order_ref": t["ref"], "broker_order_id": str(t["order_id"]), "status": STATUS_MAP.get(t["status"], t["status"])}
                for t in self.client.trades() if STATUS_MAP.get(t["status"]) in ("working", "cancel_pending")]

    def get_executions(self, since) -> list[dict]:
        self._ensure()
        return [f for f in self.client.fills() if f["at"] >= since.isoformat()]

    def lookup_instrument(self, symbol: str, venue_mic: str, currency: str) -> dict | None:
        if venue_mic not in IB_EXCHANGE:
            return None
        self._ensure()
        sec_type = "CASH" if venue_mic == "FXSP" else "STK"
        sym = symbol[:3] if sec_type == "CASH" else symbol
        found = self.client.qualify(sym, sec_type, IB_EXCHANGE[venue_mic], currency)
        if not found:
            return None
        return {"broker_instrument_id": str(found["conid"]), "symbol": symbol, "venue_mic": venue_mic,
                "currency": currency, "tradable": True}

    def _order_dict(self, o: OrderSpec, what_if: bool = False) -> dict:
        return {"action": o.side.upper(), "qty": o.quantity, "type": ORDER_TYPE[o.order_type],
                "lmt": float(o.limit_price) if o.limit_price else None,
                "aux": float(o.stop_price) if o.stop_price else None, "tif": o.tif, "ref": o.client_order_id,
                "account": o.account_id, "what_if": what_if}

    def _contract_dict(self, o: OrderSpec) -> dict:
        return {"conid": o.broker_instrument_id, "exchange": IB_EXCHANGE.get(o.venue_mic, "SMART")}

    def preview(self, order: OrderSpec) -> Preview:
        try:
            self._ensure()
            res = self.client.what_if(self._contract_dict(order), self._order_dict(order, True))
        except Exception:  # noqa: BLE001
            return Preview(None, None, "Unknown", "What-if preview unavailable; costs remain unknown.")
        if res.get("commission") is None or res["commission"] > 1e9:  # IB uses a huge sentinel for 'unset'
            return Preview(None, None, "Unknown", "The broker did not return a commission estimate.")
        return Preview(Decimal(str(res["commission"])), res.get("currency"), "Broker what-if estimate")

    def submit(self, order: OrderSpec) -> SubmitResult:
        try:
            self._ensure()
            existing = [t for t in self.client.trades() if t["ref"] == order.client_order_id]
            if existing:
                return SubmitResult("accepted", str(existing[0]["order_id"]), "Duplicate orderRef: existing order")
            placed = self.client.place(self._contract_dict(order), self._order_dict(order))
        except (TimeoutError, ConnectionError) as exc:
            return SubmitResult("uncertain", None, f"Outcome unknown: {exc.__class__.__name__}")
        status = STATUS_MAP.get(placed["status"], "working")
        if status == "rejected":
            return SubmitResult("rejected", str(placed["order_id"]), "Rejected by the broker (Inactive)")
        return SubmitResult("accepted", str(placed["order_id"]))

    def cancel(self, client_order_id: str, broker_order_id: str | None) -> dict:
        self._ensure()
        trade = next((t for t in self.client.trades() if t["ref"] == client_order_id), None)
        if trade is None or STATUS_MAP.get(trade["status"]) not in ("working",):
            return {"status": "rejected", "reason": "Order is not open at the broker."}
        self.client.cancel(trade["order_id"])
        return {"status": "requested"}

    def order_status(self, client_order_id: str) -> BrokerOrderState:
        self._ensure()
        trade = next((t for t in self.client.trades() if t["ref"] == client_order_id), None)
        if trade is None:
            return BrokerOrderState(found=False)
        execs = [{"exec_id": f["exec_id"], "qty": str(f["qty"]), "price": str(f["price"]), "at": f["at"],
                  "commission": str(f["commission"]) if f.get("commission") is not None else None}
                 for f in self.client.fills() if f["ref"] == client_order_id]
        filled = Decimal(str(trade["filled"]))
        status = STATUS_MAP.get(trade["status"], "working")
        if status == "working" and filled > 0:
            status = "partially_filled"
        return BrokerOrderState(found=True, status=status, filled=filled,
                                avg_price=Decimal(str(trade["avg_price"])) if trade["avg_price"] else None,
                                broker_order_id=str(trade["order_id"]), executions=execs)

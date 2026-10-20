"""Venue-agnostic broker adapter contract. Instruments are keyed by (venue MIC, broker instrument ID); capabilities
are declared, not assumed; cost estimates may be UNKNOWN. A future broker (e.g. an Israeli broker for TASE) only
needs a new adapter that passes the same contract tests."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Protocol

SubmitStatus = Literal["accepted", "rejected", "uncertain"]


@dataclass
class OrderSpec:
    client_order_id: str
    account_id: str
    symbol: str
    venue_mic: str
    currency: str
    broker_instrument_id: str | None
    side: str
    quantity: Decimal
    order_type: str
    limit_price: Decimal | None
    stop_price: Decimal | None
    tif: str
    reference_price: Decimal
    scenario: str | None = None  # Mock only


@dataclass
class SubmitResult:
    status: SubmitStatus
    broker_order_id: str | None = None
    reason: str | None = None


@dataclass
class BrokerOrderState:
    found: bool
    status: str | None = None  # working | partially_filled | filled | cancelled | rejected | cancel_pending
    filled: Decimal = Decimal(0)
    avg_price: Decimal | None = None
    broker_order_id: str | None = None
    executions: list[dict] = field(default_factory=list)  # {exec_id, qty, price, at, commission}
    reason: str | None = None


@dataclass
class Preview:
    commission: Decimal | None  # None = UNKNOWN
    commission_currency: str | None
    label: str  # "Simulated estimate" | "Broker what-if estimate" | "Unknown"
    detail: str | None = None


class BrokerAdapter(Protocol):
    name: str
    mode: str

    def capabilities(self) -> dict: ...
    def connection_status(self) -> dict: ...
    def list_accounts(self) -> list[dict]: ...
    def get_balances(self) -> list[dict]: ...
    def get_positions(self) -> list[dict]: ...
    def get_open_orders(self) -> list[dict]: ...
    def get_executions(self, since) -> list[dict]: ...
    def lookup_instrument(self, symbol: str, venue_mic: str, currency: str) -> dict | None: ...
    def preview(self, order: OrderSpec) -> Preview: ...
    def submit(self, order: OrderSpec) -> SubmitResult: ...
    def cancel(self, client_order_id: str, broker_order_id: str | None) -> dict: ...
    def order_status(self, client_order_id: str) -> BrokerOrderState: ...

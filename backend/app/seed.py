"""Idempotent synthetic seed data. Everything here is fictional and labelled Synthetic/Mock in the UI."""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.clock import utcnow
from app.core.logging import get_logger
from app.modules.brokers.models import BrokerConnection
from app.modules.calendar.models import CalendarEvent
from app.modules.markets.models import DataFeed, Instrument, Watchlist
from app.modules.markets.quotes import refresh_mock_quotes
from app.modules.orders.models import StopState
from app.modules.portfolio.models import CashBalance, ManualHolding, Portfolio, Position

log = get_logger("seed")

US_SCOPE = "Outside the first broker's initial order scope (US stocks/ETFs and FX spot)."
TASE_SCOPE = "TASE execution is out of scope for the first broker (owner decision D2). Record holdings manually."
INDEX = "Reference index – not tradable."

# symbol, name, venue, currency, kind, asset_class, tradable, reason, ref price, daily vol
INSTRUMENTS = [
    ("AAPL", "Apple Inc.", "XNAS", "USD", "equity", "equity", True, None, "230", "0.016"),
    ("MSFT", "Microsoft Corp.", "XNAS", "USD", "equity", "equity", True, None, "430", "0.014"),
    ("NVDA", "NVIDIA Corp.", "XNAS", "USD", "equity", "equity", True, None, "140", "0.028"),
    ("QQQ", "Invesco QQQ Trust", "XNAS", "USD", "etf", "equity", True, None, "480", "0.012"),
    ("SPY", "SPDR S&P 500 ETF", "XNYS", "USD", "etf", "equity", True, None, "560", "0.010"),
    ("JPM", "JPMorgan Chase & Co.", "XNYS", "USD", "equity", "equity", True, None, "210", "0.015"),
    ("SPX", "S&P 500 Index", "XNYS", "USD", "index", "index", False, INDEX, "5600", "0.010"),
    ("TEVA", "Teva Pharmaceutical (TASE)", "XTAE", "ILS", "equity", "equity", False, TASE_SCOPE, "65", "0.022"),
    ("LUMI", "Bank Leumi", "XTAE", "ILS", "equity", "equity", False, TASE_SCOPE, "38", "0.017"),
    ("POLI", "Bank Hapoalim", "XTAE", "ILS", "equity", "equity", False, TASE_SCOPE, "40", "0.017"),
    ("TA35", "TA-35 Index", "XTAE", "ILS", "index", "index", False, INDEX, "2400", "0.011"),
    ("7203", "Toyota Motor Corp.", "XTKS", "JPY", "equity", "equity", False, US_SCOPE, "2800", "0.017"),
    ("N225", "Nikkei 225 Index", "XTKS", "JPY", "index", "index", False, INDEX, "38000", "0.013"),
    ("600519", "Kweichow Moutai", "XSHG", "CNY", "equity", "equity", False, "Reference only.", "1500", "0.018"),
    ("SAP", "SAP SE", "XETR", "EUR", "equity", "equity", False, US_SCOPE, "210", "0.014"),
    ("SHEL", "Shell plc", "XLON", "GBP", "equity", "equity", False, US_SCOPE, "26", "0.013"),
    ("EURUSD", "Euro / US dollar", "FXSP", "USD", "fx", "fx", True, None, "1.08", "0.004"),
    ("USDJPY", "US dollar / Japanese yen", "FXSP", "JPY", "fx", "fx", True, None, "150", "0.005"),
    ("GBPUSD", "British pound / US dollar", "FXSP", "USD", "fx", "fx", True, None, "1.27", "0.004"),
    ("USDILS", "US dollar / Israeli shekel", "FXSP", "ILS", "fx", "fx", False,
     "Reference rate in this build (not in the verified FX list).", "3.70", "0.005"),
    ("USDCNY", "US dollar / Chinese yuan", "FXSP", "CNY", "fx", "fx", False, "Reference only.", "7.20", "0.002"),
]

MOCK_POSITIONS = [("AAPL", 120, "190"), ("MSFT", 60, "380"), ("NVDA", 200, "95"), ("SPY", 80, "470"), ("QQQ", 30, "400")]
MOCK_CASH = [("USD", "25000"), ("ILS", "40000"), ("EUR", "5000")]


def seed_reference(db: Session) -> None:
    existing = {i.symbol for i in db.scalars(select(Instrument))}
    for sym, name, mic, ccy, kind, ac, tradable, reason, ref, vol in INSTRUMENTS:
        if sym in existing:
            continue
        db.add(Instrument(symbol=sym, name=name, venue_mic=mic, currency=ccy, kind=kind, asset_class=ac,
                          tradable=tradable, not_tradable_reason=reason, broker_instrument_id=None,
                          reference_price=Decimal(ref), volatility=Decimal(vol)))
    db.flush()
    feeds = [
        ("mock_quotes", "Synthetic quotes (Mock)", "mock", "fresh", 300, {}),
        ("exchange_calendars", "Exchange calendars (offline library)", "computed", "fresh", 10 ** 9, {}),
        ("economic_calendar", "Economic calendar (FRED)", "external", "not_configured", 86400,
         {"note": "Optional enhancement, not configured. Economic events are user-entered or Mock."}),
        ("broker_market_data", "Broker market data (IBKR)", "external", "not_configured", 300,
         {"note": "Not configured. No real market data is shown anywhere."}),
    ]
    for key, name, label, state, stale, meta in feeds:
        if db.get(DataFeed, key) is None:
            db.add(DataFeed(key=key, name=name, source_label=label, state=state, stale_after_seconds=stale, meta=meta,
                            last_success_at=utcnow() if state == "fresh" else None))
    if db.get(StopState, 1) is None:
        db.add(StopState(id=1, engaged=False))
    if db.get(BrokerConnection, "mock") is None:
        db.add(BrokerConnection(mode="mock", broker="mock", status="connected", account_id="MOCK-0001",
                                last_connected_at=utcnow()))
    if db.scalar(select(Portfolio).where(Portfolio.mode == "mock")) is None:
        p = Portfolio(mode="mock", name="Synthetic portfolio", base_currency="ILS", account_id="MOCK-0001",
                      as_of=utcnow())
        db.add(p)
        db.flush()
        by_sym = {i.symbol: i for i in db.scalars(select(Instrument))}
        for sym, qty, cost in MOCK_POSITIONS:
            db.add(Position(portfolio_id=p.id, instrument_id=by_sym[sym].id, quantity=Decimal(qty),
                            avg_cost=Decimal(cost), as_of=utcnow()))
        for ccy, amount in MOCK_CASH:
            db.add(CashBalance(portfolio_id=p.id, currency=ccy, amount=Decimal(amount), as_of=utcnow()))
    db.flush()
    refresh_mock_quotes(db)


def seed_owner_samples(db: Session) -> None:
    """First-run conveniences for the owner workspace (all synthetic and deletable)."""
    from app.modules.knowledge.ingest import ingest_text
    from app.modules.knowledge.models import Document

    if db.scalar(select(func.count()).select_from(ManualHolding)) == 0:
        db.add(ManualHolding(name="Bank Leumi shares at an Israeli bank (sample)", symbol="LUMI", venue_mic="XTAE",
                             asset_class="equity", currency="ILS", quantity=Decimal(1500), unit_value=Decimal("36.40"),
                             value_as_of=utcnow(), notes="Synthetic manual holding. Edit or delete it."))
        db.add(ManualHolding(name="TA-35 index fund (sample)", symbol=None, venue_mic="XTAE", asset_class="fund",
                             currency="ILS", quantity=Decimal(300), unit_value=Decimal("241.10"), value_as_of=utcnow(),
                             notes="Synthetic manual holding."))
    if db.scalar(select(func.count()).select_from(Watchlist)) == 0:
        ids = [str(i.id) for i in db.scalars(select(Instrument).where(Instrument.symbol.in_(
            ["NVDA", "AAPL", "MSFT", "SPY", "EURUSD", "USDILS", "TA35", "7203"])))]
        db.add(Watchlist(name="Core watchlist", instrument_ids=ids))
    if db.scalar(select(func.count()).select_from(Document)) == 0:
        for path in sorted((get_settings().seed_dir / "docs").glob("*")):
            text = path.read_text(encoding="utf-8")
            heading = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.strip()), path.stem)
            ingest_text(db, None, f"[Sample] {heading[:180]}", path.name, text)
    if db.scalar(select(func.count()).select_from(CalendarEvent)) == 0:
        now = utcnow().replace(minute=0, second=0, microsecond=0)
        for days, hour, title in [(2, 12, "US CPI release (Mock)"), (6, 18, "FOMC rate decision (Mock)"),
                                  (9, 9, "Bank of Israel rate decision (Mock)")]:
            db.add(CalendarEvent(kind="economic", title=title, starts_at=(now + timedelta(days=days)).replace(hour=hour),
                                 timezone="UTC", source="mock", source_name="Synthetic economic calendar"))
    db.flush()

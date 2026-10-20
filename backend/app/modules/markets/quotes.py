"""Synthetic (Mock) market data: deterministic, labelled 'Synthetic', never presented as live."""

import hashlib
import math
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.clock import utcnow
from app.modules.markets.models import DataFeed, Instrument, QuoteSnapshot

EPOCH = date(2024, 1, 1)
FX_PAIRS = {"USDILS", "EURUSD", "USDJPY", "GBPUSD", "USDCNY"}


def _seed(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16)


@lru_cache(maxsize=256)
def _closes(symbol: str, ref: float, vol: float, end: date) -> tuple[tuple[date, float], ...]:
    days = (end - EPOCH).days + 1
    rng = np.random.default_rng(_seed("daily", symbol))
    rets = rng.normal(0.0002, vol, size=days)
    path = ref * np.exp(np.cumsum(rets))
    # Anchor so the long-run level stays near the reference price.
    path = path * (ref / float(np.median(path)))
    out = []
    for i in range(days):
        d = EPOCH + timedelta(days=i)
        if d.weekday() < 5:
            out.append((d, float(path[i])))
    return tuple(out)


def daily_bars(inst: Instrument, end: date, days: int = 180) -> list[dict]:
    closes = _closes(inst.symbol, float(inst.reference_price), float(inst.volatility), end)
    window = [c for c in closes if c[0] > end - timedelta(days=days)]
    bars = []
    prev = None
    for d, close in window:
        rng = np.random.default_rng(_seed("bar", inst.symbol, d.isoformat()))
        open_ = prev if prev is not None else close
        hi = max(open_, close) * (1 + abs(rng.normal(0, float(inst.volatility) / 2)))
        lo = min(open_, close) * (1 - abs(rng.normal(0, float(inst.volatility) / 2)))
        bars.append({"time": d.isoformat(), "open": round(open_, 4), "high": round(hi, 4), "low": round(lo, 4),
                     "close": round(close, 4)})
        prev = close
    return bars


def synthetic_price(inst: Instrument, at: datetime) -> tuple[Decimal, Decimal]:
    """Price and % change vs previous close at instant `at` (deterministic per minute)."""
    closes = _closes(inst.symbol, float(inst.reference_price), float(inst.volatility), at.date())
    prior = [c for c in closes if c[0] < at.date()]
    prev_close = prior[-1][1] if prior else float(inst.reference_price)
    minute = at.replace(second=0, microsecond=0)
    rng = np.random.default_rng(_seed("intraday", inst.symbol, minute.isoformat()))
    day_fraction = (minute.hour * 60 + minute.minute) / 1440
    drift = math.sin(day_fraction * math.pi * 2 + (_seed(inst.symbol) % 7)) * float(inst.volatility) * 0.4
    price = prev_close * (1 + drift + rng.normal(0, float(inst.volatility) * 0.05))
    change = (price / prev_close - 1) * 100
    digits = 4 if inst.kind == "fx" else 2
    return Decimal(str(round(price, digits))), Decimal(str(round(change, 4)))


def refresh_mock_quotes(db: Session) -> int:
    now = utcnow()
    count = 0
    for inst in db.scalars(select(Instrument)):
        price, change = synthetic_price(inst, now)
        q = db.get(QuoteSnapshot, inst.id)
        if q is None:
            q = QuoteSnapshot(instrument_id=inst.id, price=price, change_pct=change, as_of=now, source="mock")
            db.add(q)
        else:
            q.price, q.change_pct, q.as_of = price, change, now
        count += 1
    feed = db.get(DataFeed, "mock_quotes")
    if feed is not None:
        feed.state, feed.last_success_at, feed.last_error = "fresh", now, None
    return count


def _demo_snapshot(inst: Instrument, q: QuoteSnapshot | None) -> QuoteSnapshot | None:
    """The read-only demo has no worker; it computes synthetic quotes on read (transient, never written)."""
    if q is None or q.source != "mock":
        return q
    price, change = synthetic_price(inst, utcnow())
    return QuoteSnapshot(instrument_id=inst.id, price=price, change_pct=change, as_of=utcnow(), source="mock",
                         stale_override=False)


def quote_view(inst: Instrument, q: QuoteSnapshot | None, now: datetime | None = None) -> dict:
    now = now or utcnow()
    if get_settings().is_demo:
        q = _demo_snapshot(inst, q)
    if q is None:
        return {"instrument_id": str(inst.id), "symbol": inst.symbol, "price": None, "as_of": None,
                "freshness": "missing", "label": "Synthetic", "age_seconds": None}
    age = int((now - q.as_of).total_seconds())
    stale = q.stale_override or age > get_settings().quote_stale_seconds
    return {
        "instrument_id": str(inst.id), "symbol": inst.symbol, "price": float(q.price), "change_pct": float(q.change_pct),
        "currency": inst.currency, "as_of": q.as_of.isoformat(), "age_seconds": age,
        "freshness": "stale" if stale else "fresh",
        "label": "Synthetic" if q.source == "mock" else "Delayed",
    }


def latest_quotes(db: Session) -> dict:
    rows = db.execute(select(Instrument, QuoteSnapshot).outerjoin(QuoteSnapshot,
                                                                  QuoteSnapshot.instrument_id == Instrument.id)).all()
    if get_settings().is_demo:
        return {inst.symbol: (inst, _demo_snapshot(inst, q)) for inst, q in rows}
    return {inst.symbol: (inst, q) for inst, q in rows}


def fx_rate(db: Session, from_ccy: str, to_ccy: str, quotes: dict | None = None) -> tuple[Decimal, datetime | None]:
    """Convert via USD using synthetic FX quotes. Returns (rate, as_of)."""
    if from_ccy == to_ccy:
        return Decimal(1), None
    quotes = quotes or latest_quotes(db)

    def usd_per(ccy: str) -> tuple[Decimal, datetime | None]:
        if ccy == "USD":
            return Decimal(1), None
        direct, inverse = f"{ccy}USD", f"USD{ccy}"
        if direct in quotes and quotes[direct][1] is not None:
            q = quotes[direct][1]
            return Decimal(q.price), q.as_of
        if inverse in quotes and quotes[inverse][1] is not None:
            q = quotes[inverse][1]
            return Decimal(1) / Decimal(q.price), q.as_of
        raise KeyError(f"No synthetic FX rate for {ccy}")

    a, a_at = usd_per(from_ccy)
    b, b_at = usd_per(to_ccy)
    as_of = min([t for t in (a_at, b_at) if t is not None], default=None)
    return (a / b).quantize(Decimal("0.000001")), as_of


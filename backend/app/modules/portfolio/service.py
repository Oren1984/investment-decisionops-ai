"""Portfolio valuation and exposure (Computed). Mock figures are synthetic and labelled."""

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.modules.markets.models import Instrument
from app.modules.markets.quotes import fx_rate, latest_quotes, quote_view
from app.modules.portfolio.models import CashBalance, ManualHolding, Portfolio, Position
from app.modules.settings.service import home_currency, trading_mode


def get_portfolio(db: Session, mode: str) -> Portfolio | None:
    return db.scalar(select(Portfolio).where(Portfolio.mode == mode))


def _round(x: Decimal | float, n: int = 2) -> float:
    return round(float(x), n)


def valuation(db: Session, mode: str | None = None) -> dict:
    mode = mode or trading_mode(db)
    home = home_currency(db)
    portfolio = get_portfolio(db, mode)
    quotes = latest_quotes(db)
    now = utcnow()
    rows: list[dict] = []
    fx_as_of = None

    def to_home(amount: Decimal, ccy: str) -> Decimal:
        nonlocal fx_as_of
        rate, at = fx_rate(db, ccy, home, quotes)
        if at is not None:
            fx_as_of = at if fx_as_of is None else min(fx_as_of, at)
        return amount * rate

    if portfolio is not None:
        for pos, inst in db.execute(select(Position, Instrument).join(Instrument, Instrument.id == Position.instrument_id)
                                    .where(Position.portfolio_id == portfolio.id)):
            if pos.quantity == 0:
                continue
            q = quotes.get(inst.symbol, (inst, None))[1]
            price = Decimal(q.price) if q else Decimal(inst.reference_price)
            value = pos.quantity * price
            rows.append({
                "kind": "position", "instrument_id": str(inst.id), "symbol": inst.symbol, "name": inst.name,
                "venue_mic": inst.venue_mic, "asset_class": inst.asset_class, "currency": inst.currency,
                "quantity": _round(pos.quantity, 4), "avg_cost": _round(pos.avg_cost, 4), "price": _round(price, 4),
                "value_local": _round(value), "value_home": _round(to_home(value, inst.currency)),
                "unrealized_pct": _round((price / pos.avg_cost - 1) * 100) if pos.avg_cost else None,
                "quote": quote_view(inst, q, now), "source": "Synthetic" if mode == "mock" else "Broker",
            })
        for cash in db.scalars(select(CashBalance).where(CashBalance.portfolio_id == portfolio.id)):
            rows.append({"kind": "cash", "symbol": f"{cash.currency} cash", "name": f"Cash ({cash.currency})",
                         "venue_mic": None, "asset_class": "cash", "currency": cash.currency,
                         "value_local": _round(cash.amount), "value_home": _round(to_home(cash.amount, cash.currency)),
                         "source": "Synthetic" if mode == "mock" else "Broker"})

    manual = []
    for h in db.scalars(select(ManualHolding).order_by(ManualHolding.name)):
        value = h.quantity * h.unit_value
        manual.append({"kind": "manual", "id": str(h.id), "symbol": h.symbol or h.name, "name": h.name,
                       "venue_mic": h.venue_mic, "asset_class": h.asset_class, "currency": h.currency,
                       "quantity": _round(h.quantity, 4), "unit_value": _round(h.unit_value, 4),
                       "value_local": _round(value), "value_home": _round(to_home(value, h.currency)),
                       "value_as_of": h.value_as_of.isoformat(), "notes": h.notes, "source": "Manual"})

    all_rows = rows + manual
    total = sum(r["value_home"] for r in all_rows) or 1.0
    for r in all_rows:
        r["weight_pct"] = round(r["value_home"] / total * 100, 2)

    def group(key: str) -> list[dict]:
        acc: dict[str, float] = defaultdict(float)
        for r in all_rows:
            acc[r.get(key) or "—"] += r["value_home"]
        return sorted(({"key": k, "value_home": round(v, 2), "pct": round(v / total * 100, 2)} for k, v in acc.items()),
                      key=lambda x: -x["value_home"])

    return {
        "mode": mode, "home_currency": home, "label": "Synthetic" if mode == "mock" else "Broker data",
        "as_of": now.isoformat(), "fx_as_of": fx_as_of.isoformat() if fx_as_of else None,
        "total_home": round(sum(r["value_home"] for r in all_rows), 2),
        "positions": rows, "manual_holdings": manual,
        "exposure": {"asset_class": group("asset_class"), "currency": group("currency"), "venue": group("venue_mic")},
        "available": portfolio is not None,
    }


def post_trade(val: dict, instrument: Instrument, side: str, quantity: Decimal, price: Decimal, rate_home: Decimal) -> dict:
    """Simulated post-trade weights (Computed). Cash in the instrument currency moves opposite to the trade."""
    delta = float(quantity * price * rate_home) * (1 if side == "buy" else -1)
    total = val["total_home"]
    current = sum(r["value_home"] for r in val["positions"] if r.get("instrument_id") == str(instrument.id))
    new_value = current + delta
    return {
        "instrument_weight_before_pct": round(current / total * 100, 2) if total else 0.0,
        "instrument_weight_after_pct": round(new_value / total * 100, 2) if total else 0.0,
        "trade_value_home": round(abs(delta), 2),
        "label": "Computed",
    }

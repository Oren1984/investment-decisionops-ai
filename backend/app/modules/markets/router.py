import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from app.config import get_settings
from app.core import audit
from app.core.authz import Principal, perm
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import AppError, NotFound
from app.modules.markets.models import DataFeed, Instrument, QuoteSnapshot, Watchlist
from app.modules.markets.quotes import daily_bars, quote_view
from app.modules.markets.registry import all_venues
from app.modules.settings.service import trading_mode

router = APIRouter(prefix="/api/markets", tags=["markets"])


def instrument_out(inst: Instrument) -> dict:
    return {
        "id": str(inst.id), "symbol": inst.symbol, "name": inst.name, "venue_mic": inst.venue_mic,
        "currency": inst.currency, "kind": inst.kind, "asset_class": inst.asset_class, "tradable": inst.tradable,
        "not_tradable_reason": inst.not_tradable_reason, "broker_instrument_id": inst.broker_instrument_id,
    }


@router.get("/venues")
def venues(_=Depends(perm("read:sessions"))):
    return all_venues()


@router.get("/instruments")
def instruments(venue: str | None = None, db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:markets"))):
    stmt = select(Instrument).order_by(Instrument.venue_mic, Instrument.symbol)
    if venue:
        stmt = stmt.where(Instrument.venue_mic == venue)
    return [instrument_out(i) for i in db.scalars(stmt)]


@router.get("/quotes")
def quotes(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:markets"))):
    now = utcnow()
    rows = db.execute(select(Instrument, QuoteSnapshot).outerjoin(
        QuoteSnapshot, QuoteSnapshot.instrument_id == Instrument.id).order_by(Instrument.symbol)).all()
    return [{**instrument_out(i), "quote": quote_view(i, q, now)} for i, q in rows]


@router.get("/instruments/{instrument_id}/history")
def history(instrument_id: uuid.UUID, days: int = Query(180, ge=5, le=730), db: DB = Depends(get_db, scope="function"),
            _=Depends(perm("read:markets"))):
    inst = db.get(Instrument, instrument_id)
    if inst is None:
        raise NotFound("Instrument")
    return {"instrument": instrument_out(inst), "label": "Synthetic",
            "note": "Synthetic daily bars generated for Mock mode. Not real market data.",
            "bars": daily_bars(inst, utcnow().date() - timedelta(days=0), days)}


class StaleIn(BaseModel):
    stale: bool


@router.post("/instruments/{instrument_id}/simulate-stale")
def simulate_stale(instrument_id: uuid.UUID, body: StaleIn, db: DB = Depends(get_db, scope="function"),
                   principal: Principal = Depends(perm("write:markets"))):
    """Mock-only scenario helper: mark a synthetic quote as stale to exercise the stale-data order block."""
    if trading_mode(db) != "mock":
        raise AppError("mock_only", "Stale-quote simulation is available in Mock mode only.", status_code=409)
    q = db.get(QuoteSnapshot, instrument_id)
    if q is None:
        raise NotFound("Quote")
    q.stale_override = body.stale
    audit.record(db, "markets.simulate_stale", actor=principal, object_type="instrument", object_id=instrument_id,
                 details={"stale": body.stale})
    return {"ok": True}


class WatchlistIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    instrument_ids: list[uuid.UUID] = []


def _watch_out(w: Watchlist) -> dict:
    return {"id": str(w.id), "name": w.name, "instrument_ids": w.instrument_ids}


@router.get("/watchlists")
def watchlists(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:markets"))):
    return [_watch_out(w) for w in db.scalars(select(Watchlist).order_by(Watchlist.created_at))]


@router.post("/watchlists")
def create_watchlist(body: WatchlistIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:markets"))):
    w = Watchlist(owner_id=principal.user_id, name=body.name, instrument_ids=[str(i) for i in body.instrument_ids])
    db.add(w)
    db.flush()
    return _watch_out(w)


@router.put("/watchlists/{watchlist_id}")
def update_watchlist(watchlist_id: uuid.UUID, body: WatchlistIn, db: DB = Depends(get_db, scope="function"),
                     _=Depends(perm("write:markets"))):
    w = db.get(Watchlist, watchlist_id)
    if w is None:
        raise NotFound("Watchlist")
    w.name, w.instrument_ids = body.name, [str(i) for i in body.instrument_ids]
    return _watch_out(w)


@router.get("/feeds")
def feeds(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:markets"))):
    return [feed_out(f) for f in db.scalars(select(DataFeed).order_by(DataFeed.key))]


def feed_out(f: DataFeed) -> dict:
    """Effective state: a 'fresh' feed whose last success is older than its threshold is reported stale."""
    state = f.state
    if get_settings().is_demo and f.key == "mock_quotes":
        return {"key": f.key, "name": f.name, "source_label": f.source_label, "state": "fresh",
                "last_success_at": utcnow(), "last_error": None, "stale_since": None,
                "meta": {"note": "Demo: synthetic quotes are computed on read."}}
    if state == "fresh" and f.last_success_at and (utcnow() - f.last_success_at).total_seconds() > f.stale_after_seconds:
        state = "stale"
    return {"key": f.key, "name": f.name, "source_label": f.source_label, "state": state,
            "last_success_at": f.last_success_at, "last_error": f.last_error, "meta": f.meta,
            "stale_since": f.last_success_at if state == "stale" else None}

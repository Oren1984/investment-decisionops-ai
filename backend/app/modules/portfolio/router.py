import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DB

from app.core import audit
from app.core.authz import Principal, perm
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import NotFound
from app.modules.portfolio.models import ManualHolding
from app.modules.portfolio.service import valuation

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("")
def get_portfolio(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:portfolio"))):
    return valuation(db)


class ManualIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    symbol: str | None = Field(default=None, max_length=32)
    venue_mic: str | None = Field(default=None, max_length=10)
    asset_class: str = Field(default="equity", pattern="^(equity|fund|bond|cash|other)$")
    currency: str = Field(min_length=3, max_length=3)
    quantity: Decimal = Field(gt=0)
    unit_value: Decimal = Field(ge=0)
    value_as_of: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)


@router.post("/manual-holdings")
def create_manual(body: ManualIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:portfolio"))):
    h = ManualHolding(owner_id=principal.user_id, **body.model_dump(exclude={"value_as_of"}),
                      value_as_of=body.value_as_of or utcnow())
    h.currency = h.currency.upper()
    db.add(h)
    db.flush()
    audit.record(db, "portfolio.manual_holding_created", actor=principal, object_type="manual_holding", object_id=h.id)
    return {"id": str(h.id)}


@router.put("/manual-holdings/{holding_id}")
def update_manual(holding_id: uuid.UUID, body: ManualIn, db: DB = Depends(get_db, scope="function"),
                  principal: Principal = Depends(perm("write:portfolio"))):
    h = db.get(ManualHolding, holding_id)
    if h is None:
        raise NotFound("Holding")
    for k, v in body.model_dump(exclude={"value_as_of"}).items():
        setattr(h, k, v)
    h.currency = h.currency.upper()
    h.value_as_of = body.value_as_of or utcnow()
    audit.record(db, "portfolio.manual_holding_updated", actor=principal, object_type="manual_holding", object_id=h.id)
    return {"id": str(h.id)}


@router.delete("/manual-holdings/{holding_id}")
def delete_manual(holding_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:portfolio"))):
    h = db.get(ManualHolding, holding_id)
    if h is None:
        raise NotFound("Holding")
    db.delete(h)
    audit.record(db, "portfolio.manual_holding_deleted", actor=principal, object_type="manual_holding", object_id=holding_id)
    return {"ok": True}

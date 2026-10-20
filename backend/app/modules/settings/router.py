import json
import uuid
from pathlib import Path
from typing import Literal
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from app.config import get_settings
from app.core import audit
from app.core.authz import Principal, perm, require_step_up
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import AppError, NotFound
from app.modules.integrations import integration_statuses
from app.modules.ops.models import ExportFile
from app.modules.settings import data
from app.modules.settings.service import get_setting, put_setting

router = APIRouter(prefix="/api/settings", tags=["settings"])
DELETE_ALL_PHRASE = "DELETE ALL MY DATA"


@router.get("")
def get_all(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:settings"))):
    s = get_settings()
    return {"preferences": get_setting(db, "preferences"), "trading": get_setting(db, "trading"),
            "limits": get_setting(db, "limits"), "retention": get_setting(db, "retention"),
            "live_gate": {"env_flag": s.live_trading_enabled, "authorized": False,
                          "requirements": ["LIVE_TRADING_ENABLED=true in the environment", "Owner TOTP enabled",
                                           "Re-authentication (step-up)", "Checklist acknowledgement",
                                           "Completed Paper verification against a real IBKR Paper account"],
                          "status": "Disabled — not authorized in this build."},
            "modes_available": {"mock": True, "paper": s.ibkr_configured, "live": False},
            "profile": s.app_profile}


class PrefsIn(BaseModel):
    home_timezone: str
    home_currency: Literal["ILS", "USD", "EUR", "GBP", "JPY"] = "ILS"
    default_venue: str = "XNYS"

    @field_validator("home_timezone")
    @classmethod
    def _tz(cls, v):
        if v not in available_timezones():
            raise ValueError("Unknown IANA timezone")
        return v


@router.put("/preferences")
def set_prefs(body: PrefsIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:settings"))):
    value = put_setting(db, "preferences", body.model_dump())
    audit.record(db, "settings.preferences_changed", actor=principal, details=body.model_dump())
    return value


class ModeIn(BaseModel):
    mode: Literal["mock", "paper", "live"]


@router.put("/trading-mode")
def set_mode(body: ModeIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:settings"))):
    s = get_settings()
    if body.mode == "live":
        raise AppError("live_not_authorized", "Live trading is disabled and not authorized in this build.",
                       status_code=403, help_slug="modes")
    if body.mode == "paper" and not s.ibkr_configured:
        raise AppError("broker_not_configured", "Paper mode needs a configured IBKR Paper account and IB Gateway.",
                       status_code=409, help_slug="ibkr-setup")
    require_step_up(principal)
    value = put_setting(db, "trading", {"mode": body.mode})
    audit.record(db, "settings.trading_mode_changed", actor=principal, details={"mode": body.mode})
    return value


class LimitsIn(BaseModel):
    max_order_notional_home: float = Field(gt=0, le=1e9)
    max_position_pct: float = Field(gt=0, le=100)
    max_orders_per_day: int = Field(ge=1, le=500)
    price_collar_pct: float = Field(gt=0, le=50)
    block_market_orders_outside_session: bool = True
    allowlist: dict[str, list[str]] = {"mock": [], "paper": [], "live": []}


@router.put("/limits")
def set_limits(body: LimitsIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:settings"))):
    require_step_up(principal)
    value = put_setting(db, "limits", body.model_dump())
    audit.record(db, "settings.limits_changed", actor=principal, details=body.model_dump())
    return value


class RetentionIn(BaseModel):
    audit_years: int = Field(ge=1, le=20)
    run_details_years: int = Field(ge=1, le=20)
    session_days: int = Field(ge=1, le=365)
    backup_days: int = Field(ge=1, le=365)
    request_metrics_days: int = Field(ge=1, le=90)


@router.put("/retention")
def set_retention(body: RetentionIn, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:settings"))):
    value = put_setting(db, "retention", body.model_dump())
    audit.record(db, "settings.retention_changed", actor=principal, details=body.model_dump())
    return value


@router.get("/integrations")
def integrations(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:settings"))):
    return integration_statuses(db)


@router.get("/exports")
def exports(db: DB = Depends(get_db, scope="function"), _=Depends(perm("read:settings"))):
    return [{"id": str(e.id), "created_at": e.created_at, "size_bytes": e.size_bytes, "documents": len(e.document_ids)}
            for e in db.scalars(select(ExportFile).order_by(ExportFile.created_at.desc()))]


@router.post("/exports")
def create_export(db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:settings"))):
    e = data.create_export(db, principal.user_id)
    audit.record(db, "data.export_created", actor=principal, object_type="export", object_id=e.id,
                 details={"size_bytes": e.size_bytes})
    return {"id": str(e.id), "size_bytes": e.size_bytes}


@router.get("/exports/{export_id}/download")
def download_export(export_id: uuid.UUID, db: DB = Depends(get_db, scope="function"), principal: Principal = Depends(perm("write:settings"))):
    e = db.get(ExportFile, export_id)
    if e is None or not Path(e.path).exists():
        raise NotFound("Export")
    audit.record(db, "data.export_downloaded", actor=principal, object_type="export", object_id=e.id)
    return FileResponse(e.path, filename=Path(e.path).name, media_type="application/zip")


class DeleteAllIn(BaseModel):
    confirm_phrase: str


@router.post("/delete-all")
def delete_all(body: DeleteAllIn, response: Response, db: DB = Depends(get_db, scope="function"),
               principal: Principal = Depends(perm("write:settings"))):
    require_step_up(principal)
    if body.confirm_phrase.strip() != DELETE_ALL_PHRASE:
        raise AppError("confirmation_required", f"Type {DELETE_ALL_PHRASE} to confirm.", status_code=422)
    from app.modules.audit.models import ErasureLedger
    from app.modules.identity.service import clear_cookies, issue_setup_token
    from app.modules.knowledge.deletion import ledger_path

    result = data.delete_all(db)
    entry_id = uuid.uuid4()
    db.add(ErasureLedger(id=entry_id, at=utcnow(), kind="delete_all", entry=result))
    with ledger_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": str(entry_id), "at": utcnow().isoformat(), "kind": "delete_all",
                             "entry": result}) + "\n")
    audit.record(db, "data.delete_all", details=result)
    from app.seed import seed_reference

    seed_reference(db)
    issue_setup_token(db, force=True)
    clear_cookies(response)
    return {"ok": True, **result, "note": "All personal data was deleted. Set up the workspace again with a new "
                                          "setup token (docker compose exec api python -m app.cli setup-token)."}

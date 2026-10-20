"""Typed access to persisted settings with defaults."""

from copy import deepcopy

from sqlalchemy.orm import Session

from app.modules.settings.models import Setting

DEFAULTS: dict[str, dict] = {
    "preferences": {"home_timezone": "Asia/Jerusalem", "home_currency": "ILS", "default_venue": "XNYS"},
    "trading": {"mode": "mock"},
    "limits": {
        "max_order_notional_home": 150000,
        "max_position_pct": 20,
        "max_orders_per_day": 20,
        "price_collar_pct": 5,
        "block_market_orders_outside_session": True,
        "allowlist": {"mock": [], "paper": [], "live": []},  # empty list = all tradable instruments
    },
    "retention": {"audit_years": 7, "run_details_years": 2, "session_days": 30, "backup_days": 30,
                  "request_metrics_days": 7},
    "live_gate": {"checklist_acknowledged_at": None, "paper_verified_at": None, "activated_until": None},
}


def get_setting(db: Session, key: str) -> dict:
    row = db.get(Setting, key)
    value = deepcopy(DEFAULTS.get(key, {}))
    if row is not None:
        value.update(row.value)
    return value


def put_setting(db: Session, key: str, value: dict) -> dict:
    row = db.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.flush()
    return get_setting(db, key)


def home_timezone(db: Session) -> str:
    return get_setting(db, "preferences")["home_timezone"]


def home_currency(db: Session) -> str:
    return get_setting(db, "preferences")["home_currency"]


def trading_mode(db: Session) -> str:
    return get_setting(db, "trading")["mode"]

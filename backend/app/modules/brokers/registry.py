"""Adapter selection per mode. Mock can never be pointed at real endpoints; Live is never created in this build."""

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import AppError
from app.modules.brokers.mock import MockAdapter


def get_adapter(db: Session, mode: str):
    if mode == "mock":
        return MockAdapter(db)
    if mode == "paper":
        s = get_settings()
        if not s.ibkr_configured:
            raise AppError("broker_not_configured", "Paper mode needs an IBKR Paper account and IB Gateway. "
                           "It is not configured.", status_code=409, help_slug="ibkr-setup")
        from app.modules.brokers.ibkr import IbAsyncClient, IbkrAdapter

        return IbkrAdapter(IbAsyncClient(), mode="paper", host=s.ibkr_host, port=s.ibkr_paper_port,
                           client_id=s.ibkr_client_id)
    raise AppError("live_not_authorized", "Live trading is disabled and not authorized in this build.",
                   status_code=403, help_slug="modes")

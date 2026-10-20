"""Per-integration delivery status using exactly the four §5 labels. Mock success never counts as real-provider
verification; Paper never verifies Live."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.modules.ops.models import ModelVerification

VERIFIED_LOCALLY = "Implemented and verified locally"
EXT_UNVERIFIED = "Implemented but externally unverified"
VERIFIED_REAL = "Verified against a real configured provider"
BLOCKED = "Not implemented or blocked"


def integration_statuses(db: Session) -> list[dict]:
    s = get_settings()
    mv = db.scalar(select(ModelVerification).order_by(ModelVerification.at.desc()))
    model_status = (
        {"status": VERIFIED_LOCALLY, "detail": f"Model {mv.model_name} (digest {mv.model_digest[:12]}) ran a full "
                                               f"model-mode cycle on {mv.at.date().isoformat()}."}
        if mv else {"status": BLOCKED, "detail": "Model not run on this machine yet. Model mode is offered only when "
                                                 "the readiness probe passes."})
    return [
        {"key": "mock_broker", "name": "Mock broker adapter", "status": VERIFIED_LOCALLY,
         "detail": "Simulated execution with failure scenarios. Not a real broker."},
        {"key": "ibkr_paper", "name": "Interactive Brokers — Paper", "status": EXT_UNVERIFIED,
         "detail": ("Configured; run the Paper verification procedure to change this status." if s.ibkr_configured else
                    "No IBKR account or IB Gateway configured. Contract-tested against a fake client only.")},
        {"key": "ibkr_live", "name": "Interactive Brokers — Live", "status": BLOCKED,
         "detail": "Not authorized. LIVE_TRADING_ENABLED is off; Live is disabled in this build."},
        {"key": "zoom_api", "name": "Zoom scheduling (Server-to-Server OAuth)", "status": EXT_UNVERIFIED,
         "detail": "Configured but not verified." if s.zoom_configured else
         "No Zoom app configured. Contract-tested against a fake Zoom API only."},
        {"key": "zoom_manual", "name": "Meeting links (Zoom, Google Meet, Microsoft Teams, other https) and simulated "
         "meetings", "status": VERIFIED_LOCALLY,
         "detail": "Links are validated and saved locally; Open meeting opens the provider in a new tab (no provider API "
                   "is called). Simulated meetings never connect a real call."},
        {"key": "zoom_embedded", "name": "Embedded meeting video", "status": BLOCKED,
         "detail": "Not required (decision D-A, 20 Oct 2026): meetings open in the provider's own tab or app."},
        {"key": "local_model", "name": f"Local chat model (Ollama, {s.model_name})", **model_status},
        {"key": "embeddings", "name": "Local embeddings (fastembed)", "status": VERIFIED_LOCALLY if s.embeddings_enabled
         else BLOCKED, "detail": f"Enabled ({s.embedding_model})." if s.embeddings_enabled else
         "Disabled by configuration (EMBEDDINGS_ENABLED=false): keyword search only."},
        {"key": "market_data", "name": "Market data", "status": VERIFIED_LOCALLY,
         "detail": "Synthetic Mock quotes only. No real market-data feed is configured or claimed."},
        {"key": "exchange_calendars", "name": "Exchange calendars (offline library)", "status": VERIFIED_LOCALLY,
         "detail": "Computed offline from the installed exchange_calendars package; accuracy depends on its release."},
        {"key": "fred", "name": "Economic calendar feed (FRED)", "status": BLOCKED,
         "detail": "Optional enhancement, not built. Economic events are user-entered or Mock."},
    ]

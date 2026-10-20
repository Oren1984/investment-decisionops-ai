"""Import every module's models so metadata is complete (used by Alembic and tests)."""

from app.core.db import Base  # noqa: F401
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.brokers import models as broker_models  # noqa: F401
from app.modules.calendar import models as calendar_models  # noqa: F401
from app.modules.collaboration import models as collaboration_models  # noqa: F401
from app.modules.decisions import models as decision_models  # noqa: F401
from app.modules.help import models as help_models  # noqa: F401
from app.modules.identity import models as identity_models  # noqa: F401
from app.modules.knowledge import models as knowledge_models  # noqa: F401
from app.modules.markets import models as market_models  # noqa: F401
from app.modules.meetings import models as meeting_models  # noqa: F401
from app.modules.ops import models as ops_models  # noqa: F401
from app.modules.orders import models as order_models  # noqa: F401
from app.modules.portfolio import models as portfolio_models  # noqa: F401
from app.modules.settings import models as settings_models  # noqa: F401
from app.modules.workflows import models as workflow_models  # noqa: F401

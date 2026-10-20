"""Structured JSON logging with correlation IDs. Never log secrets or document content."""

import logging
import re
from contextvars import ContextVar

import structlog

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_SENSITIVE_KEYS = re.compile(
    r"pass(word)?|secret|token|authorization|cookie|totp|recovery|api_key|content|prompt|text|body|question", re.I
)
_ALWAYS_KEEP = {"event", "level", "timestamp", "logger", "correlation_id"}


def redact_event(_, __, event_dict):
    for key in list(event_dict):
        if key not in _ALWAYS_KEEP and _SENSITIVE_KEYS.search(key):
            event_dict[key] = "[redacted]"
    return event_dict


def _add_correlation(_, __, event_dict):
    cid = correlation_id.get()
    if cid and "correlation_id" not in event_dict:
        event_dict["correlation_id"] = cid
    return event_dict


def configure_logging(level: str = "INFO", stream=None) -> None:
    logging.basicConfig(format="%(message)s", level=level, stream=stream)
    for noisy in ("httpx", "httpcore", "LiteLLM", "litellm", "urllib3", "ib_async", "mcp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_correlation,
            redact_event,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(file=stream),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "app"):
    return structlog.get_logger(name)

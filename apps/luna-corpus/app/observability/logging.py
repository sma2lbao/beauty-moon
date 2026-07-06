"""structlog configuration with request-context binding."""
import logging
import sys

import structlog

from app.core.config import LogFormat, Settings
from app.security.context import (
    get_client_ip,
    get_request_id,
    get_tenant_id,
    get_user_id,
)


def bind_request_context(logger, method_name, event_dict):
    """structlog processor: inject request-scoped identity when present."""
    request_id = get_request_id()
    if request_id is not None:
        event_dict["request_id"] = request_id
    user_id = get_user_id()
    if user_id is not None:
        event_dict["user_id"] = user_id
    tenant_id = get_tenant_id()
    if tenant_id is not None:
        event_dict["tenant_id"] = tenant_id
    client_ip = get_client_ip()
    if client_ip is not None:
        event_dict["client_ip"] = client_ip
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure structlog + stdlib bridge. Idempotent."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors = [
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        bind_request_context,
    ]
    if settings.log_format == LogFormat.JSON:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Bridge stdlib logging (uvicorn, sqlalchemy) through the same stdout sink.
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processor=renderer,
        )
    )
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str = "luna"):
    """Return a bound structlog logger."""
    return structlog.get_logger(name)

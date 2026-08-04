"""Structured JSON logging to stdout (APP_SPECIFICATION.md §15).

Library choice (``structlog``) and the decision to emit JSON in every
environment, not just production, are recorded in
``docs/implementation/plan.md`` §6 (risks/assumptions) rather than a full ADR
— it's an isolated, reversible implementation detail, not one of the
architectural decisions ADRs 0001-0010 cover.
"""

from __future__ import annotations

import logging
import sys
from typing import cast

import structlog
from structlog.typing import FilteringBoundLogger

from book_app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure stdlib logging + structlog to emit one JSON object per line."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> FilteringBoundLogger:
    return cast(FilteringBoundLogger, structlog.get_logger(name))

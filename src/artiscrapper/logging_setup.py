"""
Structured logging setup — structlog + asgi-correlation-id.
Pattern 3 from 02-RESEARCH.md (lines 569-644).
OBS-05: Never log title, snippet, url, or reason in any log call.
"""

import hashlib
import logging
import sys
from typing import Any, MutableMapping
from urllib.parse import urlparse

import sentry_sdk
import structlog

from .config import settings


def add_correlation_id(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """
    Inject correlation_id from asgi-correlation-id contextvars.

    Phase 3 (D-16): also tags the Sentry scope so the Sentry UI Filter sidebar
    can join Sentry events to structlog logs by correlation_id. set_tag is a
    no-op when Sentry is uninitialized (DSN empty per D-14), so it's safe to
    always invoke. Wrapped in try/except Exception so a malformed sentry_sdk
    import (or future API drift) can NEVER break a request — observability
    code must not be load-bearing.
    """
    cid: str | None = None
    # asgi-correlation-id 5.x: check changelog for exact import path.
    # Try 5.x path first, fall back to 4.x path.
    try:
        from asgi_correlation_id import correlation_id  # 5.0 likely path

        cid = correlation_id.get()
    except (ImportError, AttributeError):
        try:
            from asgi_correlation_id.context import correlation_id  # 4.x fallback

            cid = correlation_id.get()
        except (ImportError, AttributeError):
            pass
    if cid:
        event_dict["correlation_id"] = cid
        # D-16: tag the Sentry scope so UI Filter can group by correlation_id.
        # Wrapped to never bubble an exception out of an observability path.
        try:
            sentry_sdk.get_current_scope().set_tag("correlation_id", cid)
        except Exception:
            pass
    return event_dict


def configure_logging(json_logs: bool = True, level: str = "INFO") -> None:
    """Configure structlog per Pattern 3 (02-RESEARCH.md lines 569-613)."""
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,  # pulls query_hash, stage, etc.
        add_correlation_id,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=True)
    )
    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(stream=sys.stdout, level=level, format="%(message)s")


# OBS-05 allow-list: only these fields are safe to include in candidate log events
SAFE_CANDIDATE_FIELDS = frozenset(
    {"url_hash", "host", "has_price", "freshness_signal", "confidence"}
)


def log_candidate_safe(log: Any, candidate: dict[str, Any], verdict: Any) -> None:
    """
    Emit structlog event with only allow-listed candidate fields (OBS-05).
    NEVER log title, snippet, url, or reason.
    """
    log.info(
        "candidate_classified",
        url_hash=hashlib.sha256(candidate["url"].encode()).hexdigest()[:12],
        host=urlparse(candidate["url"]).netloc,
        is_product=getattr(verdict, "is_product", None),
        confidence=round(getattr(verdict, "confidence", 0.0), 2),
        freshness_signal=getattr(verdict, "freshness_signal", "unknown"),
        # NEVER: title, snippet, url, reason
    )


# ──────────────────────────────────────────
# Phase 3 — Sentry SDK init (D-14, D-15, D-17)
# Module-import time so any boot exception (after Settings() loads) reaches
# Sentry. 03-RESEARCH.md §B2: init in logging_setup.py keeps observability
# init in one module per D-17.
# ──────────────────────────────────────────


def _init_sentry() -> None:
    """
    D-14: only init when SENTRY_DSN is set and non-empty.
    D-15: traces_sample_rate=0.1, profiles_sample_rate=0.0, send_default_pii=False.

    OBS-05: DSN value is NEVER logged. FastAPI + Httpx integrations are
    auto-detected from the installed package set (sentry-sdk 2.x behavior —
    no explicit integration kwargs needed).
    """
    dsn = settings.SENTRY_DSN
    if not dsn:
        return  # off in dev/test — D-14
    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=0.1,        # D-15: 10% of transactions
        profiles_sample_rate=0.0,      # D-15: profiling off
        send_default_pii=False,        # OBS-05 alignment
        # FastAPI + Httpx integrations auto-detected (sentry-sdk 2.x)
    )


# Run at module import time so `from .logging_setup import configure_logging`
# in main.py transitively triggers init BEFORE lifespan runs (per D-17 +
# 03-RESEARCH.md §B2).
_init_sentry()

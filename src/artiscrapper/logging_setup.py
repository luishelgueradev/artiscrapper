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

import structlog


def add_correlation_id(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Inject correlation_id from asgi-correlation-id contextvars."""
    # asgi-correlation-id 5.x: check changelog for exact import path.
    # Try 5.x path first, fall back to 4.x path.
    try:
        from asgi_correlation_id import correlation_id  # 5.0 likely path

        if cid := correlation_id.get():
            event_dict["correlation_id"] = cid
    except (ImportError, AttributeError):
        try:
            from asgi_correlation_id.context import correlation_id  # 4.x fallback

            if cid := correlation_id.get():
                event_dict["correlation_id"] = cid
        except (ImportError, AttributeError):
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

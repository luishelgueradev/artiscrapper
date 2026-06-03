"""
Phase 3 — Robustness — X-API-Key authentication module.

Provides:
  - _parse_api_keys(): split settings.API_KEYS on commas (D-01).
  - API_KEYS: module-load cache of the parsed set (D-01 — rotation
    requires container restart, no per-request re-parsing).
  - verify_api_key(request): FastAPI dependency that raises 401 with
    WWW-Authenticate=ApiKey for missing/unknown X-API-Key (D-03).
  - get_api_key(request): slowapi key_func — returns the header value or
    the string "anonymous". MUST NOT raise (slowapi treats key_func
    exceptions as 500 — see 03-RESEARCH.md §C1 / Pitfall 3).

OBS-05: the API-key VALUE is NEVER logged. logging_setup.SAFE_CANDIDATE_FIELDS
is not extended — auth fields stay outside the allow-list.

Reference analogs (03-PATTERNS.md §"src/artiscrapper/auth.py"):
  Pattern S4 — module-import-time config-derived cache (mirrors
  llm.py::_RESOLVED_MODEL + config.py::settings).
"""

import structlog
from fastapi import HTTPException, Request, status

from .config import settings

log = structlog.get_logger()


def _parse_api_keys() -> set[str]:
    """
    Parse comma-separated `settings.API_KEYS` (D-01).

    Empty entries (e.g., trailing commas, all-whitespace tokens) are dropped.
    Whitespace around each key is stripped. Returns an empty set if API_KEYS
    is unset or contains no usable tokens.
    """
    raw = settings.API_KEYS or ""
    return {k.strip() for k in raw.split(",") if k.strip()}


# Module-load cache — D-01 says rotation requires container restart.
# Re-parsing on every request would be wasted work for the single-tenant
# Sánchez Repuestos deploy.
API_KEYS: set[str] = _parse_api_keys()


def verify_api_key(request: Request) -> str:
    """
    FastAPI dependency — enforces X-API-Key auth (D-01, D-03).

    Raises HTTPException(401, WWW-Authenticate=ApiKey) for missing OR unknown
    key. Returns the key string on success so callers can audit-log the
    consumer identity (but OBS-05 forbids logging the value itself).
    """
    key = request.headers.get("X-API-Key")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    if key not in API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return key


def get_api_key(request: Request) -> str:
    """
    slowapi `key_func` — buckets per-key rate-limit counters.

    Returns the X-API-Key header value or the literal "anonymous" if absent.
    MUST NOT raise: slowapi 0.1.9 treats key_func exceptions as a 500
    response (per 03-RESEARCH.md §C1 / Pitfall 3). The 401 is enforced
    separately by `verify_api_key` as a FastAPI Depends.
    """
    return request.headers.get("X-API-Key", "anonymous")


# OBS-05: log only the COUNT of configured keys, never the keys themselves.
# A dev-misconfiguration warning helps Luis catch "I forgot to set API_KEYS"
# at boot, but the actual key values stay out of logs.
if not API_KEYS:
    log.warning(
        "api_keys_empty",
        message="API_KEYS is empty — /search will reject ALL requests with 401",
    )

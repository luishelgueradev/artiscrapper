"""
Unit tests for src/artiscrapper/main.py module-level invariants.

Phase 3.1 D-05 (Pattern B): the slowapi rate-limit strings are derived from
settings at module-load via two constants `_RATE_LIMIT_PER_MINUTE` and
`_RATE_LIMIT_PER_DAY`. Those constants are the single source of truth — the
`@limiter.limit(...)` decorators on POST /search and the `rate_limit_init`
log line both read from them. The test in this file pins that invariant:
if a refactor disconnects the constants from settings (drift between
Settings and decorator argument — R-A3), this test fires before the drift
reaches prod.
"""

import atexit
import os
import shutil
import tempfile

# Env vars MUST be set BEFORE importing src.artiscrapper.main below,
# because pydantic-settings reads env once at first Settings() call.
# Mirrors the WR-04 pattern in tests/test_health.py.
_TMP_DB_DIR = tempfile.mkdtemp(prefix="artiscrapper-test-main-")
_TMP_DB_PATH = os.path.join(_TMP_DB_DIR, "cache.db")
atexit.register(lambda: shutil.rmtree(_TMP_DB_DIR, ignore_errors=True))

os.environ.setdefault("LLM_ROUTER_BEARER_TOKEN", "test-token-main")
os.environ.setdefault("CACHE_DB_PATH", _TMP_DB_PATH)
# Cross-test contract: merge our test key into any existing API_KEYS so
# we don't clobber a sibling test file's keys.
_tm_existing_keys = os.environ.get("API_KEYS", "").strip()
_tm_existing_set = {k.strip() for k in _tm_existing_keys.split(",") if k.strip()}
_tm_merged = _tm_existing_set | {"test-key-main"}
os.environ["API_KEYS"] = ",".join(sorted(_tm_merged))
os.environ.setdefault("SENTRY_DSN", "")


def test_rate_limit_constants_match_settings():
    """
    Phase 3.1 D-05 / R-A3: assert the module-level rate-limit constants
    in src.artiscrapper.main equal the f-string of
    settings.API_RATE_PER_MINUTE / API_RATE_PER_DAY exactly.

    These constants are the single place in the codebase where the
    decorator-argument string is built. If a future refactor:
      - changes the f-string format (e.g. uses "/min" instead of "/minute"),
      - drops the constant entirely and reverts to a hardcoded literal,
      - replaces settings.* with a different source,
    this test fires immediately — before the drift reaches the /search
    decorator at module-load or the `rate_limit_init` log line.

    NOTE: We assert the constant equals `f"{settings.API_RATE_PER_MINUTE}/minute"`
    rather than the literal string "60/minute" so the test does not need
    updating every time the env-var default is bumped.
    """
    from src.artiscrapper import main
    from src.artiscrapper.config import settings

    expected_minute = f"{settings.API_RATE_PER_MINUTE}/minute"
    expected_day = f"{settings.API_RATE_PER_DAY}/day"

    assert main._RATE_LIMIT_PER_MINUTE == expected_minute, (
        f"D-05 drift: main._RATE_LIMIT_PER_MINUTE={main._RATE_LIMIT_PER_MINUTE!r} "
        f"does not match expected {expected_minute!r}. "
        f"The Pattern B invariant is broken — the /search decorator and "
        f"rate_limit_init log line are no longer in sync with settings."
    )
    assert main._RATE_LIMIT_PER_DAY == expected_day, (
        f"D-05 drift: main._RATE_LIMIT_PER_DAY={main._RATE_LIMIT_PER_DAY!r} "
        f"does not match expected {expected_day!r}. "
        f"The Pattern B invariant is broken — the /search decorator and "
        f"rate_limit_init log line are no longer in sync with settings."
    )

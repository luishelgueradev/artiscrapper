"""
D-02 / D-04: per-API-key rate limit (60/min stacked with 10000/day).

Test (RED until Task 3 stacks @limiter.limit on /search):
  - test_rate_limit_per_minute_returns_429: 61 sequential POST /search with
    the SAME valid X-API-Key within <60s → request #61 returns 429 with a
    digit-string Retry-After header.

D-04 reminder: slowapi defaults to in-memory MemoryStorage, so reloading the
limiter for each test is necessary to avoid cross-test counter bleed. We
construct a fresh TestClient inside the test (NOT a module-level fixture).
"""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

# Env vars BEFORE importing the app.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ.setdefault("LLM_ROUTER_BEARER_TOKEN", "test-token-rl")
os.environ.setdefault("CACHE_DB_PATH", _tmp_db.name)
# Append our test key to any existing API_KEYS so we don't clobber a
# sibling test file's keys (Phase 3 cross-test contract — see
# tests/integration/test_challenge_backoff.py module docstring).
_rl_existing_keys = os.environ.get("API_KEYS", "").strip()
_rl_our_key = "test-key-1"
if _rl_our_key not in _rl_existing_keys.split(","):
    os.environ["API_KEYS"] = (
        f"{_rl_existing_keys},{_rl_our_key}" if _rl_existing_keys else _rl_our_key
    )
os.environ.setdefault("SENTRY_DSN", "")

from fastapi.testclient import TestClient  # noqa: E402

from src.artiscrapper import auth as _auth_module  # noqa: E402
from src.artiscrapper.main import app  # noqa: E402

# CROSS-TEST IMPORT-ORDER DEFENSE (Phase 3): if a sibling test file
# imported `app` BEFORE this file's `os.environ.setdefault(...)` lines,
# both `auth.API_KEYS` AND `config.settings.API_KEYS` are cached with
# the sibling's values. `_parse_api_keys()` reads from cached settings,
# so we MUST parse the live env directly to rebuild auth.API_KEYS.
_live_keys = os.environ.get("API_KEYS", "")
_auth_module.API_KEYS = {k.strip() for k in _live_keys.split(",") if k.strip()}


def _make_mock_browser() -> MagicMock:
    mock_page = AsyncMock()
    mock_page.evaluate = AsyncMock(return_value=1)
    mock_page.goto = AsyncMock(return_value=None)
    mock_page.close = AsyncMock()

    mock_ctx = AsyncMock()
    mock_ctx.new_page = AsyncMock(return_value=mock_page)
    mock_ctx.close = AsyncMock()

    browser = MagicMock()
    browser.is_connected.return_value = True
    browser.new_context = AsyncMock(return_value=mock_ctx)
    browser.close = AsyncMock()
    return browser


def test_rate_limit_per_minute_returns_429(monkeypatch):
    """D-02: 61 POSTs in <60s with same X-API-Key → request #61 is 429."""
    mock_browser = _make_mock_browser()

    async def _fake_launch_async(**kwargs):
        return mock_browser

    monkeypatch.setattr("src.artiscrapper.main.launch_async", _fake_launch_async)

    # Mock fetch_serp + router_health_check so each request returns fast.
    async def _fake_fetch_serp(*args, **kwargs):
        return ("<html><body></body></html>", None)

    async def _fake_router_health(*args, **kwargs):
        return False

    monkeypatch.setattr("src.artiscrapper.main.fetch_serp", _fake_fetch_serp)
    monkeypatch.setattr(
        "src.artiscrapper.main.router_health_check", _fake_router_health
    )

    # Reset the slowapi limiter store to avoid counter bleed from prior tests
    # that may have hit /search with the same key.
    try:
        limiter = app.state.limiter  # type: ignore[attr-defined]
        if hasattr(limiter, "reset"):
            limiter.reset()
    except (AttributeError, Exception):
        pass

    headers = {"X-API-Key": "test-key-1"}
    body = {"query": "rate-limit-probe"}

    with TestClient(app) as client:
        # Reset limiter again now that lifespan has set it up.
        try:
            limiter = app.state.limiter  # type: ignore[attr-defined]
            if hasattr(limiter, "reset"):
                limiter.reset()
        except (AttributeError, Exception):
            pass

        # 60 should pass auth (status != 401 and != 429)
        for i in range(60):
            r = client.post("/search", headers=headers, json=body)
            assert r.status_code != 401, (
                f"req {i + 1}/60 returned 401 — auth must pass for the valid key; "
                f"body={r.text[:120]}"
            )
            assert r.status_code != 429, (
                f"req {i + 1}/60 returned 429 prematurely — "
                f"60/min should NOT trip on req #{i + 1}; body={r.text[:120]}"
            )

        # The 61st should hit the 60/min cap.
        r61 = client.post("/search", headers=headers, json=body)
        assert r61.status_code == 429, (
            f"D-02: req #61 should be 429, got {r61.status_code}: {r61.text[:200]}"
        )
        retry_after = r61.headers.get("Retry-After")
        assert retry_after is not None, (
            "D-02: 429 response must carry a Retry-After header"
        )
        assert retry_after.isdigit(), (
            f"D-02: Retry-After must be a digit-string, got {retry_after!r}"
        )

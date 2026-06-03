"""
D-01 / D-03: X-API-Key authentication on /search.

Pattern S5 (TestClient + monkeypatched cloakbrowser) from
03-PATTERNS.md — env vars MUST be set BEFORE the `from src.artiscrapper.main
import app` line so pydantic-settings picks them up.

Tests (all RED until Task 3 wires verify_api_key into main.py):
  - test_missing_key_returns_401: POST /search without X-API-Key → 401 +
    WWW-Authenticate=ApiKey
  - test_xapikey_header_required: POST /search with unknown key → 401 +
    WWW-Authenticate=ApiKey
  - test_valid_key_passes_auth: POST /search with valid key from API_KEYS env
    → response is NOT 401 and NOT 429 (the body may be 200/503 depending on
    the mocked pipeline — auth is what we're pinning).
"""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

# Set env vars BEFORE importing the app (pydantic-settings reads at import).
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ.setdefault("LLM_ROUTER_BEARER_TOKEN", "test-token-auth")
os.environ["CACHE_DB_PATH"] = _tmp_db.name
os.environ["API_KEYS"] = "test-key-1,test-key-2"
# Keep Sentry off — these tests don't exercise it.
os.environ.setdefault("SENTRY_DSN", "")

from fastapi.testclient import TestClient  # noqa: E402

from src.artiscrapper.main import app  # noqa: E402


def _make_mock_browser() -> MagicMock:
    """Create a mock browser that satisfies lifespan and pipeline needs."""
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


@pytest.fixture
def test_client(monkeypatch):
    """TestClient with lifespan running but cloakbrowser launch_async mocked out."""
    mock_browser = _make_mock_browser()

    async def _fake_launch_async(**kwargs):
        return mock_browser

    monkeypatch.setattr("src.artiscrapper.main.launch_async", _fake_launch_async)

    # Also mock fetch_serp so the route doesn't try a real Google round-trip.
    async def _fake_fetch_serp(*args, **kwargs):
        # Return a (html, block_reason) tuple — minimal empty SERP, no block.
        return ("<html><body></body></html>", None)

    monkeypatch.setattr("src.artiscrapper.main.fetch_serp", _fake_fetch_serp)

    # Stub LLM health check so the curator goes degraded-but-non-fatal in tests.
    async def _fake_router_health(*args, **kwargs):
        return False

    monkeypatch.setattr(
        "src.artiscrapper.main.router_health_check", _fake_router_health
    )

    with TestClient(app) as client:
        app.state.browser = mock_browser
        yield client


def test_missing_key_returns_401(test_client):
    """D-03: POST /search with NO X-API-Key → 401 + WWW-Authenticate=ApiKey."""
    resp = test_client.post("/search", json={"query": "filtro aceite"})
    assert resp.status_code == 401, (
        f"D-03: expected 401 without X-API-Key, got {resp.status_code}: {resp.text}"
    )
    assert resp.headers.get("WWW-Authenticate") == "ApiKey", (
        f"D-03: WWW-Authenticate header missing or wrong: "
        f"{resp.headers.get('WWW-Authenticate')!r}"
    )


def test_xapikey_header_required(test_client):
    """D-03: POST /search with UNKNOWN X-API-Key → 401 + WWW-Authenticate=ApiKey."""
    resp = test_client.post(
        "/search",
        json={"query": "filtro aceite"},
        headers={"X-API-Key": "this-key-does-not-exist"},
    )
    assert resp.status_code == 401, (
        f"D-03: expected 401 for unknown key, got {resp.status_code}: {resp.text}"
    )
    assert resp.headers.get("WWW-Authenticate") == "ApiKey", (
        f"D-03: WWW-Authenticate header missing or wrong: "
        f"{resp.headers.get('WWW-Authenticate')!r}"
    )


def test_valid_key_passes_auth(test_client):
    """D-01: POST /search with a valid X-API-Key reaches the route body."""
    resp = test_client.post(
        "/search",
        json={"query": "filtro aceite"},
        headers={"X-API-Key": "test-key-1"},
    )
    # Auth passed: NOT 401 and NOT 429. Body may be 200/503 depending on the
    # mocked pipeline (LLM down → degraded; empty SERP → empty results).
    assert resp.status_code != 401, (
        f"D-01: valid key should NOT yield 401, got 401: {resp.text}"
    )
    assert resp.status_code != 429, (
        f"D-01: single request should NOT yield 429, got 429: {resp.text}"
    )

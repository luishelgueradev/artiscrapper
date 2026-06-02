"""
Health endpoint tests.
OBS-01: GET /health — cheap liveness check.
OBS-02: GET /health/deep — real Cloak nav + LLM HEAD probe.
Pattern 11 from 02-RESEARCH.md (lines 1233-1293).
"""
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest
import respx
import httpx

# Set required env vars before importing app.
# CACHE_DB_PATH must point to a writable location so lifespan aiosqlite.connect works.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ.setdefault("LLM_ROUTER_BEARER_TOKEN", "test-token-health")
os.environ["CACHE_DB_PATH"] = _tmp_db.name

from fastapi.testclient import TestClient  # noqa: E402
from src.artiscrapper.main import app  # noqa: E402


def _make_mock_browser() -> MagicMock:
    """Create a mock browser that satisfies lifespan and test needs."""
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
    """
    TestClient with lifespan running but cloakbrowser launch_async mocked out.
    The lifespan boots aiosqlite (tmp db) + launches a mock browser.
    """
    mock_browser = _make_mock_browser()

    async def _fake_launch_async(**kwargs):
        return mock_browser

    monkeypatch.setattr("src.artiscrapper.main.launch_async", _fake_launch_async)

    with TestClient(app) as client:
        # Override the real browser with our controllable mock
        # (the recycle loop may have swapped it; reset to known state)
        app.state.browser = mock_browser
        yield client


def test_health_shape(test_client):
    """OBS-01: GET /health returns 200 with expected JSON shape."""
    resp = test_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    # All four keys must be present and non-null
    for key in ("status", "cloak", "llm", "cache"):
        assert key in body, f"Missing key: {key}"
        assert body[key] is not None, f"Key {key} is None"


@respx.mock
def test_health_deep_shape(test_client):
    """OBS-02: GET /health/deep returns cloak and llm status fields with mocked Cloak nav."""
    # Mock the LLM /healthz response (SPIKE.md §LLM confirmed /healthz with z)
    llm_url = os.environ.get("LLM_ROUTER_URL", "http://127.0.0.1:3210")
    respx.get(f"{llm_url}/healthz").mock(
        return_value=httpx.Response(200)
    )

    resp = test_client.get("/health/deep")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("status", "cloak", "llm", "cache"):
        assert key in body, f"Missing key: {key}"
        assert body[key] is not None, f"Key {key} is None"
    # Cloak deep: should start with "ok" when mocked successfully
    assert body["cloak"].startswith("ok"), (
        f"Expected cloak to start with 'ok', got: {body['cloak']}"
    )

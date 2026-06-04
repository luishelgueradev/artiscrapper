"""
Health endpoint tests.
OBS-01: GET /health — cheap liveness check.
OBS-02: GET /health/deep — real Cloak nav + LLM HEAD probe.
Pattern 11 from 02-RESEARCH.md (lines 1233-1293).
"""

import atexit
import os
import shutil
import tempfile
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

# WR-04 (Phase 3.1): tempfile.mkdtemp + atexit cleanup eliminates the
# orphan /tmp/tmp*.db leak that the previous named-temp-file pattern
# (with delete=False) produced every test run. The tmp DIR (not just the
# file) is rm-recursed at interpreter exit.
#
# CACHE_DB_PATH MUST be set at module-import time (before
# `from src.artiscrapper.main import app` below) because pydantic-settings
# reads env once at first Settings() call. pytest's `tmp_path` is
# function-scope and fires too late — that's why mkdtemp + atexit are
# the right shape here, not the `tmp_path` fixture.
_TMP_DB_DIR = tempfile.mkdtemp(prefix="artiscrapper-test-health-")
_TMP_DB_PATH = os.path.join(_TMP_DB_DIR, "cache.db")
atexit.register(lambda: shutil.rmtree(_TMP_DB_DIR, ignore_errors=True))

os.environ.setdefault("LLM_ROUTER_BEARER_TOKEN", "test-token-health")
os.environ.setdefault("CACHE_DB_PATH", _TMP_DB_PATH)
# ↑ WR-04: setdefault (not bracket assignment) honors the cross-test
# contract — first-importing test wins, siblings do not clobber.
# CR-03: /health/deep is now gated behind verify_api_key. Merge our test key
# into any existing API_KEYS (cross-test contract — see test_auth.py).
_hl_existing_keys = os.environ.get("API_KEYS", "").strip()
_hl_existing_set = {k.strip() for k in _hl_existing_keys.split(",") if k.strip()}
_hl_merged = _hl_existing_set | {"test-key-health"}
os.environ["API_KEYS"] = ",".join(sorted(_hl_merged))

from fastapi.testclient import TestClient  # noqa: E402

from src.artiscrapper import auth as _auth_module  # noqa: E402
from src.artiscrapper.main import app  # noqa: E402

# CR-03: refresh the auth module's API_KEYS set (captured at first import) so
# 'test-key-health' is honored even if a sibling test file imported first.
_hl_live_keys = os.environ.get("API_KEYS", "")
_auth_module.API_KEYS = {k.strip() for k in _hl_live_keys.split(",") if k.strip()}


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
    respx.get(f"{llm_url}/healthz").mock(return_value=httpx.Response(200))

    # CR-03: /health/deep requires X-API-Key (same auth dependency as /search).
    resp = test_client.get("/health/deep", headers={"X-API-Key": "test-key-health"})
    assert resp.status_code == 200
    body = resp.json()
    for key in ("status", "cloak", "llm", "cache"):
        assert key in body, f"Missing key: {key}"
        assert body[key] is not None, f"Key {key} is None"
    # Cloak deep: should start with "ok" when mocked successfully
    assert body["cloak"].startswith("ok"), (
        f"Expected cloak to start with 'ok', got: {body['cloak']}"
    )

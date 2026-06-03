"""
OBS-07 / D-10 / D-13: /metrics endpoint integration tests.

Tests (RED until Task 3 mounts /metrics in main.py):
  - test_metrics_returns_six_families: GET /metrics → 200, text/plain,
    body contains ≥6 distinct `^artiscrapper_*` family names (D-13).
  - test_metrics_endpoint_has_no_auth: GET /metrics without X-API-Key → 200
    (D-10: by design, no auth on /metrics).
"""

import os
import re
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

# Env vars BEFORE importing the app.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ.setdefault("LLM_ROUTER_BEARER_TOKEN", "test-token-metrics")
# WR-04: use setdefault so we don't clobber a sibling test file's tmp
# DB path (cross-test contract — see tests/integration/test_challenge_backoff.py
# and tests/test_auth.py docstrings).
os.environ.setdefault("CACHE_DB_PATH", _tmp_db.name)
os.environ.setdefault("API_KEYS", "test-key-1")
os.environ.setdefault("SENTRY_DSN", "")

from fastapi.testclient import TestClient  # noqa: E402

from src.artiscrapper.main import app  # noqa: E402


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


@pytest.fixture
def test_client(monkeypatch):
    mock_browser = _make_mock_browser()

    async def _fake_launch_async(**kwargs):
        return mock_browser

    monkeypatch.setattr("src.artiscrapper.main.launch_async", _fake_launch_async)

    with TestClient(app) as client:
        app.state.browser = mock_browser
        yield client


def test_metrics_returns_six_families(test_client):
    """OBS-07 / D-13: /metrics exposes ≥6 distinct artiscrapper_* families."""
    resp = test_client.get("/metrics")
    assert resp.status_code == 200, (
        f"OBS-07: GET /metrics must return 200, got {resp.status_code}"
    )
    ct = resp.headers.get("content-type", "")
    assert ct.startswith("text/plain"), (
        f"OBS-07: /metrics content-type must start with text/plain, got {ct!r}"
    )
    body = resp.text
    families = set(re.findall(r"^(artiscrapper_\w+)", body, re.MULTILINE))
    assert len(families) >= 6, (
        f"D-13: expected ≥6 artiscrapper_* families; got {len(families)}: "
        f"{sorted(families)}"
    )


def test_metrics_endpoint_has_no_auth(test_client):
    """D-10: /metrics is unauthenticated by design (no X-API-Key required)."""
    resp = test_client.get("/metrics")  # NO X-API-Key header
    assert resp.status_code == 200, (
        f"D-10: /metrics must be reachable without X-API-Key; got {resp.status_code}: "
        f"{resp.text[:200]}"
    )

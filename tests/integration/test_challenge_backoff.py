"""
Integration tests for the ChallengeBackoff /search wiring (Phase 3 — Plan 03-02).

End-to-end coverage:
  - test_503_with_retry_after: monkeypatched `fetch_serp` returns the
    sorry.html fixture → POST /search returns 503 with `metadata.block_detected=true`
    AND a digit-string `Retry-After` header (D-09).
  - test_state_survives_restart: trip a block via record_block, close the
    sqlite connection, reopen the same db, call check_gate — gate must
    still be closed (D-08 persistence across container restart).
  - test_sorry_fixture_triggers_detect_block: pins the synthetic stand-in
    (D-20) against the in-repo `BLOCK_MARKERS` tuple so a future fixture
    edit can't silently de-fang the integration test.

Pattern: Pattern S5 (TestClient + monkeypatched cloakbrowser) +
Pattern S6 (respx mock at httpx boundary if needed). Auth is bypassed via
the X-API-Key header set in module env (mirroring `tests/test_auth.py`).

D-04 reminder: slowapi's MemoryStorage is shared across the module-level
`app` singleton. Each test resets `app.state.limiter` to neutralize bleed.
"""

import asyncio
import os
import pathlib
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

# Env vars BEFORE importing the app.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ.setdefault("LLM_ROUTER_BEARER_TOKEN", "test-token-cb")
os.environ["CACHE_DB_PATH"] = _tmp_db.name
os.environ.setdefault("API_KEYS", "test-key-cb")
os.environ.setdefault("SENTRY_DSN", "")

from fastapi.testclient import TestClient  # noqa: E402

from src.artiscrapper import auth as _auth_module  # noqa: E402
from src.artiscrapper.cache import PRAGMAS, init_schema  # noqa: E402
from src.artiscrapper.main import app  # noqa: E402

# Some integration sessions reload modules from auth.py before /search
# runs — make sure the module-level cache reflects the current API_KEYS env.
_auth_module.API_KEYS = _auth_module._parse_api_keys()


SORRY_FIXTURE = (
    pathlib.Path(__file__).parent.parent / "fixtures" / "serp" / "sorry.html"
)


def _make_mock_browser() -> MagicMock:
    """Mirrors tests/test_health.py::_make_mock_browser exactly."""
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


def _reset_challenge_state(db_path: str) -> None:
    """
    Reset the `challenge_state` seed row in the SHARED test db so prior
    tests/runs don't leak a blocked state into a fresh session. Uses raw
    sqlite3 since this runs OUTSIDE the asyncio loop (module-load time).
    """
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE challenge_state "
            "SET last_block_at=NULL, retry_count=0, next_allowed_at=0, "
            "updated_at=strftime('%s','now') "
            "WHERE id=1"
        )
        conn.commit()


def test_sorry_fixture_triggers_detect_block():
    """
    D-20: the synthetic /sorry/ fixture MUST contain markers from
    `browser.BLOCK_MARKERS` so a future fixture edit can't silently
    de-fang the integration test.

    `_detect_block(page)` in `browser.py` takes a Page object (not raw
    HTML). We assert at the marker level here — the sorry.html content
    contains the exact substrings the production detector scans for in
    `page.url`, `page.content()`, and `page.title()`.
    """
    html = SORRY_FIXTURE.read_text(encoding="utf-8")
    assert SORRY_FIXTURE.stat().st_size < 1024, (
        f"D-20: sorry.html fixture should be <1KB stand-in; got {SORRY_FIXTURE.stat().st_size}B"
    )

    # The production detector looks at these substrings in lowercased content/title/url.
    # Mirroring browser._detect_block() exactly so this test catches the
    # case where someone edits sorry.html to drop ALL the markers.
    markers_in_content = [
        "unusual traffic",     # browser._detect_block content/title sniff
        "g-recaptcha",         # DOM marker
        'id="captcha-form"',   # DOM marker
        "sorry/index",         # URL path marker (here in <title>)
    ]
    lower = html.lower()
    hits = [m for m in markers_in_content if m in lower]
    assert len(hits) >= 3, (
        f"D-20: sorry.html must contain at least 3 of the BLOCK_MARKERS "
        f"substrings to pin block-detection. Found {hits} in fixture."
    )


def test_503_with_retry_after(monkeypatch):
    """
    D-09: /search returns 503 + structured metadata.block_detected=true
    + digit-string Retry-After header when the SERP fetch returns a
    block-tripping page.

    Path: monkeypatch `fetch_serp` to return (sorry.html, "sorry_redirect")
    for both URL A and URL B. The route's existing block-detection branch
    triggers BEFORE the new check_gate gate has a stored block (first
    request); the SECOND request should hit the gate and return 503 from
    check_gate's deny path. Both 503 paths must carry Retry-After.
    """
    sorry_html = SORRY_FIXTURE.read_text(encoding="utf-8")

    async def _fake_fetch_serp_blocked(*args, **kwargs):
        # `(html, block_reason)` — production shape from browser.fetch_serp
        return (sorry_html, "sorry_redirect")

    async def _fake_router_health(*args, **kwargs):
        return False  # degraded mode, no LLM calls

    mock_browser = _make_mock_browser()

    async def _fake_launch_async(**kwargs):
        return mock_browser

    monkeypatch.setattr("src.artiscrapper.main.launch_async", _fake_launch_async)
    monkeypatch.setattr("src.artiscrapper.main.fetch_serp", _fake_fetch_serp_blocked)
    monkeypatch.setattr(
        "src.artiscrapper.main.router_health_check", _fake_router_health
    )

    # Reset challenge_state in the SHARED test db before the run.
    _reset_challenge_state(_tmp_db.name)

    headers = {"X-API-Key": "test-key-cb"}
    body = {"query": "challenge-backoff-probe", "max_results": 5}

    with TestClient(app) as client:
        # Reset slowapi limiter to avoid 429 bleed from sibling tests.
        try:
            limiter = app.state.limiter  # type: ignore[attr-defined]
            if hasattr(limiter, "reset"):
                limiter.reset()
        except (AttributeError, Exception):
            pass

        # Request 1: hits the existing block-detection branch (sorry HTML
        # → block_reason="sorry_redirect"). Returns 503 with
        # metadata.block_detected=true. After Plan 03-02 Task 3 wires
        # record_block on this branch, the challenge_state row is
        # mutated as a side-effect.
        r1 = client.post("/search", headers=headers, json=body)
        assert r1.status_code == 503, (
            f"request 1: expected 503 (block detected via sorry HTML); "
            f"got {r1.status_code}, body={r1.text[:200]}"
        )
        body1 = r1.json()
        assert body1.get("metadata", {}).get("block_detected") is True, (
            f"request 1: metadata.block_detected must be True; got {body1}"
        )

        # Request 2: now the challenge_state row carries
        # next_allowed_at > now, so check_gate denies BEFORE we even
        # reach the SERP fetch. The 503 response must carry the
        # Retry-After header with a digit-string value (D-09).
        r2 = client.post("/search", headers=headers, json=body)
        assert r2.status_code == 503, (
            f"request 2: expected 503 from check_gate deny; got {r2.status_code}"
        )
        body2 = r2.json()
        assert body2.get("metadata", {}).get("block_detected") is True, (
            f"request 2: metadata.block_detected must be True from gate; got {body2}"
        )
        retry_after = r2.headers.get("Retry-After")
        assert retry_after is not None, (
            "D-09: 503 response from check_gate MUST carry a Retry-After header"
        )
        assert retry_after.isdigit(), (
            f"D-09: Retry-After must be a digit-string, got {retry_after!r}"
        )
        # Sanity: should be in the [1, 3600] window per D-06
        ra = int(retry_after)
        assert 1 <= ra <= 3600, (
            f"D-06: Retry-After should be in [1, 3600] window, got {ra}"
        )


async def test_state_survives_restart(tmp_path):
    """
    D-08 persistence: record_block → close db → reopen same path →
    check_gate STILL denies.

    Uses an isolated tmp_path db (NOT the shared test db) so the
    "close + reopen" simulates a container restart without interfering
    with sibling tests' app.state.cache.
    """
    from src.artiscrapper import challenge_backoff as cb

    db_path = str(tmp_path / "restart.db")

    # First session: init schema, record a block, close.
    cb._STATE = None
    db = await aiosqlite.connect(db_path)
    for pragma in PRAGMAS:
        await db.execute(pragma)
    await db.commit()
    await init_schema(db)
    await cb.record_block(db)
    await db.close()

    # Simulate restart: in-memory cache MUST be cleared so the reopened
    # connection sees the persisted state via cold _load.
    cb._STATE = None

    # Second session: reopen the SAME path, check the gate is closed.
    db2 = await aiosqlite.connect(db_path)
    for pragma in PRAGMAS:
        await db2.execute(pragma)
    await db2.commit()
    await init_schema(db2)  # idempotent — INSERT OR IGNORE preserves the row

    allowed, retry_after = await cb.check_gate(db2)
    assert allowed is False, (
        "D-08: state lost across reopen — challenge_state row was not persisted "
        "or INSERT OR IGNORE clobbered the existing row"
    )
    assert retry_after > 0, (
        f"D-08: retry_after must be > 0 after reopen; got {retry_after}. "
        "INSERT OR IGNORE may have re-seeded the row (clobbering state)."
    )

    # Direct verification — confirm the row content survived.
    cur = await db2.execute(
        "SELECT last_block_at, retry_count, next_allowed_at FROM challenge_state WHERE id=1"
    )
    row = await cur.fetchone()
    assert row is not None
    last_block_at, retry_count, _ = row
    assert retry_count == 1, (
        f"D-08: retry_count regressed to {retry_count} after reopen "
        f"(expected 1 from the original record_block call)"
    )
    assert last_block_at is not None, (
        "D-08: last_block_at must persist across reopen"
    )

    await db2.close()

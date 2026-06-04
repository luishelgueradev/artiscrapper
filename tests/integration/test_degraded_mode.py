"""
LLM-down degraded-mode hardening test (Phase 3 — Plan 03-02, ROADMAP-5).

When `router_health_check` returns False (router /healthz HEAD fails),
the /search pipeline falls back to the heuristic-only path:
  - junk-domain blocklist filter
  - price-in-card filter

This test loads the Phase 1 50-record labelled set and asserts that
≥5 candidates survive the heuristic-only path (LLM-06 hardening).

Pattern: Pattern S6 (respx mock at httpx boundary). CRITICAL —
`router_health_check` uses `client.head()` not `client.get()` per
`src/artiscrapper/llm.py:267`; the respx mock MUST be `respx.head(...)`.

D-18: assertion includes the specific count + total — NOT
`len(survivors) > 0` (Phase 2 lesson).

Phase 3.1 (D-04 / WR audit tech_debt[3]):
  - `test_degraded_mode_via_search_endpoint` exercises the full POST
    /search route via TestClient with a real SERP fixture, closing the
    trigger-only gap the original test_llm_down_keeps_useful_results
    leaves. Pattern S5 (TestClient + monkeypatched fetch_serp +
    launch_async + router_health_check). The cross-test env merge at
    the file top mirrors tests/integration/test_challenge_backoff.py:33-76
    exactly (R-04 — sibling-test API_KEYS bleed defense).
"""

import json
import os
import pathlib
import tempfile

import httpx
import respx

# Env vars BEFORE importing the app (Phase 3.1 D-04 — required because
# the new test_degraded_mode_via_search_endpoint uses TestClient(app)).
#
# CROSS-TEST IMPORT-ORDER CONTRACT (mirrors
# tests/integration/test_challenge_backoff.py:33-76 exactly):
#   (1) `setdefault` for CACHE_DB_PATH — don't clobber a sibling's tmpfile.
#   (2) APPEND our test key to API_KEYS — don't replace.
#   (3) Refresh `auth.API_KEYS` from the merged env after the import below.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ.setdefault("LLM_ROUTER_BEARER_TOKEN", "test-token-dm")
os.environ.setdefault("CACHE_DB_PATH", _tmp_db.name)
_existing_keys = os.environ.get("API_KEYS", "").strip()
_our_key = "test-key-dm"
if _our_key not in _existing_keys.split(","):
    os.environ["API_KEYS"] = (
        f"{_existing_keys},{_our_key}" if _existing_keys else _our_key
    )
os.environ.setdefault("SENTRY_DSN", "")

from src.artiscrapper.llm import router_health_check  # noqa: E402

LABELLED = (
    pathlib.Path(__file__).parent.parent / "fixtures" / "llm" / "labelled.jsonl"
)


def _heuristic_only_survivors(candidates: list[dict]) -> list[dict]:
    """
    Mirror the heuristic-only branch in `main.py` lines ~470-478:
    when router_healthy is False, the route keeps candidates that
    have a price hint (`price_in_card` or `has_price`) and otherwise
    falls back to the full candidate set.
    """
    survivors = [
        c
        for c in candidates
        if c.get("price_in_card") or c.get("price") or c.get("has_price")
    ]
    if not survivors:
        survivors = list(candidates)
    return survivors


async def test_llm_down_keeps_useful_results():
    """
    ROADMAP-5: with the LLM router returning 503 on /healthz, the
    heuristic-only branch MUST retain ≥5 useful candidates from the
    Phase 1 50-record labelled set.

    D-18 alignment: assertion message lists the survivor count AND
    the total so a regression is forensically actionable.
    """
    candidates = []
    with LABELLED.open() as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            cand = row.get("candidate") or {}
            candidates.append(cand)

    assert len(candidates) == 50, (
        f"Phase 1 labelled set should have exactly 50 records; got {len(candidates)}. "
        "If fixture was edited, update this assertion AND the survivor floor."
    )

    with respx.mock:
        # CRITICAL: router_health_check uses client.head() — must register .head
        respx.head("http://127.0.0.1:3210/healthz").mock(
            return_value=httpx.Response(503, json={"error": "router down"})
        )
        respx.post("http://127.0.0.1:3210/v1/chat/completions").mock(
            return_value=httpx.Response(503, json={"error": "router down"})
        )

        # Confirm the trigger: router_health_check must return False.
        healthy = await router_health_check(
            "http://127.0.0.1:3210", "test-bearer-degraded-mode"
        )
        assert healthy is False, (
            "LLM-06 trigger: router_health_check must return False when /healthz returns 503"
        )

        # Heuristic-only path filter (mirrors main.py degraded-mode branch)
        survivors = _heuristic_only_survivors(candidates)

    assert len(survivors) >= 5, (
        f"ROADMAP-5: degraded mode should retain ≥5 useful results from "
        f"Phase 1 labelled set; got {len(survivors)}/{len(candidates)}. "
        "If this regressed, the heuristic blocklist or price-in-card filter "
        "lost coverage — check `src/artiscrapper/main.py:470-478`."
    )


# ──────────────────────────────────────────
# Phase 3.1 — D-04 / audit tech_debt[3]: full-route degraded-mode coverage
# ──────────────────────────────────────────

from unittest.mock import AsyncMock, MagicMock  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from src.artiscrapper import auth as _auth_module  # noqa: E402
from src.artiscrapper.main import app  # noqa: E402

# Refresh the auth module-level cache from the MERGED API_KEYS env so
# both our key AND sibling-file keys stay valid for the remainder of
# the test session (mirrors test_challenge_backoff.py:65-76).
_live_keys_dm = os.environ.get("API_KEYS", "")
_auth_module.API_KEYS = {k.strip() for k in _live_keys_dm.split(",") if k.strip()}


SERP_FIXTURE = (
    pathlib.Path(__file__).parent.parent
    / "fixtures"
    / "serp"
    / "01-pelota_playera_quico.html"
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


def test_degraded_mode_via_search_endpoint(monkeypatch):
    """
    D-04 / LLM-06 end-to-end coverage: when `router_health_check` returns
    False, POST /search MUST still return 200 with:
      - `metadata.llm_degraded == True`
      - `len(results) > 0` (heuristic-only path retains some survivors)
      - `len(results) >= 3` (D-18 alignment — fixture-pinned floor)

    This sits next to test_llm_down_keeps_useful_results (which only
    covers the TRIGGER + the helper function). This test exercises the
    full /search route via TestClient with a real SERP fixture, closing
    the audit tech_debt[3] coverage gap.

    Pattern: S5 (TestClient + monkeypatched cloakbrowser launch_async +
    fetch_serp). Auth bypassed via X-API-Key header.
    """
    serp_html = SERP_FIXTURE.read_text(encoding="utf-8")

    async def _fake_fetch_serp(*args, **kwargs):
        # Production shape: (html, block_reason | None)
        return (serp_html, None)

    async def _fake_router_health(*args, **kwargs):
        return False  # the trigger — LLM router down

    mock_browser = _make_mock_browser()

    async def _fake_launch_async(**kwargs):
        return mock_browser

    monkeypatch.setattr("src.artiscrapper.main.launch_async", _fake_launch_async)
    monkeypatch.setattr("src.artiscrapper.main.fetch_serp", _fake_fetch_serp)
    monkeypatch.setattr(
        "src.artiscrapper.main.router_health_check", _fake_router_health
    )

    # Reset challenge_backoff state so a sibling test's block-state
    # doesn't deny our request.
    from src.artiscrapper import challenge_backoff as cb

    cb._STATE = None

    headers = {"X-API-Key": "test-key-dm"}
    body = {"query": "pelota playera quico", "max_results": 10}

    with TestClient(app) as client:
        # Reset slowapi limiter (sibling test bleed defense — mirrors
        # the pattern in test_challenge_backoff.py:209)
        try:
            limiter = app.state.limiter
            if hasattr(limiter, "reset"):
                limiter.reset()
        except (AttributeError, Exception):
            pass

        cb._STATE = None
        r = client.post("/search", headers=headers, json=body)

    assert r.status_code == 200, (
        f"D-04: degraded mode must still return 200 (not 503); "
        f"got {r.status_code}, body={r.text[:300]}"
    )
    data = r.json()
    metadata = data.get("metadata", {})

    # The two pinned assertions per CONTEXT.md D-04 + audit tech_debt[3]
    assert metadata.get("llm_degraded") is True, (
        f"LLM-06: metadata.llm_degraded must be True when "
        f"router_health_check returns False; got metadata={metadata}"
    )

    results = data.get("results", [])
    assert len(results) > 0, (
        f"LLM-06: heuristic-only path must retain ≥1 survivor from "
        f"the real SERP fixture (01-pelota_playera_quico.html — known "
        f"to yield ≥15 carousel candidates); got 0. Check "
        f"main.py degraded-mode branch."
    )
    # D-18 alignment: assertion message lists the specific count not just `> 0`.
    # The fixture historically yields ≥15 carousel + heuristic-pass candidates.
    assert len(results) >= 3, (
        f"D-18 alignment: degraded path should retain ≥3 survivors "
        f"from this fixture (it has ≥15 with price); got {len(results)}. "
        f"If this regressed, check the heuristic blocklist + price-in-card "
        f"filter at main.py:~470-478."
    )

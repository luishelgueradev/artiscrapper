"""Phase 0.2.3 PAGE2-02 + PAGE2-03 — integration tests for the paginated /search.

We do NOT hit Google in tests. The strategy:
  - monkeypatch `fetch_serp` to dispatch frozen page-1 / page-2 HTML fixtures
    by URL pattern (?start=10 → page-2 fixture; otherwise → page-1 fixture)
  - monkeypatch `launch_async` so the lifespan returns a mock browser instead
    of booting Chromium
  - monkeypatch `router_health_check` to return False → pipeline takes the
    degraded-mode branch (no LLM HTTP calls, candidates flow through the
    heuristic-only path)
  - monkeypatch `visit_candidates` to a passthrough so the visit pass doesn't
    open real HTTPX connections

What this proves end-to-end:
  - SEARCH_FETCH_PAGES=2 → fetch_serp called exactly 4 times per /search
    (page1 non-meli, page1 meli, page2 non-meli, page2 meli)
  - metadata.google_fetches reflects the real fetch count (was hardcoded 2
    pre-Phase-0.2.3; now dynamic = len(htmls))
  - SEARCH_FETCH_PAGES=1 reverts to the v0.2.2 2-fetch behavior
  - dedupe() collapses candidates whose canonical URL appears in both pages
  - Both captured page-2 fixtures parse to ≥10 candidates (sanity guard
    against accidentally committing a CAPTCHA page)

Cross-test contract (mirrors test_rate_limit.py / test_challenge_backoff.py /
test_degraded_mode.py):
  (1) Set env vars via os.environ BEFORE importing the app (pydantic-settings
      reads at module-load and LLM_ROUTER_BEARER_TOKEN has no default).
  (2) APPEND our API key to API_KEYS — do not clobber sibling keys.
  (3) Refresh auth.API_KEYS from the merged env after the app import (defense
      against sibling test files importing the app first).
"""
from __future__ import annotations

import os
import pathlib
import sqlite3
import tempfile
from unittest.mock import AsyncMock, MagicMock

# ── Env vars BEFORE importing the app (Phase 3 cross-test contract) ──
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ.setdefault("LLM_ROUTER_BEARER_TOKEN", "test-token-page2")
os.environ.setdefault("CACHE_DB_PATH", _tmp_db.name)
_existing_keys = os.environ.get("API_KEYS", "").strip()
_our_key = "test-key-page2"
if _our_key not in _existing_keys.split(","):
    os.environ["API_KEYS"] = (
        f"{_existing_keys},{_our_key}" if _existing_keys else _our_key
    )
os.environ.setdefault("SENTRY_DSN", "")
# Disable parity sample so a bg task doesn't fire and try to read html_a.
os.environ.setdefault("PARITY_SAMPLE_RATE", "0.0")

from fastapi.testclient import TestClient  # noqa: E402

from src.artiscrapper import auth as _auth_module  # noqa: E402
from src.artiscrapper import challenge_backoff as _cb  # noqa: E402
from src.artiscrapper.config import settings as _settings  # noqa: E402
from src.artiscrapper.main import app  # noqa: E402

# Cross-test import-order defense — rebuild auth.API_KEYS from merged env.
_live_keys = os.environ.get("API_KEYS", "")
_auth_module.API_KEYS = {k.strip() for k in _live_keys.split(",") if k.strip()}

FIXTURE_DIR = pathlib.Path(__file__).parent.parent / "fixtures" / "serp"
API_HEADERS = {"X-API-Key": _our_key}


# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────


def _make_mock_browser() -> MagicMock:
    """Mirror of helper in test_rate_limit.py / test_degraded_mode.py."""
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
    """Clear any sibling test's challenge_backoff seed row so check_gate opens."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE challenge_state "
                "SET last_block_at=NULL, retry_count=0, next_allowed_at=0, "
                "updated_at=strftime('%s','now') "
                "WHERE id=1"
            )
            conn.commit()
    except sqlite3.OperationalError:
        # Table not yet created (lifespan hasn't initialized schema). Harmless.
        pass


def _reset_limiter() -> None:
    """Reset slowapi limiter store to avoid 429 from sibling test counters."""
    try:
        limiter = app.state.limiter  # type: ignore[attr-defined]
        if hasattr(limiter, "reset"):
            limiter.reset()
    except (AttributeError, Exception):
        pass


def _fake_fetch_factory(page1_html: str, page2_html: str | None = None):
    """Build an async fake fetch_serp that returns (html, None) per URL.

    Routes any URL containing `&start=10` (page 2 marker) to page2_html;
    every other URL (page 1) gets page1_html. The factory records every
    URL it sees on `.call_log`.
    """
    call_log: list[str] = []

    async def fake_fetch(browser, url, rate_limiter):
        call_log.append(url)
        if page2_html is not None and "start=10" in url:
            return page2_html, None
        return page1_html, None

    fake_fetch.call_log = call_log  # type: ignore[attr-defined]
    return fake_fetch


async def _passthrough_visit(candidates, visit_timeout_s: int = 10):
    """Stub visit_candidates — return candidates untouched, no HTTPX calls."""
    return candidates


async def _router_down(*args, **kwargs):
    """Stub router_health_check — always False → degraded mode branch."""
    return False


def _prepare_app(monkeypatch, *, pages: int, fetch_fake) -> None:
    """Common monkeypatch setup before every TestClient request."""
    monkeypatch.setattr(_settings, "SEARCH_FETCH_PAGES", pages)

    async def _fake_launch_async(**kwargs):
        return _make_mock_browser()

    monkeypatch.setattr("src.artiscrapper.main.launch_async", _fake_launch_async)
    monkeypatch.setattr("src.artiscrapper.main.fetch_serp", fetch_fake)
    monkeypatch.setattr("src.artiscrapper.main.router_health_check", _router_down)
    monkeypatch.setattr("src.artiscrapper.main.visit_candidates", _passthrough_visit)

    # In-memory ChallengeBackoff singleton — clear so sibling test's block-arm
    # doesn't deny this request before fetch_serp runs.
    _cb._STATE = None


# ──────────────────────────────────────────
# Tests
# ──────────────────────────────────────────


def test_search_with_pages_2_makes_4_fetches(monkeypatch):
    """Default SEARCH_FETCH_PAGES=2 → /search calls fetch_serp 4 times
    (page1 non-meli, page1 meli, page2 non-meli, page2 meli) and reports
    `metadata.google_fetches == 4`."""
    page1 = (FIXTURE_DIR / "pla_unit_robotech.html").read_text()
    page2 = (FIXTURE_DIR / "page2_termotanque.html").read_text()
    fake = _fake_fetch_factory(page1, page2)
    _prepare_app(monkeypatch, pages=2, fetch_fake=fake)

    with TestClient(app) as client:
        _reset_challenge_state(_settings.CACHE_DB_PATH)
        _cb._STATE = None
        _reset_limiter()

        # Use a unique query so the cache layer doesn't shadow the new fetch
        # path with a sibling test's cached response.
        resp = client.post(
            "/search",
            json={"query": "page2-pages2-probe-termotanque"},
            headers=API_HEADERS,
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    metadata = body["metadata"]
    # google_fetches is dynamic post-Phase-0.2.3 (was hardcoded 2)
    assert metadata.get("google_fetches") == 4, (
        f"PAGE2-01: expected google_fetches=4 with SEARCH_FETCH_PAGES=2; "
        f"got {metadata.get('google_fetches')!r}. metadata={metadata}"
    )
    # And the fetch_serp counter must agree — 4 distinct URL calls.
    assert len(fake.call_log) == 4, (
        f"PAGE2-01: expected 4 fetch_serp calls (2 pages × 2 meli variants); "
        f"got {len(fake.call_log)}: {fake.call_log}"
    )
    # Sanity check: 2 of the 4 URLs must carry the page-2 marker (?start=10).
    page2_calls = [u for u in fake.call_log if "start=10" in u]
    assert len(page2_calls) == 2, (
        f"PAGE2-01: expected 2 page-2 URLs (one non-meli + one meli); "
        f"got {len(page2_calls)}: {page2_calls}"
    )


def test_search_with_pages_1_makes_2_fetches(monkeypatch):
    """SEARCH_FETCH_PAGES=1 reverts to the v0.2.2 single-page behavior:
    2 fetches total (non-meli + meli), `metadata.google_fetches == 2`,
    no `&start=` page-2 URL appears in the call log."""
    page1 = (FIXTURE_DIR / "pla_unit_robotech.html").read_text()
    fake = _fake_fetch_factory(page1, page2_html=None)
    _prepare_app(monkeypatch, pages=1, fetch_fake=fake)

    with TestClient(app) as client:
        _reset_challenge_state(_settings.CACHE_DB_PATH)
        _cb._STATE = None
        _reset_limiter()

        resp = client.post(
            "/search",
            json={"query": "page2-pages1-probe-termotanque"},
            headers=API_HEADERS,
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    metadata = body["metadata"]
    assert metadata.get("google_fetches") == 2, (
        f"backward-compat: expected google_fetches=2 with SEARCH_FETCH_PAGES=1; "
        f"got {metadata.get('google_fetches')!r}"
    )
    assert len(fake.call_log) == 2, (
        f"backward-compat: expected 2 fetch_serp calls; got {len(fake.call_log)}: "
        f"{fake.call_log}"
    )
    # No page-2 URL should ever appear — strict regression guard against an
    # accidental hardcoded N=2 elsewhere in the pipeline.
    page2_calls = [u for u in fake.call_log if "start=10" in u]
    assert page2_calls == [], (
        f"backward-compat: page-2 URLs leaked into N=1 path: {page2_calls}"
    )


def test_dedupe_collapses_duplicate_between_pages(monkeypatch):
    """When page 1 and page 2 serve byte-identical HTML, every candidate
    URL appears in both pages. The dedupe() pass MUST collapse them — the
    final response's candidate count is bounded by the unique-URL count of
    a single page's parse output (not 2× it)."""
    # Same fixture for both pages → identical canonical URLs guaranteed.
    page1 = (FIXTURE_DIR / "pla_unit_robotech.html").read_text()
    fake = _fake_fetch_factory(page1, page2_html=page1)
    _prepare_app(monkeypatch, pages=2, fetch_fake=fake)

    with TestClient(app) as client:
        _reset_challenge_state(_settings.CACHE_DB_PATH)
        _cb._STATE = None
        _reset_limiter()

        resp = client.post(
            "/search",
            json={"query": "page2-dedupe-probe-termotanque"},
            headers=API_HEADERS,
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    metadata = body["metadata"]

    # 4 fetches but the post-dedupe / pre-junk candidate count must reflect a
    # SINGLE page's worth of unique URLs (not 4× — that would be a dedupe
    # regression). Compute the expected upper bound from the fixture itself
    # so this test stays self-correcting if the fixture is re-captured.
    from src.artiscrapper.search import dedupe, parse_serp

    p1_cands = parse_serp(page1)
    expected_unique = len(dedupe(list(p1_cands)))

    # candidates_total in Metadata reflects post-dedupe + post-junk-blocklist
    # count (per main.py line ~843). Same fixture × 2 pages must collapse to
    # ≤ the single-page unique count (junk filter can only shrink it).
    cand_total = metadata.get("candidates_total")
    assert cand_total is not None, f"candidates_total missing: {metadata}"
    assert cand_total <= expected_unique, (
        f"PAGE2-02 dedupe regression: candidates_total={cand_total} > "
        f"single-page unique count={expected_unique}. Dedupe by canonical URL "
        f"must collapse the duplicate page-1+page-2 set into one."
    )
    # And google_fetches still honestly reports 4 — dedupe doesn't fake the fetch count.
    assert metadata.get("google_fetches") == 4, metadata


def test_parse_serp_page2_termotanque_fixture():
    """The captured page-2 fixture must yield ≥10 candidates — guards
    against accidentally committing a CAPTCHA / soft-block / empty page."""
    from src.artiscrapper.search import parse_serp

    html = (FIXTURE_DIR / "page2_termotanque.html").read_text()
    cands = parse_serp(html)
    assert len(cands) >= 10, (
        f"page2_termotanque.html parsed to only {len(cands)} candidates "
        f"(floor=10). Re-capture the fixture if Google's page-2 markup drifted."
    )
    # Soft guard: a meaningful chunk should carry a real URL (not g/search synthetic).
    real_url = [c for c in cands if "google.com" not in (c.get("url") or "")]
    assert len(real_url) >= 5, (
        f"page2_termotanque.html: only {len(real_url)}/{len(cands)} candidates "
        f"have a non-google URL — possible CAPTCHA / consent interstitial leaked through."
    )


def test_parse_serp_page2_zapatillas_fixture():
    """Same guard for the ropa-espec page-2 fixture (pla-heavy)."""
    from src.artiscrapper.search import parse_serp

    html = (FIXTURE_DIR / "page2_zapatillas.html").read_text()
    cands = parse_serp(html)
    assert len(cands) >= 10, (
        f"page2_zapatillas.html parsed to only {len(cands)} candidates (floor=10)."
    )
    real_url = [c for c in cands if "google.com" not in (c.get("url") or "")]
    assert len(real_url) >= 5, (
        f"page2_zapatillas.html: only {len(real_url)}/{len(cands)} candidates "
        f"have a non-google URL."
    )


# ──────────────────────────────────────────
# Gap C — honest google_fetches on non-success paths
# ──────────────────────────────────────────


def test_google_fetches_is_zero_when_gather_raises(monkeypatch):
    """Gap C: when asyncio.gather raises (e.g. TargetClosedError), the
    response carries google_fetches=0 — NOT the pydantic default. Pre-fix
    the response leaked the v0.1 hardcoded `=2` into total-failure paths,
    making /metrics + consumer analytics dishonest."""

    async def _exploding_fetch(browser, url, rate_limiter):
        # Mirrors the prod failure shape from issue #1.
        raise RuntimeError("simulated browser death (Gap C exception path)")

    _exploding_fetch.call_log = []  # type: ignore[attr-defined]
    _prepare_app(monkeypatch, pages=2, fetch_fake=_exploding_fetch)

    with TestClient(app) as client:
        _reset_challenge_state(_settings.CACHE_DB_PATH)
        _cb._STATE = None
        _reset_limiter()
        resp = client.post(
            "/search",
            json={"query": "gapc-exception-path-probe"},
            headers=API_HEADERS,
        )

    assert resp.status_code == 200, resp.text
    metadata = resp.json()["metadata"]
    assert metadata.get("google_fetches") == 0, (
        f"Gap C: gather-raised response must report google_fetches=0; "
        f"got {metadata.get('google_fetches')!r}. metadata={metadata}"
    )
    assert metadata.get("block_detected") is False, metadata


def test_google_fetches_reports_len_htmls_on_block_detected(monkeypatch):
    """Gap C: when a fetch succeeds in returning HTML that contains a
    block marker, the block-detected response shape must report the
    actual number of fetches that came back (len(htmls)), not the
    pydantic default. The fetches DID happen — Google just served a
    /sorry/ or interstitial page. Hiding that count made it harder to
    correlate the block volume that triggered it."""
    page1 = (FIXTURE_DIR / "pla_unit_robotech.html").read_text()

    async def _blocking_fetch(browser, url, rate_limiter):
        # block_reason non-None → triggers the block_detected branch
        return page1, "sorry_redirect"

    _blocking_fetch.call_log = []  # type: ignore[attr-defined]
    _prepare_app(monkeypatch, pages=2, fetch_fake=_blocking_fetch)

    with TestClient(app) as client:
        _reset_challenge_state(_settings.CACHE_DB_PATH)
        _cb._STATE = None
        _reset_limiter()
        resp = client.post(
            "/search",
            json={"query": "gapc-block-path-probe"},
            headers=API_HEADERS,
        )

    assert resp.status_code == 200, resp.text
    metadata = resp.json()["metadata"]
    assert metadata.get("block_detected") is True, metadata
    # 2 pages × 2 (meli/non-meli) = 4 fetches all returned HTML+block_reason
    assert metadata.get("google_fetches") == 4, (
        f"Gap C: block_detected response must report len(htmls)=4; "
        f"got {metadata.get('google_fetches')!r}. metadata={metadata}"
    )

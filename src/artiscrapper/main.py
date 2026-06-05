"""
FastAPI application with lifespan (Cloak singleton + SIGSTOP heartbeat + sqlite cache init).
Pattern 1 from 02-RESEARCH.md (lines 287-402) — lifespan + _recycle_browser_loop.
Pattern 11 from 02-RESEARCH.md (lines 1233-1293) — /health + /health/deep.
Phase 1 NEEDS-PIVOT applied: _recycle_browser_loop includes page.evaluate("1") heartbeat
every 10s to catch SIGSTOP (is_connected() stays True on SIGSTOP — SPIKE.md §Browser confirmed).
D6: uvicorn --loop asyncio --workers 1 — never uvloop.
D8: only ephemeral new_context() per request — no persistent browser contexts.
Full 10-step POST /search pipeline wired in plan 02-02:
[1] cache → [2] Google fetch → [3] detect_block → [4] parse → [5] LLM →
[6] visit → [7] freshness → [8] rerank → [9] cache write → [10] response
"""

import asyncio
import random
import re
import time
from pathlib import Path
from contextlib import asynccontextmanager

import aiosqlite
import httpx
import sentry_sdk
import structlog
from asgi_correlation_id import CorrelationIdMiddleware
from cloakbrowser import launch_async  # Phase 1 confirmed: this is the correct import path
from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import ORJSONResponse
from prometheus_client import make_asgi_app
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from . import challenge_backoff
from .auth import _parse_api_keys, get_api_key, verify_api_key
from .browser import fetch_serp
from .cache import (
    PRAGMAS,
    get_cached,
    init_schema,
    make_cache_key,
    normalize_query,
    prune_loop,
    set_cached,
)
from .challenge_backoff import check_gate, record_block, record_success
from .config import settings
from .freshness import assess_freshness
from .llm import curate_candidates, router_health_check
from .logging_setup import configure_logging
from .metrics import (  # noqa: F401  (metrics kept for backwards-compat readers)
    inc_block_detected,
    metrics,
    search_elapsed,
)
from .models import Candidate, Metadata, SearchRequest, SearchResponse
from .rate_limit import GoogleRateLimiter
from .search import (
    build_serp_url,
    dedupe,
    heuristic_pre_classify,
    is_junk,
    parse_serp,
    rerank,
)
from .visit import visit_candidates

log = structlog.get_logger()


# ──────────────────────────────────────────
# SIGSTOP heartbeat recycle loop (Phase 1 NEEDS-PIVOT)
# ──────────────────────────────────────────


async def _recycle_browser_loop(app: FastAPI) -> None:
    """
    Recycles the Cloak Browser after BROWSER_RECYCLE_AFTER cold fetches.
    Phase 1 NEEDS-PIVOT: Browser.is_connected() does NOT flip on SIGSTOP.
    Use page.evaluate("1") heartbeat to catch SIGSTOP death (every 10s).
    Pattern 1 from 02-RESEARCH.md (lines 305-350) — copied verbatim.
    """
    while True:
        await asyncio.sleep(10)  # heartbeat interval (10s per SPIKE.md §Risks)
        browser = app.state.browser
        # Primary check: is_connected() catches SIGKILL (Phase 1: 0.5s lag)
        if not browser.is_connected():
            log.warning("browser_dead_sigkill")
            app.state.browser = await launch_async(headless=settings.HEADLESS)
            app.state.browser_uses = 0
            try:
                await browser.close()
            except Exception:
                pass
            continue
        # Secondary heartbeat: catches SIGSTOP (is_connected() stays True for SIGSTOP)
        # CR-02 fix: try/finally so ctx/page close even when wait_for raises
        ctx = None
        page = None
        try:
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await asyncio.wait_for(page.evaluate("1"), timeout=5.0)
        except Exception as exc:
            log.warning("browser_heartbeat_failed", error=str(type(exc).__name__))
            # Close the (possibly half-created) heartbeat context before recycling
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass
            if ctx is not None:
                try:
                    await ctx.close()
                except Exception:
                    pass
            app.state.browser = await launch_async(headless=settings.HEADLESS)
            app.state.browser_uses = 0
            try:
                await browser.close()
            except Exception:
                pass
            continue
        else:
            # Success path: close the heartbeat context cleanly
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass
            if ctx is not None:
                try:
                    await ctx.close()
                except Exception:
                    pass
        # Recycle after N cold fetches (memory drift mitigation)
        if app.state.browser_uses >= settings.BROWSER_RECYCLE_AFTER:
            log.info("browser_recycle_start", uses=app.state.browser_uses)
            old = app.state.browser
            app.state.browser = await launch_async(headless=settings.HEADLESS)
            app.state.browser_uses = 0
            try:
                await old.close()
            except Exception:
                pass
            log.info("browser_recycle_done")


# ──────────────────────────────────────────
# Lifespan (Pattern 1 lines 352-402)
# ──────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(json_logs=settings.LOG_JSON, level=settings.LOG_LEVEL)
    log.info("boot_start", version=settings.VERSION)

    # 1. sqlite cache
    app.state.cache = await aiosqlite.connect(settings.CACHE_DB_PATH)
    for pragma in PRAGMAS:
        await app.state.cache.execute(pragma)
    await app.state.cache.commit()
    await init_schema(app.state.cache)

    # 1b. Phase 3 — D-19 empirical-retest gates (Phase 2 memory
    # `feedback_empirical_retest_after_default_changes`). Each new env-var
    # default emits a structured log line so `docker compose logs | grep ...`
    # can confirm the value reached the hot path. OBS-05: log the count /
    # quota, NEVER the API_KEYS values or the SENTRY_DSN.
    log.info(
        "api_keys_loaded",
        count=len(_parse_api_keys()),
        rate_per_min=settings.API_RATE_PER_MINUTE,
        rate_per_day=settings.API_RATE_PER_DAY,
    )
    # WRN-04: derive the log event name from the actual SDK state (which
    # `_init_sentry()` already settled at logging_setup module-import time)
    # so the log line and `sentry_sdk.get_client().is_active()` cannot
    # diverge. Branching on `settings.SENTRY_DSN` alone would be a
    # shadowing risk (Phase 2 lesson D-19).
    _sentry_active = sentry_sdk.get_client().is_active()
    log.info(
        "sentry_init_done" if _sentry_active else "sentry_init_skipped",
        traces_sample_rate=0.1 if _sentry_active else None,
    )
    log.info(
        "rate_limit_init",
        per_minute=_RATE_LIMIT_PER_MINUTE,
        per_day=_RATE_LIMIT_PER_DAY,
        source="module_constants_from_settings",
    )
    # Plan 03-02 — D-19 empirical retest gate for the ChallengeBackoff
    # constants. These are hardcoded module-level (D-06 ROADMAP-lock —
    # NOT thread-able through settings). The log line declares the
    # values reached the running container so `docker compose logs |
    # grep challenge_backoff_init` confirms the hot-path values match
    # expectations (Phase 2 memory `feedback_empirical_retest_after_default_changes`).
    log.info(
        "challenge_backoff_init",
        base_s=challenge_backoff._BASE_S,
        cap_s=challenge_backoff._BACKOFF_CAP_S,
        reset_after_s=challenge_backoff._RESET_AFTER_S,
    )

    # 2. Cloak browser (Phase 1 confirmed: from cloakbrowser import launch_async)
    app.state.browser = await launch_async(headless=settings.HEADLESS)
    app.state.browser_uses = 0

    # 3. Rate limiter (1/min between Google fetches, configurable)
    app.state.rate_limit = GoogleRateLimiter(min_interval_s=settings.GOOGLE_MIN_INTERVAL_S)

    # 4. Background tasks
    tasks = [
        asyncio.create_task(_recycle_browser_loop(app), name="browser_recycle"),
        asyncio.create_task(prune_loop(app.state.cache), name="cache_prune"),
    ]

    # WR-03: strong-reference set for fire-and-forget tasks (e.g. the
    # cache-write task created from /search). asyncio.create_task only
    # registers a weak reference, so without retaining the task here
    # Python is free to GC it mid-execution and silently drop the work.
    app.state.background_tasks = set()
    log.info("boot_done")
    try:
        yield
    finally:
        log.info("shutdown_start")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await app.state.cache.close()
        try:
            await app.state.browser.close()
        except Exception:
            pass
        log.info("shutdown_done")


# ──────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────

app = FastAPI(
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
    title="artiscrapper",
    version=settings.VERSION,
)

# ── Phase 3.1 D-05 — slowapi rate limits, single source of truth (Pattern B) ──
# These two constants are computed ONCE at module-load from settings. They flow
# into BOTH (1) the @limiter.limit() decorators on POST /search AND (2) the
# `rate_limit_init` log line in lifespan. Drift between log and runtime is
# impossible by construction — there is exactly ONE place in the codebase
# where the limit string is built. Override via .env requires
# `compose up --force-recreate` (pydantic-settings reloads at process start).
# DO NOT mutate at runtime — settings are import-time-frozen by design.
#
# Why Pattern B (decorator args) instead of Pattern A (Limiter default_limits):
# slowapi 0.1.9 does NOT auto-apply default_limits to routes without an
# @limiter.limit decorator unless SlowAPIMiddleware is installed, and
# SlowAPIMiddleware crashes on first request in 0.1.9 + FastAPI
# (AttributeError on 'TypeError'). See 03.1-03-PLAN.md Deviation Note
# (2026-06-04) for the full empirical root-cause.
_RATE_LIMIT_PER_MINUTE = f"{settings.API_RATE_PER_MINUTE}/minute"
_RATE_LIMIT_PER_DAY = f"{settings.API_RATE_PER_DAY}/day"

# ── Phase 3 — slowapi + /metrics ASGI sub-app mount ──
# Registered BEFORE CorrelationIdMiddleware so the middleware (added last =
# executed first) wraps slowapi's 429 responses → 429s still carry the
# request's X-Request-ID (03-RESEARCH.md §C5). headers_enabled=True makes
# 429 responses include X-RateLimit-* and Retry-After (§C4).
limiter = Limiter(key_func=get_api_key, headers_enabled=True)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# D-10: /metrics is mounted as an ASGI sub-app so it bypasses the
# per-route mechanisms — slowapi limits do NOT apply, and no
# verify_api_key Depends runs. WR-06 correction: this mount does NOT
# bypass app.add_middleware(...) below. Starlette installs middleware
# at the ASGI level so CorrelationIdMiddleware wraps EVERY request,
# including those that land on this sub-app. The invariant we rely on
# is therefore not "middleware doesn't run" but "the middleware in use
# is harmless on a /metrics request" — i.e. CorrelationIdMiddleware
# only adds an X-Request-ID header and never raises on a malformed
# request. If that ever changes, /metrics goes down with the rest of
# the app, breaking the scrape-must-survive-everything expectation —
# at which point the migration path is prometheus_client.start_http_server
# on a separate admin port. See test_metrics_endpoint_unprotected_by_design.
app.mount("/metrics", make_asgi_app())

# CorrelationIdMiddleware must be outermost (added last = executed first in request chain)
# WR-06: ALSO wraps the /metrics ASGI sub-app above — middleware is ASGI-level.
app.add_middleware(CorrelationIdMiddleware)


# ──────────────────────────────────────────
# Health endpoints (Pattern 11)
# ──────────────────────────────────────────


@app.get("/health")
async def health(request: Request) -> dict:
    """
    OBS-01: Cheap liveness check (<50ms). Called by nginx/monitoring.
    Uses cached browser.is_connected() — no Chromium navigation.
    """
    out: dict = {"status": "ok", "cloak": "ok", "llm": "unknown", "cache": "ok"}
    # Cache: pure sqlite call
    try:
        await request.app.state.cache.execute("SELECT 1")
    except Exception:
        out["cache"] = "fail"
        out["status"] = "degraded"
    # Cloak: is_connected() only (SIGKILL detection; SIGSTOP is caught by heartbeat loop)
    if not request.app.state.browser.is_connected():
        out["cloak"] = "fail"
        out["status"] = "degraded"
    return out


@app.get("/health/deep")
async def health_deep(
    request: Request,
    _api_key: str = Depends(verify_api_key),
) -> dict:
    """
    OBS-02: Real roundtrip. NEVER call from load balancer (eats Chromium nav).
    Use only from cron / manual smoke test.

    CR-03: gated behind X-API-Key. Without this, any unauthenticated caller
    could trigger (a) a real Chromium new_context/new_page/goto round-trip
    per request (burning browser slots and the GoogleRateLimiter), and
    (b) an outbound GET to LLM_ROUTER_URL carrying LLM_ROUTER_BEARER_TOKEN
    — a free DoS knob plus bearer-token exfiltration trigger via SSRF or
    direct port exposure. The cheap unauth /health endpoint above is what
    the LB should hit.
    """
    out = await health(request)
    # Cloak deep: navigate about:blank and evaluate
    # CR-02 fix: try/finally so ctx/page always close, even if goto/wait_for raises
    browser = request.app.state.browser
    ctx = None
    page = None
    try:
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await asyncio.wait_for(
            page.goto("about:blank", wait_until="domcontentloaded"),
            timeout=5.0,
        )
        out["cloak"] = "ok_deep"
    except Exception as exc:
        out["cloak"] = f"fail:{type(exc).__name__}"
        out["status"] = "degraded"
    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass
        if ctx is not None:
            try:
                await ctx.close()
            except Exception:
                pass
    # LLM deep: GET /healthz with bearer (SPIKE.md §LLM confirmed /healthz with z)
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(
                f"{settings.LLM_ROUTER_URL}/healthz",
                headers={"Authorization": f"Bearer {settings.LLM_ROUTER_BEARER_TOKEN}"},
            )
            out["llm"] = "ok" if r.status_code == 200 else f"fail:{r.status_code}"
    except Exception as exc:
        out["llm"] = f"fail:{type(exc).__name__}"
    return out


# ──────────────────────────────────────────
# GET /admin/parity/{query} — Phase 0.2.1 PARITY-05
# Minimum harness for visual parity audits. The full harness (12-query
# dataset + CI nightly + WARN/FAIL alerts) is Phase 0.2.2.
# ──────────────────────────────────────────


# Parity audit gauges are declared in metrics.py alongside the other
# Prometheus families (Counter/Histogram), where the project's collector
# unregistration pattern lives. importing them here keeps main.py focused
# on routing and main.py importable under importlib.reload (test_sentry_init).
from .metrics import (  # noqa: E402
    parity_coverage_pct,
    parity_pla_extracted,
    parity_pla_in_html,
    parity_pla_units_missed,
    parity_url_synthetic_ratio,
)

# Recognise canonical store-id URL patterns: /p/MLA*, /up/MLAU*, /itm/*, /dp/<10-char ASIN>.
_CANON_URL_RE = re.compile(
    r"https?://[^\"'\s<>&\\]+(?:/(?:p/MLA|up/MLAU)\d+|/itm/\d+|/dp/[A-Z0-9]{10})"
)
# Match AR prices in raw HTML (with optional NBSP / &nbsp; entity).
_HTML_PRICE_RE = re.compile(
    r"\$(?:&nbsp;|\xc2\xa0|\xa0|\s)?[1-9]\d{0,2}(?:\.\d{3})*,\d{2}"
)

# Phase 0.2.2 HARNESS-01 — load parity dataset once at module-import.
# Keyed by the lowercased+stripped query string for O(1) baseline lookup
# from both /admin/parity/{q} and the Plan 02 sample hot-path. Production
# queries that don't match the canonical dataset get None for the
# coverage_pct gauge but still update raw counts in the helper.
import yaml  # noqa: E402

_PARITY_DATASET_PATH = (
    Path(__file__).parent.parent.parent / "tests" / "fixtures" / "parity-dataset.yaml"
)
_PARITY_DATASET: dict[str, dict] = {}
try:
    with _PARITY_DATASET_PATH.open() as _fh:
        _ds = yaml.safe_load(_fh) or {}
    for _entry in _ds.get("queries") or []:
        _key = (_entry.get("query") or "").strip().lower()
        if _key:
            _PARITY_DATASET[_key] = _entry
    log.info("parity_dataset_loaded", count=len(_PARITY_DATASET))
except Exception as _exc:  # noqa: BLE001
    log.warning("parity_dataset_load_failed", error=str(_exc))


def _compute_parity_metrics(
    query: str,
    html: str,
    candidates: list[dict],
    pla_nodes_count: int,
) -> dict:
    """Compute and emit the 5 parity Prometheus families from an audit input.

    Used by /admin/parity/{q} AND by Plan 02's sample hot-path task. Always
    sets pla_in_html / pla_extracted / pla_units_missed / url_synthetic_ratio.
    coverage_pct is set only when the query is in the canonical dataset.

    Returns a `coverage` dict for inclusion in the JSON response:
      {
        "coverage_pct": float | None,
        "pla_units_missed": int,
        "url_synthetic_ratio": float,
      }

    `html` is currently unused in the metric formulas but is kept in the
    signature so future drift detectors can compare HTML signals directly
    without re-parsing.
    """
    del html  # not currently used; reserved for future detectors
    label = query[:80]
    pla_extracted_cands = [c for c in candidates if "pla_unit" in (c.get("flags") or [])]

    # 1. pla_in_html + extracted (gauges existed since Phase 0.2.1)
    parity_pla_in_html.labels(query=label).set(pla_nodes_count)
    parity_pla_extracted.labels(query=label).set(len(pla_extracted_cands))

    # 2. pla_units_missed counter (drift signal). Counter monotonic — we
    # increment by the diff, never reset to "current state".
    missed = max(0, pla_nodes_count - len(pla_extracted_cands))
    if missed > 0:
        parity_pla_units_missed.labels(query=label).inc(missed)

    # 3. url_synthetic_ratio — carousel fraction over all candidates with URL.
    cands_with_url = [c for c in candidates if c.get("url")]
    synthetic = [
        c for c in cands_with_url if "google.com/search" in (c.get("url") or "")
    ]
    ratio = len(synthetic) / len(cands_with_url) if cands_with_url else 0.0
    parity_url_synthetic_ratio.labels(query=label).set(ratio)

    # 4. coverage_pct — only when query has a baseline in the canonical dataset.
    real_url_cands = [
        c
        for c in candidates
        if c.get("url") and "google.com/search" not in (c.get("url") or "")
    ]
    entry = _PARITY_DATASET.get(query.strip().lower())
    coverage_pct: float | None = None
    if entry:
        expected = entry.get("min_expected_real_urls")
        if expected:
            coverage_pct = min(100.0, 100.0 * len(real_url_cands) / float(expected))
            parity_coverage_pct.labels(query=label).set(coverage_pct)

    return {
        "coverage_pct": coverage_pct,
        "pla_units_missed": missed,
        "url_synthetic_ratio": ratio,
    }


async def _parity_audit_sample(query: str, html: str) -> None:
    """Phase 0.2.2 HARNESS-03 — fire-and-forget parity sample from POST /search.

    Runs parity metrics on HTML the /search pipeline already produced. We
    reuse the existing html_a (the non-meli SERP) so this task adds ZERO
    Cloak rate-limit pressure and zero extra Google fetch — just a DOM parse
    + a few regexes + 5 Prometheus updates.

    Why we reuse the cached HTML instead of re-fetching:
    - /search already paid the Cloak cost; doing it twice doubles the rate-
      limiter pressure for no signal gain.
    - The parity question is "what's in THIS html that the parser missed",
      not "did Google's auction return more pla-units 200ms later".
    - Keeps overhead <50ms p99 on a 1.5 MB SERP (DOM parse only).

    NEVER raises into the caller — failure is logged structurally and
    swallowed. The bg task pattern uses app.state.background_tasks (the
    same set the cache-write task lives in) for strong-ref + GC safety.
    """
    try:
        from selectolax.parser import HTMLParser

        tree = HTMLParser(html)
        pla_nodes_count = len(tree.css("div.pla-unit"))
        candidates = parse_serp(html)
        _compute_parity_metrics(query, html, candidates, pla_nodes_count)
    except Exception as exc:  # noqa: BLE001
        log.warning("parity_sample_failed", query=query[:80], error=str(exc))


@app.get("/admin/parity/{query:path}")
async def admin_parity(
    request: Request,
    query: str,
    _api_key: str = Depends(verify_api_key),
) -> dict:
    """
    Parity audit endpoint — fetch the Google SERP for {query}, run the current
    parser, and compare against the raw HTML's measurable signals (price count,
    canonical URL count, pla-unit container count). Helps detect drift caused
    by Google class rotation or upstream changes to the SERP structure.

    Auth: X-API-Key (same as /search). Phase 0.2.2 will gate this behind a
    dedicated `admin_audit` role; for now any valid key may call.

    Response shape:
      {
        "query": str,
        "blocked": str | False,                       # block_reason or False
        "html_metrics": {
          "size_bytes": int,
          "prices_unique": int,
          "canonical_urls_in_html": int,
          "pla_units_in_html": int,                   # `div.pla-unit` nodes
        },
        "parser_metrics": {
          "candidates_total": int,
          "candidates_with_price": int,
          "candidates_real_url": int,                 # non-Google-search URLs
          "pla_unit_extracted": int,
          "carousel_extracted": int,
        },
        "drift": list[str],                           # flagged anomalies
      }

    This endpoint hits Cloak — it is NOT cached and counts against the
    GoogleRateLimiter. Do not call it from a hot loop; intended for spot-audits
    and the Phase 0.2.2 nightly job (sampling rate 1/hour expected).
    """
    from selectolax.parser import HTMLParser

    browser = request.app.state.browser
    rate_limiter = request.app.state.rate_limit
    url = build_serp_url(query, meli=False)
    html, block_reason = await fetch_serp(browser, url, rate_limiter)
    if block_reason:
        return {"query": query, "blocked": block_reason}

    tree = HTMLParser(html)
    pla_nodes = tree.css("div.pla-unit")
    cands = parse_serp(html)
    pla_extracted = [c for c in cands if "pla_unit" in (c.get("flags") or [])]
    carousel_extracted = [c for c in cands if "carousel" in (c.get("flags") or [])]

    prices_in_html = set(_HTML_PRICE_RE.findall(html))
    canon_urls = {u.split("?")[0] for u in _CANON_URL_RE.findall(html)}
    real_url_cands = [
        c
        for c in cands
        if c.get("url") and "google.com/search" not in (c.get("url") or "")
    ]

    # Phase 0.2.2: delegate all metric updates + coverage computation to the
    # shared helper so /admin/parity and the sample hot-path stay in sync.
    coverage_block = _compute_parity_metrics(query, html, cands, len(pla_nodes))

    drift: list[str] = []
    if len(pla_nodes) > 0 and len(pla_extracted) == 0:
        # Container detected but no extraction — strong signal that the inner
        # obfuscated classes (VbBaOe, UsGWMe, OkcyVb, [role=heading]) rotated.
        drift.append("pla_unit_in_html_not_extracted")

    return {
        "query": query,
        "blocked": False,
        "html_metrics": {
            "size_bytes": len(html),
            "prices_unique": len(prices_in_html),
            "canonical_urls_in_html": len(canon_urls),
            "pla_units_in_html": len(pla_nodes),
        },
        "parser_metrics": {
            "candidates_total": len(cands),
            "candidates_with_price": sum(1 for c in cands if c.get("has_price")),
            "candidates_real_url": len(real_url_cands),
            "pla_unit_extracted": len(pla_extracted),
            "carousel_extracted": len(carousel_extracted),
        },
        "coverage": coverage_block,
        "drift": drift,
    }


# ──────────────────────────────────────────
# POST /search — Full 10-step pipeline (plan 02-02)
# CACHE-05: NEVER fetch Google without checking cache first.
# VISIT-03: visit_timeout_s=request.visit_timeout_s — per-request timeout threaded through.
# ──────────────────────────────────────────


@app.post("/search", response_model=SearchResponse)
@limiter.limit(_RATE_LIMIT_PER_MINUTE)
@limiter.limit(_RATE_LIMIT_PER_DAY)
async def search(
    request: Request,
    response: Response,
    body: SearchRequest,
    _api_key: str = Depends(verify_api_key),
) -> SearchResponse:
    """
    POST /search — Full 10-step pipeline wired in plan 02-02.
    Field name is 'query' (NOT 'q') per PRD SEARCH-01.

    Phase 3:
      - D-01/D-03: `verify_api_key` FastAPI dependency enforces X-API-Key
        (401 on missing/unknown). `request: Request` MUST stay first
        positional arg (slowapi requirement — 03-RESEARCH.md §C2).
      - D-02 (Phase 3.1 D-05 refactor — Pattern B): stacked
        `@limiter.limit(_RATE_LIMIT_PER_MINUTE) + @limiter.limit(_RATE_LIMIT_PER_DAY)`
        — both decorator args are module-level constants derived from
        `settings.API_RATE_PER_MINUTE/DAY` at module-load (single source of
        truth). First-to-fire wins → 429 with Retry-After header (slowapi 0.1.9).
      - `response: Response` is declared so slowapi (with headers_enabled=True)
        can inject X-RateLimit-* + Retry-After headers into success responses.
        Without this param, slowapi raises "parameter `response` must be an
        instance of starlette.responses.Response" because FastAPI hasn't yet
        serialized the SearchResponse pydantic model when the limiter
        post-processes.
      - D-12: full body wrapped in `with search_elapsed.time():` (context-
        manager form — NEVER `@search_elapsed.time()` decorator on async def
        per 03-RESEARCH.md §A5 / Pitfall 1).

    [1] cache lookup → [2] Google fetch (parallel A+B) → [3] detect_block →
    [4] parse_serp → [5] merge+dedupe+blocklist → [6] LLM filter (or degraded mode) →
    [7] visit_candidates → [8] assess_freshness → [9] rerank → [10] cache write → response
    """
    t_start = time.time()

    # D-12: bracket the entire pipeline so the Histogram captures wall-clock
    # of every code path (cache-hit, block-detected 503, normal-flow 200).
    # Plan 03-02 will INSERT `await check_gate(...)` as step [1.5] AFTER the
    # cache-hit early-return AND INSIDE this `with` block — see coordination
    # notes in 03-01-PLAN.md and 03-02-PLAN.md.
    with search_elapsed.time():
        # Bind per-request structlog context (OBS-05: only cache key prefix, never full query)
        cache_key = make_cache_key(body.query)
        query_norm = normalize_query(body.query)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            query_hash=cache_key[:12],
            stage="search",
        )

        # ── [1] Cache lookup (CACHE-05: ALWAYS before any Google fetch) ──
        cached = await get_cached(request.app.state.cache, cache_key)
        if cached is not None:
            log.info("cache_hit")
            elapsed_ms = int((time.time() - t_start) * 1000)
            return SearchResponse(
                query=body.query,
                results=cached.get("results", []),
                metadata=Metadata(
                    elapsed_ms=elapsed_ms,
                    cache_hit=True,
                    candidates_total=len(cached.get("results", [])),
                ),
            )

        log.info("cache_miss")

        # ── [1.5] ChallengeBackoff gate (D-09 / Plan 03-02) ──
        # Read-only check on the module-singleton `_STATE` (sqlite query
        # on first call per process; cached thereafter). When the gate
        # is closed (a previous block armed the backoff), short-circuit
        # with 503 + Retry-After BEFORE consuming a Cloak fetch — the
        # consumer learns the wait window instead of getting a silent
        # timeout. The latency still counts in `search_elapsed`
        # (intentional — we're inside the `with` block).
        allowed, retry_after = await check_gate(request.app.state.cache)
        if not allowed:
            # OBS-05: log only the numeric retry_after, NEVER any
            # sorry-page content. The 503 carries the structured
            # SearchResponse shape so downstream consumers can parse
            # metadata.block_detected uniformly with the existing
            # block branch.
            log.warning("challenge_backoff_active", retry_after=retry_after)
            elapsed_ms = int((time.time() - t_start) * 1000)
            denied_body = SearchResponse(
                query=body.query,
                results=[],
                metadata=Metadata(
                    elapsed_ms=elapsed_ms,
                    cache_hit=False,
                    block_detected=True,
                ),
            )
            return Response(
                status_code=503,
                content=denied_body.model_dump_json(),
                media_type="application/json",
                headers={"Retry-After": str(retry_after)},
            )

        # ── [2] Google fetch: parallel A (query) + B (query + mercadolibre) ──
        browser = request.app.state.browser
        rate_limiter = request.app.state.rate_limit

        url_a = build_serp_url(body.query, meli=False)
        url_b = build_serp_url(body.query, meli=True)

        html_a, block_a = "", None
        html_b, block_b = "", None
        block_detected = False

        try:
            (html_a, block_a), (html_b, block_b) = await asyncio.gather(
                fetch_serp(browser, url_a, rate_limiter),
                fetch_serp(browser, url_b, rate_limiter),
            )
            request.app.state.browser_uses += 2
        except Exception as exc:
            log.warning("google_fetch_failed", error=str(type(exc).__name__))
            elapsed_ms = int((time.time() - t_start) * 1000)
            return SearchResponse(
                query=body.query,
                results=[],
                metadata=Metadata(
                    elapsed_ms=elapsed_ms,
                    cache_hit=False,
                    block_detected=False,
                ),
            )

        # ── [3] detect_block ──
        if block_a or block_b:
            block_detected = True
            block_reason = block_a or block_b
            log.warning("google_fetch_blocked", reason=block_reason)
            # D-11 bridge: dual-write to dataclass + prometheus Counter.
            inc_block_detected(block_reason)  # OBS-06
            # Plan 03-02 / D-09: persist the block event so the next
            # request's check_gate gate fires (exponential backoff
            # arming). MUST happen BEFORE the response return so the
            # state is durable even if the response serialization
            # subsequently fails.
            # WR-02: a transient sqlite error (disk full, WAL locked,
            # busy-timeout exhausted) must NOT bubble out and turn a
            # genuine block into an opaque 500. The block_detected=true
            # response shape is the consumer contract; observability
            # writes must not be load-bearing for it.
            try:
                await record_block(request.app.state.cache)
            except Exception as exc:
                log.warning("record_block_failed", error=type(exc).__name__)
            elapsed_ms = int((time.time() - t_start) * 1000)
            return SearchResponse(
                query=body.query,
                results=[],
                metadata=Metadata(
                    elapsed_ms=elapsed_ms,
                    cache_hit=False,
                    block_detected=True,
                ),
            )

        # ── [4] parse_serp on both results ──
        candidates_a = parse_serp(html_a) if html_a else []
        candidates_b = parse_serp(html_b) if html_b else []

        # ── [5] merge + dedupe + junk-domain blocklist ──
        all_candidates = candidates_a + candidates_b
        all_candidates = dedupe(all_candidates)
        all_candidates = [c for c in all_candidates if not is_junk(c["url"])]

        # Plan 03-02 / D-07: success path — record_success is a no-op
        # unless ≥1h has passed since last_block_at, in which case it
        # resets retry_count to 0 and clears next_allowed_at. This is
        # the recovery trigger after a Google IP cool-off window.
        # WR-07: only treat the fetch as a SUCCESS if at least one
        # candidate survived parse + dedupe + junk blocklist. A 200 OK
        # with zero SERP cards (consent interstitial that bypassed
        # _detect_block, A/B layout, empty-results page) would otherwise
        # reset retry_count=0 and reopen the gate on every retry —
        # exactly the failure mode the D-07 >=1h gate was designed to
        # prevent.
        # WR-02: protect the same way as record_block above.
        if all_candidates:
            try:
                await record_success(request.app.state.cache)
            except Exception as exc:
                log.warning("record_success_failed", error=type(exc).__name__)

        candidates_total = len(all_candidates)
        log.info("parse_done", candidates_total=candidates_total)

        # ── [6] Heuristic pre-classifier + LLM curator on ambiguous only ──
        # Path B (perf-audit 2026-06-04): the heuristic resolves ~76% of typical
        # candidates with precision 100% (price_in_card OR known_store). Only the
        # 24% ambiguous reach the LLM. Cuts cold-path LLM phase from ~75s to ~5-8s
        # and reduces local-llms-router load 4x with no precision loss (hybrid F1
        # 0.92 vs LLM-only F1 0.90 against the Phase 1 labeled fixtures).
        kept_pre, ambiguous = heuristic_pre_classify(all_candidates)
        pre_dropped = candidates_total - len(kept_pre) - len(ambiguous)
        log.info(
            "heuristic_pre_classified",
            n_total=candidates_total,
            n_kept_high_conf=len(kept_pre),
            n_ambiguous=len(ambiguous),
            n_dropped_hard=pre_dropped,
        )

        llm_degraded = False
        llm_filtered_out = pre_dropped  # hard drops by the heuristic count too

        router_healthy = await router_health_check(
            settings.LLM_ROUTER_URL,
            settings.LLM_ROUTER_BEARER_TOKEN,
        )

        if router_healthy and ambiguous:
            kept_llm, dropped_llm, llm_degraded = await curate_candidates(
                ambiguous,
                settings.LLM_ROUTER_URL,
                settings.LLM_ROUTER_BEARER_TOKEN,
                concurrency=settings.LLM_CONCURRENCY,
            )
            llm_filtered_out += dropped_llm

            # LLM-06: if the curator dropped every ambiguous candidate because the
            # router systematically failed (model_capability_mismatch returns 400
            # for every call, etc.), fall back to has_price heuristic on the
            # ambiguous set so the response isn't empty. The kept_pre survivors
            # already carry the high-confidence signal so they always survive.
            if llm_degraded and not kept_llm:
                log.warning("llm_degraded_all_dropped_fallback_to_heuristic")
                kept_llm = [c for c in ambiguous if c.get("has_price")]
                llm_filtered_out = candidates_total - len(kept_pre) - len(kept_llm)
        elif not ambiguous:
            # Nothing for the LLM to decide — heuristic alone covered everything.
            kept_llm = []
        else:
            # Router down: degraded mode for the ambiguous set only.
            llm_degraded = True
            log.warning("llm_degraded_router_down")
            kept_llm = [c for c in ambiguous if c.get("has_price")]
            llm_filtered_out = candidates_total - len(kept_pre) - len(kept_llm)

        survivors = kept_pre + kept_llm

        # Last-ditch safety: if both buckets ended empty but we had any candidates
        # at all, keep the high-confidence ones (heuristic side). If even those
        # were empty, the request is honestly empty — don't pad the response.
        if not survivors and all_candidates and kept_pre:
            survivors = kept_pre
            llm_filtered_out = candidates_total - len(survivors)

        # ── [7] Visit pass ──
        # VISIT-03: pass per-request timeout explicitly (not the default)
        visited_count = 0
        visit_failed_count = 0

        if survivors:
            survivors = await visit_candidates(
                survivors,
                visit_timeout_s=body.visit_timeout_s,
            )
            visited_count = sum(
                1
                for c in survivors
                if not c.get("meli_skip") and not c.get("visit_failed") and not c.get("skip_dead")
            )
            visit_failed_count = sum(1 for c in survivors if c.get("visit_failed"))

        # ── [8] Freshness assessment ──
        # CR-01 fix: pass candidate as `extracted` so FRESH-02 can read date fields
        # that visit_one stored via candidate.update(extracted). freshness.py also
        # reads candidate["freshness_signal"] (set by curate_candidates) directly.
        for candidate in survivors:
            fresh_val = assess_freshness(
                candidate,
                verdict=None,
                extracted=candidate,
            )
            candidate["fresh"] = fresh_val

        # ── [9] Re-rank ──
        ranked = rerank(survivors, max_results=body.max_results)

        # ── Build Candidate list ──
        results = []
        for c in ranked:
            # Price priority: parser's price → SERP card price_in_card (now extracted
            # via regex in search.py, was always None before) → LLM verdict price_hint.
            # The card-level price is more reliable than the LLM hint (LLM can hallucinate;
            # the SERP card showed it directly).
            price_val = c.get("price") or c.get("price_in_card") or c.get("price_hint")
            results.append(
                Candidate(
                    url=c["url"],
                    title=c.get("title"),
                    snippet=c.get("snippet"),
                    price=price_val,
                    currency=c.get("currency"),
                    has_price=bool(price_val),
                    fresh=c.get("fresh"),
                    llm_confidence=c.get("llm_confidence", 0.0),
                    freshness_signal=c.get("freshness_signal", "unknown"),
                    installments=c.get("installments"),
                    stock=c.get("stock"),
                    free_shipping=bool(c.get("free_shipping")),
                    rating=c.get("rating"),
                    store_hint=c.get("store_hint"),
                    flags=c.get("flags", []),
                )
            )

        elapsed_ms = int((time.time() - t_start) * 1000)

        # ── [10] Cache write (non-blocking — fire and don't await) ──
        # Defensive: skip caching empty result sets so a transient pipeline failure
        # doesn't poison the cache for 24h (would hide subsequent retries' real output).
        async def _write_cache() -> None:
            if not results:
                return
            try:
                await set_cached(
                    cache=request.app.state.cache,
                    cache_key=cache_key,
                    query=body.query,
                    query_norm=query_norm,
                    response={"results": [r.model_dump() for r in results]},
                    html_a=html_a,
                    html_b=html_b,
                )
            except Exception as exc:
                log.warning("cache_write_failed", error=str(type(exc).__name__))

        # WR-03: retain a strong reference to the task so Python doesn't
        # garbage-collect it mid-flight (asyncio.create_task keeps only a
        # weak ref). The done_callback removes it once the task finishes.
        _cache_task = asyncio.create_task(_write_cache())
        request.app.state.background_tasks.add(_cache_task)
        _cache_task.add_done_callback(request.app.state.background_tasks.discard)

        # Phase 0.2.2 HARNESS-03 — sample 1/N of production traffic for parity
        # drift detection. Reuses html_a (the non-meli SERP) already produced
        # by the pipeline; NO extra Cloak fetch. Set PARITY_SAMPLE_RATE=0 to
        # disable. Same bg-task strong-ref pattern as the cache write above.
        if html_a and random.random() < settings.PARITY_SAMPLE_RATE:
            _parity_task = asyncio.create_task(
                _parity_audit_sample(body.query, html_a)
            )
            request.app.state.background_tasks.add(_parity_task)
            _parity_task.add_done_callback(
                request.app.state.background_tasks.discard
            )

        return SearchResponse(
            query=body.query,
            results=results,
            metadata=Metadata(
                elapsed_ms=elapsed_ms,
                google_fetches=2,
                candidates_total=candidates_total,
                llm_filtered_out=llm_filtered_out,
                visited=visited_count,
                visit_failed=visit_failed_count,
                cache_hit=False,
                llm_degraded=llm_degraded,
                block_detected=block_detected,
            ),
        )

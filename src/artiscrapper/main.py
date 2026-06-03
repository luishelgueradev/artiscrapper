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
import time
from contextlib import asynccontextmanager

import aiosqlite
import httpx
import structlog
from asgi_correlation_id import CorrelationIdMiddleware
from cloakbrowser import launch_async  # Phase 1 confirmed: this is the correct import path
from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse

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
from .config import settings
from .freshness import assess_freshness
from .llm import curate_candidates, router_health_check
from .logging_setup import configure_logging
from .metrics import metrics
from .models import Candidate, Metadata, SearchRequest, SearchResponse
from .rate_limit import GoogleRateLimiter
from .search import build_serp_url, dedupe, is_junk, parse_serp, rerank
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
# CorrelationIdMiddleware must be outermost (added last = executed first in request chain)
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
async def health_deep(request: Request) -> dict:
    """
    OBS-02: Real roundtrip. NEVER call from load balancer (eats Chromium nav).
    Use only from cron / manual smoke test.
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
# POST /search — Full 10-step pipeline (plan 02-02)
# CACHE-05: NEVER fetch Google without checking cache first.
# VISIT-03: visit_timeout_s=request.visit_timeout_s — per-request timeout threaded through.
# ──────────────────────────────────────────


@app.post("/search", response_model=SearchResponse)
async def search(request: Request, body: SearchRequest) -> SearchResponse:
    """
    POST /search — Full 10-step pipeline wired in plan 02-02.
    Field name is 'query' (NOT 'q') per PRD SEARCH-01.

    [1] cache lookup → [2] Google fetch (parallel A+B) → [3] detect_block →
    [4] parse_serp → [5] merge+dedupe+blocklist → [6] LLM filter (or degraded mode) →
    [7] visit_candidates → [8] assess_freshness → [9] rerank → [10] cache write → response
    """
    t_start = time.time()

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
        metrics.block_detected_total[block_reason] += 1  # OBS-06
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

    candidates_total = len(all_candidates)
    log.info("parse_done", candidates_total=candidates_total)

    # ── [6] LLM curator (or degraded mode) ──
    llm_degraded = False
    llm_filtered_out = 0

    router_healthy = await router_health_check(
        settings.LLM_ROUTER_URL,
        settings.LLM_ROUTER_BEARER_TOKEN,
    )

    if router_healthy and all_candidates:
        survivors, llm_filtered_out, llm_degraded = await curate_candidates(
            all_candidates,
            settings.LLM_ROUTER_URL,
            settings.LLM_ROUTER_BEARER_TOKEN,
            concurrency=settings.LLM_CONCURRENCY,
        )
        # LLM-06: if the curator dropped everything because the router systematically
        # failed (e.g., model_capability_mismatch returns 400 for every call), fall back
        # to the same heuristic-only mode the router-down branch uses. Without this,
        # `llm_degraded=True` would surface in metadata but the response would be empty.
        if llm_degraded and not survivors:
            log.warning("llm_degraded_all_dropped_fallback_to_heuristic")
            survivors = [c for c in all_candidates if c.get("has_price")]
            if not survivors:
                survivors = all_candidates
            llm_filtered_out = candidates_total - len(survivors)
    else:
        # LLM-06: degraded mode — router down or no candidates
        if not router_healthy:
            llm_degraded = True
            log.warning("llm_degraded_router_down")
        # Heuristic-only filtering: keep candidates that have price_in_card
        # or that weren't filtered by the junk-domain blocklist (already done above)
        survivors = [c for c in all_candidates if c.get("has_price")]
        if not survivors:
            survivors = all_candidates  # fallback: keep all non-junk candidates
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

    asyncio.create_task(_write_cache())

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

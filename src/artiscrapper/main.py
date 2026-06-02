"""
FastAPI application with lifespan (Cloak singleton + SIGSTOP heartbeat + sqlite cache init).
Pattern 1 from 02-RESEARCH.md (lines 287-402) — lifespan + _recycle_browser_loop.
Pattern 11 from 02-RESEARCH.md (lines 1233-1293) — /health + /health/deep.
Phase 1 NEEDS-PIVOT applied: _recycle_browser_loop includes page.evaluate("1") heartbeat
every 10s to catch SIGSTOP (is_connected() stays True on SIGSTOP — SPIKE.md §Browser confirmed).
D6: uvicorn --loop asyncio --workers 1 — never uvloop.
D8: only ephemeral new_context() per request — no persistent browser contexts.
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

from .cache import get_cached, init_schema, make_cache_key, normalize_query, PRAGMAS, prune_loop, set_cached
from .config import settings
from .logging_setup import configure_logging
from .models import Metadata, SearchRequest, SearchResponse
from .rate_limit import GoogleRateLimiter

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
        try:
            ctx = await browser.new_context()
            page = await ctx.new_page()
            await asyncio.wait_for(page.evaluate("1"), timeout=5.0)
            await page.close()
            await ctx.close()
        except Exception as exc:
            log.warning("browser_heartbeat_failed", error=str(type(exc).__name__))
            app.state.browser = await launch_async(headless=settings.HEADLESS)
            app.state.browser_uses = 0
            try:
                await browser.close()
            except Exception:
                pass
            continue
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
    app.state.rate_limit = GoogleRateLimiter(
        min_interval_s=settings.GOOGLE_MIN_INTERVAL_S
    )

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
    browser = request.app.state.browser
    try:
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await asyncio.wait_for(
            page.goto("about:blank", wait_until="domcontentloaded"),
            timeout=5.0,
        )
        out["cloak"] = "ok_deep"
        await page.close()
        await ctx.close()
    except Exception as exc:
        out["cloak"] = f"fail:{type(exc).__name__}"
        out["status"] = "degraded"
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
# POST /search (Wave 1 stub — cache lookup only)
# Full implementation: LLM + visit pass added in plan 02-02
# ──────────────────────────────────────────

@app.post("/search", response_model=SearchResponse)
async def search(request: Request, body: SearchRequest) -> SearchResponse:
    """
    POST /search — Wave 1 stub: cache lookup + placeholder response.
    Full handler composition (LLM + visit + fresh + rerank) ships in plan 02-02.
    Field name is 'query' (NOT 'q') per PRD SEARCH-01.
    """
    t_start = time.monotonic()

    # Bind per-request structlog context
    cache_key = make_cache_key(body.query)
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        query_hash=cache_key[:12],
        stage="search",
    )

    # Cache lookup (CACHE-05: NEVER fetch Google without checking cache first)
    cached = await get_cached(request.app.state.cache, cache_key)
    if cached is not None:
        log.info("cache_hit")
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        return SearchResponse(
            query=body.query,
            results=cached.get("results", []),
            metadata=Metadata(
                elapsed_ms=elapsed_ms,
                cache_hit=True,
                candidates_total=len(cached.get("results", [])),
            ),
        )

    # Cache miss — Wave 1 stub: return empty results
    # Full pipeline (fetch SERP → parse → LLM → visit → rerank) ships in 02-02
    log.info("cache_miss_stub_response")
    elapsed_ms = int((time.monotonic() - t_start) * 1000)
    return SearchResponse(
        query=body.query,
        results=[],
        metadata=Metadata(
            elapsed_ms=elapsed_ms,
            cache_hit=False,
            block_detected=False,
        ),
    )

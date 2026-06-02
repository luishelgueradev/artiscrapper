# Phase 2: MVP — Research

**Researched:** 2026-06-02
**Domain:** FastAPI + Cloakbrowser + aiosqlite + structlog + httpx + selectolax integration wiring
**Confidence:** HIGH — all locked decisions come from Phase 1 empirical measurements (SPIKE.md) + pre-existing research briefs. This document fills the integration-layer gaps the PRD doesn't spell out.

---

## Summary

Phase 1 locked every architectural decision empirically. Phase 2 ships the production code. This research document answers the twelve integration-layer gaps that the PRD leaves underspecified — the exact Python wiring that executor agents need to write correct code on the first try.

**Three Phase 1 pivots that MUST be reflected in all three plans:**

1. **SIGSTOP heartbeat**: `Browser.is_connected()` does NOT flip on SIGSTOP (SPIKE.md §Browser — NEEDS-PIVOT). Plan 02-01 MUST add a `page.evaluate("1")` periodic heartbeat (~10s) alongside `is_connected()` inside `_recycle_browser_loop`.
2. **System deps**: Cloak/Chromium needs `libnspr4` + `libnss3` installed in the Docker image. Plan 02-01 Dockerfile MUST include `apt-get install -y libnspr4 libnss3` (SPIKE.md §Risks).
3. **Real-URL discovery**: Plan 02-02 visit pass MUST consume real PDP URLs from the Google SERP cascade — never construct catalog URLs from query terms. Slug-guessing inflates `visit_failed` rate to ~70% (SPIKE.md §Risks).

**Router shape (supersedes brief 02-llm-curator.md):** `local-llms-router` is OpenAI-compatible — `POST http://127.0.0.1:3210/v1/chat/completions` with `Authorization: Bearer $TOKEN`. Response field is `choices[0].message.content`, NOT `message.content`. JSON mode is `response_format: {type: "json_object"}`. No `format=<json_schema>` token-level grammar (SPIKE.md §LLM + 01-RESEARCH.md).

**LLM concurrency empirically confirmed at 4** (SPIKE.md §LLM — N=4 burst: 4/4 200, mean=0.81s; N=8: 8/8 200, mean=1.09s — queue absorbs without 429/503). `LLM_CONCURRENCY=4` is the correct default.

**D12 confirmed HAND-ROLL**: 9/10 catalog fixtures `jsonld-sufficient` (SPIKE.md §D12 Decision). `extruct` is NOT in pyproject.toml.

**Primary recommendation:** Follow the three-plan split (02-01 core pipeline, 02-02 LLM+visit+cache, 02-03 obs+deploy+tests) as-drafted in ROADMAP.md, applying the three Phase 1 pivots above to plans 02-01 and 02-02.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SEARCH-01 | POST /search endpoint with Pydantic request/response models | §FastAPI lifespan pattern; §Pydantic models |
| SEARCH-02 | Cache lookup in sqlite before any Google fetch | §Cache patterns — lazy TTL |
| SEARCH-03 | 2 parallel Google fetches via Cloakbrowser with exact URL params | §build_serp_url(); §Cloak launch_async pattern |
| SEARCH-04 | Parser cascade: tF2Cxc → Ez5pwe → MjjYud → h3-anchored | §Parser cascade code |
| SEARCH-05 | URL canonicalization + dedupe | §URL canonicalization pattern |
| SEARCH-06 | Heuristic junk-domain blocklist before LLM | §Blocklist pre-filter |
| SEARCH-07 | Re-rank by (has_price DESC, fresh DESC, llm_confidence DESC) | §Re-rank logic |
| SEARCH-08 | Response metadata fields | §Response model shape |
| LLM-01 | Per-candidate HTTP call to local-llms-router, Spanish prompt + 2 few-shot | §LLM prompt + call pattern |
| LLM-02 | LLMVerdict Pydantic model with fallback() classmethod | §LLMVerdict model |
| LLM-03 | asyncio.Semaphore(LLM_CONCURRENCY=4) | §LLM concurrency pattern |
| LLM-04 | 5s timeout → confidence=0.3 fallback | §LLM failure taxonomy |
| LLM-05 | confidence<0.4 cut + metadata.llm_degraded | §D2 foot-gun implementation |
| LLM-06 | Degraded mode: router down → heuristic blocklist + price-in-card | §LLM degraded mode |
| LLM-07 | temperature=0.0, max_tokens=128, format=json | §LLM call signature |
| LLM-08 | Never log prompt/response content | §OBS-05 allow-list |
| VISIT-01 | Skip-if-you-can: skip if price or live_marketplace | §Visit skip logic |
| VISIT-02 | httpx.AsyncClient(http2=True) + global Semaphore(8) + per-host Semaphore(2) | §httpx + semaphore orchestration |
| VISIT-03 | 10s timeout per visit | §httpx timeout config |
| VISIT-04 | Chromium-146 headers + Sec-Fetch-Site: cross-site + Referer | §DEFAULT_HEADERS |
| VISIT-05 | classify_response() live-vs-dead | §classify_response() |
| VISIT-06 | Hand-rolled JSON-LD + OG + microdata + AR-regex extractor | §Hand-rolled extractor |
| VISIT-07 | failure flags skip_dead/visit_failed, no retry | §visit failure handling |
| VISIT-08 | Never visit *.mercadolibre.* | §MELI host guard |
| FRESH-01 | MELI + 200 → fresh=true | §Freshness logic |
| FRESH-02 | datePublished/dateModified <90d → fresh=true | §Freshness logic |
| FRESH-03 | LLM blog → already dropped by LLM-05 | §LLM cutoff |
| FRESH-04 | No signal → fresh=unknown (not false) | §Freshness logic |
| CACHE-01 | aiosqlite + WAL + schema | §sqlite DDL |
| CACHE-02 | gzipped BLOB raw_serp_html_a/b | §gzip insert/select |
| CACHE-03 | Cache key = sha256(query_norm) | §cache key function |
| CACHE-04 | Lazy TTL on read + hourly prune + nightly checkpoint | §prune loop |
| CACHE-05 | NEVER fetch Google without checking cache first | §cache-first invariant |
| BROWSER-01 | Singleton Browser in lifespan | §FastAPI lifespan + Cloak singleton |
| BROWSER-02 | Ephemeral new_context() per request | §new_context() per request |
| BROWSER-03 | Recycle every BROWSER_RECYCLE_AFTER=200 | §recycle loop with heartbeat |
| BROWSER-04 | asyncio.Semaphore(1) + timestamp gate for Google rate-limit | §GoogleRateLimiter |
| BROWSER-05 | _detect_block() markers | §_detect_block() |
| DEPLOY-01 | Dockerfile multi-stage cloakhq/cloakbrowser:0.3.31 base | §Dockerfile pattern |
| DEPLOY-02 | Pin chromium-v146.0.7680.177.5 | §Chromium pin |
| DEPLOY-03 | uvicorn --loop asyncio --workers 1, no uvloop | §D6 foot-gun + CI assertion |
| DEPLOY-04 | tini / docker run --init | §Dockerfile tini |
| DEPLOY-05 | uv sync --locked + uv.lock checked-in, CI uvloop assertion | §uv + CI |
| DEPLOY-06 | compose.yml dev local with sqlite bind-mount | §compose.yml |
| OBS-01 | GET /health cheap (<50ms) | §health endpoint |
| OBS-02 | GET /health/deep Cloak roundtrip + LLM HEAD | §health/deep endpoint |
| OBS-03 | structlog JSON + merge_contextvars + bindings | §structlog wiring |
| OBS-04 | asgi-correlation-id middleware | §middleware order |
| OBS-05 | Never log scraped content, allow-list per log site | §OBS-05 allow-list |
| OBS-06 | Inline counters llm_fallback_total + visit_failed_total | §inline counters |
| NF-01 | P50 cache-hit <500ms, P50 cold <20s, P95 cold <40s | §latency budget |
| NF-02 | pytest unit + integration tests with respx | §validation architecture |
| NF-03 | ruff clean + mypy strict on public modules | §tooling config |
| NF-04 | $0/month additional cost | architecture constraint |
</phase_requirements>

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| HTTP request handling | FastAPI (ASGI) | — | Single-worker asyncio process; all concurrency managed in-process |
| Browser singleton lifecycle | FastAPI lifespan | asyncio background task (recycle loop) | Browser boots once at startup, recycled every 200 fetches |
| Google SERP fetching | Cloakbrowser (Chromium) | — | Stealth Chromium only; no fallback. Rate-limited by GoogleRateLimiter |
| SERP HTML parsing | selectolax (in-process) | — | Synchronous CPU work; fast enough to block the event loop briefly |
| Candidate filtering (pre-LLM) | in-process CPU (blocklist) | — | Pure Python dict/set lookup, no I/O |
| LLM classification | httpx → local-llms-router | — | External HTTP; async with Semaphore(4); never Cloak |
| Product extraction (visit pass) | httpx → selectolax | — | External HTTP; async with Semaphore(8) global + Semaphore(2) per-host |
| Cache read/write | aiosqlite (single connection) | — | WAL mode; single shared connection per process lifetime |
| Cache prune + WAL checkpoint | asyncio.Task (background) | — | Runs hourly in the same event loop |
| Correlation ID propagation | asgi-correlation-id middleware | structlog contextvars | Middleware extracts/generates; structlog merge_contextvars emits on every log line |
| Health checks | FastAPI GET endpoints | — | /health: cheap; /health/deep: Cloak nav + LLM HEAD |
| Metrics (counters) | in-process dicts/attrs | — | Incremented inline; Phase 3 exposes via Prometheus |
| Configuration | pydantic-settings (env) | — | All tunable params via env vars with typed defaults |

---

## Standard Stack

### Core Production Dependencies

| Library | Version (verified) | Purpose | Why Standard |
|---------|--------------------|---------|--------------|
| `cloakbrowser` | `==0.3.31` | Stealth Chromium for Google SERP fetching | D1 locked empirically; Phase 1 confirmed Docker tag + import path [VERIFIED: PyPI + SPIKE.md] |
| `fastapi` | `==0.136.3` | ASGI framework, /search + /health endpoints | Project constraint; current latest [VERIFIED: PyPI] |
| `uvicorn` | `==0.48.0` | ASGI server; ALWAYS `--loop asyncio --workers 1` | D6 foot-gun; current latest [VERIFIED: PyPI] |
| `pydantic` | `>=2.0` | Request/response models + LLMVerdict validation | Already in spike env; v2 API required [VERIFIED: pypi] |
| `pydantic-settings` | `>=2.0` | Typed env-var config (Settings class) | Standard FastAPI companion [ASSUMED: verify exact latest] |
| `aiosqlite` | `==0.22.1` | Async sqlite cache layer | CACHE-01 locked; current latest [VERIFIED: PyPI] |
| `selectolax` | `==0.4.10` | SERP + catalog HTML parsing | Project constraint; 10x faster than BS4; Phase 1 confirmed [VERIFIED: PyPI] |
| `httpx[http2]` | `==0.28.1` | LLM router calls + visit pass | D5 pattern; HTTP/2 required [VERIFIED: PyPI] |
| `structlog` | `==25.5.0` | Structured JSON logging with contextvars | OBS-03; current latest [VERIFIED: PyPI] |
| `asgi-correlation-id` | `==5.0.0` | X-Request-ID middleware | OBS-04; current latest (was 4.3.4 in brief — bumped) [VERIFIED: PyPI] |
| `orjson` | `==3.11.9` | Fast JSON serialization for FastAPI responses | Standard perf dep; current latest [VERIFIED: PyPI] |
| `tldextract` | `==5.3.1` | Per-host registered-domain extraction for visit-pass semaphores | D5 per-host cap; stable library [VERIFIED: PyPI] |

### Dev / Test Dependencies

| Library | Version (verified) | Purpose |
|---------|--------------------|---------|
| `pytest` | `>=9.0` | Test runner [VERIFIED: PyPI] |
| `pytest-asyncio` | `==1.4.0` | Async test support (latest) [VERIFIED: PyPI] |
| `respx` | `==0.23.1` | httpx mock for LLM router tests (NF-02) [VERIFIED: PyPI] |
| `ruff` | `>=0.15` | Lint + format [ASSUMED: verify latest] |
| `mypy` | `>=2.0` | Type checking strict mode [ASSUMED: verify latest] |
| `pytest-cov` | latest | Coverage [ASSUMED] |

### Package Legitimacy Audit

> slopcheck was run against all packages in Phase 1 research (01-RESEARCH.md §Package Legitimacy Audit, 2026-06-01). All 15 packages cleared `[OK]`. Phase 2 adds no new packages beyond those already audited. Version bumps (aiosqlite 0.21→0.22.1, uvicorn 0.47→0.48.0, asgi-correlation-id 4.3.4→5.0.0, fastapi 0.136.1→0.136.3) are point releases on well-established packages.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `cloakbrowser` | PyPI 0.3.31 | ~1 week | niche | github.com/CloakHQ/CloakBrowser | [OK] (Phase 1) | Approved (D1 lock) |
| `fastapi` | PyPI 0.136.3 | 6+ years | extremely high | github.com/fastapi/fastapi | [OK] (Phase 1) | Approved |
| `uvicorn` | PyPI 0.48.0 | 6+ years | extremely high | github.com/encode/uvicorn | [OK] (Phase 1) | Approved |
| `aiosqlite` | PyPI 0.22.1 | 5+ years | very high | github.com/omnilib/aiosqlite | [OK] (Phase 1) | Approved |
| `selectolax` | PyPI 0.4.10 | 4+ years | high | github.com/rushter/selectolax | [OK] (Phase 1) | Approved |
| `httpx[http2]` | PyPI 0.28.1 | 5+ years | very high | github.com/encode/httpx | [OK] (Phase 1) | Approved |
| `structlog` | PyPI 25.5.0 | 10+ years | very high | github.com/hynek/structlog | [OK] (Phase 1) | Approved |
| `asgi-correlation-id` | PyPI 5.0.0 | 3+ years | high | github.com/snok/asgi-correlation-id | [OK] (Phase 1) | Approved |
| `orjson` | PyPI 3.11.9 | 5+ years | very high | github.com/ijl/orjson | [OK] (Phase 1) | Approved |
| `tldextract` | PyPI 5.3.1 | 10+ years | very high | github.com/john-kurkowski/tldextract | [OK] (Phase 1) | Approved |
| `respx` | PyPI 0.23.1 | 4+ years | high | github.com/lundberg/respx | [OK] (Phase 1) | Approved |
| `pytest-asyncio` | PyPI 1.4.0 | 5+ years | very high | github.com/pytest-dev/pytest-asyncio | [OK] (Phase 1) | Approved |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

**IMPORTANT — asgi-correlation-id 5.0.0 API change**: The package jumped from 4.3.4 (used in research briefs) to 5.0.0. The import path for the context var changed from `from asgi_correlation_id.context import correlation_id` to confirm against 5.0.0 docs before wiring structlog. The middleware class `CorrelationIdMiddleware` itself is unchanged. [ASSUMED: verify 5.0.0 API vs 4.3.4 — planner must check changelog before wiring].

**Installation (production):**
```bash
uv add fastapi==0.136.3 uvicorn==0.48.0 cloakbrowser==0.3.31 \
       aiosqlite==0.22.1 selectolax==0.4.10 httpx[http2]==0.28.1 \
       structlog==25.5.0 asgi-correlation-id==5.0.0 orjson==3.11.9 \
       tldextract==5.3.1 pydantic>=2.0 pydantic-settings>=2.0
uv add --group dev pytest>=9.0 pytest-asyncio==1.4.0 respx==0.23.1 \
                   ruff>=0.15 mypy>=2.0 pytest-cov
```

---

## Architecture Patterns

### System Architecture Diagram

```
POST /search
      │
      ▼
CorrelationIdMiddleware  ←── X-Request-ID (or UUID generated)
      │                       binds to structlog contextvars
      ▼
FastAPI handler (async)
      │
      ├─[1] Cache lookup ─────────────────────────────────────────────────────►  aiosqlite
      │     sha256(query_norm) → query_cache table                                   │
      │     expires_at < now → cache miss                                            │
      │     cache HIT ──────────────────────────────────────────────────────────►  200 (fast)
      │
      ├─[2] Heuristic blocklist pre-filter (no I/O — in-process)
      │
      ├─[3] Google fetch (Cloak) ─────────────────────────────────────────────►  Chromium
      │     GoogleRateLimiter.acquire() ≥60s between fetches                        │
      │     asyncio.Semaphore(1) serializes access                                   │
      │     build_serp_url(query, meli=False) ──► URL A                             │
      │     build_serp_url(query, meli=True)  ──► URL B                             │
      │     asyncio.gather(fetch_serp(A), fetch_serp(B)) — parallel                │
      │     _detect_block() after each fetch                                         │
      │     raw HTML → gzip → sqlite BLOB                                           │
      │
      ├─[4] Parser cascade (selectolax, in-process CPU)
      │     tF2Cxc → Ez5pwe → MjjYud → h3-anchored fallback
      │     dedupe by canonical URL
      │     junk-domain blocklist (D9)
      │
      ├─[5] LLM curator ──────────────────────────────────────────────────────►  local-llms-router
      │     asyncio.Semaphore(4) per-candidate calls                            POST /v1/chat/completions
      │     5s timeout → fallback(confidence=0.3)                              Authorization: Bearer
      │     confidence<0.4 OR freshness=blog → drop (D2 foot-gun)
      │     >50% fallback → metadata.llm_degraded=true
      │
      ├─[6] Visit pass (httpx, conditional) ─────────────────────────────────►  AR catalog hosts
      │     skip if: price not None OR freshness=live_marketplace               http2=True
      │     skip if: host in *.mercadolibre.* (VISIT-08)                       Semaphore(8) global
      │     global Semaphore(8) + per-host Semaphore(2)                        Semaphore(2) per-host
      │     classify_response() → live/dead/failed
      │     extract_jsonld_product() → extract_og_product() → regex fallback
      │
      ├─[7] Freshness assessment (in-process, post-visit)
      │
      ├─[8] Re-rank: has_price DESC, fresh DESC, llm_confidence DESC
      │
      ├─[9] Cache write (aiosqlite — non-blocking)
      │
      └─[10] Return JSON response (orjson)

Background tasks (running concurrently in same event loop):
  _recycle_browser_loop — checks every 60s; recycles Browser after 200 uses + SIGSTOP heartbeat
  _prune_cache_loop     — hourly DELETE expired rows + nightly wal_checkpoint(TRUNCATE)

GET /health  ──► browser.is_connected() + SELECT 1 → <50ms
GET /health/deep ──► Cloak nav about:blank + httpx HEAD /healthz → real roundtrip
```

### Recommended Project Structure

```
artiscrapper/
├── src/
│   └── artiscrapper/
│       ├── __init__.py
│       ├── main.py           # FastAPI app, lifespan, add_middleware
│       ├── config.py         # pydantic-settings Settings class
│       ├── logging_setup.py  # configure_logging() + structlog processors
│       ├── browser.py        # launch_async, _recycle_browser_loop, _detect_block, fetch_serp
│       ├── rate_limit.py     # GoogleRateLimiter (Semaphore(1) + timestamp)
│       ├── cache.py          # DDL, PRAGMAS, get_cached, set_cached, prune_loop
│       ├── search.py         # build_serp_url, parse_serp, canonicalize, dedupe, blocklist, rerank
│       ├── llm.py            # LLMVerdict, classify_candidate, SYSTEM_PROMPT, FEW_SHOT_EXAMPLES
│       ├── visit.py          # visit_candidates, classify_response, extractor cascade
│       ├── freshness.py      # assess_freshness(candidate, verdict, extracted)
│       └── models.py         # SearchRequest, SearchResponse, Candidate, Metadata
├── tests/
│   ├── fixtures/
│   │   ├── serp/             # 10 raw SERP HTML files from Phase 1
│   │   ├── catalog/          # 10 raw catalog PDP HTML files from Phase 1
│   │   └── llm/
│   │       └── labelled.jsonl  # 50 labelled candidates from Phase 1
│   ├── test_parser.py        # unit tests against serp fixtures
│   ├── test_llm.py           # integration tests with respx mock
│   ├── test_cache.py         # cache hit/miss + TTL + gzip roundtrip
│   ├── test_visit.py         # classify_response + extractor unit tests
│   ├── test_health.py        # /health + /health/deep shape tests
│   ├── test_footguns.py      # D2 + D6 + D8 invariant assertions
│   └── conftest.py           # shared fixtures: test db, mock app state
├── pyproject.toml
├── uv.lock                   # checked-in
├── Dockerfile
├── compose.yml
└── .dockerignore
```

---

## Pattern 1: FastAPI lifespan + Cloak singleton + recycle loop

**What:** `@asynccontextmanager async def lifespan(app)` that boots Cloak once, exposes singleton via `app.state.browser`, runs background recycle + prune tasks, and tears down cleanly.

**Phase 1 NEEDS-PIVOT applied:** `_recycle_browser_loop` MUST include a SIGSTOP heartbeat (`page.evaluate("1")` attempt) because `is_connected()` does NOT flip on SIGSTOP.

```python
# src/artiscrapper/main.py
import asyncio, gzip, hashlib, time
from contextlib import asynccontextmanager
import aiosqlite
import structlog
from asgi_correlation_id import CorrelationIdMiddleware
from cloakbrowser import launch_async  # NOT async_playwright — Phase 1 confirmed this
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from .logging_setup import configure_logging
from .config import settings
from .cache import init_schema, PRAGMAS, prune_loop
from .rate_limit import GoogleRateLimiter

log = structlog.get_logger()

async def _recycle_browser_loop(app: FastAPI) -> None:
    """
    Recycles the Cloak Browser after BROWSER_RECYCLE_AFTER cold fetches.
    Phase 1 NEEDS-PIVOT: Browser.is_connected() does NOT flip on SIGSTOP.
    Use page.evaluate("1") heartbeat to catch SIGSTOP death.
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

app = FastAPI(
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
    title="artiscrapper",
    version=settings.VERSION,
)
app.add_middleware(CorrelationIdMiddleware)
# Note: CorrelationIdMiddleware must be added BEFORE any logging middleware
# so correlation_id is bound to contextvars before the first log line.
```

**Test override pattern (for unit tests that bypass lifespan):**
```python
# tests/conftest.py
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock
from artiscrapper.main import app

@pytest.fixture
def mock_app_state(tmp_path):
    """Override app.state for tests that don't need a real browser or cache."""
    app.state.browser = MagicMock()
    app.state.browser.is_connected.return_value = True
    app.state.cache = AsyncMock()  # aiosqlite connection mock
    app.state.browser_uses = 0
    app.state.rate_limit = MagicMock()
    app.state.rate_limit.acquire = AsyncMock()
    yield
```

[CITED: fastapi.tiangolo.com/advanced/events/ — lifespan pattern; 04-fastapi-deploy.md §"Recommended skeleton"]

---

## Pattern 2: aiosqlite WAL + gzipped BLOB + lazy TTL + hourly prune

**Schema (DDL):**
```sql
-- src/artiscrapper/cache.py
CREATE TABLE IF NOT EXISTS query_cache (
    cache_key       TEXT PRIMARY KEY,        -- sha256(query_norm).hexdigest()
    query           TEXT NOT NULL,           -- original query (forensics)
    query_norm      TEXT NOT NULL,           -- lowercase, trimmed, collapsed-ws
    response_json   TEXT NOT NULL,           -- full JSON response (without raw_serp_html)
    raw_serp_html_a BLOB,                    -- gzipped HTML of SERP A (q alone)
    raw_serp_html_b BLOB,                    -- gzipped HTML of SERP B (q +mercadolibre)
    created_at      INTEGER NOT NULL,        -- unix epoch
    expires_at      INTEGER NOT NULL,        -- unix epoch (created_at + 86400)
    bytes_total     INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_cache_expires_at ON query_cache(expires_at);
CREATE INDEX IF NOT EXISTS ix_cache_created_at ON query_cache(created_at);
```

**PRAGMA configuration:**
```python
PRAGMAS = [
    "PRAGMA journal_mode=WAL",         # concurrent reads while writing
    "PRAGMA synchronous=NORMAL",       # safe + ~2x faster than FULL
    "PRAGMA temp_store=MEMORY",
    "PRAGMA mmap_size=268435456",      # 256 MB mmap
    "PRAGMA cache_size=-32000",        # 32 MB page cache
    "PRAGMA wal_autocheckpoint=1000",  # default: 1000 pages = ~4 MB
    "PRAGMA busy_timeout=5000",        # wait 5s on contention
    "PRAGMA foreign_keys=ON",
]
```

**Cache key:**
```python
import hashlib, re, unicodedata

def normalize_query(query: str) -> str:
    q = query.lower().strip()
    q = unicodedata.normalize("NFKD", q)
    q = re.sub(r"\s+", " ", q)
    # Strip accessory punctuation but keep alphanumeric + spaces
    q = re.sub(r"[^\w\s]", "", q)
    return q.strip()

def make_cache_key(query: str) -> str:
    return hashlib.sha256(normalize_query(query).encode()).hexdigest()
```

**Insert (gzip the BLOBs):**
```python
import gzip, json, time

async def set_cached(
    cache: aiosqlite.Connection,
    cache_key: str,
    query: str,
    query_norm: str,
    response: dict,
    html_a: str,
    html_b: str,
    ttl_s: int = 86400,
) -> None:
    now = int(time.time())
    blob_a = gzip.compress(html_a.encode("utf-8"), compresslevel=6)
    blob_b = gzip.compress(html_b.encode("utf-8"), compresslevel=6)
    resp_json = json.dumps(response, ensure_ascii=False)
    bytes_total = len(blob_a) + len(blob_b) + len(resp_json.encode())
    await cache.execute(
        """
        INSERT OR REPLACE INTO query_cache
            (cache_key, query, query_norm, response_json,
             raw_serp_html_a, raw_serp_html_b,
             created_at, expires_at, bytes_total)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (cache_key, query, query_norm, resp_json,
         blob_a, blob_b, now, now + ttl_s, bytes_total),
    )
    await cache.commit()
```

**Read (lazy TTL — treat expired as miss, never DELETE in hot path):**
```python
async def get_cached(cache: aiosqlite.Connection, cache_key: str) -> dict | None:
    row = await (await cache.execute(
        "SELECT response_json, expires_at FROM query_cache WHERE cache_key=?",
        (cache_key,)
    )).fetchone()
    if row is None:
        return None
    response_json, expires_at = row
    if expires_at < int(time.time()):
        return None  # stale; let prune_loop sweep it
    return json.loads(response_json)
```

**Prune loop (hourly + nightly WAL checkpoint):**
```python
async def prune_loop(cache: aiosqlite.Connection) -> None:
    while True:
        await asyncio.sleep(3600)  # hourly
        now = int(time.time())
        await cache.execute(
            "DELETE FROM query_cache WHERE expires_at < ?", (now,)
        )
        await cache.commit()
        # Size cap: 2 GB total raw bytes
        cur = await cache.execute("SELECT SUM(bytes_total) FROM query_cache")
        total = (await cur.fetchone())[0] or 0
        if total > 2_000_000_000:
            await cache.execute("""
                DELETE FROM query_cache WHERE cache_key IN (
                    SELECT cache_key FROM query_cache
                    ORDER BY created_at ASC LIMIT 100
                )
            """)
            await cache.commit()
        # Nightly WAL checkpoint (TRUNCATE flushes WAL to main db file)
        if now % 86400 < 3600:
            await cache.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            await cache.commit()
```

[CITED: aiosqlite.omnilib.dev — connection API; 04-fastapi-deploy.md §2]

---

## Pattern 3: structlog + asgi-correlation-id wiring

**Middleware order (CRITICAL):**
```python
# In main.py — CorrelationIdMiddleware MUST be outermost
# (added last in code = executed first in request chain)
app.add_middleware(CorrelationIdMiddleware)
# If you add AccessLogMiddleware later, add it AFTER this line:
# app.add_middleware(LoggingMiddleware)
```

**structlog configuration:**
```python
# src/artiscrapper/logging_setup.py
import logging, sys
import structlog

def add_correlation_id(_logger, _method, event_dict: dict) -> dict:
    """Inject correlation_id from asgi-correlation-id contextvars."""
    # asgi-correlation-id 5.x: check changelog for exact import path
    # 4.x: from asgi_correlation_id.context import correlation_id
    # 5.x: may be from asgi_correlation_id import correlation_id (verify)
    try:
        from asgi_correlation_id import correlation_id  # 5.0 likely path [ASSUMED]
        if cid := correlation_id.get():
            event_dict["correlation_id"] = cid
    except ImportError:
        from asgi_correlation_id.context import correlation_id  # 4.x fallback
        if cid := correlation_id.get():
            event_dict["correlation_id"] = cid
    return event_dict

def configure_logging(json_logs: bool = True, level: str = "INFO") -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors = [
        structlog.contextvars.merge_contextvars,  # pulls query_hash, stage, etc.
        add_correlation_id,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=True)
    )
    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(stream=sys.stdout, level=level, format="%(message)s")
```

**Per-request bindings pattern:**
```python
# At the top of the /search handler:
import structlog
structlog.contextvars.clear_contextvars()
structlog.contextvars.bind_contextvars(
    query_hash=cache_key[:12],  # never the full query or URL
    stage="search",
)
log = structlog.get_logger()
```

**OBS-05 allow-list (never log scraped content):**
```python
# _log_scrape: safe fields only — title/snippet/url are FORBIDDEN in logs
SAFE_CANDIDATE_FIELDS = {"url_hash", "host", "has_price", "freshness_signal", "confidence"}

def log_candidate_safe(log, candidate: dict, verdict: "LLMVerdict") -> None:
    """Emit structlog event with only allow-listed candidate fields (OBS-05)."""
    log.info(
        "candidate_classified",
        url_hash=hashlib.sha256(candidate["url"].encode()).hexdigest()[:12],
        host=urlparse(candidate["url"]).netloc,
        is_product=verdict.is_product,
        confidence=round(verdict.confidence, 2),
        freshness_signal=verdict.freshness_signal,
        # NEVER: title, snippet, url, reason
    )
```

[CITED: structlog.org/en/stable/contextvars.html; snok/asgi-correlation-id README]

---

## Pattern 4: httpx http2 + global Semaphore(8) + per-host Semaphore(2)

**Exact orchestration:**
```python
# src/artiscrapper/visit.py
import asyncio
from collections import defaultdict
from urllib.parse import urlparse
import httpx

GLOBAL_VISIT_CAP = 8
PER_HOST_CAP = 2

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.6",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Chromium";v="146", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",   # D11: came-from-google signal
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.google.com/",  # D11 invariant
}

async def visit_candidates(
    candidates: list[dict],
    visit_timeout_s: int = 10,
) -> list[dict]:
    """
    Visit only candidates that pass skip-if-you-can (VISIT-01).
    Returns enriched candidates with price/freshness filled in.
    """
    global_sem = asyncio.Semaphore(GLOBAL_VISIT_CAP)
    host_sems: dict[str, asyncio.Semaphore] = defaultdict(
        lambda: asyncio.Semaphore(PER_HOST_CAP)
    )

    async def visit_one(candidate: dict) -> dict:
        url = candidate["url"]
        # VISIT-08: never visit *.mercadolibre.*
        if "mercadolibre." in urlparse(url).netloc:
            candidate["flags"] = candidate.get("flags", []) + ["meli_skip"]
            return candidate
        host = urlparse(url).netloc
        async with global_sem, host_sems[host]:
            try:
                async with httpx.AsyncClient(
                    http2=True,
                    headers=DEFAULT_HEADERS,
                    follow_redirects=True,
                    timeout=httpx.Timeout(
                        connect=3.0, read=float(visit_timeout_s), write=3.0, pool=2.0
                    ),
                    limits=httpx.Limits(
                        max_connections=20, max_keepalive_connections=10
                    ),
                ) as client:
                    resp = await client.get(url)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError):
                candidate["visit_failed"] = True
                return candidate
            except Exception:
                candidate["visit_failed"] = True
                return candidate

            outcome = classify_response(resp)
            if outcome == "dead":
                candidate["skip_dead"] = True
                return candidate
            if outcome == "failed":
                candidate["visit_failed"] = True
                return candidate

            extracted = extract_product(resp.text)
            if extracted:
                candidate.update(extracted)
            return candidate

    return await asyncio.gather(*[visit_one(c) for c in candidates])
```

**classify_response():**
```python
# VISIT-05 — live-vs-dead classification
from selectolax.parser import HTMLParser

DEAD_MARKERS = (
    "404", "no encontrad", "not found", "no disponible",
    "producto agotado", "sold out", "producto no existe",
)
SOFT_404_PATHS = {"", "/", "/home", "/index.html", "/buscar", "/search", "/s"}

def classify_response(response: httpx.Response) -> str:
    if response.status_code >= 400:
        return "failed"
    final_path = urlparse(str(response.url)).path.rstrip("/") or "/"
    if final_path in SOFT_404_PATHS or final_path.startswith("/buscar"):
        return "dead"  # redirect-to-home soft-404
    ct = response.headers.get("content-type", "")
    if "html" not in ct:
        return "failed"
    if len(response.content) < 5_000:
        return "failed"  # body size floor
    tree = HTMLParser(response.text)
    title = (tree.css_first("title").text() if tree.css_first("title") else "").lower()
    h1 = (tree.css_first("h1").text() if tree.css_first("h1") else "").lower()
    if any(m in title or m in h1 for m in DEAD_MARKERS):
        return "dead"
    return "live"
```

[CITED: 03-visit-extract.md §Q1, §Q5; 03-visit-extract.md DEFAULT_HEADERS (D11)]

---

## Pattern 5: LLMVerdict + Pydantic + local-llms-router call

**Phase 1 clarification on router API shape:**
- Endpoint: `POST http://127.0.0.1:3210/v1/chat/completions`
- Auth: `Authorization: Bearer <token>` (from env `LLM_ROUTER_BEARER_TOKEN`)
- Model field: `"model": "chat-local"` (or omit — router auto-selects)
- JSON mode: `"response_format": {"type": "json_object"}` (NOT Ollama-native `format=json`)
- Response: `choices[0].message.content` (OpenAI-compat shape, NOT `message.content`)
- No `format=<json_schema>` token-level grammar available (SPIKE.md §LLM confirmed)
- LLM_CONCURRENCY=4 (empirically confirmed: N=4 mean=0.81s, N=8 mean=1.09s, no 429/503)

```python
# src/artiscrapper/llm.py
import json, asyncio
from typing import Literal
import httpx
from pydantic import BaseModel, Field, ValidationError
import structlog

log = structlog.get_logger()

FreshnessSignal = Literal["live_marketplace", "static_catalog", "blog", "unknown"]

class LLMVerdict(BaseModel):
    is_product: bool
    confidence: float = Field(ge=0.0, le=1.0)
    price_hint: float | None = None
    store_hint: str | None = Field(default=None, max_length=80)
    freshness_signal: FreshnessSignal
    reason: str = Field(max_length=140)

    @classmethod
    def fallback(cls, reason: str) -> "LLMVerdict":
        """
        Permissive fallback for LLM failure.
        CRITICAL D2 FOOT-GUN: confidence=0.3 is BELOW the <0.4 cut.
        A candidate with ONLY this fallback verdict IS DROPPED at the cutoff.
        'Permissive' means we don't raise an exception, NOT that we keep the candidate.
        """
        return cls(
            is_product=True,
            confidence=0.3,
            price_hint=None,
            store_hint=None,
            freshness_signal="unknown",
            reason=f"llm_fail:{reason}",
        )

SYSTEM_PROMPT = """Sos un clasificador de resultados de búsqueda de Google para una casa de repuestos automotores en Argentina.

Tu tarea: dado un resultado de búsqueda (título + URL + snippet), decidir si es un PRODUCTO COMPRABLE concreto o ruido (blog, foro, Wikipedia, YouTube, noticia, página institucional).

Respondé ÚNICAMENTE con un objeto JSON válido con este esquema exacto:
{
  "is_product": bool,
  "confidence": float,
  "price_hint": float|null,
  "store_hint": string|null,
  "freshness_signal": string,
  "reason": string
}

Reglas:
- Mercadolibre, Mercado Libre, MELI → freshness_signal="live_marketplace"
- Tienda con catálogo propio → "static_catalog"
- Blog, foro, YouTube, Reddit, Wikipedia, Fandom, noticia → "blog" (is_product=false)
- Si no podés decidir → "unknown" con confidence baja (≤0.4)
- NO inventes precios. Si no ves el número en el snippet, price_hint=null.
- NO inventes tiendas. Si la URL no es clara, store_hint=null.
- reason: máximo 80 caracteres en español

Devolvé sólo el JSON, sin markdown, sin explicaciones extras."""

FEW_SHOT_EXAMPLES = """
Ejemplo 1 — INPUT:
{"title":"Filtro Aceite Mahle Ford Focus 1.6 - $ 8.500","url":"https://www.mercadolibre.com.ar/MLA-12345","snippet":"Envío gratis. Stock disponible. Vendedor con +1000 ventas."}
OUTPUT:
{"is_product":true,"confidence":0.95,"price_hint":8500.0,"store_hint":"Mercadolibre","freshness_signal":"live_marketplace","reason":"Card MELI con precio y stock"}

Ejemplo 2 — INPUT:
{"title":"Cómo cambiar el filtro de aceite paso a paso","url":"https://taller-mecanico-blog.com/cambio-filtro","snippet":"Guía completa con fotos para hacer el mantenimiento vos mismo..."}
OUTPUT:
{"is_product":false,"confidence":0.97,"price_hint":null,"store_hint":null,"freshness_signal":"blog","reason":"Tutorial, no producto"}
"""

USER_TEMPLATE = "INPUT:\n{candidate_json}\nOUTPUT:"

async def classify_candidate(
    client: httpx.AsyncClient,
    candidate: dict,
    sem: asyncio.Semaphore,
    router_url: str,
    bearer_token: str,
) -> LLMVerdict:
    async with sem:
        payload = {
            "model": "chat-local",  # router auto-selects; explicit for audit
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT + FEW_SHOT_EXAMPLES,
                    # KV-cache: constant system prompt across all 30 calls
                },
                {
                    "role": "user",
                    "content": USER_TEMPLATE.format(
                        candidate_json=json.dumps(
                            {k: candidate.get(k) for k in ("title", "url", "snippet")},
                            ensure_ascii=False,
                        )
                    ),
                },
            ],
            "response_format": {"type": "json_object"},  # OpenAI-compat JSON mode
            "temperature": 0.0,
            "max_tokens": 128,
            "stream": False,
        }
        try:
            resp = await client.post(
                f"{router_url}/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {bearer_token}"},
                timeout=5.0,
            )
            resp.raise_for_status()
            # OpenAI-compat shape: choices[0].message.content
            raw = resp.json()["choices"][0]["message"]["content"]
            return LLMVerdict.model_validate_json(raw)
        except httpx.TimeoutException:
            return LLMVerdict.fallback("timeout")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 503:
                # Ollama queue full — single retry after 1s
                await asyncio.sleep(1.0)
                try:
                    resp2 = await client.post(
                        f"{router_url}/v1/chat/completions",
                        json=payload,
                        headers={"Authorization": f"Bearer {bearer_token}"},
                        timeout=5.0,
                    )
                    resp2.raise_for_status()
                    raw2 = resp2.json()["choices"][0]["message"]["content"]
                    return LLMVerdict.model_validate_json(raw2)
                except Exception:
                    return LLMVerdict.fallback("overload")
            return LLMVerdict.fallback(f"http_{e.response.status_code}")
        except (json.JSONDecodeError, ValidationError, KeyError):
            return LLMVerdict.fallback("malformed")
        except Exception:
            return LLMVerdict.fallback("conn_error")


def should_keep(verdict: LLMVerdict) -> bool:
    """D2 FOOT-GUN: confidence=0.3 fallback IS dropped here. This is intentional."""
    if not verdict.is_product:
        return False
    if verdict.confidence < 0.4:
        return False        # D2: 0.3 < 0.4 → DROPPED
    if verdict.freshness_signal == "blog":
        return False
    return True
```

[CITED: 02-llm-curator.md §Q6; SPIKE.md §LLM (router shape confirmed); 01-RESEARCH.md §Pattern 4]

---

## Pattern 6: Hand-rolled extractor (D12 HAND-ROLL confirmed)

**Phase 1 result:** 9/10 catalog fixtures `jsonld-sufficient`. `extruct` NOT added.

```python
# src/artiscrapper/visit.py — extractor section
import json, re
from selectolax.parser import HTMLParser

# AR price formats: $18.032,30 / ARS 18.032,30 / $ 18.032 / 18032,30 pesos
AR_PRICE_PATTERN = re.compile(
    r'(?:ARS|pesos|ar\$)?\s*\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)',
    re.IGNORECASE,
)

def extract_jsonld_product(tree: HTMLParser) -> dict | None:
    """JSON-LD Product extraction. Handles @graph wrappers (Tiendanube/VTEX pattern)."""
    for script in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text())
        except (json.JSONDecodeError, ValueError):
            continue
        items = data if isinstance(data, list) else [data]
        # Flatten @graph (Tiendanube emits @graph wrapper with Product inside)
        expanded = []
        for item in items:
            if isinstance(item, dict) and "@graph" in item:
                expanded.extend(item["@graph"])
            else:
                expanded.append(item)
        for item in expanded:
            if not isinstance(item, dict):
                continue
            t = item.get("@type")
            if t == "Product" or (isinstance(t, list) and "Product" in t):
                return item
    return None

def extract_og_product(tree: HTMLParser) -> dict | None:
    """OG product:* extraction (NOT og:price — canonical is product:price:amount)."""
    metas: dict[str, str] = {}
    for m in tree.css("meta[property]"):
        prop = m.attributes.get("property", "")
        content = m.attributes.get("content", "")
        if prop and content:
            metas[prop] = content
    if "product:price:amount" not in metas:
        return None
    return {
        "price": metas["product:price:amount"],
        "currency": metas.get("product:price:currency", "ARS"),
        "name": metas.get("og:title"),
        "image": metas.get("og:image"),
    }

def extract_microdata_product(tree: HTMLParser) -> dict | None:
    """Microdata itemprop (legacy Magento/older Tiendanube templates)."""
    product_el = tree.css_first('[itemtype$="/Product"]')
    if not product_el:
        return None
    price_el = product_el.css_first('[itemprop="price"]')
    if price_el:
        price_val = price_el.attributes.get("content") or price_el.text(strip=True)
        currency_el = product_el.css_first('[itemprop="priceCurrency"]')
        currency = (
            currency_el.attributes.get("content", "ARS") if currency_el else "ARS"
        )
        return {"price": price_val, "currency": currency}
    return None

def extract_price_regex(tree: HTMLParser) -> dict | None:
    """
    AR price regex fallback — last resort.
    Scopes to price-like elements first, then full text.
    Phase 1: Falabella CL-redirect fixture hit this tier.
    Real Falabella AR PDPs serve JSON-LD (SPIKE.md §D12 Decision rationale).
    """
    # Scope to price-like elements
    for selector in (".price", ".precio", ".product-price", '[itemprop="price"]'):
        el = tree.css_first(selector)
        if el:
            m = AR_PRICE_PATTERN.search(el.text(strip=True))
            if m:
                return {"price": m.group(1).replace(".", "").replace(",", "."), "currency": "ARS"}
    # Full-text fallback
    body_text = tree.body.text() if tree.body else ""
    m = AR_PRICE_PATTERN.search(body_text)
    if m:
        return {"price": m.group(1).replace(".", "").replace(",", "."), "currency": "ARS"}
    return None

def extract_product(html: str) -> dict | None:
    """
    Full extraction cascade: JSON-LD → OG → microdata → AR-regex.
    Returns normalized dict with 'price', 'currency', 'name' (when available).
    """
    tree = HTMLParser(html)
    if result := extract_jsonld_product(tree):
        offers = result.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price = offers.get("price") or result.get("price")
        currency = offers.get("priceCurrency", "ARS")
        return {
            "price": str(price) if price else None,
            "currency": currency,
            "name": result.get("name"),
            "availability": offers.get("availability"),
            "date_modified": result.get("dateModified"),
        }
    if result := extract_og_product(tree):
        return {"price": result.get("price"), "currency": result.get("currency", "ARS"),
                "name": result.get("name"), "availability": None, "date_modified": None}
    if result := extract_microdata_product(tree):
        return {"price": result.get("price"), "currency": result.get("currency", "ARS"),
                "name": None, "availability": None, "date_modified": None}
    if result := extract_price_regex(tree):
        return {"price": result.get("price"), "currency": "ARS",
                "name": None, "availability": None, "date_modified": None}
    return None
```

[VERIFIED: SPIKE.md §D12 Decision — 9/10 jsonld-sufficient; 03-visit-extract.md §Q2 verbatim extractor; 01-03-PLAN.md Task 3 verbatim functions]

---

## Pattern 7: Cloak launch_async invocation + new_context chain

**Phase 1 confirmed import path** (SPIKE.md §Browser):
```
Cloak Python import path: from cloakbrowser import launch_async
(NOT async_playwright — 0.3.31 does NOT export async_playwright at top level)
```

```python
# src/artiscrapper/browser.py
from cloakbrowser import launch_async  # Phase 1 confirmed — NOT async_playwright

async def create_browser():
    """Boot the singleton Cloak Browser (called once in lifespan)."""
    browser = await launch_async(
        headless=True,
        # launch_async signature: check cloakbrowser 0.3.31 README for exact args.
        # Phase 1 spike used: headless=True; no channel arg needed (Chromium is bundled).
        # Do NOT pass proxy=None explicitly unless docs say it's safe; omit instead.
    )
    return browser

async def fetch_serp(browser, url: str, rate_limiter) -> tuple[str, str | None]:
    """
    Fetch a Google SERP URL with an ephemeral context.
    Returns (html, block_reason | None).
    D8: NEVER launch_persistent_context.
    """
    await rate_limiter.acquire()  # blocks until GOOGLE_MIN_INTERVAL_S elapsed
    ctx = await browser.new_context(
        locale="es-AR",
        timezone_id="America/Argentina/Buenos_Aires",
        viewport={"width": 1366, "height": 768},
        # NO storage_state, NO user_data_dir
    )
    try:
        page = await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        block_reason = await _detect_block(page)
        html = await page.content()
        await page.close()
        return html, block_reason
    finally:
        await ctx.close()  # ALWAYS close in finally — prevents context leaks
```

[VERIFIED: SPIKE.md §Browser — import path confirmed empirically; 01-google-stealth.md §Q2 lifecycle]

---

## Pattern 8: _detect_block() markers

**Phase 1 D3_VERDICT:** All 10 SERP fixtures clean — no markers hit. But BROWSER-05 still required.

```python
# src/artiscrapper/browser.py

BLOCK_MARKERS = (
    "detected unusual traffic",
    "captcha",
    "sorry/index",           # URL path marker
    "g-recaptcha",           # DOM marker
    'id="captcha-form"',     # DOM marker
    "before you continue",   # consent interstitial (pws=0 was clean, but defensive)
    "aria-label=\"antes de continuar",  # ES variant
)

async def _detect_block(page) -> str | None:
    """
    Returns a block_reason string or None.
    Phase 1: all 10 fixtures clean under D3 URL params.
    Still implement defensively — D3_VERDICT is for THIS VPS IP as of 2026-06-01.
    """
    url = str(page.url or "")
    if "/sorry/" in url or "/sorry?" in url:
        return "sorry_redirect"
    # Content sniff: cheap string checks, NEVER log the content
    content = await page.content()
    content_lower = content.lower()
    if "g-recaptcha" in content_lower or 'id="captcha-form"' in content_lower:
        return "captcha_form"
    if "unusual traffic" in content_lower:
        return "unusual_traffic"
    title_el = await page.title() or ""
    if "unusual traffic" in title_el.lower():
        return "unusual_traffic_title"
    return None
```

When `_detect_block` returns non-None:
1. DO NOT write to cache (don't poison with challenge page)
2. Return `HTTP 503` with `metadata.block_detected=true`
3. Log `google.fetch.blocked reason=<reason>` — NO query string in log

[CITED: 01-google-stealth.md §Q4 _detect_block; SPIKE.md §Browser D3_VERDICT]

---

## Pattern 9: build_serp_url() exact signature

```python
# src/artiscrapper/search.py
from urllib.parse import urlencode, quote

def build_serp_url(query: str, *, meli: bool = False) -> str:
    """
    D3: pws=0&safe=off always. NO num/tbm/udm/site:.
    URL B appends 'mercadolibre' to the query (NOT site: operator).
    """
    q = f"{query} mercadolibre" if meli else query
    # quote_via=quote: spaces become %20, not +
    params = urlencode(
        {"q": q, "hl": "es", "gl": "ar", "pws": "0", "safe": "off"},
        quote_via=quote,
    )
    return f"https://www.google.com/search?{params}"
```

[CITED: 01-google-stealth.md §Q5; research/SUMMARY.md D3]

---

## Pattern 10: D6 CI uvloop-absence assertion

```bash
# In CI (GitHub Actions or local pre-commit):
# Assert uvloop is NOT present in pyproject.toml or uv.lock
grep -rE 'uvloop' pyproject.toml uv.lock && echo "FAIL: uvloop found — D6 foot-gun!" && exit 1 || echo "OK: uvloop absent"

# Also assert in the Dockerfile CMD:
# CMD line must contain --loop asyncio --workers 1
grep -q 'loop asyncio' Dockerfile && grep -q 'workers 1' Dockerfile || { echo "FAIL: Dockerfile CMD missing --loop asyncio --workers 1"; exit 1; }
```

**In pyproject.toml — add to [tool.ruff.lint.per-file-ignores] or a custom test:**
```python
# tests/test_footguns.py
import subprocess, sys

def test_no_uvloop_installed():
    """D6: uvloop must not be importable in the runtime environment."""
    result = subprocess.run(
        [sys.executable, "-c", "import uvloop"],
        capture_output=True,
    )
    assert result.returncode != 0, "uvloop is installed — D6 foot-gun!"

def test_no_persistent_context_in_codebase():
    """D8: launch_persistent_context must not appear in src/."""
    result = subprocess.run(
        ["grep", "-rn", "launch_persistent_context", "src/"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0, (
        f"D8 foot-gun: launch_persistent_context found:\n{result.stdout}"
    )
```

[CITED: REQUIREMENTS.md DEPLOY-03, DEPLOY-05; research/SUMMARY.md D6]

---

## Pattern 11: /health/deep implementation

```python
# src/artiscrapper/main.py

@app.get("/health")
async def health(request: Request) -> dict:
    """
    OBS-01: Cheap liveness check (<50ms). Called by nginx/monitoring.
    Uses cached browser.is_connected() — no Chromium navigation.
    """
    out = {"status": "ok", "cloak": "ok", "llm": "unknown", "cache": "ok"}
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
    D13: cheap probe (above) + deep probe (this) are separate — do not merge.
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
    except Exception as e:
        out["cloak"] = f"fail:{type(e).__name__}"
        out["status"] = "degraded"
    # LLM deep: GET /healthz with bearer
    settings_ref = request.app.state  # assumes settings stored in app state or imported
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(
                f"{settings.LLM_ROUTER_URL}/healthz",
                headers={"Authorization": f"Bearer {settings.LLM_ROUTER_BEARER_TOKEN}"},
            )
            out["llm"] = "ok" if r.status_code == 200 else f"fail:{r.status_code}"
    except Exception as e:
        out["llm"] = f"fail:{type(e).__name__}"
    return out
```

Note: SPIKE.md §LLM confirmed the health endpoint is `/healthz` (with z), not `/health`.

[CITED: 04-fastapi-deploy.md §4; SPIKE.md §LLM router endpoint]

---

## Pattern 12: Dockerfile multi-stage (Phase 1 system deps pivot)

```dockerfile
# syntax=docker/dockerfile:1.7
# CRITICAL Phase 1 NEEDS-PIVOT: cloakbrowser requires libnspr4 + libnss3
# These are NOT bundled in the cloakbrowser wheel. Must install in runtime image.

# --- builder ---
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-editable
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

# --- runtime ---
FROM cloakhq/cloakbrowser:0.3.31 AS runtime
# D1 pin: chromium-v146.0.7680.177.5
# Phase 1 NEEDS-PIVOT: system deps required — absent in the wheel, needed at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnspr4 libnss3 tini \
 && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# D4: tini for zombie reaping (Chromium leaks defunct procs without PID-1 init)
ENTRYPOINT ["/usr/bin/tini", "--"]

# D6 FOOT-GUN: --loop asyncio --workers 1 ALWAYS. Never uvloop.
CMD ["uvicorn", "src.artiscrapper.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--loop", "asyncio"]
```

**compose.yml (dev local):**
```yaml
services:
  artiscrapper:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data/cache.db:/app/cache.db  # sqlite bind-mount (DEPLOY-06)
    environment:
      - CACHE_DB_PATH=/app/cache.db
      - LLM_ROUTER_URL=http://host.docker.internal:3210
      - LLM_ROUTER_BEARER_TOKEN=${LLM_ROUTER_BEARER_TOKEN}
      - GOOGLE_MIN_INTERVAL_S=60
      - BROWSER_RECYCLE_AFTER=200
      - LLM_CONCURRENCY=4
      - LOG_JSON=true
      - LOG_LEVEL=INFO
    init: true  # equivalent to tini if not using ENTRYPOINT tini
```

[CITED: 04-fastapi-deploy.md §6; SPIKE.md §Risks — libnspr4/libnss3 requirement]

---

## Pattern 13: OBS-06 Inline counters (pre-Prometheus)

```python
# src/artiscrapper/metrics.py
# Simple in-process counters. Phase 3 wires these into prometheus-client.
from collections import defaultdict
from dataclasses import dataclass, field

@dataclass
class Metrics:
    llm_fallback_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    visit_failed_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    browser_recycles_total: int = 0
    block_detected_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))

metrics = Metrics()  # process-singleton (safe with --workers 1)

# Usage:
# metrics.llm_fallback_total["timeout"] += 1       (LLM-04 fallback)
# metrics.llm_fallback_total["malformed"] += 1
# metrics.visit_failed_total["falabella.com.ar"] += 1  (VISIT-07)
# metrics.block_detected_total["sorry_redirect"] += 1  (BROWSER-05)
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async sqlite | Blocking sqlite3 in handlers | `aiosqlite` | Thread safety + async-native API |
| JSON-mode LLM output | Custom JSON extractor / regex | `pydantic.model_validate_json()` | Catches type coercion errors (LLM says "yes" for bool) |
| Per-host rate-limit | Token-bucket from scratch | `defaultdict(lambda: asyncio.Semaphore(2))` | Sufficient at this volume; no dep needed |
| Correlation ID threading | Custom UUID middleware | `asgi-correlation-id` | Handles X-Request-ID propagation, contextvars binding, UUID fallback |
| Gzip compression | Manual zlib calls | `gzip.compress()` / `gzip.decompress()` from stdlib | Already in stdlib; no extra dep |
| HTML parsing | `re` patterns on HTML | `selectolax.parser.HTMLParser` | Edge cases in HTML; selectolax handles malformed inputs |
| AR price parsing (ambiguous) | Rolling your own thousand/decimal separator detection | AR_PRICE_PATTERN regex (Pattern 6) | The `. thousands / , decimal` vs `, thousands / . decimal` ambiguity in AR prices requires the specific pattern from SPIKE.md extractor |
| Chromium binary management | Downloading Chromium at container runtime | `cloakhq/cloakbrowser:0.3.31` base image | Runtime download = container boot fails offline; pre-baked in image |
| Structured LLM output (grammar) | `instructor` / `outlines` / `pydantic-ai` | `response_format: {type: json_object}` + `LLMVerdict.model_validate_json()` | Router doesn't support token-level grammar; Pydantic parse + fallback() is sufficient |
| Session persistence across Google fetches | `BrowserContext` reuse | Ephemeral `new_context()` per request | D8: persistent context = CAPTCHA loop (Cloak issue #331) |

**Key insight:** The integration layer between Cloak, FastAPI, and aiosqlite is a coordination problem, not a library problem. The existing libraries handle it correctly; the foot-guns are in how they're wired together (lifecycle order, event loop selection, context management).

---

## Common Pitfalls

### Pitfall 1: Using launch_async() wrong (import path confusion)
**What goes wrong:** Importing `from cloakbrowser import async_playwright` or using `launch()` instead of `launch_async()` causes AttributeError at boot.
**Why it happens:** 01-google-stealth.md brief showed `async_playwright` — this was pre-Phase 1. Phase 1 empirically confirmed the correct path.
**How to avoid:** `from cloakbrowser import launch_async` — only this. No `async_playwright`. No `launch()` (short-lived, not singleton). SPIKE.md §Browser is authoritative.
**Warning signs:** `AttributeError: module 'cloakbrowser' has no attribute 'async_playwright'`

### Pitfall 2: D2 foot-gun — "permissive=0.3 means keep"
**What goes wrong:** Developer reads "permissive fallback confidence=0.3" and assumes LLM-failed candidates are kept. They are NOT — 0.3 < 0.4 cut → dropped.
**Why it happens:** The PRD used "permissive" to mean "don't crash", not "keep the candidate".
**How to avoid:** `should_keep()` function with explicit comment in code. `fallback()` docstring says "NOTE: 0.3 < 0.4 cut → candidate IS dropped". Unit test in `test_footguns.py` pins this.
**Warning signs:** LLM-degraded mode returns more results than expected; `metadata.llm_degraded` missing.

### Pitfall 3: D6 foot-gun — uvloop anywhere
**What goes wrong:** `uvloop` installed (by another dep, or accidentally) causes Playwright pipe hangs under load.
**Why it happens:** Some packages (redis, aiohttp extras) pull uvloop transitively.
**How to avoid:** `grep -rE 'uvloop' pyproject.toml uv.lock` CI assertion. `test_no_uvloop_installed()` unit test.
**Warning signs:** Cloak hangs indefinitely on `page.goto()`; no exception raised; `asyncio.sleep()` stops working.

### Pitfall 4: D8 foot-gun — persistent context against Google
**What goes wrong:** `launch_persistent_context()` causes per-request CAPTCHA loop starting from request #2.
**Why it happens:** Cloak issue #331 is well-documented but easy to confuse with the singleton `Browser` pattern.
**How to avoid:** `test_no_persistent_context_in_codebase()` grep test. Never pass `user_data_dir` to any context call.
**Warning signs:** All SERP fetches after request #1 return a `/sorry/index` challenge page.

### Pitfall 5: response field path error (LLM router)
**What goes wrong:** Accessing `resp.json()["message"]["content"]` (Ollama native shape) instead of `resp.json()["choices"][0]["message"]["content"]` (OpenAI compat shape).
**Why it happens:** 02-llm-curator.md brief described Ollama native shape before Phase 1 confirmed OpenAI-compat.
**How to avoid:** Use `choices[0].message.content` path in all LLM calls. Explicitly check in unit tests.
**Warning signs:** `KeyError: 'message'` on every LLM response; all verdicts are `fallback("malformed")`.

### Pitfall 6: SIGSTOP heartbeat omission
**What goes wrong:** A SIGSTOP-ed Chromium is treated as healthy; all subsequent fetches hang.
**Why it happens:** `is_connected()` stays True for SIGSTOP (Phase 1 confirmed, SPIKE.md §Browser).
**How to avoid:** `_recycle_browser_loop` MUST include the `page.evaluate("1")` heartbeat with 5s timeout.
**Warning signs:** `/search` hangs indefinitely but `GET /health` returns OK; `is_connected()` returns True.

### Pitfall 7: Logging scraped content (OBS-05)
**What goes wrong:** Logging `candidate.title`, `candidate.url`, `candidate.snippet`, or `raw_html` in structlog events.
**Why it happens:** Debug instinct.
**How to avoid:** Only log `url_hash`, `host`, `has_price`, `confidence`, `freshness_signal` from candidates. Use `log_candidate_safe()` wrapper. Ruff custom rule or pre-commit grep for `title=candidate` in log calls.
**Warning signs:** Log lines contain readable product names or URLs.

### Pitfall 8: Visiting *.mercadolibre.* in visit pass
**What goes wrong:** Architecture violation (VISIT-08 + REQUIREMENTS.md Out of Scope). Any `*.mercadolibre.*` URL hit.
**Why it happens:** Google SERP includes many MELI links; visit pass iterates candidates without host check.
**How to avoid:** FIRST line of `visit_one()` is the MELI host guard. Unit test asserts the guard fires.
**Warning signs:** `visit_failed` or `skip_dead` on MELI URLs; 403 from MELI WAF.

### Pitfall 9: asgi-correlation-id 5.0.0 API change
**What goes wrong:** `from asgi_correlation_id.context import correlation_id` raises ImportError (4.x path) or `from asgi_correlation_id import correlation_id` raises ImportError (wrong 5.x path).
**Why it happens:** Major version bump from 4.3.4 (brief) to 5.0.0 (current) may have changed the import path.
**How to avoid:** Check 5.0.0 changelog before wiring. The Pattern 3 code above has a try/except fallback for both paths [ASSUMED: verify 5.0.0 API].
**Warning signs:** `correlation_id` is always `None` in log output; ImportError at boot.

### Pitfall 10: libnspr4/libnss3 absent in Docker image
**What goes wrong:** Container boots but every `launch_async()` call fails with `error while loading shared libraries: libnspr4.so`.
**Why it happens:** Phase 1 NEEDS-PIVOT — these are NOT bundled in the cloakbrowser wheel. WSL2 spike env had them via local .deb extract.
**How to avoid:** Dockerfile MUST include `apt-get install -y libnspr4 libnss3`. This is a HARD REQUIREMENT from SPIKE.md §Risks.
**Warning signs:** Container `GET /health` returns `{"cloak": "fail"}`; Python log shows shared library error.

---

## Code Examples

### Parser cascade (from Phase 1 serp fixtures)
```python
# Source: 01-google-stealth.md §Q3 + SPIKE.md §Browser (10 fixtures clean with tF2Cxc)
ORGANIC_SELECTORS = [
    "div.MjjYud div.tF2Cxc",       # 2024-2026 primary (Phase 1 confirmed)
    "div.MjjYud",                  # 2025+ wrapper fallback
    "div.g",                       # legacy
    "div[data-sokoban-container]", # 2025-2026 experimental
    "div[data-snc]",               # mobile variants
]
CAROUSEL_SELECTORS = [
    "div.Ez5pwe",                  # carousel (Phase 1 fixtures confirmed present)
    "g-scrolling-carousel div[role='listitem']",
]

def parse_serp(html: str) -> list[dict]:
    tree = HTMLParser(html)
    candidates = []
    # Organic
    for sel in ORGANIC_SELECTORS:
        nodes = tree.css(sel)
        if nodes:
            results = [_extract_organic(n) for n in nodes]
            results = [r for r in results if r]
            if results:
                candidates.extend(results)
                break
    else:
        # D4 cascade exhausted alert
        log.warning("parse_cascade_exhausted")
        candidates.extend(_extract_by_h3(tree))
    # Carousel
    for sel in CAROUSEL_SELECTORS:
        nodes = tree.css(sel)
        if nodes:
            candidates.extend([_extract_carousel(n) for n in nodes if _extract_carousel(n)])
            break
    return candidates
```

### URL canonicalization + dedupe (SEARCH-05)
```python
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

STRIP_PARAMS = {"utm_source","utm_medium","utm_campaign","utm_content","utm_term",
                "fbclid","gclid","ved","usg","sa","ei"}

def canonicalize_url(url: str) -> str:
    p = urlparse(url)
    qs = {k: v for k, v in parse_qs(p.query).items() if k not in STRIP_PARAMS}
    return urlunparse((
        p.scheme,
        p.netloc.lower().rstrip("/"),
        p.path.rstrip("/") or "/",
        p.params,
        urlencode(qs, doseq=True),
        "",  # strip fragment
    ))

def dedupe(candidates: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for c in candidates:
        key = canonicalize_url(c["url"])
        if key not in seen:
            seen.add(key)
            c["url"] = key
            out.append(c)
    return out
```

### Junk-domain blocklist (D9, SEARCH-06)
```python
# Evaluated against host (netloc) BEFORE LLM step
JUNK_DOMAINS = frozenset({
    "youtube.com", "www.youtube.com",
    "reddit.com", "www.reddit.com",
    "wikipedia.org", "es.wikipedia.org",
    "medium.com", "www.medium.com",
})
JUNK_DOMAIN_SUFFIXES = (".fandom.com", ".gov.ar", ".medium.com")

def is_junk(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    if host in JUNK_DOMAINS:
        return True
    return any(host.endswith(s) for s in JUNK_DOMAIN_SUFFIXES)
```

### Re-rank (SEARCH-07)
```python
def rerank(candidates: list[dict], max_results: int = 15) -> list[dict]:
    def sort_key(c: dict):
        has_price = 1 if c.get("price") else 0
        fresh = 1 if c.get("fresh") is True else 0
        confidence = c.get("llm_confidence", 0.0)
        return (has_price, fresh, confidence)
    return sorted(candidates, key=sort_key, reverse=True)[:max_results]
```

---

## State of the Art (vs initial research briefs)

| Old State (research briefs, 2026-06-01) | Current State (post Phase 1, 2026-06-02) | Phase 2 Impact |
|-----------------------------------------|-------------------------------------------|----------------|
| `from cloakbrowser import async_playwright` | `from cloakbrowser import launch_async` (NOT async_playwright) | Change all browser.py code |
| LLM router: raw Ollama `/api/chat` | OpenAI-compat `POST /v1/chat/completions` with `choices[0].message.content` | Change all llm.py code |
| `format=<json_schema>` token-level grammar | Only `response_format: {type: "json_object"}` | JSON mode + Pydantic validation (no grammar) |
| LLM_CONCURRENCY=2 (estimated from config) | LLM_CONCURRENCY=4 (empirically: N=4/N=8 both 200) | Use 4 as default |
| extruct for extraction (D12 pending) | HAND-ROLL confirmed (9/10 jsonld-sufficient) | No extruct dep; ship Pattern 6 verbatim |
| `is_connected()` catches all death modes | `is_connected()` misses SIGSTOP; add page.evaluate heartbeat | _recycle_browser_loop must have heartbeat |
| libnspr4/libnss3 assumed bundled | NOT bundled — must install in Dockerfile | Add apt-get to runtime stage |
| asgi-correlation-id 4.3.4 | 5.0.0 (current PyPI) — verify API change | Check import path before wiring |

---

## Validation Architecture

This section is the input for `02-VALIDATION.md` (Nyquist validation contract for Phase 2).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-asyncio 1.4.0 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`asyncio_mode = "auto"`) |
| Quick run command | `uv run pytest tests/ -x -q -k "not e2e"` |
| Full suite command | `uv run pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File |
|--------|----------|-----------|-------------------|------|
| SEARCH-04 | Parser cascade extracts organic + carousel from all 10 serp fixtures | unit | `pytest tests/test_parser.py -x -q` | Wave 0 |
| SEARCH-04 | h3-anchored fallback fires when all selectors return 0 | unit | `pytest tests/test_parser.py::test_cascade_exhausted_alert -x` | Wave 0 |
| SEARCH-05 | canonicalize_url strips utm_*, gclid, ved; dedupes correctly | unit | `pytest tests/test_parser.py::test_canonicalize -x` | Wave 0 |
| SEARCH-06 | Junk-domain blocklist drops youtube/fandom/wikipedia/reddit | unit | `pytest tests/test_parser.py::test_blocklist -x` | Wave 0 |
| LLM-02 | LLMVerdict.model_validate_json() accepts valid JSON | unit | `pytest tests/test_llm.py::test_verdict_valid -x` | Wave 0 |
| LLM-02 | LLMVerdict.fallback() returns confidence=0.3, is_product=True | unit | `pytest tests/test_llm.py::test_fallback_shape -x` | Wave 0 |
| LLM-04/05 | D2: timeout fallback confidence=0.3 is dropped at <0.4 cut | unit | `pytest tests/test_llm.py::test_d2_fallback_is_dropped -x` | Wave 0 |
| LLM-01/07 | LLM router call uses OpenAI-compat shape (choices[0].message.content) | integration (respx) | `pytest tests/test_llm.py::test_router_call_shape -x` | Wave 0 |
| LLM-03 | Semaphore(4) limits concurrent LLM calls | integration | `pytest tests/test_llm.py::test_concurrency_semaphore -x` | Wave 0 |
| VISIT-05 | classify_response() returns dead for redirect-to-home | unit | `pytest tests/test_visit.py::test_classify_soft404 -x` | Wave 0 |
| VISIT-05 | classify_response() returns failed for 4xx | unit | `pytest tests/test_visit.py::test_classify_4xx -x` | Wave 0 |
| VISIT-06 | extract_jsonld_product() extracts price from all 9 jsonld-sufficient catalog fixtures | unit | `pytest tests/test_visit.py::test_extractor_catalog_fixtures -x` | Wave 0 |
| VISIT-06 | AR price regex matches ARS/$/pesos formats | unit | `pytest tests/test_visit.py::test_ar_price_regex -x` | Wave 0 |
| VISIT-08 | MELI host guard fires on any *.mercadolibre.* URL | unit | `pytest tests/test_visit.py::test_meli_guard -x` | Wave 0 |
| CACHE-01 | DDL creates query_cache table with correct schema | integration | `pytest tests/test_cache.py::test_schema -x` | Wave 0 |
| CACHE-02 | set_cached gzips raw_serp_html BLOBs | integration | `pytest tests/test_cache.py::test_gzip_roundtrip -x` | Wave 0 |
| CACHE-03 | make_cache_key is deterministic; identical queries → same key | unit | `pytest tests/test_cache.py::test_cache_key_deterministic -x` | Wave 0 |
| CACHE-04 | get_cached returns None for expired row (lazy TTL) | integration | `pytest tests/test_cache.py::test_lazy_ttl -x` | Wave 0 |
| OBS-01 | GET /health returns 200 with expected JSON shape | integration | `pytest tests/test_health.py::test_health_shape -x` | Wave 0 |
| OBS-02 | GET /health/deep returns cloak and llm status fields | integration (mock) | `pytest tests/test_health.py::test_health_deep_shape -x` | Wave 0 |
| DEPLOY-03 | D6: uvloop not importable in runtime env | unit | `pytest tests/test_footguns.py::test_no_uvloop_installed -x` | Wave 0 |
| DEPLOY-05 | D6: uvloop absent from pyproject.toml + uv.lock | unit (grep) | `pytest tests/test_footguns.py::test_uvloop_absent_from_lock -x` | Wave 0 |
| BROWSER-02 | D8: launch_persistent_context absent from src/ | unit (grep) | `pytest tests/test_footguns.py::test_no_persistent_context -x` | Wave 0 |
| BROWSER-03 | Recycle loop fires after BROWSER_RECYCLE_AFTER uses | unit (mock) | `pytest tests/test_footguns.py::test_recycle_triggers -x` | Wave 0 |
| NF-01 (E2E) | POST /search q=pelota playera quico → ≥10 results, ≥6 with price | e2e (dev-box) | `pytest tests/test_e2e.py::test_serp_pelota -x -m e2e` | Wave 3 |
| NF-01 (E2E) | POST /search identical query within 24h → cache_hit=true, <500ms | e2e (dev-box) | `pytest tests/test_e2e.py::test_cache_hit -x -m e2e` | Wave 3 |
| PRD §10 | Zero blogs/wiki/youtube in top 10 results | e2e + manual | same e2e test + human review | Wave 3 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/ -x -q -k "not e2e"` (< 30s, skips live network)
- **Per wave merge:** `uv run pytest tests/ -x -q -k "not e2e"` full unit + integration suite
- **Phase gate:** Full suite green (including e2e) before `/gsd:verify-work`

### Wave 0 Gaps (files that must be created before Wave 1 implementation)

- [ ] `tests/conftest.py` — shared fixtures: `tmp_db` (aiosqlite in-memory), `mock_browser`, `mock_llm_client`
- [ ] `tests/test_parser.py` — imports serp fixtures from `tests/fixtures/serp/*.html`
- [ ] `tests/test_llm.py` — respx mocks for LLM router; imports labelled.jsonl candidates
- [ ] `tests/test_visit.py` — imports catalog fixtures from `tests/fixtures/catalog/**/*.html`
- [ ] `tests/test_cache.py` — uses tmp_path sqlite file
- [ ] `tests/test_health.py` — uses TestClient with mock app state
- [ ] `tests/test_footguns.py` — D2/D6/D8 invariant grep + import tests
- [ ] `tests/test_e2e.py` — live dev-box test (marked `@pytest.mark.e2e`, skipped by default)
- [ ] `pyproject.toml` `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` and `markers = ["e2e: live network tests"]`

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | All code | ✓ | 3.12.x (WSL2) | — |
| `local-llms-router` at 127.0.0.1:3210 | LLM-01..08 | ✓ | qwen2.5:7b-instruct-q4_K_M (Phase 1 confirmed) | Mock with respx in tests |
| `cloakhq/cloakbrowser:0.3.31` Docker image | DEPLOY-01 | ✓ | 0.3.31 / chromium-v146.0.7680.177.5 (Phase 1 Hub verified) | — |
| aiosqlite 0.22.1 | CACHE-01..05 | ✓ (on PyPI) | 0.22.1 | — |
| Docker + docker compose | DEPLOY-06 | [ASSUMED: present on dev box] | — | Install via package manager |
| uv | Build/deps | [ASSUMED: present] | — | pip as fallback |
| libnspr4 + libnss3 | Chromium (SPIKE.md §Risks) | Present on WSL2 spike host | — | `apt-get install` in Dockerfile handles prod |
| `LLM_ROUTER_BEARER_TOKEN` env | LLM calls | In `.env.spike` (gitignored) | — | Must be set; startup fails without it |

**Missing dependencies with no fallback:**
- `LLM_ROUTER_BEARER_TOKEN` env var — code must fail at startup with a clear message if absent

**Missing dependencies with fallback:**
- `local-llms-router` being down — LLM-06 degraded mode handles this (heuristic blocklist + price-in-card)

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No (single client, API-key deferred to Phase 3) | — |
| V3 Session Management | No | — |
| V4 Access Control | Partial | VISIT-08: never visit *.mercadolibre.* (architecture-level access control) |
| V5 Input Validation | Yes | `SearchRequest` Pydantic model validates query + max_results + visit_timeout_s |
| V6 Cryptography | No (no secrets at rest beyond bearer token in env) | — |
| V14 Configuration | Yes | Bearer token in env (not code); libnspr4 in Docker; uv.lock pinned |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Scraped content in logs (PII/legal) | Information Disclosure | OBS-05 allow-list; log_candidate_safe() wrapper; never log title/snippet/url |
| SSRF via candidate URLs in visit pass | Tampering | VISIT-08 blocks *.mercadolibre.*; visit_one() only visits URLs from Google SERP (controlled source) |
| Bearer token leak via LLM prompt logging | Information Disclosure | LLM-08: never log prompt content; only url_hash/host in logs |
| Chromium process escape via page.evaluate() | Elevation | Cloak's fingerprint patches don't affect sandbox; Chromium --no-sandbox in Docker is acceptable in container |
| D2 confidence threshold soft-coded wrong | Tampering | `should_keep()` with constant `< 0.4`; unit test pins the threshold |
| SQL injection via cache_key | Tampering | `make_cache_key()` uses sha256 hex (alphanumeric only); parameterized queries everywhere |

---

## Open Questions

1. **asgi-correlation-id 5.0.0 import path change**
   - What we know: PyPI current is 5.0.0; briefs reference 4.3.4 with `from asgi_correlation_id.context import correlation_id`
   - What's unclear: exact import path in 5.0.0 (may be same or changed)
   - Recommendation: plan 02-03 first task should `pip install asgi-correlation-id==5.0.0 && python -c "from asgi_correlation_id.context import correlation_id"` to confirm before wiring; the Pattern 3 code has a try/except fallback for both

2. **launch_async() exact kwargs for headless mode**
   - What we know: Phase 1 used `headless=True`; SPIKE.md confirms the call worked
   - What's unclear: full accepted kwarg set for 0.3.31 (proxy, channel, args, etc.)
   - Recommendation: plan 02-01 first task reads cloakbrowser 0.3.31 README/source before writing browser.py; safe to start with `await launch_async(headless=True)` and add args only if needed

3. **LLM router /healthz vs /health endpoint**
   - What we know: SPIKE.md §LLM says `endpoint_ok: YES (200 from /healthz with bearer)`
   - What's unclear: whether `/health` (without z) also exists and which to use in /health/deep
   - Recommendation: use `/healthz` as confirmed by Phase 1 spike; add a try-both fallback in health_deep

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `asgi-correlation-id` 5.0.0 has same or similar import path as 4.3.4 | Pattern 3 | Import error at boot; easy to fix once caught |
| A2 | `launch_async(headless=True)` accepts the same args in 0.3.31 as spike scripts used | Pattern 7 | TypeError at boot; fix by reading 0.3.31 changelog |
| A3 | Docker is available on dev box | Environment Availability | Manual install required; unblocks in <10 min |
| A4 | uv is present on dev box | Build tooling | Use pip as fallback; lock file re-generation needed |
| A5 | `pydantic-settings` version is compatible with pydantic>=2.0 already in use | Standard Stack | Pydantic v2 compatibility — pydantic-settings 2.x is designed for pydantic v2 |

**Claims tagged [VERIFIED]:** All package versions verified via `pip index versions` on 2026-06-02. All architectural decisions verified against SPIKE.md empirical measurements.

---

## Sources

### Primary (HIGH confidence)
- `SPIKE.md` (2026-06-01) — empirical measurements for all Phase 1 questions; authoritative on import paths, router API shape, LLM concurrency, D12 decision, SIGSTOP behavior, libnspr4 requirement
- `01-RESEARCH.md` (2026-06-01) — Phase 1 research with Pattern 1-7 verbatim code; Package Legitimacy Audit
- `04-fastapi-deploy.md` (2026-06-01) — lifespan skeleton, sqlite DDL + PRAGMA, structlog setup, health probes, Dockerfile
- `02-llm-curator.md` (2026-06-01) — LLMVerdict model, SYSTEM_PROMPT, FEW_SHOT_EXAMPLES, failure taxonomy (superseded on router API shape by SPIKE.md)
- `03-visit-extract.md` (2026-06-01) — DEFAULT_HEADERS, classify_response, extract_jsonld_product, concurrency pattern
- `01-google-stealth.md` (2026-06-01) — parser cascade selectors, _detect_block, build_serp_url
- PyPI `pip index versions` (verified 2026-06-02) — all package versions

### Secondary (MEDIUM confidence)
- `research/SUMMARY.md` (2026-06-01) — 13 locked deviations D1-D13; anti-patterns
- `REQUIREMENTS.md` (2026-06-01) — all 54 v1 requirement definitions
- `ROADMAP.md` Phase 2 detail — pre-drafted plan descriptions for 02-01, 02-02, 02-03

### Tertiary (informing architecture but not code-level)
- `01-03-SUMMARY.md` — per-host fixture classification and D11/D12 verdicts
- `01-02-PLAN.md` / `01-02-SUMMARY.md` — LLM router concurrency measurements (raw data)

---

## Metadata

**Confidence breakdown:**
- Integration patterns (lifespan, recycle loop, cache): HIGH — from 04-fastapi-deploy.md + SPIKE.md empirical verification
- LLM call shape and verdict model: HIGH — SPIKE.md §LLM + 02-llm-curator.md verbatim code
- Extractor cascade: HIGH — D12 locked by Phase 1 (9/10 jsonld-sufficient); Pattern 6 is verbatim from 01-03-PLAN.md
- Cloak import path + lifecycle: HIGH — Phase 1 empirically confirmed `launch_async`
- asgi-correlation-id 5.0.0 API: MEDIUM — version bumped; import path not re-verified post-bump

**Research date:** 2026-06-02
**Valid until:** 2026-07-02 (Cloak pin might shift if Google blocks; re-spike if block_detected_rate > 1%/day)

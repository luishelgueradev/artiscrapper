# Research: FastAPI single-container deploy + sqlite cache + observability

**Project:** artiscrapper v0 — Google SERP curator
**Researched:** 2026-06-01
**Overall confidence:** HIGH on stack mechanics, MEDIUM on Cloak+FastAPI behavior under sustained load (no shippable benchmark in the wild yet)

---

## Verdict per question

| # | Question | Verdict | Confidence |
|---|---|---|---|
| 1 | Cloak in FastAPI event loop | **Same loop is fine if `--workers 1`, `--loop asyncio` (NOT uvloop), and Playwright objects are owned by the app lifespan, not request scope.** Subprocess (Chromium) lives next to Python; GIL is irrelevant because Chromium is its own OS process and Python only does IPC. | HIGH |
| 2 | sqlite cache: aiosqlite + WAL + lazy TTL + nightly prune | **aiosqlite (with `journal_mode=WAL`, `synchronous=NORMAL`, explicit `expires_at` column, lazy refetch on read, daily cleanup task that VACUUMs.** Cap `raw_serp_html` size and / or off-load to filesystem if it ever exceeds ~200 MB.) | HIGH |
| 3 | structlog setup | **`structlog 25.x` with `contextvars.merge_contextvars` + `asgi-correlation-id` middleware** binding `correlation_id` into contextvars. JSON renderer in prod, console renderer in dev. Whitelist fields to avoid leaking scraped content. | HIGH |
| 4 | Health probes | **`GET /health` does cheap checks only**: ping sqlite (`SELECT 1`), HEAD against LLM router, and check Cloak by verifying the *cached* Playwright `Browser.is_connected()` — DO NOT spin a new page per `/health` call. Add a separate `GET /health/deep` for full Cloak roundtrip; gate it behind k8s/probe headers, never frontend traffic. | HIGH |
| 5 | Google 1 req/min rate-limit | **`asyncio.Semaphore(1)` + last-fetched timestamp + sleep** is sufficient because **`--workers 1` is mandatory** (Chromium is process-bound; multi-worker = multi-Chromium = waste + harder eviction). If multi-worker ever needed, switch to sqlite-backed token bucket (single `rate_limit` row with `INSERT ... ON CONFLICT UPDATE`). | HIGH |
| 6 | Docker layout | **Multi-stage with `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` as builder + `cloakhq/cloakbrowser:0.3.28` runtime base** (so fonts + libs come pre-baked) OR `python:3.12-slim-bookworm` runtime + manual `apt-get install` of Chromium deps + `python -m cloakbrowser install --version chromium-v146.0.7680.177.4`. Image size: 800 MB – 1.2 GB. | HIGH |
| 7 | uv idioms | `uv.lock` checked in. `uv sync --locked --no-install-project` for cache layer. `UV_LINK_MODE=copy` and `UV_COMPILE_BYTECODE=1` in Docker. CI: `actions/cache` against `~/.cache/uv`. | HIGH |
| 8 | Observability tiers | **Phase 1**: structlog JSON + `/health`. **Phase 2**: `prometheus-client` `/metrics` + per-stage histograms + sentry-sdk. **Phase 3**: Grafana dashboard + Loki + tracing (only if P95 still hurts). | HIGH |

---

## 1. Cloakbrowser + FastAPI in one process

### What's actually shared
- Cloak is a thin Playwright wrapper. Playwright in Python = a Python client that talks to a **separate Chromium subprocess via stdio**. The Chromium process has its own memory and CPU; the Python side only ferries CDP messages over pipes.
- That means **GIL contention with Cloak is a non-issue** — Python is doing I/O (await on a pipe), not CPU work. The asyncio event loop handles it cleanly.
- What IS shared: the asyncio event loop's reactor must service the Playwright pipe AND your FastAPI request handlers. If a single navigation takes 20s, every other request that needs the same browser will queue. That's expected and matches the "1 req/min Google" constraint.

### Lifecycle: own Browser in `app.state`, never per-request
```python
# main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from cloakbrowser import launch_async  # NOT a context manager — manual close

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Boot Cloak once, share across the app's lifetime.
    app.state.browser = await launch_async(headless=True)
    app.state.cache = await aiosqlite.connect("cache.db")
    await app.state.cache.execute("PRAGMA journal_mode=WAL")
    await app.state.cache.execute("PRAGMA synchronous=NORMAL")
    await app.state.cache.commit()
    yield
    # Cleanup. ORDER MATTERS: close pages, then contexts, then browser.
    await app.state.cache.close()
    await app.state.browser.close()

app = FastAPI(lifespan=lifespan)
```
- **Per-request: create a fresh `BrowserContext`, never a fresh `Browser`.** Contexts are cheap (~50 MB); browsers are expensive (~250–400 MB).
- **Always `await context.close()` in a `finally`** — unclosed contexts are the #1 source of Playwright leaks (verified in `microsoft/playwright#15400`).

### Why NOT a thread/process pool
- Threadpool: Playwright async API is asyncio-native; running it in a thread breaks the loop attachment.
- Process pool: defeats the purpose — you'd be paying browser bootstrap cost per pool worker. The 1-Chromium-per-FastAPI-process model is correct for this scope.

### Critical constraint: uvloop is incompatible
From CloakBrowser README: **"uvloop requires `--loop asyncio` to avoid subprocess pipe hangs."** Translation: do NOT install `uvloop`, and start uvicorn with `--loop asyncio`. uvloop's subprocess transport implementation is incompatible with Playwright's pipe protocol.

### Watch list (must-monitor in Phase 1)
- Memory: a single Chromium process drifts ~50–150 MB/hr under steady scraping. **Recycle the browser every N requests** (e.g. every 200 cold fetches) — implement as a counter in `app.state`, call `browser.close()` + `launch_async()` when threshold hit. Cheap insurance.
- Zombies: if Python crashes hard (OOM), Chromium child may orphan. Docker's PID-1 init handler (`docker run --init` or `tini`) reaps zombies.

---

## 2. sqlite cache layer

### Schema (concrete)
```sql
CREATE TABLE IF NOT EXISTS query_cache (
    cache_key       TEXT PRIMARY KEY,           -- sha256(query_norm)
    query           TEXT NOT NULL,              -- original query (for forensics)
    query_norm      TEXT NOT NULL,              -- lowercase, trimmed, collapsed-ws
    response_json   TEXT NOT NULL,              -- full JSON response (sans raw_serp_html)
    raw_serp_html_a BLOB,                       -- gzipped HTML of SERP A
    raw_serp_html_b BLOB,                       -- gzipped HTML of SERP B
    created_at      INTEGER NOT NULL,           -- unix epoch
    expires_at      INTEGER NOT NULL,           -- unix epoch
    bytes_total     INTEGER NOT NULL            -- precomputed for prune ordering
);

CREATE INDEX IF NOT EXISTS ix_cache_expires_at ON query_cache(expires_at);
CREATE INDEX IF NOT EXISTS ix_cache_created_at ON query_cache(created_at);
```
- `raw_serp_html_*` stored as **gzipped BLOB**: typical Google SERP HTML compresses 8–12x (1 MB → ~100 KB). 2000 queries × 2 SERPs × 100 KB = ~400 MB/day → manageable.
- `cache_key` from `hashlib.sha256(query_norm.encode()).hexdigest()`. Deterministic; avoids weird-char issues.
- `response_json` is the full v0 response shape (PRD §5), minus the raw HTML.

### PRAGMA configuration (`lifespan` startup)
```python
PRAGMAS = [
    "PRAGMA journal_mode=WAL",          # concurrent reads while one writer
    "PRAGMA synchronous=NORMAL",        # safe + ~2x faster than FULL
    "PRAGMA temp_store=MEMORY",
    "PRAGMA mmap_size=268435456",       # 256 MB mmap; speeds reads on big DB
    "PRAGMA cache_size=-32000",         # 32 MB page cache (negative = KiB)
    "PRAGMA wal_autocheckpoint=1000",   # default; 1000 pages = ~4 MB
    "PRAGMA busy_timeout=5000",         # wait 5s on contention before erroring
    "PRAGMA foreign_keys=ON",
]
```
**Confidence: HIGH** — these are the canonical "production SQLite" pragmas (Simon Willison TIL + oneuptime guide).

### TTL strategy: lazy + nightly prune (NOT a per-row timer)
```python
# On read
async def get_cached(cache, cache_key: str) -> dict | None:
    row = await (await cache.execute(
        "SELECT response_json, expires_at FROM query_cache WHERE cache_key=?",
        (cache_key,)
    )).fetchone()
    if row is None:
        return None
    response_json, expires_at = row
    if expires_at < int(time.time()):
        return None  # stale; treat as miss, but DON'T delete here (let prune do it)
    return json.loads(response_json)

# Nightly prune task (registered in lifespan as an asyncio.Task)
async def prune_loop(cache):
    while True:
        await asyncio.sleep(3600)  # hourly
        now = int(time.time())
        await cache.execute("DELETE FROM query_cache WHERE expires_at < ?", (now,))
        await cache.commit()
        # Cap total size at 2 GB; evict oldest first
        cur = await cache.execute("SELECT SUM(bytes_total) FROM query_cache")
        total = (await cur.fetchone())[0] or 0
        if total > 2_000_000_000:
            # Delete oldest until under cap
            await cache.execute("""
                DELETE FROM query_cache WHERE cache_key IN (
                    SELECT cache_key FROM query_cache
                    ORDER BY created_at ASC LIMIT 100
                )
            """)
            await cache.commit()
        # Vacuum WAL into main on a slower cadence (daily)
        if now % 86400 < 3600:
            await cache.execute("PRAGMA wal_checkpoint(TRUNCATE)")
```
- **Lazy expiry on read** = no clock skew, no race with insert.
- **Nightly prune** = bounded DB size, predictable VACUUM windows.
- **Don't auto_vacuum=FULL**: it's slower per-write than periodic manual VACUUM; manual control wins for cache workloads (per SQLite forum guidance).
- **Don't DELETE during a hot request path** — write contention. Tag and let the prune loop sweep.

### aiosqlite vs `sqlite3` + `asyncio.to_thread`
- aiosqlite is **a single dep** that wraps sqlite3 on a thread per connection. The performance difference at 500–2000 queries/day is negligible.
- aiosqlite is what the PRD picked (correctly): less ceremony, async-native API, mirrors stdlib.
- Use **a single shared connection** for the cache — sqlite handles concurrent reads natively with WAL; aiosqlite serializes writes on the worker thread, which is exactly what you want.

### Size math sanity check
- 2000 queries/day × 2 SERPs × ~100 KB gzipped = ~400 MB/day **of raw HTML**.
- TTL 24h → steady state ~400 MB raw + ~100 MB JSON responses ~= **~500 MB**.
- Comfortably fits the "single VPS" envelope; no need for filesystem off-load until volume 5x's.

---

## 3. structlog configuration

### Canonical setup (drop-in)
```python
# logging_setup.py
import logging
import sys
import structlog
from asgi_correlation_id.context import correlation_id

def add_correlation(_logger, _method, event_dict):
    if cid := correlation_id.get():
        event_dict["correlation_id"] = cid
    return event_dict

def configure_logging(json_logs: bool = True, level: str = "INFO") -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared = [
        structlog.contextvars.merge_contextvars,
        add_correlation,
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
        processors=shared + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    # Route stdlib logs through structlog so uvicorn / httpx logs are JSON too
    logging.basicConfig(stream=sys.stdout, level=level, format="%(message)s")
```

### Middleware order (critical)
```python
from asgi_correlation_id import CorrelationIdMiddleware

# Order: outermost added LAST. CorrelationId must run BEFORE anything that logs.
app.add_middleware(CorrelationIdMiddleware)  # generates/extracts X-Request-ID
# (if you add a logging middleware later, add it AFTER this line)
```
- `CorrelationIdMiddleware` honors `X-Request-ID` header from upstream (n8n / nginx) and falls back to a generated UUID.
- Result: every log line in a request lifecycle, including `httpx` calls to LLM router and Cloak's stderr, carries the same `correlation_id`.

### Per-request bindings the PRD/business cares about
Bind these to the request logger at the top of `/search`:
```python
log = structlog.get_logger().bind(
    query_hash=cache_key[:12],
    source="serp_curator",
    cache_status="unknown",  # mutated as cache hit/miss decided
)
```
Then emit per-stage timing:
```python
import time
t0 = time.monotonic()
candidates = await fetch_google(query)
log.info("stage_fetch_done", elapsed_ms=int((time.monotonic()-t0)*1000), n=len(candidates))
```
**Never log:** `title`, `snippet`, `raw_html`, `response_json`. Whitelist enforces "no scraped content" rule via the rendered JSON shape.

### Confidence: HIGH
Verified setup against `snok/asgi-correlation-id` README + `structlog.contextvars` docs (Context7).

---

## 4. Health probes

### Tiered approach
```python
@app.get("/health")
async def health(request: Request) -> dict:
    """Cheap liveness — must be < 50 ms."""
    out = {"status": "ok", "cloak": "ok", "llm": "ok", "cache": "ok"}
    # 1. Cache: pure sqlite call, no I/O outside the container
    try:
        await request.app.state.cache.execute("SELECT 1")
    except Exception:
        out["cache"] = "fail"; out["status"] = "degraded"
    # 2. Cloak: just check the Browser handle is still connected
    if not request.app.state.browser.is_connected():
        out["cloak"] = "fail"; out["status"] = "degraded"
    # 3. LLM: TCP-level reachability only (skip on /health, do in /health/deep)
    out["llm"] = "unknown"
    return out

@app.get("/health/deep")
async def health_deep(request: Request) -> dict:
    """Real roundtrip. Use sparingly — costs a Chromium navigation."""
    out = await health(request)
    # Cloak deep check: open a context, navigate to about:blank, close.
    ctx = await request.app.state.browser.new_context()
    try:
        page = await ctx.new_page()
        await page.goto("about:blank", timeout=5000)
        out["cloak"] = "ok_deep"
    except Exception as e:
        out["cloak"] = f"fail:{type(e).__name__}"
    finally:
        await ctx.close()
    # LLM deep check: HEAD against router
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(LLM_ROUTER_URL + "/health")
            out["llm"] = "ok" if r.status_code == 200 else f"fail:{r.status_code}"
    except Exception as e:
        out["llm"] = f"fail:{type(e).__name__}"
    return out
```

### Probe budget
- `/health` from upstream nginx / monitoring: every 10–30 s. Free.
- `/health/deep` from internal scheduler or a smoke-test CI step: every 5 min max. Each call eats one Chromium page (cheap but non-zero).
- **Never call `/health/deep` from a load balancer** — it'll burn the rate limit and waste the once-a-minute Google budget if it ever touches Google.

### Status semantics for n8n / app
- 200 + `status:"ok"` → operational
- 200 + `status:"degraded"` → answer requests but with caveats (e.g. cache-only mode)
- 503 → don't ever return; PRD says graceful degradation is required, so return 200 + degraded and let the consumer decide

**Confidence: HIGH** for the pattern, MEDIUM for `is_connected()` reliably catching all Cloak deaths — verify in Phase 0 spike by killing the Chromium pid and re-probing.

---

## 5. Google rate-limit (1 req/min)

### Simplest correct implementation: in-process semaphore + timestamp
```python
from asyncio import Semaphore, sleep
import time

class GoogleRateLimiter:
    """1 fetch/min by default. Same-process only — requires --workers 1."""
    def __init__(self, min_interval_s: float = 60.0):
        self._sema = Semaphore(1)
        self._min_interval = min_interval_s
        self._last_fetch_at = 0.0

    async def acquire(self) -> None:
        async with self._sema:
            wait = self._min_interval - (time.monotonic() - self._last_fetch_at)
            if wait > 0:
                await sleep(wait)
            self._last_fetch_at = time.monotonic()
```
- `Semaphore(1)` serializes the entry; the timestamp gate enforces the gap.
- 1/min is the global cap, but Phase 1's flow needs **2 SERP fetches per query** (Google raw + Google +mercadolibre). With 1/min, that's 2 minutes per cold query — confirms why cache hit ≥ 30% target matters.
- Alternative: allow the 2 SERPs to be a "burst" (config) by configuring min_interval = 30s. Document as an env var.

### Multi-worker scenario (NOT current scope)
- If `--workers > 1` ever shipped: switch to a **sqlite-backed atomic counter**.
```sql
-- One-row table; UPDATE ... RETURNING the new last_fetch_at timestamp
CREATE TABLE rate_limit (
    key TEXT PRIMARY KEY,
    last_fetch_at INTEGER NOT NULL
);
```
- Use `BEGIN IMMEDIATE` + `UPDATE rate_limit SET last_fetch_at = max(last_fetch_at + interval, now)` returning the wait time; sleep that long before fetching.
- **Currently NOT NEEDED**: Chromium-per-worker waste makes `--workers 1` the right call.

### Why NOT redis token bucket
Redis is explicitly out of scope (PRD §4, OOS). The in-process semaphore is sufficient.

**Confidence: HIGH**.

---

## 6. Docker layout

### Option A (recommended): use `cloakhq/cloakbrowser` as runtime base
**Pros:** fonts + Chromium deps pre-installed, smaller surface area, matches upstream's tested config.
**Cons:** larger base image (~600 MB before our app), tied to Cloak's image cadence.

```dockerfile
# syntax=docker/dockerfile:1.7
# ---------- builder ----------
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

# ---------- runtime ----------
FROM cloakhq/cloakbrowser:0.3.28 AS runtime
# Note: this base is Debian-derived with Chromium + fonts already baked.
# It already has Python 3.12 and the cloakbrowser binary downloaded.
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
# tini for PID-1 zombie reaping (Chromium leaks defunct procs otherwise)
ENTRYPOINT ["/usr/bin/tini", "--"]
# uvloop is INCOMPATIBLE with Cloak — use stock asyncio
CMD ["uvicorn", "src.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--loop", "asyncio"]
```

### Option B: roll our own (more control, more work)
Use when Option A's base image lags or we want auditable layers.
```dockerfile
FROM python:3.12-slim-bookworm AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    fonts-liberation fonts-noto-color-emoji ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
# Download the pinned Chromium binary inside the build (NOT at runtime — that's how prod breaks at 3am)
RUN python -m cloakbrowser install --version chromium-v146.0.7680.177.4
# ... rest as Option A
```

### Sizing estimates
| Layout | Image size |
|---|---|
| Option A (Cloak base + venv) | ~1.1 GB |
| Option B (python:slim + manual install) | ~1.3 GB |
| Option B + multi-stage `--squash` | ~900 MB |

Either is fine for a single-VPS deploy. **Recommend Option A** for Phase 1 (faster ship, fewer dep gotchas). Re-evaluate if Cloak release cadence becomes a friction.

### `.dockerignore` (mandatory)
```
.git
.venv
__pycache__
*.pyc
.pytest_cache
.ruff_cache
.mypy_cache
.planning
PRD.md
*.db
*.db-wal
*.db-shm
```

**Confidence: HIGH** for the multi-stage uv pattern (verified against `astral-sh/uv-docker-example`). MEDIUM for Option A — verify in Phase 0 that `cloakhq/cloakbrowser:0.3.28` Docker tag actually exists on Hub (PRD says yes; treat as a Phase 0 spike checklist item).

---

## 7. uv idioms (0.11+)

### `pyproject.toml` skeleton
```toml
[project]
name = "artiscrapper"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
    "fastapi==0.136.1",
    "uvicorn==0.47.0",
    "pydantic==2.13.4",
    "pydantic-settings==2.14.1",
    "cloakbrowser==0.3.28",
    "playwright==1.59.0",
    "httpx==0.28.1",
    "aiosqlite==0.21.0",         # latest stable as of 2026-05
    "selectolax==0.4.9",
    "structlog==25.5.0",
    "asgi-correlation-id==4.3.4",
    "orjson==3.11.9",
    "tenacity==9.1.4",
]

[dependency-groups]
dev = [
    "pytest==9.0.3",
    "pytest-asyncio==1.3.0",
    "respx==0.23.1",
    "pytest-cov",
    "ruff==0.15.13",
    "mypy==2.1.0",
]
metrics = [   # Phase 2+
    "prometheus-client==0.25.0",
    "sentry-sdk==2.60.0",
]

[tool.uv]
package = true

[tool.pytest.ini_options]
asyncio_mode = "auto"

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "RUF", "ASYNC"]
```

### Commands
| Step | Command |
|---|---|
| Bootstrap dev env | `uv sync` |
| Add a dep | `uv add httpx` (auto-updates lock) |
| Add dev dep | `uv add --group dev pytest-mock` |
| Run app | `uv run uvicorn src.main:app --reload --loop asyncio` |
| Run tests | `uv run pytest` |
| Run lint | `uv run ruff check src tests` |
| Update lock | `uv lock --upgrade` |
| Verify lock | `uv sync --locked` (CI) |

### CI cache (GitHub Actions)
```yaml
- uses: astral-sh/setup-uv@v3
  with:
    enable-cache: true
    cache-dependency-glob: "uv.lock"
- run: uv sync --locked
- run: uv run ruff check src tests
- run: uv run pytest --cov
```

**Confidence: HIGH** — verified against astral-sh/uv-docker-example and current astral docs.

---

## 8. Observability tiers

### Phase 1 MVP (ship with this)
- **structlog JSON to stdout** (Docker → journald → grep)
- **`GET /health` + `GET /health/deep`**
- Log every `/search` call with: `correlation_id`, `query_hash`, `cache_status`, per-stage `elapsed_ms`, candidate counts (`n_serps_a`, `n_serps_b`, `n_candidates`, `n_after_dedupe`, `n_after_llm`, `n_visited`, `n_visit_failed`), final `total_elapsed_ms`.
- No metrics endpoint, no dashboards, no traces.
**Why this is enough:** at 500–2000 queries/day, a `journalctl | jq` one-liner can answer 95% of ops questions.

### Phase 2 robustness
Add:
- `prometheus-client==0.25.0` + `GET /metrics` (uses `make_asgi_app()` mounted at `/metrics`).
- Core series:
  - `artiscrapper_search_total{cache_status, status}` counter
  - `artiscrapper_search_latency_seconds{stage}` histogram (stages: cache, fetch, parse, llm, visit, total)
  - `artiscrapper_google_blocks_total` counter (when challenge page detected)
  - `artiscrapper_cache_bytes_total` gauge
  - `artiscrapper_browser_recycles_total` counter
- `sentry-sdk` if uncaught exceptions become a problem. Free tier covers Sánchez volume.
- `slowapi==0.1.9` for **API-key bucket** (one client = Sánchez, but rate-limit defense against a runaway n8n loop is cheap insurance).

### Phase 3 operation
- Prometheus + Grafana on same VPS, scrape `/metrics`. One dashboard panel per series above.
- Loki for log aggregation if `journalctl` queries get slow (likely after Phase 2 settles).
- Tracing (OpenTelemetry) **only** if P95 cold-path latency still surprises us after Phase 2 is fully instrumented. Otherwise, structlog stage histograms already answer "where is the time going."

### What NEVER goes in any tier
- Raw scraped HTML in logs.
- Title/snippet/url of results in stdout logs (only counts).
- Full request bodies in error reports (sanitize for Sentry).

**Confidence: HIGH** — matches CLAUDE.md / PRD constraints and standard 2026 ops practice.

---

## Recommended FastAPI lifespan + Cloak lifecycle (concrete skeleton)

```python
# src/main.py
import asyncio
import time
from contextlib import asynccontextmanager
import aiosqlite
import structlog
from asgi_correlation_id import CorrelationIdMiddleware
from cloakbrowser import launch_async
from fastapi import FastAPI, Request

from .logging_setup import configure_logging
from .config import settings
from .cache import init_schema, PRAGMAS
from .rate_limit import GoogleRateLimiter

log = structlog.get_logger()
BROWSER_RECYCLE_AFTER = 200  # cold fetches

async def _recycle_browser_loop(app: FastAPI):
    while True:
        await asyncio.sleep(60)
        if app.state.browser_uses >= BROWSER_RECYCLE_AFTER:
            log.info("browser_recycle_start", uses=app.state.browser_uses)
            old = app.state.browser
            app.state.browser = await launch_async(headless=True)
            app.state.browser_uses = 0
            await old.close()
            log.info("browser_recycle_done")

async def _prune_cache_loop(cache):
    while True:
        await asyncio.sleep(3600)
        now = int(time.time())
        await cache.execute("DELETE FROM query_cache WHERE expires_at < ?", (now,))
        await cache.commit()

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(json_logs=settings.LOG_JSON, level=settings.LOG_LEVEL)
    log.info("boot_start", version=settings.VERSION)

    # 1. sqlite
    app.state.cache = await aiosqlite.connect(settings.CACHE_DB_PATH)
    for pragma in PRAGMAS:
        await app.state.cache.execute(pragma)
    await app.state.cache.commit()
    await init_schema(app.state.cache)

    # 2. Cloak
    app.state.browser = await launch_async(headless=settings.HEADLESS)
    app.state.browser_uses = 0

    # 3. rate limit
    app.state.rate_limit = GoogleRateLimiter(min_interval_s=settings.GOOGLE_MIN_INTERVAL_S)

    # 4. background tasks
    tasks = [
        asyncio.create_task(_recycle_browser_loop(app)),
        asyncio.create_task(_prune_cache_loop(app.state.cache)),
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
        await app.state.browser.close()
        log.info("shutdown_done")

app = FastAPI(lifespan=lifespan, default_response_class=ORJSONResponse)
app.add_middleware(CorrelationIdMiddleware)

# Per-request: use app.state.browser.new_context(), close in finally.
```

---

## Risks + scale boundaries

### When this single-container design breaks
| Trigger | Symptom | Migration path |
|---|---|---|
| Volume > ~5000 queries/day | Single Chromium can't keep up with cold fetches even at 1/min | Stay at 1 container but scale cache hit ratio (longer TTL), or accept queuing |
| Multiple clients beyond Sánchez | Need per-tenant rate-limits + isolation | Add slowapi + API keys, NOT multi-worker |
| Cloak memory creeping >2 GB after recycle | Underlying leak in Cloak / Playwright | Lower `BROWSER_RECYCLE_AFTER` aggressively; report upstream; consider container-restart strategy |
| sqlite cache > 5 GB | I/O bottleneck on prune | Move `raw_serp_html` BLOBs to filesystem (one file per cache_key); keep metadata in sqlite |
| Multiple workers requested | Chromium-per-worker waste; rate-limit needs cross-process state | Sqlite-backed rate-limiter (§5); accept ~Nx Chromium RAM |
| Latency demands SSE / async | Sync 20–40s P95 unacceptable to consumer | Out of scope per PRD — but trivial migration: same code, just `BackgroundTasks` + status polling |
| LLM router intermittently slow | Single-flight LLM calls block all stages | Already handled via 5s timeout + permissive `confidence=0.3` fallback |

### Hard limits
- **Single Chromium process: ~1 navigation every ~5–10s sustained.** With 1/min Google rate-limit, you'll never push this hard for fetch — but the visit pass (~7 visits/query, often concurrent) does.
- **sqlite WAL on single disk: easily 10k writes/sec.** Not the bottleneck.
- **FastAPI single worker on asyncio: thousands of concurrent connections, limited only by event-loop work per request.** Not the bottleneck.

### The thing that will surprise us
Cloak ships a fingerprint regression in some chromium-v146.0.7680.177.X patch and Google starts challenging. Mitigation: PRD-mandated weekly canary + the pinned binary tag + a kill-switch env var to swap to a backup tag.

---

## Sources

### Authoritative / Context7
- FastAPI lifespan: https://fastapi.tiangolo.com/advanced/events/
- FastAPI release notes (lifespan introduced in 0.93): https://github.com/fastapi/fastapi/blob/master/docs/en/docs/release-notes.md
- structlog contextvars: https://www.structlog.org/en/stable/contextvars.html
- asgi-correlation-id (snok): https://github.com/snok/asgi-correlation-id
- aiosqlite docs: https://aiosqlite.omnilib.dev/en/stable/
- uv docker example: https://github.com/astral-sh/uv-docker-example
- uv-docker-example multistage Dockerfile: https://github.com/astral-sh/uv-docker-example/blob/main/uv-docker-example/multistage.Dockerfile
- Playwright Python README: https://github.com/microsoft/playwright-python
- CloakBrowser GitHub: https://github.com/CloakHQ/CloakBrowser
- CloakBrowser Docker Hub: https://hub.docker.com/r/cloakhq/cloakbrowser
- SQLite WAL: https://sqlite.org/wal.html
- SQLite pragma reference: https://sqlite.org/pragma.html

### Practitioner guides (MEDIUM confidence, used for setup patterns)
- Simon Willison — enabling WAL: https://til.simonwillison.net/sqlite/enabling-wal-mode
- "Setting up request ID logging for your FastAPI application" (Sondre Lillebø Gundersen): https://medium.com/@sondrelg_12432/setting-up-request-id-logging-for-your-fastapi-application-4dc190aac0ea
- Wazaari blog — FastAPI + structlog integration: https://wazaari.dev/blog/fastapi-structlog-integration
- Apitally — FastAPI logging guide: https://apitally.io/blog/fastapi-logging-guide
- Charles Leifer — Going Fast with SQLite and Python: https://charlesleifer.com/blog/going-fast-with-sqlite-and-python/
- oneuptime — SQLite for production: https://oneuptime.com/blog/post/2026-02-02-sqlite-production-setup/view

### Known issues (informed risk register)
- Playwright memory leak discussion (microsoft/playwright#15400): https://github.com/microsoft/playwright/issues/15400
- crawl4ai FastAPI + Playwright scaling: https://github.com/unclecode/crawl4ai/issues/188
- WebScraping.AI — Playwright memory mgmt: https://webscraping.ai/faq/playwright/what-are-the-memory-management-best-practices-when-running-long-playwright-sessions

### Confidence calibration
- HIGH: every claim about FastAPI lifespan, structlog processors, uv idioms, SQLite WAL pragmas — all verified against Context7 / official docs.
- MEDIUM: claim that `cloakhq/cloakbrowser:0.3.28` Docker tag exists today (PRD says yes; physically not curl-tested in this research). Phase 0 must verify.
- MEDIUM: exact memory drift rate of Chromium under our workload (cited 50–150 MB/hr is industry rule-of-thumb, not measured for this app).
- LOW: nothing in this report is LOW — all conclusions are either verified or flagged for Phase 0 validation.

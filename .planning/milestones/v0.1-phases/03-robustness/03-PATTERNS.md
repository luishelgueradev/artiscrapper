# Phase 3: Robustness - Pattern Map

**Mapped:** 2026-06-03
**Files analyzed:** 16 (4 new + 7 modified + 5 test files/scaffolding)
**Analogs found:** 16 / 16 (every Phase 3 surface has a direct in-repo analog)

---

## File Classification

| New/Modified File | Status | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|--------|------|-----------|----------------|---------------|
| `src/artiscrapper/auth.py` | NEW | FastAPI dependency (auth) + slowapi key_func helper | request-response (header validation) | `src/artiscrapper/rate_limit.py` (in-process state singleton) + `src/artiscrapper/logging_setup.py:add_correlation_id` (header/contextvar reader) | role-match (no existing FastAPI Depends pattern; rate_limit.py is the closest singleton-in-app.state pattern) |
| `src/artiscrapper/challenge_backoff.py` | NEW | State store module (module-singleton + asyncio.Lock + sqlite UPSERT) | event-driven (block events) | `src/artiscrapper/llm.py:resolve_model` (lines 93-141) for `_RESOLVED_MODEL` + `_RESOLVE_LOCK` pattern; `src/artiscrapper/cache.py:set_cached` (lines 87-116) for `INSERT OR REPLACE` | exact |
| `src/artiscrapper/metrics.py` | EXTEND | Pure module (registry init + Counter/Histogram declarations) | transform (event → counter inc) | itself (Phase 2 inline dataclass) + `src/artiscrapper/llm.py` increment sites (lines 196, 214, 232, 234, 237, 240) | exact |
| `src/artiscrapper/logging_setup.py` | EXTEND | Lifespan-adjacent init (Sentry SDK init at module import) + structlog processor extension | event-driven (per-log scope.set_tag) | itself (Phase 2 `add_correlation_id` + `configure_logging`) | exact |
| `src/artiscrapper/main.py` | EXTEND | FastAPI app composition (mount /metrics, register exception handler, decorate /search, lifespan emits init log lines, /search calls check_gate before fetch_serp) | request-response + lifespan | itself (Phase 2 `lifespan` + `CorrelationIdMiddleware` add + `/search` 10-step pipeline) | exact |
| `src/artiscrapper/cache.py` | EXTEND | DDL extension (`challenge_state` table added to `_DDL`) | persistence | itself (Phase 2 `_DDL` + `init_schema`) | exact |
| `src/artiscrapper/config.py` | EXTEND | pydantic-settings BaseSettings (new env vars) | config | itself (Phase 2 `Settings` class) | exact |
| `src/artiscrapper/search.py` | UNCHANGED | (referenced — `_detect_block` consumer is in `browser.py:_detect_block` lines 42-62; ChallengeBackoff `record_block()` is called by `main.py` from the existing block-detection branch lines 334-348) | — | — | n/a |
| `tests/test_auth.py` | NEW | Unit test (FastAPI dependency) | request-response | `tests/test_health.py` (lines 47-63 TestClient fixture; lines 66-74 shape assertions) | exact |
| `tests/test_challenge_backoff.py` | NEW | Unit test (math + lock semantics) | event-driven | `tests/test_llm.py::test_d2_fallback_is_dropped` (invariant pin shape) + `tests/test_cache.py::test_schema` (sqlite assertions on `tmp_db` fixture) | exact |
| `tests/test_sentry_init.py` | NEW | Unit test (env-var gating + sentry.init kwargs) | event-driven | `tests/test_footguns.py::test_no_uvloop_installed` (subprocess-based env assertion shape) + `tests/test_llm.py::test_router_call_shape` (respx-style mock of external SDK) | role-match |
| `tests/integration/__init__.py` | NEW | scaffolding | — | `tests/__init__.py` does not exist (tests/ is a package via `pythonpath = ["."]` in pyproject); empty file is sufficient | scaffolding |
| `tests/integration/conftest.py` | NEW | pytest fixtures | scaffolding | `tests/conftest.py` (lines 14-45 `mock_app_state` + `tmp_db` patterns) | exact |
| `tests/integration/test_catalog_extraction.py` | NEW | Fixture-replay test (in-process extractor) | batch transform | `tests/test_parser.py::test_carousel_extracts_prices_from_fixtures` (lines 101-138 per-fixture pinned counts) | exact |
| `tests/integration/test_degraded_mode.py` | NEW | respx-mocked end-to-end test | event-driven | `tests/test_llm.py::test_router_timeout_returns_fallback` (lines 132-151 respx mock + fallback assertion) | exact |
| `tests/integration/test_challenge_backoff.py` | NEW | sqlite + respx integration test | event-driven | `tests/test_cache.py::test_lazy_ttl` (lines 85-109 tmp_db + time-based assertion shape) | exact |
| `tests/integration/test_metrics_endpoint.py` | NEW | HTTP smoke test (TestClient → /metrics → grep) | request-response | `tests/test_health.py::test_health_shape` (lines 66-74 TestClient + body assertion) | exact |
| `tests/test_footguns.py` | EXTEND | Invariant pin (Sentry no-uvloop, /metrics no-auth grep) | static check | itself (Phase 2 `test_no_uvloop_installed`, `test_no_persistent_context_in_codebase`) | exact |
| `tests/fixtures/serp/sorry.html` | NEW | Static HTML fixture | scaffolding | Phase 1 captured none — minimal stand-in per D-20 | n/a |
| `pyproject.toml` | EXTEND | Dependency manifest + pytest markers | config | itself (Phase 2 deps + `[tool.pytest.ini_options]`) | exact |

---

## Pattern Assignments

### `src/artiscrapper/challenge_backoff.py` (NEW — module-singleton state machine, event-driven)

**Primary analog:** `src/artiscrapper/llm.py` — `_RESOLVED_MODEL` + `_RESOLVE_LOCK` + double-checked-lock pattern.
**Secondary analog:** `src/artiscrapper/cache.py` — `INSERT OR REPLACE` single-row upsert.

**Module-level state + asyncio.Lock pattern** — copy verbatim shape from `src/artiscrapper/llm.py:93-117`:

```python
# Process-lifetime cache for the resolved model alias. Populated on first
# resolve_model() call; survives until process exit. See LLM_USE_RECOMMENDATIONS.
_RESOLVED_MODEL: str | None = None
_RESOLVE_LOCK = asyncio.Lock()


async def resolve_model(
    client: httpx.AsyncClient,
    router_url: str,
    bearer_token: str,
) -> str:
    """
    Resolve the canonical model alias for chat+json_strict via the router's
    /v1/models recommendations map. Cached for the process lifetime. Falls back
    to settings.LLM_MODEL on any failure (404, timeout, missing key, etc.).
    """
    global _RESOLVED_MODEL
    if _RESOLVED_MODEL is not None:
        return _RESOLVED_MODEL
    if not settings.LLM_USE_RECOMMENDATIONS:
        _RESOLVED_MODEL = settings.LLM_MODEL
        return _RESOLVED_MODEL
    async with _RESOLVE_LOCK:
        if _RESOLVED_MODEL is not None:
            return _RESOLVED_MODEL
```

**Apply to challenge_backoff.py:** Replace `_RESOLVED_MODEL` with `_STATE: _State | None`, `_RESOLVE_LOCK` with `_LOCK = asyncio.Lock()`. Use the double-checked-lock idiom (check outside → acquire → re-check inside) for `_load()`. State mutations (`record_block`, `record_success`) acquire `_LOCK` before persisting.

**sqlite UPSERT pattern** — copy verbatim shape from `src/artiscrapper/cache.py:106-116`:

```python
    await cache.execute(
        """
        INSERT OR REPLACE INTO query_cache
            (cache_key, query, query_norm, response_json,
             raw_serp_html_a, raw_serp_html_b,
             created_at, expires_at, bytes_total)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (cache_key, query, query_norm, resp_json, blob_a, blob_b, now, now + ttl_s, bytes_total),
    )
    await cache.commit()
```

**Apply to challenge_backoff.py:** Use the same `INSERT OR REPLACE ... VALUES (?, ?, ?, ?, ?)` parameterized-placeholder shape against the new `challenge_state` table. Hard-code `id=1` (single-row pattern). Always `await cache.commit()` immediately after the execute (no fire-and-forget — backoff persistence is on the request critical path).

**Constants & math (D-06, D-07):** Hard-coded module-level (ROADMAP-locked, do NOT thread through settings — D-06 says so):

```python
_BACKOFF_CAP_S = 3600  # 1 hour — D-06
_BASE_S = 60           # D-06
_RESET_AFTER_S = 3600  # D-07
```

**Backoff curve formula (D-06 ROADMAP-locked):** `wait_s = min(_BASE_S * (2 ** (retry_count - 1)), _BACKOFF_CAP_S)` — retry_count starts at 1 after first block, so first wait = 60s, second = 120s, …, capped at 3600s.

---

### `src/artiscrapper/cache.py` (EXTEND — append `challenge_state` DDL)

**Analog:** itself (lines 29-50).

**Existing DDL block** to extend:

```python
_DDL = """
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
"""


async def init_schema(cache: aiosqlite.Connection) -> None:
    """Create the query_cache table and indexes if they don't exist."""
    await cache.executescript(_DDL)
    await cache.commit()
```

**Append to `_DDL` (D-08 single-row table with CHECK constraint):**

```sql
CREATE TABLE IF NOT EXISTS challenge_state (
    id              INTEGER PRIMARY KEY CHECK (id = 1),   -- enforce single row
    last_block_at   INTEGER,                              -- unix epoch of most recent block
    retry_count     INTEGER NOT NULL DEFAULT 0,           -- consecutive blocks since last reset
    next_allowed_at INTEGER NOT NULL DEFAULT 0,           -- unix epoch — gate for next Google fetch
    updated_at      INTEGER NOT NULL                       -- forensics
);

INSERT OR IGNORE INTO challenge_state (id, last_block_at, retry_count, next_allowed_at, updated_at)
    VALUES (1, NULL, 0, 0, strftime('%s', 'now'));
```

**`init_schema` body:** No change — `executescript` already handles multi-statement DDL. The new CREATE TABLE + INSERT OR IGNORE are idempotent.

---

### `src/artiscrapper/metrics.py` (EXTEND — bridge dataclass to prometheus_client)

**Analog:** itself (current 27 lines).

**Existing surface** to preserve (D-11 requires bridge, NOT replacement):

```python
@dataclass
class Metrics:
    llm_fallback_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    visit_failed_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    browser_recycles_total: int = 0
    block_detected_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))


metrics = Metrics()  # process-singleton (safe with --workers 1)
```

**Current call sites that increment the dataclass** (these must keep working — bridge dual-writes to prometheus):
- `src/artiscrapper/llm.py:196` `metrics.llm_fallback_total["timeout"] += 1`
- `src/artiscrapper/llm.py:214` `metrics.llm_fallback_total["overload"] += 1`
- `src/artiscrapper/llm.py:232` `metrics.llm_fallback_total[f"cold_load_{code}"] += 1`
- `src/artiscrapper/llm.py:234` `metrics.llm_fallback_total[f"http_{code}"] += 1`
- `src/artiscrapper/llm.py:237` `metrics.llm_fallback_total["malformed"] += 1`
- `src/artiscrapper/llm.py:240` `metrics.llm_fallback_total["conn_error"] += 1`
- `src/artiscrapper/main.py:338` `metrics.block_detected_total[block_reason] += 1`

**Bridge wrapper pattern (per RESEARCH §A3):**

```python
def inc_llm_fallback(reason: str) -> None:
    metrics.llm_fallback_total[reason] += 1               # legacy dataclass — preserved
    llm_fallback_counter.labels(reason=reason).inc()      # prometheus

def inc_block_detected(reason: str) -> None:
    metrics.block_detected_total[reason] += 1
    block_detected_counter.labels(reason=reason).inc()
```

**Refactor all 7 call sites above** to use the wrapper instead of direct `+=`. The dataclass still increments for backwards-compat (existing tests in `test_llm.py` may rely on it implicitly via `metrics` import).

**Counter declarations (canonical names already locked in D-11):**

```python
from prometheus_client import Counter, Histogram, REGISTRY, GC_COLLECTOR, PLATFORM_COLLECTOR, PROCESS_COLLECTOR

# Disable default Python-VM collectors so /metrics shows only artiscrapper_*
for coll in (GC_COLLECTOR, PLATFORM_COLLECTOR, PROCESS_COLLECTOR):
    try:
        REGISTRY.unregister(coll)
    except KeyError:
        pass  # already unregistered (test re-import)

llm_fallback_counter = Counter(
    "artiscrapper_llm_fallback_total",
    "LLM curator fallback verdicts emitted, by reason",
    ["reason"],
)
visit_failed_counter = Counter(
    "artiscrapper_visit_failed_total",
    "Visit-pass failures, by host",
    ["host"],
)
block_detected_counter = Counter(
    "artiscrapper_block_detected_total",
    "Google block-detection events, by marker reason",
    ["reason"],
)
```

**Histogram declarations (D-12 — three hot paths):**

```python
SEARCH_BUCKETS = (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 40.0, 60.0, float("inf"))
LLM_BUCKETS    = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, float("inf"))
VISIT_BUCKETS  = (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, float("inf"))

search_elapsed = Histogram("artiscrapper_search_elapsed_seconds", "End-to-end /search wall-clock", buckets=SEARCH_BUCKETS)
llm_elapsed = Histogram("artiscrapper_llm_elapsed_seconds", "LLM curator batch latency", buckets=LLM_BUCKETS)
visit_elapsed = Histogram("artiscrapper_visit_elapsed_seconds", "Visit pass latency per stage", ["stage"], buckets=VISIT_BUCKETS)
```

**Pre-seed label values (RESEARCH §A6 — avoid gappy metrics):** Touch every known `reason` at module load with `.labels(reason=r)` (no `.inc()`).

---

### `src/artiscrapper/logging_setup.py` (EXTEND — Sentry init at module import + tag injection in processor)

**Analog:** itself (current 83 lines).

**Existing processor to extend** (lines 16-35):

```python
def add_correlation_id(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Inject correlation_id from asgi-correlation-id contextvars."""
    # asgi-correlation-id 5.x: check changelog for exact import path.
    # Try 5.x path first, fall back to 4.x path.
    try:
        from asgi_correlation_id import correlation_id  # 5.0 likely path

        if cid := correlation_id.get():
            event_dict["correlation_id"] = cid
    except (ImportError, AttributeError):
        try:
            from asgi_correlation_id.context import correlation_id  # 4.x fallback

            if cid := correlation_id.get():
                event_dict["correlation_id"] = cid
        except (ImportError, AttributeError):
            pass
    return event_dict
```

**Extension (D-16):** After the `if cid := ...` block, add a try/except that calls `sentry_sdk.get_current_scope().set_tag("correlation_id", cid)`. The set_tag is a no-op when DSN is empty (sentry_sdk.init was skipped), so it's safe to always invoke. Wrap in `try/except Exception: pass` to never let observability code break a request.

**Sentry init at module import time (RESEARCH §B2 + D-14, D-17):**

```python
import sentry_sdk
from .config import settings

def _init_sentry() -> None:
    """D-14: only init if SENTRY_DSN is set and non-empty."""
    dsn = settings.SENTRY_DSN
    if not dsn:
        return  # off in dev/test — D-14
    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=0.1,        # D-15: 10% of transactions
        profiles_sample_rate=0.0,      # D-15: profiling off
        send_default_pii=False,        # OBS-05 alignment — never leak scraped content
        # FastAPI integration auto-detected from package presence (sentry-sdk 2.x)
    )

_init_sentry()  # runs at module import — captures boot errors after Settings() loads
```

**Place at the very bottom of the module** (after `log_candidate_safe`), so `from .logging_setup import configure_logging` in main.py transitively triggers init before lifespan.

---

### `src/artiscrapper/config.py` (EXTEND — new env vars)

**Analog:** itself (current Settings class lines 10-37).

**Existing pattern** to copy:

```python
class Settings(BaseSettings):
    VERSION: str = "0.1.0"
    CACHE_DB_PATH: str = "/app/cache.db"
    HEADLESS: bool = True
    GOOGLE_MIN_INTERVAL_S: int = 60
    BROWSER_RECYCLE_AFTER: int = 200
    LLM_ROUTER_URL: str = "http://127.0.0.1:3210"
    LLM_ROUTER_BEARER_TOKEN: (
        str  # no default — pydantic raises ValidationError at startup if absent
    )
    # …
    LLM_CONCURRENCY: int = 4
    LOG_JSON: bool = True
    LOG_LEVEL: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}
```

**Add these fields (Phase 3):**

```python
    # ── Phase 3 — Robustness ──
    # D-01: comma-separated API keys; empty string means "no auth configured" (boot logs warn).
    API_KEYS: str = ""
    # D-02: per-key quotas; whichever fires first wins.
    API_RATE_PER_MINUTE: int = 60
    API_RATE_PER_DAY: int = 10000
    # D-14: empty → Sentry disabled (no init). Set in production deploy compose only.
    SENTRY_DSN: str = ""
```

**Do NOT add `CHALLENGE_BACKOFF_*` settings** — D-06 says these constants are ROADMAP-locked and hardcoded in `challenge_backoff.py` (see Pitfall 6 in RESEARCH: settings/contract/route shadowing risk).

---

### `src/artiscrapper/auth.py` (NEW — FastAPI dependency + slowapi key_func)

**Primary analog:** `src/artiscrapper/rate_limit.py` (process-singleton class with internal state).
**Secondary analog:** `src/artiscrapper/logging_setup.py:add_correlation_id` (header / contextvar reader pattern).

**Module-level cached parsing pattern** — mirror `src/artiscrapper/rate_limit.py:20-30` (compute config once at construction, never per-request):

```python
class GoogleRateLimiter:
    def __init__(self, min_interval_s: float = 60.0) -> None:
        self._sem = asyncio.Semaphore(1)
        self._last_fetch: float = 0.0
        self._min_interval = min_interval_s
```

**Apply to auth.py:**

```python
from fastapi import HTTPException, Request, status
from .config import settings

def _parse_api_keys() -> set[str]:
    """D-01: parse comma-separated API_KEYS env var; rotation requires container restart."""
    raw = settings.API_KEYS or ""
    return {k.strip() for k in raw.split(",") if k.strip()}

API_KEYS = _parse_api_keys()  # module-load cache; D-01 says restart for rotation


def verify_api_key(request: Request) -> str:
    """
    FastAPI dependency that enforces X-API-Key auth.
    D-03: 401 Unauthorized for missing/unknown key (NOT 403).
    Returns the api_key (so it could be logged as the consumer identity — but DO NOT log the value).
    """
    key = request.headers.get("X-API-Key")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    if key not in API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return key


def get_api_key(request: Request) -> str:
    """
    slowapi key_func — buckets rate-limit counters per consumer.
    MUST NOT raise (RESEARCH §C1 / Pitfall 3): slowapi treats exceptions as 500.
    Auth is enforced by verify_api_key() dependency (separate concern).
    """
    return request.headers.get("X-API-Key", "anonymous")
```

**OBS-05 alignment:** never log the api-key value in any structlog event. The `logging_setup.SAFE_CANDIDATE_FIELDS` allow-list (lines 65-67 of logging_setup.py) does NOT include any auth field — keep it that way.

---

### `src/artiscrapper/main.py` (EXTEND — lifespan + middleware + /search route + /metrics mount)

**Analog:** itself.

**Existing lifespan structure** (lines 132-169) to extend:

```python
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
```

**Phase 3 lifespan additions (after step 1 cache init, before step 2 browser, per RESEARCH §integration_points):**

```python
    # 1b. Phase 3: emit init log lines so D-19 empirical retest works
    #    (feedback_empirical_retest_after_default_changes — Phase 2 lesson)
    api_keys = _parse_api_keys()  # imported from .auth
    log.info(
        "api_keys_loaded",
        count=len(api_keys),
        rate_per_min=settings.API_RATE_PER_MINUTE,
        rate_per_day=settings.API_RATE_PER_DAY,
    )
    log.info(
        "sentry_init_skipped" if not settings.SENTRY_DSN else "sentry_init_done",
        traces_sample_rate=0.1 if settings.SENTRY_DSN else None,
    )
    log.info(
        "challenge_backoff_init",
        base_s=challenge_backoff._BASE_S,
        cap_s=challenge_backoff._BACKOFF_CAP_S,
        reset_after_s=challenge_backoff._RESET_AFTER_S,
    )
```

**Existing FastAPI app construction** (lines 176-183) to extend:

```python
app = FastAPI(
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
    title="artiscrapper",
    version=settings.VERSION,
)
# CorrelationIdMiddleware must be outermost (added last = executed first in request chain)
app.add_middleware(CorrelationIdMiddleware)
```

**Phase 3 additions (after app construction, BEFORE the `app.add_middleware(CorrelationIdMiddleware)` line per RESEARCH §C5):**

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from prometheus_client import make_asgi_app
from .auth import verify_api_key, get_api_key

limiter = Limiter(key_func=get_api_key, headers_enabled=True)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# /metrics mounted as ASGI sub-app — bypasses ALL middleware (no auth, no rate-limit per D-10)
app.mount("/metrics", make_asgi_app())

# CorrelationIdMiddleware OUTERMOST — must run before slowapi so 429s carry X-Request-ID
app.add_middleware(CorrelationIdMiddleware)  # existing — DO NOT duplicate
```

**Existing /search route decorator** (line 265):

```python
@app.post("/search", response_model=SearchResponse)
async def search(request: Request, body: SearchRequest) -> SearchResponse:
```

**Phase 3 decorator stack (per RESEARCH §C2 + C3 + D-02 + D-03):**

```python
@app.post("/search", response_model=SearchResponse)
@limiter.limit("60/minute")            # D-02
@limiter.limit("10000/day")            # D-02
async def search(
    request: Request,
    body: SearchRequest,
    _api_key: str = Depends(verify_api_key),  # D-03: 401 if missing/unknown
) -> SearchResponse:
```

**Note:** `request: Request` MUST stay first positional arg (slowapi requirement).

**ChallengeBackoff gate (D-09 — call BEFORE Google fetch, in step [2] of pipeline):** Inject between the existing cache-hit return (line 287-299) and the Google fetch (line 303 onwards):

```python
    # ── [1.5] Challenge backoff gate (D-09) ──
    from .challenge_backoff import check_gate, record_block, record_success
    allowed, retry_after = await check_gate(request.app.state.cache)
    if not allowed:
        log.warning("challenge_backoff_active", retry_after=retry_after)
        elapsed_ms = int((time.time() - t_start) * 1000)
        from fastapi import Response
        return Response(
            status_code=503,
            content=SearchResponse(
                query=body.query,
                results=[],
                metadata=Metadata(
                    elapsed_ms=elapsed_ms,
                    cache_hit=False,
                    block_detected=True,
                ),
            ).model_dump_json(),
            media_type="application/json",
            headers={"Retry-After": str(retry_after)},
        )
```

**Record block/success after fetch (extends existing block-detection branch at lines 334-348):** In the block-detected branch, call `await record_block(request.app.state.cache)` before the return; on the success path (after `[3] detect_block` passes), call `await record_success(request.app.state.cache)` (D-07 reset trigger).

**Histogram bracketing (D-12 — use context-manager form, NEVER decorator on async def per RESEARCH §A5 / Pitfall 1):**

```python
async def search(...):
    with search_elapsed.time():
        # entire 10-step pipeline body here
        ...
```

For `curate_candidates` (in llm.py line 276) and `visit_candidates` (in visit.py): same `with hist.time():` wrap inside the async function.

---

### `tests/test_auth.py` (NEW — verify_api_key dependency, D-01 + D-03)

**Analog:** `tests/test_health.py` lines 23-63 (TestClient setup with env-var override + monkeypatched browser).

**Test client fixture pattern to copy verbatim:**

```python
# Set required env vars before importing app.
# CACHE_DB_PATH must point to a writable location so lifespan aiosqlite.connect works.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ.setdefault("LLM_ROUTER_BEARER_TOKEN", "test-token-health")
os.environ["CACHE_DB_PATH"] = _tmp_db.name

from fastapi.testclient import TestClient  # noqa: E402
from src.artiscrapper.main import app  # noqa: E402


@pytest.fixture
def test_client(monkeypatch):
    """TestClient with lifespan running but cloakbrowser launch_async mocked out."""
    mock_browser = _make_mock_browser()

    async def _fake_launch_async(**kwargs):
        return mock_browser

    monkeypatch.setattr("src.artiscrapper.main.launch_async", _fake_launch_async)

    with TestClient(app) as client:
        app.state.browser = mock_browser
        yield client
```

**Apply to test_auth.py:** Also set `os.environ["API_KEYS"] = "test-key-1,test-key-2"` at module top (before `from src.artiscrapper.main import app`), then test:
- Missing X-API-Key → 401 (D-03)
- Wrong X-API-Key → 401 (D-03)
- Valid X-API-Key → 200 (or whatever /search returns with mocked browser)
- Multiple keys parsed correctly (D-01)

**Assertion shape from `tests/test_health.py:66-74`:**

```python
def test_health_shape(test_client):
    resp = test_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("status", "cloak", "llm", "cache"):
        assert key in body, f"Missing key: {key}"
```

**Apply to test_auth.py:**

```python
def test_missing_key_returns_401(test_client):
    resp = test_client.post("/search", json={"query": "filtro aceite"})
    assert resp.status_code == 401, f"expected 401, got {resp.status_code}"
    assert "WWW-Authenticate" in resp.headers
    assert resp.headers["WWW-Authenticate"] == "ApiKey"
```

---

### `tests/test_challenge_backoff.py` (NEW — math + lock semantics, D-06 + D-07)

**Primary analog:** `tests/test_cache.py::test_lazy_ttl` (lines 85-109) — tmp_db fixture + time-based assertion shape.
**Secondary analog:** `tests/test_llm.py::test_d2_fallback_is_dropped` — invariant pin (assert a constant + assert behavior consequence).

**tmp_db fixture (already in conftest.py lines 32-45) — reuse directly:**

```python
@pytest.fixture
async def tmp_db(tmp_path):
    """Temporary aiosqlite database with WAL PRAGMAS and schema initialized."""
    db_path = str(tmp_path / "cache.db")
    db = await aiosqlite.connect(db_path)
    for pragma in PRAGMAS:
        await db.execute(pragma)
    await db.commit()
    await init_schema(db)
    yield db
    await db.close()
```

**Apply to test_challenge_backoff.py:** Use `tmp_db` directly. After `init_schema`, the `challenge_state` table exists and the seed row is inserted (via the `INSERT OR IGNORE` in the extended `_DDL`).

**Time-based assertion shape from `tests/test_cache.py:85-109`:**

```python
async def test_lazy_ttl(tmp_db):
    """CACHE-04: get_cached returns None for expired row (lazy TTL — never DELETE in hot path)."""
    query = "termostato corsa"
    key = make_cache_key(query)
    norm = normalize_query(query)
    response = {"results": [{"url": "https://example.com"}], "metadata": {}}

    # Insert with 1 second TTL
    await set_cached(tmp_db, key, query, norm, response, "<html/>", "<html/>", ttl_s=1)

    # Verify it's accessible immediately
    cached = await get_cached(tmp_db, key)
    assert cached is not None, "Freshly inserted entry should be accessible"

    # Wait for TTL to expire
    await asyncio.sleep(2)

    # Now it should return None (lazy TTL)
    expired = await get_cached(tmp_db, key)
    assert expired is None, "Expired entry should return None (lazy TTL)"
```

**Apply to test_challenge_backoff.py:**

```python
async def test_exponential_curve(tmp_db):
    """D-06: backoff curve min(60 * 2^(retries-1), 3600)."""
    from src.artiscrapper.challenge_backoff import check_gate, record_block, _STATE
    # First block: 60s wait
    await record_block(tmp_db)
    allowed, retry_after = await check_gate(tmp_db)
    assert not allowed
    assert 58 <= retry_after <= 61, f"first block wait should be ~60s, got {retry_after}"
    # Second block: 120s wait
    await record_block(tmp_db)
    allowed, retry_after = await check_gate(tmp_db)
    assert 118 <= retry_after <= 121
    # … escalation continues to 240s, 480s, … capped at 3600s
```

**Module-state reset between tests:** Add a fixture that resets `challenge_backoff._STATE = None` before each test (mirrors how Phase 2 doesn't share module-singleton state across tests).

---

### `tests/test_sentry_init.py` (NEW — env-var gating, D-14 + D-15 + D-16)

**Analog:** `tests/test_footguns.py::test_no_uvloop_installed` (subprocess shape for env-level assertions) + `tests/test_llm.py::test_router_call_shape` (respx-style mock for SDK behavior).

**Subprocess-based env assertion pattern from `tests/test_footguns.py:13-19`:**

```python
def test_no_uvloop_installed():
    """D6: uvloop must not be importable in the runtime environment."""
    result = subprocess.run(
        [sys.executable, "-c", "import uvloop"],
        capture_output=True,
    )
    assert result.returncode != 0, "uvloop is installed — D6 foot-gun!"
```

**Apply to test_sentry_init.py for D-14 (off when DSN empty):**

```python
def test_no_init_when_dsn_empty(monkeypatch):
    """D-14: sentry_sdk.init must not be called when SENTRY_DSN is unset/empty."""
    monkeypatch.setenv("SENTRY_DSN", "")
    # Re-import to trigger _init_sentry()
    import importlib
    from src.artiscrapper import logging_setup
    importlib.reload(logging_setup)
    # Sentry client should not be configured
    import sentry_sdk
    client = sentry_sdk.get_client()
    assert not client.is_active(), "Sentry should be off when DSN is empty"
```

**Mock-the-SDK shape for D-15 (sample rates):** Use `unittest.mock.patch` on `sentry_sdk.init` to capture the kwargs:

```python
def test_sample_rates(monkeypatch):
    """D-15: traces_sample_rate=0.1, profiles_sample_rate=0.0, send_default_pii=False."""
    monkeypatch.setenv("SENTRY_DSN", "https://fake@sentry.io/123")
    with patch("sentry_sdk.init") as mock_init:
        import importlib
        from src.artiscrapper import logging_setup
        importlib.reload(logging_setup)
        mock_init.assert_called_once()
        kwargs = mock_init.call_args.kwargs
        assert kwargs["traces_sample_rate"] == 0.1
        assert kwargs["profiles_sample_rate"] == 0.0
        assert kwargs["send_default_pii"] is False
```

---

### `tests/integration/test_catalog_extraction.py` (NEW — D12 ≥85% extraction, ROADMAP-6)

**Analog:** `tests/test_parser.py::test_carousel_extracts_prices_from_fixtures` (lines 101-138 — per-fixture pinned counts, NOT `len > 0`).

**Reference: D-18 says fixture-driven tests must check specific data, not structural shape.** The per-fixture pinning pattern from Phase 2 commit `160c133`:

```python
def test_carousel_extracts_prices_from_fixtures():
    """
    SEARCH-04 regression guard — the carousel extractor was originally a stub that
    required <a href> inside the card (Google uses JS click handlers, so it never
    matched). All 20+ carousel items per fixture were silently dropped, and the
    price selectors (.price/.precio) didn't match Google's obfuscated classes either.

    After the regex-first refactor, every fixture with a Google Shopping carousel
    should yield at least 8 carousel candidates with prices, and the per-fixture
    'with-price' count should be substantially above the pre-fix baseline.
    """
    expectations = {
        # name → (min_carousel_items, min_with_price)
        "01-pelota_playera_quico.html": (15, 18),
        "02-filtro_aceite_ford_focus.html": (25, 25),
        "03-amortiguador_trasero_peugeot_208.html": (8, 12),
        # …
    }
    for name, (min_carousel, min_with_price) in expectations.items():
        html = (FIXTURES_DIR / name).read_text(encoding="utf-8", errors="replace")
        cands = parse_serp(html)
        carousel_count = sum(1 for c in cands if "carousel" in c.get("flags", []))
        with_price = sum(1 for c in cands if c.get("price_in_card"))
        assert carousel_count >= min_carousel, (
            f"{name}: carousel candidates regressed: got {carousel_count}, "
            f"expected ≥{min_carousel}. Likely Google rotated the Ez5pwe selector."
        )
        assert with_price >= min_with_price, (
            f"{name}: candidates-with-price regressed: got {with_price}, "
            f"expected ≥{min_with_price}. Check _extract_commercial_signals regex."
        )
```

**Apply to test_catalog_extraction.py (per RESEARCH §F3, in-process extract_product):**

```python
import pathlib
import pytest
from src.artiscrapper.visit import extract_product

CATALOG_DIR = pathlib.Path(__file__).parent.parent / "fixtures" / "catalog"


@pytest.mark.integration
def test_catalog_price_extraction_rate_above_85_percent():
    """
    D12 production validation: ≥85% of Phase 1 catalog fixtures yield a price
    via extract_product() (in-process, no HTTP).
    SPIKE.md §Visit empirically measured 9/10 jsonld-sufficient — this test pins
    that bar in production.
    """
    fixture_files = []
    for host_dir in CATALOG_DIR.iterdir():
        if not host_dir.is_dir():
            continue
        fixture_files.extend(host_dir.glob("*.html"))

    assert len(fixture_files) >= 10, (
        f"Expected ≥10 catalog fixtures (Phase 1 spike captured 10); "
        f"found {len(fixture_files)}"
    )

    with_price = 0
    details = []
    for fpath in fixture_files:
        html = fpath.read_text(encoding="utf-8", errors="replace")
        extracted = extract_product(html)
        has_price = bool(extracted and extracted.get("price"))
        details.append((fpath.name, has_price, extracted.get("price") if extracted else None))
        if has_price:
            with_price += 1

    rate = with_price / len(fixture_files)
    assert rate >= 0.85, (
        f"Catalog price extraction regressed to {rate:.0%} (got {with_price}/{len(fixture_files)}). "
        f"D12 acceptance is ≥85%. Details: {details}"
    )
```

**Note:** The fixture directory layout from `tests/fixtures/catalog/` (verified: 10 host subdirs each containing one `product-XX.html`).

---

### `tests/integration/test_degraded_mode.py` (NEW — LLM-down survives, ROADMAP-5)

**Analog:** `tests/test_llm.py::test_router_timeout_returns_fallback` (lines 132-151) — respx mock + fallback assertion shape.

**Existing respx pattern to copy:**

```python
async def test_router_timeout_returns_fallback():
    """LLM-04: 5s timeout → fallback verdict with reason='llm_fail:timeout'."""
    with respx.mock:
        respx.post("http://127.0.0.1:3210/v1/chat/completions").mock(
            side_effect=httpx.TimeoutException("timeout")
        )
        sem = asyncio.Semaphore(4)
        async with httpx.AsyncClient(http2=True) as client:
            verdict = await classify_candidate(
                client,
                {"url": "https://tienda.com/prod", "title": "Filtro", "snippet": "En stock"},
                sem,
                "http://127.0.0.1:3210",
                "test-token",
            )
        # Fallback from timeout
        assert verdict.confidence == 0.3
        assert verdict.reason == "llm_fail:timeout"
        # D2: timeout fallback is dropped
        assert not should_keep(verdict)
```

**Apply to test_degraded_mode.py (per RESEARCH §E3 + E4) — mock BOTH /healthz and /v1/chat/completions to 503:**

```python
import json
import pathlib
import pytest
import respx
from httpx import Response

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "llm" / "labelled.jsonl"


@pytest.mark.integration
async def test_llm_down_degraded_mode_keeps_useful_results():
    """
    LLM-06 hardening: when the router HEAD /healthz fails, the search pipeline
    falls back to the heuristic-only path (junk-blocklist + price-in-card)
    and STILL returns ≥5 useful results from Phase 1's 50-record labelled set.
    """
    candidates = []
    with FIXTURES.open() as f:
        for line in f:
            row = json.loads(line)
            candidates.append(row["candidate"])

    with respx.mock:
        respx.post("http://127.0.0.1:3210/v1/chat/completions").mock(
            return_value=Response(503, json={"error": "router down"})
        )
        respx.head("http://127.0.0.1:3210/healthz").mock(
            return_value=Response(503, json={"error": "router down"})
        )

        from src.artiscrapper.llm import router_health_check
        # /healthz HEAD must fail — that's the degraded-mode trigger (main.py:366)
        assert await router_health_check("http://127.0.0.1:3210", "test-bearer") is False

        # Heuristic-only path: keep candidates with price_in_card or has_price
        survivors = [c for c in candidates if c.get("price_in_card") or c.get("price") or c.get("has_price")]
        assert len(survivors) >= 5, (
            f"Degraded mode should retain ≥5 useful results from Phase 1 labelled set; "
            f"got {len(survivors)}/{len(candidates)}"
        )
```

**Important:** `router_health_check` uses `client.head()` not `client.get()` (verified `src/artiscrapper/llm.py:267`); the respx mock must use `respx.head(...)`.

---

### `tests/integration/test_challenge_backoff.py` (NEW — 503 + Retry-After, D-09 + D-08)

**Primary analog:** `tests/test_cache.py::test_lazy_ttl` — tmp_db + time assertion.
**Secondary analog:** `tests/test_health.py` — TestClient with mocked browser + respx for outbound calls.

**Apply pattern: spin up TestClient with `_make_mock_browser()` from `test_health.py:28-43`, monkeypatch `fetch_serp` to return a synthetic /sorry/ HTML, fire /search, assert 503 + `Retry-After` header.**

**Sorry fixture (D-20):** Create `tests/fixtures/serp/sorry.html` with minimal stand-in (Phase 1 captured none — verified in SPIKE.md §Browser). Content per RESEARCH §G4:

```html
<!doctype html>
<html><head><title>https://www.google.com/sorry/index</title></head>
<body><div id="recaptcha"></div>
<p>We're sorry... but your computer or network may be sending automated queries.</p>
</body></html>
```

Then assert `_detect_block(synthetic_page) is not None` to pin the fixture as block-triggering.

---

### `tests/integration/test_metrics_endpoint.py` (NEW — /metrics smoke, OBS-07 + D-13)

**Analog:** `tests/test_health.py::test_health_shape` (lines 66-74).

**Existing TestClient + body assertion shape:**

```python
def test_health_shape(test_client):
    """OBS-01: GET /health returns 200 with expected JSON shape."""
    resp = test_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    # All four keys must be present and non-null
    for key in ("status", "cloak", "llm", "cache"):
        assert key in body, f"Missing key: {key}"
```

**Apply to test_metrics_endpoint.py:**

```python
def test_metrics_returns_six_families(test_client):
    """OBS-07 + D-13: /metrics exposes ≥6 artiscrapper_* metric families."""
    resp = test_client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    # D-13 grep replication — count distinct artiscrapper_* lines anchored at start
    import re
    families = set(re.findall(r"^(artiscrapper_\w+)", body, re.MULTILINE))
    assert len(families) >= 6, (
        f"Expected ≥6 artiscrapper_* families; got {len(families)}: {sorted(families)}"
    )


def test_metrics_endpoint_has_no_auth(test_client):
    """D-10: /metrics must be reachable WITHOUT X-API-Key header."""
    # No X-API-Key sent — must still return 200 (NOT 401)
    resp = test_client.get("/metrics")
    assert resp.status_code == 200, f"D-10: /metrics must be unauthenticated, got {resp.status_code}"
```

---

### `tests/test_footguns.py` (EXTEND — Sentry + /metrics invariants)

**Analog:** itself (existing 94 lines, lines 13-49 are the canonical invariant-pin shape).

**Existing subprocess + grep pattern to extend (lines 23-29):**

```python
def test_uvloop_absent_from_lock():
    """D6: uvloop must not appear in pyproject.toml or uv.lock."""
    result = subprocess.run(
        ["grep", "-rE", "uvloop", "pyproject.toml", "uv.lock"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, f"uvloop found: {result.stdout}"
```

**Phase 3 additions:**

```python
def test_sentry_does_not_pull_uvloop():
    """D6 + Phase 3: sentry-sdk must NOT transitively install uvloop (RESEARCH §G3)."""
    result = subprocess.run(
        ["grep", "-rE", "uvloop", "uv.lock"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0, f"uvloop appeared in uv.lock — check sentry-sdk: {result.stdout}"


def test_metrics_endpoint_unprotected_by_design():
    """D-10: /metrics mount in main.py must NOT be wrapped by verify_api_key or limiter.limit."""
    # Grep main.py for the metrics mount line; ensure no auth decorator is nearby
    result = subprocess.run(
        ["grep", "-n", "/metrics", "src/artiscrapper/main.py"],
        capture_output=True, text=True,
    )
    assert "make_asgi_app()" in result.stdout, (
        "D-10: /metrics must be mounted via prometheus_client.make_asgi_app() (ASGI sub-app), "
        "NOT a FastAPI route — otherwise CorrelationIdMiddleware + slowapi will wrap it."
    )
```

---

### `pyproject.toml` (EXTEND — deps + pytest markers)

**Analog:** itself.

**Existing structure:**

```toml
[project]
dependencies = [
    "fastapi==0.136.3",
    "uvicorn==0.48.0",
    # ...
    "tldextract==5.3.1",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
]

[dependency-groups]
dev = [
    "pytest>=9.0",
    "pytest-asyncio==1.4.0",
    "respx==0.23.1",
    # ...
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = ["e2e: live network tests (skipped by default)"]
testpaths = ["tests"]
pythonpath = ["."]
```

**Add to `[project].dependencies`:**

```toml
    "prometheus-client==0.25.0",
    "sentry-sdk==2.61.1",
    "slowapi==0.1.9",
```

**Extend `[tool.pytest.ini_options].markers`:**

```toml
markers = [
    "e2e: live network tests (skipped by default)",
    "integration: fixture-replay integration tests (run by default; selectable via -m integration)",
]
```

**Installation command (RESEARCH §Standard Stack):**

```bash
uv add prometheus-client==0.25.0 sentry-sdk==2.61.1 slowapi==0.1.9
uv sync --locked
```

---

### `tests/integration/conftest.py` (NEW — shared fixtures for integration suite)

**Analog:** `tests/conftest.py` (lines 14-45).

**Existing fixtures to mirror (mock_app_state, tmp_db):**

```python
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from src.artiscrapper.cache import PRAGMAS, init_schema


@pytest.fixture
def mock_app_state(tmp_path):
    """Override app.state for tests that don't need a real browser or cache."""
    state = MagicMock()
    state.browser = MagicMock()
    state.browser.is_connected.return_value = True
    state.cache = AsyncMock()
    state.browser_uses = 0
    state.rate_limit = MagicMock()
    state.rate_limit.acquire = AsyncMock()
    yield state


@pytest.fixture
async def tmp_db(tmp_path):
    """Temporary aiosqlite database with WAL PRAGMAS and schema initialized."""
    db_path = str(tmp_path / "cache.db")
    db = await aiosqlite.connect(db_path)
    for pragma in PRAGMAS:
        await db.execute(pragma)
    await db.commit()
    await init_schema(db)
    yield db
    await db.close()
```

**Apply to tests/integration/conftest.py:** Re-export the same `tmp_db` fixture (or rely on the parent `tests/conftest.py` — pytest auto-discovers conftest at all parent levels). Add Phase 3-specific helpers:

```python
@pytest.fixture
def load_labelled_jsonl():
    """Load the 50-record Phase 1 SERP-candidate labelled set."""
    import json, pathlib
    path = pathlib.Path(__file__).parent.parent / "fixtures" / "llm" / "labelled.jsonl"
    with path.open() as f:
        return [json.loads(line) for line in f]


@pytest.fixture(autouse=True)
def reset_challenge_backoff_state():
    """Reset module-level _STATE between tests (challenge_backoff is a singleton)."""
    import src.artiscrapper.challenge_backoff as cb
    cb._STATE = None
    yield
    cb._STATE = None
```

---

## Shared Patterns

### Pattern S1: Module-singleton with double-checked-lock (ChallengeBackoff mirrors LLM resolve_model)

**Source:** `src/artiscrapper/llm.py:93-141`
**Apply to:** `src/artiscrapper/challenge_backoff.py` (NEW)

```python
_RESOLVED_MODEL: str | None = None
_RESOLVE_LOCK = asyncio.Lock()

async def resolve_model(client, router_url, bearer_token) -> str:
    global _RESOLVED_MODEL
    if _RESOLVED_MODEL is not None:
        return _RESOLVED_MODEL
    async with _RESOLVE_LOCK:
        if _RESOLVED_MODEL is not None:  # double-check after acquiring lock
            return _RESOLVED_MODEL
        # … expensive init …
        _RESOLVED_MODEL = ...
        return _RESOLVED_MODEL
```

### Pattern S2: sqlite single-write with `INSERT OR REPLACE` + commit + `?` placeholders

**Source:** `src/artiscrapper/cache.py:106-116`
**Apply to:** `challenge_backoff.py::_persist`, `cache.py::init_schema` (extended DDL)

```python
await cache.execute(
    "INSERT OR REPLACE INTO query_cache (cache_key, …) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
    (cache_key, query, …),
)
await cache.commit()
```

Phase 2 lesson (T-02-01-02): parameterized `?` placeholders only — never string interpolation. Phase 3 inherits this discipline.

### Pattern S3: Structured logging with OBS-05 allow-list (never log secrets / scraped content)

**Source:** `src/artiscrapper/logging_setup.py:65-67`
**Apply to:** `auth.py` (never log api-key value), `main.py` lifespan (`api_keys_loaded` logs count, NOT keys; `sentry_init_done` logs sample_rate, NOT DSN), `challenge_backoff.py` (`challenge_backoff_active` logs retry_after, never sorry-page content)

```python
# OBS-05 allow-list: only these fields are safe to include in candidate log events
SAFE_CANDIDATE_FIELDS = frozenset(
    {"url_hash", "host", "has_price", "freshness_signal", "confidence"}
)
```

Phase 3 secrets to keep out of logs: `API_KEYS` values, `LLM_ROUTER_BEARER_TOKEN`, `SENTRY_DSN`, X-API-Key request header values.

### Pattern S4: Module-import time initialization gated on settings (Sentry init / API_KEYS parsing)

**Source:** `src/artiscrapper/llm.py:95-96` and `src/artiscrapper/config.py:40` (`settings = Settings()` at module level)
**Apply to:** `logging_setup.py::_init_sentry()` at module bottom, `auth.py::API_KEYS = _parse_api_keys()` at module top

Pattern: compute config-derived state ONCE per process at module import, not per-request. Lifespan emits a log line declaring the loaded values (D-19 empirical retest gate).

### Pattern S5: TestClient + monkeypatched cloakbrowser for integration tests

**Source:** `tests/test_health.py:23-63`
**Apply to:** `tests/test_auth.py`, `tests/integration/test_challenge_backoff.py`, `tests/integration/test_metrics_endpoint.py`

```python
# Set required env vars BEFORE importing app
os.environ.setdefault("LLM_ROUTER_BEARER_TOKEN", "test-token-health")
os.environ["CACHE_DB_PATH"] = _tmp_db.name

from fastapi.testclient import TestClient
from src.artiscrapper.main import app


@pytest.fixture
def test_client(monkeypatch):
    mock_browser = _make_mock_browser()
    async def _fake_launch_async(**kwargs):
        return mock_browser
    monkeypatch.setattr("src.artiscrapper.main.launch_async", _fake_launch_async)
    with TestClient(app) as client:
        app.state.browser = mock_browser
        yield client
```

### Pattern S6: respx mocking of httpx external calls

**Source:** `tests/test_llm.py:111-117`, `tests/test_health.py:77-83`
**Apply to:** `tests/integration/test_degraded_mode.py` (mock /healthz HEAD + /v1/chat/completions POST), `tests/integration/test_challenge_backoff.py` (mock external httpx if any)

```python
with respx.mock:
    respx.post("http://127.0.0.1:3210/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={...})
    )
    respx.head("http://127.0.0.1:3210/healthz").mock(
        return_value=httpx.Response(503)
    )
    # … run code that calls these endpoints …
```

### Pattern S7: Per-fixture pinned assertions (D-18 — no `len > 0` shape checks)

**Source:** `tests/test_parser.py:101-138` (post-commit `160c133`)
**Apply to:** `tests/integration/test_catalog_extraction.py` (≥85% rate with per-fixture details list), `tests/integration/test_degraded_mode.py` (≥5 specific candidates, not "any candidate")

```python
expectations = {
    "01-pelota_playera_quico.html": (15, 18),   # (min_carousel_items, min_with_price)
    "02-filtro_aceite_ford_focus.html": (25, 25),
    # …
}
for name, (min_carousel, min_with_price) in expectations.items():
    cands = parse_serp(html)
    assert sum(1 for c in cands if c.get("price_in_card")) >= min_with_price, (
        f"{name}: regressed: got {with_price}, expected ≥{min_with_price}"
    )
```

### Pattern S8: Foot-gun pinned by test (subprocess grep + behavior assertion)

**Source:** `tests/test_footguns.py:13-49`
**Apply to:** `tests/test_footguns.py` extension (Sentry-no-uvloop, /metrics-no-auth)

```python
def test_no_persistent_context_in_codebase():
    """D8: launch_persistent_context must not appear in src/."""
    result = subprocess.run(
        ["grep", "-rn", "launch_persistent_context", "src/"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, f"D8 foot-gun: launch_persistent_context found:\n{result.stdout}"
```

---

## No Analog Found

| File | Role | Data Flow | Reason | Planner Strategy |
|------|------|-----------|--------|------------------|
| (none) | — | — | — | — |

Every Phase 3 surface has a direct analog in the Phase 2 codebase. Phase 3 is almost entirely a wiring + extension exercise (RESEARCH §Don't Hand-Roll explicitly notes this) — no greenfield architecture.

The closest thing to "no analog" is the slowapi `Limiter` decorator stack, but the wiring path is fully specified by `slowapi`'s own llms.txt docs (RESEARCH §C cites the source directly), and the placement vs `CorrelationIdMiddleware` follows the same outermost-middleware-first rule already established in `main.py:183`.

---

## Metadata

**Analog search scope:**
- `src/artiscrapper/` — 14 source modules (all 11 .py files read)
- `tests/` — 7 test files + conftest.py (all read or sampled)
- `tests/fixtures/` — directory layout verified via `ls`
- `pyproject.toml`, `.planning/phases/03-robustness/03-RESEARCH.md`, `.planning/phases/03-robustness/03-CONTEXT.md`

**Files scanned for analog matching:** 25 (sources + tests + config + research)

**Pattern extraction date:** 2026-06-03

**Closest-analog quality summary:**
- Exact (same role + same data flow): 14/16 files
- Role-match (different data flow): 2/16 files (`auth.py`, `test_sentry_init.py` — no prior FastAPI Depends or sentry-init pattern in repo)
- No analog: 0/16 files

**Phase 3 wiring depth:** Every new module copies at least one verbatim pattern from a Phase 2 module. The two highest-value pinning analogs:
1. `src/artiscrapper/llm.py:93-141` (`_RESOLVED_MODEL` / `_RESOLVE_LOCK` / `resolve_model`) — the canonical module-singleton-with-async-lock blueprint for `challenge_backoff.py`.
2. `src/artiscrapper/cache.py:106-116` (`INSERT OR REPLACE` with parameterized `?` placeholders + immediate `commit()`) — the canonical sqlite-upsert blueprint for the `challenge_state` single-row table.

If the planner copies these two blocks verbatim and adapts variable names, ChallengeBackoff will be structurally identical to existing Phase 2 conventions — no novel state-management invention needed.

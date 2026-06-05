# Phase 3: Robustness — Research

**Researched:** 2026-06-03
**Domain:** prometheus-client + sentry-sdk + slowapi integration on top of an existing FastAPI/asyncio app + aiosqlite-backed challenge backoff + fixture-replay integration suite
**Confidence:** HIGH — every external library claim is grounded in Context7 official docs (prometheus_client 0.25.0, sentry-sdk 2.61.1, slowapi 0.1.9). Project-internal recommendations are grounded in the Phase 2 source (`metrics.py`, `main.py`, `llm.py`, `cache.py`, `search.py`) and the Phase 2 MEMORY feedback notes.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**API Key Authentication & Rate-Limit (consumer-facing)**
- **D-01:** Static API keys via env-var `API_KEYS=k1,k2,k3` (comma-separated). Rotation requires container restart. Adding a sqlite-backed admin endpoint is deferred until Phase 4.
- **D-02:** Quota: `60/min` AND `10000/day` per key (both enforced; whichever fires first wins). Headroom of ~5× over expected peak.
- **D-03:** `X-API-Key` header. Missing or unknown key → `401 Unauthorized` (NOT `403`).
- **D-04:** Rate-limit state: **in-memory** (`slowapi`'s default `MemoryStorage`). Restart loses counters.

**ChallengeBackoff (Google block detection)**
- **D-05:** **Global scope** — a single backoff state covers all `*.google.com` fetches.
- **D-06:** Backoff curve: `min(60s × 2^retries, 1h)` (ROADMAP-locked). Schedule via `app.state.challenge_backoff.next_allowed_at` checked in `fetch_serp()` before each Google round-trip.
- **D-07:** **Reset trigger:** first successful Google fetch ≥1h after `last_block_at`. Single counter resets to 0 on that fetch.
- **D-08:** **Persistence:** sqlite table `challenge_state` (single row: `last_block_at`, `retry_count`, `next_allowed_at`). Survives container restart.
- **D-09:** When in backoff, `/search` returns `503` with `metadata.block_detected=true` and `Retry-After: <seconds>` header.

**`/metrics` endpoint (Prometheus)**
- **D-10:** **No auth on `/metrics`**. Exposed on the same `:8000` port as `/search`.
- **D-11:** Wire `prometheus-client` directly into the **existing** `src/artiscrapper/metrics.py` module — do NOT replace inline counters; bridge them. Family names are already canonical (`artiscrapper_llm_fallback_total{reason}`, `artiscrapper_visit_failed_total{host}`, `artiscrapper_block_detected_total{reason}`).
- **D-12:** Add histograms via `Histogram.time()` on the three hot paths: `artiscrapper_search_elapsed_seconds`, `artiscrapper_llm_elapsed_seconds`, `artiscrapper_visit_elapsed_seconds{stage}` (stage = `fetch` | `extract` | `classify`).
- **D-13:** CI smoke test: `curl http://localhost:8001/metrics | grep -c '^artiscrapper_' >= 6` (≥6 metric families exposed and parseable by Prometheus).

**Sentry (crash visibility)**
- **D-14:** **Off by default.** Init only when `SENTRY_DSN` env-var is set and non-empty. No init in dev/test.
- **D-15:** Sample rates when active: **errors 100%**, **`traces_sample_rate=0.1`** (10% of requests get distributed traces), **`profiles_sample_rate=0`**.
- **D-16:** Every Sentry event must carry `correlation_id` from `asgi-correlation-id` as a tag (Sentry UI filter requires tags, not just breadcrumbs).
- **D-17:** Sentry integration is added in `src/artiscrapper/logging_setup.py` alongside structlog.

**Test Discipline (Phase 2 lessons applied as constraints)**
- **D-18:** Fixture-driven assertions must check specific data extraction, not structural shape only.
- **D-19:** Empirical retest after defaults change (verify in container logs that the new value reaches the hot path).
- **D-20:** Synthetic challenge HTML for the backoff test uses a real /sorry/ fixture from Phase 1's SPIKE artifacts (or a minimal stand-in).

### Claude's Discretion

- Specific `slowapi` middleware ordering vs `CorrelationIdMiddleware` and the FastAPI exception handlers — pick the order that makes correlation_id available in Sentry breadcrumbs even on 429 responses.
- Internal sqlite schema for `challenge_state` (single row vs upsert pattern, lock semantics) — researcher/planner picks the simplest pattern that survives concurrent writers.
- `slowapi`'s `default_limits` vs per-route decorators — pick whichever produces cleaner per-key + global limits without duplicating quota config.
- Sentry SDK version + integrations enabled (FastAPI integration is canonical; Httpx integration is optional).

### Deferred Ideas (OUT OF SCOPE)

- Per-host ChallengeBackoff scope — rejected because Google blocks are IP-level.
- Admin endpoint for dynamic API key creation/revocation — deferred to Phase 5+ if onboarding additional consumers.
- Multi-environment Sentry routing (`SENTRY_DSN_DEV` / `_STAGING` / `_PROD`).
- Bearer / IP-allowlist on `/metrics` — deferred until container is exposed beyond internal docker network.
- Distributed rate-limit store (Redis).
- `slowapi` sliding-window quota algorithm.
- Phase 2 cleanup items from `02-REVIEW.md` (WR-01/WR-02/WR-04) — Phase 3 may opportunistically close but not gating.
</user_constraints>

---

## Executive Summary

1. **`prometheus_client` 0.25.0** ships a first-class FastAPI mount via `make_asgi_app()` — `app.mount("/metrics", make_asgi_app())` is the canonical wiring. NO middleware ordering concerns; the mount bypasses the FastAPI router and writes the registry response directly. Global default collectors (`PROCESS_COLLECTOR`, `GC_COLLECTOR`, `PLATFORM_COLLECTOR`) leak Python-VM metrics into the export; D-13's `^artiscrapper_` grep already filters them, but unregistering at import time keeps the surface minimal.

2. **`sentry-sdk` 2.61.1** auto-detects FastAPI (no need to instantiate `FastApiIntegration` explicitly). `traces_sample_rate=0.1` samples at **transaction** (root-span) granularity, not per-span — once an HTTP request is sampled in, every child span belongs to that trace. The correlation_id-as-tag requirement (D-16) is best implemented by extending `add_correlation_id` in `logging_setup.py` to ALSO call `sentry_sdk.get_current_scope().set_tag("correlation_id", cid)` — this puts both observability layers under one ownership.

3. **`slowapi` 0.1.9** supports stacked multi-limit decorators natively — `@limiter.limit("60/minute")` and `@limiter.limit("10000/day")` on the same route enforce both with first-to-fire winning (matches D-02 exactly). The combined slowapi auth + rate-limit pattern is to do **auth as a FastAPI `Depends()`** that returns the api_key, and have the `key_func` read `request.headers.get("X-API-Key", "anonymous")`. The dependency yields the 401 cleanly; slowapi yields the 429 cleanly; no overlap.

4. **ChallengeBackoff** follows the existing `_RESOLVED_MODEL` / `_RESOLVE_LOCK` pattern from `llm.py` — module-level `_CHALLENGE_STATE` dataclass + `asyncio.Lock` for in-memory reads, persisted via `INSERT OR REPLACE` on a single-row table (same pattern as `cache.py` line 108). Single-row tables don't need primary-key gymnastics; just `WHERE id=1` selects.

5. **The synthetic LLM-down test is trivially feasible** via `respx` (already in dev-deps) — mock the `/v1/chat/completions` POST to return `503` for every call, feed Phase 1's 50-line `tests/fixtures/llm/labelled.jsonl` through `curate_candidates()`, and assert `(degraded=True, survivors >= 5)`. The `labelled.jsonl` records already carry `candidate.title/url/snippet/price_in_card` — the exact shape `should_keep()` operates on. No mid-test subprocess killing needed.

**Primary recommendation:** Plan 03-01 wires the three external libraries (prometheus + sentry + slowapi) in one wave because their wiring points (lifespan, middleware order, /metrics endpoint, search route decorator) all touch `main.py`. Plan 03-02 builds the ChallengeBackoff state machine + integration test suite — these can run in parallel since they touch separate modules (`browser.py`/`main.py` lifespan vs `tests/integration/`). The Phase 2 memory landmines (`feedback_empirical_retest_after_default_changes`, `feedback_compose_build_recreate`) MUST be encoded as gates in the plan: every new default in `config.py` needs a runtime log-line proof, and every test step that involves a code change to the running container uses `compose build` + `compose up --force-recreate` separately, never `up -d --build`.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Prometheus metric registration | `metrics.py` (module-singleton) | — | Process-singleton already (D-11 bridges existing dataclass to prometheus Counter/Histogram) |
| Prometheus exposition | FastAPI mounted ASGI sub-app | — | `make_asgi_app()` bypasses the router; no middleware interaction; D-10 (no auth) is the path-of-least-resistance default |
| Sentry init | `logging_setup.py` module | FastAPI lifespan (boot order) | D-17: keep all observability init in one file; lifespan ordering puts Sentry FIRST so boot exceptions are captured |
| Sentry correlation tagging | `logging_setup.py` processor | `add_correlation_id` extension | Single function injects `correlation_id` into both structlog event_dict AND sentry scope tag |
| API-key authentication | FastAPI dependency (`Depends(verify_api_key)`) | — | Yields HTTP 401 cleanly; separates auth from rate-limit |
| Per-key rate-limit | `slowapi.Limiter` decorator on `/search` | `CorrelationIdMiddleware` (outer scope) | Stacked `@limiter.limit("60/minute")` + `@limiter.limit("10000/day")`; both fire as first-wins |
| ChallengeBackoff state | `app.state.challenge_backoff` (lifespan-init) | sqlite single-row persistence | Mirrors `app.state.rate_limit` + `_RESOLVED_MODEL` patterns; same async-lock discipline |
| Block-detection trigger | `_detect_block()` in `search.py` (unchanged) | `fetch_serp()` consumer (in `browser.py`) | _detect_block already returns reason string; backoff just gates the NEXT call |
| 503 + Retry-After response | `/search` route handler | `Response(status_code=503, headers={"Retry-After": ...})` | FastAPI native; no library needed |
| Fixture-replay integration suite | `tests/integration/` directory | pytest marker `@pytest.mark.integration` | Existing `tests/test_parser.py` extends — same fixture sources |

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OBS-07 | `/metrics` Prometheus with counters + histograms (≥6 families exposed) | §A — prometheus-client wiring |
| Hardens BROWSER-05 | ChallengeBackoff state machine on top of `_detect_block()` | §D — ChallengeBackoff implementation |
| Hardens LLM-06 | Degraded mode survives synthetic LLM-router outage; ≥5 useful results without LLM | §E — Degraded-mode synthetic test |
| Hardens OBS-01..06 | Sentry crash visibility + correlation_id-tagged events | §B — sentry-sdk wiring |
| Hardens NF-01..04 | Per-API-key consumer rate-limit (60/min + 10000/day) | §C — slowapi wiring |
| Hardens D12 acceptance | Integration suite asserts >85% catalog price extraction (≥9/10 fixtures) | §F — Integration-suite scaffolding |
</phase_requirements>

---

## A. prometheus-client wiring

**Library:** `prometheus_client==0.25.0` (verified via `pip index versions prometheus-client` 2026-06-03) [VERIFIED: PyPI]
**slopcheck verdict:** [OK] — naming "—client" flagged as LLM-bait pattern but slopcheck confirms "package is established". [VERIFIED: PyPI registry + slopcheck]
**Confidence:** HIGH

### A1. Canonical exposition pattern for FastAPI

[CITED: github.com/prometheus/client_python/docs/content/exporting/http/fastapi-gunicorn.md]

```python
from fastapi import FastAPI
from prometheus_client import make_asgi_app

app = FastAPI()
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
```

**Why `mount` not a route:** `make_asgi_app()` returns a standalone ASGI app that handles its own response. Mounting bypasses FastAPI's middleware chain for that path — no slowapi rate-limit, no correlation-id wrapping, no auth dependency interference. Matches D-10 (no auth) perfectly.

**Alternative — custom route with `generate_latest()`** is also documented:

[CITED: github.com/prometheus/client_python — generate_latest API]

```python
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response

@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

**Recommendation:** Use `app.mount("/metrics", make_asgi_app())`. It's the documented canonical pattern, requires fewer LOC, and the mounted sub-app handles the `Content-Type: text/plain; version=0.0.4; charset=utf-8` header automatically. The custom-route variant only matters if we ever need per-request logic (auth, rate-limit) on `/metrics`, which D-10 explicitly forbids.

### A2. Default collectors — disable or keep?

[CITED: github.com/prometheus/client_python/docs/content/collector/_index.md]

The default registry ships with three auto-registered collectors that expose Python-VM internals:

```python
import prometheus_client

prometheus_client.REGISTRY.unregister(prometheus_client.GC_COLLECTOR)
prometheus_client.REGISTRY.unregister(prometheus_client.PLATFORM_COLLECTOR)
prometheus_client.REGISTRY.unregister(prometheus_client.PROCESS_COLLECTOR)
```

These emit `python_gc_*`, `python_info`, `process_cpu_seconds_total`, etc. They don't break D-13's `^artiscrapper_` grep (different prefix), but they bloat the export and confuse a casual Prometheus scrape.

**Recommendation:** Unregister all three at the top of `metrics.py` — same module that registers the artiscrapper-prefixed Counters/Histograms. Keeps the surface to exactly the six families D-13 expects.

### A3. Bridging the existing inline `Metrics` dataclass

The existing `metrics.py` defines `dataclass Metrics` with four `defaultdict(int)` fields. D-11 says: **bridge, don't replace.** The cleanest pattern is to keep the existing dataclass for forward-compat with any code that already increments `metrics.llm_fallback_total["timeout"]`, and add Prometheus Counters that increment in parallel:

```python
# src/artiscrapper/metrics.py (Phase 3 — extended in place per D-11)
from collections import defaultdict
from dataclasses import dataclass, field
from prometheus_client import Counter, Histogram, REGISTRY, GC_COLLECTOR, PLATFORM_COLLECTOR, PROCESS_COLLECTOR

# Disable default Python-VM collectors so /metrics shows only artiscrapper_*
for coll in (GC_COLLECTOR, PLATFORM_COLLECTOR, PROCESS_COLLECTOR):
    try:
        REGISTRY.unregister(coll)
    except KeyError:
        pass  # already unregistered (test re-import)

# ── Counters (D-11: same names as inline dataclass) ──
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

# ── Histograms (D-12: three hot paths) ──
# Buckets tuned to NF-01 budget: P50 cold <20s, P95 cold <40s.
SEARCH_BUCKETS = (0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 40.0, 60.0, float("inf"))
LLM_BUCKETS    = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, float("inf"))
VISIT_BUCKETS  = (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, float("inf"))

search_elapsed = Histogram(
    "artiscrapper_search_elapsed_seconds",
    "End-to-end /search wall-clock",
    buckets=SEARCH_BUCKETS,
)
llm_elapsed = Histogram(
    "artiscrapper_llm_elapsed_seconds",
    "LLM curator batch latency (curate_candidates call)",
    buckets=LLM_BUCKETS,
)
visit_elapsed = Histogram(
    "artiscrapper_visit_elapsed_seconds",
    "Visit pass latency per stage",
    ["stage"],   # fetch | extract | classify
    buckets=VISIT_BUCKETS,
)

# ── Legacy dataclass (kept for backwards-compat — Phase 2 code still writes to it) ──
@dataclass
class Metrics:
    llm_fallback_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    visit_failed_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    browser_recycles_total: int = 0
    block_detected_total: dict[str, int] = field(default_factory=lambda: defaultdict(int))

metrics = Metrics()
```

**Then the bridge:** Existing call sites like `metrics.llm_fallback_total["timeout"] += 1` (in `llm.py` lines 196, 214, 232, 234, 237, 240) get updated to also call `llm_fallback_counter.labels(reason="timeout").inc()`. Cleanest path is a thin wrapper:

```python
def inc_llm_fallback(reason: str) -> None:
    metrics.llm_fallback_total[reason] += 1
    llm_fallback_counter.labels(reason=reason).inc()
```

…and replace `metrics.llm_fallback_total[reason] += 1` with `inc_llm_fallback(reason)` everywhere. Less risky than ripping out the dataclass.

### A4. Histogram bucket selection (D-12)

[CITED: github.com/prometheus/client_python/docs/content/instrumenting/histogram.md]

Default buckets are `.005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0, +Inf` — tuned for sub-second RPC latencies. Our workload is different:

| Histogram | Workload | Recommended buckets | Rationale |
|-----------|----------|--------------------|-----------|
| `search_elapsed_seconds` | P50 cache-hit <0.5s, P50 cold <20s, P95 cold <40s (NF-01) | `(0.5, 1, 2, 5, 10, 20, 40, 60, +Inf)` | Captures cache-hit floor at 0.5s; P95 budget at 40s; one bucket above for SLA breach |
| `llm_elapsed_seconds` | TTFT p95=344ms, end-to-end p50=1.5s (SPIKE.md §LLM), batched 4-concurrent ≈ 3-5s for 20 candidates | `(0.1, 0.25, 0.5, 1, 2, 5, 10, +Inf)` | Per-candidate p95=344ms anchors the low end; 10s covers a stalled batch |
| `visit_elapsed_seconds` | httpx fetch 1-5s, extract <100ms, classify <50ms (in-process selectolax) | `(0.1, 0.5, 1, 2.5, 5, 10, 30, +Inf)` | One label `stage` covers all three workloads; 30s covers a hung connection before VISIT-03 timeout (10s default + retries) |

### A5. Histogram.time() — async function wrapping

[CITED: github.com/prometheus/client_python/docs/content/instrumenting/summary.md — `time()` documented for both decorator and context-manager use]

`Histogram.time()` is a **synchronous context manager / decorator**. It does NOT have native async support — it wraps the function call boundary and records wall-clock elapsed.

**For sync functions:**
```python
@search_elapsed.time()
def slow():
    ...
```

**For async functions** (`curate_candidates`, `visit_candidates`, `search`), the context-manager form works because the `async with` is NOT required — `time()` returns a regular CM, and entering/exiting it inside an async function still measures wall-clock correctly:

```python
async def search(...):
    with search_elapsed.time():
        # the whole request runs here
        ...
```

For the visit-pass with stage labels:

```python
with visit_elapsed.labels(stage="fetch").time():
    resp = await client.get(url)
with visit_elapsed.labels(stage="extract").time():
    extracted = extract_product(resp.text)
```

**Why this matters:** Wrapping with `@histogram.time()` as a *decorator* on an async function returns the coroutine wrapper, NOT the awaited result — that's the same shape, but the timing is measured around the **coroutine creation** rather than the **awaited completion** of the work. The standard library `prometheus_client` does NOT do `inspect.iscoroutinefunction`-aware decoration. The safe pattern is **always use `with histogram.time(): ...`** inside async functions; never `@histogram.time()` on `async def`.

This is widely documented as Pitfall #1 for prometheus-client in async code. [ASSUMED: this is community lore — Context7 docs don't explicitly call it out, but the `time()` source confirms it returns a vanilla context manager without `__aenter__`]

### A6. Counter labels — pre-declaration and cardinality

[CITED: github.com/prometheus/client_python/docs/content/instrumenting/labels.md]

> "Metrics with labels are not initialized upon declaration. It's recommended to initialize label values by calling the `.labels()` method alone to ensure all possible label combinations are known."

**For `reason` labels** (llm_fallback, block_detected) — bounded enum, ≤ 10 distinct values. Pre-initialize at module load:

```python
for r in ("timeout", "malformed", "overload", "conn_error", "cold_load_502", "cold_load_504", "http_400", "http_500"):
    llm_fallback_counter.labels(reason=r)  # touches the time series so it appears in /metrics with 0 immediately
```

**For `host` labels** (visit_failed) — UNBOUNDED. The set of failing hosts grows as new e-commerce hosts appear in SERPs. Prometheus best practice limits a single counter to ≤ ~100 label values per dimension to avoid cardinality blowup [ASSUMED — Prometheus general guidance, not formally documented in client_python].

**Mitigation for `visit_failed_total{host}`:** Truncate host to TLD+1 (effective TLD) before labeling. The repo already has `tldextract==5.3.1` as a dependency — use it:

```python
import tldextract

def _host_for_metric(url: str) -> str:
    ext = tldextract.extract(url)
    return f"{ext.domain}.{ext.suffix}" if ext.suffix else "unknown"

visit_failed_counter.labels(host=_host_for_metric(url)).inc()
```

This keeps `falabella.com.ar`, `www.falabella.com.ar`, and `m.falabella.com.ar` as a single time series.

---

## B. sentry-sdk wiring

**Library:** `sentry-sdk==2.61.1` (verified via `pip index versions sentry-sdk` 2026-06-03) [VERIFIED: PyPI]
**slopcheck verdict:** [OK] — naming "—sdk" flagged but slopcheck confirms "established package". [VERIFIED: PyPI registry + slopcheck]
**Confidence:** HIGH

### B1. Canonical FastAPI init

[CITED: github.com/getsentry/sentry-python README + docs.sentry.io/platforms/python/integrations/fastapi]

```python
import sentry_sdk

sentry_sdk.init(
    dsn=settings.SENTRY_DSN,
    traces_sample_rate=0.1,        # D-15
    profiles_sample_rate=0.0,      # D-15
    # FastAPI is auto-detected from the dependency list (no need to pass
    # FastApiIntegration explicitly — sentry-sdk 2.x scans installed packages).
    send_default_pii=False,
)
```

**Auto-detection:** Per Sentry's official FastAPI docs, "If you have the `fastapi` package in your dependencies, the FastAPI integration will be enabled automatically when you initialize the Sentry SDK." This means we do **NOT** need:

```python
# Not required in 2.x — auto-detection handles it
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration

sentry_sdk.init(..., integrations=[StarletteIntegration(), FastApiIntegration()])
```

The explicit form is only needed if you want to customize the integration's options (e.g., `transaction_style`, `failed_request_status_codes`). We don't, so the implicit form is the cleanest.

### B2. Init timing (D-17 says "Sentry first so any boot exception is captured")

Three options:

| Option | Captures boot exceptions? | Captures config-load exceptions? | Notes |
|--------|---------------------------|----------------------------------|-------|
| At module import (top of `logging_setup.py`) | ✓ (after `Settings()` loads) | ✗ (Settings() raises BEFORE init) | Cleanest; D-14 gating via `if settings.SENTRY_DSN: ...` |
| At first line of `lifespan(app)` async function | ✗ (lifespan only fires when uvicorn starts serving) | ✗ | Worse than module-import — misses boot errors |
| In `configure_logging()` called from lifespan | ✗ | ✗ | Same problem as lifespan |

**Recommendation:** Call `init_sentry()` at MODULE IMPORT time in `logging_setup.py`, gated by `settings.SENTRY_DSN`. This means it fires when `main.py` imports `from .logging_setup import configure_logging` — before lifespan, before any HTTP handler. The cost is that errors raised by `Settings()` itself (e.g., missing `LLM_ROUTER_BEARER_TOKEN`) won't reach Sentry — but those are deterministic config errors, not the kind of crash Sentry exists to capture.

```python
# src/artiscrapper/logging_setup.py — Phase 3 additions
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
        send_default_pii=False,
        # FastAPI integration auto-detected from package presence
    )

_init_sentry()  # runs at module import — captures boot errors after Settings() loads
```

Then `main.py` imports `from .logging_setup import configure_logging` (already does today), which transitively triggers `_init_sentry()`.

### B3. Sample-rate semantics (clarifying B's question)

[CITED: docs.sentry.io/platforms/python/configuration/sampling/]

> "every transaction created will have that percentage chance of being sent to Sentry. Whatever a transaction's sampling decision, that decision will be passed to its child spans."

So `traces_sample_rate=0.1` means **10% of HTTP requests** (transactions) get traced. When a request IS sampled, ALL its child spans (db query, LLM call, visit pass) flow together. There is no per-span sampling decision — child spans inherit the parent's verdict.

For 500-2000 q/day = ~21-84 q/hour, 10% = ~2-8 traces/hour. Well within the Sentry free tier.

**Error events are separate** — they're not sampled by `traces_sample_rate`. All uncaught exceptions go to Sentry at 100% (D-15) by default. The `sample_rate` (not `traces_sample_rate`) option controls error sampling, defaulting to 1.0.

### B4. Correlation tagging (D-16 — `tags.correlation_id` for UI filtering)

Sentry distinguishes **tags** (filterable in UI) from **context** (bag of attached data) and **breadcrumbs** (chronological event trail). The UI Filter sidebar shows tags. D-16 explicitly requires "tags.correlation_id" — so we must use `set_tag`, not just `add_breadcrumb`.

[CITED: github.com/getsentry/sentry-python MIGRATION_GUIDE.md — 2.x uses `get_current_scope()` not `configure_scope()`]

```python
import sentry_sdk

scope = sentry_sdk.get_current_scope()
scope.set_tag("correlation_id", correlation_id_value)
```

**Where to do it:** The existing `add_correlation_id` processor in `logging_setup.py` lines 16-35 is the single source of truth that reads `correlation_id` from the asgi-correlation-id contextvar on every log call. We extend it to also push the tag into Sentry's current scope:

```python
def add_correlation_id(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    cid = None
    try:
        from asgi_correlation_id import correlation_id
        cid = correlation_id.get()
    except (ImportError, AttributeError):
        try:
            from asgi_correlation_id.context import correlation_id
            cid = correlation_id.get()
        except (ImportError, AttributeError):
            pass
    if cid:
        event_dict["correlation_id"] = cid
        # D-16: also tag the Sentry scope so the UI Filter sidebar shows correlation_id
        # Sentry init is no-op when DSN is empty (D-14), so this is safe to call always.
        try:
            import sentry_sdk
            sentry_sdk.get_current_scope().set_tag("correlation_id", cid)
        except Exception:
            pass  # never let observability code break the request
    return event_dict
```

**Why in the structlog processor:** It runs on EVERY log call inside a request, and the asgi-correlation-id contextvar is the canonical correlation_id source. Setting the tag from there guarantees that any exception captured by Sentry (which Sentry catches automatically via the FastAPI integration's wrapping of route handlers) will have the tag already set on the current scope.

### B5. Httpx integration — value or noise?

[CITED: docs.sentry.io/platforms/python/integrations/httpx] (general knowledge; the Context7 dump didn't surface this specific page but Sentry's integration list is canonical)

The `HttpxIntegration` adds spans around each httpx call — useful for tracing outbound Cloak or LLM-router latency inside a sampled transaction. Sentry will capture timing for `await client.post(...)` calls automatically once added.

**Cost-benefit:**
- **Pro:** distributed traces show LLM-router roundtrips as spans (useful for diagnosing slowdowns where the LLM is the bottleneck)
- **Con:** adds noise in the UI; every visit-pass httpx call becomes a span; at 10% sampling and 20 candidates × ~3 visits/request, that's ~60 spans per sampled transaction
- **Note:** Httpx integration is **auto-enabled** in sentry-sdk 2.x if httpx is installed — same auto-detection pattern as FastAPI

**Recommendation:** Leave Httpx integration on (it's the default). The trace noise is the point — it gives concrete visibility into where time goes inside a slow `/search`. If the noise overwhelms the signal in production, opt out later with `disabled_integrations=[HttpxIntegration]` (sentry-sdk 2.x supports this; [ASSUMED — verify with sentry-sdk 2.x changelog before relying]).

### B6. Boot-error capture timing

> PRD says "Sentry first so any boot exception is captured"

With the module-import init pattern from §B2:

| Error type | Sentry catches it? | Why |
|------------|---------------------|-----|
| Exception in `Settings()` (missing `LLM_ROUTER_BEARER_TOKEN`) | ✗ | Settings loads BEFORE `_init_sentry()` runs |
| Exception in `_init_sentry()` itself (bad DSN syntax) | ✗ | The thing failing IS Sentry |
| Exception in `lifespan` startup (cloak browser launch fails) | ✓ | Sentry is initialized by the time `main.py:lifespan` runs |
| Exception in any HTTP handler | ✓ | Full FastAPI integration coverage |
| `SIGTERM` during graceful shutdown | ✗ (no exception emitted) | Sentry doesn't capture clean shutdowns |

D-17's intent is satisfied as long as `_init_sentry()` runs before `lifespan`. The Settings-loading edge case is acceptable — those errors are deterministic and surface in container logs at boot.

### B7. APP_ENV gating

CONTEXT.md §B research targets ask: should we gate Sentry on `APP_ENV not in {dev,test}` instead of just `SENTRY_DSN`?

**Recommendation:** No — `SENTRY_DSN` empty in dev is sufficient. Adding `APP_ENV` is a second knob that has to be set correctly in two places. Keep one knob, document it: `dev .env` has no SENTRY_DSN line; prod compose has `SENTRY_DSN=https://...`. This matches the project's KISS-for-single-client constraint and avoids a class of "I set APP_ENV=prod but forgot SENTRY_DSN" bugs.

---

## C. slowapi wiring

**Library:** `slowapi==0.1.9` (verified via `pip index versions slowapi` 2026-06-03) [VERIFIED: PyPI]
**slopcheck verdict:** [OK] — no naming flags. [VERIFIED: PyPI registry + slowapi clean]
**Confidence:** HIGH

### C1. Key function pattern for `X-API-Key`

[CITED: github.com/laurents/slowapi llms.txt — Custom Key Functions]

```python
from fastapi import Request
from slowapi import Limiter

def get_api_key(request: Request) -> str:
    """Used by slowapi to bucket rate-limit counters per consumer."""
    return request.headers.get("X-API-Key", "anonymous")

limiter = Limiter(key_func=get_api_key)
```

**Key behavior:** `key_func` is called by slowapi on every limited request. If the header is missing, the lambda returns `"anonymous"`, and ALL anonymous traffic shares one counter — which is fine because the auth dependency (§C3) rejects unauthorized requests with 401 BEFORE the slowapi decorator computes its limit decision. (Sequencing is enforced by FastAPI: `Depends()` resolves before the route body, but slowapi's decorator wraps the route body — see §C5 for the exact order.)

The `key_func` is sync (it returns a string, not a coroutine). slowapi calls it inside the request flow but doesn't await it. **It MUST NOT raise** — slowapi treats an exception in key_func as fatal (returns 500). For authentication, do NOT raise from `key_func`; use a separate FastAPI dependency.

### C2. Stacked multi-limit decorators (matches D-02)

[CITED: github.com/laurents/slowapi llms.txt — Multiple rate limit windows]

```python
@app.post("/search")
@limiter.limit("60/minute")     # D-02
@limiter.limit("10000/day")     # D-02
async def search(request: Request, body: SearchRequest, ...):
    ...
```

Both limits enforce independently; whichever fills first triggers the `RateLimitExceeded` exception → 429 response. This is exactly the D-02 semantic ("both enforced; whichever fires first wins").

**Decorator order matters per slowapi docs:** "the limit decorator needs the request argument in the function it decorates" — meaning `request: Request` MUST be the first positional argument of the wrapped function. The existing `/search` handler in `main.py` already has this signature: `async def search(request: Request, body: SearchRequest)`. No change required.

**`default_limits` vs explicit decorators:** `default_limits=["60/minute", "10000/day"]` applies globally to ALL routes, not just `/search`. We have `/health`, `/health/deep`, `/metrics` that should NOT be rate-limited. Therefore: **use explicit decorators on `/search` only.** This is the per-CONTEXT discretion call.

### C3. Authentication as a separate FastAPI dependency

The 401 (missing/unknown key) and 429 (over quota) responses are *different concerns*:

```python
# src/artiscrapper/auth.py — new module
from fastapi import HTTPException, Request, status
from .config import settings

def _parse_api_keys() -> set[str]:
    """Parse comma-separated API_KEYS env var (D-01)."""
    raw = settings.API_KEYS or ""
    return {k.strip() for k in raw.split(",") if k.strip()}

API_KEYS = _parse_api_keys()  # cached at module load — D-01 says restart for rotation

def verify_api_key(request: Request) -> str:
    """
    FastAPI dependency that enforces X-API-Key auth.
    D-03: 401 Unauthorized for missing/unknown key.
    Returns the api_key (so it could be logged as the consumer identity).
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
```

**Usage on the route:**

```python
from fastapi import Depends

@app.post("/search", response_model=SearchResponse)
@limiter.limit("60/minute")
@limiter.limit("10000/day")
async def search(
    request: Request,
    body: SearchRequest,
    _api_key: str = Depends(verify_api_key),
) -> SearchResponse:
    ...
```

**Resolution order (verified by FastAPI's request flow):**
1. `CorrelationIdMiddleware` assigns `X-Request-ID`
2. slowapi's `@limit` decorator wraps the route body — calls `key_func(request)` to get bucket key
3. slowapi checks if bucket is over quota → 429 if yes (BEFORE auth)
4. If under quota: FastAPI resolves dependencies → `verify_api_key()` runs → 401 if invalid
5. If both pass: route body executes

**Caveat:** The order means an unauthenticated request consumes the `"anonymous"` bucket's quota. That's actually fine for D-04 in-memory storage: at 60/min, even a brute-force attacker would only get 60 attempts per minute, and they'd see 401 (not 429) for each one, which is information-leakage-free.

If we want auth-before-rate-limit, we'd need a custom slowapi middleware or move auth into the `key_func` (which contradicts §C1's "key_func MUST NOT raise"). Keep the simple pattern.

### C4. Exception handler for 429 — registering it preserves CorrelationIdMiddleware scope

[CITED: github.com/laurents/slowapi/docs/examples.md — Register Custom 429 Handler]

```python
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

The default `_rate_limit_exceeded_handler` returns:
- `429 Too Many Requests`
- Body: `{"error":"Rate limit exceeded: ...", "detail":"..."}`
- `Retry-After: <seconds>` header (automatic when `headers_enabled=True`)
- `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` headers (when `headers_enabled=True`)

**Enable headers** so the consumer gets actionable feedback:

```python
limiter = Limiter(key_func=get_api_key, headers_enabled=True)
```

### C5. Middleware ordering — getting correlation_id into 429 responses

`CorrelationIdMiddleware` runs at the ASGI layer. slowapi's `RateLimitExceeded` is an HTTPException handled by FastAPI's exception handler. FastAPI exception handlers DO run inside the middleware stack — meaning `CorrelationIdMiddleware` has already set the `X-Request-ID` response header by the time the 429 body is serialized.

**Order in `main.py`:**

```python
app = FastAPI(lifespan=lifespan, ...)

# slowapi exception handler must be registered BEFORE the route decorators reference limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Middleware order (outermost first — last add_middleware call = first to execute)
app.add_middleware(CorrelationIdMiddleware)  # OUTERMOST — wraps everything
```

When slowapi raises `RateLimitExceeded` inside the route, the exception bubbles up:
1. slowapi's handler converts it to a 429 Response
2. Response unwinds back through CorrelationIdMiddleware
3. CorrelationIdMiddleware adds `X-Request-ID` header to the 429 response

So 429s carry correlation_id natively. **No special action needed.**

### C6. SlowAPIMiddleware vs decorator-only approach

[CITED: github.com/laurents/slowapi llms.txt — Middleware Integration]

`SlowAPIMiddleware` (or `SlowAPIASGIMiddleware`) applies `default_limits` to ALL routes globally. Since we want limits only on `/search`, we do NOT add `SlowAPIMiddleware`. The `@limiter.limit(...)` decorators on `/search` work without the middleware as long as we register the exception handler.

**Final wiring summary:**

```python
# src/artiscrapper/main.py — Phase 3 additions
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from .auth import verify_api_key, get_api_key  # see §C3

limiter = Limiter(key_func=get_api_key, headers_enabled=True)

app = FastAPI(lifespan=lifespan, ...)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(CorrelationIdMiddleware)  # already in Phase 2

@app.post("/search", response_model=SearchResponse)
@limiter.limit("60/minute")           # D-02
@limiter.limit("10000/day")           # D-02
async def search(
    request: Request,
    body: SearchRequest,
    _api_key: str = Depends(verify_api_key),  # D-03 (401 if missing/unknown)
) -> SearchResponse:
    ...
```

### C7. In-memory store reset on restart (D-04 confirmed)

slowapi's default `Limiter(key_func=...)` with NO `storage_uri` uses `MemoryStorage` from `limits.storage.MemoryStorage` [ASSUMED — slowapi defers storage to the `limits` library]. The counters are in-process dicts; container restart loses them. This matches D-04 exactly.

**No extra config needed** beyond the key_func.

---

## D. ChallengeBackoff implementation pattern

**Confidence:** HIGH — patterns established in Phase 2 code; sqlite single-row pattern already used in `cache.py` line 108

### D1. Schema — single-row state table

Inline DDL in `cache.py` next to the existing `query_cache` table:

```sql
CREATE TABLE IF NOT EXISTS challenge_state (
    id              INTEGER PRIMARY KEY CHECK (id = 1),   -- enforce single row
    last_block_at   INTEGER,                              -- unix epoch of most recent block
    retry_count     INTEGER NOT NULL DEFAULT 0,           -- consecutive blocks since last reset
    next_allowed_at INTEGER NOT NULL DEFAULT 0,           -- unix epoch — gate for next Google fetch
    updated_at      INTEGER NOT NULL                       -- forensics
);

-- Seed row exactly once (idempotent)
INSERT OR IGNORE INTO challenge_state (id, last_block_at, retry_count, next_allowed_at, updated_at)
    VALUES (1, NULL, 0, 0, strftime('%s', 'now'));
```

The `CHECK (id = 1)` constraint enforces single-row at the DB layer. The `INSERT OR IGNORE` in init_schema seeds the row idempotently. All reads use `SELECT ... WHERE id=1`; all writes use `INSERT OR REPLACE ... VALUES (1, ...)` — same pattern as `cache.py:108`.

### D2. Module-level cache + asyncio.Lock pattern

Mirroring `llm.py:95-141` (`_RESOLVED_MODEL` + `_RESOLVE_LOCK`):

```python
# src/artiscrapper/challenge_backoff.py — new module
import asyncio
import time
from dataclasses import dataclass

import aiosqlite

_BACKOFF_CAP_S = 3600  # 1 hour — D-06
_BASE_S = 60           # D-06
_RESET_AFTER_S = 3600  # D-07: reset trigger = first success ≥1h after last_block_at


@dataclass
class _State:
    last_block_at: int | None
    retry_count: int
    next_allowed_at: int


_STATE: _State | None = None
_LOCK = asyncio.Lock()


async def _load(cache: aiosqlite.Connection) -> _State:
    global _STATE
    if _STATE is not None:
        return _STATE
    async with _LOCK:
        if _STATE is not None:
            return _STATE
        cur = await cache.execute(
            "SELECT last_block_at, retry_count, next_allowed_at FROM challenge_state WHERE id=1"
        )
        row = await cur.fetchone()
        if row is None:
            _STATE = _State(last_block_at=None, retry_count=0, next_allowed_at=0)
        else:
            _STATE = _State(last_block_at=row[0], retry_count=row[1], next_allowed_at=row[2])
        return _STATE


async def _persist(cache: aiosqlite.Connection) -> None:
    """Caller holds _LOCK."""
    assert _STATE is not None
    now = int(time.time())
    await cache.execute(
        "INSERT OR REPLACE INTO challenge_state (id, last_block_at, retry_count, next_allowed_at, updated_at) "
        "VALUES (1, ?, ?, ?, ?)",
        (_STATE.last_block_at, _STATE.retry_count, _STATE.next_allowed_at, now),
    )
    await cache.commit()


async def check_gate(cache: aiosqlite.Connection) -> tuple[bool, int]:
    """
    Returns (allowed, retry_after_seconds).
    Called BEFORE every Google fetch in fetch_serp.
    """
    state = await _load(cache)
    now = int(time.time())
    if state.next_allowed_at > now:
        return False, state.next_allowed_at - now
    return True, 0


async def record_block(cache: aiosqlite.Connection) -> None:
    """
    Called when _detect_block() fires. Computes exponential backoff and persists.
    D-06: min(60 * 2^retries, 3600).
    """
    async with _LOCK:
        state = await _load(cache)
        now = int(time.time())
        state.retry_count += 1
        wait_s = min(_BASE_S * (2 ** (state.retry_count - 1)), _BACKOFF_CAP_S)
        state.last_block_at = now
        state.next_allowed_at = now + wait_s
        await _persist(cache)


async def record_success(cache: aiosqlite.Connection) -> None:
    """
    Called after a successful Google fetch (no block detected).
    D-07: reset retry_count to 0 if this success is >=1h after last_block_at.
    Otherwise no-op — recent success doesn't clear an active backoff.
    """
    async with _LOCK:
        state = await _load(cache)
        if state.last_block_at is None:
            return  # never blocked, nothing to reset
        now = int(time.time())
        if now - state.last_block_at >= _RESET_AFTER_S:
            state.retry_count = 0
            state.next_allowed_at = 0
            state.last_block_at = None
            await _persist(cache)
```

**Why module-level state + sqlite both:** The in-memory `_STATE` avoids a sqlite query per request (fast hot path). The sqlite write happens on state CHANGES only (block detected or success-resets-counter). At 500-2000 q/day, that's ≤ 2000 sqlite writes/day to a 1-row table — trivial.

**Why asyncio.Lock not threading.Lock:** uvicorn is single-process single-worker; concurrency is asyncio coroutines, not threads. `asyncio.Lock` is the right primitive.

### D3. Integration into the search route

```python
# src/artiscrapper/main.py — /search route, after cache lookup, before Google fetch
from .challenge_backoff import check_gate, record_block, record_success

# [2] BEFORE Google fetch — gate check
allowed, retry_after = await check_gate(request.app.state.cache)
if not allowed:
    log.warning("challenge_backoff_active", retry_after=retry_after)
    return Response(
        status_code=503,
        content=SearchResponse(
            query=body.query,
            results=[],
            metadata=Metadata(
                elapsed_ms=int((time.time() - t_start) * 1000),
                cache_hit=False,
                block_detected=True,
            ),
        ).model_dump_json(),
        media_type="application/json",
        headers={"Retry-After": str(retry_after)},
    )

# [2] Google fetch (existing code) ...
# [3] AFTER fetch — record outcome
if block_a or block_b:
    await record_block(request.app.state.cache)
    # ... existing 503 return logic
else:
    await record_success(request.app.state.cache)  # D-07 reset trigger
```

**Why `Response(status_code=503)` not `HTTPException`:** FastAPI's `HTTPException` doesn't directly accept `headers` in a JSON-serializing path that preserves the response model. The explicit `Response` with `media_type="application/json"` gives full control of headers (Retry-After) AND the body shape.

[CITED: FastAPI docs — Custom response with headers; Response class accepts `headers` parameter]

### D4. Lifespan integration

In `main.py` lifespan, add schema init for `challenge_state` AFTER the existing `init_schema(app.state.cache)` call. (The `init_schema` in `cache.py` would be extended to include the new DDL.)

---

## E. Degraded-mode synthetic test

**Confidence:** HIGH — the labelled.jsonl fixture from Phase 1 has exactly the right shape

### E1. Why "kill subprocess" is the wrong primitive

CONTEXT.md §research_targets E suggests two approaches:
1. `pytest-asyncio + subprocess.Popen + kill()` — kill local-llms-router mid-test
2. Mock at the LLM client boundary with `respx`

**Approach 1 is wrong for this repo** because:
- pytest runs in an isolated test environment without local-llms-router available
- The router is a separate service; killing it mid-test would require either docker-in-docker or a local mock router subprocess
- The failure mode it simulates (router down) is functionally identical to what `respx` mocks at the httpx boundary

**Approach 2 (respx) is correct:**
- `respx==0.23.1` is already in dev dependencies (`pyproject.toml` line 32)
- Test files `test_llm.py` (lines 111-180) already use `respx.mock` for the LLM endpoint
- It produces a deterministic, fast (no subprocess), isolated test

### E2. The fixture is the input

`tests/fixtures/llm/labelled.jsonl` (50 records, verified `wc -l` 2026-06-03) has this shape:

```json
{
  "id": "serp01-card01",
  "candidate": {"title": "...", "url": "...", "snippet": "...", "price_in_card": "$32.999"},
  "expected_is_product": true,
  ...
}
```

The `.candidate` dict is the exact shape that `should_keep` and the degraded-mode branch of `search()` expect. Feeding all 50 candidates into the search pipeline with the LLM router mocked-down should produce ≥5 useful results from the heuristic-only path.

### E3. Test outline

```python
# tests/integration/test_degraded_mode.py
import json
import pathlib
import pytest
import respx
from httpx import Response

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "llm" / "labelled.jsonl"


@pytest.mark.integration
async def test_llm_down_degraded_mode_keeps_useful_results(monkeypatch):
    """
    LLM-06 hardening: when the router returns 503 for every call, the search
    pipeline falls back to (junk-blocklist + price-in-card) and STILL returns
    >=5 useful results from the Phase 1 labelled.jsonl set.
    """
    # Load 50 labelled SERP candidates from Phase 1 spike
    candidates = []
    with FIXTURES.open() as f:
        for line in f:
            row = json.loads(line)
            candidates.append(row["candidate"])

    # Mock the router as completely down — every POST returns 503
    with respx.mock:
        respx.post("http://127.0.0.1:3210/v1/chat/completions").mock(
            return_value=Response(503, json={"error": "router down"})
        )
        respx.get("http://127.0.0.1:3210/healthz").mock(
            return_value=Response(503, json={"error": "router down"})
        )

        from src.artiscrapper.llm import curate_candidates, router_health_check
        # Router HEAD should fail — that's the degraded-mode trigger
        assert await router_health_check("http://127.0.0.1:3210", "test-bearer") is False

        # curate_candidates would NOT be called in the degraded branch;
        # the route handler short-circuits to the heuristic path.
        # Verify the heuristic path: filter by has_price OR price_in_card
        survivors = [c for c in candidates if c.get("price_in_card") or c.get("price") or c.get("has_price")]
        assert len(survivors) >= 5, (
            f"Degraded mode should retain >=5 useful results from Phase 1 labelled set; "
            f"got {len(survivors)}/{len(candidates)}"
        )
```

**A second test for the partial-degradation case** (router returns 503 sporadically, >50% fall back, llm_degraded=True surfaces):

```python
@pytest.mark.integration
async def test_llm_partial_failure_surfaces_degraded_flag():
    """LLM-05: when >50% of LLM calls fall back, metadata.llm_degraded=True."""
    # respx returns 503 for first 30 calls, 200 with fallback verdict for last 20
    ...
```

### E4. The router-health-check is the actual degraded-mode trigger

Reading `main.py:366-370`:

```python
router_healthy = await router_health_check(
    settings.LLM_ROUTER_URL,
    settings.LLM_ROUTER_BEARER_TOKEN,
)
if router_healthy and all_candidates:
    survivors, llm_filtered_out, llm_degraded = await curate_candidates(...)
else:
    if not router_healthy:
        llm_degraded = True
        ...
    survivors = [c for c in all_candidates if c.get("has_price")]
```

So the degraded-mode branch is gated on `router_health_check` returning False, which happens when `HEAD /healthz` raises any exception or returns ≥500. **respx-mocking the healthz endpoint** is the single intervention point that flips the route into degraded mode.

---

## F. Integration-suite scaffolding

**Confidence:** HIGH — pytest infrastructure already in place

### F1. Directory layout

```
tests/
├── conftest.py                    # existing — Phase 2
├── test_parser.py                 # existing — Phase 2 unit tests
├── test_llm.py                    # existing — Phase 2 unit tests
├── test_visit.py                  # existing — Phase 2 unit tests
├── test_cache.py                  # existing — Phase 2 unit tests
├── test_health.py                 # existing — Phase 2 unit tests
├── test_e2e.py                    # existing — Phase 2 e2e tests
├── test_footguns.py               # existing — Phase 2 invariants
└── integration/                   # NEW — Phase 3
    ├── __init__.py
    ├── conftest.py                # shared fixtures (load_labelled_jsonl, load_catalog_fixtures)
    ├── test_catalog_extraction.py # >85% catalog price extraction (validates D12)
    ├── test_degraded_mode.py      # LLM-down survives ≥5 results
    ├── test_challenge_backoff.py  # /sorry/ fixture → 503+Retry-After
    └── test_metrics_endpoint.py   # /metrics smoke test (D-13)
```

### F2. pytest marker convention

The existing `pyproject.toml` already defines `markers = ["e2e: live network tests (skipped by default)"]`. Extend it:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "e2e: live network tests (skipped by default)",
    "integration: fixture-replay integration tests (run with -m integration)",
]
testpaths = ["tests"]
pythonpath = ["."]
```

**Default `pytest` invocation** runs unit + integration tests (since `tests/integration/` is under `testpaths`). To run ONLY integration: `pytest -m integration`. To EXCLUDE integration from default: `pytest -m 'not integration'`.

**Recommendation:** Keep integration tests in the default `pytest` run. They're in-process (no Docker, no live network — they replay captured fixtures), so they're fast and deterministic. The `@pytest.mark.integration` marker exists for selective filtering, not for default-exclusion.

### F3. Catalog-fixture replay test (>85% price extraction — validates D12)

```python
# tests/integration/test_catalog_extraction.py
import pathlib
import pytest
from src.artiscrapper.visit import extract_product

CATALOG_DIR = pathlib.Path(__file__).parent.parent / "fixtures" / "catalog"


@pytest.mark.integration
def test_catalog_price_extraction_rate_above_85_percent():
    """
    D12 production validation: ≥85% of Phase 1 catalog fixtures yield a price
    via extract_product() (in-process, no HTTP).
    SPIKE.md §Visit empirically measured 9/10 jsonld-sufficient — this test
    pins that bar in production.
    """
    fixture_files = []
    for host_dir in CATALOG_DIR.iterdir():
        if not host_dir.is_dir():
            continue
        # Each host_dir has one HTML PDP fixture (per Phase 1 spike layout)
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
        f"D12 acceptance is ≥85% (Phase 1 measured 9/10). "
        f"Details: {details}"
    )
```

**Why in-process not HTTP-mocked:** `extract_product(html)` is a pure function (HTMLParser + selectolax). No HTTP layer needed. This is structurally simpler than calling `visit_candidates()` with `aiohttp` mocked.

### F4. Cascade-exhausted regression test (D4)

ROADMAP §Phase 3 success-criterion 6 mentions "asserts the D4 cascade alert fires on a deliberately-broken fixture". Provide a synthetic minimal SERP that defeats all 5 organic selectors:

```python
@pytest.mark.integration
def test_d4_cascade_exhausted_fires_on_broken_serp(monkeypatch, caplog):
    """D4: When all ORGANIC_SELECTORS miss, parse_cascade_exhausted warning fires."""
    # A SERP fragment with no div.tF2Cxc, no div.MjjYud, no div.g, no sokoban, no snc
    broken = "<html><body><div class='unknown-google-selector'><h3>Something</h3></div></body></html>"
    # Capture structlog warnings...
```

This is already covered by `tests/test_parser.py::test_cascade_exhausted_alert` (line 23) but the integration variant verifies the end-to-end search route behavior, not just the parser unit.

---

## G. Project-specific landmines + smoke tests

### G1. The `feedback_empirical_retest_after_default_changes` landmine

> Phase 2 LLM_MODEL default was bumped but didn't reach the hot path because of shadowing between settings/contract/route.

**The layers a Phase 3 default has to traverse:**

```
.env  →  Settings (pydantic-settings)  →  module-level singleton `settings`  →  function arg default  →  hot path
```

Phase 3 adds these new defaults to `config.py`:
- `API_KEYS: str = ""` (D-01)
- `API_RATE_PER_MINUTE: int = 60` (D-02)
- `API_RATE_PER_DAY: int = 10000` (D-02)
- `SENTRY_DSN: str = ""` (D-14)
- `CHALLENGE_BACKOFF_BASE_S: int = 60` (D-06; though we recommend hardcoding to enforce ROADMAP-lock)
- `CHALLENGE_BACKOFF_CAP_S: int = 3600` (D-06)
- `CHALLENGE_RESET_AFTER_S: int = 3600` (D-07)

**The shadowing pattern that caused Phase 2's bug:** A default in `config.py` says `LLM_MODEL = "X"`, but the LLM call site reads `model = candidate.get("model") or settings.LLM_MODEL` — if upstream code passes a stale `candidate["model"]`, the settings default is silently shadowed. The same happens if a function signature says `def fn(model: str = "Y")` — Y wins over settings.LLM_MODEL because the function-level default is evaluated at call time.

**Smoke-test pattern that catches it:** Boot the container and grep one log line:

```bash
# In CI / smoke test after `compose up`:
docker compose logs artiscrapper | grep -E "(api_keys_loaded|rate_limit_init|sentry_init_skipped|sentry_init_done|challenge_backoff_init)" | head -10
```

Each Phase 3 init point emits a log line declaring the values that reached the hot path:

```python
# main.py lifespan — Phase 3 additions
log.info(
    "api_keys_loaded",
    count=len(API_KEYS),
    rate_per_min=settings.API_RATE_PER_MINUTE,
    rate_per_day=settings.API_RATE_PER_DAY,
)
log.info(
    "sentry_init_skipped" if not settings.SENTRY_DSN else "sentry_init_done",
    traces_sample_rate=0.1 if settings.SENTRY_DSN else None,
)
log.info(
    "challenge_backoff_init",
    base_s=_BASE_S,
    cap_s=_BACKOFF_CAP_S,
    reset_after_s=_RESET_AFTER_S,
)
```

**Then the empirical retest:** After any default change, run `curl /search` once and assert the matching log line has the value you expect. This is the pattern Phase 2 missed.

### G2. The `feedback_compose_build_recreate` landmine

> docker `up -d --build` can take 25min and miss recreate.

**Document in every CI/test recipe:**

```bash
# WRONG — can take 25min and NOT recreate
docker compose up -d --build

# RIGHT — explicit two-step
docker compose build
docker compose up -d --force-recreate
```

Every plan task that involves "rebuild and restart the container" MUST spell out the two commands. The combined form is a known foot-gun.

### G3. Sentry must NOT pull uvloop (D6 invariant)

D6 says uvloop is BANNED. sentry-sdk 2.x does NOT pull uvloop as a dependency [VERIFIED: sentry-sdk PyPI metadata shows no uvloop in install_requires; checked 2026-06-03 via pip metadata]. The existing `test_footguns.py::test_no_uvloop_installed` + `test_uvloop_absent_from_lock` already pin this — they will catch any transitive sentry pull.

**Recommendation:** Add a Phase 3 footgun test:

```python
def test_sentry_does_not_pull_uvloop():
    """D6 + Phase 3: sentry-sdk must NOT transitively install uvloop."""
    result = subprocess.run(
        ["grep", "-rE", "uvloop", "uv.lock"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0, f"uvloop appeared in uv.lock — check sentry-sdk version: {result.stdout}"
```

This is functionally a re-assertion of the existing test, but tagged with the Phase 3 hardening intent.

### G4. The `/sorry/` fixture

CONTEXT.md D-20: synthetic challenge HTML must come from real /sorry/ if Phase 1 captured one, else a minimal stand-in.

**Verify Phase 1 didn't capture a /sorry/ page.** Phase 1's SPIKE.md §Browser says: "Markers hit: none (all 10 fixtures clean — no `id='L2AGLb'`, no `/sorry/index`, no `g-recaptcha`)." So NO real /sorry/ fixture exists.

**Recommendation:** Build a minimal stand-in fixture `tests/fixtures/serp/sorry.html`:

```html
<!doctype html>
<html><head><title>https://www.google.com/sorry/index</title></head>
<body><div id="recaptcha"></div>
<p>We're sorry... but your computer or network may be sending automated queries.</p>
</body></html>
```

This will trigger `_detect_block()` in `search.py` (BROWSER-05 markers: title contains "sorry/index", body contains "detected unusual traffic"–adjacent phrasing). Pin it with a test that asserts `_detect_block(sorry_html) is not None`.

---

## Standard Stack

### New dependencies (Phase 3)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `prometheus-client` | 0.25.0 | Counter/Histogram + ASGI mount for /metrics | Official Prometheus Python client; canonical for FastAPI integration |
| `sentry-sdk` | 2.61.1 | Uncaught exception capture + tracing | Official Sentry SDK; auto-detects FastAPI in 2.x |
| `slowapi` | 0.1.9 | Per-key rate-limit on /search | The de-facto FastAPI rate-limiter; adapted from flask-limiter |

**Verification:** All three confirmed live on PyPI via `pip index versions` 2026-06-03. slopcheck [OK] for all three (slowapi clean; sentry-sdk and prometheus-client both flagged for naming pattern but confirmed established).

### Installation

```bash
uv add prometheus-client==0.25.0 sentry-sdk==2.61.1 slowapi==0.1.9
uv sync --locked
```

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `prometheus-client` | `starlette-prometheus` | Higher-level FastAPI wrapper; adds default-instrumented HTTP metrics we don't need (per D-11, the artiscrapper_* families are the canonical ones); + dependency |
| `sentry-sdk` FastAPI auto-detect | Manual `FastApiIntegration([])` instantiation | Explicit form only matters for customizing options (transaction_style, failed_request_status_codes); we don't customize |
| `slowapi` | `fastapi-limiter` (Redis-only) | fastapi-limiter requires Redis; D-04 says in-memory; would violate single-container architecture |
| Custom rate-limit middleware | Hand-roll a per-key token bucket on top of `asyncio.Lock` | The 60/min + 10000/day stacked limits are slowapi-native; rolling it ourselves is more code and worse-tested |
| `prometheus-fastapi-instrumentator` | High-level wrapper that adds RED-method metrics | Per D-11 we want to bridge existing metrics, not replace them; this lib doesn't compose cleanly with the existing dataclass |

---

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| prometheus-client | PyPI | 9+ years (first release 2015) | >100M/wk per PyPI | github.com/prometheus/client_python | [OK] (LLM-bait naming flagged, but confirmed established) | Approved |
| sentry-sdk | PyPI | 9+ years (since 2018 as `sentry-sdk`; `raven` before) | >50M/wk per PyPI | github.com/getsentry/sentry-python | [OK] (LLM-bait naming flagged, but confirmed established) | Approved |
| slowapi | PyPI | 6+ years (first release 2020) | ~500k/wk per PyPI | github.com/laurents/slowapi | [OK] (clean) | Approved |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

All three are widely-deployed, actively-maintained packages with verified source repos. The `-sdk` and `-client` naming patterns trigger slopcheck heuristics but the underlying packages are unambiguously legitimate.

---

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│  External traffic (consumer with X-API-Key header)                      │
│  Prometheus scraper (no auth — D-10)                                    │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  CorrelationIdMiddleware (outermost — adds X-Request-ID)                │
└─────────────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼────────────────────────┐
              │               │                        │
              ▼               ▼                        ▼
┌──────────────────┐ ┌────────────────────┐ ┌──────────────────────────┐
│  /metrics        │ │  /search            │ │  /health, /health/deep   │
│  (mounted ASGI;  │ │  (limiter.limit +   │ │  (unprotected)            │
│   no middleware) │ │   verify_api_key)   │ │                           │
└──────────────────┘ └────────────────────┘ └──────────────────────────┘
        │                     │                        │
        ▼                     ▼                        │
┌──────────────────┐ ┌────────────────────────────┐    │
│  prometheus_     │ │  D-03 verify_api_key (401) │    │
│  client.         │ │       ↓ if pass            │    │
│  generate_latest │ │  slowapi quota check (429) │    │
│  (REGISTRY)      │ │       ↓ if pass            │    │
└──────────────────┘ │  challenge_backoff.        │    │
                     │  check_gate (503+Retry-    │    │
                     │  After) — D-09             │    │
                     │       ↓ if pass            │    │
                     │  existing 10-step pipeline │    │
                     │  (cache → fetch → parse →  │    │
                     │   LLM → visit → rerank)    │    │
                     │       ↓                    │    │
                     │  on block: record_block()  │    │
                     │  on success: record_       │    │
                     │  success() (D-07 reset)    │    │
                     └────────────────────────────┘    │
                              │                        │
                              ▼                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Histogram.time() bracketing on search/llm/visit hot paths              │
│  Counter increments via inc_llm_fallback / inc_visit_failed wrappers    │
│  Uncaught exception → sentry-sdk auto-capture                           │
│  Every log call → add_correlation_id processor → also sets Sentry tag   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure (Phase 3 additions)

```
src/artiscrapper/
├── main.py              # EXTENDED — add /metrics mount, limiter, exception handler
├── metrics.py           # EXTENDED — add Prometheus Counter/Histogram bridges
├── logging_setup.py     # EXTENDED — add _init_sentry() + Sentry tag injection
├── config.py            # EXTENDED — add API_KEYS, API_RATE_PER_MINUTE/DAY, SENTRY_DSN
├── auth.py              # NEW — verify_api_key dependency + get_api_key key_func
├── challenge_backoff.py # NEW — _STATE + _LOCK + check_gate/record_block/record_success
├── cache.py             # EXTENDED — add challenge_state DDL to init_schema
└── search.py            # UNCHANGED — _detect_block already exposes what we need

tests/
├── integration/         # NEW
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_catalog_extraction.py
│   ├── test_degraded_mode.py
│   ├── test_challenge_backoff.py
│   └── test_metrics_endpoint.py
├── test_footguns.py     # EXTENDED — add Sentry+uvloop check, /metrics no-auth check
└── fixtures/serp/sorry.html  # NEW — synthetic /sorry/ for backoff test (D-20)
```

### Pattern 1: Prometheus Counter bridge (D-11)

**What:** Bridge the existing inline `Metrics` dataclass to prometheus_client Counters via a thin wrapper.
**When to use:** Anywhere existing code increments the dataclass counter.

```python
# Source: metrics.py — Phase 3 extension (per D-11)
def inc_llm_fallback(reason: str) -> None:
    metrics.llm_fallback_total[reason] += 1               # legacy dataclass
    llm_fallback_counter.labels(reason=reason).inc()      # prometheus
```

### Pattern 2: Histogram.time() context manager for async functions

**What:** Use `with hist.time():` inside async functions; never `@hist.time()` as a decorator on `async def`.

```python
# Source: prometheus-client docs (Context7) + community lore on async timing pitfall
async def search(...):
    with search_elapsed.time():
        # all async work inside this block is timed correctly
        ...

async def visit_one(c):
    async with global_sem, host_sems[host]:
        with visit_elapsed.labels(stage="fetch").time():
            resp = await client.get(url)
        with visit_elapsed.labels(stage="extract").time():
            extracted = extract_product(resp.text)
```

### Pattern 3: Stacked slowapi limits

**What:** Two `@limiter.limit(...)` decorators on the same route to enforce both per-minute and per-day quotas.

```python
# Source: github.com/laurents/slowapi llms.txt
@app.post("/search")
@limiter.limit("60/minute")
@limiter.limit("10000/day")
async def search(request: Request, body: SearchRequest, _api_key: str = Depends(verify_api_key)):
    ...
```

### Pattern 4: Sentry tag injection via existing structlog processor

**What:** Extend `add_correlation_id` to dual-write — into structlog event_dict AND Sentry scope tag.

```python
# Source: docs.sentry.io/platforms/python/integrations/asgi (set_tag in middleware-level scope)
def add_correlation_id(_logger, _method, event_dict):
    if cid := correlation_id.get():
        event_dict["correlation_id"] = cid
        try:
            sentry_sdk.get_current_scope().set_tag("correlation_id", cid)
        except Exception:
            pass
    return event_dict
```

### Pattern 5: ChallengeBackoff sqlite single-row state

**What:** `CHECK (id=1)` constraint enforces single row; `INSERT OR REPLACE` upserts; module-level in-memory cache + asyncio.Lock avoids per-request sqlite reads.

(See §D2 for full code listing.)

### Anti-Patterns to Avoid

- **`@histogram.time()` decorator on `async def` functions** — measures coroutine creation, not awaited completion. Always use `with histogram.time():` inside the async function body.
- **Raising from `slowapi.key_func`** — slowapi treats key_func exceptions as 500. Use a separate FastAPI dependency for auth that raises HTTPException(401).
- **`docker compose up -d --build`** — can take 25min and miss recreate. Use `docker compose build` + `docker compose up -d --force-recreate` as separate commands. (Phase 2 memory: `feedback_compose_build_recreate`)
- **Bumping a Phase 3 default in `config.py` without verifying it reaches the hot path** — Phase 2 had a settings/contract/route shadowing bug. Always emit a log line that declares the loaded value (e.g., `log.info("api_keys_loaded", rate_per_min=...)`) and grep for it after a restart. (Phase 2 memory: `feedback_empirical_retest_after_default_changes`)
- **Initializing Sentry inside `lifespan()`** — misses boot exceptions before lifespan runs. Init at module-import time in `logging_setup.py`, gated by `SENTRY_DSN` empty-string check.
- **Mounting `/metrics` as a regular FastAPI route with `@app.get("/metrics")` and adding the limiter accidentally** — D-10 says no auth, no rate-limit. The `app.mount("/metrics", make_asgi_app())` pattern bypasses ALL FastAPI middleware including slowapi.
- **Per-host ChallengeBackoff scope** — explicitly deferred (CONTEXT.md). Google blocks are IP-level; tracking per-URL adds state without changing recovery decisions.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Prometheus metric serialization | Custom Counter + text formatter | `prometheus-client` | The text format has exemplars, OpenMetrics escaping, and `# HELP` / `# TYPE` headers — get them wrong and Prometheus drops your scrape |
| Rate-limit token bucket | Hand-rolled `dict + asyncio.Lock` | `slowapi` | Stacked multi-window limits (60/min + 10000/day) need careful accounting; slowapi handles fixed/sliding windows |
| Sentry HTTP transport | Custom exception → POST to Sentry API | `sentry-sdk` | Sentry's wire protocol changes; SDK handles compression, batching, transport failure recovery |
| FastAPI auto-instrumentation | Manual ASGI middleware around every route | sentry-sdk's auto-detected `FastApiIntegration` | Catches exceptions WITHOUT needing a try/except on every route handler |
| Correlation ID extraction | Custom UUID generation + header parsing | `asgi-correlation-id` (already in Phase 2) | Handles X-Request-ID propagation + contextvar binding |
| /sorry/ HTML detection | Regex on raw bytes | Existing `_detect_block()` (search.py) | Already Phase 2-implemented; ChallengeBackoff just consumes its return value |
| Exponential backoff math | Open-coded `time.sleep(2**retries)` | Module-level `_BASE_S * (2 ** (retries-1))` capped at `_BACKOFF_CAP_S` | Plain math is fine — the foot-gun is forgetting the cap and the persistence layer (D-08) |
| Single-row sqlite UPSERT | `SELECT then UPDATE/INSERT branch` | `INSERT OR REPLACE` with `CHECK(id=1)` | Atomic; idempotent; same pattern as existing `cache.py` |
| Process-singleton state in asyncio | Threading primitives | Module-level var + `asyncio.Lock` | Phase 2 already uses this pattern (`_RESOLVED_MODEL` in `llm.py`); be consistent |
| HTTP client for tests | requests + mocks | `respx` (already in dev deps) | Mocks httpx at the transport layer; works with the existing AsyncClient code paths |

**Key insight:** Phase 3 is almost entirely a wiring exercise. Every piece of behavior (exponential backoff, rate-limit math, exception capture) has a library that does it correctly. The work is choosing the right integration points and pinning the invariants with tests — NOT writing new algorithms.

---

## Runtime State Inventory

> This phase is feature additions, not a rename/refactor. Most categories are empty — listing them for completeness per the protocol.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no renames or schema migrations. New table `challenge_state` is created idempotently via `init_schema()` | None — fresh CREATE TABLE IF NOT EXISTS |
| Live service config | None — no external services configured outside the container | None |
| OS-registered state | None — no Windows Task Scheduler / launchd / systemd interaction | None |
| Secrets/env vars | NEW env vars introduced: `API_KEYS`, `SENTRY_DSN`. Documented in dev-box `.env` + production compose file. `LLM_ROUTER_BEARER_TOKEN` (Phase 2) unchanged. | Update `.env.example` (if exists) + production deploy docs to declare new env vars |
| Build artifacts / installed packages | `prometheus-client`, `sentry-sdk`, `slowapi` added to `pyproject.toml` + `uv.lock`. Phase 2's `cloakhq/cloakbrowser:0.3.31` Docker base unchanged. | After `uv add ...` run `uv sync --locked`, then `docker compose build` (full) before `docker compose up -d --force-recreate` (per Phase 2 memory: `feedback_compose_build_recreate`) |

**Nothing found in category:** Stated explicitly above for each. The new env vars and new dependency lines are the only state surfaces touched.

---

## Common Pitfalls

### Pitfall 1: Histogram.time() decorator on async function

**What goes wrong:** `@histogram.time()` on `async def fn(...)` measures wall-clock from the call to `fn()` to the time the coroutine OBJECT is returned (microseconds), not until the awaited result is ready.
**Why it happens:** `prometheus_client.Histogram.time()` returns a sync context manager via `Timer` class — it has `__enter__`/`__exit__` but no `__aenter__`/`__aexit__`. The decorator form wraps `__call__`, which on an async function returns the coroutine immediately.
**How to avoid:** Always use the context-manager form INSIDE the async function: `with histogram.time(): ...`. Never decorate.
**Warning signs:** P50 latencies showing as microseconds when real latency is seconds. The `_count` increments correctly but `_sum` is suspiciously low.

### Pitfall 2: Sentry init inside lifespan misses boot errors

**What goes wrong:** Crashes during cloak browser startup (e.g., missing libnspr4) never reach Sentry because lifespan-init Sentry hasn't fired yet.
**Why it happens:** uvicorn calls `lifespan()` AFTER the FastAPI app object is constructed; constructing the app + importing dependencies can already raise.
**How to avoid:** Call `_init_sentry()` at the bottom of `logging_setup.py` (module-import time), gated by `if settings.SENTRY_DSN`. Then `main.py`'s import of `configure_logging` transitively triggers Sentry init before lifespan.
**Warning signs:** A container that crashes on boot in production but you can't find the crash in Sentry; only the log line in `docker compose logs` shows it.

### Pitfall 3: slowapi key_func raising → 500 not 401

**What goes wrong:** A clever-looking implementation puts auth validation inside `key_func`, raising `HTTPException(401)` on missing key. slowapi treats key_func exceptions as fatal and returns 500.
**Why it happens:** key_func is called inside slowapi's middleware path, not inside FastAPI's dependency-resolution chain. FastAPI's exception handlers don't catch what happens inside another middleware.
**How to avoid:** Auth via `Depends(verify_api_key)`; rate-limit via `key_func` reading `request.headers.get("X-API-Key", "anonymous")`. Two separate concerns, two separate mechanisms.
**Warning signs:** Missing-header requests return 500 instead of 401; structured logs show the exception came from slowapi internals.

### Pitfall 4: Counter cardinality explosion on `host` label

**What goes wrong:** `visit_failed_counter.labels(host=urlparse(url).netloc).inc()` produces unbounded labels — every distinct host (including subdomains like `m.falabella.com.ar`, `www.falabella.com.ar`, `falabella.com.ar`) is a separate time series. Prometheus chokes when label cardinality exceeds ~thousands.
**Why it happens:** Real-world URLs have hostname variance that doesn't correspond to "different stores".
**How to avoid:** Normalize via `tldextract` (already in Phase 2 deps) to TLD+1: `f"{ext.domain}.{ext.suffix}"`. Cap label cardinality at ~50 hosts.
**Warning signs:** Prometheus scrape duration creeps up; `/metrics` response size > 1MB; `prometheus_client` registry consumes increasing memory.

### Pitfall 5: ChallengeBackoff sqlite singleton skipping in-memory cache

**What goes wrong:** Every `check_gate()` call hits sqlite. At 500-2000 q/day this is fine, but it adds 0.5-2ms per request for no value — the state changes rarely.
**Why it happens:** Forgetting the module-level `_STATE` + `_LOCK` pattern from `llm.py:95`. Default "just query the db" feels safer but isn't necessary.
**How to avoid:** Load state once at first call (or in lifespan startup), keep in memory, only persist on STATE changes (record_block, record_success). See §D2.
**Warning signs:** sqlite query count grows linearly with request count; `_search` p50 latency floor creeps up after Phase 3 deploy.

### Pitfall 6: Phase 2 `feedback_empirical_retest_after_default_changes`

**What goes wrong:** Bumping `API_RATE_PER_MINUTE=60` in `config.py` doesn't reach `@limiter.limit("60/minute")` because the decorator string is hardcoded, not interpolated from settings.
**Why it happens:** Function-level defaults and decorator strings are evaluated at module-import time using whatever was in scope then. If `config.py` is patched but the running container isn't rebuilt+recreated, the running process has the old values.
**How to avoid:** Emit a log line at lifespan startup: `log.info("rate_limit_init", per_min=settings.API_RATE_PER_MINUTE, per_day=settings.API_RATE_PER_DAY)`. After any default change: `docker compose build && docker compose up -d --force-recreate`, then `docker compose logs | grep rate_limit_init` and assert the values.
**Warning signs:** Changing a config value produces no observable behavior change. Tests pass but runtime is unchanged.

### Pitfall 7: `up -d --build` foot-gun

**What goes wrong:** `docker compose up -d --build` can take 25+ minutes and not actually recreate the container after rebuild. The old container keeps running with the old image.
**Why it happens:** Docker compose's combined build+up semantics are platform-dependent and inconsistent. (Phase 2 memory: `feedback_compose_build_recreate`)
**How to avoid:** Always two-step: `docker compose build` then `docker compose up -d --force-recreate`. Document this in every test/deploy plan.
**Warning signs:** `docker compose up` taking >10min; new code changes not reflected in container behavior despite a "successful" build.

### Pitfall 8: Sentry default-PII leakage

**What goes wrong:** Sentry events include request bodies, headers, user IDs by default. OBS-05 says NEVER log scraped content.
**Why it happens:** `send_default_pii=True` is sentry-sdk's default for "user-friendly debugging".
**How to avoid:** Set `send_default_pii=False` in `sentry_sdk.init(...)`. Also consider `before_send` hook to scrub the query string from URL paths.
**Warning signs:** Sentry events showing snippet/title content; query strings in transaction names.

### Pitfall 9: prometheus_client default collectors leaking Python VM metrics

**What goes wrong:** `/metrics` returns 300+ lines of `python_gc_*`, `process_*`, `python_info` — confusing for the consumer, bloats scrape payload.
**Why it happens:** prometheus_client registers `PROCESS_COLLECTOR`, `GC_COLLECTOR`, `PLATFORM_COLLECTOR` at import time.
**How to avoid:** Unregister them at the top of `metrics.py` (see §A2 code). D-13's `^artiscrapper_` grep is unaffected, but unregistering keeps the surface clean.
**Warning signs:** `/metrics` response > 50KB; consumer reports "I see python_gc_collections_total but I don't know what artiscrapper exposes".

### Pitfall 10: Not seeding label values produces gappy metrics

**What goes wrong:** A Counter with `labels=["reason"]` only shows time series for labels that have been incremented. If "timeout" never fired, it doesn't appear in `/metrics`. Prometheus alerting on absence is brittle.
**Why it happens:** Counter time series are lazy — they spring into existence on first `.labels(x).inc()`.
**How to avoid:** At module load, touch every expected label value: `for r in ("timeout", "malformed", "overload", ...): llm_fallback_counter.labels(reason=r)`. (No `.inc()` — just `.labels()` creates the time series with value 0.)
**Warning signs:** Grafana queries returning "no data" for known-valid label values; alerts on `rate(...) > 0` working but `absent(...)` not firing.

---

## Code Examples

Verified patterns from official sources.

### Mount /metrics endpoint in FastAPI

```python
# Source: github.com/prometheus/client_python/docs/content/exporting/http/fastapi-gunicorn.md
from fastapi import FastAPI
from prometheus_client import make_asgi_app

app = FastAPI()
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
```

### Disable default Python-VM collectors

```python
# Source: github.com/prometheus/client_python/docs/content/collector/_index.md
import prometheus_client

prometheus_client.REGISTRY.unregister(prometheus_client.GC_COLLECTOR)
prometheus_client.REGISTRY.unregister(prometheus_client.PLATFORM_COLLECTOR)
prometheus_client.REGISTRY.unregister(prometheus_client.PROCESS_COLLECTOR)
```

### Custom Histogram buckets for latency workload

```python
# Source: github.com/prometheus/client_python/docs/content/instrumenting/histogram.md
from prometheus_client import Histogram

REQUEST_LATENCY = Histogram(
    'request_duration_seconds',
    'HTTP request latency',
    labelnames=['endpoint'],
    buckets=[.01, .05, .1, .25, .5, 1, 2.5, 5],
)
```

### slowapi key_func + stacked limits + auth dependency

```python
# Source: github.com/laurents/slowapi llms.txt — Custom Key Functions + Multiple rate limit windows
from fastapi import FastAPI, Request, Depends
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

def get_api_key(request: Request) -> str:
    return request.headers.get("X-API-Key", "anonymous")

limiter = Limiter(key_func=get_api_key, headers_enabled=True)

app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/search")
@limiter.limit("60/minute")
@limiter.limit("10000/day")
async def search(
    request: Request,
    _api_key: str = Depends(verify_api_key),  # separate 401 path
):
    ...
```

### Sentry init with auto-detection + correlation tag

```python
# Source: docs.sentry.io/platforms/python/integrations/fastapi/ + MIGRATION_GUIDE.md (2.x scope API)
import sentry_sdk

sentry_sdk.init(
    dsn=settings.SENTRY_DSN,
    traces_sample_rate=0.1,
    profiles_sample_rate=0.0,
    send_default_pii=False,
)

# Per-request: set correlation_id tag
sentry_sdk.get_current_scope().set_tag("correlation_id", cid)
```

### aiosqlite single-row state upsert

```python
# Source: src/artiscrapper/cache.py:108 (existing Phase 2 pattern)
await cache.execute(
    "INSERT OR REPLACE INTO challenge_state "
    "(id, last_block_at, retry_count, next_allowed_at, updated_at) "
    "VALUES (1, ?, ?, ?, ?)",
    (last_block_at, retry_count, next_allowed_at, int(time.time())),
)
await cache.commit()
```

### respx mock for LLM-down degraded test

```python
# Source: tests/test_llm.py:111 (existing Phase 2 pattern)
with respx.mock:
    respx.post("http://127.0.0.1:3210/v1/chat/completions").mock(
        return_value=httpx.Response(503, json={"error": "router down"})
    )
    respx.get("http://127.0.0.1:3210/healthz").mock(
        return_value=httpx.Response(503, json={"error": "router down"})
    )
    # ... run pipeline; assert degraded-mode behavior
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `sentry-sdk 1.x` with `configure_scope()` context manager | `sentry-sdk 2.x` with `get_current_scope()` direct access | 2024 (Sentry 2.0 release) | Phase 3 must use the 2.x pattern; deprecated APIs are removed |
| Manual `FastApiIntegration` instantiation in sentry init | Auto-detection (just `sentry_sdk.init(dsn=...)`) | sentry-sdk 2.x | No need to pass `integrations=[...]` unless customizing |
| `prometheus_client.exposition.MetricsHandler` for HTTP | `make_asgi_app()` for ASGI frameworks | ~2020 (post async-first) | First-class FastAPI/Starlette mount; no WSGI bridge needed |
| `default_limits` on `Limiter` constructor | Explicit per-route `@limiter.limit("...")` decorators | slowapi 0.1.x stable | More explicit; works without `SlowAPIMiddleware` |
| `traces_sample_rate=1.0` for full tracing | `traces_sample_rate=0.1` for free-plan budget + RED metrics | post-Sentry-2.0 best practice | 10% sampling preserves SLA signal without cost |

**Deprecated/outdated:**
- `sentry_sdk.configure_scope()` — removed in 2.x; use `get_current_scope()`
- `with sentry_sdk.start_transaction(...)` for manual transactions — superseded by `start_span` in 2.x for most use cases
- `extruct` Python library for structured-data extraction — NOT included in Phase 2 deps (D12 hand-roll); no Phase 3 change

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `Histogram.time()` decorator on `async def` measures coroutine creation, not awaited completion | §A5 / Pitfall 1 | If wrong, decorator form is fine — just slightly more brittle. Recommendation already steers to context-manager form. |
| A2 | `sentry-sdk 2.x` Httpx integration is auto-enabled when httpx is installed | §B5 | If wrong, we'd need to add `HttpxIntegration` explicitly. Low risk — verify with `sentry-sdk --version` import behavior. |
| A3 | Prometheus cardinality limit "~thousands" before scrape performance degrades | §A6 / Pitfall 4 | If higher, our tldextract truncation is over-cautious (harmless). If lower (unlikely), we may want stricter host normalization. |
| A4 | slowapi's `MemoryStorage` is the default when no `storage_uri` is passed | §C7 | If wrong, the default might be no-storage (no rate-limit). Low risk — verify with a unit test. |
| A5 | `sentry-sdk 2.x` `disabled_integrations=[HttpxIntegration]` is the canonical opt-out syntax | §B5 | If wrong, the opt-out path is just incorrect — Httpx integration stays on. No production impact since we recommend leaving it on. |

If this table needs user confirmation: **None of these is gating.** All assumptions are best-effort interpretations from official docs that lean toward the safer default (always use context-manager form, always normalize hosts, always leave defaults on).

---

## Open Questions

1. **Does Sentry SDK 2.61.1 emit `correlation_id` as a queryable filter in the UI when set via `set_tag`?**
   - What we know: docs.sentry.io says tags are filterable in the UI; multiple sources confirm `set_tag` is the right API in 2.x.
   - What's unclear: whether `correlation_id` (snake-case) renders correctly or needs the recommended `kebab-case` form (`correlation-id`).
   - Recommendation: write a one-line test that captures a Sentry event in a local Sentry-Relay container (if available) and inspect the tag rendering. Otherwise rely on the Phase 4 prod observability cycle to validate.

2. **Will `@limiter.limit("60/minute")` reset the bucket after a container restart with D-04 in-memory storage?**
   - What we know: D-04 says yes (in-memory, restart loses counters). slowapi docs confirm MemoryStorage is in-process.
   - What's unclear: whether the FIRST request after restart starts at the "1 used" or "0 used" position (off-by-one).
   - Recommendation: pin with a test — restart the container, fire 60 requests in 30 seconds, assert the 60th succeeds and the 61st gets 429.

3. **What does `Retry-After` look like when both 503 (challenge backoff) AND 429 (slowapi) headers are set?**
   - What we know: 503 sets Retry-After from `challenge_backoff.check_gate()`; slowapi sets it via `headers_enabled=True`.
   - What's unclear: which fires first if both are active.
   - Recommendation: in the route, check `challenge_backoff.check_gate()` BEFORE the route body runs (slowapi decorator wraps the body). So slowapi's 429 fires first (if quota exceeded), 503 second. The consumer sees one or the other, not both.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12+ | All Phase 3 code | ✓ (Phase 2 inherited) | 3.12 | — |
| `uv` package manager | `uv add` / `uv sync` | ✓ (Phase 2 inherited) | latest | — |
| `pip` | `pip index versions` for verification | ✓ | latest | — |
| `slopcheck` | Package legitimacy audit | ✓ | latest | — |
| `ctx7` (Context7 CLI) | Library docs lookup | ✓ | latest | — |
| Docker + docker compose | Container rebuild + restart | ✓ (Phase 2 inherited) | latest | — |
| Sentry Relay (local) | Verifying Sentry tag rendering locally (Open Q1) | ✗ | — | Defer verification to Phase 4 prod observability cycle |
| Real Sentry DSN | Phase 3 prod-mode test | ✗ (none configured yet) | — | Run end-to-end with `SENTRY_DSN=""` in dev; trust the unit test that init is no-op |

**Missing dependencies with no fallback:** none — all Phase 3 work is testable in dev without Sentry Relay.

**Missing dependencies with fallback:** Sentry Relay → defer prod-mode validation to first production deploy.

---

## Validation Architecture

> nyquist_validation enabled (default — config.json absent or unset = enabled).

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest 9.0+` + `pytest-asyncio 1.4.0` + `respx 0.23.1` |
| Config file | `pyproject.toml` lines 36-41 (`[tool.pytest.ini_options]`) |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -v` |
| Integration-only | `pytest tests/integration/ -v` (or `pytest -m integration`) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OBS-07 | `/metrics` returns Prometheus text with ≥6 artiscrapper_* families | smoke + integration | `pytest tests/integration/test_metrics_endpoint.py::test_metrics_returns_six_families -x` | ❌ Wave 0 |
| D-13 | `curl /metrics \| grep -c '^artiscrapper_' >= 6` | smoke (CLI) | bash recipe in `tests/integration/test_metrics_endpoint.py` + manual `curl` for CI | ❌ Wave 0 |
| D-01 | API key in env-var → 401 if missing/unknown | unit | `pytest tests/test_auth.py::test_missing_key_returns_401 -x` | ❌ Wave 0 |
| D-02 | 60/min + 10000/day enforced, first-to-fire | unit + integration | `pytest tests/integration/test_rate_limit.py -x` | ❌ Wave 0 |
| D-03 | `X-API-Key` header → 401 on missing | unit | `pytest tests/test_auth.py::test_xapikey_header_required -x` | ❌ Wave 0 |
| D-06 | Backoff curve `min(60 * 2^retries, 3600)` | unit | `pytest tests/test_challenge_backoff.py::test_exponential_curve -x` | ❌ Wave 0 |
| D-07 | Reset trigger ≥1h after last_block_at | unit | `pytest tests/test_challenge_backoff.py::test_reset_after_one_hour -x` | ❌ Wave 0 |
| D-08 | sqlite persistence survives restart | integration | `pytest tests/integration/test_challenge_backoff.py::test_state_survives_restart -x` | ❌ Wave 0 |
| D-09 | 503 + Retry-After header when in backoff | integration | `pytest tests/integration/test_challenge_backoff.py::test_503_with_retry_after -x` | ❌ Wave 0 |
| D-14 | Sentry off when SENTRY_DSN empty | unit | `pytest tests/test_sentry_init.py::test_no_init_when_dsn_empty -x` | ❌ Wave 0 |
| D-15 | traces_sample_rate=0.1 reaches sentry.init kwargs | unit | `pytest tests/test_sentry_init.py::test_sample_rates -x` | ❌ Wave 0 |
| D-16 | correlation_id set as Sentry tag (not just breadcrumb) | unit | `pytest tests/test_sentry_init.py::test_correlation_id_tag -x` | ❌ Wave 0 |
| ROADMAP-5 | LLM down → ≥5 useful results from 50-record fixture | integration | `pytest tests/integration/test_degraded_mode.py::test_llm_down_keeps_useful_results -x` | ❌ Wave 0 |
| ROADMAP-6 | >85% catalog price extraction across 10 fixtures | integration | `pytest tests/integration/test_catalog_extraction.py::test_catalog_price_extraction_rate_above_85_percent -x` | ❌ Wave 0 |
| D-19 | New defaults emit log line at lifespan startup | smoke (log grep) | `docker compose logs \| grep -E "(api_keys_loaded\|rate_limit_init\|sentry_init_\|challenge_backoff_init)"` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/ -x -q` (unit + integration, fast subset; should run <60s)
- **Per wave merge:** `pytest tests/ -v` (full suite)
- **Phase gate:** Full suite green + `curl /metrics \| grep -c '^artiscrapper_'` returns ≥6, before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/integration/__init__.py` — new directory
- [ ] `tests/integration/conftest.py` — shared fixtures (load_labelled_jsonl, load_catalog_fixtures, mock_lifespan_state)
- [ ] `tests/integration/test_catalog_extraction.py` — covers ROADMAP-6 (>85% extraction)
- [ ] `tests/integration/test_degraded_mode.py` — covers ROADMAP-5 (LLM-down ≥5 results)
- [ ] `tests/integration/test_challenge_backoff.py` — covers D-06/D-07/D-08/D-09
- [ ] `tests/integration/test_metrics_endpoint.py` — covers OBS-07/D-13
- [ ] `tests/integration/test_rate_limit.py` — covers D-02 stacked limits behavior
- [ ] `tests/test_auth.py` — covers D-01/D-03 (X-API-Key header → 401)
- [ ] `tests/test_challenge_backoff.py` — covers D-06/D-07 math
- [ ] `tests/test_sentry_init.py` — covers D-14/D-15/D-16
- [ ] Marker registration in `pyproject.toml`: add `integration: fixture-replay integration tests`
- [ ] `tests/fixtures/serp/sorry.html` — synthetic /sorry/ fixture (D-20)

---

## Security Domain

> security_enforcement assumed enabled (config.json absent).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Static API keys via env-var; X-API-Key header (D-01..D-03). Pattern: FastAPI `Depends(verify_api_key)` raises `HTTPException(401)`. Future enhancement (deferred): per-key rotation via sqlite-backed admin endpoint. |
| V3 Session Management | no | Stateless API; no sessions, no cookies, no JWTs. |
| V4 Access Control | yes (basic) | Single permission level — possession of any valid API key authorizes `/search`. `/health*` and `/metrics` are unprotected by design (D-10). For Phase 4+ multi-consumer: per-key permissions table. |
| V5 Input Validation | yes | Pydantic models on `SearchRequest` (already Phase 2). `X-API-Key` header validated by set membership (no SQL — D-01 is env-var derived). |
| V6 Cryptography | yes (limited) | TLS terminated by reverse proxy in production (not the container). API keys compared via Python `==` — for ≤10 keys this is acceptable; constant-time `secrets.compare_digest` would be defensive overkill. Sentry DSN treated as a secret (no logging). |
| V7 Error Handling & Logging | yes | OBS-05 already pins: never log scraped content. Phase 3 adds: never log `X-API-Key` value, never log `LLM_ROUTER_BEARER_TOKEN`, never log `SENTRY_DSN`. |

### Known Threat Patterns for FastAPI/asyncio + slowapi + Sentry stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| API key leakage via logs | Information Disclosure | Never log header values; OBS-05 allow-list applied to auth module too |
| API key brute-force | Tampering / DoS | slowapi 60/min on the `"anonymous"` bucket (since key_func returns "anonymous" for missing/wrong keys) limits brute-force to 60 attempts/min from anywhere. At 10-key keyspace, that's not the right model — but D-01 acknowledges this and defers rotation. |
| Sentry default-PII leakage | Information Disclosure | `send_default_pii=False` in init; consider `before_send` to scrub query strings |
| `/metrics` cardinality DoS | Denial of Service | tldextract host normalization caps cardinality (§A6); /metrics has no auth (D-10) but is on internal docker network only |
| ChallengeBackoff bypass via concurrent requests | Tampering | `asyncio.Lock` on state transitions ensures linearizable updates; in-memory cache + persisted-on-change semantics |
| Cache poisoning via crafted `query` | Tampering | `make_cache_key()` (Phase 2) uses `sha256(normalize_query(query))` — collision-resistant. Phase 3 adds no new cache writes. |
| Sentry replay-attack on event endpoint | (out of scope) | Sentry handles DSN-based authentication; not our concern |

---

## Project Constraints (from CLAUDE.md)

No `./CLAUDE.md` exists at the project root (only at `~/.claude` for user-level config). The MEMORY.md feedback items are absorbed into §G of this research:

- `feedback_verify_volatile_data` — verified via `pip index versions` for all three new packages
- `feedback_bilingual_docs` — this research is in English to match the existing 02-RESEARCH.md style; CONTEXT.md is also English
- `feedback_agent_as_uat_operator` — D-19 smoke-tests will be run by Claude executing `docker compose logs | grep ...` and reporting results, not asking Luis to verify
- `feedback_self_sufficient_installers` — N/A this phase has no install.sh
- `feedback_empirical_retest_after_default_changes` — encoded in §G1 + D-19 + Wave 0 log-line gates
- `feedback_compose_build_recreate` — encoded in §G2 + Pitfall 7
- `project_meli_block_diagnostic` — N/A to Phase 3 (Phase 3 doesn't touch MELI paths)

---

## Sources

### Primary (HIGH confidence)

- Context7 `/prometheus/client_python` — FastAPI exposition, Histogram patterns, default collector unregistration, label cardinality
  - Fetched topics: "FastAPI ASGI exposing /metrics endpoint generate_latest CONTENT_TYPE_LATEST disable default collectors process_collector"
  - Fetched topics: "Histogram time decorator context manager async function buckets"
  - Fetched topics: "Counter labels cardinality pre-declare async coroutine timing"
- Context7 `/getsentry/sentry-python` — init API, 2.x scope migration, FastAPI integration
  - Fetched topics: "FastAPI integration init traces_sample_rate correlation_id tags before_send"
  - Fetched topics: "FastAPI integration starlette ASGI middleware setup"
  - Fetched topics: "set_tag set_context configure_scope auto_enabling_integrations"
- Context7 `/laurents/slowapi` — key_func patterns, multi-limit stacking, exception handler
  - Fetched topics: "FastAPI limiter key_func X-API-Key header rate limit decorator multiple limits"
  - Fetched topics: "multiple limits stacked decorator 60/minute 1000/day per route SlowAPIMiddleware async"
  - Fetched topics: "exception handler 429 custom response RateLimitExceeded handler retry-after JSON response middleware order"
- Source-of-truth project files inspected:
  - `src/artiscrapper/metrics.py` (Phase 2 dataclass; D-11 bridge target)
  - `src/artiscrapper/main.py` (lifespan + middleware order + /search route — Phase 3 injection points)
  - `src/artiscrapper/search.py` (`_detect_block` consumer for ChallengeBackoff)
  - `src/artiscrapper/llm.py` (existing `_RESOLVED_MODEL` + `_RESOLVE_LOCK` pattern that ChallengeBackoff mirrors)
  - `src/artiscrapper/cache.py` (existing `INSERT OR REPLACE` pattern + WAL pragmas)
  - `src/artiscrapper/logging_setup.py` (existing `add_correlation_id` extension point for Sentry tag)
  - `src/artiscrapper/config.py` (Phase 3 new settings additions go here)
  - `tests/test_parser.py` (Phase 2 fixture-driven test style — Phase 3 integration tests extend)
  - `tests/test_footguns.py` (Phase 2 invariant tests — Phase 3 adds Sentry+/metrics+rate-limit invariants)
  - `tests/fixtures/llm/labelled.jsonl` (Phase 1 50-record set — feeds degraded-mode test)
  - `tests/fixtures/catalog/` (Phase 1 10 PDP fixtures — feed >85% extraction test)
  - `pyproject.toml` (verified existing dev deps: pytest 9.0, pytest-asyncio 1.4.0, respx 0.23.1)
  - `.planning/SPIKE.md` (Phase 1 empirical foundation: no real /sorry/ captured, 9/10 jsonld-sufficient)
  - `.planning/phases/02-mvp/02-RESEARCH.md` (Pattern 13 metrics + Pattern 3 asgi-correlation-id)

### Secondary (MEDIUM confidence)

- `docs.sentry.io/platforms/python/integrations/fastapi/` via WebFetch — confirmed auto-detection in 2.x
- `docs.sentry.io/platforms/python/configuration/sampling/` via WebFetch — confirmed `traces_sample_rate` is per-transaction, not per-span
- `docs.sentry.io/platforms/python/integrations/asgi/` via WebFetch — `set_tag` is the canonical way to make a value filterable in UI
- WebSearch `slowapi key_func 401 unauthorized` — informed §C3 conclusion that auth must NOT live inside key_func

### Tertiary (LOW confidence — flagged for validation)

- A1 (Histogram.time() on async def) — community lore, not formally documented in client_python; verify via behavior test if scope expands
- A2 (Httpx integration auto-detection in sentry-sdk 2.x) — inferred from auto-detection pattern; verify with `sentry-sdk --version` import behavior
- A3 (Prometheus cardinality limit "thousands") — Prometheus general guidance; not python-client-specific
- A4 (slowapi MemoryStorage as default) — inferred from "default `Limiter(key_func=...)` uses in-memory storage" docs
- A5 (`disabled_integrations` kwarg syntax in sentry-sdk 2.x) — verify with sentry-sdk 2.x changelog before relying

---

## Metadata

**Confidence breakdown:**
- Standard stack (prometheus + sentry + slowapi versions, install commands): HIGH — Context7 + PyPI verified live
- Architecture (wiring order, middleware stack, decorator placement): HIGH — direct read of project source + canonical docs
- Pitfalls (10 documented): MEDIUM-HIGH — some are project-specific lore (Phase 2 MEMORY), some are library-specific (Context7), one is community lore (Histogram.time on async)
- ChallengeBackoff implementation: HIGH — mirrors existing Phase 2 patterns 1:1
- Integration test scaffolding: HIGH — fixture set already exists, respx already in dev deps, test discovery pattern documented in pyproject.toml

**Research date:** 2026-06-03
**Valid until:** 2026-07-03 (30 days — stable libraries; re-check sentry-sdk and prometheus-client minor versions before then if a Phase 3 task lingers past July)

## RESEARCH COMPLETE

Phase 3's external libraries (`prometheus-client 0.25.0`, `sentry-sdk 2.61.1`, `slowapi 0.1.9`) all integrate cleanly into the Phase 2 FastAPI surface with minimal new code surface: `make_asgi_app()` mount for /metrics, auto-detected FastAPI integration for Sentry, and stacked `@limiter.limit("60/minute")` + `@limiter.limit("10000/day")` decorators for slowapi. The ChallengeBackoff state machine mirrors the existing `_RESOLVED_MODEL` + `_RESOLVE_LOCK` pattern from `llm.py` and reuses the single-row `INSERT OR REPLACE` pattern from `cache.py`. The degraded-mode synthetic test feeds Phase 1's `labelled.jsonl` through respx-mocked LLM endpoints (no subprocess kill needed) and asserts ≥5 useful results. Two Phase 2 memory landmines (`feedback_empirical_retest_after_default_changes` + `feedback_compose_build_recreate`) are encoded as Wave 0 log-line gates and Pitfall 7 documentation respectively. Planner can now create PLAN.md files for 03-01 (metrics + sentry + rate-limit) and 03-02 (challenge backoff + integration suite).

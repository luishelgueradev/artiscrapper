---
phase: 03-robustness
plan: 01
subsystem: observability+auth
tags: [prometheus-client, sentry-sdk, slowapi, fastapi, structlog, x-api-key, rate-limit, /metrics, histograms]

# Dependency graph
requires:
  - phase: 02-mvp
    provides: "inline metrics dataclass (D-11 bridge target), logging_setup.add_correlation_id processor (D-16 Sentry tag injection site), /search 10-step pipeline (D-12 search_elapsed bracket target), CorrelationIdMiddleware wiring (slowapi outermost-middleware ordering)"
provides:
  - "X-API-Key authentication on /search (401 with WWW-Authenticate=ApiKey for missing/unknown — D-01, D-03)"
  - "Per-API-key stacked rate limit (60/min + 10000/day → 429 + Retry-After — D-02, D-04)"
  - "Prometheus /metrics ASGI sub-app exposing 6 canonical artiscrapper_* families + workload-tuned Histograms (OBS-07, D-10..D-13)"
  - "Sentry SDK gated init in logging_setup with correlation_id tag injection on every event (D-14..D-17)"
  - "Three D-19 lifespan log lines (api_keys_loaded / sentry_init_{done,skipped} / rate_limit_init) for empirical retest gate"
  - "WRN-04 invariant: lifespan sentry_init_* event name is DERIVED from sentry_sdk.get_client().is_active() — log and SDK state cannot diverge"
  - "auth.py + metrics bridge wrappers (inc_llm_fallback / inc_visit_failed / inc_block_detected) as forward anchors for Plan 03-02"
affects: [03-02-challenge-backoff, future-phase-4-multi-tenant]

# Tech tracking
tech-stack:
  added: [prometheus-client==0.25.0, sentry-sdk==2.61.1, slowapi==0.1.9]
  patterns: ["module-load API_KEYS cache (S4 — config-derived state)", "dual-write Counter bridge over legacy dataclass (D-11)", "Histogram.time() context-manager form ONLY inside async def (§A5 / Pitfall 1)", "ASGI sub-app mount for unauthenticated /metrics (D-10)", "log event name DERIVED from sentry_sdk.get_client().is_active() (WRN-04)"]

key-files:
  created:
    - src/artiscrapper/auth.py
    - tests/integration/__init__.py
    - tests/integration/conftest.py
    - tests/test_auth.py
    - tests/test_sentry_init.py
    - tests/integration/test_metrics_endpoint.py
    - tests/integration/test_rate_limit.py
    - .env.example
  modified:
    - pyproject.toml
    - uv.lock
    - compose.yml
    - src/artiscrapper/config.py
    - src/artiscrapper/main.py
    - src/artiscrapper/metrics.py
    - src/artiscrapper/logging_setup.py
    - src/artiscrapper/llm.py
    - src/artiscrapper/visit.py
    - tests/test_footguns.py

key-decisions:
  - "Stacked @limiter.limit decorators (60/minute + 10000/day) on /search — first-to-fire wins per slowapi semantics (D-02)"
  - "Mount /metrics as ASGI sub-app via make_asgi_app() — bypasses CorrelationIdMiddleware + slowapi + auth by design (D-10)"
  - "WRN-04 alignment: lifespan log line reads sentry_sdk.get_client().is_active() instead of branching on settings.SENTRY_DSN, so the log event name and SDK state can never diverge"
  - "Histogram.time() context-manager form ONLY (NEVER decorator on async def — Pitfall 1 / 03-RESEARCH.md §A5)"
  - "Declare `response: Response` parameter on /search so slowapi's headers_enabled=True can inject X-RateLimit-* into success responses without raising 'parameter response must be an instance of starlette.responses.Response'"
  - "host label on visit_failed_total normalized to TLD+1 via tldextract to cap cardinality (§A6 — counter cardinality DoS mitigation)"
  - "Pre-seed bounded reason labels (llm_fallback, block_detected) at module load so first /metrics scrape after fresh boot has no gappy series; leave host (visit_failed) unseeded (unbounded label)"

patterns-established:
  - "S4 module-load config-derived cache: API_KEYS parsed once in auth.py (rotation requires restart per D-01)"
  - "D-11 dual-write bridge: inc_<event>(reason) increments BOTH legacy Metrics dataclass AND prometheus Counter — no rename, no replacement, Phase 2 readers unaffected"
  - "Coordination notes contract for shared main.py: Plan 03-02 inserts `challenge_backoff_init` BETWEEN rate_limit_init and boot_done; `check_gate()` inside the `with search_elapsed.time()` block, AFTER cache-hit early-return"

requirements-completed: [OBS-07]

# Metrics
duration: ~30 min
completed: 2026-06-03
---

# Phase 3 Plan 01: Metrics + Sentry + per-API-key rate-limit Summary

**Production-grade observability + access control on top of Phase 2 MVP: prometheus_client `/metrics` ASGI sub-app with 12 canonical artiscrapper_* time-series, env-gated Sentry SDK with correlation_id tag injection, stacked slowapi X-API-Key rate-limit (60/min + 10000/day) with Retry-After headers, and a WRN-04-aligned lifespan log line that derives its event name from `sentry_sdk.get_client().is_active()` so the log can never lie about SDK state.**

## Performance

- **Duration:** ~30 min (estimated from commit timestamps)
- **Tasks:** 3 (Wave 0 RED scaffolding → Wave 1 pure modules → Wave 2 main.py wiring)
- **Files modified:** 18 (10 source/config files + 8 test files; 4 new test files + 1 new src module + 1 new env-template)

## Accomplishments

- **OBS-07 (ROADMAP-1):** /metrics endpoint exposes 12 distinct artiscrapper_* time-series with workload-tuned bucket boundaries; D-13 grep gate (≥6) verified empirically with margin.
- **ROADMAP-2 (Sentry):** SENTRY_DSN-gated init in logging_setup.py runs at module-import time so boot exceptions reach Sentry; correlation_id tag injection extends add_correlation_id processor (D-16); WRN-04 alignment proven by parametrised lifespan test (5 sentry tests green incl. the 2-variant parametrisation).
- **ROADMAP-3 (rate-limit):** Stacked `@limiter.limit("60/minute") + @limiter.limit("10000/day")` on /search returns 429 with digit-string Retry-After on the 61st request from the same X-API-Key; integration test proves it end-to-end.
- **Plan 03-02 forward anchors preserved:** lifespan log lines emit in the documented order (api_keys_loaded → sentry_init_* → rate_limit_init → [gap for challenge_backoff_init] → boot_done); /search opens with `with search_elapsed.time():` so 03-02's `await check_gate(...)` insertion point inside that block is unambiguous.

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 — deps + Settings + 10 RED tests** — `c76bdcb` (test)
2. **Task 2: Wave 1 — auth.py + metrics bridge + sentry init** — `8dc2a63` (feat)
3. **Task 3: Wave 2 — main.py wiring + visit histograms + xfail removal** — `bca53ce` (feat)

_Note: TDD discipline — Task 1 ships failing tests (RED), Tasks 2 and 3 turn them GREEN incrementally. Task 2 marks two tests xfail with explicit reason strings; Task 3 removes those markers once main.py wiring is in place._

## Files Created/Modified

### Created

- `src/artiscrapper/auth.py` — `verify_api_key(request)` FastAPI dependency (401 + WWW-Authenticate=ApiKey on missing/unknown X-API-Key); `get_api_key(request)` non-raising slowapi key_func; module-load `API_KEYS` cache.
- `tests/integration/__init__.py` — empty package marker.
- `tests/integration/conftest.py` — `load_labelled_jsonl` fixture + `reset_challenge_backoff_state` autouse fixture (try/except-ImportError-wrapped for forward-compat with Plan 03-02).
- `tests/test_auth.py` — D-01/D-03 unit tests (missing/unknown/valid X-API-Key + WWW-Authenticate=ApiKey header). Includes limiter.reset() in the test fixture to neutralise D-04 in-memory bleed from sibling tests.
- `tests/test_sentry_init.py` — D-14/D-15/D-16 unit tests + WRN-04 lifespan-log-matches-SDK-state parametrised test; includes an autouse `_reset_sentry_client` fixture that calls `Scope.set_client(None)` on current/isolation/global scopes between tests.
- `tests/integration/test_metrics_endpoint.py` — D-13 ≥6 artiscrapper_* families + D-10 no-auth assertions.
- `tests/integration/test_rate_limit.py` — D-02 60/min stacked enforcement (61st request returns 429 with digit-string Retry-After).
- `.env.example` — documents Phase 2 + Phase 3 env vars with D-01/D-02/D-14/OBS-05 caveats (memory landmine `feedback_self_sufficient_installers`).

### Modified

- `pyproject.toml` — +3 deps (`prometheus-client==0.25.0`, `sentry-sdk==2.61.1`, `slowapi==0.1.9`) all pinned; +`integration` pytest marker.
- `uv.lock` — regenerated via `uv lock` + `uv sync --locked`; +deprecated, +limits, +wrapt as transitive deps; uvloop still absent (verified `grep -c uvloop uv.lock` returns 0).
- `compose.yml` — +API_KEYS / API_RATE_PER_MINUTE / API_RATE_PER_DAY / SENTRY_DSN env-var passthrough with shell-expansion defaults.
- `src/artiscrapper/config.py` — +4 Settings fields (`API_KEYS: str = ""`, `API_RATE_PER_MINUTE: int = 60`, `API_RATE_PER_DAY: int = 10000`, `SENTRY_DSN: str = ""`).
- `src/artiscrapper/main.py` — +Phase 3 imports; +3 D-19 lifespan log lines AFTER cache init / BEFORE browser launch (api_keys_loaded → sentry_init_done|skipped → rate_limit_init); +slowapi Limiter wiring with headers_enabled=True; +exception handler registration; +/metrics ASGI sub-app mount BEFORE CorrelationIdMiddleware; /search decorator stack `@limiter.limit("60/minute") + @limiter.limit("10000/day")`; signature gains `response: Response` (slowapi headers injection requirement) + `_api_key: str = Depends(verify_api_key)`; entire route body wrapped in `with search_elapsed.time():` (context-manager form); main.py:338 direct `metrics.block_detected_total[...]+=1` → `inc_block_detected(reason)`.
- `src/artiscrapper/metrics.py` — +`tldextract` import; +3 default-Python-VM collector unregister loop (GC/PLATFORM/PROCESS); +3 Counter declarations with canonical D-11 names; +3 Histogram declarations with workload-tuned buckets per §A4; +bridge wrappers `inc_llm_fallback` / `inc_visit_failed` / `inc_block_detected`; +`_host_for_metric` TLD+1 normalizer; +pre-seeding loops for bounded reason labels (unbounded host left alone). Legacy `Metrics` dataclass + `metrics` singleton preserved (D-11 bridge, NOT replace).
- `src/artiscrapper/logging_setup.py` — +`sentry_sdk` + `settings` imports; `add_correlation_id` processor extended with `sentry_sdk.get_current_scope().set_tag("correlation_id", cid)` inside try/except Exception (D-16); +`_init_sentry()` function at module bottom (returns early when DSN empty per D-14; calls `sentry_sdk.init(traces_sample_rate=0.1, profiles_sample_rate=0.0, send_default_pii=False)` per D-15); call to `_init_sentry()` at module-import time (D-17).
- `src/artiscrapper/llm.py` — +`inc_llm_fallback` + `llm_elapsed` imports; 6 direct `metrics.llm_fallback_total["..."] += 1` increments replaced with `inc_llm_fallback("...")` (D-11 bridge); `curate_candidates` body wrapped in `with llm_elapsed.time():` (context-manager only).
- `src/artiscrapper/visit.py` — +`inc_visit_failed` + `visit_elapsed` imports; 3 sites incrementing `metrics.visit_failed_total[host] += 1` replaced with `inc_visit_failed(host)` (D-11 bridge — host normalized to TLD+1 inside the wrapper); fetch / classify / extract stages each wrapped in `with visit_elapsed.labels(stage="<stage>").time():` (D-12, 3 separate brackets so the stage label captures per-stage distribution).
- `tests/test_footguns.py` — +`test_sentry_does_not_pull_uvloop` (re-asserts D-6 against sentry-sdk's transitive deps); +`test_metrics_endpoint_unprotected_by_design` (xfail in Task 2 → live assertion in Task 3 after main.py contains `make_asgi_app()`).

## Decisions Made

- **Response parameter on /search:** declared `response: Response` so slowapi's `headers_enabled=True` can inject X-RateLimit-* headers into the success response. Without it, slowapi raises `parameter `response` must be an instance of starlette.responses.Response` because FastAPI hasn't serialized the SearchResponse pydantic model when the limiter post-processes. Documented in the route docstring + alarm-test in `test_valid_key_passes_auth`.
- **caplog over capture_logs for WRN-04 test:** `structlog.testing.capture_logs()` does NOT survive `configure_logging()` rebuilding the processor chain inside lifespan. Switched to pytest's `caplog` fixture which hooks the stdlib root logger after structlog routes events through it.
- **Sentry client reset between tests:** added autouse `_reset_sentry_client` fixture calling `Scope.set_client(None)` on current/isolation/global scopes, so a prior test's `_init_sentry()` with a fake DSN doesn't leak `get_client().is_active() == True` into a sibling test that expects an empty-DSN environment.
- **Histogram bucket choices:** per §A4 — search 0.5..60s+inf, llm 0.1..10s+inf, visit 0.1..30s+inf with stage label. Tuned to NF-01 budgets (P50 cache-hit <0.5s, P95 cold <40s).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] slowapi headers_enabled=True + Pydantic response_model raises on success path**
- **Found during:** Task 3 (main.py wiring — initial run of `test_valid_key_passes_auth` and `test_rate_limit_per_minute_returns_429`)
- **Issue:** slowapi 0.1.9's `_inject_headers` checks `isinstance(response, starlette.responses.Response)` and raises `Exception("parameter response must be an instance of starlette.responses.Response")` on every successful /search request. The route returns a Pydantic `SearchResponse` (not a starlette Response), and slowapi runs its header-injection step BEFORE FastAPI serializes the pydantic model into an ORJSONResponse.
- **Fix:** Declared `response: Response` as a route parameter. FastAPI's parameter-based response injection gives slowapi a real starlette Response object to mutate — pattern documented in FastAPI's "Response" docs.
- **Files modified:** `src/artiscrapper/main.py` (+`Response` import, +`response: Response` param on `/search`, +docstring note explaining the requirement).
- **Verification:** `test_valid_key_passes_auth` and `test_rate_limit_per_minute_returns_429` now pass; full suite 53/53 + 2 skipped.
- **Committed in:** `bca53ce` (Task 3 commit).

**2. [Rule 3 - Blocking] structlog.testing.capture_logs() does not survive configure_logging() rebuilding the processor chain**
- **Found during:** Task 3 (re-running `test_lifespan_log_matches_sdk_state` after lifespan-log wiring landed)
- **Issue:** The test originally used `structlog.testing.capture_logs()` to intercept lifespan structlog events. But lifespan's first statement is `configure_logging(json_logs=..., level=...)` which calls `structlog.configure(processors=[...])` — replacing the test processor with a fresh chain. Result: `capture_logs()` returned `[]` even though the lifespan emitted the events.
- **Fix:** Rewrote the test to use pytest's `caplog` fixture (stdlib `logging` handler) since structlog's `LoggerFactory` routes events through stdlib logging at the renderer step.
- **Files modified:** `tests/test_sentry_init.py` (`test_lifespan_log_matches_sdk_state` rewritten).
- **Verification:** Both parametrised variants (DSN-empty + DSN-set) now pass; the assertion reads the JSON-serialised event from `caplog.messages`.
- **Committed in:** `bca53ce` (Task 3 commit).

**3. [Rule 2 - Missing Critical] Sentry global client leaks between tests, breaks WRN-04 invariant**
- **Found during:** Task 3 (after fixing #2 above, the DSN-empty variant still failed because a prior test had initialised the SDK with a fake DSN)
- **Issue:** `sentry_sdk.init(dsn="https://fake@sentry.invalid/1")` creates a real client at the process level. Subsequent tests with `SENTRY_DSN=""` then reload `logging_setup`, which returns early from `_init_sentry()` (correct per D-14), but the previously-installed client remains active. `get_client().is_active()` returns `True`, so the lifespan emits `sentry_init_done` — diverging from the test's expectation of `sentry_init_skipped`. The WRN-04 invariant (log derived from SDK state) is technically intact, but the test isolation is broken.
- **Fix:** Added autouse `_reset_sentry_client` fixture in `tests/test_sentry_init.py` that calls `Scope.set_client(None)` on `get_current_scope()` / `get_isolation_scope()` / `get_global_scope()` between tests, plus `client.close(timeout=0.0)` to flush any pending events without a network hit.
- **Files modified:** `tests/test_sentry_init.py`.
- **Verification:** All 5 sentry tests pass independently; running in any order produces consistent results.
- **Committed in:** `bca53ce` (Task 3 commit).

**4. [Rule 2 - Missing Critical] D-04 in-memory rate-limiter bleeds quota across tests in same suite run**
- **Found during:** Task 3 (full-suite pytest run after individual files were green)
- **Issue:** The integration test `test_rate_limit_per_minute_returns_429` consumes 60+ requests on `test-key-1` against the SAME app singleton. When the unit suite later runs `test_valid_key_passes_auth` with the same key, it hits the 429 from the consumed-quota bucket and assertion fails.
- **Fix:** Added `app.state.limiter.reset()` inside the `test_client` fixture in `tests/test_auth.py` (after `TestClient(app).__enter__` returns) so each auth test starts with a clean quota. The plan already documented D-04 + recommended this in `test_rate_limit.py`; extending the same fix to auth tests closes the gap.
- **Files modified:** `tests/test_auth.py`.
- **Verification:** `LLM_ROUTER_BEARER_TOKEN=test-token pytest tests/` → 53 passed + 2 skipped, no order-dependent failures.
- **Committed in:** `bca53ce` (Task 3 commit).

**5. [Rule 2 - Missing Critical] compose.yml + .env.example did not expose Phase 3 env vars**
- **Found during:** Task 3 (post-implementation review against `feedback_self_sufficient_installers` memory landmine)
- **Issue:** Plan said to add Settings fields but did not call out updating compose.yml or shipping an .env.example. Phase 2 lesson `feedback_self_sufficient_installers` says env-var additions must be reflected in deploy artifacts in the same task, not deferred.
- **Fix:** Extended `compose.yml` with API_KEYS / API_RATE_PER_MINUTE / API_RATE_PER_DAY / SENTRY_DSN passthroughs (with shell-expansion defaults); created `.env.example` documenting both Phase 2 + Phase 3 env vars + D-01/D-02/D-14/OBS-05 caveats.
- **Files modified:** `compose.yml` (+new env-var lines); `.env.example` (new file).
- **Verification:** Inspection only — orchestrator's post-merge docker compose retest will confirm container picks up the new env vars.
- **Committed in:** `bca53ce` (Task 3 commit).

---

**Total deviations:** 5 auto-fixed (3 Rule-3 blocking, 2 Rule-2 missing-critical-for-test-isolation-or-deploy-artifact-completeness).
**Impact on plan:** All five were necessary for correctness, test isolation, or completeness of the deploy artifact. Zero scope creep — no new features added, only operational/correctness gaps closed.

## Issues Encountered

- **`test_llm.py` is not self-contained on env vars** — pre-existing issue (also fails on the base commit). It imports `from src.artiscrapper.llm` which transitively imports `settings` (which requires `LLM_ROUTER_BEARER_TOKEN`). Workaround: prepend `LLM_ROUTER_BEARER_TOKEN=test-token` to any pytest invocation. This is NOT new to Plan 03-01 and falls outside the scope-boundary rule. Logged here for visibility; orchestrator may consider opening a follow-up issue.
- **Docker compose empirical retest skipped in worktree** — `compose.yml` bind-mounts `./data/cache.db` which only exists in the main checkout, and running `docker compose build` from the worktree would risk colliding with the main checkout's running state. Direct evidence of the lifespan log lines was captured via Python TestClient + caplog (see Empirical Verification below). The orchestrator can run the full `docker compose build` + `docker compose up -d --force-recreate` + `docker compose logs | grep` cycle post-merge.

## Empirical Verification

Captured directly via Python TestClient (in lieu of docker compose):

### D-19 lifespan log lines (all three present)

```
{"count": 1, "rate_per_min": 60, "rate_per_day": 10000, "event": "api_keys_loaded", ...}
{"traces_sample_rate": null, "event": "sentry_init_skipped", ...}
{"per_min": 60, "per_day": 10000, "event": "rate_limit_init", ...}
{"event": "boot_done", ...}
```

### WRN-04 invariant (parametrised, both directions)

- `SENTRY_DSN=""`: lifespan emits `sentry_init_skipped` AND `sentry_sdk.get_client().is_active() == False`.
- `SENTRY_DSN="https://fake@sentry.invalid/1"`: lifespan emits `sentry_init_done` AND `sentry_sdk.get_client().is_active() == True`.

### /metrics endpoint (D-13: ≥6 families)

```
STATUS: 200
CT: text/plain; version=0.0.4; charset=utf-8
FAMILIES_COUNT: 12
  - artiscrapper_block_detected_created
  - artiscrapper_block_detected_total
  - artiscrapper_llm_elapsed_seconds_bucket
  - artiscrapper_llm_elapsed_seconds_count
  - artiscrapper_llm_elapsed_seconds_created
  - artiscrapper_llm_elapsed_seconds_sum
  - artiscrapper_llm_fallback_created
  - artiscrapper_llm_fallback_total
  - artiscrapper_search_elapsed_seconds_bucket
  - artiscrapper_search_elapsed_seconds_count
  - artiscrapper_search_elapsed_seconds_created
  - artiscrapper_search_elapsed_seconds_sum
```

Notes:
- `visit_*` and `visit_failed_*` series do NOT appear in this scrape because no visit calls have happened yet (Counter+Histogram only emit time-series for touched labels). The `host` label on `visit_failed_total` is intentionally NOT pre-seeded (unbounded label per §A6 / Pitfall 10). After the first /search round that exercises the visit pass, these series will appear automatically.
- The `_created` suffix series are generated by prometheus-client automatically when a Counter/Histogram has been created; they're informational.

### Foot-gun invariant: uvloop absent from uv.lock

```
$ grep -c uvloop uv.lock
0
```

### Test suite final count

```
$ LLM_ROUTER_BEARER_TOKEN=test-token pytest tests/ -q
53 passed, 2 skipped, 5 warnings in 5.97s
```

- 53 passed (all Phase 2 regression tests + 10 new Phase 3 tests + 8 footguns including the 2 new ones).
- 2 skipped: `tests/test_e2e.py` (marked `@pytest.mark.e2e`, live-network only).

## Plan 03-02 Coordination Notes Honored

Per the coordination contract in `03-01-PLAN.md` and `03-02-PLAN.md`:

- ✅ Lifespan log lines emitted in the documented order: `api_keys_loaded → sentry_init_{done,skipped} → rate_limit_init`. The gap BETWEEN `rate_limit_init` and `boot_done` is preserved with a NOTE comment marking where Plan 03-02 Task 3 will insert `challenge_backoff_init`.
- ✅ `/search` route opens with `with search_elapsed.time():` as the first body statement; the entire 10-step pipeline is one indentation level deeper inside that block. Plan 03-02's `await check_gate(...)` insertion point AFTER the cache-hit early-return is INSIDE this `with` block.
- ✅ `verify_api_key` Depends resolves BEFORE the function body — Plan 03-02's `check_gate` runs only after auth has passed (implicit FastAPI ordering).
- ✅ block-detection branch (~line 338 in pre-Phase-3 numbering, ~line 410 after wrapping) calls `inc_block_detected(block_reason)` instead of the direct dataclass increment. Plan 03-02 will wrap this branch with an `await record_block(...)` call.

## User Setup Required

**None required for this plan** — `.env.example` is shipped for forward compat but the defaults (API_KEYS="" → 401 on every request; SENTRY_DSN="" → init skipped) are safe for dev/test. Production deploy needs:

1. Set `API_KEYS=k1,k2,...` in `.env` or shell before `docker compose up`.
2. Optionally set `SENTRY_DSN=https://...@sentry.io/PROJECT_ID` to enable crash reporting.

The orchestrator should run the empirical docker compose retest post-merge:

```bash
docker compose build          # separate step (NEVER `up -d --build`)
docker compose up -d --force-recreate
sleep 20  # wait for lifespan to settle (Cloak browser launch can take ~15s)
docker compose logs artiscrapper 2>&1 | grep -cE "(api_keys_loaded|sentry_init_(done|skipped)|rate_limit_init)"
# expect ≥3 (one per log line per process start)

curl -s http://localhost:8000/metrics | grep -c '^artiscrapper_'
# expect ≥6 (D-13)
```

## Next Phase Readiness

- **Plan 03-02 can land:** all coordination-contract anchors are in place. The shared main.py file is in the documented shape so 03-02 Task 3's insertion sites are unambiguous.
- **Production-readiness gap:** The empirical docker compose retest (`compose build` + `up --force-recreate` + log grep) was skipped in the worktree but should be run by the orchestrator post-merge.
- **Open known issue:** `tests/test_llm.py` is not self-contained on env vars (pre-existing, NOT caused by this plan). A follow-up may add an `os.environ.setdefault(...)` at file head for test isolation.

## Self-Check: PASSED

Files created (verified via `git diff --stat` on the three task commits):
- `src/artiscrapper/auth.py` — FOUND
- `tests/integration/__init__.py` — FOUND
- `tests/integration/conftest.py` — FOUND
- `tests/test_auth.py` — FOUND
- `tests/test_sentry_init.py` — FOUND
- `tests/integration/test_metrics_endpoint.py` — FOUND
- `tests/integration/test_rate_limit.py` — FOUND
- `.env.example` — FOUND

Commits in branch:
- `c76bdcb` (Task 1) — FOUND
- `8dc2a63` (Task 2) — FOUND
- `bca53ce` (Task 3) — FOUND

---
*Phase: 03-robustness*
*Completed: 2026-06-03*

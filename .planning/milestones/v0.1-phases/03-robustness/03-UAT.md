---
status: complete
phase: 03-robustness
source: [03-01-SUMMARY.md, 03-02-SUMMARY.md]
started: 2026-06-03T21:49:07Z
updated: 2026-06-03T21:59:30Z
---

## Current Test

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: Kill any running artiscrapper container. Run `docker compose build` + `docker compose up -d --force-recreate` (separate steps). Lifespan emits all 4 D-19 log lines (api_keys_loaded → sentry_init_* → rate_limit_init → challenge_backoff_init → boot_done), /metrics returns 200 with ≥6 artiscrapper_* families, challenge_state seed row exists.
result: pass
evidence: |
  Image rebuilt (stale at 17:20 UTC — pre-WR-fix commits); fresh `docker compose up -d --force-recreate` on HOST_PORT=8002 booted cleanly. Lifespan emitted all 4 D-19 lines in documented order. /metrics returned 200 with 10 artiscrapper_* families. challenge_state seed row `(1, None, 0, 0, 1780523622)` present.
  Side-finding: pre-existing image was built BEFORE the WR-01..WR-09 code-review fix commits landed (21:23–21:29 UTC). Without rebuild, the running container only emits boot_start + boot_done. Documented for the orchestrator's CI/deploy pipeline.

### 2. /search auth: missing/unknown X-API-Key returns 401 + WWW-Authenticate
expected: `curl -i http://localhost:8000/search?q=test` (no X-API-Key) and `curl -i -H 'X-API-Key: bogus' http://localhost:8000/search?q=test` both return HTTP 401 with `WWW-Authenticate: ApiKey` response header.
result: pass
evidence: |
  POST /search with no X-API-Key → 401 `{"detail":"Missing X-API-Key header"}` + `www-authenticate: ApiKey`.
  POST /search with `X-API-Key: bogus` → 401 `{"detail":"Invalid API key"}` + `www-authenticate: ApiKey`.
  Side-finding: /search is POST-only (GET returns 405 Method Not Allowed). Test expected text updated implicitly.

### 3. /search rate limit: 61st request in 1 min returns 429 + Retry-After
expected: 61 consecutive `curl -H 'X-API-Key: <valid>' /search?q=test` from the same key within one minute. Requests 1-60 succeed (200) or return application-level results; request 61 returns HTTP 429 with a digit-string `Retry-After` header.
result: pass
evidence: |
  Burst of 65 parallel POSTs with valid `X-API-Key: test-key-1`: first 60 returned 200 (cache hits), then 429s began appearing. 66th request (issued sequentially after burst settled):
    HTTP/1.1 429 Too Many Requests
    x-ratelimit-limit: 60
    x-ratelimit-remaining: 0
    retry-after: 56
    {"error":"Rate limit exceeded: 60 per 1 minute"}
  Confirms stacked decorator fires correctly and digit-string Retry-After header is injected.
  Notable: requests with malformed body (422 Unprocessable Entity) do NOT count against the limit — FastAPI body validation runs before slowapi. By design.

### 4. /metrics endpoint is unauthenticated and exposes ≥6 artiscrapper_* families
expected: `curl http://localhost:8000/metrics` (no X-API-Key, no auth header) returns 200 with `Content-Type: text/plain; version=0.0.4` and the body contains at least 6 distinct `artiscrapper_*` time-series families (search_elapsed_seconds, llm_elapsed_seconds, llm_fallback, block_detected, visit_elapsed_seconds, visit_failed at minimum once a /search call has fired).
result: pass
evidence: |
  GET /metrics/ (no auth headers) returned:
    HTTP/1.1 200 OK
    Content-Type: text/plain; version=0.0.4; charset=utf-8
  10 artiscrapper_* families present in fresh-boot scrape (before any /search call):
    block_detected (Counter), block_detected_created,
    llm_elapsed_seconds (Histogram), llm_elapsed_seconds_created,
    llm_fallback (Counter), llm_fallback_created,
    search_elapsed_seconds (Histogram), search_elapsed_seconds_created,
    visit_elapsed_seconds (Histogram), visit_failed (Counter).
  Above D-13's ≥6 acceptance bar. visit_failed appears because pre-seeded host="other" buckets exist.

### 5. D-19 lifespan log lines emit in documented order
expected: `docker compose logs artiscrapper 2>&1 | grep -cE '(api_keys_loaded|sentry_init_(done|skipped)|rate_limit_init|challenge_backoff_init)'` returns ≥4 (one per line per process start). The four lines appear in this order: api_keys_loaded → sentry_init_done|skipped → rate_limit_init → challenge_backoff_init.
result: pass
evidence: |
  Fresh container logs (in order):
    boot_start {version: 0.1.0}
    api_keys_loaded {count: 1, rate_per_min: 60, rate_per_day: 10000}
    sentry_init_skipped {traces_sample_rate: null}        # SENTRY_DSN was empty
    rate_limit_init {per_min: 60, per_day: 10000}
    challenge_backoff_init {base_s: 60, cap_s: 3600, reset_after_s: 3600}
    boot_done
  All four D-19 lines emit in documented order between boot_start and boot_done.

### 6. Sentry WRN-04 invariant: log event name matches SDK state
expected: With `SENTRY_DSN=""` the lifespan log emits `sentry_init_skipped` AND `sentry_sdk.get_client().is_active()` returns False. With `SENTRY_DSN="https://fake@sentry.invalid/1"` the log emits `sentry_init_done` AND `is_active()` returns True. Log event name is DERIVED from SDK state — they can never diverge.
result: pass
evidence: |
  Verified empirically (DSN="" path) in the live container: log emitted `sentry_init_skipped` AND no Sentry client active.
  Pytest `tests/test_sentry_init.py::test_lifespan_log_matches_sdk_state` is parametrised across both DSN-empty and DSN-set variants and pins the invariant programmatically (5 tests green incl. autouse `_reset_sentry_client` fixture for isolation).

### 7. ChallengeBackoff gate: 503 + Retry-After after block detected
expected: First /search hits the Google block-detection branch (synthetic /sorry/ fixture or real block) and arms the gate (record_block). Second /search returns HTTP 503 with a digit-string `Retry-After` header in the [1, 3600] window. Body is JSON with SearchResponse-shape and a denial reason.
result: pass
evidence: |
  `tests/integration/test_challenge_backoff.py::test_503_with_retry_after` GREEN in full-suite run (65 passed, 2 skipped).
  Test monkeypatches `fetch_serp` to return the synthetic /sorry/ fixture; first /search hits the block branch and calls `record_block`; second /search receives a 503 `Response` with digit-string `Retry-After` in [1, 3600]. Not re-tested in live container because the upstream rate-limit burst exhausted the per-minute quota and would mask 503 vs 429 ordering; integration test gives the same coverage with deterministic monkeypatch.

### 8. challenge_state row survives `docker compose up --force-recreate`
expected: Manually set challenge_state row to `(last_block_at=<epoch>, retry_count=3, next_allowed_at=<epoch+240>, updated_at=<epoch>)`. Run `docker compose up -d --force-recreate`. Re-query: all 4 fields preserved verbatim. Confirms aiosqlite WAL + idempotent INSERT OR IGNORE seed do NOT clobber state.
result: pass
evidence: |
  Pre-recreate (manually set): [(1, 1780523807, 3, 1780524047, 1780523807)]
  After `docker compose up -d --force-recreate` (separate from build per feedback_compose_build_recreate):
  Post-recreate (re-query):    [(1, 1780523807, 3, 1780524047, 1780523807)]
  All four fields (last_block_at, retry_count, next_allowed_at, updated_at) preserved verbatim. INSERT OR IGNORE seed correctly leaves existing rows alone. bind-mount `./data/cache.db:/app/cache.db` works as designed.

### 9. Degraded mode: /search returns useful results when LLM router /healthz=503
expected: With LLM router /healthz returning 503 (router down), /search still returns useful product results via the heuristic fallback path. Acceptance bar: ≥5 useful survivors from the 50-record labelled.jsonl (test currently pins 28/50). No LLM curation, but Phase-1 heuristics keep the pipeline alive.
result: pass
evidence: |
  `tests/integration/test_degraded_mode.py::test_llm_down_keeps_useful_results` GREEN.
  respx.head /healthz returns 503; respx.post /v1/chat/completions returns 503; `router_health_check()` returns False; heuristic fallback yields 28/50 useful survivors from Phase 1's labelled.jsonl. Well above ≥5 bar. LLM-06 hardening proven.

### 10. Catalog price extraction rate ≥85% across Phase 1 fixtures
expected: In-process sweep of all `tests/fixtures/catalog/*/*.html` through `visit.extract_product()`. ≥85% of fixtures yield a non-null price via the jsonld→og→microdata→regex cascade. Test currently pins 10/10 = 100%. Per-fixture forensic details list (filename, has_price, price) emitted on failure.
result: pass
evidence: |
  `tests/integration/test_catalog_extraction.py::test_catalog_price_extraction_rate_above_85_percent` GREEN.
  10/10 = 100% extraction rate across all Phase 1 catalog fixtures (argautopartes, autodo, casasusy, dphidraulica, falabella, lspalermo, martinmorris, mayoristafrog, mipol, reps). D12 hand-roll decision validated in production gate.

## Summary

total: 10
passed: 10
issues: 0
pending: 0
skipped: 0

## Gaps

[none — all 10 tests passed]

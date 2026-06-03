---
phase: 03
fixed_at: 2026-06-03T22:30:00Z
review_path: .planning/phases/03-robustness/03-REVIEW.md
iteration: 1
findings_in_scope: 12
fixed: 12
skipped: 0
status: all_fixed
---

# Phase 3: Code Review Fix Report

**Fixed at:** 2026-06-03T22:30:00Z
**Source review:** `.planning/phases/03-robustness/03-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope (Critical + Warning): 12
- Fixed: 12
- Skipped: 0

Info-tier findings (IN-01..IN-06) were excluded from this iteration's scope
per `fix_scope: critical_warning`.

After every fix, the full suite (`uv run pytest -x -q`) was re-run; the
final state is **65 passed, 2 skipped** (the 2 skips are e2e tests
gated off by default).

## Fixed Issues

### CR-01 + WR-08: Constant-time API key compare and whitespace-strip header

**Files modified:** `src/artiscrapper/auth.py`
**Commit:** `b151101`
**Applied fix:**
- Imported `hmac` at module top.
- Replaced `if key not in API_KEYS` (which falls back to non-constant-time
  `str.__eq__` once the hash bucket matches) with a loop of
  `hmac.compare_digest(key, valid)` over each configured key. Cost is
  negligible on the 1–2 keys of the single-tenant Sánchez Repuestos deploy.
- Stripped the incoming `X-API-Key` header value so whitespace-only ("   ")
  is reported as `Missing X-API-Key header` rather than `Invalid API key`,
  mirroring `_parse_api_keys()` which already drops whitespace-only tokens
  from `API_KEYS`.
- Re-verified `tests/test_auth.py` (3 tests) — all green.

### CR-02: Wrap `sentry_sdk.init()` in try/except so malformed DSN cannot crash boot

**Files modified:** `src/artiscrapper/logging_setup.py`
**Commit:** `f1a531b`
**Applied fix:**
- Wrapped the `sentry_sdk.init(...)` call inside `_init_sentry()` in a
  bare `try/except Exception: pass`. The existing lifespan log line
  (`sentry_init_done` / `sentry_init_skipped`, driven by
  `sentry_sdk.get_client().is_active()` in `main.py`) already declares the
  end state correctly, so a swallowed init failure is fully observable
  downstream without crashing app boot.
- OBS-05 preserved: the DSN value is not logged on failure.
- Re-verified `tests/test_sentry_init.py` (5 tests) — all green.

### CR-03: Gate `/health/deep` behind `verify_api_key`

**Files modified:** `src/artiscrapper/main.py`, `tests/test_health.py`
**Commit:** `55e7c79`
**Applied fix:**
- Added `_api_key: str = Depends(verify_api_key)` to the `health_deep`
  route signature. `/health` (cheap, no Chromium, no outbound) remains
  unauthenticated for the load balancer.
- Updated `tests/test_health.py` to merge `test-key-health` into
  `os.environ["API_KEYS"]` (cross-test contract preserved), refresh
  `auth.API_KEYS`, and send `X-API-Key: test-key-health` on the
  `/health/deep` request.
- Re-verified `tests/test_health.py` (2 tests) — all green.

### WR-01: Revert in-memory `_STATE` if `_persist` raises inside `record_block`

**Files modified:** `src/artiscrapper/challenge_backoff.py`
**Commit:** `66cfb6c`
**Applied fix:**
- Snapshot the pre-mutation `(retry_count, last_block_at, next_allowed_at)`
  tuple before incrementing.
- Apply new values, then `await _persist(cache)` inside `try`; on
  exception, restore the snapshot and re-raise. This keeps in-memory and
  durable state consistent so a post-restart container cannot re-open
  the gate 60s × 2^N too early.
- Re-verified `tests/test_challenge_backoff.py` (7 tests) — all green.

### WR-02 + WR-07: Protect `record_block`/`record_success` and gate success on real candidates

**Files modified:** `src/artiscrapper/main.py`
**Commit:** `2076fbf`
**Applied fix:**
- Wrapped `await record_block(request.app.state.cache)` in `try/except`
  emitting `log.warning("record_block_failed", error=type(exc).__name__)`
  so a transient sqlite error cannot turn a genuine block into an opaque
  500 — the `block_detected=true` consumer contract is preserved.
- Moved `record_success` from BEFORE `parse_serp` to AFTER merge +
  dedupe + junk-blocklist, and guarded with `if all_candidates:`. A
  consent interstitial or empty-results page that bypassed
  `_detect_block` no longer resets `retry_count=0` and reopens the
  gate — exactly the failure mode D-07's ≥1h gate was designed to
  prevent. Wrapped in try/except symmetrically with `record_block`.
- Re-verified `tests/test_auth.py`, `tests/test_challenge_backoff.py`,
  `tests/test_health.py`, `tests/integration/test_challenge_backoff.py` —
  all green.

### WR-03: Strong-ref `_write_cache` task so GC cannot drop it mid-flight

**Files modified:** `src/artiscrapper/main.py`
**Commit:** `37368a0`
**Applied fix:**
- Initialized `app.state.background_tasks = set()` in lifespan after the
  recycle/prune tasks are created.
- In `/search`, captured the cache-write task into a local var, added
  it to `app.state.background_tasks`, and registered
  `task.add_done_callback(app.state.background_tasks.discard)` so the
  ref persists for the task lifetime and is dropped on completion.
- This implements the upstream `asyncio.create_task` documentation's
  explicit warning about weak refs.
- Re-verified `pytest` (54 passed in unit + integration) — all green.

### WR-04: `setdefault` instead of hard-set for `CACHE_DB_PATH` in two test files

**Files modified:** `tests/integration/test_metrics_endpoint.py`, `tests/test_sentry_init.py`
**Commit:** `fa7e15a`
**Applied fix:**
- Changed `os.environ["CACHE_DB_PATH"] = _tmp_db.name` to
  `os.environ.setdefault("CACHE_DB_PATH", _tmp_db.name)` in both files.
- Added comments referencing the cross-test contract already documented
  in `tests/integration/test_challenge_backoff.py` and
  `tests/test_auth.py`.
- Re-verified both files' tests (7 tests) — all green.

### WR-05: Narrow `add_correlation_id` Sentry catch and surface drift via one-shot flag

**Files modified:** `src/artiscrapper/logging_setup.py`
**Commit:** `fcc4d3a`
**Applied fix:**
- Added module-level `_sentry_tag_warned: bool = False` flag (process
  lifetime).
- Narrowed the catch around
  `sentry_sdk.get_current_scope().set_tag("correlation_id", cid)` from
  bare `Exception` to `(AttributeError, RuntimeError)` — the two real
  shapes of SDK drift (renamed method/attribute; scope not initialized).
  Other exception types now propagate through the structlog processor
  chain where `format_exc_info` captures them.
- On the first miss, leave `sentry_tag_failed: True` on the event dict
  so drift is observable in structured logs once, not silently every
  event.
- Re-verified `tests/test_sentry_init.py` (5 tests) — all green.

### WR-06: Correct misleading `/metrics` mount docstring and anchor test

**Files modified:** `src/artiscrapper/main.py`, `tests/test_footguns.py`
**Commit:** `76d2637`
**Applied fix:**
- Rewrote the inline mount comment in `main.py` to drop the false claim
  that `CorrelationIdMiddleware` does not wrap `/metrics`. Starlette
  installs middleware at the ASGI level so the sub-app IS wrapped — the
  real invariant is only that the middleware in use stays harmless on a
  `/metrics` request, and the per-route mechanisms (slowapi limits,
  `verify_api_key` Depends) skip the sub-app. Noted the
  `prometheus_client.start_http_server` admin-port migration path for
  the day that stops being true.
- Updated `tests/test_footguns.py` docstring and assertion message to
  drop the false bypass claim. The grep-for-`make_asgi_app()` check is
  preserved — it still pins the mount shape, which is what the test was
  ever actually validating.
- Re-verified `tests/test_footguns.py` and
  `tests/integration/test_metrics_endpoint.py` (9 tests) — all green.

### WR-09: Assert exactly-one `sentry_init_*` log line and clear caplog before boot

**Files modified:** `tests/test_sentry_init.py`
**Commit:** `c74ef6c`
**Applied fix:**
- Called `caplog.clear()` immediately before the `with TestClient(...)`
  block so only events from the current parametrization land in the
  buffer.
- Replaced the `sentry_lines[-1]`-style "last match" grep with a strict
  `len(matches) == 1` assertion against `expected_event`, pinning the
  observable side-effect directly (Phase 2 feedback
  `feedback_empirical_retest_after_default_changes`).
- The cross-check against `sentry_sdk.get_client().is_active()` is
  preserved.
- Re-verified `tests/test_sentry_init.py` (5 tests, both parametrizations
  of the lifespan test) — all green.

## Skipped Issues

None — every in-scope finding was fixed and committed atomically.

---

_Fixed: 2026-06-03T22:30:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_

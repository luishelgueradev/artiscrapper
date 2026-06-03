---
phase: 03-robustness
reviewed: 2026-06-03T21:00:00Z
depth: standard
files_reviewed: 21
files_reviewed_list:
  - src/artiscrapper/auth.py
  - src/artiscrapper/cache.py
  - src/artiscrapper/challenge_backoff.py
  - src/artiscrapper/config.py
  - src/artiscrapper/llm.py
  - src/artiscrapper/logging_setup.py
  - src/artiscrapper/main.py
  - src/artiscrapper/metrics.py
  - src/artiscrapper/visit.py
  - tests/fixtures/serp/blocks/sorry.html
  - tests/integration/__init__.py
  - tests/integration/conftest.py
  - tests/integration/test_catalog_extraction.py
  - tests/integration/test_challenge_backoff.py
  - tests/integration/test_degraded_mode.py
  - tests/integration/test_metrics_endpoint.py
  - tests/integration/test_rate_limit.py
  - tests/test_auth.py
  - tests/test_challenge_backoff.py
  - tests/test_footguns.py
  - tests/test_sentry_init.py
findings:
  critical: 3
  blocker: 3
  warning: 9
  info: 6
  total: 18
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-06-03T21:00:00Z
**Depth:** standard
**Files Reviewed:** 21
**Status:** issues_found

## Summary

Phase 3 introduces the robustness primitives (X-API-Key auth, Prometheus metrics,
Sentry init, per-API-key rate-limit, challenge-backoff state machine). The work is
generally well-structured and the test suite is unusually thorough — but the
adversarial pass surfaces three BLOCKER-class defects in the new attack surface
(auth + observability + secrets) and several WARNING-class robustness gaps in
the new state machine and lifespan.

Highest-impact findings:

1. **CR-01 — Non-constant-time API-key comparison** (auth bypass / timing oracle).
2. **CR-02 — Sentry init at module-import time has no try/except**: a malformed
   `SENTRY_DSN` (typo in compose) crashes app boot before any logging is wired,
   producing an opaque container failure with no observability.
3. **CR-03 — Bearer token transmitted to `/health/deep` is reachable by any
   unauthenticated caller** and consumes a real Chromium navigation per call —
   trivial unauthenticated DoS surface that also burns the LLM bearer against
   the configured router URL.

The challenge-backoff state machine has a subtle write-then-persist race
(WR-01) where an in-memory increment can survive an sqlite write failure,
producing in-memory/durable divergence after restart. The `/search` route does
NOT wrap `record_block` in try/except (WR-02) so a sqlite outage during a
genuine Google block turns into an opaque 500 instead of the contractual
`block_detected=true` response. The fire-and-forget `_write_cache` task
(WR-03) is created via bare `asyncio.create_task` without holding a reference,
which Python's docs explicitly call out as a GC-eligibility bug.

Two integration test files (`test_metrics_endpoint.py`, `test_sentry_init.py`)
hard-set `os.environ["CACHE_DB_PATH"]` instead of `setdefault()`, violating the
cross-test contract that the other Phase 3 test files painstakingly document —
this will silently corrupt sibling tests' state when test ordering changes
(WR-04).

Phase 3 is otherwise consistent with its plan documents and pins its
invariants well; the findings below all describe real defects (not style),
each with a concrete remediation.

## Critical Issues (BLOCKER)

### CR-01: Non-constant-time API-key comparison — timing oracle for key enumeration

**File:** `src/artiscrapper/auth.py:63-68`
**Issue:** `verify_api_key` uses `if key not in API_KEYS` where `API_KEYS` is
a Python `set[str]`. CPython `__contains__` on a set hashes the input then
probes — and once the hash bucket matches a candidate, `__eq__` falls back to
byte-by-byte string comparison. That last step is **not constant-time** and
leaks per-byte equality timing. For an auth check that protects the entire
`/search` surface (and which the project calls out as a security boundary in
the Phase 3 plan), this is the standard footgun: `hmac.compare_digest` is
the documented mitigation in the Python stdlib for exactly this case
(`secrets` module docs explicitly warn against bare `==` / `in` for secret
comparison).

The risk is amplified because the key set is small (single-tenant Sánchez
Repuestos deploy → typically 1–2 keys) and stable across the process lifetime,
giving an attacker a steady oracle to probe.

**Fix:**
```python
import hmac

def verify_api_key(request: Request) -> str:
    key = request.headers.get("X-API-Key")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    # Constant-time comparison against every configured key. Iterates the
    # full set on every call but the set is tiny (1-2 keys for the
    # Sánchez Repuestos deploy), so the cost is negligible.
    for valid in API_KEYS:
        if hmac.compare_digest(key, valid):
            return key
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )
```

### CR-02: `_init_sentry()` at module-import time is unguarded — malformed DSN crashes app boot

**File:** `src/artiscrapper/logging_setup.py:113-131,137`
**Issue:** `_init_sentry()` is called at the bottom of the module
(`_init_sentry()` on line 137), so it runs at the first `import` of
`logging_setup`. Inside `_init_sentry`, `sentry_sdk.init(dsn=dsn, ...)`
is invoked with the raw env-var DSN and there is no try/except. If a
production compose file has a malformed `SENTRY_DSN` (typo, mid-rotation
truncation, wrong scheme), `sentry_sdk.init` raises `InvalidDsn` and the
exception propagates up through `from .logging_setup import ...` in
`main.py` (line 46) — crashing app startup BEFORE `configure_logging()`
ever runs, so the failure surfaces only as an opaque non-zero exit in
the container logs. The file's own docstring even states "observability
code must not be load-bearing" (line 30) — `_init_sentry` violates that
exact invariant.

**Fix:**
```python
def _init_sentry() -> None:
    dsn = settings.SENTRY_DSN
    if not dsn:
        return
    try:
        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=0.1,
            profiles_sample_rate=0.0,
            send_default_pii=False,
        )
    except Exception:
        # OBS-05: do NOT log the DSN value. A misconfigured DSN must
        # never be load-bearing for app boot. The lifespan log line
        # `sentry_init_skipped` already declares the end state via
        # sentry_sdk.get_client().is_active() in main.py.
        pass
```

### CR-03: `/health/deep` is unauthenticated, forwards the LLM bearer, and consumes Chromium navigation

**File:** `src/artiscrapper/main.py:272-316`
**Issue:** `/health/deep` is registered without `Depends(verify_api_key)`,
so any unauthenticated caller can:

  1. Trigger a real Chromium `new_context()`/`new_page()`/`goto("about:blank")`
     round-trip per request (line 285-290) — burning real browser resources
     and the GoogleRateLimiter slot. The docstring notes "NEVER call from
     load balancer" but nothing in the code enforces that.
  2. Trigger an outbound HTTP GET to `settings.LLM_ROUTER_URL` carrying the
     `LLM_ROUTER_BEARER_TOKEN` (line 308-311). If the host can ever be
     reached by an attacker (direct port exposure, SSRF chain, container
     mis-network), the bearer token leaves the box on demand.

This combination makes `/health/deep` a free unauthenticated DoS knob AND a
bearer-token exfiltration trigger. The Phase 3 plan added a real auth layer
to `/search`; the same protection should extend to any endpoint that
performs side-effectful work.

**Fix:** Gate `/health/deep` behind the same auth dependency as `/search`,
or expose it only on a private admin port. Keep the unauthenticated `/health`
(cheap, no Chromium, no outbound) for the LB.

```python
@app.get("/health/deep")
async def health_deep(
    request: Request,
    _api_key: str = Depends(verify_api_key),
) -> dict:
    ...
```

## Warnings

### WR-01: `record_block` mutates in-memory `_STATE` before sqlite persist — divergence on write failure

**File:** `src/artiscrapper/challenge_backoff.py:183-188`
**Issue:** Inside the `_LOCK`, the sequence is:

```python
_STATE.retry_count += 1
wait_s = min(_BASE_S * (2 ** (_STATE.retry_count - 1)), _BACKOFF_CAP_S)
_STATE.last_block_at = now
_STATE.next_allowed_at = now + wait_s
await _persist(cache)   # ← can raise (sqlite full, locked, IO error)
```

If `_persist` raises, the in-memory `_STATE` has already advanced (retry_count++,
next_allowed_at moved forward) but the sqlite row has not. The exception
propagates out of `record_block` to `main.py`, where it is NOT caught
(see WR-02). Worse: if the next caller hits `check_gate`, the in-memory
`_STATE` correctly denies — but after a container restart, the durable row
reverts to the previous state, so the gate opens *too early* by 60s × 2^N.

**Fix:** Persist first to a local snapshot, then publish. Or wrap the
persist + revert the in-memory change on failure:

```python
async with _LOCK:
    ...
    new_count = _STATE.retry_count + 1
    wait_s = min(_BASE_S * (2 ** (new_count - 1)), _BACKOFF_CAP_S)
    prev = (_STATE.retry_count, _STATE.last_block_at, _STATE.next_allowed_at)
    _STATE.retry_count = new_count
    _STATE.last_block_at = now
    _STATE.next_allowed_at = now + wait_s
    try:
        await _persist(cache)
    except Exception:
        # Revert in-memory to keep durable + memory consistent
        (_STATE.retry_count, _STATE.last_block_at, _STATE.next_allowed_at) = prev
        raise
```

### WR-02: `/search` does not wrap `record_block` / `record_success` in try/except — sqlite outage turns into uncaught 500

**File:** `src/artiscrapper/main.py:468,484`
**Issue:** Both `await record_block(request.app.state.cache)` (line 468, on
the block-detected branch) and `await record_success(request.app.state.cache)`
(line 484, on the success path) can raise — sqlite is reachable through a
single shared `aiosqlite.Connection`, and the prune loop, challenge_backoff,
and `/search` all write to it. A transient sqlite error (disk full, WAL
locked, busy timeout exhausted) at exactly the moment a block is detected
will raise out of `record_block`, bypass the `return SearchResponse(...)` on
line 470, and produce an opaque 500. The block-detection telemetry already
ran (`inc_block_detected`) but the user sees a 500 instead of the contractual
`block_detected=true` response shape, breaking the consumer contract spelled
out in the route docstring.

This is the same fail-closed-but-noisy footgun Phase 2 hit elsewhere — the
observability path must not be load-bearing for the response shape.

**Fix:**
```python
if block_a or block_b:
    block_detected = True
    block_reason = block_a or block_b
    log.warning("google_fetch_blocked", reason=block_reason)
    inc_block_detected(block_reason)
    try:
        await record_block(request.app.state.cache)
    except Exception as exc:
        log.warning("record_block_failed", error=type(exc).__name__)
    elapsed_ms = int((time.time() - t_start) * 1000)
    return SearchResponse(...)

# … and symmetrically for record_success on the success branch.
```

### WR-03: `_write_cache` background task is GC-eligible — fire-and-forget without strong reference

**File:** `src/artiscrapper/main.py:601-617`
**Issue:** `asyncio.create_task(_write_cache())` is the only reference to
the created task and it's not retained anywhere. Python's `asyncio.create_task`
docs explicitly warn:

> Important: Save a reference to the result of this function, to avoid a
> task disappearing mid-execution. The event loop only keeps weak references
> to tasks.

Under load (or with a slow sqlite write), the task can be garbage-collected
mid-execution, silently dropping the cache write AND the warning log line
that `_write_cache` was supposed to emit on failure. This is a real bug
documented upstream — not theoretical.

**Fix:** Keep a strong reference on `app.state` and use a done-callback to
drop it after completion:

```python
# In main.py module-or-app scope:
app.state.background_tasks = set()

# In the handler:
task = asyncio.create_task(_write_cache())
request.app.state.background_tasks.add(task)
task.add_done_callback(request.app.state.background_tasks.discard)
```

### WR-04: Two integration test files clobber `CACHE_DB_PATH` instead of using `setdefault` — cross-test contract violation

**File:** `tests/integration/test_metrics_endpoint.py:22`,
`tests/test_sentry_init.py:32`
**Issue:** `tests/integration/test_challenge_backoff.py` (lines 49-58) and
`tests/test_auth.py` (lines 25-58) document an explicit cross-test contract:

> Use `setdefault` for `CACHE_DB_PATH` (don't clobber a sibling's tmpfile path)

Both `test_metrics_endpoint.py` line 22 and `test_sentry_init.py` line 32 use
the hard-set form:

```python
os.environ["CACHE_DB_PATH"] = _tmp_db.name   # ← BUG: clobbers sibling
```

Because the `app` and `settings` are PROCESS-singletons captured at first
import, whichever test file imports first wins. If pytest's collection
order shifts (e.g., adding a new test file, running with `-k`), the metrics
or sentry tests will overwrite a sibling's tempfile path AFTER the sibling
has already populated state into the original db, producing flaky
"challenge_state row missing" or "api_keys_empty" failures.

**Fix:**
```python
os.environ.setdefault("CACHE_DB_PATH", _tmp_db.name)
```

### WR-05: `_init_sentry` Sentry-state tag race / unbounded swallowed exception in `add_correlation_id`

**File:** `src/artiscrapper/logging_setup.py:50-53`
**Issue:** `add_correlation_id` is invoked on EVERY log call (structlog
processor chain). It calls `sentry_sdk.get_current_scope().set_tag(...)`
under a bare `try/except Exception`. Under high request concurrency this
is an O(N_log_events) call into the Sentry scope, which acquires internal
locks. More importantly: a bare `except Exception` here masks *all*
sentry-sdk regressions silently — including a future API rename of
`set_tag`. The intent ("must never break a request") is correct, but the
unconditional silencing means an SDK breakage is invisible until someone
spot-checks a Sentry event.

**Fix:** Narrow the catch to known exception types (e.g.,
`(AttributeError, RuntimeError)`) and log a single warning the first time
it fires so SDK drift is observable:

```python
_sentry_tag_warned = False

if cid:
    event_dict["correlation_id"] = cid
    try:
        sentry_sdk.get_current_scope().set_tag("correlation_id", cid)
    except Exception:
        global _sentry_tag_warned
        if not _sentry_tag_warned:
            event_dict["sentry_tag_failed"] = True
            _sentry_tag_warned = True
```

### WR-06: `metrics.py` `/metrics` mount comment is misleading — CorrelationIdMiddleware DOES wrap mounted ASGI sub-apps

**File:** `src/artiscrapper/main.py:238-241,229-233`
**Issue:** The comment on line 238-240 claims:

> /metrics is mounted as an ASGI sub-app so it bypasses FastAPI middleware
> (no slowapi, no CorrelationIdMiddleware, no auth dependency).

The "no slowapi" and "no auth" parts are correct (those are per-route
mechanisms, not middleware). But `CorrelationIdMiddleware` is added via
`app.add_middleware(...)` (line 244), which Starlette installs at the
ASGI level — it wraps ALL routes AND mounted sub-apps. So `/metrics`
actually DOES go through `CorrelationIdMiddleware`. The footgun test
`test_metrics_endpoint_unprotected_by_design` only greps for
`make_asgi_app()` and never validates the middleware-bypass claim — so
the test is a false anchor.

If anything in `CorrelationIdMiddleware` ever raises on a malformed request,
`/metrics` will go down WITH the rest of the app, breaking the
"scrape-must-survive-everything" expectation for Prometheus.

**Fix:** Either correct the docstring AND test to acknowledge that the
middleware does wrap `/metrics` (and verify it stays harmless), or
mount `/metrics` BEFORE `add_middleware` and use `app.router.mount(...)`
patterns that bypass the middleware chain (FastAPI/Starlette has limited
support; the simplest path is to run `/metrics` on a separate
`prometheus_client.start_http_server(...)` port).

### WR-07: `record_success` clears block state on EMPTY-SERP parses — false-recovery if Google returns 200 with no SERP cards

**File:** `src/artiscrapper/main.py:484`
**Issue:** `record_success` is called immediately after the block-detected
branch (line 484), BEFORE `parse_serp` runs. If Google returns 200 OK with
a non-block page but the SERP parser yields zero candidates (consent
interstitial that bypassed `_detect_block`, A/B test of a new SERP layout,
empty-results page), the success path resets `retry_count=0` and reopens
the gate. The next request walks straight back into Google, restarting
the backoff curve from scratch instead of holding the cool-off window.

This converts a single missed-detector signal into "we restart backoff on
every retry" — exactly the failure mode the D-07 ≥1h gate was designed to
prevent.

**Fix:** Move `record_success` AFTER the parse step and only call it when
at least one candidate survives dedupe + junk-blocklist (a real product
landed, not an empty page):

```python
# after [5] merge+dedupe+blocklist
if all_candidates:
    await record_success(...)
```

### WR-08: `verify_api_key` accepts whitespace-only key as "Invalid", not "Missing"

**File:** `src/artiscrapper/auth.py:56-68`
**Issue:** `key = request.headers.get("X-API-Key")` then `if not key` catches
`None` and `""` but `"   "` (whitespace-only) is truthy and falls through to
the `if key not in API_KEYS` branch. The 401 response says "Invalid API key"
when conceptually the header is empty. The mirror bug: `_parse_api_keys()`
strips whitespace AND drops empty tokens, so a configured key with only
whitespace is dropped from `API_KEYS` — but a request-supplied whitespace
key never matches. The detail strings would mislead an operator debugging
why their compose-file key fails.

**Fix:** Strip the header value before both checks:

```python
key = (request.headers.get("X-API-Key") or "").strip()
if not key:
    raise HTTPException(401, detail="Missing X-API-Key header", ...)
```

### WR-09: `test_sentry_init.py::test_lifespan_log_matches_sdk_state` greps last match — silently passes if multiple `sentry_init_*` events leak across reloads

**File:** `tests/test_sentry_init.py:194-209`
**Issue:** The test scans `caplog.messages` for any line containing
`sentry_init_done` OR `sentry_init_skipped` and inspects `sentry_lines[-1]`.
Because `importlib.reload(main_mod)` is called before each parametrization
of this test, a prior reload's lifespan log can survive in `caplog` if
pytest's caplog capture isn't reset between parametrizations. The assertion
"the last line matches" lets a stale earlier event slip through if the new
event also lands but with a different content. The forensic-failure message
prints only the last 30 messages.

This is the same shape as the Phase 2 lesson `feedback_empirical_retest_after_default_changes`
— assert on the OBSERVABLE side-effect, not on a `last_match`-style grep.

**Fix:** Filter messages to ones emitted INSIDE the `with TestClient`
block (e.g., wrap the boot in a `caplog.clear()` immediately before and
assert that EXACTLY one matching event appears, not the last):

```python
caplog.clear()
caplog.set_level(_logging.INFO)
with TestClient(main_mod.app):
    pass

matches = [m for m in caplog.messages
           if expected_event in m]
assert len(matches) == 1, (
    f"WRN-04: expected exactly one {expected_event} line; "
    f"got {len(matches)}: {matches}"
)
```

## Info

### IN-01: `add_correlation_id` re-imports `asgi_correlation_id` on every log event

**File:** `src/artiscrapper/logging_setup.py:36-44`
**Issue:** The `from asgi_correlation_id import correlation_id` (and the
4.x fallback path) is inside the function body, so it runs on every log
call. Python's import system caches imported modules in `sys.modules` so
the actual import is fast, but the `try/except (ImportError, AttributeError)`
machinery still allocates exception-handling state per event. Move the
import resolution to module-load time:

```python
# At module top:
try:
    from asgi_correlation_id import correlation_id as _correlation_id_ctx
except (ImportError, AttributeError):
    try:
        from asgi_correlation_id.context import correlation_id as _correlation_id_ctx
    except (ImportError, AttributeError):
        _correlation_id_ctx = None

def add_correlation_id(_logger, _method, event_dict):
    if _correlation_id_ctx is not None:
        try:
            cid = _correlation_id_ctx.get()
        except LookupError:
            cid = None
        ...
```

### IN-02: `cache.py` `prune_loop` size-cap deletes only 100 rows/hour — could take days to recover from a flood

**File:** `src/artiscrapper/cache.py:147-154`
**Issue:** When `bytes_total > 2_000_000_000`, only 100 oldest rows are
deleted per loop iteration (hourly). If a burst pushes the cache to 4 GB,
recovery takes ~24 hours. Loop the delete-100 inside the `if total > 2GB`
branch until under the cap, or scale the delete count to the overage.
Not a correctness bug — operational only — but worth a comment so a
future operator knows what to expect.

### IN-03: `test_challenge_backoff.py::test_503_with_retry_after` does not pin r1.status_code

**File:** `tests/integration/test_challenge_backoff.py:228-232`
**Issue:** The first request asserts `body1.get("metadata", {}).get("block_detected") is True`
but never asserts `r1.status_code`. If a future refactor changes the
Phase 2 block-detected branch from 200 to 503, the test still passes
silently (body shape is the same). Add the status assertion:

```python
assert r1.status_code in (200, 503), (
    f"request 1: expected 200 (Phase 2 contract) or 503 (gate path); "
    f"got {r1.status_code}"
)
```

### IN-04: `tests/integration/conftest.py::reset_challenge_backoff_state` keeps an `ImportError` fallback that is now dead code

**File:** `tests/integration/conftest.py:41-49`
**Issue:** The docstring notes "challenge_backoff.py is owned by Plan 03-02
and may not exist yet — tolerate the ImportError gracefully." Plan 03-02 has
shipped (`src/artiscrapper/challenge_backoff.py` is present and tested).
The `try/except ImportError` is now dead defensive code that masks a real
regression (e.g., someone accidentally deletes the module — the autouse
fixture would silently keep working). Either drop the fallback OR make the
import error visible.

### IN-05: `tests/test_challenge_backoff.py:214` — `except (AttributeError, Exception):` redundancy

**File:** `tests/integration/test_challenge_backoff.py:214`, `tests/integration/test_rate_limit.py:94,106`, `tests/test_auth.py:112`
**Issue:** `except (AttributeError, Exception)` is redundant because
`AttributeError` is already a subclass of `Exception`. Simplify to
`except Exception:` (with a brief comment about why catching broadly is
intentional). Minor — does not affect correctness.

### IN-06: `tests/integration/__init__.py` is an empty file — confirm intentional package marker

**File:** `tests/integration/__init__.py`
**Issue:** Empty file (0 bytes). This is fine as a Python package marker
(allows `tests.integration.*` imports), but with `pytest` auto-discovery,
having an `__init__.py` in `tests/integration/` can interact badly with
namespace-package semantics if a sibling `tests/` directory ever shares
`__init__.py`. Recommend either documenting the marker intent with a
one-line module docstring OR removing it if not needed for explicit
import.

---

_Reviewed: 2026-06-03T21:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

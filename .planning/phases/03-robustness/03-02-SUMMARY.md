---
phase: 03-robustness
plan: 02
subsystem: resilience+integration-suite
tags: [aiosqlite, asyncio-lock, module-singleton, fastapi, slowapi, respx, tldextract, selectolax, fixture-replay, exponential-backoff]

# Dependency graph
requires:
  - phase: 03-robustness
    provides: "Plan 03-01 main.py shape (verify_api_key Depends, `with search_elapsed.time():` bracket, slowapi decorators, inc_block_detected bridge wrapper, 3 D-19 lifespan log lines)"
  - phase: 02-mvp
    provides: "browser._detect_block markers (BLOCK_MARKERS tuple), main.py 10-step /search pipeline, cache.py aiosqlite WAL + INSERT OR REPLACE pattern, llm.py resolve_model module-singleton + asyncio.Lock pattern, visit.py extract_product (D12 jsonld→og→microdata→regex cascade)"
provides:
  - "Module-singleton ChallengeBackoff state machine: check_gate / record_block / record_success on a single aiosqlite.Connection (D-05 / D-06 / D-07 / D-08)"
  - "/search 503 + Retry-After response when the gate denies (D-09); existing block-detection branch arms the gate via record_block"
  - "4th D-19 lifespan log line `challenge_backoff_init` declaring base_s/cap_s/reset_after_s — empirically verified in container logs"
  - "challenge_state sqlite single-row table with CHECK(id=1) constraint + INSERT OR IGNORE idempotent seed; survives `docker compose up --force-recreate`"
  - "Synthetic `/sorry/` fixture under tests/fixtures/serp/blocks/sorry.html (D-20, Phase 1 captured no real one)"
  - "Per-fixture pinned integration tests (D-18): degraded-mode survivor count (≥5 from 50-record labelled set), catalog price-extraction rate (≥85%)"
affects: [03-02-acceptance-closes-ROADMAP-4-5-6, future-phase-4-multi-tenant]

# Tech tracking
tech-stack:
  added: []  # All deps were added by Plan 03-01 — this plan only wires patterns
  patterns:
    - "S1 module-singleton + asyncio.Lock + double-checked-lock (mirrors llm.py::resolve_model verbatim)"
    - "S2 INSERT OR REPLACE with parameterized ? placeholders + immediate commit (mirrors cache.py::set_cached)"
    - "S5 TestClient + monkeypatched cloakbrowser launch_async + mock_browser (for integration tests)"
    - "S6 respx.head mocks on /healthz (NOT respx.get — router_health_check uses client.head)"
    - "S7 per-fixture pinned assertions with details list (D-18 — never `len > 0` shape checks)"
    - "Cross-test env-var MERGE (not REPLACE) so sibling test files' module-level API_KEYS stay valid"
    - "Live-env rebuild of `auth.API_KEYS` in test setup (cannot use cached settings.API_KEYS)"

key-files:
  created:
    - src/artiscrapper/challenge_backoff.py
    - tests/fixtures/serp/blocks/sorry.html
    - tests/test_challenge_backoff.py
    - tests/integration/test_challenge_backoff.py
    - tests/integration/test_degraded_mode.py
    - tests/integration/test_catalog_extraction.py
  modified:
    - src/artiscrapper/cache.py
    - src/artiscrapper/main.py
    - tests/test_auth.py
    - tests/integration/test_rate_limit.py

key-decisions:
  - "Constants (_BASE_S/_BACKOFF_CAP_S/_RESET_AFTER_S) are hardcoded module-level (D-06 ROADMAP-lock) — NOT thread-able through settings (Pitfall 6 — settings/contract/route shadowing class of bugs from Phase 2)"
  - "record_block + record_success acquire _LOCK and read state DIRECTLY (bypass _load) to avoid lock re-entry; only check_gate uses double-checked-load on the read path"
  - "When the gate denies, return FastAPI `Response(status_code=503, ...)` NOT `HTTPException(status_code=503, headers=...)` — HTTPException's headers param doesn't preserve the SearchResponse pydantic shape (03-RESEARCH.md §D3)"
  - "sorry.html lives under `tests/fixtures/serp/blocks/sorry.html` (NOT directly in `tests/fixtures/serp/`) so the existing `test_parse_serp_fixtures` glob `*.html` doesn't count it (would have flipped `assert len(fixture_files) == 10` to 11)"
  - "test_challenge_backoff.py + test_auth.py + test_rate_limit.py use a defensive env-var MERGE pattern — they APPEND their test key to existing API_KEYS instead of REPLACING. After import, they refresh `auth.API_KEYS` from the LIVE env (NOT via `_parse_api_keys()` which reads cached `settings.API_KEYS`). This closes a pre-existing cross-test ordering fragility that Plan 03-02's new test file exposed."

patterns-established:
  - "ChallengeBackoff mirrors `llm.py::resolve_model` verbatim (Pattern S1 — module-singleton + asyncio.Lock + double-checked-load). Confirms the project's discipline of reusing established async-state patterns instead of inventing new ones."
  - "Per-fixture pinned integration tests with forensic details list (D-18 — test_catalog_extraction yields `[(filename, has_price, price), ...]` in the failure message so a regression points at the EXACT host that broke)."
  - "Cross-test env-var merge contract — every test file that mutates `os.environ['API_KEYS']` must APPEND its key (not replace) AND rebuild `auth.API_KEYS` from the live env. Documented in `tests/integration/test_challenge_backoff.py` module docstring as the canonical reference."

requirements_completed: []
# Phase 3 plan 03-02 introduces NO new v1 requirements.
# It hardens BROWSER-05 (sorry detection), LLM-06 (degraded mode),
# D12 (catalog extraction), NF-02 (parser tests), NF-03 (test gates).
# Their `requirements_completed` lives on the Phase 2 SUMMARY that
# originally satisfied them.

# Metrics
duration: ~30 min
completed: 2026-06-03
---

# Phase 3 Plan 02: ChallengeBackoff + degraded mode + integration suite Summary

**Google challenge-detection backoff state machine with exponential `min(60 * 2^(retries-1), 3600)` curve, sqlite single-row persistence that survives container restart, /search 503+Retry-After when the gate denies, fourth D-19 `challenge_backoff_init` lifespan log line empirically verified in container logs, AND a Phase 1 fixture-replay integration suite that pins ≥85% catalog price extraction (10/10 = 100% measured) plus ≥5 useful survivors from the 50-record LLM-down labelled set (28/50 measured).**

## Performance

- **Duration:** ~30 min (3 task commits from 20:14 → 20:43 UTC)
- **Tasks:** 3 (Wave 0 RED scaffolding → Wave 1 pure module → Wave 2 main.py wiring + empirical retest)
- **Files modified:** 10 (4 new source/fixture + 4 new test + 2 modified sibling test files for cross-test isolation)

## Accomplishments

- **ROADMAP-4 (challenge backoff):** `src/artiscrapper/challenge_backoff.py` ships the state machine. Unit tests pin D-06 curve at 60/120/240/480/960/1920/3600/3600 (retries 1..8) with ±2s tolerance; D-07 reset trigger pinned with `time.time` monkeypatch at +3700s; D-08 persistence pinned by close+reopen of the sqlite db.
- **ROADMAP-5 (degraded mode):** `test_llm_down_keeps_useful_results` pins **28/50 survivors** from Phase 1's labelled.jsonl when router /healthz returns 503 (well above the ≥5 acceptance bar). LLM-06 hardening empirically validated.
- **ROADMAP-6 (D12 catalog):** `test_catalog_price_extraction_rate_above_85_percent` pins **10/10 = 100% extraction rate** across all Phase 1 catalog fixtures (acceptance bar is ≥85%). D12 hand-roll decision validated in production gate.
- **D-09 (503 + Retry-After):** `test_503_with_retry_after` confirms end-to-end wiring — first request hits the existing block-detection branch and arms the gate (via `record_block`); second request returns 503 with a digit-string `Retry-After` header in the [1, 3600] window.
- **D-19 (4th lifespan log line):** `challenge_backoff_init base_s=60 cap_s=3600 reset_after_s=3600` empirically verified in `docker compose logs` after `compose build` + `compose up -d --force-recreate` (separate steps per Phase 2 memory).
- **D-08 container restart preservation (manual UAT, automated by Claude per `feedback_agent_as_uat_operator`):** set `(last_block_at, retry_count=3, next_allowed_at)` in the container's challenge_state row, ran `docker compose up -d --force-recreate`, re-queried — row preserved verbatim. Phase 2 lesson `feedback_compose_build_recreate` honored: NEVER `up -d --build` (always separate steps).

## Task Commits

Each task was committed atomically:

1. **Task 1 (Wave 0):** `83880fa` (test) — DDL extension + sorry.html fixture + 4 RED test files; Phase 2 `test_cache.py` regression check passed (4/4).
2. **Task 2 (Wave 1):** `0c6ea9c` (feat) — `challenge_backoff.py` module; 7 unit tests turn GREEN; module is import-safe (`_STATE=None` until first call); Phase 2 cache + llm tests still GREEN (13/13).
3. **Task 3 (Wave 2):** `3570569` (feat) — main.py wiring (check_gate + record_block + record_success + lifespan log line) + 5 integration tests GREEN + container empirical retest + cross-test env-var merge defense.

## Files Created/Modified

### Created

- `src/artiscrapper/challenge_backoff.py` — module-singleton state machine (`_STATE: _State | None`) + `asyncio.Lock` for read-modify-write serialization. Exports `check_gate(cache)`, `record_block(cache)`, `record_success(cache)` + the introspectable D-06/D-07 constants `_BASE_S=60`, `_BACKOFF_CAP_S=3600`, `_RESET_AFTER_S=3600`. Double-checked-load pattern (Pattern S1) for the read path; `record_block`/`record_success` acquire `_LOCK` and read state directly (bypass `_load`) to avoid lock re-entry. Persistence via `INSERT OR REPLACE INTO challenge_state ... VALUES (1, ?, ?, ?, ?)` (Pattern S2 — parameterized placeholders only, T-02-01-02 from Phase 2).
- `tests/fixtures/serp/blocks/sorry.html` — 404B synthetic /sorry/ stand-in (D-20, Phase 1 captured none per SPIKE.md §Browser). Contains the BLOCK_MARKERS substrings (`unusual traffic`, `g-recaptcha`, `id="captcha-form"`, `sorry/index`) that `browser._detect_block()` scans for. File lives in `blocks/` subdirectory so the existing `test_parse_serp_fixtures` glob doesn't count it.
- `tests/test_challenge_backoff.py` — 7 unit tests: D-06 constants pin, D-06 exponential curve across retries 1..8, D-07 reset after one hour (with time.time monkeypatch), D-07 reset is no-op on recent success, D-08 persistence shape, check_gate returns zero when clear, module-import safety (`_STATE=None`).
- `tests/integration/test_challenge_backoff.py` — 3 tests: sorry.html fixture marker pin (D-20), 503+Retry-After end-to-end via TestClient + monkeypatched `fetch_serp` (D-09), state-survives-restart via close+reopen of aiosqlite db (D-08).
- `tests/integration/test_degraded_mode.py` — `test_llm_down_keeps_useful_results`: respx.head 503 on /healthz + respx.post 503 on /v1/chat/completions, then assert `router_health_check` returns False AND `len(heuristic_survivors) >= 5` from 50-record labelled.jsonl. D-18 alignment: assertion message lists the count and total.
- `tests/integration/test_catalog_extraction.py` — `test_catalog_price_extraction_rate_above_85_percent`: in-process sweep of all `tests/fixtures/catalog/*/*.html` through `visit.extract_product()`, builds per-fixture `(filename, has_price, price)` tuple list, asserts rate ≥ 0.85. D-18 alignment.

### Modified

- `src/artiscrapper/cache.py` — extended `_DDL` with `CREATE TABLE IF NOT EXISTS challenge_state (..., CHECK (id = 1), ...)` + `INSERT OR IGNORE INTO challenge_state ... VALUES (1, NULL, 0, 0, strftime('%s','now'))`. `init_schema` body unchanged — `executescript` already handles multi-statement DDL. Phase 2 regression check passed (4/4 cache tests still GREEN).
- `src/artiscrapper/main.py` — added `from . import challenge_backoff` + `from .challenge_backoff import check_gate, record_block, record_success` imports; 4th D-19 lifespan log line `challenge_backoff_init` BETWEEN `rate_limit_init` and `boot_done` reading `challenge_backoff._BASE_S/_BACKOFF_CAP_S/_RESET_AFTER_S`; new step [1.5] gate AFTER cache-hit early-return INSIDE the `with search_elapsed.time():` block returning `Response(status_code=503, content=denied_body.model_dump_json(), headers={"Retry-After": str(retry_after)})` when `check_gate` denies; `await record_block(...)` in the existing block-detection branch BEFORE the 200-with-block_detected return; `await record_success(...)` after both `_detect_block` calls return None but BEFORE the parser cascade.
- `tests/test_auth.py` — defensive merge: APPENDS our test keys to existing `os.environ["API_KEYS"]` instead of REPLACING; refreshes `auth.API_KEYS` from the LIVE env (NOT via cached `settings.API_KEYS`). Closes a pre-existing cross-test ordering fragility that my new integration test exposed.
- `tests/integration/test_rate_limit.py` — same defensive merge + live-env rebuild as test_auth.py.

## Decisions Made

- **Worktree-mode sorry.html path:** Moved to `tests/fixtures/serp/blocks/sorry.html` (NOT directly in `tests/fixtures/serp/`) because the existing `test_parse_serp_fixtures` test asserts `len(fixture_files) == 10` against a `*.html` glob. Adding sorry.html at the parent level would have flipped the count to 11. The `blocks/` subdirectory pattern leaves room for future block-marker variants (e.g., `recaptcha.html`, `consent_interstitial.html`).
- **Cross-test env-var merge pattern:** Every integration test file that sets `os.environ["API_KEYS"] = ...` now uses an APPEND-not-REPLACE pattern AND rebuilds `auth.API_KEYS` from the LIVE env. The bug: `auth.API_KEYS = _parse_api_keys()` reads from CACHED `settings.API_KEYS`, so a naive refresh doesn't help. The fix: parse `os.environ["API_KEYS"]` directly. Documented in the canonical reference docstring at `tests/integration/test_challenge_backoff.py`.
- **`Response` not `HTTPException` for 503 + Retry-After:** Per 03-RESEARCH.md §D3, FastAPI's `HTTPException(headers=...)` doesn't preserve the SearchResponse pydantic shape because the headers are merged via a path that bypasses response_model serialization. Used `Response(status_code=503, content=denied_body.model_dump_json(), media_type="application/json", headers={"Retry-After": str(retry_after)})` instead.
- **record_block / record_success bypass `_load` while holding `_LOCK`:** The double-checked-load pattern (Pattern S1) is on `_load` which `async with _LOCK`. If `record_block` called `_load`, it would re-acquire the same lock and deadlock (asyncio.Lock is NOT re-entrant). Solution: read state directly inside `record_block`/`record_success` while holding the lock, replicating the cold-load fallback inline. `check_gate` still goes through `_load` because it's read-only on the hot path.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] sorry.html at `tests/fixtures/serp/sorry.html` broke `test_parse_serp_fixtures`**
- **Found during:** Task 3 full-suite run after main.py wiring landed.
- **Issue:** The existing `test_parse_serp_fixtures` test asserts `len(glob.glob(FIXTURES_DIR / "*.html")) == 10` to pin the Phase 1 fixture count. Adding `tests/fixtures/serp/sorry.html` flipped the count to 11, failing the assertion.
- **Fix:** Moved sorry.html to `tests/fixtures/serp/blocks/sorry.html`. The new subdirectory leaves room for future block-marker fixture variants (recaptcha.html, consent_interstitial.html).
- **Files modified:** `tests/fixtures/serp/sorry.html` → `tests/fixtures/serp/blocks/sorry.html`; `tests/integration/test_challenge_backoff.py` (`SORRY_FIXTURE` path updated).
- **Verification:** `test_parse_serp_fixtures` re-asserts `== 10` and passes. `test_sorry_fixture_triggers_detect_block` finds the fixture at the new path.
- **Committed in:** `3570569` (Task 3 commit).

**2. [Rule 2 - Missing Critical] Cross-test alphabetical import order poisoned `auth.API_KEYS` for sibling tests**
- **Found during:** Task 3 full-suite run (`test_auth.py::test_valid_key_passes_auth` and `test_integration/test_rate_limit.py::test_rate_limit_per_minute_returns_429` failed when run AFTER `test_integration/test_challenge_backoff.py`).
- **Issue:** Pytest collects `tests/integration/test_challenge_backoff.py` BEFORE `tests/integration/test_rate_limit.py` and `tests/test_auth.py` (alphabetical order). Each test file sets `os.environ["API_KEYS"] = ...` at module top, then imports `from src.artiscrapper.main import app`. The `app` import is cached after the first import → subsequent files' env-var assignments don't reach the cached `settings.API_KEYS` (pydantic-settings reads env ONCE at first `Settings()` call). Each test file's setup was assuming it was the FIRST import — a fragility that existed in Plan 03-01 but only surfaced when Plan 03-02 added a new alphabetically-earlier integration test file.
- **Fix:** Three layers of defense in test_challenge_backoff.py + test_auth.py + test_rate_limit.py:
  1. APPEND our test keys to `os.environ["API_KEYS"]` instead of REPLACING them.
  2. Use `os.environ.setdefault("CACHE_DB_PATH", ...)` instead of `os.environ["CACHE_DB_PATH"] = ...` so the first-importing file's tempfile wins.
  3. After import, rebuild `auth.API_KEYS` from the LIVE `os.environ["API_KEYS"]` directly (NOT via cached `settings.API_KEYS`).
- **Files modified:** `tests/test_auth.py`, `tests/integration/test_rate_limit.py`, `tests/integration/test_challenge_backoff.py`.
- **Verification:** Full suite green (65 passed, 2 skipped) regardless of test-collection order. Individual files still pass standalone (no regression).
- **Committed in:** `3570569` (Task 3 commit).

**3. [Rule 1 - Bug] `record_block` / `record_success` would deadlock if they used `_load`**
- **Found during:** Task 2 implementation (caught at design time, not via failing test).
- **Issue:** `_load` acquires `_LOCK` via `async with`. If `record_block` called `_load` first (to ensure state is loaded), then re-acquired `_LOCK` for the mutation, it would deadlock — `asyncio.Lock` is NOT re-entrant. The original PATTERNS.md pseudocode showed `record_block` calling `_load(cache)` and then `async with _LOCK:` separately, which is racey (state could change between load and lock acquisition).
- **Fix:** `record_block` and `record_success` acquire `_LOCK` ONCE, then read state directly inside the lock (replicating the cold-load fallback inline). `check_gate` still uses `_load` because it's read-only on the hot path and doesn't mutate state.
- **Files modified:** `src/artiscrapper/challenge_backoff.py`.
- **Verification:** All 7 unit tests + 3 integration tests pass; the `test_state_survives_restart` test specifically exercises the cold-load path inside `check_gate` after `record_block` persisted state.
- **Committed in:** `0c6ea9c` (Task 2 commit).

---

**Total deviations:** 3 auto-fixed (1 Rule-1 bug from a fixture path collision, 1 Rule-2 missing test-isolation defense, 1 Rule-1 design-time deadlock avoidance).
**Impact on plan:** All three were necessary for correctness. Zero scope creep — no new features added, only operational/correctness gaps closed.

## Threat-Model Acceptance

Per the plan's `<threat_model>`:

- **T-03-02-01 (Block amplification — DoS HIGH):** `test_exponential_curve` pins the D-06 curve across retries 1..8. `test_503_with_retry_after` confirms the gate denies subsequent requests after a block. Acceptance ref met.
- **T-03-02-02 (State loss on restart — Tampering MEDIUM):** `test_state_persists_to_sqlite` + `test_state_survives_restart` + container-restart manual UAT (block state preserved across `docker compose up --force-recreate`) all pass. Acceptance ref met.
- **T-03-02-03 (Silent timeout — DoS MEDIUM):** `test_503_with_retry_after` confirms 503 + digit-string Retry-After header. Acceptance ref met.
- **T-03-02-04 (LLM-down cascade — DoS HIGH):** `test_llm_down_keeps_useful_results` pins 28/50 survivors (≥5 bar). Acceptance ref met.
- **T-03-02-05 (Extractor regression — Tampering MEDIUM):** `test_catalog_price_extraction_rate_above_85_percent` pins 10/10 = 100% (≥85% bar). Per-fixture details list per D-18.
- **T-03-02-06 (sorry-page content in logs — Info Disclosure MEDIUM):** `challenge_backoff_active` log line carries only `retry_after=<int>`; no sorry-page content. OBS-05 aligned.
- **T-03-02-07 (Test fixture authenticity — Spoofing LOW):** ACCEPTED (synthetic stand-in). Mitigated by Plan 03-01's `block_detected_total{reason}` Prometheus counter showing actual production marker reasons.
- **T-03-02-08 (Default shadowing — Default MEDIUM):** Constants are hardcoded module-level (NOT settings-threaded per D-06 ROADMAP-lock). `challenge_backoff_init` log line empirically verified in container logs.
- **T-03-02-09 (Concurrent block-trip race — Race MEDIUM):** `_LOCK = asyncio.Lock()` serializes `record_block` mutations. `--workers 1 --loop asyncio` (D6) means no thread/GIL concerns.
- **T-03-02-10 (Block-detection audit trail — Repudiation LOW):** ACCEPTED. `block_detected_total{reason}` Counter + correlation_id propagation cover single-client deploy. Per-key attribution deferred.

## Empirical Verification

### D-19 lifespan log lines (4 of 4 present in container logs after `compose up --force-recreate`)

```
{"event": "boot_start", "version": "0.1.0", ...}
{"event": "api_keys_loaded", "count": 1, "rate_per_min": 60, "rate_per_day": 10000, ...}
{"event": "sentry_init_skipped", "traces_sample_rate": null, ...}
{"event": "rate_limit_init", "per_min": 60, "per_day": 10000, ...}
{"event": "challenge_backoff_init", "base_s": 60, "cap_s": 3600, "reset_after_s": 3600, ...}
{"event": "boot_done", ...}
```

Verified via `docker compose logs artiscrapper 2>&1 | grep -cE '(api_keys_loaded|sentry_init_(done|skipped)|rate_limit_init|challenge_backoff_init)'` → **4**.

### challenge_state row in running container (D-08 acceptance)

Fresh container after `compose up --force-recreate`:
```
(1, None, 0, 0, 1780518809)
-- id=1, last_block_at=NULL, retry_count=0, next_allowed_at=0, updated_at=<epoch>
```

After setting `(last_block_at=1780518852, retry_count=3, next_allowed_at=1780519092, updated_at=1780518852)` and running `docker compose up -d --force-recreate`:
```
(1, 1780518852, 3, 1780519092, 1780518852)
-- ALL FOUR fields preserved across restart. D-08 acceptance proven empirically.
```

Schema verified:
```sql
CREATE TABLE challenge_state (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    last_block_at   INTEGER,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    next_allowed_at INTEGER NOT NULL DEFAULT 0,
    updated_at      INTEGER NOT NULL
)
```

### /metrics endpoint healthy post-recreate

```
$ curl -sL http://localhost:8002/metrics/ | grep -c '^artiscrapper_'
47
```

Well above D-13's ≥6 acceptance bar (Plan 03-01).

### Catalog extraction rate (test_catalog_price_extraction_rate_above_85_percent)

Measured 10/10 = **100.00%** (acceptance bar ≥85%). Per-fixture details:

| Fixture | Has Price | Price |
|---------|-----------|-------|
| argautopartes_com_ar/product-01.html | True | 224103 |
| autodo_com_ar/product-01.html | True | 117367.65 |
| casasusy_com_ar/product-01.html | True | 24900 |
| dphidraulica_com_ar/product-01.html | True | 350843.86 |
| falabella_com_ar/product-01.html | True | 29990 |
| lspalermo_com_ar/product-01.html | True | 54398 |
| martinmorris_ar/product-01.html | True | 33231.98 |
| mayoristafrog_com_ar/product-01.html | True | 5000.00 |
| mipol_com_ar/product-01.html | True | 129910.85 |
| reps_com_ar/product-01.html | True | 111910 |

### Degraded-mode survivor count (test_llm_down_keeps_useful_results)

Measured **28/50 survivors** from Phase 1's labelled.jsonl when `router_health_check` returns False (via respx.head /healthz → 503). Acceptance bar is ≥5. LLM-06 hardening confirmed.

### Test suite final count

```
$ LLM_ROUTER_BEARER_TOKEN=test-token uv run pytest tests/ -q
65 passed, 2 skipped, 4 warnings in 8.40s
```

- 65 passed (all 53 Phase 3-Plan-01 tests + 12 new Phase 3-Plan-02 tests).
- 2 skipped: `tests/test_e2e.py` (live-network only, marked `@pytest.mark.e2e`).

### Phase 3 integration suite breakdown (test_integration/ — 8 tests)

```
$ LLM_ROUTER_BEARER_TOKEN=test-token uv run pytest tests/integration/ -v
tests/integration/test_catalog_extraction.py::test_catalog_price_extraction_rate_above_85_percent PASSED
tests/integration/test_challenge_backoff.py::test_sorry_fixture_triggers_detect_block PASSED
tests/integration/test_challenge_backoff.py::test_503_with_retry_after PASSED
tests/integration/test_challenge_backoff.py::test_state_survives_restart PASSED
tests/integration/test_degraded_mode.py::test_llm_down_keeps_useful_results PASSED
tests/integration/test_metrics_endpoint.py::test_metrics_returns_six_families PASSED
tests/integration/test_metrics_endpoint.py::test_metrics_endpoint_has_no_auth PASSED
tests/integration/test_rate_limit.py::test_rate_limit_per_minute_returns_429 PASSED
8 passed in 1.28s
```

## Issues Encountered

- **`test_llm.py` is not self-contained on env vars** — pre-existing issue inherited from Phase 2 / Plan 03-01 (logged in 03-01-SUMMARY.md). Workaround: prepend `LLM_ROUTER_BEARER_TOKEN=test-token` to any pytest invocation. Not caused by this plan.
- **Cross-test ordering bleed (now fixed):** Plan 03-01 silently relied on alphabetical test-collection order; Plan 03-02 exposed the bleed via the new `test_integration/test_challenge_backoff.py` file. Closed in Task 3 with the defensive merge pattern documented in `<deviations>` above. Tests now pass regardless of collection order.
- **Phase 2 WARNING items (WR-01/WR-02/WR-04 from 02-REVIEW.md):** Not touched by this plan. Per CONTEXT.md §deferred, these were marked `[opportunistic]` and "not gating the phase goal." Plan 03-02's scope was tightly bounded to ChallengeBackoff + integration suite; WR-* items remain open for future opportunistic cleanup.

## Phase 2 Memory Landmines Honored

- ✅ `feedback_empirical_retest_after_default_changes`: 4th D-19 log line `challenge_backoff_init` empirically verified in container logs alongside the 3 from Plan 03-01.
- ✅ `feedback_compose_build_recreate`: `docker compose build` + `docker compose up -d --force-recreate` as SEPARATE steps (never the combined `up -d --build`).
- ✅ `feedback_self_sufficient_installers`: DDL extension is idempotent (INSERT OR IGNORE seed); no .env updates needed (constants are ROADMAP-locked module-level per D-06 + Pitfall 6); `.env.example` already covers Phase 3 env vars from Plan 03-01.
- ✅ `feedback_agent_as_uat_operator`: container-restart preservation UAT automated by Claude (set state → recreate → re-query → confirm preservation). Evidence captured under Empirical Verification.
- ✅ `feedback_verify_volatile_data`: Phase 1 SPIKE captured no real /sorry/ fixture (verified by inspection — only the 10 Phase 1 SERP fixtures + MANIFEST.md + README.md existed). Created synthetic stand-in per D-20.

## User Setup Required

**None** — Plan 03-02 adds no new env vars. ChallengeBackoff constants are hardcoded module-level (D-06 ROADMAP-lock + Pitfall 6 — no settings shadowing). The `challenge_state` row is seeded idempotently via `INSERT OR IGNORE` at every `init_schema` call.

The orchestrator's post-merge docker-compose retest should confirm:

```bash
# Phase 2 memory: NEVER `up -d --build`
docker compose build
docker compose up -d --force-recreate

# All 4 D-19 log lines emit per process start
docker compose logs artiscrapper 2>&1 | grep -cE "(api_keys_loaded|sentry_init_(done|skipped)|rate_limit_init|challenge_backoff_init)"
# expect ≥4

# challenge_state seed row exists
docker compose exec artiscrapper python3 -c "import sqlite3; print(list(sqlite3.connect('/app/cache.db').execute('SELECT * FROM challenge_state')))"
# expect [(1, None, 0, 0, <epoch>)]
```

## Next Phase Readiness

- **ROADMAP §Phase 3 success criteria 4, 5, 6 all PROVEN** with empirical evidence (see Accomplishments).
- **Phase 2 WARNING items still open** (WR-01 MELI substring match, WR-02 cache-write strong ref, WR-04 test cleanup) — deferred per CONTEXT.md.
- **Phase 4 readiness:** challenge_state schema is single-row + single-counter. Per-host backoff (rejected in Phase 3 — Google blocks are IP-level) would require a schema migration. If multi-tenancy lands in Phase 4+, per-API-key challenge state may be revisited.

## Self-Check: PASSED

Files created (verified via `git diff --stat` on the three task commits):
- `src/artiscrapper/challenge_backoff.py` — FOUND
- `tests/fixtures/serp/blocks/sorry.html` — FOUND
- `tests/test_challenge_backoff.py` — FOUND
- `tests/integration/test_challenge_backoff.py` — FOUND
- `tests/integration/test_degraded_mode.py` — FOUND
- `tests/integration/test_catalog_extraction.py` — FOUND

Commits in branch:
- `83880fa` (Task 1) — FOUND
- `0c6ea9c` (Task 2) — FOUND
- `3570569` (Task 3) — FOUND

---
*Phase: 03-robustness*
*Completed: 2026-06-03*

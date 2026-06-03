# Phase 3: Robustness - Context

**Gathered:** 2026-06-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Production-grade resilience layer on top of the Phase 2 MVP:
- **Prometheus `/metrics`** — expose the inline counters/histograms already wired in Phase 2
- **Sentry crash visibility** — env-var gated, off in dev by default
- **Per-API-key consumer rate-limit** — `slowapi` keyed off `X-API-Key`, isolates runaway clients from Cloak/Google rate-limit
- **Google challenge detection + exponential backoff** — `ChallengeBackoff` state machine on top of the existing `_detect_block()`
- **Hardened degraded mode** — synthetic load test killing `local-llms-router` mid-search; the heuristic blocklist + price-in-card path must keep `/search` serving
- **Fixture-replay integration suite** — Phase 1's SERP + catalog fixtures replayed through the live parser cascade + JSON-LD extractor, asserting >85% catalog price extraction (validates D12 hand-roll in production)

**In scope:** OBS-07 + hardening of OBS-01..06 / BROWSER-05 / LLM-06 / NF-01..04 paths already implemented in Phase 2. No new feature surfaces beyond `/metrics` + `X-API-Key` rate-limit headers.

**Out of scope:** Per-host backoff (global only), admin endpoint for dynamic keys, multi-environment Sentry routing, distributed rate-limit store (Redis/Postgres — violates 1-container architecture).

</domain>

<decisions>
## Implementation Decisions

### API Key Authentication & Rate-Limit (consumer-facing)
- **D-01:** Static API keys via env-var `API_KEYS=k1,k2,k3` (comma-separated). Rotation requires container restart. **Why:** KISS for the single-client deploy (Sánchez Repuestos, ~500-2000 q/day expected). Adding a sqlite-backed admin endpoint is deferred until Phase 4 if onboarding additional consumers.
- **D-02:** Quota: `60/min` AND `10000/day` per key (both enforced; whichever fires first wins). Headroom of ~5× over expected peak — protects Cloak's 1/min Google rate-limit from runaway client traffic.
- **D-03:** `X-API-Key` header. Missing or unknown key → `401 Unauthorized` (NOT `403`). Distinguishes "no credentials" from "credentials but lack permission".
- **D-04:** Rate-limit state: **in-memory** (`slowapi`'s default `MemoryStorage`). Restart loses counters. **Why:** Acceptable for single-container deploy where restarts are rare and the worst case (quota briefly reset on restart) is benign compared to the operational complexity of sqlite-backed counters. If restarts become frequent or multi-instance, revisit in Phase 4.

### ChallengeBackoff (Google block detection)
- **D-05:** **Global scope** — a single backoff state covers all `*.google.com` fetches. **Why:** Google blocks are IP-level (Phase 1 SPIKE confirmed); tracking per-URL (`query` vs `query mercadolibre`) would not isolate damage and adds state complexity.
- **D-06:** Backoff curve: `min(60s × 2^retries, 1h)` (ROADMAP-locked). Schedule via `app.state.challenge_backoff.next_allowed_at` checked in `fetch_serp()` before each Google round-trip.
- **D-07:** **Reset trigger:** first successful Google fetch ≥1h after `last_block_at`. Single counter resets to 0 on that fetch. **Why:** Matches Google's typical IP-cool-off window; counting successive successes adds state that doesn't change the recovery decision materially.
- **D-08:** **Persistence:** sqlite table `challenge_state` (single row: `last_block_at`, `retry_count`, `next_allowed_at`). Survives container restart so a restart doesn't accidentally reset and re-trigger a block. ROADMAP-pinned.
- **D-09:** When in backoff, `/search` returns `503` with `metadata.block_detected=true` and `Retry-After: <seconds>` header. The consumer gets a structured signal, not a silent timeout.

### `/metrics` endpoint (Prometheus)
- **D-10:** **No auth on `/metrics`**. Exposed on the same `:8000` port as `/search`. **Why:** In single-container deploy the scraper runs on the host docker network and reaches the container via internal address. If the container is ever exposed publicly behind a reverse proxy, the proxy enforces an IP allowlist for `/metrics`. KISS for Phase 3.
- **D-11:** Wire `prometheus-client` directly into the **existing** `src/artiscrapper/metrics.py` module — do NOT replace the inline counters created in Phase 2; bridge them. The Counter family names are already canonical (`artiscrapper_llm_fallback_total{reason}`, `artiscrapper_visit_failed_total{host}`, `artiscrapper_block_detected_total{reason}`).
- **D-12:** Add histograms via `Histogram.time()` decorators on the three hot paths: `artiscrapper_search_elapsed_seconds`, `artiscrapper_llm_elapsed_seconds`, `artiscrapper_visit_elapsed_seconds{stage}` (with `stage` = `fetch` | `extract` | `classify`).
- **D-13:** CI smoke test: `curl http://localhost:8001/metrics | grep -c '^artiscrapper_' >= 6` (verifies all 6 metric families are exposed and parseable by Prometheus).

### Sentry (crash visibility)
- **D-14:** **Off by default.** Init only when `SENTRY_DSN` env-var is set and non-empty. No init in dev/test. PRD-aligned.
- **D-15:** Sample rates when active: **errors 100%** (all uncaught exceptions reported), **`traces_sample_rate=0.1`** (10% of requests get distributed traces — enough to detect regressions without blowing the free-plan budget), **`profiles_sample_rate=0`** (profiling is expensive and unnecessary for an MVP).
- **D-16:** Correlation: every Sentry event must carry the `correlation_id` from `asgi-correlation-id` as a breadcrumb tag, so a Sentry crash links to the matching `correlation_id` in structlog logs.
- **D-17:** Sentry integration is added in `src/artiscrapper/logging_setup.py` alongside structlog — keep observability initialization in one module.

### Test Discipline (Phase 2 lessons applied as constraints)
- **D-18:** **Fixture-driven assertions must check specific data extraction, not structural shape only.** Phase 2's parser shipped extracting 0 prices from all 10 fixtures because the test only asserted `len(results) > 0` instead of `sum(price is not None) > N`. Phase 3 integration tests must pin per-fixture price counts (already encoded in `tests/test_parser.py::test_carousel_extracts_prices_from_fixtures` post-commit `160c133`).
- **D-19:** **Empirical retest after defaults change** (memory: `feedback_empirical_retest_after_default_changes`). When config defaults shift (e.g., `LLM_MODEL`, backoff curve constants, quota numbers), verify in container logs that the new value reaches the hot path — unit tests alone miss shadowing between settings/contract/route layers.
- **D-20:** **Synthetic challenge HTML for the backoff test** uses a real /sorry/ fixture from Phase 1's SPIKE artifacts (or a minimal stand-in if none was captured) — not a hand-typed string. Keeps the test grounded in what Google actually serves.

### Claude's Discretion
- Specific `slowapi` middleware ordering vs `CorrelationIdMiddleware` and the FastAPI exception handlers — pick the order that makes correlation_id available in Sentry breadcrumbs even on 429 responses.
- Internal sqlite schema for `challenge_state` (single row vs upsert pattern, lock semantics) — researcher/planner picks the simplest pattern that survives concurrent writers (lifespan recycle + request handler).
- `slowapi`'s `default_limits` vs per-route decorators — pick whichever produces cleaner per-key + global limits without duplicating quota config.
- Sentry SDK version + integrations enabled (FastAPI integration is canonical; Httpx integration is optional) — researcher picks based on current Sentry SDK docs.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope + decisions
- `.planning/ROADMAP.md` §"Phase 3: Robustness" — 2 plans pre-drafted (03-01, 03-02) + 6 success criteria
- `.planning/REQUIREMENTS.md` — OBS-07 (only new req formally); Phase 3 hardens OBS-01..06, BROWSER-05, LLM-06, NF-01..04
- `.planning/PROJECT.md` — RESET scope: 1 container, no Redis/Postgres, no MELI direct

### Phase 1 empirical foundation (still authoritative)
- `.planning/SPIKE.md` §Browser — block markers Google uses (consent interstitial, `/sorry/`, recaptcha) feed `_detect_block()` and `ChallengeBackoff`
- `.planning/SPIKE.md` §LLM router — qwen2.5:7b-instruct-q4_K_M backend behavior; degraded-mode synthetic test should mock this

### Phase 2 implementation + lessons
- `.planning/phases/02-mvp/02-VERIFICATION.md` — what shipped; 53/54 v1 reqs covered; OBS-07 deferred to this phase
- `.planning/phases/02-mvp/02-HUMAN-UAT.md` §G-01 — full root-cause analysis of carousel + LLM routing bugs; lessons inform Phase 3 test discipline (D-18, D-19)
- `.planning/phases/02-mvp/02-REVIEW.md` — open WARNING items (WR-01 MELI substring match, WR-02 strong-ref on cache write task, WR-04 health test cleanup) — Phase 3 can opportunistically close these
- `.planning/phases/02-mvp/02-RESEARCH.md` Pattern 13 (metrics) + Pattern 3 (asgi-correlation-id + structlog) — the wiring patterns Phase 3 builds on
- `.planning/phases/02-mvp/02-02-SUMMARY.md` — LLM curator + degraded mode current shape (informs the synthetic load test design)

### Existing source modules Phase 3 extends (not greenfield)
- `src/artiscrapper/metrics.py` — inline `Counter`-shape dicts; Phase 3 bridges to `prometheus_client.Counter`/`Histogram`
- `src/artiscrapper/search.py` `_detect_block()` — returns block reason string; ChallengeBackoff consumes this
- `src/artiscrapper/main.py` lifespan — sqlite cache init point; `challenge_state` schema co-located here
- `src/artiscrapper/logging_setup.py` — Sentry SDK init goes alongside structlog
- `src/artiscrapper/llm.py` `curate_candidates` — Histogram.time() target for `artiscrapper_llm_elapsed_seconds`
- `src/artiscrapper/visit.py` `visit_candidates` — Histogram.time() target with `stage` label

### Test fixtures already in repo
- `tests/fixtures/serp/*.html` — 10 SERP fixtures from Phase 1 (parser cascade integration test)
- `tests/fixtures/catalog/**/*.html` — per-host PDP fixtures from Phase 1 (extractor D12 ≥85% test)
- `tests/test_parser.py::test_carousel_extracts_prices_from_fixtures` — pinning baseline that Phase 3's integration suite extends

### External library docs the researcher should consult
- `prometheus-client` (Python) — Counter / Histogram patterns + WSGI/ASGI exporter
- `sentry-sdk` (Python) — FastAPI integration, sample-rate semantics, correlation tag conventions
- `slowapi` (Python) — `Limiter` + `key_func` patterns; `X-API-Key` extractor; per-route vs default limits

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`src/artiscrapper/metrics.py`** — already exposes 3 inline counter families with the exact names ROADMAP requires (`artiscrapper_llm_fallback_total`, `artiscrapper_visit_failed_total`, `artiscrapper_block_detected_total`). Phase 3 is wiring `prometheus-client` on top, not redesigning the metric model.
- **`src/artiscrapper/search.py::_detect_block()` (BROWSER-05)** — returns a block-reason string (`consent_interstitial` / `sorry` / `recaptcha` / `unknown`); already invoked in `main.py` pipeline step 3 and increments `metrics.block_detected_total[reason]`. ChallengeBackoff just gates the NEXT fetch based on these signals.
- **`src/artiscrapper/rate_limit.py::GoogleRateLimiter`** — per-instance 1/min throttle (BROWSER-04). Phase 3's consumer rate-limit is layered ON TOP via slowapi (consumer 60/min × server-side 1/min Google). Both must co-exist; one is per-instance protection, the other is per-consumer fairness.
- **`src/artiscrapper/llm.py::resolve_model()` (Phase 2 / commit `0af57a7`)** — model: lazy lookup + module-level cache + fallback. Same pattern applies to potential future dynamic config (e.g., quota override via the router's recommendations endpoint).
- **`src/artiscrapper/cache.py`** — aiosqlite + WAL is already wired; the `challenge_state` table piggy-backs on the same connection in `app.state.cache`.

### Established Patterns
- **`asgi-correlation-id` middleware order** — set in `main.py:159` BEFORE the structlog binding. slowapi must be added between the correlation-id middleware and the route handler so 429 responses still carry the request's correlation_id.
- **Try / except / fallback in LLM module** — `classify_candidate` has retry-on-503 (1s wait) and retry-on-{502,504} (30s wait) with metric-incremented fallback. ChallengeBackoff is structurally identical: detect → wait → retry → fallback (degraded).
- **Module-level cache with `asyncio.Lock`** — `_RESOLVED_MODEL` + `_RESOLVE_LOCK` in llm.py. Same pattern fits `_CHALLENGE_STATE` if we want in-memory caching of the sqlite row to avoid a query per request.
- **Foot-gun pinned by test** (D2 / D6 / D8) — Phase 2 pattern: each invariant gets a `test_footguns.py::test_<name>` that asserts the constant or grep'd condition. Phase 3 adds: `test_no_uvloop_after_sentry_init` (Sentry SDK must not pull uvloop), `test_metrics_endpoint_unprotected_by_design` (no auth decorator on /metrics).
- **Regex-over-CSS for volatile HTML data** (Phase 2 / commit `160c133`) — applies to `_detect_block()` if Google changes the `/sorry/` page structure. Phase 3 may want to add a regex-anchored block-marker check as a defense-in-depth fallback.

### Integration Points
- **`main.py` lifespan startup order:** structlog → Sentry init (conditional on `SENTRY_DSN`) → cache + `challenge_state` schema init → Cloak singleton → rate limiters → background tasks. Sentry first so any boot exception is captured.
- **`main.py` middleware order:** `CorrelationIdMiddleware` (outermost) → `slowapi`'s `_rate_limit_exceeded_handler` → route handlers. This keeps 429 responses inside the correlation-id scope.
- **`/search` endpoint:** add `@limiter.limit(...)` decorator with `key_func` extracting `X-API-Key`. Quota constants live in `config.py` (`API_RATE_PER_MINUTE`, `API_RATE_PER_DAY`).
- **`/metrics` endpoint:** new route in `main.py`, returns `prometheus_client.generate_latest()` with `CONTENT_TYPE_LATEST` content-type. No auth, no correlation_id binding (Prometheus scraper doesn't need it).
- **Histogram instrumentation:** wrap `search()`, `curate_candidates()`, `visit_candidates()` with `Histogram.time()` context managers. Add `stage` label to visit (fetch / extract / classify) via separate sub-spans.

</code_context>

<specifics>
## Specific Ideas

- **Phase 1's `labelled.jsonl`** (the 49 hand-labelled SERP candidates from `01-02`) is the perfect input for the synthetic degraded-mode test: feed all 49 into `should_keep()` with the LLM router mocked-down, assert that the heuristic blocklist + price-in-card path retains ≥5 useful results. This avoids inventing synthetic data.
- **D12 ≥85% catalog price extraction** — Phase 1 measured 9/10 jsonld-sufficient empirically. Phase 3's integration test should run all catalog fixtures through `visit.extract_product()` directly (in-process, no HTTP) and assert `≥9` yield `price > 0`. If Google rotates and a fixture stops parsing, the test surfaces it.
- **ChallengeBackoff test:** Use a `tests/fixtures/serp/sorry.html` (a real Google /sorry/ page captured from Phase 1; if absent, the planner adds a minimal synthetic stand-in). Inject via monkeypatched `fetch_serp()` to return the fixture, assert `_detect_block` fires, then second call within `next_allowed_at` returns 503 + `Retry-After` header without hitting Cloak.
- **Sentry breadcrumb:** the `correlation_id` value should appear as `tags.correlation_id` (not just a breadcrumb) so Sentry's UI lets you filter by it.

</specifics>

<deferred>
## Deferred Ideas

- **Per-host ChallengeBackoff scope** (`query` vs `query mercadolibre` tracked independently) — rejected because Google blocks are IP-level. Revisit only if we observe asymmetric block behavior in production.
- **Admin endpoint for dynamic API key creation/revocation** — deferred to a future phase if onboarding additional consumers beyond Sánchez Repuestos. Today's static env-var is sufficient.
- **Multi-environment Sentry routing** (`SENTRY_DSN_DEV` / `_STAGING` / `_PROD`) — rejected; current scope is single-environment. The env-var naming pattern (just `SENTRY_DSN`) leaves room for an `APP_ENV` tag without restructuring config.
- **Bearer / IP-allowlist on `/metrics`** — deferred until the container is exposed beyond the internal docker network. KISS for Phase 3.
- **Distributed rate-limit store** (Redis) — out of scope, violates single-container architecture.
- **`slowapi` plus sliding-window quota algorithm** — slowapi default (fixed window) is acceptable for 60/min; sliding window adds dependency complexity. Revisit if abuse patterns appear.
- **Phase 2 cleanup items from `02-REVIEW.md`** (WR-01 MELI substring match, WR-02 cache-write strong ref, WR-04 temp file cleanup) — Phase 3 may opportunistically close these but they are not gating the phase goal.

</deferred>

---

*Phase: 03-Robustness*
*Context gathered: 2026-06-03*

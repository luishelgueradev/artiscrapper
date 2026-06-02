# Roadmap: artiscrapper v0

**Date:** 2026-06-01
**Granularity:** Coarse (5 phases, 1-3 plans each)
**Parallelization:** Plans within a phase run in parallel when independent
**Total phases:** 5 (Phase 1 Spike → Phase 5 Expansion)
**Mode:** YOLO (auto-approve, mapped from PRD §7 Fase 0..4)

## Overview

`artiscrapper v0` is a single-container FastAPI service that exposes `POST /search` — Google SERP curation via Cloakbrowser, structured LLM filtering against the existing `local-llms-router`, optional visit pass for price+freshness, and a 24h sqlite cache. The journey is empirically gated: **Phase 1** is a 1-day spike that answers 12 open questions and produces fixtures + Go/No-Go (no production code); **Phase 2** delivers the full MVP (all 53 v1 requirements + Docker + tests + end-to-end `/search`); **Phase 3** adds production robustness (Prometheus, Sentry, rate-limit per API-key, challenge backoff, degraded mode, fixture-based integration suite); **Phase 4** is on-demand operational tooling (Grafana, Loki, tracing, cache invalidation) only if prod data justifies it; **Phase 5** is deferred expansion (per-supplier adapters, residential proxy, async+SSE, multi-tenant auth) only if Sánchez Repuestos grows past current scope.

The architecture survives research with **13 LOCKED deviations** from the PRD (D1..D13) and 3 load-bearing foot-guns (D2 confidence cutoff, D6 uvloop ban, D8 persistent_context ban). Phase 1 is non-negotiable — it pins empirical numbers that Phase 2 cannot infer.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3, 4, 5): Planned milestone work mapping PRD Fase 0..4
- Decimal phases (e.g. 2.1): Reserved for urgent INSERTED work post-execution

- [x] **Phase 1: Spike & Empirical Validation** - Answer 12 Phase-0-spike questions, capture fixtures, deliver Go/No-Go (no production code) (completed 2026-06-01)
- [ ] **Phase 2: MVP** - Endpoint `/search` end-to-end with all 53 v1 requirements, Docker image, tests, validated against PRD §10 success criteria
- [ ] **Phase 3: Robustness** - Prometheus metrics, Sentry, rate-limit per API-key, challenge detection + backoff, degraded mode, fixture-based integration suite
- [ ] **Phase 4: Production Operations** - Grafana dashboards, Loki, cache invalidation endpoint, tracing — only on demand from prod telemetry
- [ ] **Phase 5: Expansion** - Per-supplier adapters, residential proxy, async+SSE, multi-tenant auth — deferred until Sánchez grows past current scope

## Phase Details

### Phase 1: Spike & Empirical Validation

**Goal**: Empirically answer the 12 Phase-0-spike questions from `research/SUMMARY.md §5`, capture the regression fixture set, and produce a 1-page Go/No-Go for Phase 2 lock-in.
**Depends on**: Nothing (first phase)
**Requirements**: None implemented — this phase validates assumptions, it does not satisfy v1 requirements. Outputs gate Phase 2 implementation of D1, D3, D4, D8, D10, D11, D12 specifically.
**Success Criteria** (what must be TRUE):

  1. Docker tag `cloakhq/cloakbrowser:0.3.31` is verified present on Hub (or D1 pin is revised in writing).
  2. `local-llms-router` model identity, KV-cache behavior, `format=json` support, median TTFT, and per-client concurrency are documented as concrete numbers.
  3. Repo contains 5-10 raw Google SERP HTML fixtures (committed under `tests/fixtures/serp/`) + 10 raw catalog-page HTML fixtures from top-10 AR stores (under `tests/fixtures/catalog/`) for the parser regression set.
  4. 30-50 hand-labeled candidate records exist (`tests/fixtures/llm/labelled.jsonl`) for LLM prompt iteration regression.
  5. A `SPIKE.md` Go/No-Go document exists in `.planning/` covering: D12 (JSON-LD hand-roll vs extruct decision based on fixture sweep), `pws=0` consent interstitial behavior on cold container, `Browser.is_connected()` death-mode coverage (verified by killing pid manually), and Falabella/Frog/Romero httpx 403 rates with realistic headers.

**Plans**: 3 plans

Plans:
**Wave 1**

- [x] 01-01-PLAN.md — Wave 0 scaffolding + Browser spike: verify Cloak Docker tag 0.3.31 (D1), confirm pws=0 doesn't trigger consent interstitial (D3), verify Browser.is_connected() catches Cloak death modes (D8), confirm ephemeral new_context() cookie isolation, capture 5-10 raw SERP HTML fixtures (AC-3). Output: SPIKE.md §Browser + tests/fixtures/serp/.

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02-PLAN.md — LLM router spike: probe OpenAI-compat /v1/chat/completions (D8 amended — NOT raw Ollama /api/chat), measure TTFT p50/p95 + JSON-mode reliability + KV-cache reuse + per-bearer concurrency at N=2/4/8 (D10 — likely LLM_CONCURRENCY=2). Hand-label 30-50 candidates for LLM regression set (AC-5). Output: SPIKE.md §LLM + tests/fixtures/llm/labelled.jsonl.

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 01-03-PLAN.md — Visit/extraction spike: capture 10 AR catalog PDP fixtures headed (Mercadolibre excluded per VISIT-08), classify via hand-rolled JSON-LD + OG + microdata + regex extractor (RESEARCH §Pattern 5), measure Falabella + Frog + Romero httpx 403 rates with DEFAULT_HEADERS (D11), make D12 decision (hand-roll vs extruct). Output: SPIKE.md §Visit + §D12 Decision + tests/fixtures/catalog/.

**Cross-cutting constraints:**

- D8 amended: router is OpenAI-compatible (POST /v1/chat/completions with Authorization: Bearer ...), NOT raw Ollama /api/chat. Brief 02-llm-curator.md is superseded on this point by 01-RESEARCH.md §Pattern 4.
- Phase 1 produces NO application code. Only scripts/spike/, tests/fixtures/, and .planning/SPIKE.md are written. Phase 2 will scaffold src/ and pyproject.toml.
- Bearer token + router URL live in .env.spike (gitignored). NEVER commit a real bearer token. If .env.spike is missing, the spike script must exit 2 with a hint pointing at scripts/spike/README.md.
- Each sub-spike plan's terminal task appends its SPIKE.md §<section> block from the captured artifacts — not from prose. The fill-in points are listed in 01-RESEARCH.md §SPIKE.md Template.

**Duration**: 1 day (matches PRD §7 Fase 0 estimate)

### Phase 2: MVP

**Goal**: Endpoint `POST /search` works end-to-end against the dev box, satisfying all 53 v1 requirements, running in 1 Docker container, with `pytest -x -q` green and PRD §10 success criteria measured on real queries.
**Depends on**: Phase 1 (D1 Docker tag confirmed, D12 extruct decision made, fixture set in place, LLM router behavior pinned)
**Requirements**: SEARCH-01, SEARCH-02, SEARCH-03, SEARCH-04, SEARCH-05, SEARCH-06, SEARCH-07, SEARCH-08, LLM-01, LLM-02, LLM-03, LLM-04, LLM-05, LLM-06, LLM-07, LLM-08, VISIT-01, VISIT-02, VISIT-03, VISIT-04, VISIT-05, VISIT-06, VISIT-07, VISIT-08, FRESH-01, FRESH-02, FRESH-03, FRESH-04, CACHE-01, CACHE-02, CACHE-03, CACHE-04, CACHE-05, BROWSER-01, BROWSER-02, BROWSER-03, BROWSER-04, BROWSER-05, DEPLOY-01, DEPLOY-02, DEPLOY-03, DEPLOY-04, DEPLOY-05, DEPLOY-06, OBS-01, OBS-02, OBS-03, OBS-04, OBS-05, OBS-06, NF-01, NF-02, NF-03, NF-04
**Success Criteria** (what must be TRUE):

  1. `POST /search` with body `{"query": "pelota playera quico"}` returns ≥10 products in <30s, ≥6 with `price` non-null, **zero blogs/wiki/youtube in top 10** (PRD §10).
  2. `POST /search` with body `{"query": "filtro aceite ford focus"}` returns ≥10 products, ≥7 from real stores (not link aggregators).
  3. `GET /health` returns `{"status":"ok","cloak":"ok","llm":"ok","cache":"ok"}` in <50ms; `GET /health/deep` performs real Cloak roundtrip + LLM HEAD.
  4. Re-running an identical query within 24h hits sqlite cache (response includes `metadata.cache_hit=true`, P50 <500ms).
  5. **Foot-gun D2 verified**: when `local-llms-router` is killed mid-test, `metadata.llm_degraded=true` surfaces, candidates with only `confidence=0.3` fallback ARE dropped at the `<0.4` cut, and the heuristic blocklist + price-in-card path keeps the response useful. A unit test pins this behavior.
  6. **Foot-gun D6 verified**: `uvicorn --loop asyncio --workers 1` in the Dockerfile CMD; `uvloop` is absent from `pyproject.toml` and `uv.lock`; CI asserts this absence (grep + fail).
  7. **Foot-gun D8 verified**: `cloakbrowser.launch_persistent_context` does NOT appear in the codebase; singleton `Browser` lives in FastAPI `lifespan`; ephemeral `new_context()` is created per request; `BROWSER_RECYCLE_AFTER=200` recycles the singleton. Unit test pins the no-persistent-context invariant.
  8. `docker build .` produces a single image; `docker run` boots `/health` in <10s on dev box; `pytest tests/ -x -q` green; `ruff check` and `ruff format --check` pass.

**Plans**: 3 plans

Plans:
**Wave 1**

- [ ] 02-01-PLAN.md — Core pipeline — scaffold FastAPI app with `lifespan` (Cloak singleton + recycle loop + sqlite cache init), implement `build_serp_url()` (D3: `pws=0&safe=off`, no `num/tbm/udm/site:`), parser cascade (`div.tF2Cxc` → `div.Ez5pwe` → `div.MjjYud` → h3-anchored fallback with `parse.cascade.exhausted` alert per D4), `_detect_block()` (BROWSER-05), URL canonicalization + dedupe (SEARCH-05), heuristic junk-domain blocklist pre-filter (D9, SEARCH-06), re-rank logic (SEARCH-07), and Pydantic request/response models (SEARCH-01, SEARCH-08). Covers SEARCH-01..08, BROWSER-01..05.

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 02-02-PLAN.md — LLM curator + visit pass + freshness + cache — implement `LLMVerdict` Pydantic model with `fallback()` classmethod (LLM-02), Spanish system prompt + 2 few-shot examples (LLM-01), `asyncio.Semaphore(LLM_CONCURRENCY=4)` orchestration (LLM-03), 5s timeout + `llm_fail:*` reason taxonomy (LLM-04), `<0.4` cutoff + `metadata.llm_degraded` surfacing (LLM-05 = D2 foot-gun), degraded-mode fallback to blocklist + price-in-card (LLM-06), router HEAD probe (LLM-07/08); visit pass with `httpx.AsyncClient(http2=True)` + global Semaphore(8) + per-host Semaphore(2) (VISIT-02, D5), realistic Chromium-146 headers + `Sec-Fetch-Site` + `Referer` (VISIT-04, D11), skip-if-you-can (VISIT-01), `classify_response()` for live-vs-dead (VISIT-05), hand-rolled JSON-LD + OG + microdata + AR-regex extractor in selectolax (VISIT-06, D12 — assuming Phase 1 spike confirms hand-roll), no-MELI-host invariant (VISIT-08), failure flags `skip_dead`/`visit_failed` no-retry (VISIT-07); freshness logic per FRESH-01..04; sqlite cache with `aiosqlite` + WAL + gzipped BLOB columns + lazy TTL + hourly prune loop + nightly checkpoint (CACHE-01..05, D7). Covers LLM-01..08, VISIT-01..08, FRESH-01..04, CACHE-01..05.

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 02-03-PLAN.md — Observability + deploy + tests — structlog with `merge_contextvars` + correlation_id binding (OBS-03), `asgi-correlation-id` middleware (OBS-04), allow-list whitelist for `_log_scrape` (OBS-05), `/health` cheap + `/health/deep` real (OBS-01, OBS-02, D13), inline counters `artiscrapper_llm_fallback_total{reason}` + `artiscrapper_visit_failed_total{host}` (OBS-06); Dockerfile multi-stage with `cloakhq/cloakbrowser:0.3.31` base + Chromium pin `chromium-v146.0.7680.177.5` (DEPLOY-01, DEPLOY-02), `tini`/`--init` (DEPLOY-04), `uv sync --locked` + `uv.lock` checked-in (DEPLOY-05), CI assertion that uvloop is absent (D6 foot-gun, DEPLOY-03, DEPLOY-05), `compose.yml` for dev with sqlite bind-mount (DEPLOY-06); parser unit tests against the Phase 1 SERP fixtures, LLM integration tests with `respx` mock (NF-02), `pytest tests/ -x -q` green, `ruff` clean, `mypy --strict` on public modules (NF-03), end-to-end test that hits dev-box `/search?q=pelota+playera+quico` and asserts PRD §10 (NF-01). Covers DEPLOY-01..06, OBS-01..06, NF-01..04.

**Duration**: 2-3 days (matches PRD §7 Fase 1 estimate)

### Phase 3: Robustness

**Goal**: Production-grade resilience — exposed Prometheus metrics, Sentry crash visibility, per-API-key consumer rate-limit, Google challenge detection + backoff, structured degraded mode under LLM router outage, and a fixture-replay integration suite that catches regressions in the parser cascade and the JSON-LD extractor.
**Depends on**: Phase 2 (MVP shipped, real traffic data informs rate-limit + per-host failure dashboards)
**Requirements**: OBS-07
**Success Criteria** (what must be TRUE):

  1. `GET /metrics` exposes Prometheus-format counters (`artiscrapper_llm_fallback_total{reason}`, `artiscrapper_visit_failed_total{host}`, `artiscrapper_block_detected_total`) and histograms (`artiscrapper_search_elapsed_seconds`, `artiscrapper_llm_elapsed_seconds`, `artiscrapper_visit_elapsed_seconds{stage}`) — `curl /metrics | grep artiscrapper_` returns ≥6 distinct metric families.
  2. Triggering an uncaught exception in a non-prod environment produces a Sentry event with correlation_id breadcrumb (toggle-able via `SENTRY_DSN` env-var; off in dev).
  3. `X-API-Key` header consumer rate-limit (`slowapi`) enforces per-key quotas on `/search`; runaway clients hit 429 without flooding the Cloak rate-limiter.
  4. Synthetic challenge HTML injected into the SERP path triggers `BlockDetected` → exponential backoff scheduler delays the next Google fetch by `min(60s × 2^retries, 1h)` and surfaces `metadata.block_detected=true`; a unit test pins the backoff curve.
  5. Killing `local-llms-router` mid-load test keeps `/search` returning 200 with `metadata.llm_degraded=true`; the heuristic blocklist + price-in-card path delivers ≥5 useful results for a popular query without LLM. A fixture-driven integration test asserts this.
  6. `tests/integration/` replays the Phase 1 SERP + catalog fixtures through the live parser cascade + JSON-LD extractor and asserts >85% of catalog fixtures yield a price (D12 acceptance target).

**Plans**: 2 plans

Plans:

- [ ] 03-01: Metrics + Sentry + per-API-key rate-limit — wire `prometheus-client` into the existing inline counters from Phase 2, add histograms with `Histogram.time()` decorators on the search/llm/visit hot paths, expose `/metrics` endpoint behind same-process middleware (OBS-07); add `sentry-sdk` with `SENTRY_DSN` env-var gating; integrate `slowapi` with `X-API-Key` extractor for per-consumer rate-limit on `/search` (does not replace the BROWSER-04 1/min Google rate-limit). CI: `curl /metrics` smoke test.
- [ ] 03-02: Challenge detection + backoff + degraded-mode + integration tests — extend `_detect_block()` (BROWSER-05) with a `ChallengeBackoff` state machine that exponentially delays next-fetch on consecutive blocks, persists last-block-at in sqlite for restart survival; harden the LLM-down degraded path with a synthetic-load test that kills the router and asserts `/search` keeps serving; build `tests/integration/` suite that replays the Phase 1 fixture set through the live parser cascade + JSON-LD extractor + visit-pass classifier and asserts the D4 cascade alert fires on a deliberately-broken fixture and >85% catalog price extraction (validates D12 hand-roll decision in production).

**Duration**: 1 week (matches PRD §7 Fase 2 estimate)

### Phase 4: Production Operations

**Goal**: On-demand production tooling — Grafana dashboards backed by the Phase 3 Prometheus metrics, Loki log aggregation, cache invalidation endpoint, and OpenTelemetry tracing if latency investigation demands it. **Scope is gated by actual prod telemetry**, not pre-emptive build.
**Depends on**: Phase 3 (Prometheus + Sentry shipping; need 2+ weeks of prod data to know which dashboards matter)
**Requirements**: None from v1 — all v1 requirements close in Phases 1-3. This phase covers v2 ADV-01, ADV-02 (already wired in Phase 3 — Sentry), ADV-03 (Loki), ADV-04 (tracing) on demand. Listed here only if Sánchez asks for them or prod data forces them.
**Success Criteria** (what must be TRUE):

  1. A Grafana dashboard exists on the VPS showing P50/P95 `/search` latency, cache hit ratio, LLM fallback rate, top-N visit_failed hosts, and challenge_detected count — accessible from Luis's browser, no auth bypass.
  2. Loki ingests structlog JSON from the container; a single `correlation_id` query in Grafana surfaces the full request trace across `lifespan` + `search` + `llm` + `visit` + `cache` stages.
  3. `POST /admin/cache/invalidate` (API-key gated) deletes specific cache rows by query hash or wildcard pattern; sqlite WAL stays consistent; subsequent `/search` for the invalidated query triggers a fresh fetch.
  4. (Conditional, only if P95 cold >40s for >2 days) OpenTelemetry trace spans are emitted around browser fetch / LLM filter / visit pass; a Tempo/Jaeger backend on the VPS receives them.

**Plans**: TBD (work composed on demand based on Phase 3 telemetry — typical plans below)

Plans:

- [ ] 04-01: Grafana + Loki on the VPS — Compose additions for `grafana`, `loki`, `promtail` containers; provisioned dashboard JSON committed under `ops/grafana/`; structlog already emits JSON so promtail tail of container logs suffices; Loki query examples in `ops/loki/QUERIES.md`. Only ship if Luis or Sánchez asks; otherwise Phase 2 inline counters + Phase 3 `/metrics` cover ops needs.
- [ ] 04-02: Cache invalidation + tracing (optional) — `POST /admin/cache/invalidate` with API-key gating, query-hash or wildcard target; OpenTelemetry instrumentation via `opentelemetry-instrumentation-fastapi` + manual spans on the Cloak/LLM/visit hot paths. Tracing ships ONLY if P95 cold latency exceeds PRD §10 budget (>40s) for 2+ days in prod.

**Duration**: On demand (PRD §7 Fase 3 — "a demanda", no a-priori schedule)

### Phase 5: Expansion

**Goal**: Scale-out work deferred until Sánchez Repuestos outgrows the current Google + LLM-curator architecture — per-supplier B2B adapters, residential proxy if Google IP-blocks the VPS, async + SSE if sync latency becomes a bottleneck, multi-tenant auth if a second consumer onboards.
**Depends on**: Phase 4 (real prod data showing one of the four expansion triggers fires) — or explicit business request from Sánchez.
**Requirements**: None from v1. Covers v2 SUP-01, SUP-02, SUP-03, MULTI-01, MULTI-02, MULTI-03. MELI-01 and MELI-02 remain blocked-by-architecture and require a separate Partner Program decision before scoping.
**Success Criteria** (what must be TRUE):

  1. (If SUP-* triggered) A per-supplier adapter package exists (e.g. `adapters/mayorista_frog/`) with auth flow + per-supplier rate-limit + product extractor; `/search` results merge supplier hits with Google curator hits behind a feature flag.
  2. (If residential proxy triggered by Google IP-block >5%/day for 2+ days) `PROXY_URL` env-var routes Cloak fetches through an IPRoyal/Bright Data/Smartproxy endpoint; block-detected rate falls back under 1%/day in a 7-day window.
  3. (If async + SSE triggered by P95 cold >40s sustained 7+ days) `/search/stream` SSE endpoint exists alongside `/search`; clients receive incremental candidates as the LLM filter completes them; total wall-clock unchanged but TTFB <2s.
  4. (If multi-tenant triggered by a second consumer onboarding) API-key registry table in sqlite; per-key quota + per-key rate-limit + per-key billing telemetry counter; no cross-tenant cache leakage (cache key namespaces by key).

**Plans**: TBD (composed when a trigger fires — none staged up-front)

Plans:

- [ ] 05-01: Per-supplier adapter framework (only if Google + LLM curator no longer satisfies Sánchez query mix — measure: <70% useful-hits week over week). Add a `SupplierAdapter` protocol, ship first concrete adapter (most likely Mayorista Frog), wire merge logic into the SEARCH-07 re-rank.
- [ ] 05-02: Residential proxy / async-SSE / multi-tenant auth (each gated independently by its trigger above). Compose at trigger time; do NOT pre-build.

**Duration**: Deferred indefinitely (PRD §7 Fase 4 — "si Sánchez crece")

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Spike & Empirical Validation | 3/3 | Complete   | 2026-06-01 |
| 2. MVP | 0/3 | Planned | - |
| 3. Robustness | 0/2 | Not started | - |
| 4. Production Operations | 0/TBD | Not started | - |
| 5. Expansion | 0/TBD | Not started | - |

## Coverage Check

All 53 v1 requirements from `.planning/REQUIREMENTS.md` are mapped to exactly one phase:

| Category | Requirements | Phase |
|---|---|---|
| SEARCH | SEARCH-01..08 (8) | Phase 2 |
| LLM | LLM-01..08 (8) | Phase 2 |
| VISIT | VISIT-01..08 (8) | Phase 2 |
| FRESH | FRESH-01..04 (4) | Phase 2 |
| CACHE | CACHE-01..05 (5) | Phase 2 |
| BROWSER | BROWSER-01..05 (5) | Phase 2 |
| DEPLOY | DEPLOY-01..06 (6) | Phase 2 |
| OBS (Fase 1 subset) | OBS-01..06 (6) | Phase 2 |
| OBS (Fase 2 subset) | OBS-07 (1) | Phase 3 |
| NF | NF-01..04 (4) | Phase 2 |
| **Total** | **55 requirement IDs across 53 logical reqs** | **Phases 2-3** |

**Coverage:** 53/53 v1 requirements mapped (100%). No orphans. No duplicates.

**Phase 1 carries 0 v1 requirements** — by design. The Spike is empirical validation that gates Phase 2 lock-in of D1, D3, D4, D8, D10, D11, D12. Phase 1 produces fixtures + `SPIKE.md` Go/No-Go; production code starts in Phase 2.

**Phases 4 and 5 carry 0 v1 requirements** — by design. They cover v2 items (ADV-*, SUP-*, MULTI-*) and on-demand operational extensions. None block v1 production-ready.

## Out of Scope Reminder

See `.planning/REQUIREMENTS.md` §"Out of Scope" for the full list. Highlights that MUST NOT appear in any plan:

- Scraping directly any `*.mercadolibre.*` URL (architecture forbids the host, not just the code).
- Residential proxy / IP rotation (Phase 5 only if Google IP-block trigger fires; do NOT pre-build).
- Multi-engine browser fallback (Camoufox) — Cloak is sufficient for Google; v1 proved Camoufox added no value.
- Async + SSE in `/search` (Phase 5 only if latency trigger fires).
- Workers / RQ / Redis / message queues.
- Postgres + Alembic — sqlite covers the cache.
- `uvloop` — banned (D6 foot-gun, Cloak subprocess incompatibility).
- `launch_persistent_context` against Google — banned (D8 foot-gun, Cloak issue #331).
- Retry on malformed LLM JSON (temp=0 → identical output).
- Retry on visit-pass failures (`visit_failed` is the honest signal).
- `instructor`/`outlines`/`pydantic-ai` libs.
- `extruct` library (Phase 1 spike decides hand-roll vs adopt; default is hand-roll per D12).

## Evolution Rules

The roadmap updates at well-defined boundaries:

**After Phase 1 (Spike) completes** (via `/gsd-transition` or `/gsd-execute-phase` 1):

- If `SPIKE.md` reveals D1 Docker tag missing → revise DEPLOY-01 pin in Phase 2 plans before kicking 02-03.
- If D12 spike says microdata-only stores exist in top-10 AR → flip VISIT-06 to use `extruct` and update Phase 2 acceptance.
- If LLM router doesn't support `format=json` token-grammar → adjust LLM-07 acceptance to JSON-mode-only, lower confidence on PRD §10 latency target.
- If `pws=0` triggers consent interstitial → add cookie-banner-dismissal step to Phase 2 plan 02-01 (`build_serp_url()` + first-fetch warmup).

**After Phase 2 (MVP) completes**:

- Move all 53 v1 requirements from `Active` to `Validated` in `PROJECT.md` (with phase reference).
- If any acceptance criterion fails, do NOT advance to Phase 3 — fix in place or split a 2.1 INSERTED decimal phase.
- Update PRD §10 success criteria with measured P50/P95 from end-to-end test.
- Capture lessons in `.planning/SPIKE.md` (rename to `.planning/MVP-LEARNINGS.md`) for Phase 3 planning.

**After Phase 3 (Robustness) completes**:

- Review prod telemetry (cache hit ratio, LLM fallback rate, block_detected count, per-host visit_failed rate).
- Decide if Phase 4 plans are warranted by data (Grafana yes/no; tracing yes/no; cache invalidation likely yes by month 2).
- If a per-host visit_failed rate >30% sustains → consider `curl-cffi` TLS-impersonation in Phase 4 plan (was deferred from MVP per `research/SUMMARY.md §7`).

**After Phase 4 (Operations) completes**:

- Re-evaluate Phase 5 triggers (Google block rate, P95 latency, supplier coverage, second consumer interest).
- If no trigger fires within 3 months of Phase 4 close → declare v1.0 complete and freeze the roadmap; new work spawns a v1.1 milestone via `/gsd-complete-milestone`.

**Decimal phase insertion** (e.g. `2.1`): use only for urgent post-execution corrections (e.g. parser cascade fix mid-Phase 3) — never for scope additions. Decimal phases live between integers in execution order: `1 → 2 → 2.1 → 3`.

---
*Roadmap created: 2026-06-01 by gsd-roadmapper from PRD v0.1 + research synthesis (5 docs).*
*Mirrors PRD §7 Fase 0..4 structure (validated by research as sound, no structural deviations).*

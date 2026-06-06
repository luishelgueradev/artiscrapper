# Milestones

## v0.2 Paridad Visual + Robustez del Parser (Shipped: 2026-06-06)

**Phases shipped:** 4 of 5 planned (0.2.1, 0.2.2, 0.2.3, 0.2.5; 0.2.4 cancelled)
**Plans shipped:** 11 (2 + 3 + 2 + 4)
**Total commits:** 75
**Timeline:** 2026-06-05 → 2026-06-06 (2 days wall-clock)
**Project LOC:** ~11,408 lines tracked Python (src/ + tests/ + scripts/), +10,241 / -191 net delta over v0.2
**Test suite:** 113 → 126 (+13 net new tests; 124 passed / 2 skipped / **0 warnings** at close)
**Cancelled:** Phase 0.2.4 (SerpAPI Ground-Truth Spike) — violates the standing project constraint "no paid services of any kind" persisted as `feedback_no_paid_services` standing rule.

### Key Accomplishments

1. **Parser visual parity (Phase 0.2.1)** — Applied the 3 surgical patches from the parser-visual-parity report. Switched browser `wait_until` for Shopping panel render, added `_extract_pla_unit()` aditivo al cascade, closed the `$410.420,311001` price-regex bug (`,DD` cierre obligatorio). Empirically validated **+207% URLs reales** + **+74% productos con precio** across 5 saturated commercial queries (electro / ropa / libro / electrónica / deporte). Endpoint `GET /admin/parity/{query}` shipped with 2 minimal Prometheus gauges.

2. **Continuous parity harness (Phase 0.2.2)** — Canonical 12-query dataset (6 verticals × 2 specificity levels) in `tests/fixtures/parity-dataset.yaml`. 3 Prometheus gauges (`parity_coverage_pct{query}`, `parity_pla_units_missed{query}`, `parity_url_synthetic_ratio{query}`). 1/N async sample on the hot path (p99 overhead <50ms measured). GitHub Actions nightly that fails CI at <75% avg coverage. 3 Prometheus alert rules (Warn @75%>30min + Fail @50%>5min).

3. **Page 2 pagination (Phase 0.2.3)** — `build_serp_url(page=N)` with `&start=10*(N-1)`, `settings.SEARCH_FETCH_PAGES` (default 2, validated [1,3], env-overridable as a 1-flip rollback path). `POST /search` loops N×2 fetches in `asyncio.gather`. 2 frozen page-2 fixtures (termotanque + zapatillas) + 4 integration tests pinning the 4-fetch flow, dedupe-across-pages, and the rollback to single-page. Empirical gain measured live on saturated queries: **+39% candidate volume** (271 → 376 across 5 queries; 4 of 5 show 20-69% gain). UAT verified 19/19 calls succeeded post-fix.

4. **v0.2.3 stability hardening (issue #1 + 3 Gap fixes)** — Browser singleton was dying under N×2 sustained pressure due to `wait_until="load"` timeout cascade (issue #1). Fixed by switching to `wait_until="domcontentloaded"` + best-effort `wait_for_selector("div.pla-unit", state="attached", timeout=2_500)`. Additional Gap fixes: `compose.yml` env passthrough for `SEARCH_FETCH_PAGES` (Gap A — the rollback knob was a no-op pre-fix), honest `google_fetches` accounting on every non-success Metadata path including cache_hit / 503 / exception / block_detected (Gap C). Post-fix: 14 consecutive `/search` calls with 0 browser deaths; `block_detected_total{sorry_redirect}` now correctly surfaces real Google blocks that previously hid behind `TargetClosedError`. Footgun test added that greps `page.goto(.*wait_until="load")` to prevent regression.

5. **Project constraint locked in code + memory: "no paid services of any kind"** — Phase 0.2.4 (SerpAPI Ground-Truth Spike) cancelled the moment SerpAPI's pricing was presented. Two standing rules persisted to agent memory: `feedback_no_paid_services` (never propose paid SaaS dependencies — no SerpAPI, Bright Data, Oxylabs, OpenAI cloud, Sentry tier paid, observability SaaS, etc.) + `feedback_browser_rendered_ground_truth` (the only valid ground truth for artiscrapper is what the explorer renders with price + URL — if the render breaks, fix the render, don't change the source). ROADMAP / REQUIREMENTS / PROJECT.md updated to reflect both.

6. **Carried tech debt v0.1 closed (Phase 0.2.5)** — `tldextract` `.registered_domain` → `.top_domain_under_public_suffix` rename at the single call site (tldextract 6.x does NOT exist on PyPI; the deprecation warning live in 5.3.1 was the actual root cause). FastAPI `default_response_class=ORJSONResponse` fully removed (Pydantic-Rust default is the fast path per PR #14964). `httpx2==2.3.0` added as dev dep (Starlette's testclient auto-detects) + `filterwarnings = ["error::DeprecationWarning"]` always-on in `pyproject.toml` (gate is now the default, not opt-in). `scripts/spike/` ruff-zero via source rename `l → line` (5 sites split 2/3 across two files) + dead-assignment cleanup — NO per-file-ignores, NO `# noqa` shortcuts (preserves regression lint coverage if any spike is revived). Suite went 1 → **0 warnings** at close.

### Key Decisions (carried into PROJECT.md)

- **The browser is the only ground truth.** Cloak/Playwright rendering with price + URL is the contract; if it breaks we fix the render, never switch sources. Codified by Phase 0.2.4 cancellation + the two `feedback_*` standing memories.
- **No paid services.** Hard project constraint. Any future suggestion that introduces recurring SaaS cost is out of scope without discussion.
- **`wait_until="load"` is a foot-gun under concurrency.** Phase 0.2.1 chose it for Shopping panel render; Phase 0.2.3 N×2 exposed the fragility; phase-end fix is `domcontentloaded` + best-effort `wait_for_selector("div.pla-unit")`. Footgun test pins the lesson.
- **Empirical retest after default-bumps is non-negotiable.** Gap A (compose env passthrough missing) and the `SEARCH_FETCH_PAGES` rollback test caught a runtime/source mismatch that unit tests couldn't see. Standing memory `feedback_empirical_retest_after_default_changes` updated.
- **Drop pydantic-default leaks on non-success paths.** Gap C: every Metadata construction site now passes `google_fetches=` explicitly (0 for cache_hit / 503 / exception, `len(htmls)` for block_detected). Default flipped 2 → 0. Two regression tests pin the semantics.

### Known Deferred (not blocking close)

- `feedback_compose_build_recreate` known gotcha re-validated: `docker compose build` + `compose up --force-recreate` separately is the only reliable cycle in this dev box; combined `up -d --build` can hang ~25min and may not auto-recreate.
- WR-01 (rate-limiter `Semaphore(1)` serialization risk) and WR-02 (parity-audit page-1-only) surfaced by code review on Phase 0.2.3 — both advisory follow-ups for future milestones; do NOT trigger today because `GOOGLE_MIN_INTERVAL_S=0` is the deployed default.

### What Did NOT Ship

- **Phase 0.2.4 (SerpAPI Ground-Truth Spike)** — cancelled with strikethrough in ROADMAP, REQUIREMENTS SERPAPI-01/02 marked cancelled. Reason persisted as standing memory. Coverage Check footnote: 19 → 17 active REQ-IDs.

---

## v0.1 MVP — Google + LLM curator (Shipped: 2026-06-04)

**Phases shipped:** 4 (Phase 1 Spike + Phase 2 MVP + Phase 3 Robustness + Phase 3.1 v0.1 close hygiene)
**Plans shipped:** 11 (3 + 3 + 2 + 3)
**Total commits:** 125
**Timeline:** 2026-06-01 → 2026-06-04 (3 days)
**Project LOC:** ~5,876 lines (src/ + tests/)
**Audit:** `.planning/milestones/v0.1-MILESTONE-AUDIT.md` — status `passed`, 55/55 v1 reqs satisfied, 10/10 cross-phase integration WIRED, 5/5 E2E flows PASS, 3/3 Nyquist VALIDATION.md accepted.

### What Shipped

A single-container FastAPI service (`POST /search`) for Sánchez Repuestos auto-parts inventory:

- **Phase 1 — Spike & Empirical Validation** (2026-06-01, 3 plans, 0 v1 reqs by design): Verified Cloak Docker tag `cloakhq/cloakbrowser:0.3.31`, confirmed D8 (no `launch_persistent_context` — CAPTCHA loop), measured local-llms-router OpenAI-compat behavior (TTFT, KV-cache, per-bearer concurrency), captured 10 SERP + 10 catalog PDP fixtures + 50 hand-labeled candidates, decided D12 hand-roll JSON-LD (vs extruct), produced SPIKE.md Go/No-Go gating Phase 2 lock-in.
- **Phase 2 — MVP** (2026-06-02, 3 plans, 53 v1 reqs): End-to-end `/search` pipeline — SearchRequest/Response Pydantic models, build_serp_url with `pws=0&safe=off`, parser cascade `tF2Cxc → Ez5pwe → MjjYud → h3-anchored` with `parse.cascade.exhausted` alert, URL canonicalize+dedupe, junk-domain blocklist pre-filter, Spanish LLM curator with 2 few-shot + `<0.4` confidence cutoff + `metadata.llm_degraded` surfacing, degraded-mode heuristic fallback (price-in-card), visit pass with httpx http2 + global+per-host Semaphores + hand-rolled JSON-LD/OG/microdata/AR-regex extractor, freshness logic, aiosqlite WAL cache with gzipped BLOBs + lazy TTL + hourly prune, single-image Dockerfile + compose.yml, structlog JSON + correlation_id + cheap/deep health endpoints + inline metric counters. PRD §10 success criteria empirically validated on real queries (`pelota playera quico`, `filtro aceite ford focus`).
- **Phase 3 — Robustness** (2026-06-03, 2 plans, OBS-07 + hardening overlay): Production-grade `/metrics` ASGI sub-app with 12 canonical `artiscrapper_*` Prometheus families + workload-tuned Histograms, env-gated Sentry SDK with correlation_id tag injection, stacked slowapi X-API-Key rate-limit (60/min + 10000/day) with Retry-After headers, Google challenge-detection backoff state machine (`min(60 * 2^retries, 3600)` curve) with sqlite single-row persistence surviving container restart, /search 503+Retry-After when gate denies, Phase-1 fixture-replay integration suite pinning ≥85% catalog price extraction (measured 100%) + ≥5 useful survivors from 50-record LLM-down set (measured 28/50). 6/6 ROADMAP success criteria + 20/20 D-NN decisions + 21/21 threat mitigations + 10/10 operator UAT all PASS.
- **Phase 3.1 — v0.1 close hygiene (INSERTED)** (2026-06-04, 3 plans, 0 new v1 reqs): Closed 5 medium-severity tech_debt items + 4 low-severity Phase-2 review WARNINGs surfaced by pre-3.1 audit. Traceability bookkeeping (55 REQUIREMENTS.md rows flipped Pending→Complete + 4 SUMMARY frontmatters populated + 3 VALIDATION.md formal accepts); test coverage (X-API-Key on e2e, degraded-mode TestClient sibling with real Phase-1 fixture); slowapi settings-source-of-truth refactor (Pattern B — module constants referenced by `@limiter.limit()` decorator argument AND `rate_limit_init` log line; Pattern A `default_limits` revealed non-viable on slowapi 0.1.9 + FastAPI by empirical regression); empirical D-06 retest PASS; WR-01 tldextract MELI guard + regression (eliminates `notmercadolibre.com` false-positive class) + WR-02 verify-only + WR-03 tautology fix + WR-04 NamedTemporaryFile leak → mkdtemp+atexit. 11/11 must-haves verified.

### Key Decisions (carried into PROJECT.md)

- **Architecture:** 1 container Docker, sync HTTP, sqlite cache — no Postgres/Redis/RQ/Camoufox (YAGNI for 500-2000 q/day from 1 client).
- **D2 foot-gun:** LLM timeout fallback `confidence=0.3` IS dropped at `<0.4` cut; `metadata.llm_degraded=true` when >50% fall back.
- **D6 foot-gun:** `uvicorn --loop asyncio --workers 1` always; uvloop BANNED (Cloak subprocess pipe incompatible).
- **D8 foot-gun:** Singleton Browser + ephemeral `new_context()` per request; `launch_persistent_context` banned (Cloak issue #331).
- **Phase 3 D-05/D-06 (Pattern B):** slowapi rate-limit module constants → decorator argument + log line; drift impossible by construction; `Limiter(default_limits=...)` rejected after empirical regression.
- **Phase 3.1 WR-01:** MELI guard uses `tldextract.registered_domain` membership check instead of substring; eliminates over-matching `notmercadolibre.com`.

### Phases 4-5 — Deferred-by-Design

Per ROADMAP §Coverage Check, Phases 4 (Production Operations) and 5 (Expansion) carry **zero v1 requirements**. Both are gated on production triggers (Phase 4 = prod telemetry demand; Phase 5 = growth triggers per supplier/proxy/SSE/multi-tenant). Per `/gsd-audit-milestone v0.1` recommendation (option B):

**Decision:** Phases 4-5 are **deferred-by-design — re-evaluated for v0.2 trigger conditions**. Phase 4-01 (Grafana + Loki) is marked complete in the original ROADMAP (`completed 2026-06-03`) but produced no v1 reqs — recorded as informational, not as v0.1 scope. Phase 4-02 (cache invalidation + tracing) and all of Phase 5 remain not-started, awaiting their triggers.

### Carried Tech Debt → v0.2

Items tracked but not blocking v0.1:

1. tldextract 5.3.1 → 6.x migration (`.registered_domain` → `.top_domain_under_public_suffix` rename).
2. FastAPI ORJSONResponse deprecation cleanup.
3. Starlette/httpx TestClient → httpx2 migration (test-time only).
4. ruff debt in `scripts/spike/` + `artifacts/spike/` (48 errors — Phase 1 quick-spike code).
5. `browser_uses += 2` accounting under partial fetch failure (conservative under-counting toward recycle gate; not a correctness bug).

### Known Deferred Items (artifact-audit)

- `02-HUMAN-UAT.md`: status=resolved, 0 pending scenarios (false-positive flag from artifact scanner; closed in Phase 2).

### Archives

- `.planning/milestones/v0.1-ROADMAP.md` — full original roadmap with all 5 phases.
- `.planning/milestones/v0.1-REQUIREMENTS.md` — full original requirements table with 55 v1 + 13 v2 reqs.
- `.planning/milestones/v0.1-MILESTONE-AUDIT.md` — post-3.1 audit (status `passed`).

---

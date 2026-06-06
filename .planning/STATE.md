---
gsd_state_version: 1.0
milestone: v0.2
milestone_name: Paridad Visual + Robustez del Parser
status: Phase 0.2.5 complete; milestone v0.2 close-out pending
stopped_at: Phase 3.1 Plan 03 partial (Wave 3 Tasks 1+2 — D-05 Pattern B refactor of src/artiscrapper/main.py + new tests/test_main.py propagation invariant; commits 1f44310 (refactor), f29ee77 (test). Full quick suite 68 passed / 2 deselected — +1 vs prior baseline. Task 4 (D-06 empirical retest) queued for orchestrator; non-autonomous because it needs docker compose bump-and-recreate cycle.)
last_updated: "2026-06-06T03:58:54.671Z"
last_activity: 2026-06-06 -- Phase 0.2.5 planning complete
progress:
  total_phases: 5
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# State: artiscrapper v0

**Project initialized:** 2026-06-01
**Reset of:** artiscrapper v1 (codebase + git history discarded 2026-06-01)
**Mode:** YOLO · **Granularity:** Coarse · **Parallel:** Yes · **Quality gates:** All 3 (research + plan-check + verifier)

## Current Position

Phase: 0.2.5 Carried Tech Debt — Complete
Plan: 01 + 02 + 03 + 04 (4/4)
Status: Phase shipped 2026-06-06 — verifier 4/4 must-haves green, code review 0 critical, suite 124/2 + 0 warnings under always-on DeprecationWarning gate. Milestone v0.2 status: 0.2.3 + 0.2.5 ✓, 0.2.4 cancelled, 0.2.1 + 0.2.2 boxes stale in ROADMAP (work shipped earlier but checkboxes never flipped — pending /gsd:complete-milestone audit).
Last activity: 2026-06-06 — Phase 0.2.5 closed (4 TECHDEBT items shipped)

## Recent Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-06-01 | Discard artiscrapper v1 (codebase + git history) | v1 entregaba 7 productos por query igual que una búsqueda manual de Google; multi-source orchestrator vacío sin fuentes activas; MELI directo no factible sin proxy residencial (deferido a Fase 3 v1, nunca arrancado); ~15.000 LOC para entregar lo mismo que un script de 600-1000 |
| 2026-06-01 | PRD v0.1 como single source of truth — Google + LLM curator + selective visit pass | Insight: Google ya aggregating MELI catalog en su SERP — usarlo evita pelear con MELI WAF |
| 2026-06-01 | NO MELI direct (cualquier `*.mercadolibre.*`) en arquitectura, no solo en código | API oficial 403 incluso autenticada post-abril 2025; browser path → /gz/account-verification; investigación confirma proxy residencial es el único path técnico real, deferido |
| 2026-06-01 | 1 container Docker, sync HTTP, sqlite cache — sin Postgres/Redis/RQ/Camoufox | YAGNI: el volumen 500-2000 q/día desde 1 cliente no justifica la operativa de 5 containers |
| 2026-06-01 | Cloak pin bump 0.3.28→0.3.31, chromium .177.4→.177.5 (D1) | Research verificó: no breaking deps, stealth-patch refresh |
| 2026-06-01 | Singleton Browser + ephemeral `new_context()` per request (D8) | Cloak issue #331: `launch_persistent_context` = CAPTCHA loop garantizado |
| 2026-06-01 | `--loop asyncio --workers 1` siempre, uvloop BANNED (D6) | Cloak README: uvloop subprocess pipe incompatible con Playwright |
| 2026-06-01 | Parser cascade `tF2Cxc → Ez5pwe → MjjYud → h3-anchored` con alert `parse.cascade.exhausted` (D4) | Google rota selectors obfuscados ~trimestralmente |
| 2026-06-01 | Heuristic pre-filter (junk-domain blocklist) ANTES del LLM (D9) | Drops ~30% del noise, LLM phase de p95 ~22s a ~10s |
| 2026-06-01 | LLM confidence=0.3 fallback IS dropped at the <0.4 cut (D2 reconciliación) | PRD §3 step 5 manda; consumidor lo ve vía `metadata.llm_degraded` |
| 2026-06-03 | Phase 3: stacked `@limiter.limit("60/minute") + @limiter.limit("10000/day")` on /search with `Response` param for slowapi header injection | slowapi 0.1.9 requires a starlette `Response` parameter to inject `X-RateLimit-*` + `Retry-After` headers; pydantic return models break header injection without it |
| 2026-06-03 | Phase 3: WRN-04 invariant — Sentry log event name DERIVED from SDK state, pinned by parametrised lifespan test | Prevents log/SDK divergence (`sentry_init_done` emitted while client inactive) silently regressing observability |
| 2026-06-03 | Phase 3: ChallengeBackoff via aiosqlite WAL + INSERT OR IGNORE seed; bind-mount `./data/cache.db:/app/cache.db` survives `compose up --force-recreate` | State must survive container recreation; idempotent seed + bind-mount verified empirically (UAT test 8) |
| 2026-06-03 | Phase 3: /metrics mounted as ASGI sub-app via `make_asgi_app()` BEFORE CorrelationIdMiddleware, unauthenticated by design (D-10) | Prometheus scrapers cannot send X-API-Key; `test_metrics_endpoint_unprotected_by_design` pins the design choice |
| 2026-06-04 | Phase 3.1 Plan 02: WR-01 MELI guard uses tldextract.registered_domain instead of `"mercadolibre." in netloc` substring (frozenset of 8 MELI registered domains) | Substring over-matched notmercadolibre.com / mercadoliberia.com; tldextract 5.3.1 already pinned + public-suffix-aware; no new dep |
| 2026-06-04 | Phase 3.1 Plan 02: WR-02 verify-only (no source diff) — strong-ref pattern already in place at main.py:207 + 668-670 | Audit text referenced pre-Phase-3 line numbers; re-emitting a fix would produce no-op diff + falsely claim a fix (R-02 mitigation) |
| 2026-06-04 | Phase 3.1 Plan 02: WR-04 uses tempfile.mkdtemp + atexit.register cleanup (NOT pytest tmp_path) for tests/test_health.py CACHE_DB_PATH | CACHE_DB_PATH must be set at module-import time before pydantic-settings reads env; tmp_path is function-scope and fires too late |
| 2026-06-04 | Phase 3.1 Plan 03: D-05 lands as Pattern B (module constants referenced by @limiter.limit decorator args), NOT Pattern A (Limiter default_limits) | Empirical: slowapi 0.1.9 does NOT auto-apply default_limits without SlowAPIMiddleware, and SlowAPIMiddleware crashes on first request in 0.1.9+FastAPI (AttributeError on TypeError). Pattern B preserves the single-source-of-truth intent (drift impossible by construction) without depending on broken middleware. See 03.1-03-PLAN.md Deviation Note (2026-06-04). |

## Active TODOs

- _none active_ — Phase 3 closed with 0 outstanding issues (10/10 UAT pass, 21/21 threats SECURED). Phase 4 marked `deferred` in ROADMAP pending prod telemetry trigger.

## Known Risks (from research SUMMARY.md §8)

- **Anti-bot risk at Google scale** (MEDIUM): community estimate <5%/day para 1 q/min from datacenter IP, NO medido empíricamente para nuestro stack. Phase 1 spike lo confirma o desmiente.
- **Per-host visit anti-bot rate** (MEDIUM): Falabella / VTEX-Akamai 403 rate desconocido. Aceptado como `visit_failed` flag en MVP; revisitar con `curl-cffi` en Phase 3 si >30% sostenido.
- **JSON-LD coverage en stores AR menores** (MEDIUM): inferido ~75-85% de e-commerce AR ship JSON-LD Product; Phase 1 fixture sweep lo confirma per-host.
- **LLM router model & schema support** (MEDIUM): no sabemos qué modelo está sirviendo `local-llms-router`, ni si soporta `format=<json_schema>` token-level grammar vs solo `format=json`. Phase 1 lo descubre.
- **Chromium memory drift** (MEDIUM): Playwright issue #15400 documenta memory leak gradual. `BROWSER_RECYCLE_AFTER=200` es estimate; Phase 1 mide el threshold real.

## Foot-guns (NUNCA OLVIDAR — surface en cada phase plan)

1. **D2** — LLM timeout fallback `confidence=0.3` está POR DEBAJO del cutoff `<0.4`. Esto significa que los candidatos timed-out **SÍ se descartan** por LLM-05 a menos que tengan otra señal. `metadata.llm_degraded=true` cuando >50% caen. **No "ablandar" el cutoff "para que entren los timeouts" — eso era el bug que el research surface**.
2. **D6** — `uvicorn --loop asyncio --workers 1` SIEMPRE. NUNCA instalar `uvloop` (subprocess pipe protocol incompatible con Cloak/Playwright). CI assertion en Phase 2.
3. **D8** — NUNCA usar `cloakbrowser.launch_persistent_context()` contra Google. Cloak issue #331 = CAPTCHA loop garantizado. Singleton `Browser` en lifespan + ephemeral `new_context()` por request.

## Quick Tasks Completed

| Date | Task ID | Description | Commits |
|---|---|---|---|

_(none yet — quick tasks track ad-hoc fixes outside the phase structure)_

## Session Continuity

- **Last session:** 2026-06-04T04:00:00.000Z
- **Stopped at:** Phase 3.1 Plan 03 partial (Wave 3 Tasks 1+2 — D-05 Pattern B refactor of src/artiscrapper/main.py + new tests/test_main.py propagation invariant; commits 1f44310 (refactor), f29ee77 (test). Full quick suite 68 passed / 2 deselected — +1 vs prior baseline. Task 4 (D-06 empirical retest) queued for orchestrator; non-autonomous because it needs docker compose bump-and-recreate cycle.)
- **Resume command:** orchestrator runs Task 4 D-06 (recipe in 03.1-03-PLAN.md `<how-to-verify>` Steps 1-10)
- **Files to load next session:**
  - `.planning/phases/03.1-v0-1-close-hygiene-requirements-md-traceability-flip-summary/03.1-03-PLAN.md` (Deviation Note 2026-06-04 + Task 4 D-06 recipe)
  - `src/artiscrapper/main.py` lines 235-262 (Pattern B module constants + Limiter) and lines 374-375 (decorators) — Pattern B reference for what the runtime log must report
  - `tests/test_main.py` (propagation invariant — extend if Task 4 reveals additional drift surface)
  - `compose.yml` + `.env` (Task 4 mutates API_RATE_PER_MINUTE then restores)

## Evolution

This document evolves at every plan/phase boundary:

- **After each plan**: update "Current Position" + "Recent Decisions" + plan counts.
- **After each phase transition** (`/gsd-transition`): update progress bar + active TODOs + blockers; promote insights to PROJECT.md if they change architecture.
- **After each milestone** (`/gsd-complete-milestone`): full audit; reset Active TODOs; archive Recent Decisions older than the milestone.

## Accumulated Context

### Roadmap Evolution

- Phase 3.1 inserted after Phase 3: v0.1 close hygiene: traceability + frontmatter + test_e2e auth + degraded TestClient + slowapi drift + nyquist accept (URGENT)

## Operator Next Steps

- Start the next milestone with /gsd-new-milestone

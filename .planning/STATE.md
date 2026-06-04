---
gsd_state_version: 1.0
milestone: v0.1
milestone_name: "close hygiene: REQUIREMENTS.md traceability flip + SUMMARY frontmatter population + tests/test_e2e.py X-API-Key header + degraded-mode TestClient coverage + slowapi rate-limit settings-source-of-truth + Nyquist wave-0 accept/complete for phases 1-3"
status: executing
stopped_at: Phase 3.1 Plan 02 executed (Wave 2 — tests + WR cleanup)
last_updated: "2026-06-04T03:00:00.000Z"
progress:
  total_phases: 5
  completed_phases: 3
  total_plans: 10
  completed_plans: 10
  percent: 70
---

# State: artiscrapper v0

**Project initialized:** 2026-06-01
**Reset of:** artiscrapper v1 (codebase + git history discarded 2026-06-01)
**Mode:** YOLO · **Granularity:** Coarse · **Parallel:** Yes · **Quality gates:** All 3 (research + plan-check + verifier)

## Current Position

Phase: 3.1
Plan: 02 complete (Wave 2 — tests + WR cleanup); Plan 03 pending

- **Active phase:** 3.1 (v0.1 close hygiene; 2/3 plans done, 1 plan to go in wave 3)
- **Phases completed:** 3/5 (1, 2, 3 — Phase 3.1 still in progress)
- **Plans completed:** 10 total (3+3+2+2; Plan 03.1-02 closed 2026-06-04)
- **Quick tasks completed:** 0
- **Next command:** `/gsd-execute-phase 3.1 --plan 03` to run Wave 3 (slowapi settings-source-of-truth refactor + D-06 empirical retest)

```
Phase 1   — Spike & Empirical Validation       [x] complete      (2026-06-01, 3/3 plans)
Phase 2   — MVP                                 [x] complete      (2026-06-02, 3/3 plans)
Phase 3   — Robustness                          [x] complete      (2026-06-03, 2/2 plans)
Phase 3.1 — v0.1 close hygiene (INSERTED)       [~] in progress   (2/3 plans done: 01-bookkeeping + 02-tests-WR; 03-slowapi-refactor pending)
Phase 4   — Production Operations               [ ] deferred      (on demand from prod telemetry)
Phase 5   — Expansion                           [ ] deferred      (on growth trigger)
```

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

- **Last session:** 2026-06-04T03:00:00.000Z
- **Stopped at:** Phase 3.1 Plan 02 executed (Wave 2 — D-03 X-API-Key in e2e + D-04 degraded-mode TestClient + WR-01 tldextract guard + WR-02 verify-only + WR-03 tautology fix + WR-04 mkdtemp+atexit; 7 commits bd9d176, f9f25fc, d527e4d, 626314c, aa9937e, e5390e5, 58be58d. Full quick suite 67 passed / 2 deselected.)
- **Resume command:** `/gsd-execute-phase 3.1 --plan 03`
- **Files to load next session:**
  - `.planning/v0.1-MILESTONE-AUDIT.md` (tech_debt[4] = slowapi settings-source-of-truth refactor is what Plan 03 closes)
  - `.planning/ROADMAP.md` §Phase 3.1 entry (line 128)
  - `.planning/phases/03.1-v0-1-close-hygiene-requirements-md-traceability-flip-summary/03.1-RESEARCH.md` §1 (slowapi default_limits pattern A — chosen recipe)
  - `.planning/phases/03.1-v0-1-close-hygiene-requirements-md-traceability-flip-summary/03.1-03-PLAN.md` (Wave 3 plan)
  - `src/artiscrapper/main.py` lines 240 + 354-362 (Limiter constructor + /search decorator stack — targets of the D-05 refactor)

## Evolution

This document evolves at every plan/phase boundary:

- **After each plan**: update "Current Position" + "Recent Decisions" + plan counts.
- **After each phase transition** (`/gsd-transition`): update progress bar + active TODOs + blockers; promote insights to PROJECT.md if they change architecture.
- **After each milestone** (`/gsd-complete-milestone`): full audit; reset Active TODOs; archive Recent Decisions older than the milestone.

## Accumulated Context

### Roadmap Evolution

- Phase 3.1 inserted after Phase 3: v0.1 close hygiene: traceability + frontmatter + test_e2e auth + degraded TestClient + slowapi drift + nyquist accept (URGENT)

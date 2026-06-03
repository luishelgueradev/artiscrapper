---
gsd_state_version: 1.0
milestone: v0.1
milestone_name: milestone
status: ready_to_plan
stopped_at: Phase 3 context gathered
last_updated: "2026-06-03T19:50:48.469Z"
progress:
  total_phases: 5
  completed_phases: 2
  total_plans: 8
  completed_plans: 6
  percent: 40
---

# State: artiscrapper v0

**Project initialized:** 2026-06-01
**Reset of:** artiscrapper v1 (codebase + git history discarded 2026-06-01)
**Mode:** YOLO · **Granularity:** Coarse · **Parallel:** Yes · **Quality gates:** All 3 (research + plan-check + verifier)

## Current Position

Phase: 03 (robustness) — EXECUTING
Plan: 1 of 2

- **Active phase:** _none yet_ (project initialized, ready to plan)
- **Phases completed:** 0/5
- **Plans completed:** 0
- **Quick tasks completed:** 0
- **Next command:** `/gsd-plan-phase 1` to start Phase 1 (Spike & Empirical Validation)

```
Phase 1 — Spike & Empirical Validation       [ ] not started   (1 day, 0 v1 reqs)
Phase 2 — MVP                                 [ ] not started   (2-3 days, 53 v1 reqs)
Phase 3 — Robustness                          [ ] not started   (1 week, OBS-07 + extensions)
Phase 4 — Production Operations               [ ] deferred      (on demand from prod telemetry)
Phase 5 — Expansion                           [ ] deferred      (on growth trigger)
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

## Active TODOs

- _none — project just initialized_

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

- **Last session:** 2026-06-03T17:41:14.053Z
- **Stopped at:** Phase 3 context gathered
- **Resume command:** `/gsd-plan-phase 1`
- **Files to load next session:**
  - `.planning/ROADMAP.md` (Phase 1 goal + 3 plans + acceptance criteria)
  - `.planning/REQUIREMENTS.md` (Traceability table, Phase 1 row)
  - `.planning/research/SUMMARY.md` (12 open Phase-0-spike questions + 13 deviations + foot-guns)
  - `.planning/PROJECT.md` (Active requirements + Key Decisions)
  - `PRD.md` (canonical spec, sections 3+7+10)

## Evolution

This document evolves at every plan/phase boundary:

- **After each plan**: update "Current Position" + "Recent Decisions" + plan counts.
- **After each phase transition** (`/gsd-transition`): update progress bar + active TODOs + blockers; promote insights to PROJECT.md if they change architecture.
- **After each milestone** (`/gsd-complete-milestone`): full audit; reset Active TODOs; archive Recent Decisions older than the milestone.

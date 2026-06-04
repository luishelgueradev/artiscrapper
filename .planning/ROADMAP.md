# Roadmap: artiscrapper

## Milestones

- ✅ **v0.1 MVP — Google + LLM curator** — Phases 1, 2, 3, 3.1 (shipped 2026-06-04)
- 📋 **v0.2 (next)** — TBD, started via `/gsd-new-milestone`

## Phases

<details>
<summary>✅ v0.1 MVP — Google + LLM curator (Phases 1, 2, 3, 3.1) — SHIPPED 2026-06-04</summary>

- [x] Phase 1: Spike & Empirical Validation (3/3 plans) — completed 2026-06-01
  *Cloak verify + LLM router probe + visit/extraction spike → SPIKE.md Go/No-Go + 20 raw HTML fixtures + 50 hand-labeled candidates*
- [x] Phase 2: MVP (3/3 plans) — completed 2026-06-02
  *Full `/search` pipeline (parser cascade, LLM curator, visit pass, freshness, sqlite cache) + Dockerfile + tests; 53 v1 reqs SATISFIED*
- [x] Phase 3: Robustness (2/2 plans) — completed 2026-06-03
  */metrics + Sentry + slowapi rate-limit + ChallengeBackoff + fixture-replay integration suite (OBS-07 + 21/21 threats SECURED)*
- [x] Phase 3.1: v0.1 close hygiene (3/3 plans, INSERTED) — completed 2026-06-04
  *REQUIREMENTS.md flip + SUMMARY frontmatters + VALIDATION.md accepts + e2e X-API-Key + degraded TestClient + slowapi Pattern B + WR-01..04 cleanup; 11/11 must-haves verified*

**Deferred-by-design (no v1 reqs assigned):**
- ⏭ Phase 4: Production Operations — on-demand from prod telemetry (Grafana, Loki, cache invalidation, tracing). Phase 4-01 (Grafana+Loki) was sketched 2026-06-03 but produced no v1 reqs. Re-evaluated at v0.2 entry.
- ⏭ Phase 5: Expansion — growth-triggered (per-supplier adapters, residential proxy, async+SSE, multi-tenant auth). Re-evaluated at v0.2 entry.

</details>

### 📋 v0.2 (Planning)

Use `/gsd-new-milestone` to scope the next milestone. Triggers to consider at scoping:

- Phase 4 triggers: P95 cold >40s sustained, per-host visit_failed rate >30%, prod-data demand for Grafana dashboards.
- Phase 5 triggers: Google IP-block rate >5%/day, supplier-adapter request, residential proxy need, multi-tenant onboarding.
- Carried tech debt from v0.1: tldextract 6.x migration, FastAPI ORJSONResponse cleanup, httpx2 test migration, scripts/spike/ ruff debt.

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Spike & Empirical Validation | v0.1 | 3/3 | Complete | 2026-06-01 |
| 2. MVP | v0.1 | 3/3 | Complete | 2026-06-02 |
| 3. Robustness | v0.1 | 2/2 | Complete | 2026-06-03 |
| 3.1. v0.1 Close Hygiene (INSERTED) | v0.1 | 3/3 | Complete | 2026-06-04 |
| 4. Production Operations | (deferred) | 0/TBD | Deferred-by-design | - |
| 5. Expansion | (deferred) | 0/TBD | Deferred-by-design | - |

## Coverage Check

v0.1 shipped with **55/55 v1 REQ-IDs satisfied** (across SEARCH×8 + LLM×8 + VISIT×8 + FRESH×4 + CACHE×5 + BROWSER×5 + DEPLOY×6 + OBS×7 + NF×4). Full traceability table archived at `.planning/milestones/v0.1-REQUIREMENTS.md`.

Phase 4 + 5 ship with **0 v1 requirements** by design.

## Archives

- `.planning/milestones/v0.1-ROADMAP.md` — full v0.1 roadmap with all phase details
- `.planning/milestones/v0.1-REQUIREMENTS.md` — full v0.1 requirements with final SATISFIED status
- `.planning/milestones/v0.1-MILESTONE-AUDIT.md` — post-3.1 audit (status `passed`)
- `.planning/MILESTONES.md` — milestone log

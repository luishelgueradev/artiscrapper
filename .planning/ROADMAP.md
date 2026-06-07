# Roadmap: artiscrapper

## Milestones

- ✅ **v0.1 MVP — Google + LLM curator** — Phases 1, 2, 3, 3.1 (shipped 2026-06-04, archived `.planning/milestones/v0.1-phases/`)
- ✅ **v0.2 — Paridad Visual + Robustez del Parser** — Phases 0.2.1, 0.2.2, 0.2.3, 0.2.5 shipped + 0.2.4 cancelled (shipped 2026-06-06, archived `.planning/milestones/v0.2-*`)
- 🚧 **v0.3 — Consumer-Facing Real URLs + Harness Signal Integrity** — Phases 0.3.1 (hygiene + sleeper bugs) + 0.3.2 (cache page-aware / WR-02) + 0.3.3 (carousel real-URL extraction) (scaffolded 2026-06-07, not started)

## Phases

<details>
<summary>✅ v0.1 MVP (Phases 1, 2, 3, 3.1) — SHIPPED 2026-06-04</summary>

- [x] Phase 1: Spike & Empirical Validation (3/3 plans) — completed 2026-06-01
- [x] Phase 2: MVP (3/3 plans, 53 v1 reqs) — completed 2026-06-02
- [x] Phase 3: Robustness (2/2 plans) — completed 2026-06-03
- [x] Phase 3.1: v0.1 close hygiene (3/3 plans) — completed 2026-06-04

See `.planning/milestones/v0.1-ROADMAP.md` for full phase details.

</details>

<details>
<summary>✅ v0.2 Paridad Visual + Robustez del Parser (Phases 0.2.1, 0.2.2, 0.2.3, 0.2.5) — SHIPPED 2026-06-06</summary>

- [x] Phase 0.2.1: Parser Visual Parity (2/2 plans) — completed 2026-06-05 — +207% URLs reales medidas, pla-unit extractor aditivo, regex precio v2 (cierra `$410.420,311001` bug)
- [x] Phase 0.2.2: Harness de Paridad Visual Continua (3/3 plans) — completed 2026-06-05 — 12-query dataset, 3 Prometheus gauges, 1/N hot-path sample, CI nightly + alerts
- [x] Phase 0.2.3: Paginación Page 2 (2/2 plans + 3 Gap fixes + issue #1) — completed 2026-06-05/06 — N×2 fetches in asyncio.gather, dedupe by canonical URL, +39% candidate gain measured live on saturated queries, browser fragility under N×2 fixed via `wait_until="domcontentloaded"` + selector wait
- [~] Phase 0.2.4: SerpAPI Ground-Truth Spike — **CANCELLED 2026-06-06** (paid-service constraint; standing rule persisted as `feedback_no_paid_services`)
- [x] Phase 0.2.5: Carried Tech Debt v0.1 (4/4 plans) — completed 2026-06-06 — tldextract rename, FastAPI ORJSONResponse fully removed, httpx2 dev dep + always-on `error::DeprecationWarning` filter, scripts/spike ruff-zero via source rename

See `.planning/milestones/v0.2-ROADMAP.md` for full phase details + `.planning/MILESTONES.md` for the shipped summary.

</details>

### 🚧 v0.3 Consumer-Facing Real URLs + Harness Signal Integrity (scaffolded 2026-06-07)

- [ ] **Phase 0.3.1: Hygiene + Sleeper Bugs** - WR-01 cross-field validator (rate-limiter ×N latency cliff), drop orphan `orjson` dep, `/admin/parity` separate rate-limit (5/min/key vs /search's 60), `/health/deep` audit (probe path). Cheap, high-confidence. (~half day)
- [ ] **Phase 0.3.2: Cache Page-Awareness (WR-02)** - Cache schema persists N HTMLs (page-1 AND page-2+) so `_parity_audit_sample` reads the unionized signal. Today: cache hits silently downgrade HARNESS-05 alert signal by ~50% on recurring queries because only `html_a` is persisted while response carries N×2 candidates. (~1 day)
- [ ] **Phase 0.3.3: Carousel Real URLs (CAROUSEL-01)** - Recover non-synthetic merchant URLs for the 30 Shopping carousel items per query, respecting D8 invariant (no `launch_persistent_context`). Research path: inline JSON / data-attrs in captured fixtures; `page.evaluate()` for post-render attrs. Acceptance: ≥50% recovery rate OR documented decision why not. (~1-2 days)

**Phase numbering**: skipped 0.3.0 — direct generic-article framing committed as a 1-commit hygiene before scaffold (commit `5dcb471`).

**Out of v0.3 explicit:** /health/deep real-fetch probe, BROWSER_RECYCLE_AFTER empirical tuning, CI nightly alerting (Slack/issue-open) — all gated on production traffic which doesn't exist yet (per user direction 2026-06-07 "esto no esta en produccion real"). Push to v0.4 when there's real signal to measure.

### 📋 Deferred-by-design (gated, not on any milestone)

- [ ] **Phase 4: Production Operations** — Grafana dashboards, Loki, cache invalidation endpoint, tracing. Gated on prod telemetry demand. _(deferred since v0.1)_
- [ ] **Phase 5: Expansion** — Per-supplier adapters, residential proxy, async+SSE, multi-tenant auth. Gated on growth triggers. _(deferred since v0.1)_

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Spike & Empirical Validation | v0.1 | 3/3 | Complete (archived) | 2026-06-01 |
| 2. MVP | v0.1 | 3/3 | Complete (archived) | 2026-06-02 |
| 3. Robustness | v0.1 | 2/2 | Complete (archived) | 2026-06-03 |
| 3.1. v0.1 Close Hygiene | v0.1 | 3/3 | Complete (archived) | 2026-06-04 |
| 0.2.1. Parser Visual Parity | v0.2 | 2/2 | Complete | 2026-06-05 |
| 0.2.2. Harness Paridad Continua | v0.2 | 3/3 | Complete | 2026-06-05 |
| 0.2.3. Paginación Page 2 | v0.2 | 2/2 | Complete | 2026-06-05 |
| 0.2.4. SerpAPI Ground-Truth Spike | v0.2 | 0/0 | CANCELLED (paid service constraint) | 2026-06-06 |
| 0.2.5. Carried Tech Debt v0.1 | v0.2 | 4/4 | Complete | 2026-06-06 |
| 4. Production Operations | (deferred) | 0/TBD | Deferred-by-design | - |
| 5. Expansion | (deferred) | 0/TBD | Deferred-by-design | - |

## Archives

- `.planning/milestones/v0.1-phases/` — phase docs de v0.1 (01-spike, 02-mvp, 03-robustness, 03.1-close-hygiene)
- `.planning/milestones/v0.1-ROADMAP.md` + `v0.1-REQUIREMENTS.md` + `v0.1-MILESTONE-AUDIT.md` — original v0.1 docs
- `.planning/milestones/v0.2-ROADMAP.md` + `v0.2-REQUIREMENTS.md` — original v0.2 docs (full phase details preserved)
- `.planning/MILESTONES.md` — historical log with shipped summary + key accomplishments per milestone

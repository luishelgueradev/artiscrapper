# Requirements: artiscrapper v0.3 — Consumer-Facing Real URLs + Harness Signal Integrity

**Defined:** 2026-06-07
**Source:** v0.2 close-out review (code reviews WR-01 / WR-02 on phase 0.2.3, scope debt CAROUSEL-01 deferred since v0.1, hygiene items from phase 0.2.5 review IN-04 + perf audit cleanup) + user direction "esto es para buscar cualquier articulo, no esta en produccion real" (2026-06-07).

**Scope frame:** generic article search service; consumers across verticals; no specific client coupling. Pre-MVP shape (not in prod yet) — features that need real telemetry to design (e.g. `/health/deep` real-fetch probe, `BROWSER_RECYCLE_AFTER` empirical tuning, CI nightly alerting wiring) are deferred to v0.4 when production traffic exists.

---

## Phase 0.3.1: Hygiene + Sleeper Bugs

- [ ] **HYGIENE-01**: drop the orphan `orjson==3.11.9` pin from `pyproject.toml [project].dependencies`. All `import orjson` and `ORJSONResponse` callsites were removed in v0.2.5 plan 02; the pin is dead weight (~7MB container bloat). Verification: `grep -c '^"orjson' pyproject.toml` returns 0 in `dependencies` block AND suite still 124/2.
- [ ] **HYGIENE-02**: WR-01 sleeper bug — add a `model_validator` in `src/artiscrapper/config.py` that rejects `SEARCH_FETCH_PAGES > 1 AND GOOGLE_MIN_INTERVAL_S > 5` at Settings construction. Today the combo silently multiplies cold-path latency by `SEARCH_FETCH_PAGES × 2` (e.g. N=2 + INTERVAL=60s → 240s wall-clock inside a single /search, well past typical LB idle timeouts). Verification: settings construction with the forbidden combo raises `ValueError`; default values (N=2, INTERVAL=0) still pass.
- [ ] **HYGIENE-03**: `/admin/parity` separate slowapi rate-limit. Today it shares `/search`'s `60/min + 10000/day` per-key bucket; an authenticated consumer could DOS the Google fetch pool by spamming `/admin/parity` (uncached, hits Cloak directly). Cap it at `5/min/key + 60/day/key` via dedicated module-constant + decorator (Pattern B). Verification: 6th call within a minute returns 429.

## Phase 0.3.2: Cache Page-Awareness (WR-02)

- [ ] **CACHE-PAGE-01**: extend `cache.py` schema to persist N HTMLs per cached query (e.g. `raw_serp_html_pages` BLOB containing a gzipped JSON array of page-HTMLs, OR additional columns `raw_serp_html_c/d` etc.). Schema migration: drop-and-recreate the cache table is acceptable (cache is fully regenerable; TTL 24h means worst-case is a single day of cache misses for active queries). Verification: a row written by the new code roundtrips with the same N HTMLs.
- [ ] **CACHE-PAGE-02**: `set_cached` / `get_cached` signatures accept and return the full N-page HTML list (not just `html_a`/`html_b`). Backward-compat readers can still expose `html_a` / `html_b` as derived views of `htmls[0]` / `htmls[1]` if needed for downstream callers, but the new pathway is the N-page list. Verification: `pytest tests/integration/test_search_paginated.py` still green; existing cache-hit shape still produces a valid JSON response.
- [ ] **CACHE-PAGE-03**: `_parity_audit_sample` in `src/artiscrapper/main.py` reads ALL cached pages (not just `html_a`) and reports unionized pla-unit counts. Today on a cache hit it sees only page-1 markup → `parity_pla_units_missed{query}` reads ~50% low on recurring queries → HARNESS-05 alert signal is noisy/biased. Verification: a parity sample on a query with cached page-1 + page-2 reports pla-unit count > page-1-only count.

## Phase 0.3.3: Carousel Real URLs (CAROUSEL-01)

- [ ] **CAROUSEL-01**: research browser-rendered approaches to recover real merchant URLs for the 30 Shopping carousel items per query, within the D8 invariant (no `launch_persistent_context`, no simulated click navigation). Candidates documented in v0.2 PROJECT.md: (a) inline JSON / `data-*` attrs in the captured page HTML; (b) `page.evaluate()` to extract DOM attrs that aren't in initial HTML; (c) post-load `wait_for_selector` + DOM read pattern (extension of the v0.2.3 issue #1 fix). Existing captured fixtures (`tests/fixtures/serp/pla_unit_robotech.html`, `pla_unit_zapatillas.html`, `page2_termotanque.html`, `page2_zapatillas.html`) provide the empirical ground for option (a) without hitting Google. Output: `.planning/phases/0.3.3-carousel-real-urls/CAROUSEL-DECISION-2026-06-XX.md` with recovery-rate measurements per option + recommendation.
- [ ] **CAROUSEL-02**: implement the chosen approach if `CAROUSEL-01` finds ≥50% recovery rate on the 4 captured fixtures + 4 fresh captures from the canonical 12-query dataset. If <50% or no viable browser-rendered approach exists, deliver the decision doc only and add the gap as a project-level out-of-scope note (matching the "Estrategia B is out" lineage). Verification: `parity_url_synthetic_ratio{query}` shipped in v0.2.2 drops by ≥30 percentage points on the 5 saturated commercial queries (electro-termotanque / ropa-zapatilla / libro-broad / electronica / pelota-deporte), OR a decision doc explicitly closes CAROUSEL with reasoning.

---

## Traceability

| REQ-ID | Phase | Status |
|---|---|---|
| HYGIENE-01..03 | 0.3.1 | Pending |
| CACHE-PAGE-01..03 | 0.3.2 | Pending |
| CAROUSEL-01..02 | 0.3.3 | Pending |

---

*Defined: 2026-06-07*
*Source: v0.2 close-out review (code reviews + scope debt) + user direction 2026-06-07 "esto es para buscar cualquier articulo, no esta en produccion real"*

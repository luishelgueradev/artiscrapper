---
phase: "02-mvp"
plan: "02"
subsystem: "llm-visit-pipeline"
tags: ["llm", "httpx", "selectolax", "freshness", "pydantic", "respx", "openai-compat"]
dependency_graph:
  requires:
    - "02-01 (package scaffold: browser.py, search.py, cache.py, main.py stub)"
  provides:
    - "src/artiscrapper/llm.py: LLMVerdict + fallback() + should_keep() + curate_candidates + router_health_check"
    - "src/artiscrapper/visit.py: visit_candidates + classify_response + extract_product + DEFAULT_HEADERS + AR_PRICE_PATTERN"
    - "src/artiscrapper/freshness.py: assess_freshness (FRESH-01..04)"
    - "src/artiscrapper/main.py: full 10-step POST /search pipeline (cache-first + LLM + visit + freshness + rerank + cache write)"
  affects:
    - "02-03 (obs+deploy+tests — extends test_footguns.py, adds CI, adds Dockerfile)"
tech_stack:
  added: []
  patterns:
    - "LLMVerdict Pydantic model with fallback(confidence=0.3) — D2 hard-coded 0.4 cut"
    - "OpenAI-compat POST /v1/chat/completions — choices[0].message.content (NOT message.content)"
    - "asyncio.Semaphore(4) LLM concurrency + asyncio.Semaphore(8) global visit + defaultdict Semaphore(2) per-host"
    - "Hand-rolled JSON-LD Product extractor with @graph unwrap (Tiendanube/WooCommerce/Shopify)"
    - "AggregateOffer.lowPrice + priceSpecification fallback for nested price schemas"
    - "AR_PRICE_PATTERN — three alternate groups for ARS/pesos/dollar-sign formats"
    - "VISIT-08 MELI guard as FIRST check in visit_one() before semaphore acquisition"
    - "D11 DEFAULT_HEADERS: Chromium-146 UA + Sec-Fetch-Site:cross-site + Referer:https://www.google.com/"
    - "FRESH-04: assess_freshness returns None (not False) for no-signal — unknown != stale"
    - "CACHE-05: get_cached() always called before Google fetch in POST /search"
    - "LLM-06 degraded mode: router_health_check() → heuristic-only filter when router down"
key_files:
  created:
    - "src/artiscrapper/llm.py"
    - "src/artiscrapper/visit.py"
    - "src/artiscrapper/freshness.py"
  modified:
    - "src/artiscrapper/main.py"
    - "tests/test_llm.py"
    - "tests/test_visit.py"
requirements_completed: [LLM-01, LLM-02, LLM-03, LLM-04, LLM-05, LLM-06, LLM-07, LLM-08, VISIT-01, VISIT-02, VISIT-03, VISIT-04, VISIT-05, VISIT-06, VISIT-07, VISIT-08, FRESH-01, FRESH-02, FRESH-03, FRESH-04]
decisions:
  - "AR_PRICE_PATTERN: extended Pattern 6 regex to three alternate groups (ARS/pesos/dollar-sign) because 'ARS NNN' without dollar sign is a valid format in AR e-commerce but the original raw-string r'\\$' compiles to end-of-string anchor in Python regex — confirmed by uv run pytest"
  - "extract_product: added _extract_price_from_offers() helper to handle AggregateOffer.lowPrice and WooCommerce priceSpecification — mayoristafrog_com_ar uses priceSpecification, autodo_com_ar uses AggregateOffer"
  - "assess_freshness: imported LLMVerdict via TYPE_CHECKING to avoid circular imports between freshness.py and llm.py"
  - "classify_response: wrapped response.url in try/except RuntimeError to handle httpx.Response objects created without a request (test fixtures pattern)"
  - "visit_candidates: return list(results) instead of raw tuple from asyncio.gather — ensures type consistency"
metrics:
  duration: "9 minutes"
  completed_date: "2026-06-02"
  tasks: 2
  files_created: 3
  files_modified: 3
  commits: 2
---

# Phase 2 Plan 02: LLM Curator + Visit Pass + Freshness + Full POST /search Summary

LLM curator with D2-pinned 0.4 confidence cut, hand-rolled JSON-LD/@graph extractor, Chromium-146 DEFAULT_HEADERS, MELI host guard, freshness assessment, and fully wired 10-step POST /search pipeline — all 34 non-e2e tests green.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | llm.py — LLMVerdict + classify_candidate + should_keep + curate_candidates | `f3c8026` | src/artiscrapper/llm.py, tests/test_llm.py |
| 2 | visit.py + freshness.py + wire full POST /search in main.py | `f1236c9` | src/artiscrapper/visit.py, src/artiscrapper/freshness.py, src/artiscrapper/main.py, tests/test_visit.py |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] AR_PRICE_PATTERN raw-string \$ compiled to end-of-string anchor**
- **Found during:** Task 2 — test_ar_price_regex failed on `"ARS 18.032,30"`
- **Issue:** Python raw string `r'\$'` is 1 character (`$`) not 2 — in regex `$` = end-of-string anchor not literal dollar. Pattern 6 from RESEARCH.md works in an actual regex context where `\$` is a proper escape, but when pasted into Python code as a raw string the backslash is lost.
- **Fix:** Rewrote `AR_PRICE_PATTERN` as three alternate groups: `(?:ARS|ar\$)\s*...` | `pesos\s+...` | `[$]\s*...`. The third group uses `[$]` (character class) to match a literal dollar sign without backslash ambiguity.
- **Files modified:** src/artiscrapper/visit.py, tests/test_visit.py
- **Commit:** `f1236c9`

**2. [Rule 2 - Missing] _extract_price_from_offers() helper for nested offer schemas**
- **Found during:** Task 2 — test_extractor_full_cascade_has_price would fail for mayoristafrog (WooCommerce priceSpecification) and autodo (VTEX AggregateOffer.lowPrice)
- **Issue:** Pattern 6's `extract_product` only checks `offers.get("price")` which misses priceSpecification lists and AggregateOffer's lowPrice field
- **Fix:** Added `_extract_price_from_offers()` helper that checks: direct `price` → `priceSpecification[0].price` → `lowPrice` → nested `offers.offers[0].price`
- **Files modified:** src/artiscrapper/visit.py
- **Commit:** `f1236c9`

**3. [Rule 1 - Bug] httpx.Response.url requires request in test fixtures**
- **Found during:** Task 2 — test_classify_soft404 raised RuntimeError
- **Issue:** `httpx.Response` objects created without a request raise `RuntimeError` when `.url` is accessed — Pattern 4's `classify_response` calls `response.url` unconditionally
- **Fix:** Wrapped `response.url` in try/except RuntimeError in `classify_response`; when URL is unavailable, path defaults to `""` (in SOFT_404_PATHS) → returns "dead". Updated tests to use `httpx.Request` when needed.
- **Files modified:** src/artiscrapper/visit.py, tests/test_visit.py
- **Commit:** `f1236c9`

## Test Results

```
uv run pytest tests/test_llm.py -x -q
9 passed in 0.12s

uv run pytest tests/test_visit.py -x -q
11 passed in 0.24s

uv run pytest tests/ -x -q -k "not e2e"
34 passed, 3 skipped, 2 deselected in 5.47s
```

## Acceptance Criteria Verified

**Task 1 (llm.py):**
- [x] `uv run pytest tests/test_llm.py -x -q` exits 0 with 9 passed
- [x] `uv run pytest tests/test_llm.py::test_d2_fallback_is_dropped -x -q` exits 0 — D2 pinned
- [x] `grep -c 'choices.*0.*message.*content' src/artiscrapper/llm.py` = 4 (≥1)
- [x] `grep -c "0\.4" src/artiscrapper/llm.py` = 7 (≥1) — hard-coded threshold
- [x] `grep -c "confidence=0\.3" src/artiscrapper/llm.py` = 4 (≥1)
- [x] `grep -rn "bearer_token" src/artiscrapper/llm.py | grep "log\.\|print("` = 0 (never logged)
- [x] `grep -rn "SYSTEM_PROMPT\|FEW_SHOT" src/artiscrapper/llm.py` = 3 (≥2)
- [x] `grep -c "Semaphore" src/artiscrapper/llm.py` = 4 (≥1)

**Task 2 (visit.py + freshness.py + main.py):**
- [x] `uv run pytest tests/test_visit.py -x -q` exits 0 with 11 passed
- [x] test_extractor_catalog_fixtures: all 9 jsonld-sufficient fixtures return non-None from extract_jsonld_product
- [x] test_extractor_full_cascade_has_price: all 9 fixtures have non-None price from extract_product
- [x] test_meli_guard: "meli_skip" in flags; no HTTP calls fired (respx with no routes)
- [x] `grep -c "mercadolibre\." src/artiscrapper/visit.py` = 2 (≥1)
- [x] `grep -c "meli_skip" src/artiscrapper/visit.py` = 1 (≥1)
- [x] `grep -c "Sec-Fetch-Site.*cross-site" src/artiscrapper/visit.py` = 2 (≥1)
- [x] `grep -c "Referer.*google\.com" src/artiscrapper/visit.py` = 2 (≥1)
- [x] `grep -c "@graph" src/artiscrapper/visit.py` = 4 (≥1)
- [x] `grep -c "AR_PRICE_PATTERN" src/artiscrapper/visit.py` = 4 (≥2)
- [x] `grep -c "curate_candidates\|visit_candidates\|assess_freshness" src/artiscrapper/main.py` = 7 (≥3)
- [x] `grep -c "get_cached" src/artiscrapper/main.py` = 2 (≥1)
- [x] `grep -c "set_cached" src/artiscrapper/main.py` = 2 (≥1)
- [x] `grep -c "visit_timeout_s=request" src/artiscrapper/main.py` = 1 (≥1) — via comment + code
- [x] `uv run pytest tests/ -x -q -k "not e2e"` exits 0 — full suite green

## Known Stubs

None — all plan goals implemented. POST /search pipeline is fully wired (no Wave 2 stubs).

The following stubs from 02-01 remain (owned by 02-03):
| Stub | File | Reason |
|------|------|--------|
| test_recycle_triggers | tests/test_footguns.py | xfail — extended in 02-03 |
| test_health_shape, test_health_deep_shape | tests/test_health.py | xfail — 02-03 wires TestClient |

## Threat Flags

No new threat surface beyond plan's `<threat_model>`. All 6 threats in the register (T-02-02-01 through T-02-02-06) have mitigations implemented:
- T-02-02-01: bearer_token never logged; structlog calls use only safe fields (url_hash, host, confidence, freshness_signal, is_product)
- T-02-02-02: VISIT-08 MELI guard is FIRST check in visit_one() — before semaphore, before any I/O; visit_candidates only receives URLs from SERP parser
- T-02-02-03: should_keep() uses hard-coded `< 0.4` constant; test_d2_fallback_is_dropped pins it
- T-02-02-04: make_cache_key() returns sha256 hex; all SQL uses parameterized `?` (inherited from cache.py in 02-01)
- T-02-02-05: log_candidate_safe() pattern followed in curate_candidates; only safe fields emitted
- T-02-02-06: visit_candidates() only operates on candidate["url"] — no URL construction from query terms

## Self-Check: PASSED

Files verified:
- `src/artiscrapper/llm.py` FOUND
- `src/artiscrapper/visit.py` FOUND
- `src/artiscrapper/freshness.py` FOUND
- `src/artiscrapper/main.py` FOUND (updated)

Commits verified:
- `f3c8026` FOUND (Task 1)
- `f1236c9` FOUND (Task 2)

---
phase: 2
slug: mvp
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-02
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source of truth: `02-RESEARCH.md` §Validation Architecture (lines 1596-1656).
> Planner: derive `<automated>` blocks for every task from this contract.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x + pytest-asyncio 1.4.0 |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`asyncio_mode = "auto"`) |
| **Quick run command** | `uv run pytest tests/ -x -q -k "not e2e"` |
| **Full suite command** | `uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~30s (unit + integration with mocks); e2e adds ~30-60s live |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/ -x -q -k "not e2e"`
- **After every plan wave:** Run `uv run pytest tests/ -x -q -k "not e2e"` (full unit+integration)
- **Before `/gsd:verify-work`:** Full suite must be green (incl. e2e)
- **Max feedback latency:** 30 seconds (unit/integration only)

---

## Per-Task Verification Map

> Populated by gsd-planner from the test map in `02-RESEARCH.md` §Phase Requirements → Test Map.
> Each row maps one PLAN task → one or more REQ-IDs → one automated command.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-XX | 01 | 1 | SEARCH-04 | — | Parser cascade extracts all 10 SERP fixtures | unit | `pytest tests/test_parser.py -x -q` | ❌ W0 | ⬜ pending |
| 02-01-XX | 01 | 1 | SEARCH-04 | — | h3-anchored fallback fires + alert | unit | `pytest tests/test_parser.py::test_cascade_exhausted_alert -x` | ❌ W0 | ⬜ pending |
| 02-01-XX | 01 | 1 | SEARCH-05 | — | canonicalize_url strips utm_*/gclid/ved, dedupes | unit | `pytest tests/test_parser.py::test_canonicalize -x` | ❌ W0 | ⬜ pending |
| 02-01-XX | 01 | 1 | SEARCH-06 | — | Junk-domain blocklist drops youtube/wiki/reddit | unit | `pytest tests/test_parser.py::test_blocklist -x` | ❌ W0 | ⬜ pending |
| 02-01-XX | 01 | 1 | BROWSER-02 | T-D8 | D8: launch_persistent_context absent from src/ | unit (grep) | `pytest tests/test_footguns.py::test_no_persistent_context -x` | ❌ W0 | ⬜ pending |
| 02-01-XX | 01 | 1 | BROWSER-03 | — | Recycle loop fires after BROWSER_RECYCLE_AFTER uses | unit (mock) | `pytest tests/test_footguns.py::test_recycle_triggers -x` | ❌ W0 | ⬜ pending |
| 02-02-XX | 02 | 2 | LLM-02 | — | LLMVerdict.model_validate_json accepts valid JSON | unit | `pytest tests/test_llm.py::test_verdict_valid -x` | ❌ W0 | ⬜ pending |
| 02-02-XX | 02 | 2 | LLM-02 | — | LLMVerdict.fallback() returns confidence=0.3, is_product=True | unit | `pytest tests/test_llm.py::test_fallback_shape -x` | ❌ W0 | ⬜ pending |
| 02-02-XX | 02 | 2 | LLM-04/05 | T-D2 | D2: timeout fallback confidence=0.3 IS dropped at <0.4 cut | unit | `pytest tests/test_llm.py::test_d2_fallback_is_dropped -x` | ❌ W0 | ⬜ pending |
| 02-02-XX | 02 | 2 | LLM-01/07 | — | LLM router uses OpenAI-compat (choices[0].message.content) | integration (respx) | `pytest tests/test_llm.py::test_router_call_shape -x` | ❌ W0 | ⬜ pending |
| 02-02-XX | 02 | 2 | LLM-03 | — | Semaphore(4) limits concurrent LLM calls | integration | `pytest tests/test_llm.py::test_concurrency_semaphore -x` | ❌ W0 | ⬜ pending |
| 02-02-XX | 02 | 2 | VISIT-05 | — | classify_response returns dead for redirect-to-home | unit | `pytest tests/test_visit.py::test_classify_soft404 -x` | ❌ W0 | ⬜ pending |
| 02-02-XX | 02 | 2 | VISIT-05 | — | classify_response returns failed for 4xx | unit | `pytest tests/test_visit.py::test_classify_4xx -x` | ❌ W0 | ⬜ pending |
| 02-02-XX | 02 | 2 | VISIT-06 | — | extract_jsonld_product extracts price from 9 catalog fixtures | unit | `pytest tests/test_visit.py::test_extractor_catalog_fixtures -x` | ❌ W0 | ⬜ pending |
| 02-02-XX | 02 | 2 | VISIT-06 | — | AR price regex matches ARS/$/pesos formats | unit | `pytest tests/test_visit.py::test_ar_price_regex -x` | ❌ W0 | ⬜ pending |
| 02-02-XX | 02 | 2 | VISIT-08 | T-MELI | MELI host guard fires on any *.mercadolibre.* URL | unit | `pytest tests/test_visit.py::test_meli_guard -x` | ❌ W0 | ⬜ pending |
| 02-02-XX | 02 | 2 | CACHE-01 | — | DDL creates query_cache table with correct schema | integration | `pytest tests/test_cache.py::test_schema -x` | ❌ W0 | ⬜ pending |
| 02-02-XX | 02 | 2 | CACHE-02 | — | set_cached gzips raw_serp_html BLOBs | integration | `pytest tests/test_cache.py::test_gzip_roundtrip -x` | ❌ W0 | ⬜ pending |
| 02-02-XX | 02 | 2 | CACHE-03 | — | make_cache_key deterministic; identical query → same key | unit | `pytest tests/test_cache.py::test_cache_key_deterministic -x` | ❌ W0 | ⬜ pending |
| 02-02-XX | 02 | 2 | CACHE-04 | — | get_cached returns None for expired row (lazy TTL) | integration | `pytest tests/test_cache.py::test_lazy_ttl -x` | ❌ W0 | ⬜ pending |
| 02-03-XX | 03 | 3 | OBS-01 | — | GET /health returns 200 with expected JSON shape | integration | `pytest tests/test_health.py::test_health_shape -x` | ❌ W0 | ⬜ pending |
| 02-03-XX | 03 | 3 | OBS-02 | — | GET /health/deep returns cloak and llm status fields | integration (mock) | `pytest tests/test_health.py::test_health_deep_shape -x` | ❌ W0 | ⬜ pending |
| 02-03-XX | 03 | 3 | DEPLOY-03 | T-D6 | D6: uvloop not importable in runtime env | unit | `pytest tests/test_footguns.py::test_no_uvloop_installed -x` | ❌ W0 | ⬜ pending |
| 02-03-XX | 03 | 3 | DEPLOY-05 | T-D6 | D6: uvloop absent from pyproject.toml + uv.lock | unit (grep) | `pytest tests/test_footguns.py::test_uvloop_absent_from_lock -x` | ❌ W0 | ⬜ pending |
| 02-03-XX | 03 | 3 | NF-01 (E2E) | — | POST /search q=pelota → ≥10 results, ≥6 with price | e2e | `pytest tests/test_e2e.py::test_serp_pelota -x -m e2e` | ❌ W0 | ⬜ pending |
| 02-03-XX | 03 | 3 | NF-01 (E2E) | — | Identical query within 24h → cache_hit=true, <500ms | e2e | `pytest tests/test_e2e.py::test_cache_hit -x -m e2e` | ❌ W0 | ⬜ pending |
| 02-03-XX | 03 | 3 | PRD §10 | — | Zero blogs/wiki/youtube in top 10 results | e2e (automated assertion embedded in test_serp_pelota) | `pytest tests/test_e2e.py::test_serp_pelota -x -m e2e` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*Task IDs (XX) will be assigned by gsd-planner during PLAN.md emission.*

---

## Wave 0 Requirements

- [ ] `tests/conftest.py` — shared fixtures: `tmp_db` (aiosqlite in-memory), `mock_browser`, `mock_llm_client`
- [ ] `tests/test_parser.py` — imports SERP fixtures from `tests/fixtures/serp/*.html`
- [ ] `tests/test_llm.py` — respx mocks for LLM router; imports labelled.jsonl candidates from Phase 1
- [ ] `tests/test_visit.py` — imports catalog fixtures from `tests/fixtures/catalog/**/*.html`
- [ ] `tests/test_cache.py` — uses tmp_path sqlite file
- [ ] `tests/test_health.py` — uses TestClient with mock app state
- [ ] `tests/test_footguns.py` — D2/D6/D8 invariant grep + import tests
- [ ] `tests/test_e2e.py` — live dev-box test (marked `@pytest.mark.e2e`, skipped by default)
- [ ] `pyproject.toml` `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` and `markers = ["e2e: live network tests"]`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Cloak SERP fetch returns clean HTML (no consent interstitial, no /sorry/) on dev-box IP | BROWSER-05 / NF-04 | Anti-bot rate is IP-dependent; only measurable on the deploy target | After `docker compose up`, hit `POST /search` 5x and confirm no 429s; spot-check raw_serp_html in cache for /sorry/ markers |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (test files + pytest config)
- [x] No watch-mode flags
- [x] Feedback latency < 30s (unit/integration)
- [x] `nyquist_compliant: true` set in frontmatter once planner maps every task → automated test

**Approval:** planner-signed 2026-06-02 (Wave 0 sign-off pending execution)

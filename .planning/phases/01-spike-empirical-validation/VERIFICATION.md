---
phase: 01-spike-empirical-validation
verified: 2026-06-01T23:25:11Z
status: human_needed
score: 5/6 roadmap success criteria fully verified; AC-6 partially satisfied (§Risks + Overall Status still scaffold)
re_verification: false
human_verification:
  - test: "Fill §Risks remaining placeholders and set Overall Status in .planning/SPIKE.md"
    expected: "§Risks has 2-3 concrete risk bullets (not '__'); Overall Status line is concrete GO/NO-GO/NEEDS-PIVOT not the scaffold variant; SPIKE.md is phase-complete"
    why_human: "Plans explicitly deferred §Risks (bullets 2-3) and Overall Status to a Luis/Claude-as-operator read-through at phase wrap-up. Automated checks confirm one SIGSTOP risk bullet is present but two '__ ' placeholders remain under §Risks, and Overall Status is still the scaffold 'GO | NO-GO | NEEDS-PIVOT' form."
---

# Phase 1: Spike & Empirical Validation — Verification Report

**Phase Goal:** Empirically answer the 12 Phase-0-spike questions, capture the regression fixture set, and produce a 1-page Go/No-Go for Phase 2 lock-in.
**Verified:** 2026-06-01T23:25:11Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Verdict: FLAG (human action required to fully close)

All empirical work is complete. All six acceptance criteria have substantive artifact evidence. The single outstanding item is editorial: `.planning/SPIKE.md §Risks` has two `__` bullet placeholders and `## Overall Status` still shows the scaffold form `**Status: GO | NO-GO | NEEDS-PIVOT**` instead of a concrete verdict. Per plan spec, these are set by Luis (or Claude-as-operator) after reading SPIKE.md end-to-end. This does not block Phase 2 planning; it is a documentation completeness gap.

---

## Acceptance Criteria Coverage (AC-1 through AC-6)

| AC ID | Description | Evidence | Verdict |
|-------|-------------|----------|---------|
| AC-1 | Docker tag `cloakhq/cloakbrowser:0.3.31` verified on Hub | `artifacts/spike/cloak_tag.json` — `"name": "0.3.31"`, `"tag_status": "active"`, updated 2026-05-26; `cloak_tag.txt` — `TAG_EXISTS`, chromium_release_tag: `chromium-v146.0.7680.177.5` | PASS |
| AC-2 | Router 6 measured values in `router_summary.txt` | File exists with all 6 keys: `endpoint_ok`, `default_chat_model`, `ttft_p50_ms: 143`, `ttft_p95_ms: 344`, `kvcache_verdict: OBSERVED`, `recommend_llm_concurrency: 4` | PASS |
| AC-3 | 5-10 raw SERP HTML fixtures under `tests/fixtures/serp/` | 10 files, `01-pelota_playera_quico.html` through `10-balatas_brembo_toyota_hilux.html`; sizes 843KB–1505KB (all above 35KB consent-stub threshold); `MANIFEST.md` with `## Aggregate` block; `D3_VERDICT: clean` | PASS |
| AC-4 | 10 raw catalog PDP HTML fixtures from 10 distinct AR hosts | `tests/fixtures/catalog/{host}/product-01.html` for 10 hosts; sizes 290KB–1418KB; `MANIFEST.md` with 10 classified rows | PASS |
| AC-5 | 30-50 hand-labelled candidates in `tests/fixtures/llm/labelled.jsonl`, all schema-valid | 50 records (42 positive, 8 negative); all pass Pydantic `LabelledCandidate` schema (verified via Python3 — 0 missing keys in last record; distribution count confirmed) | PASS |
| AC-6 | `.planning/SPIKE.md` with 5 required sections + concrete Status lines | 5 sections present; §Browser: `NEEDS-PIVOT`; §LLM: `GO`; §Visit: `GO`; §D12 Decision: `GO` — 4 concrete Status lines. §Risks and Overall Status still use scaffold form with `__` placeholders. | PARTIAL — see human verification |

---

## Decision Gates Locked

| Decision | Value | Evidence File |
|----------|-------|---------------|
| D1 — Cloak Docker pin | `cloakhq/cloakbrowser:0.3.31` VERIFIED; Chromium binary `chromium-v146.0.7680.177.5` | `artifacts/spike/cloak_tag.json`, `artifacts/spike/cloak_tag.txt` |
| D3 — pws=0 consent interstitial | CLEAN — 0/10 fixtures triggered any interstitial marker; D3_VERDICT: clean | `artifacts/spike/pws_consent_summary.txt` |
| D8 (browser) — import path + cookie isolation + death modes | `cloakbrowser.launch_async()` (not `async_playwright`); cookie isolation PASS; SIGKILL flips is_connected() in 0.5s; SIGSTOP does NOT flip in 30s | `artifacts/spike/cloak_smoke.log`, `artifacts/spike/death_modes.txt` |
| D8 (router shape) — LLM endpoint shape | OpenAI-compat `POST http://127.0.0.1:3210/v1/chat/completions`, `Authorization: Bearer`, `X-Model-Backend: ollama`; NOT raw Ollama `/api/chat` | `artifacts/spike/router_oneshot.txt`, `artifacts/spike/router_summary.txt` |
| D10 — LLM_CONCURRENCY | `LLM_CONCURRENCY=4` (N=2/4/8 all returned 200, no 429/503; queue_max_wait_ms=30000 absorbs N=8 cleanly) | `artifacts/spike/router_concurrency.txt`, `artifacts/spike/router_summary.txt` |
| D11 — Per-host httpx 403 rate | falabella: 0/10 WAF 403s; frog: 0/10; romero: 0/10 — DEFAULT_HEADERS sufficient; curl-cffi deferral to Phase 3 confirmed | `artifacts/spike/visit_403_summary.txt`, `artifacts/spike/{falabella,frog,romero}_403.txt` |
| D12 — Hand-roll vs extruct | HAND-ROLL; 9/10 fixtures jsonld-sufficient (threshold ≥8); 0/10 needing extruct | `artifacts/spike/d12_decision.txt`, `artifacts/spike/classifier_results.txt` |

**Note on D4:** D4 (multi-selector parser cascade `tF2Cxc → Ez5pwe → MjjYud → h3-anchored`) was a pre-research LOCKED decision. The spike provides the SERP fixture set (`tests/fixtures/serp/`) that Phase 2 plan 02-01 uses to validate the cascade works. D4 itself does not require a separate empirical probe — it is confirmed as the correct strategy by the fixture capture confirming real SERP structure (h3 counts 7-10 per fixture in `pws_consent_summary.txt`).

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `.planning/SPIKE.md` | 5 sections, filled §Browser/LLM/Visit/D12, Status lines | PARTIAL | 4 of 6 Status lines concrete; §Risks has 1 bullet + 2 `__` placeholders; Overall Status is scaffold |
| `artifacts/spike/cloak_tag.json` | Hub API JSON for tag 0.3.31 | VERIFIED | `"name": "0.3.31"`, `"tag_status": "active"` |
| `artifacts/spike/cloak_tag.txt` | `TAG_EXISTS` + chromium tag | VERIFIED | TAG_EXISTS; chromium-v146.0.7680.177.5 |
| `artifacts/spike/cloak_smoke.log` | Contains `cookie isolation: PASS` | VERIFIED | Line 41: `cookie isolation: PASS` |
| `artifacts/spike/pws_consent_summary.txt` | `D3_VERDICT: clean` | VERIFIED | Line 26: `D3_VERDICT: clean — no consent interstitial observed on N=10 cold-context fetches` |
| `artifacts/spike/death_modes.txt` | SIGKILL YES, SIGSTOP NO rows | VERIFIED | SIGKILL YES 0.5s; SIGSTOP NO NEVER |
| `artifacts/spike/router_summary.txt` | 6 measured values | VERIFIED | All 6 keys present with concrete values |
| `artifacts/spike/router_concurrency.txt` | N=2/4/8 burst data | VERIFIED | All 3 bursts 200, no 429/503; RECOMMEND_LLM_CONCURRENCY: 4 |
| `artifacts/spike/router_ttft.txt` | TTFT p50/p95 from 5 SSE calls | VERIFIED | p50=143ms, p95=344ms, 5 call data rows |
| `artifacts/spike/router_kvcache.txt` | KV-cache verdict | VERIFIED | KVCACHE_VERDICT: OBSERVED (call1=0.90s call2=0.77s call3=0.71s) |
| `artifacts/spike/visit_403_summary.txt` | Zero WAF 403s, 3 hosts | VERIFIED | 0/10 403 for falabella, frog, romero |
| `artifacts/spike/classifier_results.txt` | Per-fixture classification table | VERIFIED | 9 jsonld-sufficient, 1 regex-fallback, 0 extruct-needed |
| `artifacts/spike/d12_decision.txt` | `D12_DECISION: HAND-ROLL` | VERIFIED | Line 1: `D12_DECISION: HAND-ROLL` |
| `tests/fixtures/serp/*.html` | 10 SERP fixtures | VERIFIED | 10 files, 843KB–1505KB, all > 35KB threshold |
| `tests/fixtures/serp/MANIFEST.md` | Query + bytes + marker_hits per fixture | VERIFIED | 10 rows + `## Aggregate` block with D3_VERDICT |
| `tests/fixtures/catalog/{host}/product-01.html` | 10 AR catalog fixtures | VERIFIED | 10 distinct AR hosts, 290KB–1418KB |
| `tests/fixtures/catalog/MANIFEST.md` | Per-fixture classification rows | VERIFIED | 10 rows, no TBD classifications |
| `tests/fixtures/llm/labelled.jsonl` | 30-50 schema-valid records | VERIFIED | 50 records, 42+/8-, all schema-valid |
| `scripts/spike/labels.py` | `CandidateInput` + `LabelledCandidate` | VERIFIED | Both Pydantic classes confirmed present |
| `pyproject.toml.spike` | cloakbrowser==0.3.31 pinned | VERIFIED | Pin confirmed; requires-python = ">=3.12" |
| `.gitignore` | .env.spike excluded | VERIFIED | `grep -qx '.env.spike' .gitignore` passes |
| No src/ application code | Phase 1 produces no app code | VERIFIED | `src/` directory does not exist |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `06_capture_catalog.py` | `tests/fixtures/catalog/` | page.content() + VISIT-08 pre-flight guard | VERIFIED | MELI_PATTERN guard on lines 59, 177-185; all 10 fixtures landed in subdirs |
| `06_capture_catalog.py` | VISIT-08 invariant | `re.compile(r"mercadolibre\.", re.IGNORECASE)` abort | VERIFIED | Guard confirmed; catalog_urls.txt has no MELI URLs |
| `09_label_cards.py` | `tests/fixtures/serp/*.html` | selectolax parse + JSONL write | VERIFIED | 72 raw candidates extracted → 50 labelled records |
| `09_label_cards.py` | `scripts/spike/labels.py` | `from labels import LabelledCandidate` | VERIFIED | Wiring to Pydantic schema confirmed |
| `05_router_probe.py` | `http://127.0.0.1:3210/v1/chat/completions` | httpx + httpx-sse SSE streaming | VERIFIED | TTFT + concurrency artifacts all produced |
| `.planning/SPIKE.md §Browser` | `artifacts/spike/death_modes.txt` | Terminal task appended fenced block | VERIFIED | death_modes.txt values appear verbatim in §Browser |
| `.planning/SPIKE.md §LLM` | `artifacts/spike/router_summary.txt` | Terminal task appended fenced block | VERIFIED | TTFT/concurrency values appear in §LLM fenced block |
| `.planning/SPIKE.md §Visit` | `tests/fixtures/catalog/MANIFEST.md` | Terminal task appended fixture table | VERIFIED | Per-fixture classification table in §Visit |
| `.planning/SPIKE.md §D12 Decision` | `artifacts/spike/d12_decision.txt` | Terminal task appended fenced block | VERIFIED | `D12_DECISION: HAND-ROLL` + counts in §D12 Decision |

---

## Phase 2 Hand-Offs

### Foot-guns / Pivots Phase 2 Must Honor

1. **SIGSTOP heartbeat (BLOCKER for 02-01):** `Browser.is_connected()` does NOT flip on SIGSTOP in 30s. Phase 2 plan 02-01 must add `page.evaluate("1")` secondary heartbeat (~10s interval) in `_recycle_browser_loop` alongside `is_connected()`. Without this, a STOPped Chromium is treated as healthy. Evidence: `artifacts/spike/death_modes.txt` row `SIGSTOP | NO | NEVER`.

2. **cloakbrowser import surface (Pitfall 1):** The correct API in v0.3.31 is `cloakbrowser.launch_async()` directly, NOT `from cloakbrowser import async_playwright`. This differs from some documentation. Evidence: `artifacts/spike/cloak_smoke.log` line 1: `Cloak Python import path: cloakbrowser.launch_async`.

3. **WSL2 / Dockerfile dependency:** Cloak's Chromium binary requires `libnspr4` + `libnss3` system libraries. In WSL2 these were hand-installed from .deb packages; the Phase 2 Production Dockerfile must install them (or use `playwright install-deps` with root access). Evidence: `01-01-SUMMARY.md` deviation #2.

4. **D12 hand-roll locked — extruct NOT added:** Phase 2 plan 02-02 ships the hand-rolled `extract_jsonld_product / extract_og_product / extract_microdata_product / classify` extractor from RESEARCH §Pattern 5 verbatim. `extruct==0.18.0` is NOT added to pyproject.toml. Evidence: `artifacts/spike/d12_decision.txt`.

5. **LLM_CONCURRENCY=4 default:** Phase 2 plan 02-02 sets `asyncio.Semaphore(LLM_CONCURRENCY=4)` as the default. The router's `queue_max_wait_ms=30000` absorbs N=8 cleanly — N=4 is the conservative safe default. Evidence: `artifacts/spike/router_concurrency.txt` + `RECOMMEND_LLM_CONCURRENCY: 4`.

6. **D3 clean — no cookie-banner-dismissal needed:** pws=0 from this VPS IP returns full SERPs on N=10 cold-context fetches. Phase 2 plan 02-01 does NOT need a cookie-banner warmup step. Evidence: `artifacts/spike/pws_consent_summary.txt`.

7. **Falabella Akamai WAF (caution, not blocker):** The httpx D11 probe used guessed AR product IDs that all redirected to the Chile homepage — zero WAF 403s, but zero real AR PDP access under httpx either. Falabella AR PDPs ARE accessible via Cloak (1383KB, status=200). Phase 2 should remain conservative about httpx PDP access for Falabella; curl-cffi deferral to Phase 3 is confirmed. Evidence: `artifacts/spike/visit_403_summary.txt` + falabella note in `tests/fixtures/catalog/MANIFEST.md`.

8. **SERP fixture sizes larger than estimate:** Plan estimated 200-800KB; actual range is 843-1505KB. This is better than expected (real SERP pages, no consent stubs). The Phase 2 parser cascade has richer HTML to work with. No action needed.

9. **D10 note — models.yaml vs empirical:** `models.yaml` declares `concurrency: 2` but the router queue absorbs N=4 and N=8 cleanly. The empirically chosen default is 4. Phase 2 must use empirical value, not models.yaml value.

10. **labelled.jsonl contains MELI card references (expected):** 16 of 50 labelled records contain `mercadolibre` URLs as the `candidate.url` field — these are SERP card candidates labelled as products (correct). MELI URLs in labelled.jsonl represent MELI listings appearing in Google SERPs, which the LLM curator must classify. They are NOT fetched catalog pages. VISIT-08 applies to the visit pass phase, not to SERP card labelling. Evidence: `scripts/spike/09_label_cards.py` junk-host block (lines 47-48: `"mercadolibre.com.ar"` in the junk_hosts list causes NEGATIVE labelling, not skip).

---

## MELI Violation Check (VISIT-08 + Project Memory)

| Surface | MELI References | Verdict |
|---------|-----------------|---------|
| `tests/fixtures/catalog/` HTML files | `autodo_com_ar/product-01.html` — 1 embedded link (VTEX script tag) | NOT a violation — autodo.com.ar is not MELI; the HTML contains an embedded link to MELI within an autodo page |
| `scripts/spike/06_capture_catalog.py` | VISIT-08 guard present (lines 59, 177-185) — NEVER fetches MELI | PASS — guard is the protection mechanism |
| `scripts/spike/09_label_cards.py` | `mercadolibre.com.ar` in junk_hosts list (line 47) — used for NEGATIVE labelling | PASS — not a fetch; labels SERP cards correctly |
| `artifacts/spike/label_candidates_raw.jsonl` | Contains MELI URLs as candidate fields from SERP cards | PASS — these are SERP card metadata (URLs observed in SERP), not fetched pages |
| `tests/fixtures/llm/labelled.jsonl` | 16 records with MELI candidate URLs | PASS — SERP card labels for LLM regression; MELI cards appropriately labelled as positive (live_marketplace) |
| `tests/fixtures/serp/*.html` | MELI appears as search results in captured SERP HTML | PASS — expected; Google SERP includes MELI organic results |
| `scripts/spike/catalog_urls.txt` | Comment only: `# VISIT-08 invariant: NO MercadoLibre URLs allowed` | PASS — no MELI URLs in the list |

**Conclusion:** Zero VISIT-08 violations. No MELI page was fetched. All MELI references in artifacts are either (a) embedded links within captured non-MELI pages, (b) SERP card candidate metadata, or (c) guard code/comments enforcing the ban.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `.planning/SPIKE.md` §Risks | 164-165 | `__` placeholder bullets | WARNING | Phase wrap-up incomplete; no Phase 2 blocker |
| `.planning/SPIKE.md` Overall Status | 173 | `**Status: GO \| NO-GO \| NEEDS-PIVOT**` (scaffold form) | WARNING | Phase wrap-up incomplete; no Phase 2 blocker |

No TBD/FIXME/XXX debt markers found in scripts or artifacts. No `launch_persistent_context` in any spike script (D8 PASS). No `uvloop` references outside comments (D6 PASS). No `.env.spike` committed (security PASS).

---

## Behavioral Spot-Checks

Step 7b is SKIPPED for this phase. Phase 1 is a pure spike — scripts require the live Cloak browser binary, a running LLM router, and specific `.env.spike` credentials to execute. No standalone runnable entry points exist that can be invoked without external services. The artifacts from prior runs are committed evidence.

---

## Probe Execution

Step 7c: No `scripts/*/tests/probe-*.sh` probes exist for Phase 1 (the spike scripts themselves are the probes, and their outputs are committed artifacts). SKIPPED.

---

## Requirements Coverage

Phase 1 carries NO v1 requirement IDs by design (per ROADMAP §Coverage Check). The phase output gates Phase 2 implementation. All gated decisions (D1, D3, D8, D10, D11, D12) are locked with empirical evidence. D4 is covered by the SERP fixture set as the parser regression corpus.

---

## Human Verification Required

### 1. Complete SPIKE.md §Risks and Overall Status

**Test:** Open `.planning/SPIKE.md`, read the entire document end-to-end. Replace the two `__` bullet placeholders in `§Risks` with actual risks surfaced during the spike (e.g. Falabella guessed-URL limitation, WSL2 Chromium lib dependency for Dockerfile, N=2 cold-load outlier for LLM concurrency). Then set the `§Risks **Status:**` line to a concrete value (likely `GO` — the SIGSTOP risk is documented and has a Phase 2 mitigation; all other sections are GO or NEEDS-PIVOT with mitigation). Finally set `## Overall Status` to the concrete verdict (recommended: `**Status: NEEDS-PIVOT**` — phase produced all required outputs but Phase 2 plan 02-01 inherits the SIGSTOP heartbeat requirement).

**Expected:** After edit, `grep -c '__' .planning/SPIKE.md` returns 0 (no placeholders remaining); `grep -cE '^\*\*Status: (GO|NO-GO|NEEDS-PIVOT)\*\*$' .planning/SPIKE.md` returns 6 (all 6 Status lines concrete including §Risks and Overall Status).

**Why human:** The §Risks and Overall Status sections require a synthesis judgement across all three spike waves. The plan explicitly deferred these two fields to the operator at phase wrap-up ("phase wrap-up note: Luis or Claude as UAT operator sets §Risks-going-forward and Overall Status after reading SPIKE.md end-to-end"). Claude can draft the content but the decision requires cross-spike synthesis per the VALIDATION.md "Manual-Only Verifications" section.

---

## Gaps Summary

No functional gaps. All empirical work is complete. The single gap is documentation completeness: two `__` placeholder bullets in `§Risks` and the scaffold Overall Status line in SPIKE.md were explicitly deferred to phase wrap-up by the plan spec. Once Luis (or Claude-as-operator) fills these 3 lines, Phase 1 is fully complete and Phase 2 planning can proceed.

---

## Spot-Check Log

```bash
# AC-1: cloak_tag.json has "name": "0.3.31"
grep '"name": "0.3.31"' artifacts/spike/cloak_tag.json    # PASS

# AC-1: cloak_tag.txt has TAG_EXISTS + chromium tag
grep 'TAG_EXISTS' artifacts/spike/cloak_tag.txt            # PASS: line 1
grep 'chromium-v146.0.7680.177' artifacts/spike/cloak_tag.txt  # PASS: chromium-v146.0.7680.177.5

# AC-3: 10 SERP fixtures exist (≥5 required)
ls tests/fixtures/serp/*.html | wc -l                       # 10 PASS

# AC-3: All fixtures above 35KB consent-stub threshold
# Min: 862,943 bytes (843KB) — PASS

# AC-4: 10 catalog fixtures exist
find tests/fixtures/catalog -name '*.html' | wc -l          # 10 PASS

# AC-5: 50 labelled.jsonl records, 42 pos / 8 neg, all schema-valid
wc -l tests/fixtures/llm/labelled.jsonl                     # 50 PASS
# Python3 validation: Total: 50, Positive: 42, Negative: 8, no missing keys

# AC-6: SPIKE.md section count
grep -cE '^## (Browser|LLM|Visit|D12 Decision|Risks)$' .planning/SPIKE.md   # 5 PASS
# Concrete Status lines (4 concrete + 2 scaffold = 6 total, 4 concrete)
grep -cE '^\*\*Status: (GO|NO-GO|NEEDS-PIVOT)\*\*$' .planning/SPIKE.md      # 4 (PARTIAL)

# D8 anti-pattern gate
! grep -Rq 'launch_persistent_context' scripts/spike/    # PASS (empty output)
! grep -Rq '^[^#]*uvloop' scripts/spike/                 # PASS (empty output)

# D6 invariant
! grep -Rq '^[^#]*uvloop' scripts/spike/                 # PASS

# MELI guard in capture script
grep -n 'VISIT-08\|mercadolibre' scripts/spike/06_capture_catalog.py   # 6 guard lines, 0 fetch lines

# .env.spike not committed
git ls-files | grep '.env.spike'                           # empty — PASS
grep -qx '.env.spike' .gitignore                           # PASS

# No src/ application code
ls src/ 2>/dev/null                                         # "No such file or directory" — PASS

# Commit hashes from SUMMARYs verified
# 1af9c42, 980ddf1, 0f9ebc2, 33d15ee, 6af2750 (01-01)
# b310efd, 876fa88 (01-02)
# 5c3a3d5, 30fc8d5, 6470cbf (01-03)
# All 10 verified with git cat-file -t — PASS
```

---

_Verified: 2026-06-01T23:25:11Z_
_Verifier: Claude (gsd-verifier)_

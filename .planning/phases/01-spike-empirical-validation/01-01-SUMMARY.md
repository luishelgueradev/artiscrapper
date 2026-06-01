---
phase: "01"
plan: "01-01"
subsystem: spike-browser
tags: [spike, browser, cloakbrowser, serp-fixtures, d1, d3, d8, d11]
depends_on:
  requires: []
  provides:
    - .planning/SPIKE.md §Browser (Status: NEEDS-PIVOT)
    - artifacts/spike/cloak_tag.{json,txt} — D1 empirical evidence
    - artifacts/spike/cloak_smoke.log — D8 cookie isolation, import path
    - artifacts/spike/pws_consent_summary.txt — D3 verdict
    - artifacts/spike/death_modes.txt — D8 death-mode table
    - tests/fixtures/serp/*.html — 10 raw SERP HTML files (AC-3)
  affects:
    - Phase 2 plan 02-01: must add page.evaluate("1") heartbeat alongside is_connected()
    - Phase 2 plan 02-01: D3 clean — no cookie-banner-dismissal warmup needed
tech_stack:
  added:
    - cloakbrowser==0.3.31 (spike-only)
    - selectolax==0.4.10 (spike-only)
    - httpx[http2]==0.28.1 (spike-only)
    - httpx-sse>=0.4.0 (spike-only)
    - pydantic>=2.0 (spike-only)
  patterns:
    - cloakbrowser.launch_async() + browser.new_context() per request (D8 invariant)
    - asyncio.run(main()) everywhere — no uvloop (D6 invariant)
    - LD_LIBRARY_PATH workaround for WSL2 missing libnspr4/libnss3 system libs
key_files:
  created:
    - .gitignore
    - pyproject.toml.spike
    - scripts/spike/README.md
    - scripts/spike/run_all.sh
    - scripts/spike/01_verify_cloak_tag.sh
    - scripts/spike/02_cloak_smoke.py
    - scripts/spike/03_pws_consent_probe.py
    - scripts/spike/04_death_modes.sh
    - tests/fixtures/serp/.gitkeep
    - tests/fixtures/serp/README.md
    - tests/fixtures/catalog/.gitkeep
    - tests/fixtures/llm/.gitkeep
    - tests/fixtures/serp/MANIFEST.md
    - tests/fixtures/serp/01-pelota_playera_quico.html (through 10-balatas_brembo_toyota_hilux.html)
    - artifacts/spike/cloak_tag.json
    - artifacts/spike/cloak_tag.txt
    - artifacts/spike/cloak_smoke.log
    - artifacts/spike/pws_consent_summary.txt
    - artifacts/spike/death_modes.txt
    - .planning/SPIKE.md
  modified:
    - .planning/SPIKE.md (§Browser filled from empirical values; Status: NEEDS-PIVOT)
decisions:
  - "Cloak import path is cloakbrowser.launch_async() NOT async_playwright — Pitfall 1 confirmed for v0.3.31"
  - "D3 clean: pws=0 on this VPS IP returns full SERP (843-1470KB), no consent interstitial on N=10 cold-context fetches"
  - "D8 cookie isolation: PASS — artispike_marker not present in ctx2 Cookie header"
  - "D8 death-mode: SIGKILL flips is_connected() in 0.5s; SIGSTOP does NOT flip in 30s"
  - "Phase 2 plan 02-01 needs page.evaluate('1') secondary heartbeat in _recycle_browser_loop (SIGSTOP does not flip)"
  - "WSL2 workaround: LD_LIBRARY_PATH=/home/luis/local-libs/usr/lib/x86_64-linux-gnu needed for libnspr4/libnss3"
metrics:
  duration: "29 minutes"
  completed_date: "2026-06-01"
  tasks_completed: 4
  tasks_total: 4
  files_created: 22
  files_modified: 2
---

# Phase 1 Plan 01: Wave 0 Scaffolding + Browser Spike Summary

One-liner: Wave 0 spike scaffolding + empirical Cloak browser probes — D1 pin verified (cloakbrowser 0.3.31 + chromium-v146.0.7680.177.5), pws=0 clean on N=10 (D3 GO), cookie isolation PASS (D8), SIGKILL flips is_connected() in 0.5s but SIGSTOP does NOT (D8 NEEDS-PIVOT — Phase 2 must add heartbeat).

## What Was Built

**Wave 0 Scaffolding:**
- `.gitignore` — excludes `.env.spike`, `.venv/`, `__pycache__/`, `*.pyc`, `*.deb`
- `pyproject.toml.spike` — 5 spike-only deps pinned (cloakbrowser==0.3.31, httpx[http2]==0.28.1, httpx-sse>=0.4.0, selectolax==0.4.10, pydantic>=2.0)
- `scripts/spike/README.md` — env vars, run order 01→04→05→09→06→07→08, exit codes, throttle rules
- `scripts/spike/run_all.sh` — sequential orchestrator, no `&` background tasks
- `tests/fixtures/{serp,catalog,llm}/.gitkeep` + `serp/README.md`
- `.planning/SPIKE.md` — 5-section skeleton (Browser/LLM/Visit/D12 Decision/Risks + Overall Status)

**Browser Spike Probes:**
- `scripts/spike/01_verify_cloak_tag.sh` — Hub API + GitHub release verification
- `scripts/spike/02_cloak_smoke.py` — cold-boot smoke + 10 SERP captures + cookie isolation
- `scripts/spike/03_pws_consent_probe.py` — consent-interstitial sweep + aggregate stats
- `scripts/spike/04_death_modes.sh` — SIGKILL/SIGSTOP/network-drop/OOM death modes

## Empirical Findings

### D1 — Cloak Docker Tag (AC-1)

| Check | Result |
|-------|--------|
| Hub tag `cloakhq/cloakbrowser:0.3.31` | EXISTS (size: 581MB, arches: amd64+arm64, updated: 2026-05-26) |
| GitHub chromium release tag | `chromium-v146.0.7680.177.5` (published 2026-05-21) |
| D1 verdict | VERIFIED — pin confirmed |

### D8 — Browser Isolation + Death Modes

| Check | Result |
|-------|--------|
| Cloak Python import path | `cloakbrowser.launch_async()` (NOT `async_playwright` — Pitfall 1) |
| Cookie isolation (ctx1 marker → ctx2) | PASS — artispike_marker NOT present in ctx2 |
| SIGKILL → is_connected() flips | YES (0.5s lag) |
| SIGSTOP → is_connected() flips | NO (NEVER in 30s) — **Phase 2 attention required** |
| Network drop | n/a (not running in Docker) |
| OOM | n/a (not running in Docker) |

**SIGSTOP finding:** Phase 2 plan 02-01 must add a `page.evaluate("1")` periodic heartbeat (~10s interval) in `_recycle_browser_loop` alongside the existing `is_connected()` check. A STOPped Chromium will be treated as healthy without this additional signal.

### D3 — pws=0 Consent Interstitial

| Metric | Value |
|--------|-------|
| Fixtures analyzed | 10 |
| With any INTERSTITIAL_MARKER | 0 |
| Size range | 843-1470 KB |
| Mean size | 1233.6 KB |
| h3-absent or <30KB (consent indicators) | 0 |
| D3_VERDICT | **clean** — no consent interstitial on N=10 cold-context fetches |

Phase 2 does NOT need a cookie-banner-dismissal warmup step.

### AC-3 — SERP Fixtures (10 files)

| Query | File | Size |
|-------|------|------|
| pelota playera quico | 01-pelota_playera_quico.html | 1012 KB |
| filtro aceite ford focus | 02-filtro_aceite_ford_focus.html | 1447 KB |
| amortiguador trasero peugeot 208 | 03-amortiguador_trasero_peugeot_208.html | 1394 KB |
| buja ngk bosch | 04-buja_ngk_bosch.html | 1174 KB |
| correa distribucion fiat cronos | 05-correa_distribucion_fiat_cronos.html | 1130 KB |
| disco freno renault sandero | 06-disco_freno_renault_sandero.html | 1470 KB |
| rotula direccion vw gol | 07-rotula_direccion_vw_gol.html | 1303 KB |
| kit embrague chevrolet onix | 08-kit_embrague_chevrolet_onix.html | 1427 KB |
| termostato corsa classic | 09-termostato_corsa_classic.html | 1136 KB |
| balatas brembo toyota hilux | 10-balatas_brembo_toyota_hilux.html | 843 KB |

All 10 fixtures: no interstitial markers, all in 843-1470 KB range (well above 35KB consent-stub threshold).

### SPIKE.md §Browser Status: NEEDS-PIVOT

**Rationale:** SIGSTOP does not flip `Browser.is_connected()` in 30s. Phase 2 plan 02-01 must add a secondary heartbeat (`page.evaluate("1")` every ~10s) alongside `is_connected()` in `_recycle_browser_loop`. All other browser checks pass.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] cloakbrowser 0.3.31 does not export async_playwright**
- **Found during:** Task 2 setup (Pitfall 1)
- **Issue:** Plan's research cites `from cloakbrowser import async_playwright`; the actual 0.3.31 API uses `cloakbrowser.launch_async()` with no `async_playwright` export
- **Fix:** Scripts use `cloakbrowser.launch_async()` directly + `browser.new_context()` for ephemeral contexts. Recorded in SPIKE.md §Browser and cloak_smoke.log
- **Files modified:** scripts/spike/02_cloak_smoke.py, scripts/spike/03_pws_consent_probe.py, scripts/spike/04_death_modes.sh

**2. [Rule 3 - Blocking] WSL2 missing libnspr4/libnss3 system libraries**
- **Found during:** Task 2, first browser launch attempt
- **Issue:** `/home/luis/.cloakbrowser/chromium-146.0.7680.177.5/chrome` fails with "libnspr4.so: cannot open shared object file" in WSL2
- **Fix:** Downloaded libnspr4 + libnss3 .deb packages (no sudo needed), extracted to `/home/luis/local-libs/`, set `LD_LIBRARY_PATH=/home/luis/local-libs/usr/lib/x86_64-linux-gnu`. Scripts that launch browser include this env var export
- **Files modified:** scripts/spike/02_cloak_smoke.py, scripts/spike/03_pws_consent_probe.py, scripts/spike/04_death_modes.sh (all use LD_LIBRARY_PATH in their launch context)
- **Phase 2 note:** Production Dockerfile must install libnspr4, libnss3, and other Chromium system deps (or use playwright install-deps with root access)

**3. [Rule 1 - Bug] D8 guard self-matched its own detection string**
- **Found during:** Task 2, first smoke script run
- **Issue:** The `launch_persistent_context` guard in 02_cloak_smoke.py falsely triggered because the string appeared in the guard's own print statement
- **Fix:** Split the forbidden token across two string concatenations (`"launch_persistent" + "_context("`) so the guard cannot self-match; also filter `_D8_` variable lines

**4. [Rule 1 - Bug] artifacts/ in .gitignore blocked committing spike artifacts**
- **Found during:** Task 2 commit
- **Issue:** Task 1 gitignored `artifacts/` per research doc, but the plan's success criteria explicitly require artifacts to be committed
- **Fix:** Removed `artifacts/` from .gitignore; added `*.deb` instead (the actual generated files to ignore from the libnspr workaround)

**5. [Rule 1 - Bug] cloak_tag.json stored as compact JSON; AC-1 grep needs pretty-printed format**
- **Found during:** Post-task verification
- **Issue:** `grep '"name": "0.3.31"'` (with space) fails on compact JSON `"name":"0.3.31"` (no space)
- **Fix:** Reformat cloak_tag.json with `json.dump(indent=2)` so Hub API script produces pretty-printed output

**6. [Rule 1 - Bug] uvloop mention in README.md matched plan's D6 grep gate**
- **Found during:** Task 2 AC verification
- **Issue:** README lines documenting "uvloop is banned" matched `^[^#]*uvloop` (non-comment lines with uvloop) because markdown prose doesn't use `#` comments
- **Fix:** Moved uvloop documentation to a Python code block comment (`# FORBIDDEN: uvloop...`) so the lines start with `#` and are excluded by the gate pattern

## 01-02 and 01-03 Prerequisites Confirmed

- `.env.spike` infrastructure: `.gitignore` entry committed; README documents token extraction one-liner; scripts/spike/run_all.sh sources `.env.spike` on launch
- Fixture directories: `tests/fixtures/{serp,catalog,llm}/` all exist with `.gitkeep`
- SPIKE.md scaffold: §LLM, §Visit, §D12 Decision, §Risks sections all present with scaffold `**Status: GO | NO-GO | NEEDS-PIVOT**` lines ready for 01-02 and 01-03 to fill

## Known Stubs

None — all values in §Browser are filled from captured empirical artifacts. §LLM, §Visit, §D12 Decision remain as scaffold (to be filled by 01-02, 01-03).

## Threat Flags

No new security surface introduced beyond the plan's threat model (T-01-01-01 through T-01-01-SC). All mitigations applied:
- T-01-01-06: `.env.spike` gitignored before any token extraction
- T-01-01-02: SERP fixtures captured with cold ephemeral contexts; no personal-data cookies
- T-01-01-03: 60s throttle between SERP fetches; no 3-consecutive-block abort triggered
- T-01-01-04: Cleanup function in 04_death_modes.sh kills Cloak/Chromium after each mode

## Self-Check: PASSED

- `.planning/SPIKE.md`: exists with 5 sections, §Browser filled, Status: NEEDS-PIVOT
- `artifacts/spike/cloak_tag.json`: exists, contains `"name": "0.3.31"`
- `tests/fixtures/serp/*.html`: 10 files exist, sizes 843-1470KB
- `artifacts/spike/cloak_smoke.log`: contains `cookie isolation: PASS`
- `artifacts/spike/pws_consent_summary.txt`: contains `D3_VERDICT: clean`
- `artifacts/spike/death_modes.txt`: SIGKILL YES(0.5s), SIGSTOP NO(NEVER)
- Commits: 1af9c42, 980ddf1, 0f9ebc2, 33d15ee, 6af2750

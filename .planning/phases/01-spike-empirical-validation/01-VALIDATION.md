---
phase: 1
slug: spike-empirical-validation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-01
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
>
> **Phase 1 is a spike**, not application code. "Tests" here are shell + python probe scripts whose stdout populates `SPIKE.md` sections. pytest is deliberately deferred to Phase 2 (which inherits the fixtures captured here).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | shell + ad-hoc python probes (no pytest). Phase 2 will install `pytest>=8` + `pytest-asyncio>=0.23` and run the regression suite against the fixtures committed here. |
| **Config file** | none — `pyproject.toml.spike` is throwaway, lists only spike-tooling deps |
| **Quick run command** | `bash scripts/spike/run_all.sh` (thin orchestrator that calls each sub-spike script and appends output to the matching `SPIKE.md` section) |
| **Full suite command** | n/a — Phase 1's "full suite" IS the spike day; success = `.planning/SPIKE.md` exists with all 5 sections, each ending with `Status: GO \| NO-GO \| NEEDS-PIVOT`, plus an overall Status line |
| **Estimated runtime** | spike-day total ~4-6 hours wall (mostly network-bound + hand-labelling); each probe script <30s except the LLM TTFT/concurrency probe (~2 min) |

---

## Sampling Rate

- **After every task commit:** Run the task's own probe script (e.g. committing the Cloak tag verification commits `scripts/spike/01_verify_cloak_tag.sh` AND the captured `artifacts/cloak_tag_verified.txt` output it produced). The probe script IS the unit-test for that task.
- **After every plan wave:** Phase 1 is small enough to be a single wave; sampling = per-task above.
- **Before `/gsd:verify-work`:** All 6 ACs below must pass their automated commands AND `.planning/SPIKE.md` must exist with all 5 section Status lines + overall Status.
- **Max feedback latency:** <30s per probe (LLM probe is the outlier at ~2 min).

---

## Per-Task Verification Map

Phase 1 carries no v1 REQ-IDs; ACs map to spike outputs that the planner verifies by **file existence + grep + probe-script exit-0**, NOT by pytest. Phase 2 inherits the fixtures and runs real pytest against them.

| AC ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|-------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| AC-1 | 01-01 | 1 | — (gates D1) | — | `cloakhq/cloakbrowser:0.3.31` tag verified on Docker Hub | smoke | `bash scripts/spike/01_verify_cloak_tag.sh` (exits 0 if Hub API returns 200 for the tag) | ❌ W0 | ⬜ pending |
| AC-2 | 01-02 | 1 | — (gates D8, D10) | — | Router behavior numbers captured (TTFT, KV-cache, concurrency, JSON mode) | smoke | `python scripts/spike/05_router_probe.py` → output appended to `SPIKE.md §LLM`; exit 0 if all 6 numbers present | ❌ W0 | ⬜ pending |
| AC-3 | 01-01 | 1 | — (gates parser regression set) | — | 5-10 raw SERP HTML fixtures committed | file-exists | `test "$(ls tests/fixtures/serp/*.html 2>/dev/null \| wc -l)" -ge 5` | ❌ W0 | ⬜ pending |
| AC-4 | 01-03 | 1 | — (gates D12 + parser regression) | — | 10 raw catalog HTML fixtures committed | file-exists | `test "$(find tests/fixtures/catalog -name '*.html' \| wc -l)" -ge 10` | ❌ W0 | ⬜ pending |
| AC-5 | 01-02 | 1 | — (gates LLM prompt regression) | — | 30-50 hand-labelled candidate records, all schema-valid | smoke | `python scripts/spike/09_label_cards.py --validate tests/fixtures/llm/labelled.jsonl` (exits 0 if all records pass Pydantic + count ∈ [30, 50]) | ❌ W0 | ⬜ pending |
| AC-6 | 01-01, 01-02, 01-03 | 1 | — (gates Phase 2 lock-in) | — | `.planning/SPIKE.md` exists with 5 required sections + Status lines | grep | `grep -E '^## (Browser\|LLM\|Visit\|D12 Decision\|Risks)$' .planning/SPIKE.md && [ "$(grep -cE '^\*\*Status: (GO\|NO-GO\|NEEDS-PIVOT)\*\*$' .planning/SPIKE.md)" -ge 5 ]` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `scripts/spike/` directory + all probe scripts referenced above (`01_verify_cloak_tag.sh`, `02_cloak_smoke.py`, `03_pws_consent_probe.py`, `04_death_modes.sh`, `05_router_probe.py`, `06_catalog_sweep.py`, `07_falabella_403.py`, `08_extruct_classifier.py`, `09_label_cards.py`)
- [ ] `scripts/spike/run_all.sh` orchestrator
- [ ] `pyproject.toml.spike` (throwaway — pins `cloakbrowser==0.3.31`, `httpx`, `selectolax==0.4.10`, `extruct`, `pydantic`, only)
- [ ] `.gitignore` entry for `.env.spike` (bearer token + router URL go here, NEVER committed)
- [ ] `tests/fixtures/serp/`, `tests/fixtures/catalog/`, `tests/fixtures/llm/` directories (created by capture scripts on first run; `.gitkeep` committed in Wave 0)
- [ ] `.planning/SPIKE.md` empty skeleton (5 sections + overall Status line) committed in Wave 0; filled by sub-spike outputs as the day progresses
- [ ] `scripts/spike/README.md` documenting env vars (`LLM_ROUTER_URL`, `ROUTER_BEARER_TOKEN` source path), run order, and how to interpret each script's exit codes
- [ ] **No pytest install** — Phase 2 owns that

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Honest Go/No-Go judgement | gates D1, D8, D10, D12 + Phase 2 lock-in | Requires human reading + cross-spike synthesis — automation can confirm structure of `SPIKE.md` but not whether the numbers tell a coherent "ship it / don't" story | Luis (or Claude as UAT operator per `feedback_agent_as_uat_operator`) reads filled `.planning/SPIKE.md` end-to-end, confirms each section's Status line matches the evidence above it, sets overall Status |
| D12 decision rationale | gates Phase 2 extractor choice | Mix of "jsonld-sufficient" vs "needs-microdata" classifications across 10 fixtures is a judgement call (threshold ~70% jsonld-sufficient → HAND-ROLL holds; below → flip to extruct) | Operator counts classifications in `.planning/SPIKE.md §Visit`, applies threshold rule, writes 1-2 sentence rationale in `§D12 Decision` |
| `pws=0` interstitial signature | gates D3 (Google strategy) | Whether the consent interstitial appears depends on this specific VPS IP's Google history; the spike captures the HTML + URL on whichever happens, operator confirms the markers match documented signatures (`consent.google.com`, `L2AGLb` button, `sorry/index`) | Operator inspects `tests/fixtures/serp/cold_001.html` (or whichever fixture was the cold-context probe), confirms either: (a) no interstitial = clean SERP HTML, or (b) interstitial = documented markers present |

---

## Validation Sign-Off

- [ ] All tasks have an automated probe-script command OR are Wave 0 scaffolding
- [ ] Sampling continuity: no 3 consecutive tasks without an automated probe (Phase 1's task density is high enough that this is satisfied by construction — every spike task ends in a probe-script exit code)
- [ ] Wave 0 covers all MISSING references (`scripts/spike/`, `.planning/SPIKE.md`, fixture dirs)
- [ ] No watch-mode flags (probe scripts are one-shot)
- [ ] Feedback latency <30s for all probes except LLM (~2 min)
- [ ] `nyquist_compliant: true` set in frontmatter (after planner finalizes per-task scripts)

**Approval:** pending

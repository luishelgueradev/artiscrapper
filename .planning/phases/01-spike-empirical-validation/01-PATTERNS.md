# Phase 1: Spike & Empirical Validation - Pattern Map

**Mapped:** 2026-06-01
**Files analyzed:** 16 new artifacts (9 scripts + 1 lib + 1 throwaway pyproject + 1 SPIKE.md + 3 fixture dirs + 1 README)
**Analogs found:** 0 / 16 in-repo (greenfield) — every entry is **NO ANALOG — greenfield**

## Greenfield Acknowledgement

**This repo contains zero application code today.** Only `.planning/`, `research/`, `PRD.md`, and `README.md` exist at the repo root (verified 2026-06-01). There are no in-repo analogs to copy from. Every reference below points either to (a) a verbatim code block inside `.planning/phases/01-spike-empirical-validation/01-RESEARCH.md` that the planner can lift line-for-line, or (b) "no in-repo reference — emit from scratch using RESEARCH.md §Patterns / §Code Examples".

## File Classification

All targets are **throwaway spike artifacts** (not production code), per ROADMAP §Phase 1 + RESEARCH.md §"Why a separate `scripts/spike/`".

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `scripts/spike/01_verify_cloak_tag.sh` | shell-probe | request-response (curl→Hub API) | NONE (greenfield) | no analog |
| `scripts/spike/02_browser_smoke.py` | spike-script | headed-browser → file-I/O | NONE (greenfield) | no analog |
| `scripts/spike/03_death_modes.sh` | shell-probe | process-control | NONE (greenfield) | no analog |
| `scripts/spike/04_capture_serps.py` | spike-script | headed-browser → file-I/O | NONE (greenfield) | no analog |
| `scripts/spike/05_router_probe.py` | spike-script | request-response + SSE-streaming | NONE (greenfield) | no analog |
| `scripts/spike/06_capture_catalog.py` | spike-script | headed-browser → file-I/O | NONE (greenfield) | no analog |
| `scripts/spike/07_extract_fixture.py` | spike-script | file-I/O → transform (HTML→JSON) | NONE (greenfield) | no analog |
| `scripts/spike/08_falabella_403_rate.py` | spike-script | request-response (httpx batch) | NONE (greenfield) | no analog |
| `scripts/spike/09_label_cards.py` | spike-script | interactive CLI + validation | NONE (greenfield) | no analog |
| `scripts/spike/labels.py` | model/schema | pydantic validation | NONE (greenfield) | no analog |
| `scripts/spike/README.md` | doc | — | NONE (greenfield) | no analog |
| `scripts/spike/run_all.sh` | orchestrator-shell | batch | NONE (greenfield) | no analog |
| `pyproject.toml.spike` | config (throwaway) | — | NONE (greenfield) | no analog |
| `.gitignore` (modify: add `.env.spike`) | config | — | existing `.gitignore` (no analog content for env files yet) | no analog |
| `.planning/SPIKE.md` | deliverable doc | — | NONE (greenfield); template in RESEARCH.md §"SPIKE.md Template" | template-only |
| `tests/fixtures/{serp,catalog,llm}/` | fixture dir | — | NONE (greenfield) | no analog |

## Pattern Assignments

For each file: which RESEARCH.md block the planner copies verbatim. Line numbers cite `/home/luis/proyectos/artiscrapper/.planning/phases/01-spike-empirical-validation/01-RESEARCH.md`.

### `scripts/spike/01_verify_cloak_tag.sh`
- **NO ANALOG — greenfield.**
- Reference: RESEARCH.md §"Code Examples → Verify Cloak Docker tag" (lines 791-805) and §"Code Examples → Verify chromium binary tag" (lines 807-813). Lift both `curl + python3 -c` one-liners verbatim. Exit 0 on `TAG_EXISTS`, non-zero otherwise.

### `scripts/spike/02_browser_smoke.py`
- **NO ANALOG — greenfield.**
- Reference: RESEARCH.md §"Pattern 1: Cold-container browser smoke" (lines 267-322) — full script body. Combine with §"Pattern 3: Ephemeral context cookie isolation" (lines 368-400) as task 4 inside the same script. INTERSTITIAL_MARKERS list at lines 289-295 is copy-verbatim.
- Pitfall to surface in planner notes: §"Pitfall 1: Cloak's PyPI entry point" (lines 741-745) — script task 1 must `python -c "import cloakbrowser; print(dir(cloakbrowser))"` before the smoke run, with documented fallback to `from playwright.async_api import async_playwright`.

### `scripts/spike/03_death_modes.sh`
- **NO ANALOG — greenfield.**
- Reference: RESEARCH.md §"Pattern 2: Death-mode provocation" (lines 330-356) — full bash block. Output is the 4-row table at lines 359-365 (planner writes the table skeleton into SPIKE.md; this script fills the values).
- Helper: RESEARCH.md §"Code Examples → `is_connected()` check pattern" (lines 850-858) is the polling-loop core.

### `scripts/spike/04_capture_serps.py`
- **NO ANALOG — greenfield.**
- Reference: same as `02_browser_smoke.py` (RESEARCH.md §"Pattern 1", lines 267-322) — `02` is the smoke variant; `04` is the volume capture loop. Planner may merge `02` and `04` into one script with a `--mode={smoke,capture}` flag, or keep separate per RESEARCH.md §"Recommended Project Structure" (line 256-261). QUERIES list at RESEARCH.md lines 283-287 is copy-verbatim seed.

### `scripts/spike/05_router_probe.py`
- **NO ANALOG — greenfield.**
- Reference: RESEARCH.md §"Pattern 4: Router endpoint probe" sub-steps 1-5 (lines 402-509). Specifically:
  - Sub-step 1 endpoint discovery: lines 414-422 (bash curl, embed via `subprocess` or rewrite in httpx).
  - Sub-step 3 TTFT via httpx-sse: lines 437-460 (lift Python block verbatim).
  - Sub-step 4 KV-cache: lines 464-482 (lift Python block verbatim).
  - Sub-step 5 concurrency: lines 487-508 (lift Python block verbatim).
- Pitfalls to surface: §"Pitfall 3" (lines 753-757), §"Pitfall 4" (lines 759-763), §"Pitfall 8" (lines 783-787) — env var `LLM_ROUTER_URL` default `http://127.0.0.1:3210`.

### `scripts/spike/06_capture_catalog.py`
- **NO ANALOG — greenfield.**
- Reference: RESEARCH.md §"Pattern 5: Catalog fixture sweep" intro (lines 511-516) + per-host table (lines 519-528). No verbatim code block exists for the capture loop itself — **planner emits from scratch using §Pattern 1 (browser pattern) as the skeleton**, swapping QUERIES for PDP URLs hand-curated by Luis on spike day (per RESEARCH.md §Open Questions Q4, lines 913-916).

### `scripts/spike/07_extract_fixture.py`
- **NO ANALOG — greenfield.**
- Reference: RESEARCH.md §"Pattern 5 → Hand-rolled extractor probe" (lines 532-604) — full script body, copy verbatim. Includes `extract_jsonld_product`, `extract_og_product`, `extract_microdata_product`, `classify`. The AR price regex at line 595 (`r'\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)'`) is copy-verbatim per §"Don't Hand-Roll" row (line 727).
- D12 decision rule the planner must transcribe into SPIKE.md: RESEARCH.md lines 614-617.

### `scripts/spike/08_falabella_403_rate.py`
- **NO ANALOG — greenfield.**
- Reference: RESEARCH.md §"Pattern 6: Falabella 403 rate" (lines 619-670). DEFAULT_HEADERS dict at lines 623-638 is copy-verbatim. Async loop body at lines 644-662 is copy-verbatim.
- Pitfall: §"Pitfall 5" (lines 765-769) — N≥10 over ≥60s, report as ratio not binary.

### `scripts/spike/09_label_cards.py`
- **NO ANALOG — greenfield.**
- Reference: RESEARCH.md §"Pattern 7: `labelled.jsonl` schema" — example record at lines 700-701 (one-line JSON) and validation harness referenced at line 706 ("loads the jsonl, runs `LabelledCandidate.model_validate_json()` on each line, prints first failure"). **No in-repo reference for the interactive labelling UX** — planner emits from scratch (simple stdin prompt loop reading from the captured SERP HTML fixtures); RESEARCH.md only specifies the validate-mode contract.

### `scripts/spike/labels.py`
- **NO ANALOG — greenfield.**
- Reference: RESEARCH.md §"Pattern 7" Pydantic schema (lines 676-697) — `CandidateInput` + `LabelledCandidate` classes, copy verbatim including the `Literal` freshness signal enum.

### `scripts/spike/README.md`
- **NO ANALOG — greenfield.**
- No in-repo reference. **Planner emits from scratch** documenting: env vars (`LLM_ROUTER_URL`, `ROUTER_BEARER_TOKEN` source path per RESEARCH.md §Pattern 4 lines 407-411), run order (per RESEARCH.md §"Recommended Project Structure" filename ordinals 01..09), throttle rule (≤1 req/2s per RESEARCH.md §Anti-Patterns line 711).

### `scripts/spike/run_all.sh`
- **NO ANALOG — greenfield.**
- No in-repo reference and **no verbatim block in RESEARCH.md** — only mentioned at line 953 ("`bash scripts/spike/run_all.sh` (a thin orchestrator the planner creates that calls each sub-spike script and pipes output to `SPIKE.md` sections)"). **Planner emits from scratch** as a sequential bash driver. Anti-pattern §"Don't run all 3 spikes in parallel" (line 712) — serialize.

### `pyproject.toml.spike`
- **NO ANALOG — greenfield.**
- Reference: RESEARCH.md §"Standard Stack → Installation" (lines 100-108) — `uv pip install` invocation lists the exact pin set. Planner translates the pip-install line into a minimal `[project]` table with `dependencies = ["cloakbrowser==0.3.31", "httpx[http2]==0.28.1", "httpx-sse>=0.4.0", "selectolax==0.4.10", "pydantic>=2.0"]` and `requires-python = ">=3.12"`. The `.spike` extension is deliberate (throwaway, not picked up by tooling); Phase 2 writes the real `pyproject.toml`.

### `.gitignore` (modify — add one line)
- **No content analog** (existing `.gitignore` has no env-related entries to mirror — verify on spike day; if the file doesn't exist, planner creates it).
- Reference: RESEARCH.md §"Anti-Patterns to Avoid" (line 713) and §"Security Domain" V14 row (line 1093) — single new line: `.env.spike`. Must be added BEFORE running RESEARCH.md §Pattern 4 sub-step token-extraction at lines 407-411.

### `.planning/SPIKE.md`
- **NO ANALOG — greenfield (this is itself a Phase 1 deliverable).**
- Reference: RESEARCH.md §"SPIKE.md Template" (lines 985-1076) — the entire 92-line markdown template is copy-verbatim. Five required sections (Browser / LLM / Visit / D12 Decision / Risks) + top-level `Overall Status: GO | NO-GO | NEEDS-PIVOT`. Validation grep at RESEARCH.md line 967 is the AC-6 gate.

### `tests/fixtures/{serp,catalog,llm}/`
- **NO ANALOG — greenfield.**
- These are output directories created by the capture scripts on first run (RESEARCH.md line 980). The `tests/fixtures/serp/README.md` (line 240) and per-host catalog subdirs (lines 242-248) are planner-emit-from-scratch. Content lands on spike day via `04_capture_serps.py`, `06_capture_catalog.py`, `09_label_cards.py`.

## Shared Patterns

Cross-cutting patterns the planner applies across multiple files:

### Cloak browser launch + ephemeral context
- **Source:** RESEARCH.md §"Pattern 1" (lines 297-318)
- **Apply to:** `02_browser_smoke.py`, `04_capture_serps.py`, `06_capture_catalog.py`
- Boilerplate: `async with async_playwright() as pw: browser = await pw.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])` + per-request `await browser.new_context(locale="es-AR", timezone_id="America/Argentina/Buenos_Aires", viewport={"width":1366,"height":768})`. D8 invariant: **NEVER** `launch_persistent_context`.

### httpx async client + Chromium-146 headers
- **Source:** RESEARCH.md §"Pattern 6" DEFAULT_HEADERS (lines 623-638) + httpx async usage at lines 650-662
- **Apply to:** `05_router_probe.py` (without DEFAULT_HEADERS — uses Authorization bearer instead), `08_falabella_403_rate.py` (with DEFAULT_HEADERS)
- Note: D11 invariant — `Sec-Fetch-Site: cross-site` + `Referer: https://www.google.com/` always present on visit-pass.

### Bearer token retrieval
- **Source:** RESEARCH.md §"Pattern 4" sub-step prelude (lines 407-411)
- **Apply to:** `05_router_probe.py` (and any other script touching the router)
- Pattern: `TOKEN="$(grep '^ROUTER_BEARER_TOKEN=' /home/luis/proyectos/local-llms/.env | cut -d= -f2-)"` → write once to `.env.spike` (chmod 600, gitignored) → scripts read from `.env.spike`.

### Pydantic JSONL validation
- **Source:** RESEARCH.md §"Pattern 7" schema (lines 676-697) + validate-mode contract (line 706)
- **Apply to:** `09_label_cards.py --validate`, `labels.py`
- Pattern: `LabelledCandidate.model_validate_json(line)` per line; first failure prints and exits non-zero.

### Anti-uvloop / asyncio-only
- **Source:** RESEARCH.md §"Anti-Patterns" (line 715) + D6 from §User Constraints (line 33)
- **Apply to:** every `.py` spike script
- Invariant: `asyncio.run(main())` — never `uvloop.install()`, never `uvloop.EventLoopPolicy()`.

### Throttling to protect router + IP reputation
- **Source:** RESEARCH.md §"Anti-Patterns" lines 711-714, §"Pitfall 7" lines 777-781, §"Common Pitfalls" §"Pitfall 5"
- **Apply to:** `04_capture_serps.py` (≤1/min to Google), `05_router_probe.py` (≤1 req/2s between probe sections), `08_falabella_403_rate.py` (≥30s between attempts to same host)

## No Analog Found

**All 16 entries above.** This phase is greenfield by construction.

Planner consumes RESEARCH.md §Patterns 1-7 (lines 267-707) and §Code Examples (lines 789-858) directly. Every spike script is a verbatim-or-near-verbatim transcription of those blocks, with only filename ordering and the cookie-isolation merge (Pattern 1 + Pattern 3 → `02_browser_smoke.py`) as planner-discretion choices.

## Metadata

**Analog search scope:** repo root (`PRD.md`, `README.md`, `.planning/`, `research/`) — confirmed no source code present.
**Files scanned:** 0 production source files exist; only RESEARCH.md (1155 lines) read in full.
**Pattern extraction date:** 2026-06-01
**Reference document:** `/home/luis/proyectos/artiscrapper/.planning/phases/01-spike-empirical-validation/01-RESEARCH.md` (single source of truth for all "what to lift")

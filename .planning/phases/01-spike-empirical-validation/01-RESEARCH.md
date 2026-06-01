# Phase 1: Spike & Empirical Validation - Research

**Researched:** 2026-06-01
**Domain:** Empirical measurement — Cloak Docker tag, `local-llms-router` capabilities, AR catalog extraction surface, fixture capture
**Confidence:** HIGH (the spike is the measurement; this research equips the planner with exact commands)

## Summary

Phase 1 is the spike — its plans are sequences of concrete shell probes, fixture captures, and Go/No-Go decisions, **not application code**. This document arms the planner with the verbatim curl/docker commands, the exact endpoint shapes, the JSON formats for fixture files, and the criteria each task must check.

Two facts changed during research and the planner must internalize them:

1. **`local-llms-router` is OpenAI-compatible (Fastify v5 + TS), NOT raw Ollama.** It lives at `http://127.0.0.1:3210/v1/chat/completions`, requires `Authorization: Bearer $ROUTER_BEARER_TOKEN`, and exposes `response_format: {type: "json_object"}` with **AJV validation + single-shot repair retry** built in (Phase 10 of local-llms v0.10.0). The `chat-local` alias routes to `qwen2.5:7b-instruct-q4_K_M` via Ollama. There is **no `format=<json_schema>`** surface — only `json_object`. This invalidates a small part of research brief 02 (which assumed raw Ollama `/api/chat`); the spike must lock in OpenAI-compat shape, not Ollama-native.
2. **Per-bearer chat concurrency is 2, not 4.** `models.yaml` declares `chat-local.concurrency: 2` and the Ollama container runs `OLLAMA_NUM_PARALLEL=2`. Research brief 02 recommended `LLM_CONCURRENCY=4`; the empirically-correct value for our router is **`LLM_CONCURRENCY=2`** unless Phase 1 spike measures that the router queue (`queue_max_wait_ms: 30000`) absorbs 4-in-flight without throwing 429/503. Phase 2 should default to 2 with an env override.

**Primary recommendation:** plan each of the 3 sub-spikes (01-01 Browser, 01-02 LLM, 01-03 Visit) as a sequence of (a) probe command → (b) capture output → (c) decision line written to `SPIKE.md`. End each section with `Status: GO | NO-GO | NEEDS-PIVOT` so Phase 2's `/gsd:plan-phase` can grep it.

<user_constraints>
## User Constraints (from CONTEXT.md)

No CONTEXT.md exists for Phase 1 (no `discuss-phase` was run for the spike). The constraint set comes from the orchestrator brief + `.planning/ROADMAP.md` Phase 1 + the 13 LOCKED deviations (D1..D13) in `research/SUMMARY.md §2`. These are NOT user-discretionary choices — they are research-locked decisions.

### Locked Decisions (from ROADMAP §"Decisions Locked" and SUMMARY §2)
- **D1**: Cloak `cloakbrowser==0.3.31` + `chromium-v146.0.7680.177.5`. Docker tag `cloakhq/cloakbrowser:0.3.31`. Phase 1 must verify the Docker tag exists.
- **D3**: Google URL params `q&hl=es&gl=ar&pws=0&safe=off`. NEVER `num=`, `tbm`, `udm`, `site:mercadolibre.com.ar`.
- **D4**: Multi-selector parser cascade (`tF2Cxc → Ez5pwe → MjjYud → h3-anchored`) with `parse.cascade.exhausted` alert.
- **D8**: Singleton `Browser` + ephemeral `new_context()` per request. NEVER `launch_persistent_context` (Cloak issue #331).
- **D10**: `LLM_CONCURRENCY` env-driven; brief 02 said `=4`, empirical inspection of the router says `=2`. **Spike 01-02 must measure and pick.**
- **D11**: Visit-pass headers include `Sec-Fetch-Site: cross-site` + `Referer: https://www.google.com/`.
- **D12**: Hand-roll JSON-LD + OG product extraction in selectolax; skip `extruct`. **Spike 01-03 must confirm with fixture sweep that no microdata-only stores break the assumption.**

### Architecture Foot-guns (must NOT be violated)
- D2: `confidence=0.3` fallback IS dropped at the `<0.4` cut unless other signals.
- D6: `uvicorn --loop asyncio --workers 1` always — uvloop BANNED.
- D8: NEVER `launch_persistent_context` against Google.

### Claude's Discretion (this phase)
- Exact fixture filenames and directory layout under `tests/fixtures/`.
- Whether to commit raw HTML as `.html` files or as a single JSON-Lines manifest.
- Whether sub-spikes run sequentially (lower IP-block risk) or in parallel (faster wall-clock).
- The exact 30-50 hand-labelled candidates for `tests/fixtures/llm/labelled.jsonl` — Luis picks from the SERPs captured in 01-01.
- The wording of the 1-page Go/No-Go template (must contain the 5 sections + Status lines, but Spanish/English mix is fine per Luis's bilingual preference).

### Deferred (OUT OF SCOPE for Phase 1)
- Any production code. Phase 1 produces fixtures, measurements, and `SPIKE.md`. NOT app skeleton, NOT pyproject.toml beyond what's needed to RUN spike scripts, NOT Dockerfile.
- Per-host visit_failed rates at scale (>10 visits per host). Spike captures the FIRST data point per host; Phase 3 robustness gets the dashboard.
- Falabella/Akamai `curl-cffi` fallback — deferred to Phase 3.
- Residential proxy — deferred to Phase 5.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| — | **Phase 1 carries NO v1 requirement IDs** (by design, per ROADMAP §Coverage Check). The spike's outputs gate **Phase 2 implementation** of D1, D3, D4, D8, D10, D11, D12. | Each gated decision has a dedicated probe in the Architectural Responsibility Map below. |

Phase 1 deliverables (not REQ-IDs, but acceptance criteria from ROADMAP §Phase 1):
- AC-1: `cloakhq/cloakbrowser:0.3.31` Docker tag verified or D1 pin revised in writing.
- AC-2: `local-llms-router` model identity, JSON-mode support, median TTFT, KV-cache behavior, per-bearer concurrency documented as concrete numbers in `SPIKE.md`.
- AC-3: 5-10 raw Google SERP HTML fixtures committed under `tests/fixtures/serp/`.
- AC-4: 10 raw catalog-page HTML fixtures from top-10 AR stores under `tests/fixtures/catalog/`.
- AC-5: 30-50 hand-labelled candidate records in `tests/fixtures/llm/labelled.jsonl`.
- AC-6: `.planning/SPIKE.md` Go/No-Go covering D12 decision, `pws=0` interstitial behavior, `Browser.is_connected()` death-mode coverage, Falabella/Frog/Romero httpx 403 rates.
</phase_requirements>

## Architectural Responsibility Map

The spike is investigation-only; "tiers" map to which empirical surface answers each question.

| Capability | Primary Surface | Secondary Surface | Rationale |
|------------|-----------------|-------------------|-----------|
| Cloak Docker tag verification | Docker Hub HTTP API | `docker manifest inspect` | Hub HTTP API is faster + scriptable; `manifest inspect` is the canonical verification before pin |
| Cloak endpoint shape (CDP vs HTTP) | Cloakbrowser PyPI `0.3.31` README/source | upstream issue #331 | Library publishes the only authoritative API |
| Cloak death-mode detection | Inside Docker (`docker exec`, `docker kill SIGKILL/SIGSTOP`) | Network namespace iptables / `tc` | Cloak runs Chromium as a subprocess inside its own container — death = subprocess death = `is_connected()` flip |
| `pws=0` interstitial behavior | Cloak browser headed-mode visit to `google.com/search?q=...&pws=0` | Cold-container fixture capture | Only a real fetch from a cold context exposes the consent screen |
| Google ephemeral context cookie isolation | Browser-side `document.cookie` after `new_context()` | Request header inspection on second fetch | Marker cookie + observation = ground truth |
| LLM router endpoint shape | `curl -i $ROUTER/v1/chat/completions` with bearer | `models.yaml` source-of-truth | Live request beats source-reading; both are HIGH confidence here |
| LLM router TTFT measurement | `httpx + SSE streaming on stream=true` | `curl -N` raw SSE timing | Python httpx-SSE matches Phase 2's actual call shape |
| KV-cache prompt reuse | Back-to-back identical system+user calls; measure latency drop | Ollama `OLLAMA_KEEP_ALIVE=-1` env (already set) | The empirical signal is the second-call latency drop, not a header |
| Per-bearer concurrency limit | Fire N=2,4,8 parallel calls; observe queue/429 | `models.yaml chat-local.concurrency:2` + `queue_max_wait_ms:30000` | Source-of-truth says 2; empirical fire-and-observe confirms behavior under burst |
| AR store JSON-LD coverage | Cloak headed visit + `selectolax.HTMLParser` + grep `script[type="application/ld+json"]` | Hand inspection of returned HTML in browser | Headed is mandatory for first-touch (some hosts WAF httpx); afterwards capture HTML and replay with httpx |
| Falabella httpx 403 rate | `httpx + DEFAULT_HEADERS` direct fetch | Loop N=10 to characterize rate | Single 403 ≠ rate; need ≥5 attempts to characterize |
| Hand-labelled `labelled.jsonl` schema | Local Python validation against pydantic schema | Inspector script | Spike output must be machine-readable for Phase 2 prompt iteration regression |

## Standard Stack

### Spike Tooling (what the spike scripts need to RUN — not production deps)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `cloakbrowser` | `==0.3.31` | Drive Google SERP fetches via stealth Chromium | D1 lock; verified on PyPI 2026-05-26 [VERIFIED: pypi.org/pypi/cloakbrowser/json] |
| `playwright` | `>=1.40` | Cloak's underlying engine; called via `from cloakbrowser import async_playwright` | Transitive of cloakbrowser; do NOT pin separately [VERIFIED: cloakbrowser 0.3.31 requires_dist] |
| `httpx[http2]` | `==0.28.1` | LLM router calls + visit-pass probes | Async, HTTP/2, supports `httpx-sse` for streaming TTFT measurement [VERIFIED: pypi.org/pypi/httpx/json] |
| `httpx-sse` | `>=0.4.0` | SSE stream chunk timing for LLM TTFT measurement | The cleanest way to time `data:` chunks against an OpenAI-compat router [CITED: github.com/florimondmanca/httpx-sse] |
| `selectolax` | `==0.4.10` | Parse Google SERP + catalog HTML; cheap JSON-LD grep | Brief 03 had `0.4.9`; PyPI latest is `0.4.10` (verified 2026-06-01) [VERIFIED: pypi.org/pypi/selectolax/json] |
| `pydantic` | `>=2.0` | Validate `labelled.jsonl` records during capture | Already part of Phase 2 stack; minor dep here [ASSUMED — verify Phase 2 lock] |
| `python` | `3.12` | Spike scripts | Project constraint (PROJECT.md "Tech stack — Python 3.12") |

**Installation (spike-only `pyproject.toml`):**
```bash
# Minimal spike env — Phase 2 will define the production pyproject.toml from scratch.
uv venv .venv && source .venv/bin/activate
uv pip install 'cloakbrowser==0.3.31' 'httpx[http2]==0.28.1' 'httpx-sse>=0.4.0' \
  'selectolax==0.4.10' 'pydantic>=2.0'
# Cloak ships its own pinned Chromium binary — pull on first import:
python -c "from cloakbrowser import install; install()"  # API to confirm in 01-01 task 1
```

**Verification commands run during research (2026-06-01):**
```bash
# PyPI version + upload date
curl -s "https://pypi.org/pypi/cloakbrowser/json" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['info']['version'])"
# → 0.3.31

# Docker Hub tag verification
curl -s "https://hub.docker.com/v2/repositories/cloakhq/cloakbrowser/tags/0.3.31/" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('last_updated'),d.get('full_size'))"
# → 2026-05-26T...  581915063 bytes (~582MB), arches: amd64, arm64

# Chromium binary release tag (GitHub)
curl -s "https://api.github.com/repos/CloakHQ/CloakBrowser/releases?per_page=1" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d[0]['tag_name'],d[0]['published_at'])"
# → chromium-v146.0.7680.177.5 2026-05-21T...
```

### Production Stack (deferred to Phase 2 — listed here so spike scripts don't accidentally diverge)

| Library | Version | Used in Phase 2 As |
|---------|---------|--------------------|
| `fastapi` | `>=0.115` | `/search`, `/health` endpoints [ASSUMED — Phase 2 picks] |
| `uvicorn` | `>=0.30` | ASGI server (`--loop asyncio --workers 1` always — D6) [VERIFIED: research SUMMARY §9] |
| `aiosqlite` | `>=0.20` | Cache backend (CACHE-01) [VERIFIED: research/04-fastapi-deploy.md §2] |
| `structlog` | `>=25.0` | Logging (OBS-03) [VERIFIED: PROJECT.md Constraints] |
| `asgi-correlation-id` | `>=4.3` | `X-Request-ID` middleware (OBS-04) [VERIFIED: PROJECT.md] |
| `extruct` | `0.18.0` | **DEFERRED** — D12 says hand-roll; spike 01-03 may flip this [CITED: pypi.org/pypi/extruct/json] |

### Alternatives Considered (and why the spike does NOT pursue them)

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Cloakbrowser | stock `playwright` | Stock Playwright fails Google fingerprint in <5 requests (brief 01 §Q1) — would invalidate the spike |
| `httpx-sse` for TTFT | raw `httpx.stream` with manual line splitting | Possible but `httpx-sse` parses `data:` SSE frames correctly; manual splitting is fragile across `\r\n\r\n` boundaries |
| `selectolax` | BeautifulSoup | 10x slower; brief 03 + PROJECT.md confirm selectolax |
| `extruct` for spike 01-03 | hand-rolled JSON-LD grep | The spike's job is to **decide** between them; brief 03 recommends hand-roll, spike must validate against the 10 captured fixtures |

## Package Legitimacy Audit

slopcheck v0.6.1 ran 2026-06-01 against the spike toolset.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `cloakbrowser` | PyPI 0.3.31 | 6 days (uploaded 2026-05-26) | low (niche) | github.com/CloakHQ/CloakBrowser | [OK] | Approved (D1 lock) |
| `httpx[http2]` | PyPI 0.28.1 | 6+ months | very high | github.com/encode/httpx | [OK] | Approved |
| `httpx-sse` | PyPI | mature | high | github.com/florimondmanca/httpx-sse | [OK] | Approved |
| `selectolax` | PyPI 0.4.10 | recent stable | high | github.com/rushter/selectolax | [OK] | Approved |
| `playwright` | PyPI | mature | very high | github.com/microsoft/playwright-python | [OK] | Approved |
| `pydantic` | PyPI 2.x | very mature | very high | github.com/pydantic/pydantic | [OK] | Approved |
| `aiosqlite` | PyPI | mature | very high | github.com/omnilib/aiosqlite | [OK] | Approved |
| `structlog` | PyPI 25.x | mature | very high | github.com/hynek/structlog | [OK] | Approved |
| `asgi-correlation-id` | PyPI | mature | high | github.com/snok/asgi-correlation-id | [OK] | Approved |
| `extruct` | PyPI 0.18.0 | mature | medium | github.com/scrapinghub/extruct | [OK] | Approved (only if D12 flips) |
| `fastapi` | PyPI | mature | extremely high | github.com/fastapi/fastapi | [OK] | Approved (Phase 2) |
| `uvicorn` | PyPI | mature | extremely high | github.com/encode/uvicorn | [OK] | Approved (Phase 2) |
| `respx` | PyPI 0.23.1 | mature | high | github.com/lundberg/respx | [OK] | Approved (Phase 2 testing) |
| `pytest` / `pytest-asyncio` | PyPI | extremely mature | extremely high | github.com/pytest-dev/* | [OK] | Approved |
| `tldextract` | PyPI | mature | very high | github.com/john-kurkowski/tldextract | [OK] | Approved (Phase 2 per-host sema) |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

All 15 packages cleared slopcheck. The spike scripts may install the spike-only subset; production deps are Phase 2's call.

## Architecture Patterns

### Spike System Architecture Diagram

```
                     Phase 1 Spike — 3 parallel investigations
                     ════════════════════════════════════════
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        ▼                              ▼                              ▼
  ┌───────────┐                ┌────────────────┐               ┌──────────────┐
  │ 01-01 Browser│              │ 01-02 LLM Router │             │ 01-03 Visit  │
  └─────┬─────┘                └────────┬───────┘               └──────┬───────┘
        │                               │                              │
        │ 1. docker manifest inspect    │ 1. curl /v1/models           │ 1. headed browser
        │    cloakhq/cloakbrowser:0.3.31│    (bearer auth)             │    each of top-10 stores
        │                               │                              │
        │ 2. python -m spike.browser    │ 2. POST /v1/chat/completions │ 2. capture raw HTML →
        │    - cold container boot      │    response_format=json_object│    tests/fixtures/catalog/
        │    - cold ephemeral context   │    measure end-to-end ms     │
        │    - fetch google?pws=0       │                              │ 3. for each: run
        │    - detect interstitial      │ 3. fire same body twice;     │    selectolax grep
        │    - capture SERP HTML →      │    Δlatency = KV-cache evidence│   script[type="application/ld+json"]
        │    tests/fixtures/serp/       │                              │    + OG product:price:amount meta
        │                               │ 4. fire 1, 2, 4, 8 parallel; │
        │ 3. kill chromium pid;         │    observe 200/429/503 mix   │ 4. for each fixture:
        │    is_connected()→false?     │                              │    httpx GET with DEFAULT_HEADERS
        │                               │ 5. test response_format=     │    record status (200/403/timeout)
        │ 4. docker network disconnect  │    {type:json_object}        │
        │    cloak; is_connected()?     │    against malformed-input   │ 5. classify per fixture:
        │                               │    → expect 400              │    JSON-LD-sufficient / OG-only /
        │ 5. set marker cookie in ctx1; │    invalid_structured_output │    needs-microdata / blob-JS-only
        │    new_context() ctx2;        │                              │
        │    observe no cookie in ctx2  │ 6. hand-label 30-50 cards    │ 6. D12 verdict line in SPIKE.md:
        │                               │    from 01-01 SERPs →        │    GO hand-roll / NEEDS extruct
        │                               │    labelled.jsonl            │
        ▼                               ▼                              ▼
  SPIKE.md §Browser              SPIKE.md §LLM                  SPIKE.md §Visit
  Status: GO | NO-GO            Status: GO | NO-GO            Status: GO | NO-GO
        │                               │                              │
        └──────────────────────────────┬┴──────────────────────────────┘
                                       ▼
                              SPIKE.md §D12 Decision
                              SPIKE.md §Risks
                              Top-level Status: GO | NO-GO | NEEDS-PIVOT
                                       │
                                       ▼
                              Phase 2 plan-phase consumes
```

### Recommended Project Structure (this phase produces only spike artifacts)

```
artiscrapper/                            # already exists (greenfield: no src yet)
├── .planning/
│   ├── SPIKE.md                         # ← NEW — Phase 1 deliverable, Go/No-Go for D1/D3/D8/D10/D11/D12
│   └── phases/01-spike-empirical-validation/
│       ├── 01-RESEARCH.md               # ← THIS FILE
│       ├── 01-VALIDATION.md             # ← generated by /gsd:nyquist
│       └── 01-PLAN.md (+ task plans)    # ← generated by /gsd:plan-phase
├── tests/
│   └── fixtures/
│       ├── serp/                        # ← NEW — 5-10 raw Google SERP HTML files
│       │   ├── 01-pelota_playera_quico.html
│       │   ├── 02-filtro_aceite_ford_focus.html
│       │   ├── 03-...
│       │   └── README.md                # which query produced which fixture, capture date
│       ├── catalog/                     # ← NEW — 10 raw catalog PDP HTML files
│       │   ├── falabella_ar/            # one subdir per host (avoid filename collisions)
│       │   │   └── product-01.html
│       │   ├── tiendanube_casasusy/
│       │   │   └── product-01.html
│       │   ├── mayoristafrog/
│       │   │   └── product-01.html
│       │   └── ... (10 hosts total — see Per-host strategy table below)
│       └── llm/
│           └── labelled.jsonl           # ← NEW — 30-50 hand-labelled SERP cards
├── scripts/
│   └── spike/                           # ← NEW — throwaway-OK Python scripts, NOT production code
│       ├── 01_verify_cloak_tag.sh       # docker manifest inspect
│       ├── 02_browser_smoke.py          # cold-boot + pws=0 + interstitial detect + cookie isolation
│       ├── 03_death_modes.sh            # kill / network drop / OOM provocation
│       ├── 04_capture_serps.py          # drive N queries, save raw HTML
│       ├── 05_router_probe.py           # /v1/models + /v1/chat/completions + TTFT + KV-cache + concurrency
│       ├── 06_capture_catalog.py        # drive 10 hosts headed, save raw HTML
│       ├── 07_extract_fixture.py        # one-liner: load fixture, run hand-rolled JSON-LD + OG, print result
│       ├── 08_falabella_403_rate.py     # httpx N=10 to Falabella, record outcomes
│       └── 09_label_cards.py            # interactive labeller for labelled.jsonl
└── pyproject.toml.spike                  # ← NEW, throwaway — Phase 2 writes the real pyproject.toml
```

**Why a separate `scripts/spike/` (vs `src/`):** Phase 1 explicitly produces NO production code (ROADMAP §Phase 1). The scripts dir is throwaway — Phase 2's `src/` layout is its own decision. Keeping scripts isolated prevents accidental imports into the eventual production package.

### Pattern 1: Cold-container browser smoke (spike 01-01)

**What:** Boot a fresh Cloak container, open exactly one ephemeral context, fetch `google.com/search?q=...&pws=0&hl=es&gl=ar`, snapshot the response. Detect the consent interstitial (if any). Run twice with different ephemeral contexts and confirm cookies don't leak.

**When to use:** Every time the planner needs to verify a Cloak invariant — cold boot, pws=0 behavior, ephemeral context isolation.

**Example (`scripts/spike/02_browser_smoke.py`):**
```python
# Source: cloakbrowser 0.3.31 README usage + brief 01 "Recommended pattern code"
# https://github.com/CloakHQ/CloakBrowser  (HIGH confidence)
import asyncio, sys
from pathlib import Path
from cloakbrowser import async_playwright

GOOGLE = "https://www.google.com/search?q={q}&hl=es&gl=ar&pws=0&safe=off"
QUERIES = [
    "pelota playera quico", "filtro aceite ford focus", "amortiguador trasero peugeot 208",
    "buja ngk bosch", "correa distribucion fiat cronos", "disco freno renault sandero",
    "rotula direccion vw gol", "kit embrague chevrolet onix", "termostato corsa classic",
    "balatas brembo toyota hilux",
]

INTERSTITIAL_MARKERS = [
    'id="L2AGLb"',                   # "I agree" button on consent screen (EU + ES variant)
    'href="https://policies.google.com',  # consent screen meta
    'aria-label="Antes de continuar',     # "Before you continue" ES
    '/sorry/index',                       # block challenge
    'g-recaptcha',                        # captcha
]

async def main(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])
        # NOTE: confirm at 01-01 task 1 whether `async_playwright` factory is exposed at top level
        # in cloakbrowser 0.3.31 or behind cloakbrowser.async_api. The PyPI README has the signature.
        for i, q in enumerate(QUERIES[:10], start=1):
            ctx = await browser.new_context(
                locale="es-AR", timezone_id="America/Argentina/Buenos_Aires",
                viewport={"width": 1366, "height": 768},
            )
            page = await ctx.new_page()
            url = GOOGLE.format(q=q.replace(" ", "+"))
            await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            html = await page.content()
            hits = [m for m in INTERSTITIAL_MARKERS if m in html]
            slug = q.replace(" ", "_").replace("/", "_")
            (out_dir / f"{i:02d}-{slug}.html").write_text(html, encoding="utf-8")
            print(f"[{i:02d}] q='{q}' interstitial_hits={hits} bytes={len(html)}")
            await page.close()
            await ctx.close()
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/serp")))
```

**Empirical answers the planner needs to record in SPIKE.md §Browser from this script:**
- For each query: did `INTERSTITIAL_MARKERS` match? (per-query line)
- File sizes (sanity check — a normal SERP is 200-800 KB; a consent page is ~30 KB)
- Wall-clock per query (`time` the script; record p50/p95)

### Pattern 2: Death-mode provocation (spike 01-01 task 3)

**What:** Kill the Chromium subprocess underneath Cloak via various mechanisms; observe whether `browser.is_connected()` flips to `false` for each.

**Concrete invocations:**
```bash
# Death-mode 1: SIGKILL the Chromium process
# Find the chromium pid INSIDE the Cloak container (or local process if running outside Docker)
# Local Python venv (most likely Phase 1 spike): chromium is a child of the python script.
ps --ppid $(pgrep -f spike/02_browser_smoke.py | head -1) -o pid,cmd
# Then kill:
kill -KILL <chromium_pid>
# Inside the script, the next call to browser.is_connected() should return False.

# Death-mode 2: stop Chromium with SIGSTOP (process still exists but unresponsive)
# - is_connected() may return True for a brief window — this is the OOM-like case
kill -STOP <chromium_pid>
# Wait 5s; call is_connected(); record result. Then SIGCONT.
kill -CONT <chromium_pid>

# Death-mode 3: network drop (if Cloak runs in Docker — not necessary for Phase 1 spike outside Docker)
# docker network disconnect <network_name> cloak-container
# is_connected() flip expected within ~30s when CDP heartbeat times out.

# Death-mode 4: OOM simulation
# In Docker: docker update --memory 200m cloak-container ; then drive a memory-heavy page
# Outside Docker: skip; OOM is rare and Docker-specific.
```

**Planner records in SPIKE.md §Browser:**
| Death mode | Trigger | `is_connected()` flips to false? | Detection lag |
|---|---|---|---|
| SIGKILL Chromium | `kill -KILL pid` | YES / NO | __s |
| SIGSTOP Chromium | `kill -STOP pid` | YES / NO | __s |
| Network drop | `iptables -A OUTPUT -d 127.0.0.1 -p tcp --dport <cdp_port> -j DROP` | YES / NO | __s |
| OOM (Docker) | `docker update --memory 200m` + heavy page | YES / NO | __s |

Any "NO" row is a CRITICAL finding — Phase 2's `_recycle_browser_loop` cannot rely on `is_connected()` for that failure mode, and the planner must add a secondary heartbeat (e.g. periodic `page.evaluate("1")`).

### Pattern 3: Ephemeral context cookie isolation (spike 01-01 task 4)

**What:** Set a marker cookie in context A, close it, open context B, navigate, observe header on second fetch. If the marker cookie appears in B's request → ephemeral context isolation is broken; Cloak's D8 promise fails.

**Example:**
```python
# Set marker in ctx1
ctx1 = await browser.new_context(locale="es-AR")
page1 = await ctx1.new_page()
await page1.goto("https://www.google.com/")
await ctx1.add_cookies([{"name":"artispike_marker","value":"42","domain":".google.com","path":"/"}])
cookies1 = await ctx1.cookies("https://www.google.com/")
print("ctx1 cookies after set:", [c["name"] for c in cookies1])
await ctx1.close()

# New ephemeral context — must NOT see marker
ctx2 = await browser.new_context(locale="es-AR")
page2 = await ctx2.new_page()
# Use page.route to inspect the request headers actually sent
captured_headers = {}
async def on_request(req):
    captured_headers[req.url] = req.headers
page2.on("request", on_request)
await page2.goto("https://www.google.com/")
cookies2 = await ctx2.cookies("https://www.google.com/")
print("ctx2 cookies after nav:", [c["name"] for c in cookies2])
# Check the captured Cookie header for artispike_marker
g_url = next((u for u in captured_headers if "google.com" in u), None)
print("ctx2 request Cookie header:", captured_headers.get(g_url, {}).get("cookie", "(none)"))
assert "artispike_marker" not in (captured_headers.get(g_url, {}).get("cookie") or "")
```

**Pass/fail criterion:** `artispike_marker` MUST NOT appear in ctx2's `Cookie` header or `ctx2.cookies()`. If it does, D8's "ephemeral isolation" promise is violated and Phase 2 needs a different cookie-clear strategy.

### Pattern 4: Router endpoint probe (spike 01-02)

**What:** Confirm endpoint shape, list models, time a single completion, time two back-to-back identical calls (KV-cache evidence), fire 2/4/8 in parallel (concurrency limit).

**Token retrieval (one-time, write to `.env.spike` then source):**
```bash
TOKEN="$(grep '^ROUTER_BEARER_TOKEN=' /home/luis/proyectos/local-llms/.env | cut -d= -f2-)"
test -n "$TOKEN" && echo "TOKEN=$TOKEN" > /home/luis/proyectos/artiscrapper/.env.spike
chmod 600 /home/luis/proyectos/artiscrapper/.env.spike
```

**Sub-step 1 — Endpoint discovery (HIGH confidence, verified live 2026-06-01):**
```bash
# /v1/models — confirmed 200 OK with bearer; payload is OpenAI-compat
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3210/v1/models | python3 -m json.tool
# Expect: data[].id includes "chat-local", "qwen2.5-7b-instruct-q4km", "qwen2.5-7b-instruct-awq",
# "big-cloud", "gpt-oss:120b-cloud", "gpt-oss:20b-cloud", and embedding/rerank models.

# /healthz (not /health — see local-llms README "Instalacion rapida"; healthz is the canonical name)
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3210/healthz
```
**Recorded in SPIKE.md §LLM:** the list of chat-capable models + which one is the default for our use case (`chat-local`). Confidence HIGH; verified live during research.

**Sub-step 2 — One-shot completion + JSON mode:**
```bash
curl -s -i -X POST "http://127.0.0.1:3210/v1/chat/completions" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"model":"chat-local","messages":[{"role":"user","content":"Devuelve {\"ok\":true}"}],"response_format":{"type":"json_object"},"temperature":0.0,"max_tokens":40}' \
  | tee /tmp/router_one_shot.txt
# Capture: response time (use `time curl ...`), X-Model-Backend header, X-Cost-Cents header,
# choices[0].message.content, finish_reason, usage.{prompt_tokens, completion_tokens}
```

**Sub-step 3 — TTFT measurement via SSE streaming (Python + httpx-sse):**
```python
# scripts/spike/05_router_probe.py (TTFT section)
import time, httpx
from httpx_sse import connect_sse

TOKEN = open("/home/luis/proyectos/artiscrapper/.env.spike").read().split("=",1)[1].strip()
url = "http://127.0.0.1:3210/v1/chat/completions"
hdrs = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
body = {
    "model": "chat-local",
    "messages": [{"role":"system","content":"Sos un clasificador..."}, {"role":"user","content":"ok"}],
    "stream": True, "temperature": 0.0, "max_tokens": 80,
}
with httpx.Client(timeout=15.0) as client:
    t0 = time.perf_counter()
    with connect_sse(client, "POST", url, headers=hdrs, json=body) as event_source:
        first = None
        for sse in event_source.iter_sse():
            if sse.data == "[DONE]": break
            if first is None:
                first = time.perf_counter()
                print(f"TTFT={first-t0:.3f}s")
        total = time.perf_counter() - t0
        print(f"total={total:.3f}s")
```
**Run 5 times back-to-back, record p50/p95 TTFT and total wall-clock.** Then run with `stream:false` and time end-to-end for comparison.

**Sub-step 4 — KV-cache reuse evidence:**
```python
# Same body twice; if KV cache works, second call's TTFT drops.
# For Ollama backend (chat-local routes here), OLLAMA_KEEP_ALIVE=-1 keeps the model warm
# but Ollama does NOT preserve KV across REQUESTS by default — it preserves the loaded model.
# Real KV-prompt-cache reuse would require explicit cache_prompt=true at Ollama level, NOT exposed at /v1.
# So expect: second-call TTFT is similar (warm model) but NOT dramatically lower (no prompt cache).
# Record exactly what you see; this is the spike's job.
import time, httpx
TOKEN = open("/home/luis/proyectos/artiscrapper/.env.spike").read().split("=",1)[1].strip()
url = "http://127.0.0.1:3210/v1/chat/completions"
hdrs = {"Authorization": f"Bearer {TOKEN}", "Content-Type":"application/json"}
SYSTEM = "Sos un clasificador..." * 30  # long enough to make prompt eval measurable
body = {"model":"chat-local","messages":[{"role":"system","content":SYSTEM},{"role":"user","content":"ok"}],"temperature":0.0,"max_tokens":40}

for i in range(3):
    t0 = time.perf_counter()
    r = httpx.post(url, headers=hdrs, json=body, timeout=15.0)
    print(f"call {i+1}: {time.perf_counter()-t0:.3f}s  status={r.status_code}")
```
**Record:** call 1 latency, call 2 latency, call 3 latency. If call 2/3 are NOT meaningfully lower than call 1, the router does NOT do prompt KV cache reuse across requests, and Phase 2's prompt design must assume each call pays full prompt eval. (Brief 02 §Q4 already assumed this; spike confirms it.)

**Sub-step 5 — Concurrency limit discovery:**
```python
# Fire 8 parallel identical short requests; record how many succeed, how many queue, how many 429/503.
import asyncio, time, httpx
TOKEN = open("/home/luis/proyectos/artiscrapper/.env.spike").read().split("=",1)[1].strip()
url = "http://127.0.0.1:3210/v1/chat/completions"
hdrs = {"Authorization": f"Bearer {TOKEN}", "Content-Type":"application/json"}
body = {"model":"chat-local","messages":[{"role":"user","content":"ok"}],"temperature":0.0,"max_tokens":10}

async def fire(n: int):
    async with httpx.AsyncClient(timeout=60.0) as client:
        t0 = time.perf_counter()
        async def one(i):
            t = time.perf_counter()
            r = await client.post(url, headers=hdrs, json=body)
            return i, r.status_code, r.headers.get("retry-after"), time.perf_counter()-t
        results = await asyncio.gather(*(one(i) for i in range(n)), return_exceptions=True)
        print(f"N={n} elapsed={time.perf_counter()-t0:.2f}s")
        for r in results:
            print(" ", r)

for n in (2, 4, 8):
    asyncio.run(fire(n))
```
**Record:** at N=2 expect all 200 + no queuing; at N=4 expect 2 immediate + 2 queued (waiting up to `queue_max_wait_ms=30000`); at N=8 likely some 429/503. The exact behavior **is the spike's answer to D10**. Use the result to choose `LLM_CONCURRENCY` env default for Phase 2 (almost certainly **2**, possibly 4 if queueing absorbs cleanly).

### Pattern 5: Catalog fixture sweep + extraction probe (spike 01-03)

**What:** For each of 10 target AR catalog hosts, headed-browse to one real product detail page, capture raw HTML, then run a hand-rolled selectolax extractor over the captured HTML. Classify each fixture as `JSON-LD-sufficient`, `OG-only`, `microdata-only`, or `blob-JS-only`. The mix of classifications determines D12.

**Target hosts (per ROADMAP Phase 1 + brief 03 per-host table — Mercadolibre excluded per VISIT-08):**

| # | Host | Platform | Expected extraction tier (brief 03) |
|---|------|----------|-------------------------------------|
| 1 | `mayoristafrog.com.ar` | custom / PrestaShop? | unknown — fixture decides |
| 2 | `casasusy.com.ar` | Tiendanube (likely) | JSON-LD-sufficient |
| 3 | `falabella.com.ar` | VTEX/proprietary | JSON-LD-sufficient (but 403 risk on httpx) |
| 4 | `romero-jugueteria.com.ar` | likely Tiendanube | JSON-LD-sufficient |
| 5 | one Tiendanube store (`*.mitiendanube.com`) | Tiendanube | JSON-LD-sufficient |
| 6 | one VTEX store (`musimundo.com` or `garbarino.com`) | VTEX | JSON-LD-sufficient |
| 7 | `walmart.com.ar` | proprietary | JSON-LD-sufficient |
| 8 | one generic Shopify (`*.myshopify.com`) | Shopify | JSON-LD-sufficient (89% Product schema globally) |
| 9 | "Distribuidora Romero" (per ROADMAP — find via Google) | unknown — discover during spike | unknown |
| 10 | a small custom catalog discovered from SERPs in 01-01 | varies | unknown — the long-tail test case |

**Capture script (`scripts/spike/06_capture_catalog.py`):** drives Cloak to each PDP found by clicking through a SERP fixture from 01-01 (or hand-curated URLs in a `targets.txt`), saves raw HTML.

**Hand-rolled extractor probe (`scripts/spike/07_extract_fixture.py`):**
```python
# Loads a single fixture, runs hand-rolled JSON-LD + OG + microdata extraction, prints result.
# This IS the "decide D12" probe — if this script returns a Product on 9/10 fixtures, hand-roll wins.
import json, sys
from pathlib import Path
from selectolax.parser import HTMLParser

def extract_jsonld_product(tree: HTMLParser) -> dict | None:
    for script in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text())
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        # flatten @graph wrappers
        flat = []
        for it in items:
            if isinstance(it, dict) and "@graph" in it:
                flat.extend(it["@graph"])
            else:
                flat.append(it)
        for it in flat:
            if not isinstance(it, dict): continue
            t = it.get("@type")
            if t == "Product" or (isinstance(t, list) and "Product" in t):
                return it
    return None

def extract_og_product(tree: HTMLParser) -> dict | None:
    metas = {}
    for m in tree.css("meta[property]"):
        prop = m.attributes.get("property"); content = m.attributes.get("content")
        if prop and content: metas[prop] = content
    if "product:price:amount" in metas:
        return {
            "price": metas["product:price:amount"],
            "currency": metas.get("product:price:currency", "ARS"),
            "name": metas.get("og:title"),
            "image": metas.get("og:image"),
        }
    return None

def extract_microdata_product(tree: HTMLParser) -> dict | None:
    root = tree.css_first("[itemtype$='/Product']")
    if root is None: return None
    out = {}
    for el in root.css("[itemprop]"):
        prop = el.attributes.get("itemprop")
        val = el.attributes.get("content") or el.text(strip=True)
        if prop and val and prop not in out: out[prop] = val
    return out or None

def classify(html: str) -> tuple[str, dict | None]:
    tree = HTMLParser(html)
    jsonld = extract_jsonld_product(tree)
    og = extract_og_product(tree)
    micro = extract_microdata_product(tree)
    if jsonld and jsonld.get("offers"): return ("jsonld-sufficient", jsonld)
    if og and og.get("price"): return ("og-only", og)
    if micro and micro.get("price"): return ("microdata-only", micro)
    # Last resort: regex over text body looking for AR price
    import re
    m = re.search(r'\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)', html)
    if m: return ("regex-fallback", {"price_text": m.group(0)})
    return ("blob-JS-only", None)

if __name__ == "__main__":
    p = Path(sys.argv[1])
    cls, data = classify(p.read_text(encoding="utf-8"))
    print(f"{p.name}: {cls}")
    if data: print(json.dumps(data, ensure_ascii=False, indent=2)[:600])
```

**Per-fixture line in SPIKE.md §Visit:**
```
fixture                              classification          extracted_price  extracted_name
falabella_ar/product-01.html         jsonld-sufficient       $ 18.999         Filtro de aceite Mahle
mayoristafrog/product-01.html        regex-fallback          $ 1.200          (none)
...
```

**D12 decision rule (write into SPIKE.md):**
- If **≥8/10 fixtures classify as `jsonld-sufficient` or `og-only`** → **GO hand-roll** (D12 stays locked).
- If **3+ fixtures classify as `microdata-only` or `blob-JS-only`** → **NEEDS-PIVOT to extruct** (D12 flips; Phase 2 plan 02-02 must add `extruct==0.18.0`).
- Borderline (4-7/10 sufficient): record as `NEEDS-PIVOT` and document in Risks; the planner adds a Phase 2 task to revisit with more samples.

### Pattern 6: Falabella 403 rate (spike 01-03 task 4)

**Realistic Chromium-146 headers (drop-in from brief 03, copy verbatim):**
```python
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.6",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Chromium";v="146", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.google.com/",
}
```

**Probe (`scripts/spike/08_falabella_403_rate.py`):**
```python
# Fire 10 sequential httpx GETs at 10 different Falabella PDP URLs (pulled from 01-01 SERPs).
# Record outcomes. ≥4/10 403s → "Akamai live, expect visit_failed flag at MVP" per brief 03.
import asyncio, httpx, time
from pathlib import Path

URLS = Path("scripts/spike/falabella_urls.txt").read_text().strip().splitlines()
HEADERS = {...}  # paste DEFAULT_HEADERS above

async def main():
    async with httpx.AsyncClient(http2=True, headers=HEADERS, follow_redirects=True, timeout=10.0) as client:
        for i, url in enumerate(URLS, 1):
            t0 = time.perf_counter()
            try:
                r = await client.get(url)
                elapsed = time.perf_counter()-t0
                final = str(r.url)
                print(f"[{i:02d}] status={r.status_code} elapsed={elapsed:.2f}s final={final} bytes={len(r.content)}")
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                print(f"[{i:02d}] ERR {type(e).__name__}: {e}")

asyncio.run(main())
```

**Recorded in SPIKE.md §Visit (Falabella row):**
| Host | N | 200 | 403 | 5xx | timeout | conclusion |
|---|---|---|---|---|---|---|
| falabella.com.ar | 10 | __ | __ | __ | __ | (`visit_failed` rate at MVP) |
| mayoristafrog.com.ar | 10 | __ | __ | __ | __ | |
| romero-jugueteria.com.ar | 10 | __ | __ | __ | __ | |

### Pattern 7: `labelled.jsonl` schema (spike 01-02 task 6)

**One record per line. Schema (Pydantic, ship under `scripts/spike/labels.py`):**
```python
from pydantic import BaseModel, Field
from typing import Literal

class CandidateInput(BaseModel):
    """The card as it would arrive at the LLM step — exact shape the LLM sees."""
    title: str
    url: str
    snippet: str | None = None
    price_in_card: str | None = None       # e.g. "$ 8.500" — preserved as raw string from SERP

class LabelledCandidate(BaseModel):
    """One labelled SERP card, ready for prompt-regression eval."""
    id: str                                # stable id, e.g. "serp01-card05"
    source_fixture: str                    # "01-pelota_playera_quico.html"
    candidate: CandidateInput
    expected_is_product: bool
    expected_confidence_min: float = Field(ge=0.0, le=1.0)  # if model says < this, regression FAIL
    expected_store_hint: str | None = None
    expected_freshness_signal: Literal["live_marketplace","static_catalog","blog","unknown"]
    expected_price_hint: float | None = None
    notes: str | None = None               # Luis's reasoning, in Spanish or English mix is fine
```

**Example record (one line per record in `tests/fixtures/llm/labelled.jsonl`):**
```json
{"id":"serp01-card01","source_fixture":"01-pelota_playera_quico.html","candidate":{"title":"Pelota Playera Quico - $ 1.200","url":"https://www.mercadolibre.com.ar/MLA-99999","snippet":"Envío gratis. +500 vendidos.","price_in_card":"$ 1.200"},"expected_is_product":true,"expected_confidence_min":0.85,"expected_store_hint":"Mercadolibre","expected_freshness_signal":"live_marketplace","expected_price_hint":1200.0,"notes":"Card MELI con precio claro"}
```

**Target: 30-50 records.** Mix across positive (real product), negative (blog/tutorial/wikipedia), and ambiguous (link-aggregator with no price). Luis hand-labels these during 01-02 task 6 by walking the 5-10 SERP fixtures captured in 01-01.

**Validation script (`scripts/spike/09_label_cards.py --validate`):** loads the jsonl, runs `LabelledCandidate.model_validate_json()` on each line, prints first failure. Zero failures = AC-5 met.

### Anti-Patterns to Avoid

- **Don't write Phase 2 code in Phase 1.** Spike scripts under `scripts/spike/` are throwaway — no FastAPI lifespan, no Pydantic models for production payloads, no Dockerfile. ROADMAP §Phase 1 explicit.
- **Don't probe the live router in a tight loop without throttle.** The router has per-bearer rate-limit + circuit breaker (local-llms README); a runaway spike script can trip the breaker for Luis's other consumers (Open WebUI, n8n). Pause 200ms between probe calls.
- **Don't run all 3 spikes in parallel against the same VPS IP.** Spike 01-01 hits Google ~10 times; spike 01-03 hits 10 stores. Running them concurrently multiplies the IP-block surface. Serialize unless wall-clock matters (it shouldn't — Phase 1 is 1 day).
- **Don't commit `.env.spike`.** Add `.env.spike` to `.gitignore` BEFORE running the token-extraction step. The bearer token is a secret.
- **Don't trust a single Falabella 200 as "Akamai is friendly".** Brief 03 + project-memory `feedback_empirical_retest_after_default_changes.md` both warn: N≥5 attempts before declaring a rate.
- **Don't capture SERP HTML with `--workers 1` removed.** D6 still applies — spike scripts that import cloakbrowser must use `asyncio` event loop (not uvloop). `python -m scripts.spike.02_browser_smoke` defaults to asyncio; do not introduce `uvloop` anywhere.
- **Don't skip the cookie-isolation test.** Even if "everyone knows" `new_context()` is isolated, the spike's whole job is to verify "everyone knows" is empirically true for THIS Cloak version on THIS host.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cloak Docker tag check | curl-and-parse-JSON-by-hand | `docker manifest inspect cloakhq/cloakbrowser:0.3.31` then `curl` Hub API for cross-check | manifest inspect is the canonical pin verification; matches what `docker pull` would do |
| TTFT timing | manual `time` + grep | `httpx-sse` + `time.perf_counter()` | SSE frame parsing is fiddly; `httpx-sse` handles `\r\n\r\n` boundaries correctly |
| JSON-LD parsing during spike | `regex` for `<script type="application/ld+json">` | `selectolax.HTMLParser(...).css('script[type="application/ld+json"]')` + `json.loads()` | Regex on JSON-in-HTML is the classic foot-gun; selectolax is already in stack |
| Schema validation for `labelled.jsonl` | dict-comparison-by-hand | `pydantic.BaseModel.model_validate_json()` | Catches type drift on capture; same Pydantic the Phase 2 production code uses |
| Falabella URL discovery | manual browsing | Pull URLs from spike 01-01 SERP fixtures with a grep | Reuses spike output; deterministic for replay |
| AR price regex | guess from one fixture | `r'\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)'` (brief 03 verbatim) | Already validated against v1 SERPs; AR uses point-thousands + comma-decimal |

**Key insight:** Phase 1 produces evidence, not code. Every "Don't hand-roll" recommendation above is about not wasting spike-day effort on infrastructure that's already in the stack.

## Runtime State Inventory

**Not applicable.** Phase 1 is greenfield — no rename/refactor/migration. No prior runtime state to inventory. Search-and-replace, ORM keys, OS-registered tasks: none.

The only "stored state" to be aware of is **`local-llms-router`'s rate-limit + circuit-breaker counters** (per-bearer, in Valkey). Spike scripts that hammer the router can trip these:
- Per-bearer rate-limit: configured in `local-llms/.env`, exposed via `/metrics`. Probe scripts must throttle.
- Circuit breaker: opens on backend 5xx/timeout streaks. If the spike trips it, n8n's chat-local calls will get 503 until the breaker closes (~30s). **Luis is the only consumer; coordinate.**

## Common Pitfalls

### Pitfall 1: Cloak's PyPI entry point differs from research brief
**What goes wrong:** Research brief 01 cites `from cloakbrowser import async_playwright`. Cloak 0.3.31's actual public API may instead be `from cloakbrowser.async_api import async_playwright` or `from playwright.async_api import async_playwright` (post-import-of-cloakbrowser monkey-patch). Wrong import path = `ImportError` and the spike starts with a stack trace.
**Why it happens:** Cloak ships its own wrapped Playwright; the wrap point is library-version-specific.
**How to avoid:** Phase 1 task 1 (very first spike step) is `python -c "import cloakbrowser; print(dir(cloakbrowser))"` + `python -c "from cloakbrowser import async_playwright; print('ok')"`. If the second fails, fall back to `from playwright.async_api import async_playwright` and re-test that Cloak's stealth patches activated (verify via `navigator.webdriver === undefined` JS evaluation on a test page).
**Warning signs:** Spike script fails on import; or imports succeed but `navigator.webdriver` reads as `true` in a test eval.

### Pitfall 2: `pws=0` triggers the EU consent screen
**What goes wrong:** `pws=0` disables personalization but on a cold-context fetch from an EU/US-jurisdiction VPS, Google may still serve the consent interstitial (`id="L2AGLb"`) regardless. Phase 1 must detect this; if it fires, Phase 2's `build_serp_url()` needs a "click I agree" first-fetch warmup (or a pre-set `CONSENT=YES+...` cookie).
**Why it happens:** Consent screens are jurisdiction-driven (VPS IP geo), not user-account-driven. `pws=0` doesn't dismiss them.
**How to avoid:** The interstitial-marker scan in `scripts/spike/02_browser_smoke.py` is the detector. If ANY of `INTERSTITIAL_MARKERS` hits, record it in SPIKE.md §Browser as `pws=0_interstitial_observed: YES` and flag Phase 2 plan 02-01 to add a cookie-banner-dismissal step.
**Warning signs:** SERP HTML is ~30 KB instead of 200-800 KB; no `<h3>` elements present; URL still on `consent.google.com/*`.

### Pitfall 3: KV-cache is conflated with model-keep-alive
**What goes wrong:** Brief 02 says "measure with two back-to-back identical calls". The danger is conflating **model-keep-alive** (Ollama `OLLAMA_KEEP_ALIVE=-1` keeps weights in VRAM) with **prompt-KV-cache reuse** (skipping prompt eval on identical-prefix prompts). The former is already configured; the latter is NOT exposed at the OpenAI-compat surface. Two identical calls will both pay full prompt eval — that's a wash, not a "cache miss".
**Why it happens:** Ollama's prompt-cache (a recent feature, `cache_prompt`) is per-session and not surfaced through OpenAI `/v1/chat/completions`.
**How to avoid:** Spike 01-02 sub-step 4 should record latency for 3 back-to-back calls + a 4th call with a DIFFERENT system prompt. If call 2/3/4 are within ~10% of each other, **there is no prompt KV cache reuse** at our integration point. That's the truth — Phase 2's prompt design (brief 02 §Q4) must assume each call pays full prompt eval.
**Warning signs:** Calls 2 and 3 latency identical to call 1; first-token-to-output-complete fraction doesn't shrink on repeats.

### Pitfall 4: Confusing per-bearer rate-limit with per-model concurrency
**What goes wrong:** `models.yaml chat-local.concurrency: 2` controls the **per-bearer-per-model** dispatch cap inside the router. **`OLLAMA_NUM_PARALLEL=2`** is the Ollama backend's parallelism. **The router's per-bearer rate-limit** (configured in `.env`) is a token-bucket on request count. Three different caps; a single sustained burst can hit any of them with different error shapes (queued vs 429 vs 503).
**Why it happens:** Layered defense.
**How to avoid:** Spike 01-02 sub-step 5 should record HTTP status + `Retry-After` header for each parallel call at N=2/4/8. Map the error mode (429 = rate-limit, 503 = breaker, queue exhaustion = `queue_max_wait_ms` exceeded).
**Warning signs:** All N parallel calls succeed when N>2 → router is queuing (`queue_max_wait_ms=30000`) and `LLM_CONCURRENCY=4` may work but is silently latency-padded.

### Pitfall 5: Falabella 403 misread as "always blocks httpx"
**What goes wrong:** A single 403 on Falabella does not mean Akamai always blocks httpx. Akamai may rate-limit by IP-burst; the second request 30s later may pass. Recording "Falabella: 403" with N=1 is misleading.
**Why it happens:** Akamai/Imperva backoff windows are non-deterministic from outside.
**How to avoid:** N≥10 requests, spread over ≥60s. Record per-attempt status + final URL (redirect) + body size. The conclusion in SPIKE.md is a ratio (e.g. "8/10 403", "3/10 200, 7/10 403"), not a binary.
**Warning signs:** SPIKE.md §Visit says "Falabella: blocked" without a sample size.

### Pitfall 6: Spike scripts depend on Phase 2 code that doesn't exist yet
**What goes wrong:** Mid-spike, a script tries to import from `artiscrapper.parser` or `artiscrapper.cache` — but Phase 2 hasn't written those modules yet. Result: spike work pollutes Phase 2's eventual API surface, or spike scripts break.
**Why it happens:** Muscle memory from working on a non-greenfield codebase.
**How to avoid:** Spike scripts live in `scripts/spike/` and import ONLY from third-party deps (`cloakbrowser`, `httpx`, `selectolax`, `pydantic`). Each script is a self-contained `__main__`. **Phase 2 may copy patterns from spike scripts but does not import them.**
**Warning signs:** A spike script tries to `from artiscrapper.something import ...`.

### Pitfall 7: Docker Hub anonymous-pull rate-limit during spike
**What goes wrong:** Verifying `cloakhq/cloakbrowser:0.3.31` with `docker manifest inspect` or `docker pull` from an anonymous account hits Docker Hub's 100-pull/6h rate-limit if the spike day involves multiple rebuilds.
**Why it happens:** Anonymous Docker Hub pulls share an IP quota.
**How to avoid:** (a) Prefer the Hub HTTP API (`curl -s https://hub.docker.com/v2/repositories/cloakhq/cloakbrowser/tags/0.3.31/`) for tag existence verification — no pull quota consumed. (b) If `docker pull` is genuinely needed, use a logged-in Docker Hub account (`docker login`) — authenticated quota is 200/6h. (c) For the spike, **tag verification ≠ image pull**. Verify via API; pull only if Phase 2's eventual Dockerfile build needs it.
**Warning signs:** `toomanyrequests: You have reached your pull rate limit` error.

### Pitfall 8: `local-llms-router` unreachable from a different dev box
**What goes wrong:** The orchestrator brief warns: "What if `local-llms-router` is on the user's LAN and not always reachable from the dev box?" The router binds to `127.0.0.1:3210` (verified via `docker ps`). Spike scripts that hardcode `127.0.0.1:3210` only work on the host running the router.
**Why it happens:** Loopback binding by default.
**How to avoid:** Make the spike scripts read `LLM_ROUTER_URL` from env (default `http://127.0.0.1:3210`). If the spike runs on a different machine, set `LLM_ROUTER_URL=http://<vps-ip>:3210` AND ensure Traefik or a SSH tunnel exposes it. Document the env var in `scripts/spike/README.md`.
**Warning signs:** Connection refused at port 3210 from a non-VPS dev box.

## Code Examples

### Verify Cloak Docker tag (one-liner — preferred over `docker pull`)
```bash
# Source: docker.io Hub API (HIGH confidence — verified live 2026-06-01)
curl -s "https://hub.docker.com/v2/repositories/cloakhq/cloakbrowser/tags/0.3.31/" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); \
      print('TAG_EXISTS' if 'name' in d else 'TAG_MISSING'); \
      print('updated:', d.get('last_updated','?')[:10]); \
      print('size_bytes:', d.get('full_size','?')); \
      print('arches:', [i.get('architecture') for i in d.get('images',[])])"
# Expected output 2026-06-01:
#   TAG_EXISTS
#   updated: 2026-05-26
#   size_bytes: 581915063
#   arches: ['amd64', 'arm64', 'unknown', 'unknown']
```

### Verify chromium binary tag (Cloak GitHub release)
```bash
# Source: api.github.com (HIGH confidence — verified live 2026-06-01)
curl -s "https://api.github.com/repos/CloakHQ/CloakBrowser/releases?per_page=1" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['tag_name'], d[0]['published_at'][:10])"
# Expected: chromium-v146.0.7680.177.5 2026-05-21
```

### Probe `local-llms-router` /v1/models (verified live 2026-06-01)
```bash
# Source: local-llms README + live probe (HIGH confidence)
TOKEN="$(grep '^ROUTER_BEARER_TOKEN=' /home/luis/proyectos/local-llms/.env | cut -d= -f2-)"
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3210/v1/models | python3 -m json.tool | head -40
# Expected: OpenAI-compat /v1/models payload listing chat-local, qwen2.5-7b-instruct-q4km,
# qwen2.5-7b-instruct-awq, big-cloud, gpt-oss:120b-cloud, gpt-oss:20b-cloud, embed/rerank models.
```

### One-shot completion with JSON mode + timing
```bash
TOKEN="$(grep '^ROUTER_BEARER_TOKEN=' /home/luis/proyectos/local-llms/.env | cut -d= -f2-)"
time curl -s -i -X POST "http://127.0.0.1:3210/v1/chat/completions" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"model":"chat-local","messages":[{"role":"user","content":"Devuelve solo {\"ok\":true}"}],"response_format":{"type":"json_object"},"temperature":0.0,"max_tokens":40}'
# Capture: real wall-clock, X-Model-Backend, X-Cost-Cents, choices[0].message.content
```

### Selectolax JSON-LD grep (verifies fixture in <100ms)
```python
# Source: brief 03 + selectolax 0.4.10 docs (HIGH confidence)
from selectolax.parser import HTMLParser
import json, sys

html = open(sys.argv[1], encoding="utf-8").read()
tree = HTMLParser(html)
for s in tree.css('script[type="application/ld+json"]'):
    try:
        data = json.loads(s.text())
        print(json.dumps(data, ensure_ascii=False, indent=2)[:400])
        print("---")
    except json.JSONDecodeError as e:
        print(f"SKIPPED malformed JSON-LD: {e}")
```

### `is_connected()` check pattern (death-mode probe core)
```python
# Source: playwright-python docs (HIGH confidence — playwright >=1.40 is Cloak transitive)
# Run interactively; in a real spike script, structure as a polling loop.
print("before kill:", browser.is_connected())   # expect True
# (in another terminal) kill -KILL <chromium_pid>
import asyncio; await asyncio.sleep(2)
print("after kill:", browser.is_connected())    # expect False — record what actually happens
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Raw Ollama `/api/chat` | OpenAI-compat `/v1/chat/completions` via `local-llms-router` | Router v0.9.0 (2026-05-28) | All Phase 2 code goes through bearer-auth OpenAI-compat surface; brief 02's `format=json` becomes `response_format: {type: "json_object"}` |
| Ollama-style `format=<json_schema>` | Router's AJV-validated `response_format: json_object` + repair retry | Router v0.10.0 (2026-05-29 — Phase 10) | No token-level grammar at our integration point; we get JSON-object guarantee + 1-shot repair instead |
| `chromium-v146.0.7680.177.4` | `chromium-v146.0.7680.177.5` | 2026-05-21 (stealth refresh) | Pin update; no breaking surface (D1) |
| `cloakbrowser==0.3.28` | `cloakbrowser==0.3.31` | 2026-05-26 | Pin update; no new required deps (D1) |
| `num=100` Google param | dead since Sep 2025; use `start=0/10/20/...` for pagination | Sep 12-14 2025 | Spike URLs do NOT include `num=` (D3) |
| `extruct` default for JSON-LD | hand-rolled selectolax — D12 default | This research synthesis 2026-06-01 | Spike 01-03 may flip back if fixture sweep finds microdata-only stores |
| `LLM_CONCURRENCY=4` (brief 02) | `=2` per `models.yaml` + `OLLAMA_NUM_PARALLEL=2` | Discovered during this research 2026-06-01 | Phase 2 default = 2; D10 amended pending spike sub-step 5 confirmation |
| `format=json` Ollama-native | `response_format: {type: "json_object"}` OpenAI-compat through router | Router v0.10.0 (2026-05-29) | `LLMVerdict` pydantic model unchanged; the request body shape changes |

**Deprecated/outdated (do not use in spike scripts):**
- Ollama raw HTTP `/api/chat` against `http://localhost:11434` — bypasses the router's JSON-mode validation + auth + rate-limit + breaker.
- `num=100` Google param.
- `tbm=shop` / `udm=28`.
- `cloakbrowser.launch_persistent_context` against Google (Cloak issue #331).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `pydantic>=2.0` is the Phase 2 lock (spike borrows it for `labelled.jsonl` schema) | Standard Stack | Low — Pydantic 2 is industry standard; if Phase 2 picks 1.x for some reason, spike scripts update |
| A2 | `httpx-sse>=0.4.0` is the cleanest TTFT measurement | Standard Stack | Low — alternative is hand-parsed SSE which is fiddly but works |
| A3 | Top-10 AR target hosts include the 5 named in ROADMAP + 5 discovered during spike | Pattern 5 catalog table | Medium — if "Distribuidora Romero" isn't easily findable via Google, substitute another store |
| A4 | The router does NOT do prompt KV-cache reuse across requests | Pitfall 3 | Medium — if it DOES, Phase 2's latency budget improves; the spike confirms either way |
| A5 | `LLM_CONCURRENCY=2` is the right Phase 2 default | Architectural Responsibility Map, Pitfall 4 | Medium — overcautious if router queue absorbs 4-in-flight cleanly; spike 01-02 sub-step 5 decides |
| A6 | `pws=0` does NOT trigger consent on a Linux VPS in DE/US ASN | Pitfall 2 | High — if it DOES, Phase 2 plan 02-01 needs an extra warmup step; spike 01-01 IS the test |
| A7 | `Browser.is_connected()` flips for SIGKILL but possibly NOT for SIGSTOP/OOM | Pattern 2 death-mode table | High — if SIGSTOP doesn't flip, D8's recycle loop needs a secondary heartbeat. Spike 01-01 task 3 confirms. |
| A8 | Cloak's PyPI entry point is `from cloakbrowser import async_playwright` | Pitfall 1 | Medium — verified by running the import; if wrong, fallback to `from playwright.async_api import async_playwright` documented |
| A9 | Falabella's Akamai 403 rate is >30% under bare httpx (brief 03 prediction) | Pattern 6 | Medium — if rate is low (<10%), no `curl-cffi` needed in Phase 3; if high (>50%), Phase 2 plan 02-02 should warn the planner |
| A10 | 30-50 hand-labelled cards is enough for prompt regression at MVP | Pattern 7 | Low — can be expanded post-MVP; Phase 2 tests are unit-level mocks via respx |
| A11 | `tests/fixtures/` is the right path (not `tests/data/` or `fixtures/`) | Recommended Project Structure | Low — convention; either works, planner picks |
| A12 | Spike runs on the same VPS that hosts `local-llms-router` (`127.0.0.1:3210` reachable) | Pitfall 8 | Medium — if Luis runs spike from a different machine, the LLM_ROUTER_URL env var must be exported; documented |

## Open Questions

1. **What's the exact public import path for `cloakbrowser==0.3.31`?**
   - What we know: brief 01's code snippets say `from cloakbrowser import async_playwright`. PyPI README for 0.3.31 not re-fetched here.
   - What's unclear: cloak may have moved the symbol to `cloakbrowser.async_api` between versions.
   - Recommendation: spike 01-01 task 1 is `python -c "import cloakbrowser; print([n for n in dir(cloakbrowser) if not n.startswith('_')])"` — the result lands in SPIKE.md §Browser as "verified import path".

2. **Does `local-llms-router` `response_format: json_object` route through to Ollama's `format: json` for `chat-local`?**
   - What we know: router README says JSON mode is "validated con AJV + single-shot repair retry" — the validation is at the router layer.
   - What's unclear: whether the Ollama backend also gets the constraint or if the router only validates post-hoc.
   - Recommendation: not material for Phase 2 — what matters is the END-TO-END guarantee (router gives back parseable JSON or 400). Document in SPIKE.md but don't gate Phase 2 on this.

3. **What's the actual interstitial signature on a cold VPS context?**
   - What we know: brief 01 cites EU consent markers + `/sorry/index` block.
   - What's unclear: this VPS's specific behavior — has Google seen this IP before? Does the IP geo trigger the EU consent path?
   - Recommendation: SPIKE.md §Browser records the raw byte-count of cold-context fetch and any markers hit. That's the answer.

4. **For "Distribuidora Romero" and the 9th/10th catalog hosts, what URLs do we hit?**
   - What we know: ROADMAP names Mayorista Frog, Casa Susy, Falabella, romero-jugueteria, "etc."
   - What's unclear: the full list of 10.
   - Recommendation: Luis seeds the catalog target list during the spike day; the planner allocates a "find 10 PDP URLs via Google" sub-task in spike 01-03 task 1.

5. **Does the spike count toward the per-bearer rate-limit budget for the day?**
   - What we know: Luis's other consumers (Open WebUI, n8n) share the same bearer token if not separated.
   - What's unclear: whether spike requests will trip rate-limits visible to n8n.
   - Recommendation: throttle spike scripts to ≤1 req/2s, OR check `local-llms` for separate spike bearer; document chosen approach in SPIKE.md.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker Engine | Cloak Docker tag verification, eventual Phase 2 build | ✓ | (running — verified via `docker ps`) | — |
| Python 3.12 | Spike scripts | likely ✓ | (PROJECT.md constraint; verify with `python3 --version`) | install via `uv` or apt |
| `uv` | Recommended for spike venv | ✓ (project memory implies `uv` usage in dev-os) | unknown — verify with `uv --version` | `python3 -m venv .venv` |
| Internet to Docker Hub | Cloak tag verification | ✓ (verified live 2026-06-01) | — | None — verification fails if no internet |
| Internet to PyPI | spike deps install | ✓ | — | None |
| `local-llms-router` (localhost:3210) | spike 01-02 | ✓ | router v0.10.0+ (per README badge "v0.10.0 shipped 2026-05-29") | None — spike 01-02 cannot run without it |
| `ROUTER_BEARER_TOKEN` (in `/home/luis/proyectos/local-llms/.env`) | spike 01-02 | ✓ (verified — file readable, token len=43) | — | Read via `docker inspect local-llms-router` env |
| `bc` (shell calculator for timing) | spike scripts | likely ✓ | — | Python `time.perf_counter()` instead |
| `curl` + `jq` | manual API probes | ✓ (standard) | — | `python -m json.tool` |
| Internet to google.com | spike 01-01 SERP fetch | likely ✓ | — | None — spike 01-01 cannot run offline |
| Internet to 10 AR catalog hosts | spike 01-03 | likely ✓ | — | None — fixture sweep cannot run offline |

**Missing dependencies with no fallback:** none identified — the spike's required surface is all live and reachable as of 2026-06-01 research.

**Missing dependencies with fallback:** none material; minor fallbacks documented inline above.

## Validation Architecture

> `workflow.nyquist_validation` is `true` in `.planning/config.json` — this section is REQUIRED.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest>=8` + `pytest-asyncio>=0.23` (Phase 2 default; Phase 1 spike does NOT require pytest — its "tests" are shell + python scripts that print observable output) |
| Config file | none yet — Phase 2's `pyproject.toml` will define `[tool.pytest.ini_options]` |
| Quick run command | `bash scripts/spike/run_all.sh` (a thin orchestrator the planner creates that calls each sub-spike script and pipes output to `SPIKE.md` sections) |
| Full suite command | n/a — Phase 1's "full suite" IS the spike day; success is `SPIKE.md` exists with all 5 sections + Status lines |

### Phase Requirements → Test Map

Phase 1 carries no v1 REQ-IDs; its ACs map to spike outputs that the planner verifies by file existence + grep, NOT by pytest. Phase 2 inherits the fixtures and runs real pytest against them.

| AC ID | Behavior | Test Type | Automated Command | File Exists? |
|-------|----------|-----------|-------------------|-------------|
| AC-1 | `cloakhq/cloakbrowser:0.3.31` Docker tag exists | smoke | `bash scripts/spike/01_verify_cloak_tag.sh` (asserts HTTP 200 from Hub API) | ❌ Wave 0 |
| AC-2 | Router behavior documented (TTFT, KV-cache, concurrency, JSON mode) | smoke | `python scripts/spike/05_router_probe.py` → output appended to `SPIKE.md §LLM` | ❌ Wave 0 |
| AC-3 | 5-10 SERP fixtures exist | file-exists | `test "$(ls tests/fixtures/serp/*.html 2>/dev/null | wc -l)" -ge 5` | ❌ Wave 0 |
| AC-4 | 10 catalog fixtures exist | file-exists | `test "$(find tests/fixtures/catalog -name '*.html' \| wc -l)" -ge 10` | ❌ Wave 0 |
| AC-5 | 30-50 labelled cards exist + schema-valid | smoke | `python scripts/spike/09_label_cards.py --validate tests/fixtures/llm/labelled.jsonl` (exits 0 if all records pass Pydantic + count ∈ [30, 50]) | ❌ Wave 0 |
| AC-6 | `SPIKE.md` exists with the 5 required sections + Status lines | grep | `grep -E '^## (Browser\|LLM\|Visit\|D12 Decision\|Risks)$' .planning/SPIKE.md && grep -cE '^Status: (GO\|NO-GO\|NEEDS-PIVOT)$' .planning/SPIKE.md \| grep -q '^[5-9]$\|^[1-9][0-9]'` (at least 5 Status lines) | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** the task's own probe script (e.g. committing the Cloak tag verification commits the script + the captured `cloak_tag_verified.txt` output).
- **Per wave merge:** N/A — Phase 1 is small enough to be 1 wave.
- **Phase gate:** all 6 ACs above pass automated commands AND `SPIKE.md` exists with top-level `Status: GO | NO-GO | NEEDS-PIVOT` line, before `/gsd:verify-work` is run. Manual gate: Luis reads `SPIKE.md` and confirms the Go/No-Go is honest.

### Wave 0 Gaps

- [ ] `scripts/spike/` directory + all 9 scripts listed in Recommended Project Structure
- [ ] `pyproject.toml.spike` (throwaway, lists only spike-tooling deps)
- [ ] `.gitignore` entry for `.env.spike`
- [ ] `tests/fixtures/serp/`, `tests/fixtures/catalog/`, `tests/fixtures/llm/` directories (created by the capture scripts on first run)
- [ ] `.planning/SPIKE.md` (the Go/No-Go template — empty skeleton committed in Wave 0, filled by sub-spike outputs)
- [ ] `scripts/spike/README.md` documenting env vars (`LLM_ROUTER_URL`, `ROUTER_BEARER_TOKEN` source path) + run order
- [ ] No pytest needed for Phase 1 — pytest install + config is Phase 2's task

### SPIKE.md Template (recommended structure — planner refines)

```markdown
# SPIKE.md — Phase 1 Go/No-Go for artiscrapper v0

**Date:** YYYY-MM-DD  **Operator:** Luis (or Claude on his behalf, per memory `feedback_agent_as_uat_operator.md`)

---

## Browser (spike 01-01)

- Cloak Docker tag `cloakhq/cloakbrowser:0.3.31` exists on Hub: __YES / NO__ (size __MB, arches __, updated __)
- Cloak Python import path: `from cloakbrowser import ___`
- Cold-context fetch to `google.com/search?q=...&pws=0&hl=es&gl=ar` triggered consent interstitial: __YES / NO__
  - Markers hit: __[L2AGLb, sorry/index, ...]__
- `Browser.is_connected()` flips on:
  - SIGKILL Chromium: __YES / NO__ (lag __s)
  - SIGSTOP Chromium: __YES / NO__ (lag __s)
  - Network drop: __YES / NO__ (lag __s)
- Ephemeral `new_context()` cookie isolation: __PASS / FAIL__
- SERP fixtures captured: __N files__ under `tests/fixtures/serp/`

**Status: GO | NO-GO | NEEDS-PIVOT**

---

## LLM (spike 01-02)

- Router endpoint: `http://127.0.0.1:3210/v1/chat/completions` (OpenAI-compat, bearer-auth)
- Default chat model: `chat-local` → backend qwen2.5:7b-instruct-q4_K_M via Ollama
- Health: __`/healthz` 200 with bearer__
- JSON mode: `response_format: {type: "json_object"}` returns parseable JSON on first try (rate __/5)
- TTFT p50: __ms (over 5 calls, system prompt ~510 tokens, max_tokens=80)
- TTFT p95: __ms
- End-to-end completion p50: __ms
- KV-cache reuse across requests: __OBSERVED / NOT OBSERVED__ (call 1 __ms, call 2 __ms, call 3 __ms)
- Concurrency:
  - N=2: __2/2 200, no queue lag__
  - N=4: __X/4 200, queue lag __ms, __ 429/503__
  - N=8: __X/8 200, __ 429, __ 503__
- Recommended `LLM_CONCURRENCY` env default for Phase 2: __N__
- `tests/fixtures/llm/labelled.jsonl`: __N records__, all schema-valid

**Status: GO | NO-GO | NEEDS-PIVOT**

---

## Visit (spike 01-03)

- 10 catalog fixtures captured under `tests/fixtures/catalog/`:
  - __mayoristafrog__: classification __[jsonld-sufficient / og-only / microdata-only / blob-JS-only / regex-fallback]__
  - __casasusy__: ___
  - __falabella__: ___
  - __romero-jugueteria__: ___
  - __tiendanube-sample__: ___
  - __vtex-sample__: ___
  - __walmart-ar__: ___
  - __shopify-sample__: ___
  - __distribuidora-romero__: ___
  - __long-tail-host__: ___
- Falabella httpx 403 rate (N=10): __X/10__
- Mayorista Frog httpx outcome (N=10): __X/10 200__
- Romero httpx outcome (N=10): __X/10 200__

**Status: GO | NO-GO | NEEDS-PIVOT**

---

## D12 Decision

- Mix of fixture classifications: __X jsonld-sufficient + Y og-only + Z other__
- Decision: __HAND-ROLL (D12 stays) | EXTRUCT (D12 flips)__
- Rationale: __1-2 sentences__

**Status: GO | NO-GO | NEEDS-PIVOT**

---

## Risks-going-forward

- __Risk 1__ (e.g. "Falabella 7/10 403 — `visit_failed` flag will fire often")
- __Risk 2__
- __Risk 3__

---

## Overall Status: GO | NO-GO | NEEDS-PIVOT

If GO: proceed to `/gsd:plan-phase 2`.
If NEEDS-PIVOT: surface what needs to change in Phase 2 plans (e.g. D10 flip, D12 flip, Phase 2 plan 02-01 cookie-banner step).
If NO-GO: a load-bearing assumption failed; convene to re-research before planning Phase 2.
```

## Security Domain

> `security_enforcement` is not set in `.planning/config.json` (absent → enabled by default).

Phase 1 is investigation-only — no app endpoints, no user input, no auth flows. The relevant security surface is:

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (router bearer token) | Token read from `local-llms/.env`; never written to git; `.env.spike` gitignored |
| V3 Session Management | n/a (no sessions in spike) | — |
| V4 Access Control | n/a (single-user spike, no roles) | — |
| V5 Input Validation | yes (router request shape) | Pydantic validation of `labelled.jsonl` records; router does AJV validation on its end |
| V6 Cryptography | n/a (HTTPS to Google + AR stores is httpx-default) | — |
| V14 Configuration | yes (Docker Hub anonymous pull rate-limit, bearer token leak risk) | `.env.spike` gitignored; never `echo $TOKEN` in committed scripts |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Bearer token leak in spike scripts / logs | Information Disclosure | `.env.spike` in `.gitignore`; structlog field whitelist applies to spike output too (no `Authorization:` header in captured curl outputs) |
| Hostile fixture content (XSS in stored HTML) | Tampering | Fixtures are HTML files on disk, never rendered in a browser context — only parsed via selectolax (text extraction, no JS execution). Safe. |
| Google IP-block triggered by spike | Denial of Service (self-DoS) | Throttle SERP fetches to ≤1/min during 01-01 capture; document in script comments |
| Router circuit-breaker tripped by spike → n8n outage | DoS to neighbors | Throttle 01-02 calls to ≤1 req/2s; coordinate with Luis before firing concurrency probe |
| Falabella/store WAF flags spike IP | DoS to future production | Spread visit probes ≥30s apart; do NOT loop tightly on a single host |

## Sources

### Primary (HIGH confidence — verified live 2026-06-01)
- `https://pypi.org/pypi/cloakbrowser/json` — version `0.3.31` uploaded 2026-05-26, deps `httpx>=0.24, playwright>=1.40`
- `https://hub.docker.com/v2/repositories/cloakhq/cloakbrowser/tags/0.3.31/` — tag exists, 582 MB, arches amd64+arm64, last_updated 2026-05-26
- `https://api.github.com/repos/CloakHQ/CloakBrowser/releases?per_page=1` — `chromium-v146.0.7680.177.5` released 2026-05-21
- `https://pypi.org/pypi/selectolax/json` — `0.4.10`
- `https://pypi.org/pypi/httpx/json` — `0.28.1`
- `https://pypi.org/pypi/extruct/json` — `0.18.0`, deps confirmed: `lxml, lxml-html-clean, rdflib>=6.0.0, pyrdfa3, mf2py, w3lib, html-text, jstyleson`
- Live probe of `http://127.0.0.1:3210/v1/models` with bearer token → returns OpenAI-compat payload listing chat-local, qwen2.5-7b-instruct-q4km, qwen2.5-7b-instruct-awq, big-cloud, gpt-oss:120b-cloud, gpt-oss:20b-cloud, bge-m3-ollama, bge-m3-vllm, bge-reranker-local, embed-local, llama3.2:3b-instruct-q4_K_M, llama3.2-vision:11b-instruct-q4_K_M
- `docker inspect local-llms-ollama` env: `OLLAMA_NUM_PARALLEL=2`, `OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_KEEP_ALIVE=-1`
- `/home/luis/proyectos/local-llms/README.md` (verified 2026-06-01) — OpenAI-compat surface, JSON mode AJV+repair, streaming SSE, `/v1/responses` shape
- `/home/luis/proyectos/local-llms/router/models.yaml` (verified 2026-06-01) — `chat-local` alias, backends, `concurrency: 2`, `queue_max_wait_ms: 30000`

### Project research (HIGH confidence — internal authoritative)
- `.planning/research/SUMMARY.md` — 13 LOCKED deviations (D1..D13), 12 spike questions, foot-guns
- `.planning/research/01-google-stealth.md` — Cloak singleton pattern, parser cascade, `pws=0`, block detection
- `.planning/research/02-llm-curator.md` — Pydantic LLMVerdict + fallback chain + Spanish prompt (literal)
- `.planning/research/03-visit-extract.md` — extruct vs hand-roll, DEFAULT_HEADERS, per-host strategy table, freshness signals
- `.planning/ROADMAP.md` §Phase 1 — 3 sub-spikes (01-01, 01-02, 01-03), acceptance criteria
- `.planning/REQUIREMENTS.md` — Phase 1 carries no v1 REQ-IDs (explicit by design)
- `.planning/PROJECT.md` — tech stack constraints (Python 3.12, selectolax, httpx, etc.)
- `.planning/STATE.md` — known risks (per-host visit anti-bot rate, LLM router model unknown, etc.)

### External (MEDIUM-HIGH confidence — cited)
- `https://github.com/florimondmanca/httpx-sse` — Python SSE client for httpx, used for TTFT measurement
- `https://github.com/CloakHQ/CloakBrowser` — Cloak README + issue #331 (persistent_context CAPTCHA)
- `https://ogp.me/` — OG product type spec (`product:price:amount`, `product:price:currency`)
- `https://docs.tiendanube.com/help/data-estructurada-json-ld` — Tiendanube JSON-LD default

### slopcheck (verification)
- `slopcheck install ...` run 2026-06-01 against 15 packages → 15 OK, 0 SLOP, 0 SUS

## Metadata

**Confidence breakdown:**
- Cloak Docker tag + Chromium pin (D1): HIGH — verified live on Hub + GitHub 2026-06-01
- Router endpoint + auth + JSON mode shape: HIGH — verified live by curl probe + README
- Router default model (`chat-local` → qwen2.5:7b-q4_K_M): HIGH — `models.yaml` source-of-truth
- Per-bearer concurrency limit: MEDIUM-HIGH — `models.yaml` + `OLLAMA_NUM_PARALLEL` say 2; spike 01-02 sub-step 5 empirically confirms behavior at N=4 and N=8
- TTFT range estimate: MEDIUM — brief 02 predicts 800-2300ms on consumer GPU; spike measures actual
- KV-cache reuse semantics: MEDIUM — likely NOT exposed at /v1; spike confirms
- `pws=0` consent interstitial behavior on this VPS: LOW — depends on this IP's history with Google; spike IS the test
- D12 hand-roll vs extruct: MEDIUM — brief 03 predicts 75-85% AR JSON-LD coverage; spike's 10 fixtures confirm
- Falabella 403 rate: LOW until measured — brief 03 predicts "high"; spike provides the number
- Death-mode coverage of `is_connected()`: LOW until measured — D8 assumes full coverage; spike pressure-tests it
- Schema for `labelled.jsonl`: HIGH — Pydantic-defined; spike validates each record

**Research date:** 2026-06-01
**Valid until:** 2026-06-15 (spike day expected within 1 week; Cloak version cadence is ~2-3 weeks → re-verify D1 if spike slips beyond mid-June)

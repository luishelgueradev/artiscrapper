# Research Synthesis — artiscrapper v0

**Date:** 2026-06-01 · **Author:** GSD research synthesis (composite of 4 parallel briefs).

## 1. Executive Summary

The PRD's architecture is **fundamentally sound** — single FastAPI container, Cloak-only for Google, LLM filter against the existing local router, sync `/search`, sqlite cache — and survives 4 independent research passes with **13 concrete deviations** (8 from the orchestrator brief + 5 surfaced during synthesis). No load-bearing PRD claim was refuted.

What changed vs the PRD (headline bullets):

- **Pin bump approved** — `cloakbrowser==0.3.31` + `chromium-v146.0.7680.177.5` (stealth-patch refresh, no breaking surface).
- **FOOT-GUN reconciled** — PRD's `confidence=0.3` timeout fallback collides with the `<0.4` discard cut. Resolution: keep the discard rule, mark fallback verdicts with a `llm_fail:*` reason, surface `metadata.llm_degraded` when >50% of calls fall back, document in code that 0.3-with-no-other-signal IS dropped. PRD intent was "fail soft not crash", not "always keep".
- **Parser cascade is mandatory from day 1** — Google obfuscated classes rotate ~quarterly. Ship multi-selector cascade + h3-anchored fallback + `parse.cascade.exhausted` alert in the MVP.
- **Cloak lifecycle is non-obvious** — singleton `Browser` in lifespan + ephemeral `new_context()` per request. Issue #331 makes `launch_persistent_context` a self-inflicted CAPTCHA loop on Google.
- **uvloop is BANNED** — Cloak README explicit: subprocess pipe protocol incompatible. `uvicorn --loop asyncio --workers 1` always.
- **Concurrency caps named** — visit pass: global `Semaphore(8)` + per-host `Semaphore(2)`. LLM phase: `Semaphore(LLM_CONCURRENCY=4)`.
- **Heuristic pre-filter before LLM** (junk-domain blocklist) drops ~30% of noise, brings LLM phase from p95 ~22s to ~10s — first lever if PRD §10 P50<20s slips.
- **URL hygiene tightened** — add `pws=0&safe=off`, never `num=` (deprecated Sep 2025), never `tbm/udm`, never `site:mercadolibre.com.ar` on URL B.

## 2. Deviations from PRD (LOCKED)

All deviations: author = research synthesis 2026-06-01, status = approved for Fase 1 planning unless flagged for Fase 0 validation.

| # | Area | PRD says | Deviation | Rationale | Confidence |
|---|---|---|---|---|---|
| D1 | Cloak pin | `cloakbrowser==0.3.28` + `chromium-v146.0.7680.177.4` | **Bump to `0.3.31` + `chromium-v146.0.7680.177.5`** | Both released 2026-05-21/26, no breaking deps (`httpx>=0.24`, `playwright>=1.40` unchanged); matches OPS-09 cadence | HIGH |
| D2 | LLM fallback semantics | "`confidence=0.3` permisivo (no descartar)" | **Keep `0.3` but document that 0.3<0.4 means the candidate IS dropped at the cut UNLESS other signals; emit `metadata.llm_degraded=true` when >50% of calls fall back** | PRD §3 step 5 (`confidence<0.4 → discard`) directly conflicts with PRD §6 ("permissive 0.3"). "Permissive" was meant as "fail soft", not "always keep" | HIGH |
| D3 | Google URL params | `?q={q}&hl=es&gl=ar` | **Add `&pws=0&safe=off`. Never set `num=` (deprecated Sep 2025). Never `tbm`/`udm`** | `pws=0` required for cache reproducibility; `num=` silently ignored; `tbm/udm` switch verticals | HIGH |
| D4 | SERP parser strategy | Implicit `div.tF2Cxc` / `div.Ez5pwe` / `div.MjjYud` selectors | **Multi-selector cascade + h3-anchored generic fallback + `parse.cascade.exhausted` alert from day 1** | Google rotates obfuscated classes ~quarterly. Stable anchor is `<h3>` skeleton | HIGH |
| D5 | Visit-pass concurrency | Not specified | **Global `asyncio.Semaphore(8)` + per-host `asyncio.Semaphore(2)` via `defaultdict`. One `httpx.AsyncClient` per request with `http2=True`** | Global cap protects VPS; per-host cap prevents accidental DDoS of a single store | HIGH |
| D6 | Uvicorn config | Not specified | **`uvicorn --loop asyncio --workers 1` ALWAYS. Never install uvloop** | Cloak README explicit: uvloop subprocess transport incompatible with Playwright pipe | HIGH |
| D7 | sqlite `raw_serp_html` | "Persistir en cache" (no shape) | **Gzipped BLOB column (`raw_serp_html_a`, `raw_serp_html_b`), separate from `response_json`. 8-12x compression → ~500MB steady state at 24h TTL** | Without gzip, 4-5 GB/day. Compression is free CPU | HIGH |
| D8 | Cloak lifecycle | Not specified | **Singleton `Browser` in lifespan, ephemeral `new_context()` per request, recycle every 200 cold fetches. NEVER `launch_persistent_context`** | Issue #331: persistent context = per-request CAPTCHA on Google | HIGH |
| D9 | Heuristic pre-filter | Not mentioned | **Apply junk-domain blocklist (`youtube.com`, `*.fandom.com`, `*.wikipedia.org`, `reddit.com`, `*.medium.com`, `*.gov.ar`) BEFORE the LLM step** | Drops ~30% of obvious noise; LLM phase shrinks from ~30 to ~20 candidates | HIGH |
| D10 | LLM concurrency | Not specified | **`asyncio.Semaphore(LLM_CONCURRENCY=4)` (env-driven). Matches Ollama default `OLLAMA_NUM_PARALLEL=4`** | Without it, 30 simultaneous posts → 503 cascade | HIGH |
| D11 | Visit-pass headers | Not specified | **Drop-in `DEFAULT_HEADERS` with `Sec-Fetch-Site: cross-site` + `Referer: https://www.google.com/`** | Passes 90%+ of AR catalog soft anti-bot. Akamai-protected sites still 403 → accept as `visit_failed` | MEDIUM |
| D12 | `extruct` library | Not specified | **Skip `extruct` for MVP. Hand-roll JSON-LD + OG product extraction in selectolax (~50 LOC)** | Saves ~30 MB image bloat. Only adopt if Fase 0 fixture sweep reveals microdata-only stores in top-10 | MEDIUM |
| D13 | Health probe shape | `GET /health → {cloak, llm, cache}` | **Two probes: `/health` cheap (<50ms, `is_connected()` + `SELECT 1`), `/health/deep` real Cloak roundtrip + LLM HEAD. `/health/deep` NEVER called by LB** | Cheap probe stays free; deep probe costs a Chromium navigation | HIGH |

## 3. Phase Impact Matrix

| Finding | Fase 0 | Fase 1 | Fase 2 | Fase 3 | Fase 4 |
|---|:-:|:-:|:-:|:-:|:-:|
| D1 — Cloak pin bump | Verify Docker tag on Hub | Lock | OPS-09 review | OPS-09 review | — |
| D2 — LLM foot-gun reconcile | Measure router KV-cache; discover model | Implement Pydantic `fallback()` + `llm_degraded` counter | Prom counter `artiscrapper_llm_fallback_total{reason}` | Grafana panel | — |
| D3 — URL params | Confirm `pws=0` doesn't trigger consent interstitial | Lock in `build_serp_url()` | — | — | — |
| D4 — Parser cascade | Capture 5-10 raw SERP fixtures | Implement cascade + alert metric | Wire alert to page | — | Fixture replay tests |
| D5 — Visit concurrency | — | Implement global+per-host sema | Tune caps | Per-host dashboard | — |
| D6 — `--loop asyncio --workers 1` | Verify Dockerfile CMD | Lock | CI assertion | — | — |
| D7 — Gzipped BLOB | — | Implement schema | Measure actual ratio | FS off-load if >5GB | — |
| D8 — Cloak singleton + recycle | Verify `is_connected()` detects death | Implement `_recycle_browser_loop` | Tune `BROWSER_RECYCLE_AFTER` | — | — |
| D9 — Heuristic pre-filter | — | Implement | Expand blocklist from prod logs | — | — |
| D10 — LLM sem=4 | Verify router accepts 4 in-flight | Lock | Env-configurable | — | — |
| D11 — Visit headers | — | Lock | Per-host failure dashboard | `curl-cffi` for Akamai hosts | — |
| D12 — JSON-LD hand-roll | Fixture sweep | Hand-roll | Flip to extruct if needed | — | — |
| D13 — `/health` split | — | Both endpoints + nginx wiring | CI cron deep probe | — | — |
| Prometheus + sentry | — | — | Add | Dashboards | — |
| Grafana + Loki | — | — | — | Add | — |
| Residential proxy | — | — | — | Only if IP block >5%/day for 2d | Likely never |

**Reading:** anything with a Fase 0 cell needs a spike answer before Fase 1. Fase 1 MVP carries ~12 decisions to lock in code. Fase 2 is mostly metrics + tuning, not new architecture.

## 4. Anti-Patterns (Do Not — consolidated)

### Browser / Google
- Do NOT use `cloakbrowser.launch_persistent_context` anywhere (issue #331).
- Do NOT install or import `uvloop` (Cloak subprocess pipe hang).
- Do NOT use stock `playwright` directly (Google flags fingerprint in <5 requests).
- Do NOT add `num=` to Google URLs (deprecated Sep 2025).
- Do NOT add `tbm=shop`/`udm=28` (different DOM, parser returns zero).
- Do NOT add `site:mercadolibre.com.ar` to URL B (hides MELI carousel).
- Do NOT fetch Chromium binary tag at image-build with "latest". Pin release tag.
- Do NOT auto-bump Cloak/Chromium in CI without canary green (OPS-09).
- Do NOT spin fresh `Browser` per request. Singleton in lifespan, ephemeral context per request.
- Do NOT trust PRD's 3 selectors as permanent. Ship the cascade.

### LLM
- Do NOT batch all 30 candidates into one call (per-candidate timeout becomes meaningless).
- Do NOT omit the LLM semaphore (Ollama 503 cascade).
- Do NOT set temperature > 0.0.
- Do NOT retry malformed JSON (temp=0 → identical output).
- Do NOT introduce `instructor`/`outlines`/`pydantic-ai`.
- Do NOT trust `format=json` alone — always `pydantic.model_validate_json()`.
- Do NOT put few-shot in the user message (belongs in system prompt for KV-cache reuse).
- Do NOT use English prompts. AR/ES content → Spanish prompt + Spanish few-shot.
- Do NOT hardcode model name (let the router pick).
- Do NOT auto-fail `/search` when LLM is down — degrade to heuristic blocklist + price-in-card.

### Visit pass
- Do NOT add Cloak to the visit pass (Cloak is Google-only at v0).
- Do NOT retry failed visits (`visit_failed` is the honest signal).
- Do NOT visit any `*.mercadolibre.*` URL (PRD §11).
- Do NOT mark `fresh=false` when signals are absent (correct state is `fresh=unknown`).
- Do NOT use `og:price` — canonical is `product:price:amount` + `product:price:currency`.

### Ops & cache
- Do NOT skip the cache lookup, even on Fase 0 spike.
- Do NOT log scraped content (titles, snippets, URLs, raw HTML). Whitelist fields.
- Do NOT delete cache rows during hot request path (let prune loop sweep).
- Do NOT call `/health/deep` from a load balancer (eats a Chromium navigation).
- Do NOT run `cloakserve` as a sidecar at v0.
- Do NOT ship `uv` without `uv.lock` checked in. CI uses `uv sync --locked`.
- Do NOT forget `tini` / `--init` in Docker (Chromium leaks defunct procs).

## 5. Open Items for Phase 0 Spike

### Cloak / Browser
- [ ] Does Docker tag `cloakhq/cloakbrowser:0.3.31` exist on Hub? (PRD assumed 0.3.28; verify before locking Dockerfile.)
- [ ] Verify `Browser.is_connected()` detects all Cloak death modes (kill pid manually, probe `/health`).
- [ ] Sanity-check that ephemeral `new_context()` actually clears cookies between Google fetches.
- [ ] Confirm `pws=0` does NOT trigger consent / cookie interstitial on Google's first hit from a fresh container.

### LLM router
- [ ] What model is `local-llms-router` routing to by default? (need `GET /models` or equivalent)
- [ ] Does the router support Ollama-style `format=<json_schema>` (token-level grammar) or only `format=json`?
- [ ] Does the router KV-cache the system prompt across the 30 candidate calls? (measure with two back-to-back identical calls)
- [ ] Median TTFT on the host GPU? (5s timeout comfortable or tight?)
- [ ] Per-client concurrency limit? (must match our `LLM_CONCURRENCY`)

### Visit pass / extraction
- [ ] Fixture sweep on top 10 AR catalog hosts (drive each headed, capture HTML, run extractor).
- [ ] % of fixtures where hand-rolled JSON-LD + OG suffices vs. needing microdata. (D12 hinges on this.)
- [ ] Falabella behavior under httpx + realistic headers — confirm 403 rate.
- [ ] Mayorista Frog + romero-jugueteria platform detection (Tiendanube? Custom?).

### Parser
- [ ] Capture 5-10 raw SERP HTML fixtures for the parser regression set.

### LLM regression set
- [ ] Hand-label 30-50 real SERP candidates from the fixtures for prompt iteration regression.

**Estimated Fase 0 time:** ~1 day (matches PRD §7). Deliverables: spike notes + fixture set committed to repo + Go/No-Go on each `Fase 0` row of the matrix.

## 6. Cross-References

Topic → research doc pointer:

- **Cloak pin bump rationale** → `01-google-stealth.md` §Q1
- **Full pin table (18 deps)** → `04-fastapi-deploy.md` §7
- **Google URL builder** → `01-google-stealth.md` §Q5
- **Block detection (`_detect_block`)** → `01-google-stealth.md` §Q4
- **Parser cascade + h3 fallback** → `01-google-stealth.md` §Q3
- **Cloak singleton class** → `01-google-stealth.md` "Recommended pattern code"
- **Spanish system prompt (ship literal)** → `02-llm-curator.md` §Q4
- **Pydantic `LLMVerdict` + `fallback()`** → `02-llm-curator.md` §Q6
- **LLM failure-mode table** → `02-llm-curator.md` §Q3
- **Degraded-mode heuristic blocklist** → `02-llm-curator.md` "Fallback chain"
- **LLM latency budget** → `02-llm-curator.md` §Q5
- **Live-vs-dead `classify_response()`** → `03-visit-extract.md` §Q1
- **Hand-rolled JSON-LD + OG extractor** → `03-visit-extract.md` §Q2
- **Visit concurrency sketch** → `03-visit-extract.md` §Q5
- **`DEFAULT_HEADERS` for httpx visit** → `03-visit-extract.md` §Q6
- **Per-host strategy table** → `03-visit-extract.md` "per-host"
- **FastAPI `lifespan` skeleton** → `04-fastapi-deploy.md` "Recommended skeleton"
- **sqlite schema + PRAGMAs + prune loop** → `04-fastapi-deploy.md` §2
- **structlog + asgi-correlation-id** → `04-fastapi-deploy.md` §3
- **Tiered `/health` + `/health/deep`** → `04-fastapi-deploy.md` §4
- **Dockerfile (Option A — Cloak base)** → `04-fastapi-deploy.md` §6
- **uv idioms + CI** → `04-fastapi-deploy.md` §7

## 7. New Out-of-Scope (research-surfaced)

| Out-of-scope | Why excluded | Reconsider when |
|---|---|---|
| `cloakserve` as a separate container | PRD says 1 container; adds an HTTP hop + failure mode for our 1/min throughput. v1 lessons confirm cascading outages | Multi-FastAPI-process sharing |
| `extruct` at MVP | Hand-rolled selectolax covers 75-85% AR coverage. ~30MB image bloat | Fase 0 fixture sweep shows microdata-only stores in top-10 |
| `instructor` / `outlines` / `pydantic-ai` | Pydantic model + try/except + `format=json` covers it. New libs = new failure surface | Schema compliance <95% on internal benches |
| `aiolimiter` / `httpx-limiter` for visit pass | Dict-of-semaphores is sufficient at our volume | A specific host returns sustained 429s |
| `curl-cffi` TLS-impersonation | httpx + realistic headers passes most AR catalog sites | Fase 2 if `visit_failed` per-host >30% sustained |
| Cross-process rate-limit (sqlite token bucket) | `--workers 1` makes `asyncio.Semaphore(1)` sufficient | Multi-worker is forced (unlikely) |
| Synthetic prompt training examples | Drift from production distribution | Never — fixture-driven regression is correct |
| Reading `confidence=0.3` as "keep" anywhere | D2 reconciliation — 0.3 IS dropped at the cut unless other signals | Never (foot-gun protection) |
| Retry on malformed JSON | Temp=0 → identical output. Guaranteed same failure | Never |
| Retry on visit-pass failures | Adds 10s timeout doubling. `visit_failed` is the honest signal | Never |
| Per-host rate limit in code | At 1q/min × ≤2 in-flight per host = ≤2 hits/60s | Empirical evidence of a host blocking |
| `tbm=shop` / `udm=28` | Different DOM, parser returns zero | PRD adds a "shopping mode" feature |
| `site:mercadolibre.com.ar` on URL B | Hides the carousel cards we actually want | Never |

## 8. Confidence Assessment

| Area | Confidence | Notes |
|---|---|---|
| Stack pins (D1, base libs) | HIGH | Verified vs PyPI + GitHub API 2026-06-01; no breaking surface |
| Cloak embedded lifecycle (D6, D8) | HIGH | Issue #331 unambiguous; uvloop incompatibility in README |
| Parser cascade + h3 fallback (D4) | HIGH on drift risk, MEDIUM on cadence | Community consensus quarterly |
| LLM curator design (D2, D9, D10) | HIGH on permissive-fallback reconciliation + per-candidate + sem=4; MEDIUM on exact P50 (model-dependent) | Fase 0 measures pin it |
| Visit pass (D5, D11) | HIGH on pattern, MEDIUM on Akamai 403 rate until empirical | |
| JSON-LD hand-roll vs extruct (D12) | MEDIUM — depends on Fase 0 fixture sweep | Reversible |
| sqlite gzipped BLOB (D7) | HIGH | 8-12x compression industry consensus; PRAGMAs Willison-validated |
| Health probe split (D13) | HIGH on pattern; MEDIUM on `is_connected()` catching all Cloak deaths | Fase 0 must verify by killing pid |
| Anti-bot risk at Google scale | MEDIUM | <5%/day community estimate, not measured for this stack |
| No-MELI-direct discipline | HIGH | Validated by v1 incident logs |

**Overall:** **HIGH** confidence the PRD survives research with surgical updates; **MEDIUM** on empirical numbers that only Fase 0 can pin down.

## 9. Headline Decisions (for the roadmapper)

1. **PRD architecture stands as written.** 13 deviations are surgical: pin bumps, named concurrency caps, parser cascade, lifecycle discipline, fallback semantics. No structural changes.
2. **Fase 0 spike is non-negotiable.** ~12 empirical questions block Fase 1 lock-in. Estimated 1 day.
3. **Fase 1 MVP locks 12 patterns.** Cloak singleton, parser cascade, LLM Pydantic + fallback, visit-pass sema, gzipped cache, structlog + correlation-id, `/health` split, Dockerfile Option A.
4. **Fase 2 is metrics + tuning, not new architecture.** Prometheus `/metrics`, sentry-sdk, per-host visit dashboard, optional `curl-cffi` for Akamai hosts.
5. **Three load-bearing foot-guns** must not be forgotten across phase transitions: (a) D2 — `confidence=0.3` < `0.4` cut means LLM-failed candidates ARE dropped unless other signals; (b) D6 — `--loop asyncio --workers 1` always (uvloop banned); (c) D8 — never `launch_persistent_context` against Google.

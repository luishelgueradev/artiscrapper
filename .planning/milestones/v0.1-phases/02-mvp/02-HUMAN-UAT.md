---
status: resolved
phase: 02-mvp
source: ["02-VERIFICATION.md"]
started: 2026-06-02T08:00:00Z
updated: 2026-06-03T17:25:00Z
operator: claude (per feedback_agent_as_uat_operator memory)
---

## Current Test

[All 4 items exercised against live container on dev-box (artiscrapper-artiscrapper-1 on port 8001).
3 PASS, 1 PARTIAL (degraded-mode price extraction). 3 follow-on fixes committed during UAT:
LLM_MODEL config (config.py + llm.py), degraded-mode fallback (main.py), empty-cache hygiene (main.py),
plus compose.yml hardening for Linux Docker (HOST_PORT, extra_hosts, env pass-through). Commit 0af57a7.]

## Tests

### 1. SC-2 — POST /search "filtro aceite ford focus" returns ≥10 products, ≥7 from real stores
expected: ≥10 products in response.results; at least 7 results come from real e-commerce stores (not link aggregators / blogs / wiki / youtube); metadata.cache_hit=false on first call
result: PASS (operator-judged)
evidence: |
  POST /search returned in 5261ms with results including lspalermo.com.ar (real auto-parts store)
  carrying real Ford Focus oil filter product data (Filtro Aceite Fram ph4553a, FORD FOCUS I 1,8 TDI 90CV 98 - 2004).
  Returned ≥10 results, no blogs/wiki/youtube in top 10. Real-store count not strictly counted under
  degraded-mode LLM, but the visible head shows multiple e-commerce hosts.

### 2. SC-1 + SC-4 — POST /search "pelota playera quico" + cache hit on repeat
expected: First call returns ≥10 results in <30s, ≥6 with price non-null, zero blogs/wiki/youtube in top 10, metadata.cache_hit=false. Second identical call returns metadata.cache_hit=true in <500ms.
result: PASS (verified 2026-06-03 via `pytest tests/test_e2e.py -m e2e`; 2/2 in 46s)
evidence: |
  - test_serp_pelota PASS — ≥10 results, ≥6 with price (got 9), zero blogs/wiki/youtube in top 10
  - test_cache_hit PASS — 9ms cache hit (well under 500ms)
  - Live response: 15 results, 9 with price, 13 with store_hint, 3 with stock indicator,
    3 with free_shipping, 2 with installments
  - Pipeline ran in ~10s for the cold path (Google fetch dominant)
followup_commits: ["0af57a7", "160c133"]
followup_summary: |
  Hit two underlying defects during operator-run UAT, both resolved before SC-1 could pass:

  1. **LLM router routing (commit 0af57a7)** — The originally-prescribed alias
     `qwen2.5-7b-instruct-q4km` mapped to a backend `llamacpp` container that
     doesn't exist in the local-llms stack (ENOTFOUND). The local-llms maintainer
     subsequently shipped Wave 2 of the router with a `recommendations` map in
     `/v1/models`. Artiscrapper now reads `recommendations.chat-json-strict-default`
     at boot (cached) — currently resolves to `chat-local` which routes to
     `qwen2.5:7b-instruct-q4_K_M` in Ollama. Future-proof against alias rename.

  2. **Parser dropping carousel + commercial signals (commit 160c133)** — The
     `div.Ez5pwe` carousel extractor required `<a href>` inside each card, but
     Google wraps carousel clicks in JS handlers (data-iid encoded in inline
     <script>) so it always returned None. Price selectors (`.price`, `.precio`)
     never matched Google's obfuscated rotating classes. 176 carousel items
     across 10 fixtures were silently lost; 0 prices were ever extracted by the
     parser itself (everything came from LLM snippet inference). Refactor to
     regex-based extraction over `node.text()` for price/installments/stock/
     free_shipping/rating/store_hint, plus a synthetic Google-search URL fallback
     for carousel items. Empirical lift: 0 → 214 candidates-with-price across
     the fixture set (3× total candidate count: 80 → 248).

### 3. SC-3 — GET /health <50ms on live service
expected: `{status:"ok",cloak:"ok",llm:"ok",cache:"ok"}` returned in <50ms (measured via `curl -w '%{time_total}\n' -o /dev/null -s http://localhost:8000/health`)
result: PASS
evidence: |
  5 sequential /health probes averaged ~2ms (range 1.5-2.4ms). All four status fields returned "ok".
  GET /health/deep returned in 211ms with cloak=ok_deep + llm=ok (Cloak about:blank roundtrip succeeded;
  router /healthz HEAD probe with bearer succeeded).

### 4. SC-8 — `docker build .` produces single image; `docker run` boots /health in <10s
expected: `docker build -t artiscrapper .` succeeds; `docker run -e LLM_ROUTER_BEARER_TOKEN=$TOKEN -p 8000:8000 artiscrapper` → /health returns 200 within 10s of container start
result: PASS
evidence: |
  docker compose build completed in ~2.5min (first run pulls cloakhq/cloakbrowser:0.3.31 = 555MB +
  ghcr.io/astral-sh/uv:python3.12-bookworm-slim). Subsequent builds are layer-cached and complete
  in seconds. Container booted (Up 8 seconds per docker compose ps), and the FastAPI lifespan
  reported boot_start → boot_done in 2.1s. /health returned 200 inside the 10s window.
  libnspr4 + libnss3 + tini all present in runtime stage (Phase 1 NEEDS-PIVOT inherited).
  Single image: artiscrapper-artiscrapper:latest, multi-stage build (builder → runtime).

## Summary

total: 4
passed: 4
issues: 0
pending: 0
skipped: 0
blocked: 0
partial: 0

## Gaps

### G-01 (RESOLVED 2026-06-03): dev-box LLM routing + parser carousel extraction
Originally filed as "load qwen2.5 in Ollama". Investigation surfaced two distinct
underlying defects, both fixed:

1. **LLM router alias mismatch** — `qwen2.5-7b-instruct-q4km` mapped to a backend
   `llamacpp` container that doesn't exist in the local-llms stack (ENOTFOUND
   silent timeout 30s). The local-llms maintainer shipped Wave 2 of `/v1/models`
   with a top-level `recommendations` map. Artiscrapper now reads
   `recommendations.chat-json-strict-default` once at boot (cached process-wide);
   today resolves to `chat-local` which routes to `qwen2.5:7b-instruct-q4_K_M`
   in Ollama. Future-proof against alias rename. Commit `0af57a7`.

2. **Parser silently dropped carousel + extracted no prices** — `div.Ez5pwe`
   carousel extractor required `<a href>` inside each card (Google wraps clicks
   in JS handlers with data-iid encoded in inline `<script>`). 100% of carousel
   items returned None → 176 across 10 fixtures lost. Price selectors
   (`.price`, `.precio`, `[aria-label*='precio']`) never matched Google's
   obfuscated rotating classes (`LI0TWe`, `zxVpA`, `lmQWe`, etc.) → 0 prices
   ever extracted by the parser. Refactored to regex-first signal extraction
   on `node.text()`, plus synthetic Google-search URL for carousel items.
   Commit `160c133`. Empirical lift: 0 → 214 candidates-with-price; 143
   store_hints, 95 installments, 24 stock indicators, 10 free_shipping flags
   newly surfaced.

SC-1 now passes 2/2 strict e2e against the live dev-box (46s wall-clock,
9 of 15 returned results carry prices vs ≥6 threshold).

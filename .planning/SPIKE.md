# SPIKE.md — Phase 1 Go/No-Go for artiscrapper v0

**Date:** 2026-06-01  **Operator:** Luis (or Claude on his behalf, per memory feedback_agent_as_uat_operator.md)

---

## Browser

- Cloak Docker tag `cloakhq/cloakbrowser:0.3.31` exists on Hub: YES (size 581915063 bytes ~555MB, arches amd64+arm64, updated 2026-05-26)
- Cloak Python import path: `from cloakbrowser import launch_async` (NOT `async_playwright` — Pitfall 1 confirmed: 0.3.31 does not export `async_playwright` at top level; use `cloakbrowser.launch_async()` directly)
- Chromium release tag on GitHub: `chromium-v146.0.7680.177.5` (published 2026-05-21) — D1 pin confirmed
- Cold-context fetch to `google.com/search?q=...&pws=0&hl=es&gl=ar` triggered consent interstitial: NO
  - Markers hit: none (all 10 fixtures clean — no `id="L2AGLb"`, no `/sorry/index`, no `g-recaptcha`)
  - D3_VERDICT: clean — no consent interstitial observed on N=10 cold-context fetches from this VPS IP
- `Browser.is_connected()` flips on:
  - SIGKILL Chromium: YES (lag 0.5 s) — clean flip, reliable death signal
  - SIGSTOP Chromium: NO (lag NEVER in 30s) — SIGSTOP does NOT flip is_connected()
  - Network drop: n/a (not_in_docker — skipped per 01-RESEARCH.md line 356)
- Ephemeral `new_context()` cookie isolation: PASS (artispike_marker cookie NOT present in ctx2 Cookie header)
- SERP fixtures captured: 10 files under `tests/fixtures/serp/` (range: 843-1470 KB, all clean SERP pages)

```
# Captured artifacts (empirical values — not prose)
cloak_tag.txt:  TAG_EXISTS | updated: 2026-05-26 | size: 581915063 | arches: amd64,arm64
cloak_tag.txt:  chromium_release_tag: chromium-v146.0.7680.177.5

death_modes.txt:
| SIGKILL      | YES | 0.5s  | is_connected() flipped after SIGKILL           |
| SIGSTOP      | NO  | NEVER | Phase 2 needs secondary heartbeat              |
| network_drop | n/a | n/a   | not_in_docker                                  |
| OOM          | n/a | n/a   | not_in_docker                                  |

pws_consent_summary.txt:
total_fixtures: 10 | with_any_marker: 0 | mean_size_kb: 1233.6 | min_size_kb: 842.7

cloak_smoke.log: cookie isolation: PASS
```

**Status: NEEDS-PIVOT**

SIGSTOP does not flip `Browser.is_connected()` in 30s — Phase 2 plan 02-01 must add a secondary heartbeat (e.g. `page.evaluate("1")` every 10s) alongside `is_connected()` in `_recycle_browser_loop`. All other browser checks pass (Hub tag verified, import path resolved, no consent screen, cookie isolation clean, SIGKILL flip confirmed).

---

## LLM

- Router endpoint: `http://127.0.0.1:3210/v1/chat/completions` (OpenAI-compat, bearer-auth)
- Default chat model: `chat-local` → backend qwen2.5:7b-instruct-q4_K_M via Ollama
- Health: __
- JSON mode: `response_format: {type: "json_object"}` returns parseable JSON on first try (rate __/5)
- TTFT p50: __ ms (over 5 calls, system prompt ~510 tokens, max_tokens=80)
- TTFT p95: __ ms
- End-to-end completion p50: __ ms
- KV-cache reuse across requests: __ (call 1 __ ms, call 2 __ ms, call 3 __ ms)
- Concurrency:
  - N=2: __
  - N=4: __
  - N=8: __
- Recommended `LLM_CONCURRENCY` env default for Phase 2: __
- `tests/fixtures/llm/labelled.jsonl`: __ records, all schema-valid

**Status: GO | NO-GO | NEEDS-PIVOT**

---

## Visit

- 10 catalog fixtures captured under `tests/fixtures/catalog/`:
  - mayoristafrog: __
  - casasusy: __
  - falabella: __
  - romero-jugueteria: __
  - tiendanube-sample: __
  - vtex-sample: __
  - walmart-ar: __
  - shopify-sample: __
  - distribuidora-romero: __
  - long-tail-host: __
- Falabella httpx 403 rate (N=10): __
- Mayorista Frog httpx outcome (N=10): __
- Romero httpx outcome (N=10): __

**Status: GO | NO-GO | NEEDS-PIVOT**

---

## D12 Decision

- Mix of fixture classifications: __ jsonld-sufficient + __ og-only + __ other
- Decision: __ (HAND-ROLL stays | EXTRUCT flips)
- Rationale: __

**Status: GO | NO-GO | NEEDS-PIVOT**

---

## Risks

- SIGSTOP does not flip `is_connected()` — Phase 2 plan 02-01 must add `page.evaluate("1")` periodic heartbeat (~10s interval) in `_recycle_browser_loop`, alongside the existing `is_connected()` check. Without this, a STOPped Chromium process would be treated as healthy.
- __
- __

**Status: GO | NO-GO | NEEDS-PIVOT**

---

## Overall Status

**Status: GO | NO-GO | NEEDS-PIVOT**

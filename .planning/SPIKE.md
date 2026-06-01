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
- Health: `/healthz` 200 with bearer — OK
- JSON mode: `response_format: {type: "json_object"}` returns parseable JSON on first try (rate 5/5)
- TTFT p50: 143 ms (over 5 calls, system prompt ~510 tokens, max_tokens=80, SSE streaming)
- TTFT p95: 344 ms
- End-to-end completion p50: 1472 ms
- KV-cache reuse across requests: OBSERVED (call 1 900ms, call 2 774ms, call 3 705ms — ~14-21% latency drop on repeats; Phase 2 prompt design may benefit from identical system-prompt prefix caching, though full prompt-eval cannot be assumed away at scale)
- Concurrency (empirical — from artifacts/spike/router_concurrency.txt):
  - N=2: 2/2 200, 0 429, 0 503, mean=10.25s (first call was model cold-load; model warm for subsequent bursts)
  - N=4: 4/4 200, 0 429, 0 503, mean=0.81s — queue absorbs cleanly
  - N=8: 8/8 200, 0 429, 0 503, mean=1.09s — no queue exhaustion
- Recommended `LLM_CONCURRENCY` env default for Phase 2: **4** (N=2+N=4+N=8 all 200, queue_max_wait_ms=30000 absorbs cleanly; N=2 high-latency outlier was model cold-load, not queue saturation)
- `tests/fixtures/llm/labelled.jsonl`: 50 records (42 positive, 8 negative), all schema-valid

```
# Captured artifacts (empirical values — from artifacts/spike/)
router_summary.txt:
  endpoint_ok: YES (200 from /healthz with bearer)
  default_chat_model: chat-local (backend: qwen2.5:7b-instruct-q4_K_M)
  json_mode_first_try_rate: 5/5
  ttft_p50_ms: 143
  ttft_p95_ms: 344
  end_to_end_p50_ms: 1472
  kvcache_verdict: OBSERVED (call1=0.90s call2=0.77s call3=0.71s)
  concurrency_table:
    N=2: 2/2 200, 0 429, 0 503, mean=10.25s
    N=4: 4/4 200, 0 429, 0 503, mean=0.81s
    N=8: 8/8 200, 0 429, 0 503, mean=1.09s
  recommend_llm_concurrency: 4

router_concurrency.txt: N=2/4/8 status mixes + per-call elapsed (justification data)
router_ttft.txt: per-call TTFT ms + p50/p95 computations
router_kvcache.txt: KVCACHE_VERDICT: OBSERVED (call1=0.90s call2=0.77s call3=0.71s)
```

**Status: GO**

TTFT p95=344ms gives 14.5x headroom against the 5s per-candidate timeout; JSON mode 5/5 first-try; LLM_CONCURRENCY=4 justified by N=2+N=4+N=8 all 200 with no 429/503; 50 schema-valid labelled records committed.

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

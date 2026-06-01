# SPIKE.md — Phase 1 Go/No-Go for artiscrapper v0

**Date:** __  **Operator:** Luis (or Claude on his behalf, per memory feedback_agent_as_uat_operator.md)

---

## Browser

- Cloak Docker tag `cloakhq/cloakbrowser:0.3.31` exists on Hub: __ (size __ MB, arches __, updated __)
- Cloak Python import path: `from cloakbrowser import ___`
- Cold-context fetch to `google.com/search?q=...&pws=0&hl=es&gl=ar` triggered consent interstitial: __
  - Markers hit: __
- `Browser.is_connected()` flips on:
  - SIGKILL Chromium: __ (lag __ s)
  - SIGSTOP Chromium: __ (lag __ s)
  - Network drop: __ (lag __ s)
- Ephemeral `new_context()` cookie isolation: __
- SERP fixtures captured: __ files under `tests/fixtures/serp/`

**Status: GO | NO-GO | NEEDS-PIVOT**

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

- __
- __
- __

**Status: GO | NO-GO | NEEDS-PIVOT**

---

## Overall Status

**Status: GO | NO-GO | NEEDS-PIVOT**

---
status: partial
phase: 02-mvp
source: ["02-VERIFICATION.md"]
started: 2026-06-02T08:00:00Z
updated: 2026-06-02T08:00:00Z
---

## Current Test

[awaiting human testing on live dev-box — Cloakbrowser + local-llms-router must be running, LLM_ROUTER_BEARER_TOKEN must be set]

## Tests

### 1. SC-2 — POST /search "filtro aceite ford focus" returns ≥10 products, ≥7 from real stores
expected: ≥10 products in response.results; at least 7 results come from real e-commerce stores (not link aggregators / blogs / wiki / youtube); metadata.cache_hit=false on first call
result: [pending]

### 2. SC-1 + SC-4 — POST /search "pelota playera quico" + cache hit on repeat
expected: First call returns ≥10 results in <30s, ≥6 with price non-null, zero blogs/wiki/youtube in top 10, metadata.cache_hit=false. Second identical call returns metadata.cache_hit=true in <500ms.
result: [pending]
how_to_run: `LLM_ROUTER_BEARER_TOKEN=$TOKEN E2E=1 uv run pytest tests/test_e2e.py -x -q -m e2e` (after `docker compose up` or `uv run uvicorn src.artiscrapper.main:app --loop asyncio --workers 1`)

### 3. SC-3 — GET /health <50ms on live service
expected: `{status:"ok",cloak:"ok",llm:"ok",cache:"ok"}` returned in <50ms (measured via `curl -w '%{time_total}\n' -o /dev/null -s http://localhost:8000/health`)
result: [pending]

### 4. SC-8 — `docker build .` produces single image; `docker run` boots /health in <10s
expected: `docker build -t artiscrapper .` succeeds; `docker run -e LLM_ROUTER_BEARER_TOKEN=$TOKEN -p 8000:8000 artiscrapper` → /health returns 200 within 10s of container start
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps

[None recorded yet — see VERIFICATION.md non-blocking warnings (WR-01..04) for cosmetic items the verifier suggests addressing in a future cleanup phase, but they do NOT block phase completion.]

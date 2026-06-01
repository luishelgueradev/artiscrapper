# 02 — LLM Curator (F-05) Design Research

**Date:** 2026-06-01
**Scope:** Local LLM filter step (PRD §3 step 5, F-05). Structured-output reliability against `local-llms-router`.
**Owner:** Luis Helguera

---

## Verdict (per question, confidence)

| # | Question | Verdict | Confidence |
|---|----------|---------|------------|
| 1 | Best model class for `{is_product, confidence, ...}` schema with ~250 in / ~80 out tokens | **Qwen 2.5 7B-Instruct** (default) or **Llama 3.1 8B-Instruct** (fallback for strict schema). Phi-4 14B if router has it provisioned. Avoid Mistral-Nemo for this small a schema — overkill. | HIGH |
| 2 | Per-candidate vs batched | **Per-candidate with bounded concurrency (sem=4)**. Batching is tempting but blows up parse-failure blast radius and the PRD has a 5s per-candidate timeout — that semantic only makes sense if calls are per-candidate. | HIGH |
| 3 | Failure modes & permissive fallback | `confidence=0.3` on timeout is correct (permissive — keep candidate, let downstream visit/re-rank decide). On malformed JSON: same path (`confidence=0.3`, `reason="llm_malformed"`). On router 5xx or 503: same. **Never let LLM failure drop a candidate** — that's a different decision (re-rank handles it). | HIGH |
| 4 | Prompt design | **Spanish system prompt + Spanish few-shot (2 examples)**. Queries are AR, results contain AR/ES content (e.g. "$ 18.032,30", "envío gratis"), and language-matched prompts improve classification 1-5 pp in the literature. Use a single-candidate template (one JSON in → one JSON out). | MEDIUM-HIGH |
| 5 | Latency budget on consumer GPU | A 7B Q4_K_M on RTX 3090/4090 produces ~80 output tokens in 800-1500ms wall-clock for short prompts. Grammar/JSON constraints add 30-80% (so 1000-2700ms). **5s per-candidate timeout is comfortable** for p95. For 30 candidates with `sem=4` → ~8-15s LLM phase wall-time. | MEDIUM |
| 6 | Schema enforcement strategy | **Two-layer:** (a) Send `format=<json_schema>` to `local-llms-router` if it supports Ollama-style structured output (token-level grammar — best); (b) Always re-validate with `pydantic.TypeAdapter` after parse. Fallback if router doesn't support structured: zero-shot JSON-mode + Pydantic parse + `tenacity` retry once. No need for `outlines`/`instructor` libs — the router does the heavy lifting; we just need a Pydantic model + parse-or-default. | HIGH |

---

## Findings

### Q1 — Model choice (router-agnostic recommendation)

Since we don't control which model is behind `local-llms-router`, we design **for the union of reasonable local models** and document the degraded path per model.

**Recommended tier (in order of fit for this task):**

1. **Qwen 2.5 7B-Instruct** — strongest JSON fluency among 7-8B class, AR/ES capable, ~100 tok/s on RTX 4090 Q4_K_M. *Significant improvements in generating structured outputs, especially JSON* per Qwen team's own published claims, corroborated by third-party benches.
2. **Llama 3.1 8B-Instruct** — slightly weaker raw JSON quality but **stronger strict-schema compliance** (lower hallucinated-key rate). Safest if router uses native function-calling.
3. **Phi-4 14B** — Microsoft's reasoning-tuned 14B, strong instruction following. If router has it and the 14B is fast enough on the host, prefer over 7B for ambiguous candidates. Otherwise overkill.
4. **Mistral-Nemo 12B** — works but no advantage over Qwen 2.5 7B on this small-schema task; bigger memory footprint.

**Tier to flag as risky (degrade-gracefully if encountered):**

- Gemma 2/3 9B and smaller: known to enter repetition loops during grammar-constrained JSON generation on free-text string fields (e.g. our `reason` field). Workaround: clamp `reason` with `max_length=140` in the schema and lower `max_tokens` aggressively (≤120).
- Anything <7B: hallucinated keys, dropped fields, schema drift. Don't use for production.

**Don't depend on a specific model.** The router exposes a model-agnostic HTTP endpoint; treat it as a black box and validate output shape on every call.

### Q2 — Per-candidate vs batched

| Dimension | Per-candidate (chosen) | Batched (1 call, all 30) |
|---|---|---|
| **Tokens** | 30 × 250 = 7500 in, 30 × 80 = 2400 out | 1 × ~7500 in, 1 × ~2400 out |
| **Latency wall-time** | ~8-15s with `asyncio.Semaphore(4)` | ~6-10s for a single 2400-output call |
| **Parse failure blast radius** | 1 candidate lost → others fine | 1 malformed JSON → potentially all 30 lost |
| **Per-item timeout semantics** | Clean (PRD §6: "LLM timeout 5s por candidato") | Impossible — timeout is over the whole batch |
| **Permissive fallback** | Trivial per item (`confidence=0.3`) | Hard — partial JSON recovery is fragile |
| **Context window pressure** | 250 in fits anything | 7500 in pressure on small models; Qwen 7B/Llama 8B handle it, smaller models degrade |
| **Output drift with batch size** | None | Research shows 6/8 models degrade <2pp through batch=100, but reasoning models collapse at large batches with parse failures up to 27-36 pp. Local models are not reasoning-tuned, but the asymmetry is real |
| **Ops simplicity** | Higher | Lower |

**Recommended:** per-candidate calls behind `asyncio.Semaphore(4)`. The semaphore is critical:
- Ollama's `OLLAMA_NUM_PARALLEL` default is 1 (recently bumped to 4 on newer versions); concurrency beyond that just queues.
- Without a semaphore, 30 simultaneous `httpx.post()` calls cause Ollama to return 503 once the queue (`OLLAMA_MAX_QUEUE=512`) cycles or to slow per-request throughput so badly that everything timeouts. *Running multiple Ollama requests simultaneously without rate limiting causes resource contention that pushes all of them toward timeout* (markaicode, 2026).
- Empirically, semaphore=4 maps cleanly to most `local-llms-router` configurations.

**Concurrency env to discover at startup** (don't hardcode):
```python
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "4"))
sem = asyncio.Semaphore(LLM_CONCURRENCY)
```

### Q3 — Failure modes & fallback policy

| Failure | Detection | Action | Rationale |
|---|---|---|---|
| **Timeout (>5s)** | `httpx.ReadTimeout` / `asyncio.TimeoutError` | `confidence=0.3`, `is_product=true`, `freshness_signal="unknown"`, `reason="llm_timeout"` | PRD §6 mandates 0.3 permissive. **Keep the candidate alive**; re-rank handles it. |
| **Malformed JSON** | `json.JSONDecodeError` or `pydantic.ValidationError` after parse | Same as timeout: `confidence=0.3`, `reason="llm_malformed"` | Don't punish the candidate for the LLM's failure. |
| **Refusal / "I cannot determine..."** | Heuristic: response text doesn't start with `{` after stripping markdown fences; or Pydantic validation fails on `is_product` type | Same fallback path | Refusal is just malformed JSON in disguise. |
| **Router 5xx** | `httpx.HTTPStatusError` 500-599 | `confidence=0.3`, `reason="llm_server_error"` | Degraded mode (PRD risk table line 2). |
| **Router 503 (overloaded)** | Status 503 | Retry **once** with 1s backoff (tenacity); on second fail → `confidence=0.3`, `reason="llm_overload"` | Ollama returns 503 when queue is full; a single retry usually clears it. |
| **Router 4xx (client error)** | Status 400-499 | **No retry.** `confidence=0.3`, `reason="llm_bad_request"`, log structured error (without payload contents) | Indicates schema mismatch on our side — should never happen in steady state but log loudly. |
| **`is_product=false`** | Valid LLM verdict | Drop candidate. | This is the LLM doing its job. |
| **`confidence < 0.4`** | Valid LLM verdict | Drop. | PRD §3 step 5 explicit cut. |
| **`freshness_signal="blog"`** | Valid LLM verdict | Drop. | PRD §3 step 5 explicit cut. |
| **All 30 calls fail** | Counter | Set degraded flag in response metadata; **don't fail the request**; fall back to heuristic filter (junk-domain blocklist, has-price-in-card) | PRD §10 success criteria say "zero blogs/wiki/youtube in top 10" — heuristic blocklist alone gets ~70% of the way. |

**Critical:** confidence=0.3 is a "shrug" value below the 0.4 cut. **This means LLM-failed candidates ARE DROPPED unless they have other signals** (price in card, MELI domain, etc.). Re-read PRD §3 step 5:

> *Descarte: is_product=false OR confidence<0.4 OR freshness="blog".*

So `confidence=0.3` is borderline — it gets dropped if alone. **The PRD's "permissive" framing means "don't fail loudly", not "keep the candidate"**. This is correct: a candidate that the LLM couldn't classify and that has no other positive signal probably is junk. **Document this clearly in the code comment**, because it's a foot-gun if someone later reads "permissive=0.3" and assumes it means "keep".

### Q4 — Prompt design

**Decision tree:**

- **Zero-shot vs few-shot:** Few-shot wins for this task. We have a tight schema and a recurring pattern (SERP card → product/not-product) that benefits from 2 concrete examples. Few-shot adds ~150 tokens to the prompt but lifts compliance by 5-15 pp for small models per the literature. With Qwen 2.5 7B's strong JSON priors, even zero-shot works, but few-shot is cheap insurance.
- **Language:** **Spanish system prompt + Spanish examples.** Queries are AR (e.g. "filtro aceite ford focus"), snippets contain Spanish + AR price format (`$\xa018.032,30`). *Language-matched prompts improved classification accuracy significantly* (ryanstenhouse.dev, multilingual prompt research). Spanish is a high-resource language for all the model candidates above.
- **System prompt vs in-message:** **System prompt for role + schema description; user message for the candidate JSON.** Cleaner trace, cleaner cache (system prompt is constant → KV cache stays warm in Ollama).
- **Chain-of-thought:** **NO.** 80 output tokens is tight; CoT blows the budget. The `reason` field is a one-liner justification, not a reasoning trace.

**Concrete template (literal text, ship this):**

```python
SYSTEM_PROMPT = """Sos un clasificador de resultados de búsqueda de Google para una casa de repuestos automotores en Argentina.

Tu tarea: dado un resultado de búsqueda (título + URL + snippet), decidir si es un PRODUCTO COMPRABLE concreto o ruido (blog, foro, Wikipedia, YouTube, noticia, página institucional).

Respondé ÚNICAMENTE con un objeto JSON válido con este esquema exacto:
{
  "is_product": bool,           // true sólo si es una página que vende UN producto comprable concreto
  "confidence": float,          // 0.0-1.0, qué tan seguro estás
  "price_hint": float|null,     // precio en ARS si lo ves en el snippet, sino null
  "store_hint": string|null,    // nombre de la tienda si lo identificás (ej "Mercadolibre", "Distribuidora Romero"), sino null
  "freshness_signal": string,   // uno de: "live_marketplace", "static_catalog", "blog", "unknown"
  "reason": string              // máximo 80 caracteres, en español
}

Reglas:
- Mercadolibre, Mercado Libre, MELI → freshness_signal="live_marketplace"
- Tienda con catálogo propio (mahle.com, mann-filter.com, etc.) → "static_catalog"
- Blog, foro, YouTube, Reddit, Wikipedia, Fandom, noticia → "blog" (is_product=false)
- Si no podés decidir → "unknown" con confidence baja (≤0.4)
- NO inventes precios. Si no ves el número en el snippet, price_hint=null.
- NO inventes tiendas. Si la URL no es clara, store_hint=null.

Devolvé sólo el JSON, sin markdown, sin explicaciones extras."""

FEW_SHOT_EXAMPLES = """
Ejemplo 1 — INPUT:
{"title":"Filtro Aceite Mahle Ford Focus 1.6 - $ 8.500","url":"https://www.mercadolibre.com.ar/MLA-12345","snippet":"Envío gratis. Stock disponible. Vendedor con +1000 ventas."}
OUTPUT:
{"is_product":true,"confidence":0.95,"price_hint":8500.0,"store_hint":"Mercadolibre","freshness_signal":"live_marketplace","reason":"Card MELI con precio y stock"}

Ejemplo 2 — INPUT:
{"title":"Cómo cambiar el filtro de aceite paso a paso","url":"https://taller-mecanico-blog.com/cambio-filtro","snippet":"Guía completa con fotos para hacer el mantenimiento vos mismo..."}
OUTPUT:
{"is_product":false,"confidence":0.97,"price_hint":null,"store_hint":null,"freshness_signal":"blog","reason":"Tutorial, no producto"}
"""

USER_TEMPLATE = """INPUT:
{candidate_json}
OUTPUT:"""
```

Total per-call prompt budget:
- System: ~280 tokens
- Few-shot block: ~180 tokens (sent as part of the system or first user turn — depends on router API shape)
- Per-candidate user message: ~50 tokens (the JSON)
- Output: ~80 tokens budget (cap with `max_tokens=128`)

**Total in: ~510, out: ~80.** Slightly over the PRD's 250in/80out estimate but the system prompt is constant — most routers will KV-cache it across the 30 calls in a query. Effective marginal cost per candidate ≈ 50 in / 80 out.

If the router does NOT cache system prompts across calls, drop few-shot for the first cut and measure. Qwen 2.5 7B zero-shot on this task is acceptable.

### Q5 — Latency budget

**Per-candidate (single LLM call):**

| Stage | RTX 3090, Q4_K_M, Qwen 2.5 7B | RTX 4090, same | Notes |
|---|---|---|---|
| Time-to-first-token (TTFT) | 150-300 ms | 100-200 ms | Includes prompt eval. Lower if KV-cached. |
| Output tokens | 80 tok × ~14 ms/tok = 1120 ms | 80 tok × ~10 ms/tok = 800 ms | Q4_K_M typical |
| **Without grammar constraint** | **~1300 ms p50** | **~900 ms p50** | |
| Grammar-constrained overhead (+30-80%) | +400-1000 ms | +300-700 ms | |
| **With grammar constraint** | **~1800-2300 ms p50** | **~1200-1600 ms p50** | |
| p95 | ~3500 ms | ~2500 ms | KV miss + longer outputs |
| **Within 5s timeout?** | **YES (comfortable)** | **YES (comfortable)** | |

**Per-query (30 candidates, sem=4):**

- Ideal parallelism: 30 / 4 = 7.5 batches of 4 → 8 sequential rounds.
- Round latency = max(4 parallel calls) ≈ p95 of single-call ≈ 3500 ms on RTX 3090.
- **Total LLM phase p50: 30/4 × ~2000ms ≈ 15s.** With KV warm: ~10-12s.
- **Total LLM phase p95: ~22s.** Borderline against PRD's "P50 cold <20s, P95 cold <40s".

**Implication:** The LLM phase is the dominant cost in cold path. If it consistently misses the 20s P50 budget:

1. First lever: drop few-shot examples (cuts ~30% of prompt eval).
2. Second lever: reduce `max_tokens` from 128 to 96. The `reason` field can be 60 chars.
3. Third lever: bump `LLM_CONCURRENCY` to 6 or 8 if the router supports it (verify with `OLLAMA_NUM_PARALLEL`).
4. Fourth lever: pre-filter with heuristic blocklist BEFORE the LLM step. Drops ~30% of obvious junk (youtube.com, wikipedia.org, fandom.com, reddit.com, .gov.ar). Don't LLM-filter what you can regex-filter.

**Concrete recommendation in MVP:**
- Implement heuristic blocklist as pre-filter (cheap, deterministic, no LLM cost).
- Run LLM filter on the ~20 survivors of pre-filter (not all 30 raw candidates).
- LLM phase budget shrinks to ~20/4 × 2s = **10s** — comfortably under PRD §10.

### Q6 — Schema enforcement

**Stack decision tree:**

1. **Does `local-llms-router` expose Ollama-style `format=<json_schema>` parameter?**
   - YES → use it. Token-level grammar constraint gives 100% structural validity (cannot emit invalid JSON). This is the gold path.
   - NO → use `format="json"` (JSON-only mode, available in nearly all router APIs incl. OpenAI-compat). Lower guarantee but Qwen 2.5 7B and Llama 3.1 8B have ~95% compliance on this small schema in JSON-only mode without grammar.

2. **In both cases**, always re-validate the parsed JSON with a Pydantic model on our side. The router does NOT validate semantic correctness against the schema (only structural for grammar mode). It WILL happily return `is_product="yes"` (string) when we asked for bool if it's only in JSON-mode without grammar.

3. **Do NOT introduce `instructor`, `outlines`, or `pydantic-ai`** to the project unless step 1 answer is NO and reliability is <95% on internal benches. Reasons:
   - `instructor` wraps SDK calls; we're using raw httpx against an internal router. Adds complexity without value.
   - `outlines` does constrained decoding client-side, but only works if you control the model loader (we don't — it's behind a router HTTP API).
   - `pydantic-ai` is for agent loops, not single-shot classification.

**Pydantic model (ship this):**

```python
from typing import Literal
from pydantic import BaseModel, Field

FreshnessSignal = Literal["live_marketplace", "static_catalog", "blog", "unknown"]

class LLMVerdict(BaseModel):
    is_product: bool
    confidence: float = Field(ge=0.0, le=1.0)
    price_hint: float | None = None
    store_hint: str | None = Field(default=None, max_length=80)
    freshness_signal: FreshnessSignal
    reason: str = Field(max_length=140)

    @classmethod
    def fallback(cls, reason: str) -> "LLMVerdict":
        """Permissive fallback when LLM fails. Note confidence=0.3 < 0.4 cut → candidate is dropped unless other signals."""
        return cls(
            is_product=True,
            confidence=0.3,
            price_hint=None,
            store_hint=None,
            freshness_signal="unknown",
            reason=f"llm_fail:{reason}",
        )
```

**Parse-and-fallback wrapper:**

```python
async def classify_candidate(client: httpx.AsyncClient, candidate: dict, sem: asyncio.Semaphore) -> LLMVerdict:
    async with sem:
        try:
            resp = await client.post(
                LLM_ROUTER_URL,
                json={
                    "model": LLM_MODEL,           # or omit if router auto-selects
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT + FEW_SHOT_EXAMPLES},
                        {"role": "user", "content": USER_TEMPLATE.format(candidate_json=json.dumps(candidate))},
                    ],
                    "format": "json",              # Ollama JSON mode; OR pass JSON Schema if router supports
                    "options": {"temperature": 0.0, "num_predict": 128},
                    "stream": False,
                },
                timeout=5.0,
            )
            resp.raise_for_status()
            raw = resp.json()["message"]["content"]      # adjust per router shape
            return LLMVerdict.model_validate_json(raw)
        except httpx.TimeoutException:
            return LLMVerdict.fallback("timeout")
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            return LLMVerdict.fallback(f"http_{getattr(e.response, 'status_code', 'err')}")
        except (json.JSONDecodeError, ValidationError):
            return LLMVerdict.fallback("malformed")
```

**One retry on 503 only** (via tenacity decorator) is optional but recommended — Ollama emits 503 transiently when its queue fills.

---

## Recommended Prompt Template

See Q4 above for literal text. Summary of choices:

- **Language:** Spanish system + Spanish few-shot.
- **Shots:** 2 (one positive MELI card with price; one negative blog/tutorial). No third shot — diminishing returns above 2 for schema this small.
- **Schema description:** Inline in the system prompt (not as a separate JSON Schema attachment) — works with any router API shape (Ollama, OpenAI-compatible, custom).
- **Temperature:** **0.0** — deterministic, cache-friendly, no creativity needed for classification.
- **max_tokens (`num_predict`):** **128** — enough headroom for the JSON; cap protects against runaway generation on small models (Gemma loop bug).
- **Stop sequences:** None needed with `format=json` mode.

---

## Schema Validation Strategy + Fallback Chain

```
LLM call
  │
  ├─► HTTP 200 ────► JSON parse ────► Pydantic validate ────► LLMVerdict (real)
  │                       │                  │
  │                       │                  └─► ValidationError ─► fallback("malformed")
  │                       │
  │                       └─► JSONDecodeError ─► fallback("malformed")
  │
  ├─► HTTP 503 ─► retry 1x with 1s backoff
  │                  │
  │                  ├─► 200 ─► (same as above)
  │                  └─► still 503 ─► fallback("overload")
  │
  ├─► HTTP 5xx (other) ─► fallback("server_error")
  ├─► HTTP 4xx ─► fallback("bad_request") + log loud
  ├─► Timeout ─► fallback("timeout")
  └─► Connection error ─► fallback("conn_error")

Downstream:
  All verdicts (real or fallback) flow through the same filter cut:
    is_product=false  → drop
    confidence < 0.4  → drop
    freshness="blog"  → drop

  ↳ fallback() returns confidence=0.3 → dropped unless re-rank surfaces other signals
    (NOTE: with current logic, fallback verdicts ARE dropped at filter. Document this.)
```

**Degraded mode (all LLM calls fail):**
- Detected by counter: if >50% of LLM calls in a single query return fallback, set `metadata.llm_degraded=true`.
- Apply heuristic filter only:
  - Drop URLs in blocklist (youtube.com, *.fandom.com, *.wikipedia.org, reddit.com, *.gov.ar, *.medium.com)
  - Keep cards with explicit price in SERP carousel
  - Keep URLs matching known store patterns (`mercadolibre.com.ar`, `mahle.com`, etc. — small whitelist)
- Return results with `confidence=0.5` for kept candidates and `metadata.llm_degraded=true` so the consumer knows.

---

## Latency Budget Breakdown

| Stage | p50 (target) | p95 (target) | Hard timeout |
|---|---|---|---|
| Cache lookup (sqlite) | 5 ms | 20 ms | 200 ms |
| Google fetch x2 (parallel, Cloak) | 4 s | 8 s | 15 s (per fetch) |
| Parser (selectolax, both SERPs) | 50 ms | 200 ms | 1 s |
| Dedupe | <10 ms | <30 ms | n/a |
| Heuristic pre-filter (blocklist) | <10 ms | <30 ms | n/a |
| **LLM filter (~20 candidates × sem=4)** | **8 s** | **15 s** | 5 s per candidate; 25 s phase |
| Visit pass (~7 visits, parallel) | 3 s | 7 s | 10 s per visit |
| Re-rank + serialize | <50 ms | <100 ms | n/a |
| **TOTAL (cold)** | **~16 s** | **~30 s** | within PRD §10 |
| **TOTAL (cache hit)** | **<300 ms** | **<500 ms** | within PRD §10 |

LLM is ~50% of cold-path budget — single biggest lever. If we miss P50 target, **first thing to tune is the pre-filter blocklist**, not the LLM.

---

## What NOT to do (anti-patterns)

1. **Don't batch all 30 candidates into one LLM call.** PRD's per-candidate timeout becomes meaningless and a single malformed array drops 30 candidates.
2. **Don't use temperature > 0.0.** Classification is deterministic. Higher temp = more JSON drift = more retries.
3. **Don't introduce `instructor`/`outlines`/`pydantic-ai`.** We're calling a black-box router over HTTP. A Pydantic model + try/except is enough. New libs = new dependency surface + new failure modes.
4. **Don't trust `format=json` alone.** It guarantees the response is JSON, NOT that fields match types/enums. Always run `pydantic.model_validate_json()`.
5. **Don't omit the semaphore.** 30 simultaneous httpx posts → Ollama 503 cascade → all candidates fall through to fallback → effectively no LLM filter. Use `sem=4` minimum.
6. **Don't put scraped content in logs.** PRD §6 constraint. Structlog with explicit field whitelist; never log `candidate_json` payload, only id/url/verdict.
7. **Don't use English prompts.** Queries are AR, content is ES. Language-matched prompts measurably improve classification on this kind of task.
8. **Don't tune the prompt against synthetic examples.** Capture 30-50 real SERP fixtures from Phase 0 spike + label them by hand → use as a regression set. Iterate prompt against the regression set.
9. **Don't auto-fail the request when LLM is down.** Degraded mode with heuristic blocklist + price-in-card retention is much better UX than a 503.
10. **Don't hardcode model name in the call.** Let the router pick the default (`model: null` or just omit). Lets the client switch behind the router without redeploying us.
11. **Don't retry malformed JSON.** The model's output distribution doesn't change between identical calls (temp=0). Retrying the same prompt that produced malformed JSON will produce malformed JSON again. Fallback immediately.
12. **Don't put few-shot examples in the user message.** They belong in system prompt so KV-cache treats them as constants across the 30 calls. Otherwise prompt eval re-runs 30 times — kills latency.
13. **Don't use `confidence=0.3` as a "keep" signal without documenting that it's actually below the 0.4 cut.** Foot-gun for the next person reading the code.

---

## Open questions to resolve in Phase 0 spike

1. **What model does `local-llms-router` route to by default?** Need to discover via a `GET /models` or equivalent. If it's something <7B, we have a problem.
2. **Does the router support `format=<json_schema>` (token-level grammar) or only `format=json`?** Determines whether we get 100% structural validity or just JSON-only mode.
3. **What's the actual KV-cache behavior across our 30 calls?** If the router re-evaluates the system prompt every time, our 510-token prompt cost is real. If it caches, marginal cost is 50 in / 80 out as planned. Measure with two back-to-back identical calls.
4. **Does the router enforce per-client concurrency limits?** If yes, our `sem=4` should match. If no, we set it.
5. **What's the median TTFT (time-to-first-token) on the host's actual GPU?** This determines whether our 5s timeout is comfortable or tight in practice.

These 5 questions are the spike's deliverable. Sub-1-day work.

---

## Sources

- [How to Get Structured JSON Output from Ollama with Pydantic — mljourney.com](https://mljourney.com/how-to-get-structured-json-output-from-ollama-with-pydantic/)
- [Reliable Structured Output from Local LLMs — markaicode.com](https://markaicode.com/ollama-structured-output-pipeline/)
- [Constraining LLMs with Structured Output: Ollama, Qwen3 — glukhov.org](https://www.glukhov.org/llm-performance/ollama/llm-structured-output-with-ollama-in-python-and-go/)
- [Best Local LLMs for Structured Output: Qwen 3.6, Gemma 4 — insiderllm.com](https://insiderllm.com/guides/structured-output-local-llms/)
- [Llama 3.1 8B Instruct vs Qwen2.5 7B Instruct — galaxy.ai](https://blog.galaxy.ai/compare/llama-3-1-8b-instruct-vs-qwen-2-5-7b-instruct)
- [Qwen2.5-LLM: Extending the boundary of LLMs — qwenlm.github.io](https://qwenlm.github.io/blog/qwen2.5-llm/)
- [Llama 3.1 8B Instruct vs Qwen2.5 7B Instruct Comparison — llm-stats.com](https://llm-stats.com/models/compare/llama-3.1-8b-instruct-vs-qwen-2-5-7b-instruct)
- [Researchers waste 80% of LLM annotation costs by classifying one text at a time — arxiv.org/2604.03684](https://arxiv.org/pdf/2604.03684) (batch vs per-item; reasoning models collapse at large batches)
- [JSONSchemaBench: A Rigorous Benchmark of Structured Outputs — arxiv.org/2501.10868](https://arxiv.org/html/2501.10868v3)
- [Generating Structured Outputs from Language Models — nathanrchn.com/p/jsb](https://nathanrchn.com/p/jsb) (Guidance wins; Outlines slow on enums/arrays)
- [Why Your LLM Prompts Should Match Your Content Language — ryanstenhouse.dev](https://ryanstenhouse.dev/why-your-llm-prompts-should-match-your-content-language/)
- [Beyond English: The Impact of Prompt Translation Strategies — arxiv.org/2502.09331](https://arxiv.org/html/2502.09331v1)
- [Multilingual Prompt Engineering in LLMs: A Survey — arxiv.org/2505.11665](https://arxiv.org/html/2505.11665v1)
- [How Ollama Handles Parallel Requests — glukhov.org](https://www.glukhov.org/llm-performance/ollama/how-ollama-handles-parallel-requests/)
- [Configure Ollama Concurrent Requests — markaicode.com](https://markaicode.com/ollama-concurrent-requests-parallel-inference/) (OLLAMA_NUM_PARALLEL, OLLAMA_MAX_QUEUE)
- [Ollama API Timeout Fix — aimadetools.com](https://www.aimadetools.com/blog/ollama-api-timeout-fix/) (httpx timeout patterns)
- [Ollama vs vLLM Performance Benchmark 2026 — sitepoint.com](https://www.sitepoint.com/ollama-vs-vllm-performance-benchmark-2026/) (Ollama 4 parallel default; vLLM 8-10x throughput at scale)
- [Top 5 Structured Output Libraries for LLMs in 2026 — dev.to/nebulagg](https://dev.to/nebulagg/top-5-structured-output-libraries-for-llms-in-2026-48g0)
- [Comparing Python Libraries for Structured LLM Extraction — mcginniscommawill.com](https://mcginniscommawill.com/posts/2025-11-27-structured-extraction-with-llms/)
- [GitHub Issue: Gemma 4 31B repetition loop during constrained JSON — ollama/ollama#15502](https://github.com/ollama/ollama/issues/15502)
- [GitHub Issue: structured output not enforced on qwen 3.5/gemma 4 — ollama/ollama#15540](https://github.com/ollama/ollama/issues/15540)
- [Small LLM Performance Benchmark — ascentcore.com](https://ascentcore.com/2026/04/01/small-llm-performance-benchmark/)
- [Home GPU LLM Leaderboard — awesomeagents.ai](https://awesomeagents.ai/leaderboards/home-gpu-llm-leaderboard/) (TPS by VRAM tier)

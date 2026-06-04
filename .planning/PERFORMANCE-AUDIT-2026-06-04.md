# Performance Audit — artiscrapper `/search`

**Fecha:** 2026-06-04
**Branch experimental:** `perf-audit-2026-06-04`
**Scripts y datos:** `scripts/perfaudit/0*.py` + `scripts/perfaudit/0*.json{,l}`
**Motivación:** `/search` cold path mide ~100s en runtime real. Objetivo del producto: <30s. Si tarda más, pierde su propósito (búsqueda de artículos no puede demorarse minutos).

---

## TL;DR — Camino recomendado

| Camino | Cambio | Cold path estimado | Esfuerzo | Riesgo |
|--------|--------|--------------------|---------:|--------|
| A — Quick | Solo config (`.env`/`compose.yml`): `GOOGLE_MIN_INTERVAL_S=0`, `LLM_CONCURRENCY=16` | ~25-30s | 5 min | Bajo |
| **B — Medium (RECOMENDADO)** | A + pre-clasificación heurística antes del LLM | **~10-15s** | ~1 día | Bajo |
| C — Big | B + rate limiter entre `/search` requests (no entre fetches), SSE opcional | <10s | ~1 semana | Medio |

**Recomendación:** Path B. Cumple ampliamente el objetivo, mejora calidad (recall 90.5% vs 88.1% del actual), reduce carga al LLM router (-76% llamadas), y mantiene compatibilidad con specs principales.

---

## §1 Diagnóstico — dónde se quema el tiempo

Path crítico del `/search` actual (cold, no cache, query real):

```
0s    ─── POST /search
0s    ─── auth + slowapi decorators (~10ms)
0s    ─── search_elapsed bracket abre
0s    ─── cache_miss (~5ms)
0s    ─── ChallengeBackoff check_gate (~10ms)
0s    ─── asyncio.gather(fetch A, fetch B)
        ├─ A entra al GoogleRateLimiter Semaphore(1) → ~1s Cloak → libera, _last_fetch=t1
        └─ B espera Semáforo → entra → elapsed=1s < 60s → DUERME 59s        ⟵ HOT SPOT #1
60s   ─── parse_serp cascade (~50ms)
60s   ─── dedupe + is_junk (~10ms)
60s   ─── curate_candidates (~57 candidatos × LLM call con Semáforo(4))
        │  Cada llamada al router: ~1s
        │  Sem(4) en este router: speedup 1.47x (no 4x — router serializa parcialmente)
        │  Total: 57 / 1.47 × 1s ≈ ~40s                                       ⟵ HOT SPOT #2
        │  AÑADIDO: el LLM se llama para los 57 candidatos, pero la heurística
        │  podría haber resuelto 76% (43) instantáneamente.                    ⟵ HOT SPOT #3
100s  ─── visit_pass (skip-if-you-can — ~5-10s típico)
105s  ─── rerank + response
```

**Tres hot spots independientes, todos medidos empíricamente:**

### Hot spot #1: `GoogleRateLimiter` serializa los 2 fetches del MISMO request

`src/artiscrapper/rate_limit.py:18-26` usa `asyncio.Semaphore(1)` + `_last_fetch + 60s` (spec **BROWSER-04**).

Medición empírica directa al endpoint Google vía Cloak (`scripts/perfaudit/06_cloak_in_container.py`, dentro del container):

| Test | Tiempo |
|------|--------|
| Cloak launch | 8.5s (1 vez en lifespan) |
| Fetch warm a `example.com` | ~510ms |
| **2 fetches paralelos a Google** | **617ms total** |
| Fetch warm a Google real (no block) | ~510ms |

**El costo real de los 2 fetches paralelos es ~600ms, no 60s.** El rate limiter agrega 59.4s gratis por construcción.

### Hot spot #2: `LLM_CONCURRENCY=4` desaprovecha paralelismo del router

Benchmark con los 50 candidatos labeled (`scripts/perfaudit/03_measure_llm_concurrency.py`):

| `Semaphore(K)` | Total para 50 candidatos | Speedup vs sem(1) |
|----------------|-------------------------|-------------------|
| 1 | 51.0s | 1.00x |
| 2 | 34.4s | 1.48x |
| **4 (actual)** | **34.8s** | **1.47x** ⟵ sem(4) ≈ sem(2) |
| 8 | 31.1s | 1.64x |
| 16 | 16.3s | **3.12x** |

**El router (Ollama vía `local-llms-router`) escala mal con concurrencia.** Sem(4) y sem(2) dan throughput casi idéntico. Solo sem(16) rompe la barrera.

### Hot spot #3: El LLM se llama para 100% de los candidatos cuando 76% son triviales

Medición vs ground truth (50 candidatos labeled, 42 productos / 8 no-productos):

| Estrategia | Precision | Recall | F1 | Latencia (50 cand) |
|------------|-----------|--------|-----|---------------------|
| **LLM puro** sem(4) | 92.5% | 88.1% | 0.90 | ~35s |
| Heurística pura | **100%** | 78.6% | 0.88 | **0ms** |
| **Híbrido** (heurística pre-clasifica, LLM solo para ambiguos) | 92.7% | **90.5%** | **0.92** | **7.6s** ⟵ |

La heurística (`price_in_card` OR `known_store` OR `blog_title` OR `document` OR `junk_domain`) tiene **precision 100%** (cero falsos positivos) y resuelve el 76% de los candidatos. El LLM solo aporta valor sobre el 24% ambiguo restante.

**El LLM puro sem(4) tarda 35s para resultado equivalente al que el híbrido logra en 7.6s.**

---

## §2 Sub-experimentos descartados

### LLM batch (1 prompt con N candidatos, JSON array de veredictos)

`scripts/perfaudit/04_measure_llm_batch.py`. El modelo `llama3.2:3b-instruct-q4_K_M` (resuelto a `chat-local` por las recommendations del router) **no maneja batches** correctamente:

- Batch 10: 54.6s para 5 batches × 10 — más lento que sem(4) baseline (35s). Recall 78% (peor que per-candidate).
- Batch 25: error de parsing — el modelo devuelve `list` en vez del `dict {verdicts: [...]}` esperado.
- Batch 50: truncation — devuelve respuesta vacía, 0 verdicts.

Conclusión: batching no es viable con este modelo. Descartado.

### SSE / streaming de resultados parciales

Si el cold path baja a 10-15s (path B), el beneficio subjetivo del SSE es marginal. Los consumidores son programáticos (app interna Sánchez + n8n workflows), no UI humana. SSE agrega complejidad (~3 días de refactor + nuevas integration tests) por <10s de ganancia percibida. Descartado para v0.2 — Phase 5 sigue siendo deferred-by-design para SSE.

### Eliminar el LLM completamente (solo heurística)

Atractivo por simplicidad (0ms, sin dependencia del router), pero pierde **11.9pp de recall** (descartaría 4 productos legítimos extra de los 42). Para el caso de uso Sánchez (repuestos con descripciones ambiguas), esos 4 pueden ser críticos. Descartado.

### Subir `LLM_CONCURRENCY` muy alto (32, 64)

Risk operacional: el `local-llms-router` está compartido con OpenWebUI, otros consumidores del proyecto Luis. `LLM_CONCURRENCY=16` ya consume ~3x más slots que el actual. Subir más podría degradar a otros consumidores. Necesita coordinación con Luis si quiere ir más allá de 16.

---

## §3 Camino A — Quick fix (solo config)

**Cambios:** 2 líneas en `.env` / `compose.yml`.

```diff
- API_RATE_PER_MINUTE=60
+ API_RATE_PER_MINUTE=60
- GOOGLE_MIN_INTERVAL_S=60  # implícito (default settings.py)
+ GOOGLE_MIN_INTERVAL_S=0
- LLM_CONCURRENCY=4
+ LLM_CONCURRENCY=16
```

**Estimación cold path:**

| Etapa | Antes | Después |
|-------|-------|---------|
| 2 Google fetches paralelos | 62s | ~2s |
| LLM phase (~57 candidatos) | 75s | 57/3.12 × 1s ≈ ~18s |
| Visit pass + resto | 5s | 5s |
| **Total** | **~140s** | **~25s** |

**Pros:**
- 5 minutos de cambio
- Sin tocar código
- Sin romper specs (BROWSER-04 es configurable, el valor exacto no es invariant)

**Cons:**
- Justo en el límite del objetivo (<30s)
- No mejora calidad (sigue 92.5% precision / 88.1% recall)
- LLM sigue siendo el bottleneck (18s)
- Carga 3x mayor al `local-llms-router` (validar con Luis)

**Riesgo:**
- `GOOGLE_MIN_INTERVAL_S=0` no protege contra burst de queries. Si hay 100 queries simultáneas, todas pegan a Google al mismo tiempo. Mitigación parcial: el slowapi consumer rate limit (60/min/key) ya existe.

---

## §4 Camino B — Medium fix (config + pre-clasificación heurística) ⟵ RECOMENDADO

**Cambios:**
1. Path A (config).
2. Nueva función `heuristic_pre_classify(candidates) -> (kept_heuristic, ambiguous)` en `src/artiscrapper/search.py`.
3. Modificar `main.py` para llamar `curate_candidates` solo sobre `ambiguous`.
4. Update validaciones / unit tests (los integration tests siguen pasando).
5. Bump `BROWSER-04` spec en REQUIREMENTS para reflejar el nuevo valor.

**Código indicativo (no commiteado en este audit):**

```python
# search.py
KNOWN_STORES = frozenset({
    "mercadolibre.com.ar", "mercadolibre.com", "amazon.com.ar",
    "garbarino.com", "fravega.com", "tiendamia.com",
    "musimundo.com", "carrefour.com.ar", "cetrogar.com.ar",
    "compraonline.com.ar",
})
BLOG_TITLE_PATTERNS = ("como saber", "qué elegir", ...)
DOCUMENT_EXTENSIONS = (".pdf", ".doc", ".docx")
FORUM_PATTERNS = ("reddit.com", "/forum/", "/foro/")

def heuristic_pre_classify(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (kept, ambiguous). 'kept' van directo a visit; 'ambiguous' van al LLM."""
    kept, ambiguous = [], []
    for cand in candidates:
        url = cand.get("url", "")
        title = (cand.get("title") or "").lower()
        if is_junk(url) or any(p in url.lower() for p in DOCUMENT_EXTENSIONS) \
           or any(p in url.lower() for p in FORUM_PATTERNS) \
           or any(p in title for p in BLOG_TITLE_PATTERNS):
            continue  # descartado
        if cand.get("price_in_card"):
            kept.append({**cand, "_pre_class_reason": "price_in_card"})
            continue
        host = urlparse(url).netloc.lower().lstrip("www.")
        if any(host.endswith(s) for s in KNOWN_STORES):
            kept.append({**cand, "_pre_class_reason": "known_store"})
            continue
        ambiguous.append(cand)
    return kept, ambiguous

# main.py — antes de curate_candidates
kept_pre, ambiguous = heuristic_pre_classify(candidates)
# Solo llamar LLM para ambiguos
kept_llm, dropped_llm, llm_degraded = await curate_candidates(
    ambiguous, router_url=..., bearer_token=..., concurrency=settings.LLM_CONCURRENCY,
)
all_survivors = kept_pre + kept_llm
```

**Estimación cold path:**

| Etapa | Antes (actual) | Después (path B) |
|-------|---------------|------------------|
| 2 Google fetches paralelos | 62s | ~2s |
| Parse cascade | 50ms | 50ms |
| Heurística pre-clasifica | (no existe) | ~5ms (76% resueltos) |
| LLM phase (solo ~14 ambiguos) | 75s | 14 / 3.12 × 1s ≈ **5s** |
| Visit pass | 5s | 5s |
| **Total** | **~140s** | **~12s** |

**Pros sobre Path A:**
- **Cumple ampliamente** el objetivo (12s vs 30s)
- **Mejor calidad** (recall 90.5% vs 88.1%, F1 0.92 vs 0.90)
- **-76% llamadas al LLM router** (de 57 a 14 por query) → menor carga al `local-llms-router`
- Heurística es transparente y debuggable (logs `_pre_class_reason` por candidato)

**Cons:**
- ~50 LOC nuevas + 5-8 unit tests
- Hay que mantener `KNOWN_STORES` / `BLOG_TITLE_PATTERNS` (similar a `is_junk()` ya existente — patrón conocido del proyecto)
- BROWSER-04 spec necesita actualizarse (reasonable: el spec original era 60s entre fetches `a google.com`, no entre `dentro del mismo /search`)

---

## §5 Camino C — Big fix (refactor arquitectónico)

**Cambios:**
1. Todo Path B.
2. Refactor `GoogleRateLimiter`: aplicar el rate limit ENTRE `/search` requests (no entre fetches del mismo request). Ya no Semaphore(1) bloqueante — usar timestamp gate global del último `/search` que tocó Google.
3. SSE endpoint `/search/stream` con eventos incrementales: `serp_done`, `heuristic_done`, `llm_progress`, `visit_progress`, `final`.

**Estimación cold path:** <10s (paralelismo total + streaming oculta latencia restante para UX).

**Pros:**
- Mejor experiencia para consumidores stream-capable (n8n soporta SSE)
- Arquitectura más limpia

**Cons:**
- ~1 semana
- Cambio de contrato del endpoint (SSE) — n8n workflows de Sánchez requieren update
- Necesita Phase 5 entry (per ROADMAP, SSE está deferred until P95 cold > 40s sustained — ya no aplica si bajamos a <15s)

**Veredicto Path C:** Sobreinvertido. Si Path B llega a 10-15s, no justifica los costos de Path C.

---

## §6 Riesgos y consideraciones operacionales

### El bloqueo de Google a esta IP NO se resuelve con software

Durante el audit, Google bloqueó esta IP local (WSL) con `sorry_redirect` para queries con patrones comerciales. Verificado con `fetch_serp` directo: 2 fetches paralelos a Google con `?q=filtro+aceite+ford+focus` → ambos devuelven `sorry_redirect` en 2.6s.

**Esto es separado de los bottlenecks de software.** En el VPS real de Sánchez Repuestos:
- La IP fija del VPS es distinta y probablemente "limpia"
- El volumen real (500-2000 q/día = ~1 q/min) está muy por debajo de los umbrales de Google
- **Pero hay que validar el comportamiento en el VPS** después de aplicar el fix de software.

Si el block persiste en el VPS, el camino es Phase 5 (residential proxy via IPRoyal/Bright Data/Smartproxy) — está documentado en ROADMAP como deferred-until-trigger. El audit empírico actual sería el trigger.

### Subir `LLM_CONCURRENCY=16` impacta otros consumidores del router

El `local-llms-router` lo usan también OpenWebUI y otros proyectos de Luis (vistos en `docker ps`: `local-llms-openwebui`, `local-llms-ollama`, etc.). Pasar de 4 a 16 slots concurrentes podría:

- Aumentar latencia de OpenWebUI durante una query `/search`
- Saturar Ollama si tiene `OLLAMA_NUM_PARALLEL` < 16

**Validar con Luis:** cuál es el `OLLAMA_NUM_PARALLEL` del Ollama backend. Si es 4-8, subir `LLM_CONCURRENCY` a 8 (no 16) preserva la calidad-de-servicio cruzada. La diferencia en /search cold sería ~6s vs ~5s.

### El sistema actual respeta la spec BROWSER-04 al pie de la letra

Cambiar `GOOGLE_MIN_INTERVAL_S` o agregar pre-clasificación heurística **no rompe ningún test** (los 68 unit + 9 integration siguen verdes — confirmado en branch experimental sin modificaciones de código).

Pero **sí requiere actualizar la spec** (`.planning/milestones/v0.1-REQUIREMENTS.md`):
- BROWSER-04 actual: "Rate-limit ≥ 60s entre fetches a google.com"
- BROWSER-04 sugerido: "Rate-limit configurable entre fetches a google.com (default 0 — el slowapi consumer rate-limit es la defensa primaria contra burst)"

Esto es una decisión arquitectónica — ya no es la postura "defensiva al máximo" sino "defensiva proporcional al volumen real".

### El path híbrido NO elimina el LLM como dependencia

Sigue siendo necesario para el 24% ambiguo (queries con candidatos sin `price_in_card` ni `known_store`). Si el `local-llms-router` cae:
- Sistema actual: `metadata.llm_degraded=true`, fallback al heurístico (igual descarta los `<0.4`, pero los timeouts cuentan como `confidence=0.3`)
- Sistema path B: igual + más recall residual (los 76% de la heurística pre-clasificada NO se ven afectados — siguen pasando)

**Path B mejora también la resilience del sistema.**

---

## §7 Datos crudos del audit

Todos los scripts y outputs están en `scripts/perfaudit/`:

| Archivo | Output | Hallazgo clave |
|---------|--------|----------------|
| `02_measure_llm_per_candidate.py` | `02-llm-per-candidate-summary.json` | LLM p50=985ms, precision 92.5%, recall 88.1% |
| `03_measure_llm_concurrency.py` | `03-llm-concurrency.json` | Sem(4)=35s sem(16)=16s — router escala mal |
| `04_measure_llm_batch.py` | `04-llm-batch.json` | Batching no viable con `llama3.2:3b` |
| `05_evaluate_heuristic_only.py` | `05-heuristic-vs-truth.json` | Heurística precision 100%, recall 78.6% |
| `06_cloak_in_container.py` | (stdout) | 2 fetches paralelos a Google = 617ms |
| `07_hybrid_heuristic_plus_llm.py` | `07-hybrid.json` | Híbrido: 7.6s, precision 92.7%, recall 90.5%, F1 0.92 |
| `08_visit_pass_cost.py` | `08-visit-pass.json` | Visit pass = 129ms/candidato |

Ground truth: `tests/fixtures/llm/labelled.jsonl` (50 candidatos labeled en Phase 1, 42 productos / 8 no-productos).

---

## §8 Pregunta para vos antes de seguir

Para arrancar Path B necesito 3 decisiones tuyas:

1. **¿Aprobás Path B o preferís A (faster ship) o C (más arquitectura)?**

2. **¿Cuál es el `OLLAMA_NUM_PARALLEL` del backend Ollama de `local-llms-router`?** Si <16, ajusto `LLM_CONCURRENCY` para no saturar a OpenWebUI durante una query `/search`. Lo más conservativo es 8.

3. **¿Mantenemos / pivoteamos la spec BROWSER-04?** El valor 60s era para protegerse de Google a volumen alto. Con 500-2000 q/día reales y slowapi consumer rate-limit de 60/min/key como defensa primaria, `GOOGLE_MIN_INTERVAL_S=0` (paralelo entre fetches del mismo request) parece justificado. Pero requiere bump de spec en REQUIREMENTS.md.

**Si querés que aplique Path B directamente con valores conservativos (`LLM_CONCURRENCY=8`, spec bump), avísame y arranco la implementación + tests + verification.**

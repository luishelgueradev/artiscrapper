# PRD — `artiscrapper` v0.1

**Author:** Luis Helguera · **Client:** Sánchez Repuestos · **Date:** 2026-06-01 · **Status:** Draft

## 1. Identity

- **Name:** `artiscrapper` (reset — historia git previa descartada)
- **Successor of:** versión 1 del proyecto homónimo, descartada tras evidencia operacional: MELI scraping directo no factible sin proxy residencial, arquitectura multi-fuente sin fuentes activas no se justifica, Google + LLM-curator entrega 90% del valor a 1/10 de la complejidad.

## 2. Core Value

**Si solo una cosa tiene que funcionar bien**: el endpoint `/search?q=...` recibe una query, dispara 2 fetches a Google (`q` y `q +mercadolibre`), filtra con LLM local para quedarse solo con productos comprables, valida live + precio visitando los survivors cuando hace falta, y devuelve un JSON ordenado por relevancia. El consumidor recibe productos que existen, con precio, link y procedencia clara.

## 3. Functional Flow

```
INPUT: query string (ej. "filtro aire ranger")

1. Cache lookup (sqlite, TTL 24h). Si hit → return.

2. Fetch en paralelo dos SERPs vía Cloakbrowser:
   - URL A: google.com/search?q={query}&hl=es&gl=ar
   - URL B: google.com/search?q={query} mercadolibre&hl=es&gl=ar

3. Parser unificado de ambos HTMLs:
   - Organic (div.tF2Cxc)         → title + url + snippet + optional inline price
   - Carousel cards (div.Ez5pwe)  → title + price + store (URL sintética al store)
   - Knowledge panels, ads, "people also ask" → ignorar
   → Lista CRUDA de N candidatos (típicamente 20-40 entre los dos SERPs).

4. Dedupe por URL canónica (strip tracking params, normalize host).

5. LLM filter — modo estructurado (Caso 1c — elección del cliente):
   Prompt por candidato al local-llms-router:
     INPUT:  { title, url, snippet, price_hint?, store_hint? }
     OUTPUT: {
       is_product: bool,
       confidence: 0.0-1.0,
       price_hint: number?,
       store_hint: string?,
       freshness_signal: "live_marketplace" | "static_catalog" | "blog" | "unknown",
       reason: string (corto)
     }
   Descarte: is_product=false OR confidence<0.4 OR freshness="blog".
   Timeout LLM 5s por candidato; on timeout marca confidence=0.3 (permisivo).

6. Visit pass — SOLO si (price is None) AND (freshness != "live_marketplace"):
   - httpx GET con timeout 10s, en paralelo (asyncio.gather)
   - 200 → parser ligero (selectolax) extrae JSON-LD Product, Schema.org Offer, OG price
   - 404/redirect → flag skip_dead
   - 5xx / timeout → flag visit_failed
   Skip-if-you-can: si el card ya trae precio + es MELI/store conocido, se salta.

7. Freshness final:
   - MELI link + 200 → fresh=true
   - JSON-LD datePublished < 90d O <time datetime="..."> < 90d → fresh=true
   - LLM freshness_signal="blog" → ya descartado en step 5
   - Sino → fresh=unknown (mantener pero baja confidence)

8. Re-rank: ordenar por (has_price DESC, fresh DESC, llm_confidence DESC).

9. Output JSON: top max_results survivors.
```

## 4. Tech Stack

| Layer | Pick | Versión |
|---|---|---|
| Lenguaje | Python | 3.12 |
| HTTP framework | FastAPI | 0.136+ |
| Browser (Google) | Cloakbrowser (Chromium 146) | 0.3.28 |
| HTTP client | httpx | 0.28+ |
| HTML parser | selectolax | 0.4+ |
| LLM client | httpx contra `local-llms-router` existente | — |
| Cache | sqlite (`aiosqlite`) | stdlib + ~1 dep |
| Container | 1 imagen Docker (Cloak embebido vía Playwright) | — |
| Tests | pytest + pytest-asyncio + respx | últimas |
| Lint/format | ruff | 0.15+ |
| Project mgmt | uv | 0.11+ |
| Logging | structlog | 25+ |

**NO incluir**: Postgres, Redis, RQ, Alembic, Camoufox, browser-pool desacoplado, multi-engine, async workers, SSE, circuit breakers, dispatcher, orchestrator multi-source.

## 5. API Contract

### Endpoint único

```
POST /search
{
  "query": "filtro aceite ford focus 1.6",
  "max_results": 15,        // default 15, max 30
  "visit_timeout_s": 10     // default 10
}
```

### Response

```json
{
  "query": "filtro aceite ford focus 1.6",
  "results": [
    {
      "title": "Filtro Aceite Ford Focus 1.6 Mahle",
      "url": "https://www.mercadolibre.com.ar/...",
      "store": "Mercadolibre.com.ar",
      "price": {"value": 8500.00, "currency": "ARS"},
      "fresh": true,
      "live": true,
      "confidence": 0.92,
      "source_serp": "both",
      "extraction": "carousel"
    }
  ],
  "metadata": {
    "elapsed_ms": 18450,
    "google_fetches": 2,
    "candidates_total": 32,
    "llm_filtered_out": 14,
    "visited": 8,
    "visit_failed": 2,
    "cache_hit": false
  }
}
```

### Health

```
GET /health → {"status":"ok","cloak":"ok","llm":"ok","cache":"ok"}
```

## 6. Constraints (no negociables)

- **Rate limit Google interno**: 1 query/min máx (default). Configurable. Por encima → riesgo cierto de challenge.
- **Cache obligatorio**: NUNCA disparar Google sin chequear sqlite previo.
- **LLM timeout 5s** por candidato. On timeout: `confidence=0.3` (permisivo).
- **Visit pass solo si necesario**: nunca visitar links que ya tienen precio en SERP ni MELI links.
- **Persistir `raw_serp_html`** en cache para forensics (no en response).
- **No loguear contenido scrapeado** en logs estándar.
- **NO scrapear MELI directamente**. MELI catalog data sale vía Google (`+mercadolibre` query).
- **Headed antes que headless** para probar fuentes nuevas.

## 7. Roadmap

| Fase | Duración | Entrega |
|---|---|---|
| **0 — Spike** | 1 día | Confirmar local-llms-router maneja el prompt estructurado <3s; Cloak desde IP fresca pasa Google a 1/min; formato JSON-LD esperado en stores AR. |
| **1 — MVP** | 2-3 días | Endpoint `/search` end-to-end. Cache sqlite. 1 container Docker. Tests unit del parser + integration con LLM mockeado. |
| **2 — Robustez** | 1 semana | Métricas Prometheus, health checks reales, rate limit por API key, detección+backoff de challenges Google, degraded mode si LLM cae, integration tests vs fixtures reales. |
| **3 — Operación** | a demanda | Grafana dashboard, Sentry, cache invalidation endpoint, tracing si la latencia lo justifica. |
| **4 — Diferido** | si Sánchez crece | Adapters per-supplier directos (Mayorista Frog, Distribuidora Romero, etc.); proxy residencial; async+SSE; auth tiers. |

## 8. Volumen y Costos

- **Volumen esperado**: 500-2000 queries/día (uso interno Sánchez)
- **Google fetches**: 2/query × 2000 = 4000/día. Con cache hit 30% baja a ~2800/día
- **LLM tokens**: ~250 in / ~80 out por candidato × ~30 candidatos/query = ~10k tokens/query. Costo en router local ≈ **$0**.
- **Visit pass**: ~7 visitas/query (skip-if-you-can) × 2000 = ~14k visitas/día
- **Hosting**: mismo VPS donde corre el router local. Un container más. Costo neto **~$0/mes** vs $80-300/mes del path con proxy residencial.

## 9. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Google bloquea IP del VPS | Medium | Cache agresivo + rate limit 1/min + headed canary semanal |
| LLM router cae | Medium | Degraded mode (confianza baja, sigue sirviendo con filtro heuristic) |
| Algunos stores con anti-bot en visit step | Medium | Aceptar `visit_failed` flag; el LLM ya descartó la basura antes |
| JSON-LD ausente en stores menores | High | Fallback a regex de precio AR (heredado del proyecto viejo) |
| Sánchez quiere data MELI-específica (variants, stock, seller_id) | Low | Documentar fuera de scope. Si aparece, evaluar Partner Program. |

## 10. Success Criteria

- `/search?q=pelota+playera+quico` → ≥10 productos en <30s, ≥6 con precio
- `/search?q=filtro+aceite+ford+focus` → ≥10 productos, ≥7 de tiendas reales
- **Zero blogs/wiki/youtube en top 10** (gracias al LLM filter)
- Cache hit ratio ≥30% tras 1 semana
- P50 cache hit <500ms · P50 cold <20s · P95 cold <40s
- Sistema en 1 container, alcanzable desde n8n/app interna sin cambios upstream

## 11. Out of Scope (explícito)

- Scraping directo de MercadoLibre (cualquier endpoint `*.mercadolibre.*`)
- Proxy residencial / mobile proxy / cualquier IP rotation
- Multi-engine browser fallback (Cloak es suficiente para Google)
- Async + SSE para `/search`
- Workers / RQ / Redis / message queues
- Postgres + Alembic
- Authentication multi-tenant (un solo cliente: Sánchez)
- Marketplaces que no aparecen en Google (eBay AR, Tiendanube específicas, etc.)

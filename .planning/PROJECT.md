# artiscrapper

## What This Is

Servicio HTTP que dada una query de búsqueda (e.g. `"filtro aire ranger"`) devuelve una lista curada de productos comerciales que reflejan lo que una persona vería buscando en Google manualmente, enriquecidos con precio, validación de destino vivo, y filtrados por un LLM local para descartar blogs/wikis/contenido irrelevante. Cliente único: **Sánchez Repuestos** (taller / casa de repuestos AR) — alimenta su app interna de gestión de productos y pedidos + workflows n8n.

## Core Value

**Si solo una cosa tiene que funcionar bien**: el endpoint `/search?q=...` recibe una query, dispara 2 fetches a Google (`q` y `q +mercadolibre`), filtra con LLM local para quedarse solo con productos comprables, valida live + precio visitando los survivors cuando hace falta, y devuelve un JSON ordenado por relevancia. El consumidor recibe **productos que existen, con precio, link y procedencia clara**.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] **F-01** Endpoint `POST /search?q=<query>` síncrono que devuelve JSON ordenado por relevancia
- [ ] **F-02** 2 fetches paralelos a Google (raw + `+mercadolibre`) vía Cloakbrowser 0.3.28 (Chromium 146)
- [ ] **F-03** Parser unificado que extrae: organic results (`div.tF2Cxc`) + carousel cards (`div.Ez5pwe`)
- [ ] **F-04** Dedupe por URL canónica (strip tracking params, normalize host)
- [ ] **F-05** LLM filter estructurado contra `local-llms-router` con output `{is_product, confidence, price_hint, store_hint, freshness_signal, reason}`
- [ ] **F-06** Visit pass condicional (skip-if-you-can): solo si `price is None AND freshness != "live_marketplace"`; extrae JSON-LD/Schema.org/OG price
- [ ] **F-07** Freshness assessment: MELI link + 200 → fresh; JSON-LD datePublished <90d → fresh; LLM "blog" → descartado
- [ ] **F-08** Re-rank: ordenar por `(has_price DESC, fresh DESC, llm_confidence DESC)`
- [ ] **F-09** Cache sqlite con TTL 24h por query (cache key = query normalizada)
- [ ] **F-10** Endpoint `GET /health` con probes: cloak, llm, cache
- [ ] **NF-01** 1 imagen Docker, sin Postgres/Redis/RQ/Alembic/Camoufox/worker-pool
- [ ] **NF-02** Cobertura tests unit del parser + integration con LLM mockeado
- [ ] **NF-03** Logging structlog estructurado (no loguear contenido scrapeado)
- [ ] **NF-04** Rate limit interno Google: máx 1 query/min (configurable)
- [ ] **NF-05** Métricas Prometheus en `/metrics` (Fase 2+)
- [ ] **NF-06** Volumen target: 500-2000 queries/día sin estrangulamiento

### Out of Scope

- **Scraping directo de MercadoLibre** (cualquier `*.mercadolibre.*` endpoint) — IP-blocked sin proxy residencial; mitigación deferida a Fase 3 del PRD viejo, nunca arrancada. Catálogo MELI sale vía Google con `+mercadolibre`.
- **Proxy residencial / mobile / IP rotation** — costo + fricción no justificados a este scope (volumen 500-2000/día desde 1 IP soporta cache + rate-limit).
- **Multi-engine browser fallback** (Camoufox como Plan B) — Cloak es suficiente para Google; el proyecto anterior probó que Camoufox no agregaba valor real para esta fuente.
- **Async + SSE** para `/search` — sync HTTP es suficiente para los tiempos esperados (P50 cold <20s).
- **Workers / RQ / Redis / message queues** — sync HTTP cubre el caso de uso sin la complejidad operativa.
- **Postgres + Alembic** — sqlite local cubre el cache, no hay datos relacionales que justifiquen RDBMS.
- **Authentication multi-tenant** — un solo cliente (Sánchez), header API-key estático alcanza.
- **Marketplaces que no aparecen en Google** (eBay AR, Tiendanube específicas) — Google es el descubridor; lo que Google no muestra, fuera de scope.
- **Adapters per-supplier directos** (Mayorista Frog, Distribuidora Romero, etc.) — diferido a Fase 4 si Sánchez crece; hoy Google + LLM curator alcanza.
- **Partner Program MELI** — investigado, bureaucratic, no garantizado, deferido indefinidamente.

## Context

- **Successor of**: versión 1 de artiscrapper (descartada 2026-06-01, git history wiped). v1 tenía ~15.000 LOC, 5 containers Docker, 6 fases roadmap, multi-source orchestrator con browser-pool desacoplado. Entregaba ~7 productos por query sin precio confiable. MELI directo bloqueado por WAF a nivel IP. Multi-source vacío sin sources activas. **La complejidad arquitectónica no se justificaba sin fuentes activas además de Google.** El v0 actual destila el aprendizaje a un sistema 1/10 del tamaño.
- **Knowledge preservado del v1** (en código futuro): parser de Google SERP (`div.tF2Cxc`, `div.Ez5pwe`, h3), extracción precio AR (`$\xa018.032,30` → Decimal con punto-miles/coma-decimal), junk-domain blocklist (youtube/fandom/etc), setup Cloakbrowser para Google.
- **Cliente operacional**: Sánchez Repuestos ya tiene app de gestión + workflows n8n en producción. Este servicio se enchufa como dependencia HTTP. **No bloquea operación actual** — degradación graceful si cae.
- **LLM router local**: el cliente ya tiene `local-llms-router` corriendo en el mismo VPS (containers `local-llms-*` siguen vivos post-reset, healthy). Se reutiliza vía httpx — no agregar dependencias nuevas de modelo.
- **Volumen real esperado**: 500-2000 queries/día, mayormente del lado-app interna. n8n agrega un workflow más sincrónico.
- **Owner técnico**: Luis Helguera (Objetiva.com.ar).

## Constraints

- **Tech stack — Python 3.12**: continuidad con conocimiento existente; cloakbrowser/camoufox son first-class allí (aunque solo usamos Cloak).
- **HTTP framework — FastAPI**: rápido, OpenAPI auto-generado, async-friendly, convención global del taller.
- **Browser — Cloakbrowser 0.3.28 (Chromium 146.0.7680.177.4)**: la única pieza del stack viejo que sí agrega valor — Google detecta Playwright stock en <5 requests.
- **HTML parser — selectolax 0.4+**: validado contra fixtures reales del v1; ~10x más rápido que BeautifulSoup.
- **HTTP client — httpx 0.28+**: async, HTTP/2, retry-friendly.
- **Cache — sqlite (aiosqlite)**: stdlib + 1 dep; TTL 24h por query.
- **LLM client — httpx contra `local-llms-router`**: servicio existente del cliente, mismo VPS, no agregar dependencia de modelo.
- **Logging — structlog 25+**: con `merge_contextvars` para correlation_id desde el principio (lección del v1: agregar después es retrofitting caro).
- **Deploy — 1 container Docker**: Cloak embebido vía Playwright en el mismo proceso, no servicio separado. Detrás de nginx del VPS.
- **Rate limit obligatorio**: máx 1 request Google/min por defecto (configurable via env). Por encima → riesgo cierto de challenge.
- **Cache siempre primero**: NUNCA disparar Google sin chequear sqlite previo.
- **LLM timeout**: 5s por candidato; on timeout → `confidence=0.3` (fallback permisivo, no descartar el candidato).
- **Visit pass solo si necesario**: nunca visitar links que ya tienen precio en SERP ni MELI links (asumir fresh).
- **Persistir `raw_serp_html` en cache**, NO en response (forensics + reproducibilidad).
- **No loguear contenido scrapeado** en logs estándar (privacidad/legal).
- **NO scrapear MELI directamente** — cualquier `*.mercadolibre.*` endpoint queda prohibido por arquitectura, no por código.
- **Headed antes que headless** para probar fuentes nuevas (lección heredada del v1: nunca asumir).
- **YAGNI fase por fase**: cada fase entrega valor cerrado, no infraestructura especulativa.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Discard v1 codebase + git history | v1 entregaba en producción los mismos 7 productos por query que una búsqueda manual; complejidad arquitectónica (5 containers, ~15k LOC) no justificada sin fuentes activas además de Google; MELI directo no factible sin proxy residencial (Fase 3 nunca arrancada) | — Pending validation |
| Single endpoint `/search` sync (no SSE, no async workers) | P50 esperado <20s cold con cache hit 30% — sync HTTP cubre el SLA sin la complejidad operativa de queues | — Pending |
| LLM filter estructurado (Caso 1c) vs binario o score+razón | LLM estructurado evita pase de extracción posterior; reduce un step downstream | — Pending |
| Skip-if-you-can en visit pass | Visitar 20 sitios por query es lento (30-60s); si el SERP ya trae precio + es MELI link, se asume fresh y se evita la visita | — Pending |
| NO scrapear MELI directamente; usar Google con `+mercadolibre` query | API oficial 403 incluso autenticado post-abril 2025; browser-path → `/gz/account-verification` redirect; proxy residencial deferido; Google ya hizo el trabajo de aggregating MELI en su SERP | ✓ Validated by v1 incident logs |
| 1 container Docker, no browser-pool desacoplado | Cloak embebido vía Playwright en el mismo proceso es suficiente para 1 fuente; desacople agrega operativa sin valor a este scope | — Pending |
| Cloakbrowser sin Camoufox fallback | v1 nunca ejerció el fallback en producción; agrega tamaño de imagen + complejidad sin uso real | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-01 after initialization (artiscrapper v0 reset from v1)*

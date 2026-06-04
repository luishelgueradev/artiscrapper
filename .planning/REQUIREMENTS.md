# Requirements: artiscrapper v0

**Defined:** 2026-06-01
**Core Value:** El endpoint `/search?q=...` recibe una query, dispara 2 fetches a Google (`q` y `q +mercadolibre`), filtra con LLM local para quedarse solo con productos comprables, valida live + precio visitando survivors cuando hace falta, y devuelve JSON ordenado por relevancia. **El consumidor recibe productos que existen, con precio, link y procedencia clara.**

## v1 Requirements

Requerimientos para llegar a "production-ready" (GSD Phase 1 → Phase 2 → Phase 3, mapeado del PRD Fase 0/1/2). Cada uno mapea a una fase del roadmap.

### Search Pipeline (SEARCH)

- [ ] **SEARCH-01**: Endpoint `POST /search` recibe `{query: string, max_results?: int (default 15, max 30), visit_timeout_s?: int (default 10)}` y devuelve `200 OK` con `{query, results[], metadata}`.
- [ ] **SEARCH-02**: Cache lookup en sqlite con TTL 24h ANTES de cualquier fetch a Google. Cache hit devuelve respuesta cacheada con `metadata.cache_hit=true`.
- [ ] **SEARCH-03**: 2 fetches paralelos a Google vía Cloakbrowser: URL A = `q&hl=es&gl=ar&pws=0&safe=off`, URL B = `q mercadolibre&hl=es&gl=ar&pws=0&safe=off`. SIN `num=`, SIN `tbm`/`udm`, SIN `site:mercadolibre.com.ar`.
- [ ] **SEARCH-04**: Parser unificado de ambos SERPs con cascade de selectors: `div.tF2Cxc` (organic) + `div.Ez5pwe` (carousel) + `div.MjjYud` (fallback), con generic `h3`-anchored fallback si todos los selectors específicos devuelven 0 resultados.
- [ ] **SEARCH-05**: Dedupe de candidatos por URL canónica (strip tracking params: `utm_*`, `fbclid`, `gclid`, `ved`, `usg`; normalize host lowercase + strip trailing `/`).
- [ ] **SEARCH-06**: Heuristic pre-filter aplica blocklist de junk domains (`youtube.com`, `*.fandom.com`, `*.wikipedia.org`, `reddit.com`, `*.medium.com`, `*.gov.ar`) ANTES del paso LLM.
- [ ] **SEARCH-07**: Re-rank final por `(has_price DESC, fresh DESC, llm_confidence DESC)`. Truncar a `max_results`.
- [ ] **SEARCH-08**: Response JSON incluye `metadata`: `elapsed_ms, google_fetches, candidates_total, llm_filtered_out, visited, visit_failed, cache_hit, llm_degraded`.

### LLM Curator (LLM)

- [ ] **LLM-01**: Por cada candidato, llamada HTTP a `local-llms-router` con prompt estructurado en español + 2 few-shot examples (positive MELI card, negative blog).
- [ ] **LLM-02**: Output schema: `{is_product: bool, confidence: 0.0-1.0, price_hint: number?, store_hint: string?, freshness_signal: enum["live_marketplace","static_catalog","blog","unknown"], reason: string}`. Validación con `pydantic.model_validate_json()` — sin `instructor`/`outlines`.
- [ ] **LLM-03**: Llamadas concurrentes con `asyncio.Semaphore(LLM_CONCURRENCY=4)`. NO batchear todos los candidatos en una sola llamada.
- [ ] **LLM-04**: Timeout 5s por candidato. On timeout/malformed-JSON/refusal → fallback verdict `{is_product: true, confidence: 0.3, freshness_signal: "unknown", reason: "llm_fail:<type>"}`.
- [ ] **LLM-05**: Cutoff: descartar candidato si `confidence < 0.4` OR `freshness_signal == "blog"`. Como `confidence=0.3` está por debajo de `0.4`, los timeouts caen — esto es intencional (PRD §3 step 5 manda). El consumidor lo ve vía `metadata.llm_degraded=true` cuando >50% de llamadas caen al fallback.
- [ ] **LLM-06**: Degraded mode: si el router está completamente abajo (HEAD `/health` falla), el filtro LLM se salta y se usa solo la blocklist heurística + "tiene precio in-card" como criterios de retención.
- [ ] **LLM-07**: Configuración LLM: `temperature=0.0, max_tokens=128, format=json` (token-level grammar si el router lo soporta).
- [ ] **LLM-08**: NO loguear contenido del prompt ni del response (campos de candidatos van por allow-list a structlog).

### Visit Pass (VISIT)

- [ ] **VISIT-01**: Skip-if-you-can: NO visitar candidatos donde `(price is not None) OR (freshness_signal == "live_marketplace") OR (host ∈ live_marketplaces_allowlist)`.
- [ ] **VISIT-02**: Visitas concurrentes con `httpx.AsyncClient(http2=True)` + global `asyncio.Semaphore(8)` + per-host `asyncio.Semaphore(2)` via `defaultdict`.
- [ ] **VISIT-03**: Timeout 10s por visita (default, configurable via `visit_timeout_s` en request).
- [ ] **VISIT-04**: Headers realistas Chromium-146 + `Sec-Fetch-Site: cross-site` + `Referer: https://www.google.com/`.
- [ ] **VISIT-05**: Live-vs-dead classification: combina HTTP status + `response.history` final-path normalizado + `<title>`/`<h1>` markers (`"404"`, `"not found"`, `"no encontrado"`) + body size floor 5KB.
- [ ] **VISIT-06**: Extracción structured: JSON-LD Product (`<script type="application/ld+json">`) → OG (`product:price:amount` + `product:price:currency`) → microdata (`itemprop="price"`) → AR-regex fallback. Hand-rolled en selectolax, sin `extruct`.
- [ ] **VISIT-07**: Failure modes: 404/redirect-home → `flag: skip_dead`. 5xx/timeout/connection error → `flag: visit_failed`. NO retry. NO Cloak en visit pass (Cloak es Google-only en v0).
- [ ] **VISIT-08**: NO visitar URLs `*.mercadolibre.*` (PRD §11, out of scope explícito).

### Freshness (FRESH)

- [ ] **FRESH-01**: MELI link (`mercadolibre.com.ar`) + HTTP 200 → `fresh=true` (asumir).
- [ ] **FRESH-02**: JSON-LD `datePublished` o `<meta property="article:modified_time">` o `<time datetime>` < 90 días → `fresh=true`.
- [ ] **FRESH-03**: LLM `freshness_signal == "blog"` → candidato ya descartado en LLM-05.
- [ ] **FRESH-04**: Sin signal → `fresh=unknown` (NO `fresh=false` — eso es para evidencia positiva de antigüedad).

### Cache (CACHE)

- [ ] **CACHE-01**: sqlite + `aiosqlite` + `journal_mode=WAL`. Schema mínimo: `(cache_key TEXT PK, query TEXT, response_json TEXT, raw_serp_html_a BLOB, raw_serp_html_b BLOB, created_at, expires_at)`.
- [ ] **CACHE-02**: `raw_serp_html_a` y `raw_serp_html_b` se persisten como BLOB gzip (separados del response_json) para forensics. Target compresión 8-12x, ~500MB steady-state a 24h TTL para 2000 q/día.
- [ ] **CACHE-03**: Cache key = hash determinístico de la query normalizada (lowercase, trim, strip puntuación accesoria).
- [ ] **CACHE-04**: TTL enforcement lazy en read (`if expires_at < now → refetch`). Loop de prune horario que elimina expired rows + nightly `wal_checkpoint(TRUNCATE)`.
- [ ] **CACHE-05**: NUNCA disparar Google sin chequear cache primero. Cache miss → fetch → write → return.

### Health & Observability (OBS)

- [ ] **OBS-01**: `GET /health` cheap (<50ms): chequea `Browser.is_connected()` + `SELECT 1` en sqlite. Devuelve `{status, cloak, llm, cache}`.
- [ ] **OBS-02**: `GET /health/deep` real: navega Cloak a `about:blank`, HEAD a LLM router. NUNCA llamado por LB (eats Chromium nav). Solo manual/cron.
- [ ] **OBS-03**: structlog desde día 1: JSON output, bindings `(correlation_id, query_hash, stage, elapsed_ms)`, `merge_contextvars` activado.
- [ ] **OBS-04**: asgi-correlation-id middleware en FastAPI propaga `X-Request-ID` (genera UUID si no viene del cliente).
- [ ] **OBS-05**: NO loguear contenido scrapeado (titles, snippets, URLs, raw HTML). Whitelist de campos en cada log site.
- [ ] **OBS-06**: Counter `artiscrapper_llm_fallback_total{reason}` y `artiscrapper_visit_failed_total{host}` instrumented inline (incluso pre-Prometheus; expuestos en Fase 2).
- [x] **OBS-07** (Fase 2): Endpoint `/metrics` Prometheus con counters anteriores + histograms `artiscrapper_search_elapsed_seconds`, `artiscrapper_llm_elapsed_seconds`, `artiscrapper_visit_elapsed_seconds{stage}`.

### Browser Lifecycle (BROWSER)

- [ ] **BROWSER-01**: Singleton `Browser` instanciado en FastAPI `lifespan` startup; cerrado en shutdown.
- [ ] **BROWSER-02**: Ephemeral `new_context()` por request — NUNCA `launch_persistent_context` (Cloak issue #331: CAPTCHA loop garantizado).
- [ ] **BROWSER-03**: Recycle del browser cada `BROWSER_RECYCLE_AFTER=200` cold-fetches (env-driven) para evitar memory drift de Chromium (Playwright issue #15400).
- [ ] **BROWSER-04**: `asyncio.Semaphore(1)` + last-fetch timestamp gate alrededor de las llamadas a Google. Rate-limit ≥ 60s entre fetches a `google.com` (configurable via `GOOGLE_MIN_INTERVAL_S`).
- [ ] **BROWSER-05**: Block detection: si SERP HTML contiene `"detected unusual traffic"`, `"captcha"`, `"sorry/index"` en `<title>`, `_detect_block` levanta `BlockDetected` y la query falla con `503` + `metadata.block_detected=true`.

### Deploy & Build (DEPLOY)

- [ ] **DEPLOY-01**: 1 imagen Docker multi-stage: builder `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` + runtime `cloakhq/cloakbrowser:0.3.31` (verificar tag en Fase 0).
- [ ] **DEPLOY-02**: Pin Chromium binary tag `chromium-v146.0.7680.177.5` (no `latest`).
- [ ] **DEPLOY-03**: `uvicorn --loop asyncio --workers 1` SIEMPRE. NUNCA instalar `uvloop` (incompatible con Cloak).
- [ ] **DEPLOY-04**: `tini` / `docker run --init` para evitar zombies de Chromium.
- [ ] **DEPLOY-05**: `uv sync --locked` con `uv.lock` checked in. CI assert: no uvloop en pyproject.toml.
- [ ] **DEPLOY-06**: Compose file de dev local (`compose.yml`) con la imagen + bind-mount de sqlite path. Producción se decide en Fase 3.

### Non-Functional (NF)

- [ ] **NF-01**: Volumen target: 500-2000 queries/día sostenido, P50 cache-hit <500ms, P50 cold <20s, P95 cold <40s.
- [ ] **NF-02**: Tests unit del parser con fixtures HTML reales (top 10 AR stores) + tests integration con LLM mockeado (respx).
- [ ] **NF-03**: Linting ruff clean + mypy strict en módulos públicos. `pytest tests/ -x -q` green.
- [ ] **NF-04**: Cost: $0/mes adicional (mismo VPS donde corre `local-llms-router`, sin proxy residencial, sin servicio externo).

## v2 Requirements

Deferidos a futuro release. Tracked pero NO en current roadmap (PRD Fase 4 territory = GSD Phase 5).

### Suppliers (SUP) — GSD Phase 5 diferido

- **SUP-01**: Adapter directo per-supplier (Mayorista Frog, Distribuidora Romero, Casa Susy, etc.) — solo si la lista curada de Google no alcanza
- **SUP-02**: Per-supplier auth flow (algunos B2B requieren login)
- **SUP-03**: Per-supplier rate-limit configurable

### MELI Direct (MELI) — bloqueado por arquitectura

- **MELI-01**: MELI API oficial via Developer Partner Program (10 días SLA, no garantizado)
- **MELI-02**: Catalog search MELI vía `/marketplace/products/search` con GTIN — solo si la app interna empieza a manejar GTINs

### Advanced Observability (ADV)

- **ADV-01**: Grafana dashboard con per-host visit stats — GSD Phase 4 si trigger
- **ADV-02**: Sentry-sdk para uncaught exceptions — GSD Phase 3 (ya wired)
- **ADV-03**: Loki para log aggregation — GSD Phase 4 si trigger
- **ADV-04**: Distributed tracing (OpenTelemetry) — GSD Phase 4 condicional

### Multi-tenant (MULTI)

- **MULTI-01**: Authentication API-key por consumer — GSD Phase 5 si trigger
- **MULTI-02**: Per-consumer rate-limit + quota
- **MULTI-03**: Per-consumer billing/usage telemetry

## Out of Scope

Explícitamente excluido. Documentado para prevenir scope creep.

| Feature | Reason |
|---|---|
| Scraping directo `*.mercadolibre.*` | IP-blocked sin proxy residencial; arquitectura prohibe el host, no solo el código |
| Proxy residencial / mobile / IP rotation | Costo + fricción no justificados a este scope (1 IP + cache + rate-limit suficiente) |
| Multi-engine browser fallback (Camoufox) | v1 demostró que Camoufox no agrega valor real para Google |
| Async + SSE en `/search` | Sync HTTP cubre el SLA esperado (P50 cold <20s) |
| Workers / RQ / Redis / message queues | Sync HTTP cubre el caso de uso sin complejidad operativa |
| Postgres + Alembic | sqlite local cubre cache, no hay relacional que justifique RDBMS |
| Authentication multi-tenant (v1) | Un solo cliente (Sánchez); header API-key estático en Fase 1 si hace falta |
| Marketplaces no-Google-indexados (eBay AR, etc.) | Google es el descubridor — lo que Google no muestra, fuera de scope |
| `cloakserve` sidecar | 1 container es suficiente; adds HTTP hop + failure mode |
| `extruct` library en MVP | Hand-rolled selectolax cubre 75-85% AR; +30MB imagen |
| `instructor`/`outlines`/`pydantic-ai` | Pydantic + try/except + `format=json` cubre el caso |
| `aiolimiter`/`httpx-limiter` | Dict-of-semaphores suficiente a este volumen |
| `curl-cffi` TLS-impersonation | Headers realistas pasan la mayoría; deferred a Fase 2 si >30% failure por host |
| `tbm=shop` / `udm=28` | Different DOM, parser returns zero |
| Retry on malformed JSON | Temp=0 → identical output, garantizado mismo fail |
| Retry on visit-pass failures | `visit_failed` es la señal honesta — retry duplica timeout sin valor |
| `uvloop` | Incompatible con Cloak (subprocess pipe protocol) — banned |
| `launch_persistent_context` en Cloak | Issue #331: CAPTCHA loop garantizado en Google |
| Cross-process rate-limit (sqlite token bucket) | `--workers 1` hace `asyncio.Semaphore(1)` suficiente |

## Traceability

Phase mapping per `.planning/ROADMAP.md`. **GSD Phase numbering:** 1 = Spike (PRD Fase 0), 2 = MVP (PRD Fase 1), 3 = Robustness (PRD Fase 2), 4 = Operations (PRD Fase 3), 5 = Expansion (PRD Fase 4).

| Requirement | Phase | Status |
|---|---|---|
| SEARCH-01 | Phase 2 (MVP) | Complete |
| SEARCH-02 | Phase 2 (MVP) | Complete |
| SEARCH-03 | Phase 2 (MVP) | Complete |
| SEARCH-04 | Phase 2 (MVP) | Complete |
| SEARCH-05 | Phase 2 (MVP) | Complete |
| SEARCH-06 | Phase 2 (MVP) | Complete |
| SEARCH-07 | Phase 2 (MVP) | Complete |
| SEARCH-08 | Phase 2 (MVP) | Complete |
| LLM-01 | Phase 2 (MVP) | Complete |
| LLM-02 | Phase 2 (MVP) | Complete |
| LLM-03 | Phase 2 (MVP) | Complete |
| LLM-04 | Phase 2 (MVP) | Complete |
| LLM-05 | Phase 2 (MVP) | Complete |
| LLM-06 | Phase 2 (MVP) | Complete |
| LLM-07 | Phase 2 (MVP) | Complete |
| LLM-08 | Phase 2 (MVP) | Complete |
| VISIT-01 | Phase 2 (MVP) | Complete |
| VISIT-02 | Phase 2 (MVP) | Complete |
| VISIT-03 | Phase 2 (MVP) | Complete |
| VISIT-04 | Phase 2 (MVP) | Complete |
| VISIT-05 | Phase 2 (MVP) | Complete |
| VISIT-06 | Phase 2 (MVP) | Complete |
| VISIT-07 | Phase 2 (MVP) | Complete |
| VISIT-08 | Phase 2 (MVP) | Complete |
| FRESH-01 | Phase 2 (MVP) | Complete |
| FRESH-02 | Phase 2 (MVP) | Complete |
| FRESH-03 | Phase 2 (MVP) | Complete |
| FRESH-04 | Phase 2 (MVP) | Complete |
| CACHE-01 | Phase 2 (MVP) | Complete |
| CACHE-02 | Phase 2 (MVP) | Complete |
| CACHE-03 | Phase 2 (MVP) | Complete |
| CACHE-04 | Phase 2 (MVP) | Complete |
| CACHE-05 | Phase 2 (MVP) | Complete |
| BROWSER-01 | Phase 2 (MVP) | Complete |
| BROWSER-02 | Phase 2 (MVP) | Complete |
| BROWSER-03 | Phase 2 (MVP) | Complete |
| BROWSER-04 | Phase 2 (MVP) | Complete |
| BROWSER-05 | Phase 2 (MVP) | Complete |
| DEPLOY-01 | Phase 2 (MVP) | Complete |
| DEPLOY-02 | Phase 2 (MVP) | Complete |
| DEPLOY-03 | Phase 2 (MVP) | Complete |
| DEPLOY-04 | Phase 2 (MVP) | Complete |
| DEPLOY-05 | Phase 2 (MVP) | Complete |
| DEPLOY-06 | Phase 2 (MVP) | Complete |
| OBS-01 | Phase 2 (MVP) | Complete |
| OBS-02 | Phase 2 (MVP) | Complete |
| OBS-03 | Phase 2 (MVP) | Complete |
| OBS-04 | Phase 2 (MVP) | Complete |
| OBS-05 | Phase 2 (MVP) | Complete |
| OBS-06 | Phase 2 (MVP) | Complete |
| OBS-07 | Phase 3 (Robustness) | Complete |
| NF-01 | Phase 2 (MVP) | Complete |
| NF-02 | Phase 2 (MVP) | Complete |
| NF-03 | Phase 2 (MVP) | Complete |
| NF-04 | Phase 2 (MVP) | Complete |

**Phase 1 (Spike)** carries zero v1 requirements by design — it produces fixtures + `SPIKE.md` Go/No-Go gating Phase 2 lock-in of D1, D3, D4, D8, D10, D11, D12 from `research/SUMMARY.md`.

**Coverage:**
- v1 requirements: 55 REQ-IDs (en SEARCH×8 + LLM×8 + VISIT×8 + FRESH×4 + CACHE×5 + BROWSER×5 + DEPLOY×6 + OBS×7 + NF×4)
- v2 requirements: 13 total (SUP/MELI/ADV/MULTI — todos diferidos a GSD Phase 4-5)
- Mapped to phases: **55/55 (100%)** — Phase 2 closes 54, Phase 3 closes OBS-07
- Unmapped: 0
- Orphans: 0
- Duplicates: 0

> Note: ROADMAP.md historically framed v1 as "55 REQ-IDs across 53 logical reqs". After 2026-06-04 audit (Phase 3.1 traceability flip), the canonical count is 55 unique REQ-IDs — each maps to exactly one SUMMARY's `requirements_completed:` field and one VERIFICATION.md row. The "53 logical" framing is deprecated.

---
*Requirements defined: 2026-06-01 from PRD v0.1 + research synthesis (5 docs in `.planning/research/`)*
*Last updated: 2026-06-01 by gsd-roadmapper (Traceability mapped to GSD Phase 1-5 per `.planning/ROADMAP.md`)*
*Status flip: 2026-06-04 by Phase 3.1 (v0.1 close hygiene). 55/55 REQ-IDs Complete per VERIFICATION.md evidence + SUMMARY frontmatter union.*

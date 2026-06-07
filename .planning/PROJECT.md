# artiscrapper

## What This Is

Servicio HTTP genérico de búsqueda de artículos comerciales: dada una query (e.g. `"filtro aire ranger"`, `"zapatillas nike air max 42"`, `"termotanque rheem 80 litros"`), devuelve una lista curada de productos que reflejan lo que una persona vería buscando en Google manualmente, enriquecidos con precio, validación de destino vivo, y filtrados por un LLM local para descartar blogs/wikis/contenido irrelevante. **Reutilizable across consumidores y verticales** — no acoplado a ningún cliente, taller, o vertical específico. Diseñado para que cualquier app que necesite "lo que un humano ve en Google con precios y URLs accionables" pueda consumirlo vía un único endpoint.

**Shipped en v0.1 (2026-06-04):** servicio funcional 1-container production-ready con `/search`, `/health`, `/metrics`, X-API-Key auth, slowapi rate-limit (Pattern B settings-source-of-truth), challenge-backoff, degraded-mode fallback, fixture-replay integration suite, Sentry-ready (env-gated).

**Shipped en v0.2 (2026-06-06):** parser visual parity (+207% URLs reales medidas), continuous parity harness (12-query dataset + 3 Prometheus gauges + CI nightly + alerts), page-2 pagination (+39% candidate volume measured live), browser stability hardening (issue #1 + 3 Gap fixes), carried tech debt closure (tldextract rename, ORJSONResponse removal, httpx2 + always-on `error::DeprecationWarning` filter, scripts/spike ruff-zero).

## Core Value

**Si solo una cosa tiene que funcionar bien**: el endpoint `POST /search` recibe una query con `X-API-Key`, dispara N×2 fetches a Google (default N=2 → page 1 + page 2, ambos en `q` y `q +mercadolibre`), filtra con LLM local para quedarse solo con productos comprables, valida live + precio visitando los survivors cuando hace falta, y devuelve un JSON ordenado por relevancia. El consumidor recibe **productos que existen, con precio, link y procedencia clara**, accionables across cualquier vertical commercial (auto-parts, electro, ropa, libros, deporte, electrónica) — empíricamente validado en v0.2 a través de 12 queries canónicas cross-vertical.

<details>
<summary>📦 Prior shipped state (v0.1 — 2026-06-04, archived)</summary>

## Current State (v0.1 — shipped 2026-06-04)

- **Production-ready single-container deploy**: Dockerfile multi-stage con `cloakhq/cloakbrowser:0.3.31` + Chromium pin `v146.0.7680.177.5`, `tini`/`--init`, `uv sync --locked`, sqlite bind-mount `./data/cache.db`. CI-asserted no-uvloop + no-launch_persistent_context invariants.
- **Pipeline integrado**: `/search` → cache lookup → ChallengeBackoff gate → 2 parallel Google fetches (rate-limited 1/min) → block detection → parser cascade `tF2Cxc → Ez5pwe → MjjYud → h3-anchored` con `parse.cascade.exhausted` alert → URL dedupe + junk blocklist → LLM curator con Semaphore(4) + `<0.4` confidence cutoff + degraded-mode price-in-card fallback → visit pass con httpx http2 + global+per-host Semaphores + hand-rolled JSON-LD/OG/microdata/AR-regex extractor → freshness assessment → rerank → background cache-write.
- **Observability**: structlog JSON + `merge_contextvars` + correlation_id en todo evento + asgi-correlation-id middleware; `/metrics` ASGI sub-app expone 12 canonical `artiscrapper_*` Prometheus families + workload-tuned Histograms; env-gated Sentry con correlation_id tag injection (off when DSN empty); `/health` cheap + `/health/deep` real (gated auth).
- **Resilience**: X-API-Key auth con `hmac.compare_digest` constant-time; stacked slowapi rate-limit `(60/min + 10000/day)` Pattern B (module constants → decorator argument + log line, drift impossible by construction); ChallengeBackoff state machine `min(60·2^retries, 3600)` con sqlite single-row persistence surviving `compose up --force-recreate`; 503+Retry-After when gate denies.
- **Test surface**: 68 unit + 9 integration + 2 e2e (E2E=1 gated) = 79 tests; mypy --strict on `src/artiscrapper/` clean; ruff + format clean on production files. PRD §10 success criteria validated by operator UAT 2026-06-02.

</details>

## Current State (v0.2 — shipped 2026-06-06)

v0.2 cerró el gap empíricamente medido del parser SERP (+207% URLs reales) con cambios quirúrgicos sobre v0.1, instaló harness continuo de paridad visual, agregó paginación page 2 (+39% candidate volume medido live), y limpió carried tech debt. **75 commits, 11 plans, 2 días wall-clock, 124/2/0-warnings suite at close.**

- **Parser visual parity shipped:** `wait_until="domcontentloaded"` + `wait_for_selector("div.pla-unit")` (revisited from Phase 0.2.1's original `wait_until="load"` after issue #1 surfaced N×2 fragility); extractor `_extract_pla_unit()` aditivo al cascade; regex precio v2 (`,DD` cierre obligatorio). **Endpoint `GET /admin/parity/{query}`** autenticado retorna `html_metrics` + `parser_metrics` + `drift` con 2 Prometheus gauges mínimas.
- **Continuous parity harness shipped:** Dataset canónico de **12 queries** cross-vertical (`tests/fixtures/parity-dataset.yaml`). **3 Prometheus gauges** completas (`parity_coverage_pct{query}`, `parity_pla_units_missed{query}`, `parity_url_synthetic_ratio{query}`). Sample 1/10 async en hot path productivo (p99 <50ms). **GitHub Actions `.github/workflows/parity-nightly.yml`** falla CI a coverage avg <75%. **3 Prometheus alert rules** en `prometheus/alerts/parity.yaml` (Warn @75%>30min + Fail @50%>5min).
- **Page 2 pagination shipped:** `build_serp_url(query, meli, page=N)` con `&start=10*(N-1)`. `settings.SEARCH_FETCH_PAGES` (default 2, validado [1,3], env-overridable via compose.yml passthrough). `POST /search` loops N×2 fetches en `asyncio.gather`. Dedupe pre-LLM por URL canónica. **2 frozen page-2 fixtures** (termotanque + zapatillas) + 4 integration tests pinning las invariantes. Gain medido live: **+39% candidate volume** (271 → 376 across 5 saturated queries; 4 of 5 muestran 20-69% increase).
- **Stability hardening (issue #1 + 3 Gap fixes):** Browser singleton ya no muere bajo N×2 sostenido (14 consecutive calls 0 deaths). Real Google blocks ahora correctamente surface en `block_detected_total{sorry_redirect}` en vez de ocultarse como `TargetClosedError`. Honest `google_fetches` accounting on all non-success paths (cache_hit=0, 503=0, exception=0, block=len(htmls)). `compose.yml` env passthrough fixed (`SEARCH_FETCH_PAGES` rollback knob now actually wired). Footgun test pina el invariant.
- **Tech debt closed:** tldextract `.registered_domain` → `.top_domain_under_public_suffix` rename (6.x doesn't exist on PyPI yet; deprecation was the real root cause). FastAPI `default_response_class=ORJSONResponse` fully removed (Pydantic-Rust default per PR #14964). `httpx2==2.3.0` dev dep (Starlette auto-detects via testclient import-by-name). `filterwarnings = ["error::DeprecationWarning"]` **always-on in pyproject.toml** (gate is the default, not opt-in). `scripts/spike/` ruff-zero via source rename `l → line` (no per-file-ignores, no `# noqa` shortcuts).

**Out of scope explícito (carried into v0.3+):**
- **Servicios pagos de cualquier tipo** — SerpAPI, Bright Data, Oxylabs, ScraperAPI, OpenAI cloud, Sentry tier paid, observability SaaS, etc. Constraint hard del proyecto (locked 2026-06-06; standing memories `feedback_no_paid_services` + `feedback_browser_rendered_ground_truth`). Ground truth = lo que el explorador renderiza (Cloak / Playwright / browser-rendered); si el render se rompe, se arregla el render, no se cambia la fuente.
- **Estrategia B (DOM-driven browser persistente)** — viola D8 invariant; URLs reales del carousel solo recuperables con JS-render + clic simulado, costo arquitectónico no justificado.
- **Resolución de URLs reales del carousel** — los 30 carousel items por query siguen con URL sintética `google.com/search?q=Title+site:Store`. Best-effort sin Estrategia B; el reporte demuestra que sigue siendo accionable para el consumidor.
- **Phases 4-5 deferred-by-design** — Phase 4 (production-ops, Grafana/Loki) y Phase 5 (per-supplier adapters, residential proxy, SSE, multi-tenant) siguen gated en sus triggers originales.

## Next Milestone Goals (v0.3 — TBD)

Scope to be defined via `/gsd:new-milestone`. Likely candidates (not committed):

- Carousel real-URL resolution (Estrategia B revisited, or alternative browser-rendered approach within D8 invariant).
- WR-01 follow-up: GoogleRateLimiter `Semaphore(1)` serialization risk under N×2 fetches when `GOOGLE_MIN_INTERVAL_S > 0` (latent landmine — code review surfaced in 0.2.3).
- WR-02 follow-up: parity-audit page-1-only — current `_parity_audit_sample` ignores page-2 HTML, so HARNESS-05 drift signal is undercount on queries where page-2 contributes ≥50% (code review surfaced in 0.2.3).
- LLM router rotation / multi-model fallback (if `local-llms-router` model drift becomes operational concern).
- Phase 4 trigger conditions hit? Grafana/Loki/tracing on-ramp.

## Requirements

### Validated (v0.1)

All 55 v1 REQ-IDs SATISFIED per `.planning/milestones/v0.1-MILESTONE-AUDIT.md` (3-source cross-reference clean):

- ✓ **SEARCH-01..08** — Pydantic models, build_serp_url, parser cascade with cascade-exhausted alert, URL dedupe, junk blocklist, re-rank, structured response — v0.1
- ✓ **LLM-01..08** — Spanish prompt + 2 few-shot, LLMVerdict + fallback(), Semaphore(LLM_CONCURRENCY=4), 5s timeout + reason taxonomy, `<0.4` cutoff + `llm_degraded` surfacing, degraded-mode fallback, router HEAD probe — v0.1
- ✓ **VISIT-01..08** — skip-if-you-can, httpx http2 + global+per-host Semaphores, Chromium-146 headers, classify_response, JSON-LD+OG+microdata+AR-regex extractor, no-MELI invariant — v0.1
- ✓ **FRESH-01..04** — MELI 200 → fresh; datePublished <90d → fresh; blog → drop; live-marketplace signal — v0.1
- ✓ **CACHE-01..05** — aiosqlite WAL + gzipped BLOB + lazy TTL + hourly prune + nightly checkpoint — v0.1
- ✓ **BROWSER-01..05** — Singleton Browser lifespan + ephemeral new_context() + BROWSER_RECYCLE_AFTER=200 + _detect_block — v0.1
- ✓ **DEPLOY-01..06** — Dockerfile multi-stage, Chromium pin, tini, uv.lock, compose.yml, no uvloop CI assertion — v0.1
- ✓ **OBS-01..06** — structlog + correlation_id + asgi-correlation-id + `/health` cheap + `/health/deep` real + inline counters — v0.1
- ✓ **OBS-07** — `/metrics` ASGI sub-app + 6+ canonical artiscrapper_* families + Histograms — v0.1 (Phase 3)
- ✓ **NF-01..04** — PRD §10 latency budget, respx mocks, mypy --strict, ruff clean — v0.1

### Validated (v0.2 — shipped 2026-06-06)

All 17 active v0.2 REQ-IDs SATISFIED (2 cancelled, see below):

- ✓ **PARITY-01..05** — Parser visual parity (wait_until + pla-unit extractor + precio v2 + fixtures + `/admin/parity/{query}` endpoint with Prometheus gauges) — v0.2.1 (2026-06-05). PARITY-01 subsequently revisited: switched from `wait_until="load"` to `wait_until="domcontentloaded"` + `wait_for_selector("div.pla-unit")` for stability under N×2 concurrency (issue #1 resolved 2026-06-06).
- ✓ **HARNESS-01..05** — Continuous parity harness (12-query canonical dataset + 3 Prometheus gauges + 1/N async sample on hot path + CI nightly + Warn/Fail alerts) — v0.2.2 (2026-06-05).
- ✓ **PAGE2-01..03** — Page-2 pagination (build_serp_url page kwarg + SEARCH_FETCH_PAGES setting + N×2 asyncio.gather + dedupe by canonical URL + 2 frozen fixtures + 4 integration tests). Live gain measured: +39% candidate volume on saturated queries. — v0.2.3 (2026-06-05, UAT rerun 2026-06-06).
- ⊘ **SERPAPI-01..02** — **CANCELLED 2026-06-06**: violates the standing project rule "no paid services of any kind". The decision is permanent — `feedback_no_paid_services` standing memory codifies it.
- ✓ **TECHDEBT-01..04** — Carried v0.1 tech debt (tldextract rename + ORJSONResponse removal + httpx2 dev dep + always-on `error::DeprecationWarning` filter + scripts/spike ruff-zero) — v0.2.5 (2026-06-06).

### Active (v0.3 — TBD)

Scope to be defined via `/gsd:new-milestone`. Likely v0.3 candidates surfaced by v0.2 work:

- **CAROUSEL-01** — Carousel real-URL resolution within D8 invariant (Estrategia B revisited or browser-rendered alternative; currently 30 carousel items per query serve synthetic `g/search?q=...&site:Store` URLs).
- **WR-01-FOLLOWUP** — `GoogleRateLimiter` `Semaphore(1)` serializes the N×2 fetches when `GOOGLE_MIN_INTERVAL_S > 0`. Latent landmine (currently masked by default of 0) — needs to either drop the serializer or raise the timeout per-fetch.
- **WR-02-FOLLOWUP** — `_parity_audit_sample` only reads `html_a` (page-1) while the response now carries page-2 candidates. HARNESS-05 drift signal is undercount on queries where page-2 contributes ≥50% of post-dedupe results.
- **OBSERVABILITY-01** — Phase 4 trigger conditions assessment (Grafana/Loki/tracing) once production telemetry demand materializes.
### Out of Scope (still valid post-v0.2)

- **Scraping directo de MercadoLibre** (cualquier `*.mercadolibre.*` endpoint) — confirmed by Phase 1 spike: IP-blocked sin proxy residencial; MELI catálogo sale vía Google con `+mercadolibre`. WR-01 (Phase 3.1) hardened guard con tldextract.registered_domain match.
- **Proxy residencial / mobile / IP rotation** — costo + fricción no justificados a este scope; revisit only if Phase 5 trigger fires.
- **Multi-engine browser fallback** (Camoufox) — Cloak es suficiente, v1 demostró que Camoufox no agregaba valor real.
- **Async + SSE en /search** — sync HTTP cubre el SLA (PRD §10); Phase 5 candidate only if latency trigger fires.
- **Workers / RQ / Redis / message queues** — sync HTTP cubre el caso de uso.
- **Postgres + Alembic** — sqlite local cubre el cache; sin datos relacionales.
- **Multi-tenant auth** — X-API-Key estático con frozenset module-load alcanza para 1-5 consumidores; revisitar cuando aparezca el N+1.
- **Marketplaces que no aparecen en Google** (eBay AR, Tiendanube específicas) — Google es el descubridor.
- **Partner Program MELI** — investigado, deferido indefinidamente.
- **uvloop** — banned (D6 foot-gun, Cloak subprocess incompatibility, CI grep assertion enforces).
- **launch_persistent_context** — banned (D8 foot-gun, Cloak issue #331, footgun test enforces).

## Context

- **Successor of**: versión 1 de artiscrapper (descartada 2026-06-01, git history wiped). v1 tenía ~15.000 LOC, 5 containers Docker, 6 fases roadmap, multi-source orchestrator con browser-pool desacoplado. Entregaba ~7 productos por query sin precio confiable. v0.1 entrega el mismo dominio en ~5,876 LOC, 1 container, 4 fases, con 55/55 reqs SATISFIED y empirical validation contra queries reales.
- **Knowledge preservado del v1** (ahora en código v0.1): parser de Google SERP (`div.tF2Cxc`, `div.Ez5pwe`, h3-anchored fallback), extracción precio AR (`$\xa018.032,30` → Decimal), junk-domain blocklist (youtube/fandom/wiki/reddit/quora), setup Cloakbrowser para Google con `pws=0&safe=off`.
- **Modelo de consumo**: cualquier app (n8n workflow, backend de catalog browser, etc.) que necesite "lo que un humano ve en Google con precios + URLs accionables" puede enchufar artiscrapper como dependencia HTTP. Degradación graceful via `metadata.llm_degraded=true` (LLM-06) y 503+Retry-After (ChallengeBackoff) si Google rotea challenges. No-prod-yet — pre-MVP shape, consumidores actuales = dev/test.
- **LLM router local**: `local-llms-router` corriendo en el mismo VPS (mismo proyecto Luis); reutilizado vía OpenAI-compat HTTP, no agregar deps de modelo.
- **Volumen real esperado**: 500-2000 queries/día. Phase 1 spike confirmó la viabilidad operacional.
- **Owner técnico**: Luis Helguera (Objetiva.com.ar).
- **Codebase size (post-v0.1)**: ~5,876 LOC (src/ + tests/), 125 commits, 3 días de desarrollo, 11 plans, 0 outstanding tech_debt items (5 medium-severity + 4 low-severity cleared in Phase 3.1).
- **Tech debt v0.2 backlog**: tldextract 6.x migration (`registered_domain` → `top_domain_under_public_suffix`), FastAPI ORJSONResponse deprecation cleanup, starlette/httpx TestClient → httpx2, scripts/spike/ ruff debt (48 errors, Phase 1 quick-spike code).

## Constraints

- **Tech stack — Python 3.13**: validated in v0.1 production build (pyproject.toml `requires-python = ">=3.13"`).
- **HTTP framework — FastAPI 0.136.3**: rápido, OpenAPI auto-generado, async-friendly.
- **Browser — Cloakbrowser 0.3.31 (Chromium 146.0.7680.177.5)**: Cloak pin bump validated en Phase 1 (D1), stealth-patch refresh sin breaking deps.
- **HTML parser — selectolax 0.4+**: validated contra 10 SERP + 10 catalog fixtures de Phase 1.
- **HTTP client — httpx 0.28+**: async, HTTP/2, retry-friendly; con `respx` 0.23.1 para tests.
- **Cache — aiosqlite + WAL + gzipped BLOB + lazy TTL**: validated en Phase 2; survives compose recreate.
- **LLM client — httpx contra `local-llms-router`**: OpenAI-compat POST `/v1/chat/completions` (D8 amended).
- **Logging — structlog 25+**: `merge_contextvars` + correlation_id desde el principio (NOT retrofitted).
- **Deploy — 1 container Docker**: Cloak embebido vía Playwright en mismo proceso, no servicio separado.
- **Rate limit — slowapi 0.1.9 Pattern B**: `_RATE_LIMIT_PER_*` module constants computed from settings; `@limiter.limit(_RATE_LIMIT_PER_MINUTE)` + `@limiter.limit(_RATE_LIMIT_PER_DAY)` on `/search`; `rate_limit_init` log line reads same constants (drift impossible by construction). Pattern A (`Limiter(default_limits=...)`) rejected — empirically non-viable on slowapi 0.1.9 + FastAPI.
- **Google rate limit — 0s gap por default desde Path B (2026-06-04)**: `GoogleRateLimiter(min_interval_s=settings.GOOGLE_MIN_INTERVAL_S)` con `GOOGLE_MIN_INTERVAL_S=0` default (era 60s). Las 2 fetches del mismo `/search` corren paralelo. Defensa contra burst la hace slowapi consumer rate-limit por API-key. Ver `.planning/PERFORMANCE-AUDIT-2026-06-04.md` §3-§4.
- **Heuristic pre-classifier (Path B 2026-06-04)**: `search.heuristic_pre_classify()` resuelve ~76% de candidatos típicos por reglas simples (price_in_card OR known_store host) ANTES del LLM. El LLM solo decide sobre el 24% ambiguo. Reduce cold-path LLM phase de ~75s a ~5-8s, baja 4x la carga al `local-llms-router`, mantiene F1 0.92 vs 0.90 del LLM solo.
- **Cache siempre primero**: NUNCA disparar Google sin chequear sqlite previo (validated by main.py `/search` step ordering).
- **LLM timeout — 5s/candidato**: on timeout → `confidence=0.3` (DROPPED at `<0.4` cut per D2 foot-gun, `metadata.llm_degraded` surfaced).
- **Visit pass skip-if-you-can**: never visit links with SERP price OR MELI hosts.
- **NO scrapear MELI directamente**: WR-01 hardening uses `tldextract.registered_domain` match (8 MELI registered domains frozenset).
- **OBS-05 — never log scraped content**: titles, snippets, URLs, raw HTML, prompts, responses, bearer tokens, API_KEYS, SENTRY_DSN. Allow-list via `log_candidate_safe()`.
- **YAGNI fase por fase**: cada fase entrega valor cerrado; v0.1 shipped 4 phases, NOT 5 — Phase 4 + 5 deferred-by-design.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Discard v1 codebase + git history (2026-06-01) | v1 entregaba 7 productos por query sin precio confiable; complejidad arquitectónica (5 containers, ~15k LOC) no justificada sin fuentes activas además de Google; MELI directo no factible sin proxy residencial | ✓ Validated — v0.1 entrega el mismo dominio en 5,876 LOC, 1 container |
| Single endpoint `POST /search` sync (no SSE, no async workers) | P50 esperado <20s cold con cache hit; sync HTTP cubre el SLA | ✓ Validated — PRD §10 success criteria PASS en queries reales |
| LLM filter estructurado con `<0.4` cutoff + `metadata.llm_degraded` surface | LLM estructurado evita pase de extracción posterior; D2 foot-gun: timeout fallback `confidence=0.3` ESTÁ POR DEBAJO del cutoff, los candidatos timed-out SÍ se descartan, consumidor lo ve vía metadata | ✓ Validated — Phase 2 D2 verification test pins behavior |
| Skip-if-you-can en visit pass | Visitar 20 sitios por query es lento (30-60s); skip si SERP ya trae precio o MELI link | ✓ Validated — Phase 2 + 3 acceptance |
| NO scrapear MELI directamente; usar Google con `+mercadolibre` query | API oficial 403 incluso autenticada post-abril 2025; browser-path → `/gz/account-verification` redirect; proxy residencial deferido | ✓ Validated — Phase 1 spike confirmed; WR-01 (Phase 3.1) hardened guard con tldextract |
| 1 container Docker, no browser-pool desacoplado | Cloak embebido vía Playwright en mismo proceso suficiente para 1 fuente | ✓ Validated — Phase 2 ship, Phase 3 hardening |
| Cloakbrowser sin Camoufox fallback | v1 nunca ejerció el fallback en producción | ✓ Validated — Phase 2 ship sin Camoufox |
| Singleton Browser + ephemeral `new_context()` per request (D8) | Cloak issue #331: `launch_persistent_context` = CAPTCHA loop garantizado | ✓ Validated — Phase 1 spike + Phase 2 footgun test enforces |
| `--loop asyncio --workers 1` siempre, uvloop BANNED (D6) | Cloak subprocess pipe incompatible con uvloop | ✓ Validated — Phase 2 CI grep assertion |
| Parser cascade `tF2Cxc → Ez5pwe → MjjYud → h3-anchored` con `parse.cascade.exhausted` alert (D4) | Google rota selectors obfuscados ~trimestralmente | ✓ Validated — Phase 2 production; Phase 3 fixture-replay confirms |
| Heuristic junk-domain blocklist ANTES del LLM (D9) | Drops ~30% del noise pre-LLM; reduce p95 ~22s → ~10s | ✓ Validated — Phase 2 production |
| Phase 3 D-05/D-06 — slowapi Pattern B (module constants → decorator + log line) | Pattern A (`Limiter(default_limits=...)`) requires SlowAPIMiddleware which crashes on slowapi 0.1.9 + FastAPI; Pattern B preserves single-source-of-truth intent without broken middleware | ✓ Validated — Phase 3.1 D-06 empirical retest PASS (5×200 + 1×429 with new rate in log) |
| Phase 3 ChallengeBackoff via aiosqlite single-row + bind-mount survives `compose up --force-recreate` | State must survive container recreation | ✓ Validated — Phase 3 UAT test 8 |
| Phase 3 `/metrics` ASGI sub-app mounted before CorrelationIdMiddleware, unauthenticated by design (D-10) | Prometheus scrapers cannot send X-API-Key; design choice pinned by test_metrics_endpoint_unprotected_by_design | ✓ Validated — Phase 3 production |
| Phase 3.1 WR-01 MELI guard with `tldextract.registered_domain` match (8 MELI registered domains frozenset) | Substring `"mercadolibre." in netloc` over-matched `notmercadolibre.com`; tldextract 5.3.1 already pinned + public-suffix-aware | ✓ Validated — regression test `test_meli_guard_no_false_positive_on_notmercadolibre` PASS |
| Phases 4-5 deferred-by-design — re-evaluated at v0.2 trigger conditions | Both carry 0 v1 reqs; Phase 4 on-demand from prod telemetry, Phase 5 growth-triggered | ✓ Recorded in MILESTONES.md; revisit at `/gsd-new-milestone` for v0.2 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition**:
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-06 — Milestone v0.2 shipped; 4 phases + 11 plans, 17/17 active reqs SATISFIED (2 cancelled per no-paid-services rule); suite 124/2 with 0 warnings*

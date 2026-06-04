# artiscrapper

## What This Is

Servicio HTTP que dada una query de búsqueda (e.g. `"filtro aire ranger"`) devuelve una lista curada de productos comerciales que reflejan lo que una persona vería buscando en Google manualmente, enriquecidos con precio, validación de destino vivo, y filtrados por un LLM local para descartar blogs/wikis/contenido irrelevante. Cliente único: **Sánchez Repuestos** (taller / casa de repuestos AR) — alimenta su app interna de gestión de productos y pedidos + workflows n8n.

**Shipped en v0.1 (2026-06-04):** servicio funcional 1-container production-ready con `/search`, `/health`, `/metrics`, X-API-Key auth, slowapi rate-limit (Pattern B settings-source-of-truth), challenge-backoff, degraded-mode fallback, fixture-replay integration suite (≥85% catalog price extraction empirically validated at 100%), Sentry-ready (env-gated).

## Core Value

**Si solo una cosa tiene que funcionar bien**: el endpoint `POST /search` recibe una query con `X-API-Key`, dispara 2 fetches a Google (`q` y `q +mercadolibre`), filtra con LLM local para quedarse solo con productos comprables, valida live + precio visitando los survivors cuando hace falta, y devuelve un JSON ordenado por relevancia. El consumidor recibe **productos que existen, con precio, link y procedencia clara** — empíricamente validado en v0.1 contra queries reales `pelota playera quico` y `filtro aceite ford focus`.

## Current State (v0.1 — shipped 2026-06-04)

- **Production-ready single-container deploy**: Dockerfile multi-stage con `cloakhq/cloakbrowser:0.3.31` + Chromium pin `v146.0.7680.177.5`, `tini`/`--init`, `uv sync --locked`, sqlite bind-mount `./data/cache.db`. CI-asserted no-uvloop + no-launch_persistent_context invariants.
- **Pipeline integrado**: `/search` → cache lookup → ChallengeBackoff gate → 2 parallel Google fetches (rate-limited 1/min) → block detection → parser cascade `tF2Cxc → Ez5pwe → MjjYud → h3-anchored` con `parse.cascade.exhausted` alert → URL dedupe + junk blocklist → LLM curator con Semaphore(4) + `<0.4` confidence cutoff + degraded-mode price-in-card fallback → visit pass con httpx http2 + global+per-host Semaphores + hand-rolled JSON-LD/OG/microdata/AR-regex extractor → freshness assessment → rerank → background cache-write.
- **Observability**: structlog JSON + `merge_contextvars` + correlation_id en todo evento + asgi-correlation-id middleware; `/metrics` ASGI sub-app expone 12 canonical `artiscrapper_*` Prometheus families + workload-tuned Histograms; env-gated Sentry con correlation_id tag injection (off when DSN empty); `/health` cheap + `/health/deep` real (gated auth).
- **Resilience**: X-API-Key auth con `hmac.compare_digest` constant-time; stacked slowapi rate-limit `(60/min + 10000/day)` Pattern B (module constants → decorator argument + log line, drift impossible by construction); ChallengeBackoff state machine `min(60·2^retries, 3600)` con sqlite single-row persistence surviving `compose up --force-recreate`; 503+Retry-After when gate denies.
- **Test surface**: 68 unit + 9 integration + 2 e2e (E2E=1 gated) = 79 tests; mypy --strict on `src/artiscrapper/` clean; ruff + format clean on production files. PRD §10 success criteria validated by operator UAT 2026-06-02.

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

### Active (v0.2 — TBD)

To be defined via `/gsd-new-milestone` at next planning session. Candidate triggers:

- **Phase 4 candidates** (gated on prod telemetry): Grafana dashboards, Loki log aggregation, cache invalidation endpoint, OpenTelemetry tracing.
- **Phase 5 candidates** (gated on growth): per-supplier adapters (Mayorista Frog first if requested), residential proxy (if Google IP-block >5%/day sustained), `/search/stream` SSE (if P95 cold >40s sustained 7+ days), multi-tenant auth (if 2nd consumer onboards).
- **Carried tech debt**: tldextract 6.x migration, FastAPI ORJSONResponse cleanup, httpx2 test migration, scripts/spike/ ruff debt.

### Out of Scope (still valid post-v0.1)

- **Scraping directo de MercadoLibre** (cualquier `*.mercadolibre.*` endpoint) — confirmed by Phase 1 spike: IP-blocked sin proxy residencial; MELI catálogo sale vía Google con `+mercadolibre`. WR-01 (Phase 3.1) hardened guard con tldextract.registered_domain match.
- **Proxy residencial / mobile / IP rotation** — costo + fricción no justificados a este scope; revisit only if Phase 5 trigger fires.
- **Multi-engine browser fallback** (Camoufox) — Cloak es suficiente, v1 demostró que Camoufox no agregaba valor real.
- **Async + SSE en /search** — sync HTTP cubre el SLA (PRD §10); Phase 5 candidate only if latency trigger fires.
- **Workers / RQ / Redis / message queues** — sync HTTP cubre el caso de uso.
- **Postgres + Alembic** — sqlite local cubre el cache; sin datos relacionales.
- **Multi-tenant auth** — un solo cliente (Sánchez); X-API-Key estático alcanza hasta que se onboardee un segundo consumidor.
- **Marketplaces que no aparecen en Google** (eBay AR, Tiendanube específicas) — Google es el descubridor.
- **Partner Program MELI** — investigado, deferido indefinidamente.
- **uvloop** — banned (D6 foot-gun, Cloak subprocess incompatibility, CI grep assertion enforces).
- **launch_persistent_context** — banned (D8 foot-gun, Cloak issue #331, footgun test enforces).

## Context

- **Successor of**: versión 1 de artiscrapper (descartada 2026-06-01, git history wiped). v1 tenía ~15.000 LOC, 5 containers Docker, 6 fases roadmap, multi-source orchestrator con browser-pool desacoplado. Entregaba ~7 productos por query sin precio confiable. v0.1 entrega el mismo dominio en ~5,876 LOC, 1 container, 4 fases, con 55/55 reqs SATISFIED y empirical validation contra queries reales.
- **Knowledge preservado del v1** (ahora en código v0.1): parser de Google SERP (`div.tF2Cxc`, `div.Ez5pwe`, h3-anchored fallback), extracción precio AR (`$\xa018.032,30` → Decimal), junk-domain blocklist (youtube/fandom/wiki/reddit/quora), setup Cloakbrowser para Google con `pws=0&safe=off`.
- **Cliente operacional**: Sánchez Repuestos ya tiene app de gestión + workflows n8n en producción. v0.1 se enchufa como dependencia HTTP. Degradación graceful via `metadata.llm_degraded=true` (LLM-06) y 503+Retry-After (ChallengeBackoff) si Google rotea challenges.
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
- **Google rate limit — 60s gap**: `GoogleRateLimiter(min_interval_s=60)` in lifespan.
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
*Last updated: 2026-06-04 after v0.1 milestone (shipped)*

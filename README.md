# artiscrapper

Servicio HTTP de un solo contenedor que recibe una query de búsqueda (ej. `"filtro aceite ford focus"`) y devuelve una lista curada de productos comerciales — los mismos que vería una persona buscando en Google manualmente, pero enriquecidos con precio, validación de destino vivo, y filtrados por un LLM local para descartar blogs, wikis y contenido irrelevante. Cliente único: **Sánchez Repuestos** (taller / casa de repuestos AR); alimenta su app interna de gestión de productos y pedidos más workflows de n8n. La arquitectura es deliberadamente minimalista (1 contenedor, sqlite, sync HTTP) — el v1 del proyecto entregaba lo mismo con 5 contenedores y 15.000 LOC; v0.1 lo destila a ~5.876 LOC con 55/55 requisitos satisfechos.

## Tecnologías

| Categoría | Tecnología |
|-----------|------------|
| Lenguaje | Python 3.12+ |
| Framework HTTP | FastAPI 0.136.3 |
| Server | uvicorn (`--loop asyncio --workers 1`; uvloop banneado por D6) |
| Browser scraping | Cloakbrowser 0.3.31 (Chromium v146.0.7680.177.5, vía Playwright embebido) |
| Parser HTML | selectolax 0.4+ |
| Cliente HTTP | httpx 0.28+ (HTTP/2) |
| Validación | Pydantic + pydantic-settings |
| Cache | aiosqlite + WAL + gzip BLOB |
| LLM client | OpenAI-compat HTTP contra `local-llms-router` |
| Auth | X-API-Key con `hmac.compare_digest` constant-time |
| Rate limit | slowapi 0.1.9 (Pattern B: módulo constants → decorator + log) |
| Observabilidad | structlog 25+, asgi-correlation-id, prometheus-client |
| Crash reporting | sentry-sdk (env-gated, off por default) |
| Parsing TLD | tldextract 5.3.1 (guardia MELI suffix-aware) |
| Build/lock | uv (`uv.lock` reproducible) |
| Testing | pytest 9+, pytest-asyncio 1.4, respx 0.23 |
| Lint / format | ruff |
| Type check | mypy --strict (sobre `src/artiscrapper/`) |
| Infraestructura | Docker Compose v2, base image `cloakhq/cloakbrowser:0.3.31` |

## Requisitos previos

- **Sistema operativo**: Linux con `apt-get`, `dnf`, `yum`, `apk`, o `pacman` (el instalador detecta cuál). Testeado en Debian 12 y Ubuntu 22.04.
- **Docker**: Docker Engine + plugin `docker compose v2`. El instalador los provisiona automáticamente si faltan.
- **Internet**: para tirar la imagen base `cloakhq/cloakbrowser:0.3.31` desde Docker Hub (~1.5 GB, primer build 5-25 minutos).
- **CPU/RAM**: 2 vCPU + 2 GB RAM mínimo. Chromium dentro de Cloak consume ~500 MB residente; recomendado 4 GB para holgura.
- **`local-llms-router`** corriendo en la misma máquina (otro proyecto del cliente) con un bearer token válido. Sin esto, el LLM curator entra en modo degradado y `metadata.llm_degraded=true` en cada respuesta.
- **Python 3.12+** (solo para desarrollo local sin Docker). El runtime de producción corre dentro del contenedor.
- **Tailscale** (opcional) para acceso interno por VPN al VPS de Sánchez Repuestos.

## Instalación

El proyecto tiene un instalador autosuficiente (`install.sh`) que resuelve dependencias del sistema, permisos, autenticación de GitHub si el repo es privado, descubrimiento del `local-llms-router` y generación del `.env`. Este es el camino principal — el flujo manual queda como referencia.

### Instalación con el script (recomendada)

```bash
curl -sL https://raw.githubusercontent.com/luishelgueradev/artiscrapper/main/install.sh | bash
```

Para repos privados:

```bash
GH_TOKEN=ghp_xxxx curl -sL https://raw.githubusercontent.com/luishelgueradev/artiscrapper/main/install.sh | bash
```

Para correr 100% desatendido (sin prompts):

```bash
LLM_ROUTER_BEARER_TOKEN=... \
API_KEYS=key1,key2 \
LLM_ROUTER_URL=http://host.docker.internal:3210 \
HOST_PORT=8000 \
curl -sL https://raw.githubusercontent.com/luishelgueradev/artiscrapper/main/install.sh | bash
```

El instalador hace todo: instala `git`, `docker`, `docker compose v2`, `gh` si hace falta; prepara `/opt/luishelgueradev/artiscrapper` con permisos correctos; agrega al usuario al grupo `docker`; clona el repo; detecta el container `local-llms-router` corriendo en la máquina; pregunta los secretos (`LLM_ROUTER_BEARER_TOKEN`) o los genera (`API_KEYS`); persiste el `.env` con `chmod 600`; builda la imagen; levanta el contenedor; valida `/health` con 30 reintentos.

### Instalación manual (desarrollo local)

```bash
# Clonar
git clone https://github.com/luishelgueradev/artiscrapper.git
cd artiscrapper

# Setup Python local (opcional, para tests fuera de Docker)
uv sync --locked

# Configurar .env
cp .env.example .env
# Editar .env con LLM_ROUTER_BEARER_TOKEN y API_KEYS (mínimo)

# Crear bind-mount sqlite
mkdir -p data && touch data/cache.db

# Build + levantar
docker compose build
docker compose up -d --force-recreate
```

Nota: por un bug conocido de `docker compose v2`, `compose up --build` no siempre recrea el contenedor post-build. Usar los pasos por separado (`build` y `up --force-recreate`) — está documentado en la memoria del proyecto `feedback_compose_build_recreate`.

## Configuración

Las variables se persisten en `.env` (chmod 600) y `docker compose` las inyecta automáticamente al contenedor. El instalador maneja todas; podés sobreescribirlas pasándolas por entorno antes de correr `install.sh`. El archivo `.env.example` lista todas las opciones documentadas.

| Variable | Default | Descripción | Requerida |
|----------|---------|-------------|-----------|
| `LLM_ROUTER_BEARER_TOKEN` | — | Bearer token del `local-llms-router`. Sin esto el LLM curator falla y `llm_degraded=true` en cada response. | Sí |
| `LLM_ROUTER_URL` | `http://host.docker.internal:3210` | URL del backend LLM (OpenAI-compat `/v1/chat/completions`). | No |
| `LLM_MODEL` | `llama3.2:3b-instruct-q4_K_M` | Modelo a usar contra el router. | No |
| `API_KEYS` | (vacío) | API keys (CSV) para autenticar consumidores. Sin esto **todo `/search` devuelve 401**. El instalador genera una si no se pasa. | Sí |
| `API_RATE_PER_MINUTE` | `60` | Quota slowapi por API-key por minuto. Wired a `_RATE_LIMIT_PER_MINUTE` en `main.py` (Pattern B). | No |
| `API_RATE_PER_DAY` | `10000` | Quota slowapi por API-key por día. | No |
| `SENTRY_DSN` | (vacío) | DSN de Sentry. Vacío = SDK NO se inicializa (default seguro). | No |
| `HOST_PORT` | `8000` | Puerto del host (el contenedor siempre escucha en `:8000` interno). | No |
| `GOOGLE_MIN_INTERVAL_S` | `60` | Gap mínimo entre fetches a Google (rate-limit interno por VPS). | No |
| `BROWSER_RECYCLE_AFTER` | `200` | Fetches antes de reciclar el singleton Browser. | No |
| `LLM_CONCURRENCY` | `4` | Semáforo del curator LLM. | No |
| `LOG_JSON` | `true` | structlog JSON output (recomendado en prod). | No |
| `LOG_LEVEL` | `INFO` | Nivel de log. | No |
| `CACHE_DB_PATH` | `/app/cache.db` | Path al sqlite cache dentro del contenedor. Hardcoded en `compose.yml`. | No |

### Bump de quotas en vivo

Por el refactor Pattern B (Phase 3.1 D-05), los strings de slowapi se computan al import-time desde `settings`. Para bumpear sin downtime de configuración:

```bash
cd /opt/luishelgueradev/artiscrapper

# Editar .env (ej. API_RATE_PER_MINUTE=120)
nano .env

# Aplicar: build + recreate por separado (memoria feedback_compose_build_recreate)
docker compose build
docker compose up -d --force-recreate

# Confirmar que el nuevo valor llegó al runtime hot path
docker compose logs | grep rate_limit_init
# → {"per_minute": "120/minute", "per_day": "10000/day",
#    "source": "module_constants_from_settings", ...}
```

## Uso

| Comando | Descripción |
|---------|-------------|
| `docker compose build` | Construir la imagen (multi-stage: builder uv + runtime cloak) |
| `docker compose up -d --force-recreate` | Levantar el contenedor (siempre con `--force-recreate` post-`.env` change) |
| `docker compose down` | Detener y eliminar el contenedor |
| `docker compose logs -f` | Ver logs en vivo (structlog JSON con correlation_id) |
| `docker compose ps` | Estado del contenedor |
| `docker compose restart` | Reiniciar sin rebuild |
| `uv run pytest tests/ -x -q -k "not e2e"` | Suite local (68 unit + 9 integration); requiere `LLM_ROUTER_BEARER_TOKEN=test-token` |
| `uv run ruff check src/ tests/` | Lint |
| `uv run ruff format src/ tests/` | Format |
| `uv run mypy --strict src/artiscrapper/` | Type check estricto (clean en main) |

### Desarrollo local

Para iterar fuera de Docker (más rápido para cambios al pipeline):

```bash
uv sync --locked
export LLM_ROUTER_BEARER_TOKEN=...
export API_KEYS=test-key-1
export CACHE_DB_PATH=./data/cache.db
uv run uvicorn src.artiscrapper.main:app --reload --port 8000
```

El singleton Browser en `lifespan` necesita conexión a Cloakbrowser; si no hay container Docker corriendo, los tests usan mocks (`respx` + monkeypatched `fetch_serp`). Para correr el suite completo:

```bash
LLM_ROUTER_BEARER_TOKEN=test-token uv run pytest tests/ -v
```

### Producción

Ver [`DEPLOY.md`](./DEPLOY.md). Resumen: `install.sh` deja todo levantado en `/opt/luishelgueradev/artiscrapper` con el contenedor exponiendo `:HOST_PORT`. El acceso público se maneja a nivel VPS con nginx delante (Let's Encrypt) o acceso interno por IP de Tailscale.

### Smoke test

```bash
curl -X POST http://localhost:8000/search \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: <tu-api-key>' \
  -d '{"query": "filtro aceite ford focus"}'
```

Respuesta esperada: ≥10 resultados, ≥6 con `price` no nulo, cero blogs/wiki/youtube en top 10 (criterio PRD §10).

## Arquitectura del proyecto

```
├── src/artiscrapper/
│   ├── main.py                # FastAPI app + lifespan + /search + /health + /metrics mount
│   ├── auth.py                # X-API-Key Depends + slowapi key_func
│   ├── browser.py             # Cloak singleton + fetch_serp + _detect_block
│   ├── cache.py               # aiosqlite WAL + gzip BLOB + prune loop + challenge_state
│   ├── challenge_backoff.py   # State machine + sqlite single-row persistence
│   ├── config.py              # pydantic-settings (API_RATE_*, LLM_*, BROWSER_*)
│   ├── freshness.py           # FRESH-01..04: MELI live, JSON-LD datePublished, blog drop
│   ├── llm.py                 # OpenAI-compat client + curate_candidates + fallback
│   ├── logging_setup.py       # structlog + correlation_id + Sentry init derivado de SDK state
│   ├── metrics.py             # Counter + Histogram families + tldextract host norm
│   ├── models.py              # SearchRequest/Response/Candidate/Metadata
│   ├── rate_limit.py          # GoogleRateLimiter (1/min interno hacia Google)
│   ├── search.py              # build_serp_url + parse_serp cascade + dedupe + rerank
│   └── visit.py               # httpx + extractor cascade + MELI guard (tldextract)
├── tests/
│   ├── integration/           # 9 tests: catalog extraction, challenge backoff,
│   │                          # degraded mode (full-route TestClient), metrics endpoint,
│   │                          # rate limit 429
│   ├── fixtures/              # 10 SERP HTML + 10 catalog PDP + 50 hand-labeled LLM
│   ├── test_auth.py           # X-API-Key 401/200
│   ├── test_cache.py          # aiosqlite WAL + gzip roundtrip + lazy TTL
│   ├── test_challenge_backoff.py  # State machine + module constants
│   ├── test_e2e.py            # E2E gated (E2E=1, requiere dev-box)
│   ├── test_footguns.py       # No uvloop, no persistent_context, recycle invariant
│   ├── test_health.py         # /health shape + deep + nunca rate-limited
│   ├── test_llm.py            # Verdict + fallback + concurrency semáforo
│   ├── test_main.py           # Pattern B propagation invariant (D-05)
│   ├── test_parser.py         # SERP cascade + carousel + commercial signals
│   ├── test_sentry_init.py    # WRN-04 lifespan log matches SDK state
│   └── test_visit.py          # Extractor cascade + MELI guard + AR precio regex
├── compose.yml                # Docker Compose v2 (artiscrapper + bind-mount cache.db)
├── Dockerfile                 # Multi-stage: builder (uv) + runtime (cloak)
├── pyproject.toml             # Deps + ruff + pytest + mypy config
├── uv.lock                    # Lockfile reproducible (sin uvloop — D6 invariant)
├── .env.example               # Plantilla con todas las vars documentadas
├── install.sh                 # Instalador autosuficiente (curl | bash)
├── DEPLOY.md                  # Guía de deploy (arquitectura, troubleshooting)
├── .planning/                 # Framework GSD (PROJECT, MILESTONES, ROADMAP, RETROSPECTIVE)
│   └── milestones/v0.1-*.md   # Archivos archivados del milestone v0.1
└── data/
    └── cache.db               # sqlite cache (bind-mount, persiste fuera del contenedor)
```

### Flujo del pipeline `/search`

```
Request POST /search (X-API-Key)
   │
   ▼
[Middleware] CorrelationIdMiddleware → corr_id en logs + Sentry tag
   │
   ▼
[Decorator] @limiter.limit(_RATE_LIMIT_PER_MINUTE) + @limiter.limit(_RATE_LIMIT_PER_DAY)
   │  (429 + Retry-After si excede)
   ▼
[Depends] verify_api_key → 401 si X-API-Key falta o no matchea
   │
   ▼
[Histogram] search_elapsed.time() abre el bracket
   │
   ▼
get_cached(query_norm)   ─── hit? ───▶ 200 + cache_hit=true (early return)
   │ miss
   ▼
check_gate(cache)  ─── closed? ───▶ 503 + Retry-After + block_detected=true
   │ open
   ▼
asyncio.gather(
   fetch_serp(browser, url_q),
   fetch_serp(browser, url_q+mercadolibre)
) con GoogleRateLimiter(60s)
   │
   ▼
_detect_block(htmls) ─── true? ───▶ record_block + 200 con block_detected=true
   │ no
   ▼
parse_serp cascade (tF2Cxc → Ez5pwe → MjjYud → h3-anchored)
   │
   ▼
dedupe + is_junk blocklist (drops ~30% pre-LLM)
   │
   ▼
record_success (D-07 ≥1h reset, WR-07 solo si hay survivors)
   │
   ▼
router_health_check ─── falla? ───▶ degraded: heurístico price-in-card
   │ ok                                            (llm_degraded=true)
   ▼
curate_candidates (Semáforo(4), 5s timeout, <0.4 cutoff, drop blogs)
   │ con inc_llm_fallback(reason) en 6 sitios
   ▼
visit_candidates (httpx http2, Sem global(8) + per-host(2),
                  MELI guard tldextract, extractor JSON-LD/OG/microdata/AR-regex)
   │ con inc_visit_failed(host)
   ▼
assess_freshness (MELI 200 → fresh; datePublished <90d → fresh; blog → drop)
   │
   ▼
rerank (has_price DESC, fresh DESC, llm_confidence DESC) + truncate max_results
   │
   ▼
Background: asyncio.create_task(set_cached) + strong-ref (WR-02 invariant)
   │
   ▼
200 con results[] + metadata (9 campos)
```

## API / Endpoints

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| POST | `/search` | `X-API-Key` | Pipeline principal — query → resultados curados |
| GET | `/health` | (sin auth) | Liveness probe, <50ms. Verifica cloak + cache. Para LB. |
| GET | `/health/deep` | `X-API-Key` | Roundtrip real — Chromium nav + LLM HEAD. NUNCA del LB. |
| GET | `/metrics` | (sin auth — D-10) | Prometheus exposition. 12 familias `artiscrapper_*`. |

### POST `/search`

**Body** (Pydantic):

```json
{
  "query": "filtro aceite ford focus",
  "max_results": 15,
  "visit_timeout_s": 10
}
```

| Campo | Default | Descripción |
|-------|---------|-------------|
| `query` | (requerido) | Texto de búsqueda |
| `max_results` | `15` | Tope de resultados a devolver |
| `visit_timeout_s` | `10` | Timeout por candidato en el visit pass |

**Headers obligatorios**:

```
Content-Type: application/json
X-API-Key: <una de las API_KEYS del .env>
```

**Respuestas**:

| Código | Significado | Body |
|--------|-------------|------|
| 200 | OK (incluye modo degradado y cache hit) | `{ "results": Candidate[], "metadata": Metadata }` |
| 401 | `X-API-Key` faltante o inválida | `{ "detail": "Missing X-API-Key header" }` / `"Invalid API key"` |
| 429 | Rate limit excedido | `{ "error": "Rate limit exceeded: N per 1 minute" }` + `Retry-After` |
| 503 | ChallengeBackoff activo (Google detectó captcha) | `{ "metadata": { "block_detected": true } }` + `Retry-After` |
| 422 | Body inválido (Pydantic) | Pydantic validation errors |

**Campos de `metadata`** (siempre presentes):

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `elapsed_ms` | int | Wall-clock total del pipeline |
| `google_fetches` | int | Cantidad de fetches a Google (0=cache hit, 2=miss) |
| `candidates_total` | int | Candidatos post-parse antes de filtros |
| `llm_filtered_out` | int | Descartes del LLM curator |
| `visited` | int | Candidatos a los que se les hizo visit pass |
| `visit_failed` | int | Visits que devolvieron `visit_failed` flag |
| `cache_hit` | bool | True si el resultado vino del sqlite cache |
| `llm_degraded` | bool | True si el LLM router está caído y el pipeline cayó al heurístico |
| `block_detected` | bool | True si `_detect_block` disparó o si el ChallengeBackoff gate denegó |

### GET `/metrics`

Exposición Prometheus estándar. Familias relevantes:

```
artiscrapper_search_elapsed_seconds_{bucket,count,sum}
artiscrapper_llm_elapsed_seconds_{bucket,count,sum}
artiscrapper_visit_elapsed_seconds_{bucket,count,sum}{stage=fetch|classify|extract}
artiscrapper_llm_fallback_total{reason=timeout|invalid_json|router_down|...}
artiscrapper_visit_failed_total{host=<tld+1>}
artiscrapper_block_detected_total{reason=sorry|captcha|...}
```

`/metrics` es **público por diseño** (decisión D-10): los scrapers de Prometheus no pueden mandar `X-API-Key`. Si se expone públicamente, restringir por IP allow-list en el reverse proxy.

## Docker

El proyecto vive en un único contenedor (`artiscrapper-artiscrapper-1` por convención de docker compose).

### Dockerfile

Multi-stage para reducir tamaño final:

| Stage | Base | Propósito |
|-------|------|-----------|
| `builder` | `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` | `uv sync --locked --no-editable` con cache montado |
| `runtime` | `cloakhq/cloakbrowser:0.3.31` | Cloakbrowser + Chromium v146 + `libnspr4` + `libnss3` + `tini` |

- **Puerto interno**: `8000`
- **ENTRYPOINT**: `tini --` (DEPLOY-04: zombie reaping de procesos hijos de Chromium)
- **CMD**: `uvicorn src.artiscrapper.main:app --host 0.0.0.0 --port 8000 --workers 1 --loop asyncio` (uvloop banneado por D6 — incompatible con subprocess pipe de Cloak)

### compose.yml

Un solo servicio (`artiscrapper`):

- `ports`: `${HOST_PORT:-8000}:8000` — override con `HOST_PORT=8001 docker compose up`
- `volumes`: `./data/cache.db:/app/cache.db` (bind-mount sqlite — sobrevive `--force-recreate`)
- `extra_hosts`: `host.docker.internal:host-gateway` (resuelve el host en Linux sin Docker Desktop)
- `init: true` (equivalente a tini si no se usa `ENTRYPOINT tini`)
- `environment`: las variables del `.env` con defaults sensatos

### Comandos Docker útiles

```bash
# Build inicial (5-25 min por la imagen base cloak)
docker compose build

# Levantar
docker compose up -d --force-recreate

# Logs en vivo (structlog JSON con correlation_id)
docker compose logs -f artiscrapper

# Ejecutar comando dentro del container
docker compose exec artiscrapper python -c "from src.artiscrapper.config import settings; print(settings)"

# Inspeccionar el sqlite cache
sqlite3 data/cache.db "SELECT COUNT(*) FROM serp_cache;"

# Bajar todo
docker compose down
```

## Deploy

Ver [`DEPLOY.md`](./DEPLOY.md) para la guía completa. Resumen:

- **Estrategia**: 1 contenedor en VPS Linux, levantado por `install.sh`. Datos persisten en `/opt/luishelgueradev/artiscrapper/data/cache.db` vía bind-mount.
- **Reverse proxy**: el contenedor expone HTTP plano en `${HOST_PORT}`. El routing público se maneja a nivel VPS — el repo no incluye config de Traefik ni nginx; se documentan 3 opciones en `DEPLOY.md`:
  1. **Tailscale** (recomendado para uso interno Sánchez) — acceso por IP del VPN.
  2. **nginx delante con Let's Encrypt** — para acceso público con TLS y subdominio.
  3. **Solo localhost** — para smoke tests desde el propio VPS.
- **Actualización**: re-ejecutar `bash /opt/luishelgueradev/artiscrapper/install.sh` (idempotente — backup automático del `.env`, fetch del último `main`, rebuild + force-recreate). Alternativa rápida sin rebuild: `git pull && docker compose up -d --force-recreate`.
- **Health check**: `curl http://localhost:HOST_PORT/health` (devuelve `{"status":"ok","cloak":"ok","llm":"ok","cache":"ok"}` en <50ms).
- **Monitoreo**: `/metrics` expone 12 familias Prometheus + Histograms. `SENTRY_DSN` activa crash reporting solo si se setea.

`DEPLOY.md` incluye 8 escenarios de troubleshooting con causa raíz y comandos: `cloak: fail` en `/health`, 401 masivo, 503 con `Retry-After` (cómo resetear el `challenge_state` manualmente), `llm_degraded` persistente, build de 25 minutos, cache no persiste, bump de `API_RATE_PER_MINUTE` que no aplica, `local-llms-router` no encontrado.

## Estado del proyecto

**Milestone v0.1 — MVP — Google + LLM curator** completado el **2026-06-04**. Producción-listo.

- **55/55 requisitos v1 satisfechos** (SEARCH×8, LLM×8, VISIT×8, FRESH×4, CACHE×5, BROWSER×5, DEPLOY×6, OBS×7, NF×4).
- 4 fases entregadas (Spike + MVP + Robustness + v0.1 close hygiene), 11 plans, ~125 commits en 3 días.
- Auditoría de milestone: status `passed`, 10/10 integración cross-phase, 5/5 flujos E2E PASS, 3/3 VALIDATION.md aceptados. Reporte completo en `.planning/milestones/v0.1-MILESTONE-AUDIT.md`.
- Tag: `v0.1`.

**Fases 4 y 5 deferidas por diseño** — ambas con 0 requisitos v1, gateadas por triggers de producción (Fase 4 = demanda de telemetría real; Fase 5 = triggers de crecimiento). Se re-evalúan al inicio de v0.2.

**v0.2 — TBD** (se arranca con `/gsd-new-milestone` cuando aparezcan los triggers o nuevos requisitos del cliente). Tech debt acumulada documentada en `.planning/PROJECT.md` y `.planning/RETROSPECTIVE.md`: migración tldextract 6.x, cleanup de FastAPI ORJSONResponse, migración a httpx2 en tests, ruff debt en `scripts/spike/`.

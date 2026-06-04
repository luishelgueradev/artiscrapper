# Deploy — artiscrapper

Servicio HTTP single-container que expone `POST /search` para Sánchez Repuestos. Toda la operativa corre en **1 imagen Docker** (FastAPI + Cloakbrowser embebido + sqlite cache + slowapi rate-limit). Sin Postgres, sin Redis, sin worker-pool, sin Camoufox.

## Instalación rápida

```bash
curl -sL https://raw.githubusercontent.com/luishelgueradev/artiscrapper/main/install.sh | bash
```

Si el repo es privado, pasá el token:

```bash
GH_TOKEN=ghp_xxxx curl -sL https://raw.githubusercontent.com/luishelgueradev/artiscrapper/main/install.sh | bash
```

Para correr 100% desatendido (sin prompts), seteá todas las variables por entorno:

```bash
LLM_ROUTER_BEARER_TOKEN=... \
API_KEYS=key1,key2 \
LLM_ROUTER_URL=http://host.docker.internal:3210 \
HOST_PORT=8000 \
curl -sL https://raw.githubusercontent.com/luishelgueradev/artiscrapper/main/install.sh | bash
```

El instalador resuelve todo solo: instala `git`, `docker`, `docker compose v2`, `gh` (si el repo es privado), prepara `/opt/luishelgueradev/artiscrapper`, agrega al usuario al grupo `docker`, descubre el container `local-llms-router` corriendo en la máquina, pregunta solo lo que no puede inferir (bearer token, API keys), persiste el `.env` con permisos `600`, construye la imagen, levanta el container y valida `/health`.

## Requisitos

- **Sistema operativo**: Linux con uno de estos gestores de paquetes: `apt-get`, `dnf`, `yum`, `apk`, `pacman` (el instalador detecta cuál usar). Testeado en Debian 12 / Ubuntu 22.04 y derivados.
- **Internet**: para tirar la imagen base `cloakhq/cloakbrowser:0.3.31` desde Docker Hub. Primer build tarda **5-25 minutos** según ancho de banda (la imagen pesa).
- **CPU/RAM**: 2 vCPU + 2 GB RAM mínimo. Chromium dentro de Cloak consume ~500 MB residente; recomendado 4 GB para holgura.
- **`local-llms-router`** corriendo en la misma máquina con un bearer token válido. El instalador lo detecta automáticamente; default `http://host.docker.internal:3210`.
- **Tailscale** instalado en el VPS si querés acceso por VPN (opcional pero recomendado).

## Arquitectura

artiscrapper es un **único container Docker** que corre:

```
┌─────────────────────────────────────────────────────────────┐
│ container: artiscrapper-artiscrapper-1                      │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  FastAPI app (uvicorn --workers 1 --loop asyncio)   │    │
│  │  ─────────────────────────────────────────────────  │    │
│  │  POST /search        → pipeline curado              │    │
│  │  GET  /health        → liveness probe (<50ms)       │    │
│  │  GET  /health/deep   → roundtrip real (auth)        │    │
│  │  GET  /metrics       → Prometheus exposition        │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Cloakbrowser 0.3.31 (Chromium v146.0.7680.177.5)   │    │
│  │  Singleton en lifespan; ephemeral new_context()     │    │
│  │  por request; recycle cada 200 fetches.             │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  sqlite cache (aiosqlite + WAL + gzipped BLOB)      │    │
│  │  bind-mount: ./data/cache.db ↔ /app/cache.db        │    │
│  │  TTL 24h, prune horario, checkpoint nocturno        │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
       │                                       ▲
       │ httpx (OpenAI-compat)                 │ HTTP :8000 (HOST_PORT)
       ▼                                       │
┌─────────────────────────┐         ┌──────────────────────────┐
│ local-llms-router       │         │ Consumidor (app interna  │
│ (host.docker.internal)  │         │ Sánchez + workflows n8n) │
│ :3210                   │         │ con X-API-Key            │
└─────────────────────────┘         └──────────────────────────┘
```

### Componentes externos (no levantados por este container)

| Servicio | Ubicación | Para qué |
|----------|-----------|----------|
| **local-llms-router** | Otro container en el mismo VPS, mapeado a `host.docker.internal:3210` | Backend OpenAI-compat para el LLM curator (`POST /v1/chat/completions`) |
| **nginx / reverse proxy** | Opcional, a nivel VPS | Routing por subdominio + TLS si se expone públicamente. El container expone HTTP plano en el puerto del host |
| **Tailscale** | Opcional, a nivel VPS | Acceso interno por VPN (recomendado para la app de Sánchez) |
| **Sentry** | SaaS opcional, off por default | Crash reporting si `SENTRY_DSN` está seteada |

### Conectividad `local-llms-router`

Tres formas, en orden de preferencia que usa el instalador:

1. **Container detectado por nombre**: si hay un container llamado `local-llms-router` (o similar), el instalador extrae el puerto publicado y arma `http://host.docker.internal:PORT`.
2. **Puerto en el host**: si nada matchea por nombre pero hay un proceso escuchando en `127.0.0.1:3210`, asume `http://host.docker.internal:3210`.
3. **Fallback**: usa `http://host.docker.internal:3210` y deja que el usuario lo corrija después editando `.env`.

`host.docker.internal` resuelve a la IP del host gracias al `extra_hosts: ["host.docker.internal:host-gateway"]` en `compose.yml` (necesario en Linux; no-op en Docker Desktop).

## Variables de entorno

Las variables se persisten en `.env` (chmod 600) y `docker compose` las inyecta automáticamente. El instalador maneja todas; podés sobreescribirlas pasándolas por entorno antes de correr `install.sh`.

| Variable | Descripción | Default | Requerida |
|----------|-------------|---------|-----------|
| `LLM_ROUTER_BEARER_TOKEN` | Bearer token del `local-llms-router`. Sin esto, el LLM curator dispara `llm_degraded=true` en cada request y los resultados caen al heurístico solo. | — | **Sí** |
| `LLM_ROUTER_URL` | URL del backend LLM (OpenAI-compat `/v1/chat/completions`). | `http://host.docker.internal:3210` | No (auto-discover) |
| `LLM_MODEL` | Modelo a usar contra el router. | `llama3.2:3b-instruct-q4_K_M` | No |
| `API_KEYS` | API keys (CSV) para autenticar consumidores. Sin esto, **todo `/search` devuelve 401**. | (generada al instalar) | **Sí** |
| `API_RATE_PER_MINUTE` | Quota slowapi por API-key/min. Wired via Pattern B (módulo constants → decorator). | `60` | No |
| `API_RATE_PER_DAY` | Quota slowapi por API-key/día. | `10000` | No |
| `SENTRY_DSN` | DSN de Sentry. Vacío = SDK NO se inicializa. | (vacío) | No |
| `HOST_PORT` | Puerto del host (el container siempre escucha en `:8000` interno). | `8000` | No |
| `GOOGLE_MIN_INTERVAL_S` | Gap mínimo entre fetches a Google (rate-limit interno). Hardcoded en `compose.yml`. | `60` | No |
| `BROWSER_RECYCLE_AFTER` | Cantidad de fetches antes de reciclar el singleton Browser. | `200` | No |
| `LLM_CONCURRENCY` | Semáforo del curator LLM. | `4` | No |
| `LOG_JSON` | structlog JSON output (recomendado en prod). | `true` | No |
| `LOG_LEVEL` | Nivel de log. | `INFO` | No |
| `CACHE_DB_PATH` | Path al sqlite cache dentro del container. Hardcoded; no override. | `/app/cache.db` | No |

### Bump de quotas en vivo (Pattern B)

Por el refactor de Phase 3.1 D-05, `API_RATE_PER_MINUTE` y `API_RATE_PER_DAY` están wired desde `.env` hacia los decoradores `@limiter.limit()` AND la línea de log `rate_limit_init` vía **module constants en `main.py`**. Bumpear en vivo:

```bash
cd /opt/luishelgueradev/artiscrapper
# Editar .env (cambiar API_RATE_PER_MINUTE=120 por ejemplo)
nano .env

# Aplicar (separar build de recreate por bug conocido de compose)
docker compose build
docker compose up -d --force-recreate

# Confirmar que el valor llegó al runtime
docker compose logs | grep rate_limit_init
# → {"per_minute": "120/minute", "per_day": "10000/day",
#    "source": "module_constants_from_settings", "event": "rate_limit_init", ...}
```

## Servicios

| Servicio | Puerto interno | Mapeo al host | Descripción |
|----------|----------------|---------------|-------------|
| `artiscrapper` (FastAPI + uvicorn) | `8000` | `${HOST_PORT:-8000}:8000` | App principal — `/search`, `/health`, `/health/deep`, `/metrics` |

Volúmenes:

| Tipo | Source | Target | Descripción |
|------|--------|--------|-------------|
| bind-mount | `./data/cache.db` | `/app/cache.db` | sqlite cache persistente. Sobrevive `compose up --force-recreate` (validado por Phase 3 UAT). |

## Red y acceso

El container expone `:8000` **directamente al host** vía port-mapping (`HOST_PORT:8000`). **No hay labels de Traefik ni nginx config en el repo** — el routing público se maneja a nivel VPS (nginx delante con un server-block, o Tailscale + acceso por IP del VPN).

### Opción A: Tailscale (recomendado para uso interno Sánchez)

Acceso por la IP de Tailscale del VPS, sin DNS público.

```bash
# En el VPS (después de instalar)
tailscale ip -4
# → 100.64.x.y

# Desde tu máquina, agregás en /etc/hosts (opcional, para no recordar la IP):
100.64.x.y    artiscrapper.local
```

Luego accedés a `http://artiscrapper.local:8000/health` o directamente `http://100.64.x.y:8000/health`.

### Opción B: nginx delante (acceso público con TLS)

Si querés exponer públicamente con dominio + Let's Encrypt, agregás un server-block en el nginx del VPS:

```nginx
server {
    listen 443 ssl http2;
    server_name artiscrapper.tu-dominio.com.ar;

    ssl_certificate     /etc/letsencrypt/live/artiscrapper.tu-dominio.com.ar/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/artiscrapper.tu-dominio.com.ar/privkey.pem;

    # Health (público sin auth, <50ms)
    location = /health {
        proxy_pass http://127.0.0.1:8000;
    }

    # /metrics (público sin auth por diseño D-10 — Prometheus scrapers no mandan X-API-Key)
    # Restringí por IP allow-list a tu Prometheus
    location = /metrics {
        allow 100.64.0.0/10;  # red Tailscale
        deny all;
        proxy_pass http://127.0.0.1:8000;
    }

    # /search y resto requieren X-API-Key (lo enforcea la app, no nginx)
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;  # /search cold puede tardar 20-30s
    }
}
```

### Opción C: Solo localhost

Sin nada delante, `curl http://localhost:8000/health` directamente desde el VPS.

## Endpoints

| Endpoint | Método | Auth | Descripción |
|----------|--------|------|-------------|
| `/search` | POST | `X-API-Key` | Pipeline principal — query → resultados curados |
| `/health` | GET | (none) | Liveness probe, <50ms. Verifica cloak + cache. Para LB. |
| `/health/deep` | GET | `X-API-Key` | Roundtrip real — Chromium navigation + LLM HEAD. NUNCA del LB. |
| `/metrics` | GET | (none — D-10) | Prometheus exposition. 12 familias `artiscrapper_*`. |

Body de `/search`:

```json
{
  "query": "filtro aceite ford focus",
  "max_results": 15,
  "visit_timeout_s": 10
}
```

Headers obligatorios:

```
X-API-Key: <una de las API_KEYS del .env>
Content-Type: application/json
```

Smoke test:

```bash
curl -X POST http://localhost:8000/search \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: <tu-api-key>' \
  -d '{"query": "filtro aceite ford focus"}'
```

## Comandos útiles

Todos desde `/opt/luishelgueradev/artiscrapper`:

```bash
cd /opt/luishelgueradev/artiscrapper

# Logs en vivo
docker compose logs -f artiscrapper

# Logs últimas 100 líneas
docker compose logs --tail 100

# Reiniciar (sin rebuild)
docker compose restart

# Detener
docker compose down

# Estado
docker compose ps

# Stats de runtime
docker stats artiscrapper-artiscrapper-1

# Filtrar por correlation_id (todos los eventos de una request)
docker compose logs | grep '"correlation_id":"<id>"'

# Métricas Prometheus
curl http://localhost:8000/metrics | grep artiscrapper_

# Healh
curl http://localhost:8000/health
# → {"status":"ok","cloak":"ok","llm":"ok","cache":"ok"}

# Health profundo (requiere X-API-Key)
curl -H "X-API-Key: <key>" http://localhost:8000/health/deep
```

## Actualización

Para tirar la versión más nueva del repo:

```bash
bash /opt/luishelgueradev/artiscrapper/install.sh
```

El instalador es **idempotente**: detecta la instalación previa, hace backup del `.env`, baja el container, fetcha la rama, rebuildea, restaura el `.env` y levanta de nuevo. Si tu `.env` ya tiene `LLM_ROUTER_BEARER_TOKEN` y `API_KEYS`, no te vuelve a preguntar.

Si querés saltar el build y solo actualizar la config:

```bash
cd /opt/luishelgueradev/artiscrapper
git pull
docker compose up -d --force-recreate
```

## Troubleshooting

### `/health` devuelve `{"status":"degraded","cloak":"fail"}`

Cloakbrowser no levantó (o el lifespan se cayó). Pasos:

```bash
docker compose logs artiscrapper | grep -E "cloak|browser|chromium"
docker compose restart
# Si persiste, rebuild:
docker compose build --no-cache && docker compose up -d --force-recreate
```

Causa típica: falta `libnspr4` o `libnss3` en el build (no debería pasar — el Dockerfile las instala — pero si pasa, indica que la base `cloakhq/cloakbrowser:0.3.31` cambió). Verificá con:

```bash
docker compose exec artiscrapper apt list --installed 2>/dev/null | grep -E "libnspr4|libnss3"
```

### Todas las requests devuelven 401 "Missing X-API-Key header"

`API_KEYS` quedó vacío en `.env`. La app no rota keys en caliente — requiere restart:

```bash
cd /opt/luishelgueradev/artiscrapper
echo "API_KEYS=key-nueva-1,key-nueva-2" >> .env  # o editá la línea existente
docker compose up -d --force-recreate
docker compose logs | grep api_keys_loaded
# → {"count": 2, "rate_per_min": 60, ...}
```

### Todas las requests devuelven 503 con `Retry-After`

Google detectó challenge y activó ChallengeBackoff. Curva: `min(60·2^retries, 3600)` segundos. Esperá lo que diga el header. Si querés forzar el reset:

```bash
# Editar manualmente el row sqlite (ChallengeBackoff vive en cache.db)
sqlite3 /opt/luishelgueradev/artiscrapper/data/cache.db \
  "UPDATE challenge_state SET retry_count=0, next_allowed_at=0 WHERE id=1;"
docker compose restart
```

### `metadata.llm_degraded=true` en todas las respuestas

El `local-llms-router` no responde. Verificá:

```bash
# Desde el container hacia el router
docker compose exec artiscrapper curl -fsv \
  -H "Authorization: Bearer $(grep LLM_ROUTER_BEARER_TOKEN .env | cut -d= -f2)" \
  http://host.docker.internal:3210/healthz

# Si falla: confirma que el router está corriendo
docker ps | grep -i llms
```

Mientras el LLM está caído, `/search` sigue funcionando en modo degradado (devuelve resultados con `has_price=true` filtrados por blocklist heurística).

### `compose up --build` tarda 25 minutos

Es el primer build. La imagen `cloakhq/cloakbrowser:0.3.31` pesa ~1.5 GB y trae Chromium + Python + Playwright. **Bug conocido de docker compose v2**: en algunas versiones, `compose up --build` no recrea el container post-build. Usá los pasos por separado:

```bash
docker compose build
docker compose up -d --force-recreate
```

(Memoria del proyecto: `feedback_compose_build_recreate`.)

### Cache no persiste entre `compose up --force-recreate`

Verificá que el bind-mount esté presente:

```bash
docker compose config | grep -A2 volumes
# Debe mostrar: ./data/cache.db:/app/cache.db
ls -la /opt/luishelgueradev/artiscrapper/data/
# cache.db debe existir y tener tamaño > 0
```

Si `data/cache.db` no existe, recreá:

```bash
mkdir -p /opt/luishelgueradev/artiscrapper/data
touch /opt/luishelgueradev/artiscrapper/data/cache.db
docker compose up -d --force-recreate
```

### Bumpé `API_RATE_PER_MINUTE` en `.env` y los tests siguen pegando al rate viejo

Pattern B (D-05) lee `settings` al import-time. Necesita restart con `--force-recreate`:

```bash
docker compose build  # NO se necesita --no-cache (no cambió source)
docker compose up -d --force-recreate
docker compose logs | grep rate_limit_init
# debe mostrar el nuevo per_minute
```

Si el log sigue mostrando el valor viejo: revisá que el `.env` no tenga el viejo valor comentado encima del nuevo, y que `docker compose config` lo esté leyendo:

```bash
docker compose config | grep API_RATE
```

### El instalador no encuentra `local-llms-router`

Si el router no está corriendo todavía, instalalo primero (es otro proyecto del cliente). Después corré el instalador de artiscrapper. Alternativamente, pasá la URL manualmente:

```bash
LLM_ROUTER_URL=http://192.168.1.10:3210 \
LLM_ROUTER_BEARER_TOKEN=... \
bash install.sh
```

## Estructura del proyecto

```
/opt/luishelgueradev/artiscrapper/
├── install.sh                # Este instalador
├── DEPLOY.md                 # Este doc
├── compose.yml               # docker compose v2 spec
├── Dockerfile                # multi-stage: builder (uv) + runtime (cloak)
├── pyproject.toml            # Python 3.12+, FastAPI 0.136, slowapi 0.1.9, tldextract 5.3.1
├── uv.lock                   # lockfile reproducible (no uvloop — D6)
├── .env                      # generado por install.sh (chmod 600)
├── .env.example              # plantilla con todas las vars
├── data/
│   └── cache.db              # sqlite cache (bind-mount)
├── src/artiscrapper/
│   ├── main.py               # FastAPI app + lifespan + /search + /health + /metrics mount
│   ├── auth.py               # X-API-Key Depends + slowapi key_func
│   ├── browser.py            # Cloak singleton + fetch_serp + _detect_block
│   ├── cache.py              # aiosqlite WAL + gzip BLOB + prune loop
│   ├── challenge_backoff.py  # state machine + sqlite persistence
│   ├── config.py             # pydantic-settings (API_RATE_*, LLM_*, etc.)
│   ├── freshness.py          # FRESH-01..04 lógica
│   ├── llm.py                # OpenAI-compat client + curate_candidates + fallback
│   ├── logging_setup.py      # structlog + correlation_id + Sentry init
│   ├── metrics.py            # Counter + Histogram families + tldextract host norm
│   ├── models.py             # Pydantic SearchRequest/Response/Candidate/Metadata
│   ├── rate_limit.py         # GoogleRateLimiter (1/min interno)
│   ├── search.py             # build_serp_url + parse_serp cascade + dedupe + rerank
│   └── visit.py              # httpx + extractor cascade + MELI guard (tldextract)
├── tests/                    # 68 unit + 9 integration + 2 e2e gated
└── .planning/                # GSD workflow (PROJECT.md, MILESTONES.md, ROADMAP.md, etc.)
```

## Referencias

- **Auditoría v0.1**: `.planning/milestones/v0.1-MILESTONE-AUDIT.md` (status `passed`).
- **Roadmap**: `.planning/ROADMAP.md` + archivo histórico en `.planning/milestones/v0.1-ROADMAP.md`.
- **Requirements**: `.planning/milestones/v0.1-REQUIREMENTS.md` (55/55 v1 reqs SATISFIED).
- **Decisiones clave**: `.planning/PROJECT.md` §Key Decisions.
- **Retrospectiva**: `.planning/RETROSPECTIVE.md` (lessons + patterns + costos).

---
*Generado: 2026-06-04 — v0.1 shipped.*

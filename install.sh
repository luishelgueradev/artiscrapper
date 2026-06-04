#!/bin/bash
# =============================================================================
# artiscrapper — Instalador automatico
# =============================================================================
# Uso (con repo publico):
#   curl -sL https://raw.githubusercontent.com/luishelgueradev/artiscrapper/main/install.sh | bash
#
# Uso (con repo privado, pasando token):
#   GH_TOKEN=ghp_... curl -sL https://raw.githubusercontent.com/luishelgueradev/artiscrapper/main/install.sh | bash
#
# Uso (desatendido, todas las vars por entorno):
#   LLM_ROUTER_BEARER_TOKEN=... API_KEYS=key1,key2 curl -sL .../install.sh | bash
#
# Uso (desde el VPS, ya clonado):
#   bash /opt/luishelgueradev/artiscrapper/install.sh
#
# Que hace:
#   1. Instala git, curl, docker + docker compose v2, gh (si el repo es privado).
#   2. Asegura al usuario en el grupo docker y prepara /opt/luishelgueradev.
#   3. Si el repo es privado, autentica con gh (o usa GH_TOKEN/GITHUB_TOKEN).
#   4. Clona o actualiza el repo en /opt/luishelgueradev/artiscrapper.
#   5. Detecta el container `local-llms-router` corriendo en la maquina y
#      arma la URL de conexion (default: host.docker.internal:3210).
#   6. Pide LLM_ROUTER_BEARER_TOKEN (secreto) y API_KEYS (genera uno si falta).
#   7. Persiste .env con permisos 600.
#   8. Crea la carpeta data/ y el archivo cache.db (bind-mount sqlite).
#   9. Build + force-recreate + health check sobre /health.
#
# Requisitos:
#   - Linux con apt-get / dnf / yum / apk / pacman (instala el resto solo).
#   - Acceso a Internet (Docker Hub para la imagen cloakhq/cloakbrowser:0.3.31).
#   - Container local-llms-router corriendo en la misma maquina (o accesible
#     via host.docker.internal:3210 / IP especifica) con un bearer token valido.
# =============================================================================

set -euo pipefail

# -- Config ------------------------------------------------------------------
# Permiten override por entorno; defaultean a la configuracion canonica.
GIT_USER="${GIT_USER:-luishelgueradev}"
APP_NAME="${APP_NAME:-artiscrapper}"
INSTALL_DIR="${INSTALL_DIR:-/opt/${GIT_USER}/${APP_NAME}}"
REPO_URL="${REPO_URL:-https://github.com/${GIT_USER}/${APP_NAME}.git}"
GIT_BRANCH="${GIT_BRANCH:-main}"
HOST_PORT="${HOST_PORT:-8000}"

# Vars del .env que el instalador maneja (preguntables o derivables).
# Si vienen en el entorno se usan tal cual; si no, se preguntan o se descubren.
LLM_ROUTER_URL="${LLM_ROUTER_URL:-}"
LLM_ROUTER_BEARER_TOKEN="${LLM_ROUTER_BEARER_TOKEN:-}"
LLM_MODEL="${LLM_MODEL:-llama3.2:3b-instruct-q4_K_M}"
API_KEYS="${API_KEYS:-}"
API_RATE_PER_MINUTE="${API_RATE_PER_MINUTE:-60}"
API_RATE_PER_DAY="${API_RATE_PER_DAY:-10000}"
SENTRY_DSN="${SENTRY_DSN:-}"

# -- Colores -----------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# -- Banner ------------------------------------------------------------------
echo ""
echo "=========================================="
echo "  artiscrapper — Instalador"
echo "=========================================="
echo "  Destino: ${INSTALL_DIR}"
echo "  Repo:    ${REPO_URL} (rama ${GIT_BRANCH})"
echo "  Puerto:  ${HOST_PORT}"
echo "=========================================="
echo ""

# -- Helpers -----------------------------------------------------------------
have()  { command -v "$1" >/dev/null 2>&1; }

# sudo solo si no somos root y existe sudo
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if have sudo; then
    SUDO="sudo"
  else
    warn "Sin sudo ni root: instalacion de paquetes/permisos puede fallar."
  fi
fi

# Detectar gestor de paquetes una vez
PKG=""
for c in apt-get dnf yum apk pacman; do
  if have "$c"; then PKG="$c"; break; fi
done

pkg_install() {
  local p="$1"
  case "$PKG" in
    apt-get) $SUDO apt-get update -qq && $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$p" ;;
    dnf|yum) $SUDO "$PKG" install -y "$p" ;;
    apk)     $SUDO apk add --no-cache "$p" ;;
    pacman)  $SUDO pacman -Sy --noconfirm "$p" ;;
    *)       return 1 ;;
  esac
}

ensure_cmd() {
  local cmd="$1" pkg="${2:-$1}"
  if have "$cmd"; then ok "$cmd presente"; return 0; fi
  info "Falta '$cmd' — instalando paquete '$pkg'..."
  if pkg_install "$pkg" && have "$cmd"; then
    ok "$cmd instalado"
  else
    error "No pude instalar '$cmd' automaticamente. Instalalo y reintenta."
  fi
}

# Terminal para prompts interactivos (funciona incluso bajo `curl | bash`)
TTY=""
[ -e /dev/tty ] && TTY="/dev/tty"

# prompt VAR "Pregunta" "default"  — usa $VAR del entorno si ya viene seteada
prompt() {
  local __var="$1" __msg="$2" __def="${3:-}" __cur
  eval "__cur=\${$__var:-}"
  if [ -n "$__cur" ]; then return 0; fi
  if [ -z "$TTY" ]; then
    if [ -n "$__def" ]; then
      eval "$__var=\$__def"
      return 0
    else
      error "Falta $__var y no hay terminal para preguntarlo. Pasalo como variable de entorno."
    fi
  fi
  local __ans
  if [ -n "$__def" ]; then
    read -r -p "$__msg [$__def]: " __ans < "$TTY"
    __ans="${__ans:-$__def}"
  else
    read -r -p "$__msg: " __ans < "$TTY"
  fi
  eval "$__var=\$__ans"
}

prompt_secret() {
  local __var="$1" __msg="$2" __cur
  eval "__cur=\${$__var:-}"
  [ -n "$__cur" ] && return 0
  [ -z "$TTY" ] && error "Falta $__var (secreto) y no hay terminal. Pasalo como variable de entorno."
  local __ans
  read -r -s -p "$__msg: " __ans < "$TTY"
  echo ""
  eval "$__var=\$__ans"
}

gen_secret() {
  python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null \
    || openssl rand -base64 32 | tr -d '/+=' | cut -c1-43
}

# ============================================================================
# 1. Dependencias del sistema
# ============================================================================
info "Verificando dependencias del sistema..."

ensure_cmd curl curl
ensure_cmd git git

# Docker: si falta, instalar via script oficial
if ! have docker; then
  info "Instalando Docker (script oficial get.docker.com)..."
  curl -fsSL https://get.docker.com | $SUDO sh \
    || error "No pude instalar Docker. Instalalo manualmente: https://docs.docker.com/engine/install/"
  $SUDO systemctl enable --now docker 2>/dev/null || true
  ok "Docker instalado"
else
  ok "docker presente"
fi

# docker compose v2 (plugin)
if ! docker compose version >/dev/null 2>&1; then
  info "Instalando plugin docker-compose-v2..."
  pkg_install docker-compose-plugin 2>/dev/null \
    || pkg_install docker-compose 2>/dev/null \
    || warn "No pude instalar el plugin. Verifica 'docker compose version' manualmente."
fi
docker compose version >/dev/null 2>&1 && ok "docker compose v2 presente" \
  || error "Falta docker compose v2 (plugin). Instalalo y reintenta."

# openssl (para generar secretos si no hay python3)
ensure_cmd openssl openssl

# python3 (opcional — para gen_secret; sino openssl alcanza)
have python3 || warn "python3 no esta presente. Se usara openssl para generar secretos."

# ============================================================================
# 2. Permisos, grupo docker y carpeta /opt
# ============================================================================
info "Preparando ${INSTALL_DIR}..."

# Crear /opt/{git_user} con ownership del usuario real
$SUDO mkdir -p "/opt/${GIT_USER}"
CURRENT_USER="$(id -un)"
CURRENT_GROUP="$(id -gn)"
$SUDO chown "${CURRENT_USER}":"${CURRENT_GROUP}" "/opt/${GIT_USER}" 2>/dev/null || true

# Agregar al grupo docker si no esta
if have docker && [ "$CURRENT_USER" != "root" ] && ! id -nG "$CURRENT_USER" | grep -qw docker; then
  info "Agregando ${CURRENT_USER} al grupo docker..."
  $SUDO usermod -aG docker "$CURRENT_USER" || true
  warn "Se agrego al grupo docker. Esta corrida usa sudo para docker si hace falta;"
  warn "logueate de nuevo despues para que docker funcione sin sudo."
fi

# Helper: docker via sudo si el usuario no esta efectivamente en el grupo
DOCKER="docker"
if ! docker ps >/dev/null 2>&1; then
  if $SUDO docker ps >/dev/null 2>&1; then
    DOCKER="$SUDO docker"
    warn "Usando 'sudo docker' para esta corrida (grupo docker requiere relogueo)."
  else
    error "docker no responde. Verifica el daemon: '$SUDO systemctl status docker'"
  fi
fi

# ============================================================================
# 3. Proteccion contra sobreescritura de repo de desarrollo
# ============================================================================
if [ -d "$INSTALL_DIR/.git" ]; then
  EXISTING_REMOTE=$(git -C "$INSTALL_DIR" remote get-url origin 2>/dev/null || echo "")
  DIRTY_FILES=$(git -C "$INSTALL_DIR" status --porcelain 2>/dev/null | wc -l)
  if [ "$DIRTY_FILES" -gt 0 ]; then
    error "${INSTALL_DIR} tiene cambios sin commitear — parece ser un repo de desarrollo. Abortando para no pisarlo. Si querés reinstalar limpio, commiteá o stasheá primero."
  fi
  info "Detectada instalacion previa en ${INSTALL_DIR}. Backup de .env si existe..."
  if [ -f "${INSTALL_DIR}/.env" ]; then
    cp "${INSTALL_DIR}/.env" "/tmp/${APP_NAME}.env.bak.$$"
    BACKUP_ENV="/tmp/${APP_NAME}.env.bak.$$"
    info "Backup de .env en ${BACKUP_ENV}"
  fi
fi

# ============================================================================
# 4. Autenticacion para repo privado (best-effort)
# ============================================================================
# Probar acceso anonimo primero
REPO_NEEDS_AUTH=false
if ! curl -fsI "${REPO_URL%.git}" >/dev/null 2>&1; then
  REPO_NEEDS_AUTH=true
fi

if [ "$REPO_NEEDS_AUTH" = "true" ]; then
  info "Repo parece privado o requiere auth. Configurando GitHub CLI..."
  ensure_cmd gh gh

  if ! gh auth status >/dev/null 2>&1; then
    if [ -n "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]; then
      info "Usando GH_TOKEN/GITHUB_TOKEN del entorno..."
      echo "${GH_TOKEN:-$GITHUB_TOKEN}" | gh auth login --with-token \
        || error "Login con token fallido. Verifica que el token tenga scope 'repo'."
    elif [ -n "$TTY" ]; then
      info "Necesito autenticar GitHub para clonar el repo privado."
      gh auth login --hostname github.com --git-protocol https < "$TTY" \
        || error "Login de GitHub fallido."
    else
      error "Repo privado sin auth disponible. Pasa GH_TOKEN=ghp_... o corre 'gh auth login' antes."
    fi
  fi
  gh auth setup-git >/dev/null 2>&1 || true
  ok "GitHub autenticado"
fi

# ============================================================================
# 5. Clonar / actualizar repositorio
# ============================================================================
if [ -d "$INSTALL_DIR/.git" ]; then
  info "Bajando instalacion previa (docker compose down)..."
  ( cd "$INSTALL_DIR" && $DOCKER compose down 2>/dev/null || true )

  info "Actualizando repo en ${INSTALL_DIR}..."
  git -C "$INSTALL_DIR" fetch origin "$GIT_BRANCH" --depth=1 || error "git fetch fallido."
  git -C "$INSTALL_DIR" reset --hard "origin/${GIT_BRANCH}" || error "git reset fallido."
else
  info "Clonando ${REPO_URL} (rama ${GIT_BRANCH})..."
  git clone --branch "$GIT_BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR" \
    || error "git clone fallido. Verifica REPO_URL y permisos."
fi
ok "Repo presente en ${INSTALL_DIR}"

# Restaurar .env si habia backup
if [ -n "${BACKUP_ENV:-}" ] && [ -f "$BACKUP_ENV" ]; then
  mv "$BACKUP_ENV" "${INSTALL_DIR}/.env"
  chmod 600 "${INSTALL_DIR}/.env"
  ok ".env restaurado desde backup"
  # Releer valores del .env para reusarlos en el resto del flujo
  set -a; . "${INSTALL_DIR}/.env" 2>/dev/null || true; set +a
fi

# ============================================================================
# 6. Descubrir local-llms-router (servicio externo compartido)
# ============================================================================
info "Buscando container local-llms-router..."

LLMS_CONTAINER=""
if [ -z "$LLM_ROUTER_URL" ]; then
  # Buscar containers que parezcan local-llms-router
  LLMS_CONTAINER=$($DOCKER ps --format '{{.Names}}' | grep -iE 'local-llms-router|local-llms|llms-router' | head -1 || echo "")

  if [ -n "$LLMS_CONTAINER" ]; then
    # Sacar el puerto publicado (busca 3210/tcp por convencion del proyecto)
    LLMS_PORT=$($DOCKER port "$LLMS_CONTAINER" 2>/dev/null | grep -oE '[0-9]+/tcp -> 0\.0\.0\.0:[0-9]+' | head -1 | grep -oE '[0-9]+$' || echo "3210")
    info "Container '${LLMS_CONTAINER}' detectado (puerto host: ${LLMS_PORT})."
    LLM_ROUTER_URL_DEFAULT="http://host.docker.internal:${LLMS_PORT}"
  elif (exec 3<>/dev/tcp/127.0.0.1/3210) 2>/dev/null; then
    info "Puerto 3210 escuchando en el host — asumo local-llms-router en host."
    LLM_ROUTER_URL_DEFAULT="http://host.docker.internal:3210"
  else
    warn "No encontre local-llms-router corriendo. Usa el default y ajusta luego si hace falta."
    LLM_ROUTER_URL_DEFAULT="http://host.docker.internal:3210"
  fi

  prompt LLM_ROUTER_URL "URL del local-llms-router" "$LLM_ROUTER_URL_DEFAULT"
fi
ok "LLM_ROUTER_URL=${LLM_ROUTER_URL}"

# ============================================================================
# 7. Preguntar / generar secretos
# ============================================================================
echo ""
info "Configurando secretos del .env..."

# Bearer token del LLM router — secreto, obligatorio
if [ -z "$LLM_ROUTER_BEARER_TOKEN" ]; then
  prompt_secret LLM_ROUTER_BEARER_TOKEN "Bearer token del local-llms-router (en el VPS de Sanchez Repuestos)"
  [ -z "$LLM_ROUTER_BEARER_TOKEN" ] && error "LLM_ROUTER_BEARER_TOKEN no puede estar vacio."
fi
ok "LLM_ROUTER_BEARER_TOKEN recibido"

# API keys — sin esto, /search devuelve 401 a todos
if [ -z "$API_KEYS" ]; then
  GENERATED_KEY="$(gen_secret)"
  info "No me pasaste API_KEYS. Sin al menos 1 key, /search devuelve 401 a todo el mundo."
  prompt API_KEYS "API keys (CSV) para autenticar consumidores" "$GENERATED_KEY"
fi
ok "API_KEYS configurado ($(echo "$API_KEYS" | tr ',' '\n' | wc -l) key(s))"

# Sentry: optional
if [ -z "$SENTRY_DSN" ] && [ -n "$TTY" ]; then
  prompt SENTRY_DSN "Sentry DSN (Enter para skip — Sentry off por default)" ""
fi

# ============================================================================
# 8. Escribir .env con permisos 600
# ============================================================================
info "Escribiendo .env..."
cat > "${INSTALL_DIR}/.env" <<EOF
# Generado por install.sh el $(date -u +%Y-%m-%dT%H:%M:%SZ).
# Para regenerar, corre el instalador con override de variables:
#   LLM_ROUTER_BEARER_TOKEN=... bash install.sh

# ── Phase 2 — MVP ──
LLM_ROUTER_BEARER_TOKEN=${LLM_ROUTER_BEARER_TOKEN}
LLM_ROUTER_URL=${LLM_ROUTER_URL}
LLM_MODEL=${LLM_MODEL}

# ── Phase 3 — Robustness ──
API_KEYS=${API_KEYS}
API_RATE_PER_MINUTE=${API_RATE_PER_MINUTE}
API_RATE_PER_DAY=${API_RATE_PER_DAY}

# ── Phase 3 — Sentry (off por default) ──
SENTRY_DSN=${SENTRY_DSN}

# ── Deploy override ──
HOST_PORT=${HOST_PORT}
EOF
chmod 600 "${INSTALL_DIR}/.env"
ok ".env escrito con permisos 600"

# ============================================================================
# 9. Crear data/ y cache.db (bind-mount sqlite)
# ============================================================================
info "Preparando bind-mount sqlite..."
mkdir -p "${INSTALL_DIR}/data"
touch "${INSTALL_DIR}/data/cache.db"
# Permisos del usuario que corre docker — el container monta el archivo
chmod 644 "${INSTALL_DIR}/data/cache.db"
ok "data/cache.db listo"

# ============================================================================
# 10. Build + force-recreate
# ============================================================================
cd "$INSTALL_DIR"

info "Build de la imagen (cloakhq/cloakbrowser:0.3.31 base — la primera vez tarda 5-25 min)..."
$DOCKER compose build || error "docker compose build fallido."
ok "Imagen construida"

info "Levantando container con force-recreate..."
HOST_PORT="${HOST_PORT}" $DOCKER compose up -d --force-recreate || error "docker compose up fallido."
ok "Container levantado"

# ============================================================================
# 11. Health check sobre /health
# ============================================================================
info "Esperando que /health responda..."
RETRIES=0
MAX_RETRIES=30
HEALTH_OK=false
while [ $RETRIES -lt $MAX_RETRIES ]; do
  if curl -fs "http://localhost:${HOST_PORT}/health" >/dev/null 2>&1; then
    HEALTH_OK=true
    break
  fi
  RETRIES=$((RETRIES + 1))
  sleep 2
done

if [ "$HEALTH_OK" = "true" ]; then
  HEALTH_BODY="$(curl -s "http://localhost:${HOST_PORT}/health")"
  ok "/health responde: ${HEALTH_BODY}"
else
  warn "/health no respondio en $((MAX_RETRIES * 2))s. Mostrando logs:"
  $DOCKER compose logs --tail 50 || true
  error "Health check fallido. Revisa logs arriba o corre 'docker compose logs -f' en ${INSTALL_DIR}."
fi

# ============================================================================
# 12. Resultado final
# ============================================================================
TAILSCALE_IP="$(tailscale ip -4 2>/dev/null | head -1 || echo "<IP-del-VPS>")"
FIRST_API_KEY="$(echo "$API_KEYS" | cut -d, -f1)"

echo ""
echo "=========================================="
echo "  ✓ artiscrapper INSTALADO"
echo "=========================================="
echo ""
echo "Directorio:    ${INSTALL_DIR}"
echo "Puerto:        ${HOST_PORT}"
echo "Health:        http://localhost:${HOST_PORT}/health"
echo "Acceso VPN:    http://${TAILSCALE_IP}:${HOST_PORT}/"
echo ""
echo "API key (primera):"
echo "  ${FIRST_API_KEY}"
echo ""
echo "Smoke test:"
echo "  curl -X POST http://localhost:${HOST_PORT}/search \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -H \"X-API-Key: ${FIRST_API_KEY}\" \\"
echo "    -d '{\"query\": \"filtro aceite ford focus\"}'"
echo ""
echo "Comandos utiles (correr desde ${INSTALL_DIR}):"
echo "  docker compose logs -f                # logs en vivo"
echo "  docker compose restart                # reiniciar"
echo "  docker compose down                   # detener"
echo "  docker compose ps                     # estado"
echo "  curl http://localhost:${HOST_PORT}/metrics   # Prometheus metrics"
echo ""
echo "Para actualizar a la version mas nueva:"
echo "  bash ${INSTALL_DIR}/install.sh"
echo ""
echo "Doc completa: ${INSTALL_DIR}/DEPLOY.md"
echo "=========================================="

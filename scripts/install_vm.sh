#!/usr/bin/env bash
# =====================================================================
# Instalador único para la VM de SuperSalud
# Corre como root o con sudo. Idempotente — re-ejecutable sin daño.
#
# Uso:
#   sudo bash scripts/install_vm.sh
# =====================================================================

set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/informe-regional}"
REPO_URL="${REPO_URL:-https://github.com/NavinetGroup/dashboard-salud.git}"
RUN_USER="${RUN_USER:-navinet-ops}"

log() { echo "  → $*"; }
ok()  { echo "  ✓ $*"; }
err() { echo "  ✗ $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || err "Este script debe correr como root (sudo bash $0)"

echo "============================================="
echo "  Instalador — Informe Regional de Salud"
echo "============================================="
echo

# ---------------------------------------------------------------------
log "1/8 Verificando OS"
# ---------------------------------------------------------------------
[ -f /etc/os-release ] && . /etc/os-release || err "/etc/os-release no encontrado"
case "${ID:-}" in
    ubuntu|debian) ok "OS detectado: $PRETTY_NAME" ;;
    *) err "OS no soportado: ${ID:-desconocido} (se requiere Ubuntu/Debian)" ;;
esac

# ---------------------------------------------------------------------
log "2/8 Actualizando paquetes del sistema"
# ---------------------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    curl ca-certificates git \
    python3.12 python3.12-venv python3-pip \
    cron mailutils \
    > /dev/null
ok "Paquetes base instalados"

# ---------------------------------------------------------------------
log "3/8 Instalando Docker si falta"
# ---------------------------------------------------------------------
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh -s -- > /dev/null
    ok "Docker engine instalado"
else
    ok "Docker ya presente ($(docker --version))"
fi
systemctl enable --now docker > /dev/null
ok "Docker habilitado en boot"

# ---------------------------------------------------------------------
log "4/8 Instalando Google Chrome (para scrapers Selenium)"
# ---------------------------------------------------------------------
if ! command -v google-chrome &>/dev/null; then
    curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | \
        gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list
    apt-get update -qq
    apt-get install -y -qq google-chrome-stable > /dev/null
    ok "Chrome instalado ($(google-chrome --version))"
else
    ok "Chrome ya presente ($(google-chrome --version))"
fi

# ---------------------------------------------------------------------
log "5/8 Creando usuario de operaciones ($RUN_USER)"
# ---------------------------------------------------------------------
if ! id -u "$RUN_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$RUN_USER"
    ok "Usuario $RUN_USER creado"
else
    ok "Usuario $RUN_USER ya existe"
fi
usermod -aG docker "$RUN_USER"
ok "$RUN_USER agregado al grupo docker"

# ---------------------------------------------------------------------
log "6/8 Clonando repositorio en $PROJECT_DIR"
# ---------------------------------------------------------------------
if [ -d "$PROJECT_DIR/.git" ]; then
    cd "$PROJECT_DIR"
    sudo -u "$RUN_USER" git pull --ff-only
    ok "Repo actualizado"
else
    mkdir -p "$(dirname "$PROJECT_DIR")"
    git clone "$REPO_URL" "$PROJECT_DIR"
    chown -R "$RUN_USER:$RUN_USER" "$PROJECT_DIR"
    ok "Repo clonado"
fi

# ---------------------------------------------------------------------
log "7/8 Configurando venv Python para scrapers"
# ---------------------------------------------------------------------
sudo -u "$RUN_USER" bash <<EOF
cd "$PROJECT_DIR"
if [ ! -d .venv ]; then
    python3.12 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements_full.txt
EOF
ok "Venv Python listo (con scrapers completos)"

# ---------------------------------------------------------------------
log "8/8 Configurando cron mensual"
# ---------------------------------------------------------------------
CRON_LINE_MONTHLY="0 6 5 * * cd $PROJECT_DIR && bash scripts/run_monthly_pipeline.sh >> $PROJECT_DIR/logs/cron_monthly.log 2>&1"
CRON_LINE_ANNUAL="0 6 15 7 * cd $PROJECT_DIR && bash scripts/run_monthly_pipeline.sh --annual >> $PROJECT_DIR/logs/cron_annual.log 2>&1"

mkdir -p "$PROJECT_DIR/logs"
chown -R "$RUN_USER:$RUN_USER" "$PROJECT_DIR/logs"

(crontab -u "$RUN_USER" -l 2>/dev/null | grep -v "scripts/run_monthly_pipeline.sh"; \
 echo "$CRON_LINE_MONTHLY"; \
 echo "$CRON_LINE_ANNUAL") | crontab -u "$RUN_USER" -

ok "Cron configurado:"
echo "      • Día 5 de cada mes 06:00 → pipeline mensual"
echo "      • 15 de julio 06:00       → pipeline anual (demografía)"

# ---------------------------------------------------------------------
echo
echo "============================================="
echo "  ✓ INSTALACIÓN COMPLETA"
echo "============================================="
echo
echo "Próximos pasos:"
echo "  1. cd $PROJECT_DIR"
echo "  2. cp .env.example .env  &&  vim .env       # config hostname, TLS, notificaciones"
echo "  3. docker compose -f docker-compose.prod.yml up -d"
echo "  4. Verificar:  curl -k https://localhost/_stcore/health"
echo
echo "Logs del cron:    $PROJECT_DIR/logs/cron_monthly.log"
echo "Logs Docker:      docker logs informe-dashboard"
echo

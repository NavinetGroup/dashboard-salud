#!/usr/bin/env bash
# =====================================================================
# Instalador único para la VM de SuperSalud
# Corre como root o con sudo. Idempotente — re-ejecutable sin daño.
#
# Uso:
#   sudo bash scripts/install_vm.sh
#
# Modelo de permisos:
#   - $RUN_USER (navinet-ops) es dueño del repo y corre el pipeline por cron.
#     Ese pipeline ejecuta Chrome contra sitios externos, así que NO pertenece
#     al grupo docker (equivale a root). Para reiniciar el dashboard tiene una
#     única regla sudo hacia /usr/local/sbin/informe-restart-dashboard.
#   - Los administradores manejan los contenedores con sudo docker ...
# =====================================================================

set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/informe-regional}"
REPO_URL="${REPO_URL:-https://github.com/NavinetGroup/dashboard-salud.git}"
RUN_USER="${RUN_USER:-navinet-ops}"
RESTART_HELPER=/usr/local/sbin/informe-restart-dashboard

log() { echo "  → $*"; }
ok()  { echo "  ✓ $*"; }
err() { echo "  ✗ $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || err "Este script debe correr como root (sudo bash $0)"

echo "============================================="
echo "  Instalador — Informe Regional de Salud"
echo "============================================="
echo

# ---------------------------------------------------------------------
log "1/9 Verificando OS"
# ---------------------------------------------------------------------
[ -f /etc/os-release ] && . /etc/os-release || err "/etc/os-release no encontrado"
# python3.12 viene en los repos de Ubuntu 24.04; 22.04 no lo trae.
if [ "${ID:-}" != "ubuntu" ] || [ "${VERSION_ID%%.*}" -lt 24 ]; then
    err "Se requiere Ubuntu Server 24.04 LTS o superior (detectado: ${PRETTY_NAME:-desconocido})"
fi
ok "OS detectado: $PRETTY_NAME"

# ---------------------------------------------------------------------
log "2/9 Actualizando paquetes del sistema"
# ---------------------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    curl ca-certificates gnupg git \
    python3.12 python3.12-venv python3-pip \
    cron mailutils \
    > /dev/null
ok "Paquetes base instalados"

# ---------------------------------------------------------------------
log "3/9 Instalando Docker desde el repositorio oficial firmado"
# ---------------------------------------------------------------------
if ! command -v docker &>/dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin > /dev/null
    ok "Docker engine instalado ($(docker --version))"
else
    ok "Docker ya presente ($(docker --version))"
fi
systemctl enable --now docker > /dev/null
ok "Docker habilitado en boot"

# ---------------------------------------------------------------------
log "4/9 Instalando Google Chrome (para scrapers Selenium)"
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
log "5/9 Creando usuario de operaciones ($RUN_USER)"
# ---------------------------------------------------------------------
if ! id -u "$RUN_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$RUN_USER"
    ok "Usuario $RUN_USER creado"
else
    ok "Usuario $RUN_USER ya existe"
fi
if id -nG "$RUN_USER" | tr ' ' '\n' | grep -qx docker; then
    gpasswd -d "$RUN_USER" docker > /dev/null
    ok "$RUN_USER retirado del grupo docker (instalaciones anteriores)"
fi

# ---------------------------------------------------------------------
log "6/9 Clonando repositorio en $PROJECT_DIR"
# ---------------------------------------------------------------------
if [ -d "$PROJECT_DIR/.git" ]; then
    sudo -u "$RUN_USER" git -C "$PROJECT_DIR" pull --ff-only
    ok "Repo actualizado"
else
    mkdir -p "$(dirname "$PROJECT_DIR")"
    git clone "$REPO_URL" "$PROJECT_DIR"
    chown -R "$RUN_USER:$RUN_USER" "$PROJECT_DIR"
    ok "Repo clonado"
fi
# data/ se monta (solo lectura) en el contenedor: debe ser legible por todos
sudo -u "$RUN_USER" mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/logs"
chmod 755 "$PROJECT_DIR/data"

# ---------------------------------------------------------------------
log "7/9 Configurando venv Python para scrapers"
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
log "8/9 Permiso acotado para reiniciar el dashboard"
# ---------------------------------------------------------------------
cat > "$RESTART_HELPER" <<EOF
#!/usr/bin/env bash
# Reinicia el contenedor del dashboard y espera a que esté healthy (máx. 5 min).
# Único comando docker que $RUN_USER puede ejecutar (vía sudoers).
set -euo pipefail
docker compose -f "$PROJECT_DIR/docker-compose.prod.yml" --project-directory "$PROJECT_DIR" restart dashboard
for _ in \$(seq 1 60); do
    [ "\$(docker inspect --format='{{.State.Health.Status}}' informe-dashboard 2>/dev/null)" = healthy ] && exit 0
    sleep 5
done
echo "dashboard no quedó healthy en 5 minutos" >&2
exit 1
EOF
chown root:root "$RESTART_HELPER"
chmod 0755 "$RESTART_HELPER"
echo "$RUN_USER ALL=(root) NOPASSWD: $RESTART_HELPER" > /etc/sudoers.d/informe-regional
chmod 0440 /etc/sudoers.d/informe-regional
visudo -cf /etc/sudoers.d/informe-regional > /dev/null || err "sudoers inválido"
ok "$RUN_USER puede ejecutar: sudo $RESTART_HELPER"

# ---------------------------------------------------------------------
log "9/9 Configurando cron mensual"
# ---------------------------------------------------------------------
CRON_LINE_MONTHLY="0 6 5 * * cd $PROJECT_DIR && bash scripts/run_monthly_pipeline.sh >> $PROJECT_DIR/logs/cron_monthly.log 2>&1"
CRON_LINE_ANNUAL="0 6 15 7 * cd $PROJECT_DIR && bash scripts/run_monthly_pipeline.sh --annual >> $PROJECT_DIR/logs/cron_annual.log 2>&1"

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
echo "  2. sudo -u $RUN_USER cp .env.example .env && sudo -u $RUN_USER nano .env"
echo "  3. Primera carga de datos (~25 min; genera data/informe_regional.duckdb):"
echo "       sudo -u $RUN_USER .venv/bin/python pipeline/runner.py --run-now"
echo "  4. Validar la config de Caddy:"
echo "       sudo docker compose -f docker-compose.prod.yml run --rm caddy caddy validate --config /etc/caddy/Caddyfile"
echo "  5. sudo docker compose -f docker-compose.prod.yml up -d --build"
echo "  6. Verificar:  curl -k https://localhost/_stcore/health"
echo
echo "Logs del cron:    $PROJECT_DIR/logs/cron_monthly.log"
echo "Logs Docker:      sudo docker logs informe-dashboard"
echo

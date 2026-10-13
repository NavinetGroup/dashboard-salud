#!/usr/bin/env bash
# =====================================================================
# Pipeline mensual — ejecuta scrapers, transforma datos, reinicia dashboard
#
# Llamado por cron el día 5 de cada mes @ 06:00.
# Uso manual:  bash scripts/run_monthly_pipeline.sh [--annual]
#
# Notifica SIEMPRE el resultado (OK / CON FALLOS / FAILED). Códigos de salida:
#   0  todo OK
#   1  algún paso falló (ver notificación y log)
# =====================================================================

set -uo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/informe-regional}"
cd "$PROJECT_DIR" || { echo "ERROR: no se pudo cambiar a $PROJECT_DIR"; exit 1; }

# Cargar .env si existe
[ -f .env ] && set -a && . ./.env && set +a

MODE="${1:---monthly}"
START_TS=$(date '+%Y-%m-%d %H:%M:%S')
START_EPOCH=$(date +%s)
LOG_FILE="logs/pipeline_$(date +%Y%m%d_%H%M%S).log"
PYTHON=".venv/bin/python"

mkdir -p logs data

# ---------------------------------------------------------------------
# Lock: two overlapping runs would fight over the DuckDB file lock.
# ---------------------------------------------------------------------
exec 9>"data/.pipeline.lock"
if ! flock -n 9; then
    echo "Otra ejecución del pipeline sigue en curso; saliendo." | tee -a "$LOG_FILE"
    exit 1
fi

echo "============================================="
echo "  Pipeline $MODE — $START_TS"
echo "  Log: $LOG_FILE"
echo "============================================="

# ---------------------------------------------------------------------
# Helper: send notification. Failures to notify are logged, never hidden.
# ---------------------------------------------------------------------
notify() {
    local subject="$1"
    local body="$2"

    if [ -n "${NOTIFY_WEBHOOK_URL:-}" ]; then
        # Build the JSON with a real serializer: the body has newlines and may
        # contain quotes from error messages.
        local payload
        payload=$(SUBJECT="$subject" BODY="$body" python3 -c \
            'import json, os; print(json.dumps({"text": os.environ["SUBJECT"] + "\n\n" + os.environ["BODY"]}))')
        if ! curl -fsS -X POST -H "Content-Type: application/json" \
                --data-binary "$payload" "$NOTIFY_WEBHOOK_URL" >/dev/null 2>>"$LOG_FILE"; then
            echo "⚠ No se pudo enviar la notificación al webhook" | tee -a "$LOG_FILE"
        fi
    elif [ -n "${NOTIFY_EMAIL_TO:-}" ] && command -v mail >/dev/null; then
        if ! printf '%s\n' "$body" | mail -s "$subject" "$NOTIFY_EMAIL_TO" 2>>"$LOG_FILE"; then
            echo "⚠ No se pudo enviar la notificación por correo" | tee -a "$LOG_FILE"
        fi
    else
        echo "⚠ Sin canal de notificación configurado (NOTIFY_WEBHOOK_URL / NOTIFY_EMAIL_TO)" | tee -a "$LOG_FILE"
    fi
}

fail() {
    local step="$1"
    local detail="${2:-}"
    echo "✗ Pipeline FAILED en: $step" | tee -a "$LOG_FILE"
    notify "[Informe Regional] Pipeline FAILED — $step" \
           "El pipeline $MODE falló en el paso: $step.
$detail
Inicio: $START_TS
Log en la VM: $PROJECT_DIR/$LOG_FILE"
    exit 1
}

# Run a command, tee its output to the log, return the command's own exit code.
run_logged() {
    "$@" 2>&1 | tee -a "$LOG_FILE"
    return "${PIPESTATUS[0]}"
}

# ---------------------------------------------------------------------
# 1. Pull latest code
# ---------------------------------------------------------------------
echo "→ git pull..." | tee -a "$LOG_FILE"
run_logged git pull --ff-only || fail "git pull"

# ---------------------------------------------------------------------
# 2. Sync venv (in case requirements_full.txt changed)
# ---------------------------------------------------------------------
echo "→ Sincronizando venv..." | tee -a "$LOG_FILE"
run_logged .venv/bin/pip install -q -r requirements_full.txt || fail "pip install"

# ---------------------------------------------------------------------
# 3. Run scrapers + transform
#    runner.py exit codes: 0 OK · 1 some scrapers failed (DB rebuilt with the
#    rest) · 2 transform failed (DB not rebuilt)
# ---------------------------------------------------------------------
echo "→ Ejecutando pipeline $MODE..." | tee -a "$LOG_FILE"
if [ "$MODE" = "--annual" ]; then
    run_logged "$PYTHON" pipeline/runner.py --annual
else
    run_logged "$PYTHON" pipeline/runner.py --monthly
fi
PIPELINE_RC=$?

# Lines from the runner's end-of-run summary that name failed steps
FAILED_STEPS=$(grep -E 'FALLO|Falló|Error en' "$LOG_FILE" | sed 's/^[0-9-]* [0-9:]* //' | tail -n 20)

if [ "$PIPELINE_RC" -ge 2 ]; then
    fail "pipeline (exit $PIPELINE_RC)" "La base de datos NO se reconstruyó.

$FAILED_STEPS"
fi

# ---------------------------------------------------------------------
# 4. Restart dashboard so it picks up the fresh DB
# ---------------------------------------------------------------------
echo "→ Reiniciando dashboard..." | tee -a "$LOG_FILE"
run_logged docker compose -f docker-compose.prod.yml restart dashboard || fail "docker compose restart"

echo "→ Esperando healthcheck..." | tee -a "$LOG_FILE"
HEALTH="unknown"
for _ in {1..60}; do
    HEALTH=$(docker inspect --format='{{.State.Health.Status}}' informe-dashboard 2>/dev/null || echo "unknown")
    if [ "$HEALTH" = "healthy" ]; then
        echo "  ✓ Dashboard saludable" | tee -a "$LOG_FILE"
        break
    fi
    sleep 5
done
[ "$HEALTH" = "healthy" ] || fail "healthcheck del dashboard" "Estado tras 5 min: $HEALTH"

# ---------------------------------------------------------------------
# 5. Summarize and notify
# ---------------------------------------------------------------------
END_TS=$(date '+%Y-%m-%d %H:%M:%S')
DURATION=$(( $(date +%s) - START_EPOCH ))

# Pull DB row counts for the summary
SUMMARY=$("$PYTHON" <<'PY'
import duckdb, os
db = os.environ.get('INFORME_DB_PATH', 'data/informe_regional.duckdb')
c = duckdb.connect(db, read_only=True)
tables = ['reps_prestadores', 'irca', 'afiliacion', 'supersalud_ips_intervenidas',
          'ins_mortalidad_materna', 'ins_dengue', 'demografico_edad_sexo']
for t in tables:
    try:
        n = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        print(f'  {t:30s} {n:>10,} filas')
    except Exception as e:
        print(f'  {t:30s} ERROR: {e}')
# Latest data-quality run: list what did not pass (warnings included)
try:
    rows = c.execute("""
        SELECT nivel, control, detalle FROM _calidad_resultados
        WHERE ejecutado_en = (SELECT MAX(ejecutado_en) FROM _calidad_resultados) AND NOT ok
        ORDER BY nivel, control""").fetchall()
    print('')
    print('Calidad de datos:' if rows else 'Calidad de datos: todos los controles OK')
    for nivel, control, detalle in rows:
        print(f'  [{nivel.upper()}] {control}: {detalle}')
except Exception as e:
    print(f'Calidad de datos: no disponible ({e})')
c.close()
PY
)

if [ "$PIPELINE_RC" -eq 0 ]; then
    STATUS="OK"
    HEADLINE="Pipeline completado correctamente."
else
    STATUS="CON FALLOS"
    HEADLINE="Pipeline completado, pero algunas fuentes NO se actualizaron:
$FAILED_STEPS"
fi

echo "" | tee -a "$LOG_FILE"
echo "Pipeline $STATUS en ${DURATION}s" | tee -a "$LOG_FILE"
echo "$SUMMARY" | tee -a "$LOG_FILE"

notify "[Informe Regional] Pipeline $STATUS ($MODE)" \
       "$HEADLINE

Inicio:    $START_TS
Fin:       $END_TS
Duración:  ${DURATION}s
Modo:      $MODE

Resumen de tablas:
$SUMMARY"

echo "Log completo: $LOG_FILE"
[ "$PIPELINE_RC" -eq 0 ] || exit 1

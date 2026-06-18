#!/usr/bin/env bash
# =====================================================================
# Pipeline mensual — ejecuta scrapers, transforma datos, reinicia dashboard
#
# Llamado por cron el día 5 de cada mes @ 06:00.
# Uso manual:  bash scripts/run_monthly_pipeline.sh [--annual]
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

mkdir -p logs data

echo "============================================="
echo "  Pipeline $MODE — $START_TS"
echo "  Log: $LOG_FILE"
echo "============================================="

# ---------------------------------------------------------------------
# Helper: send notification
# ---------------------------------------------------------------------
notify() {
    local subject="$1"
    local body="$2"

    if [ -n "${NOTIFY_WEBHOOK_URL:-}" ]; then
        curl -s -X POST -H "Content-Type: application/json" \
            -d "{\"text\":\"$subject\n\n$body\"}" \
            "$NOTIFY_WEBHOOK_URL" >/dev/null || true
    elif [ -n "${NOTIFY_EMAIL_TO:-}" ] && command -v mail >/dev/null; then
        echo -e "$body" | mail -s "$subject" "$NOTIFY_EMAIL_TO" || true
    fi
}

# ---------------------------------------------------------------------
# 1. Pull latest code
# ---------------------------------------------------------------------
echo "→ git pull..." | tee -a "$LOG_FILE"
git pull --ff-only 2>&1 | tee -a "$LOG_FILE"

# ---------------------------------------------------------------------
# 2. Sync venv (in case requirements_full.txt changed)
# ---------------------------------------------------------------------
echo "→ Sincronizando venv..." | tee -a "$LOG_FILE"
.venv/bin/pip install -q -r requirements_full.txt 2>&1 | tee -a "$LOG_FILE"

# ---------------------------------------------------------------------
# 3. Run scrapers + transform
# ---------------------------------------------------------------------
echo "→ Ejecutando pipeline $MODE..." | tee -a "$LOG_FILE"
if [ "$MODE" = "--annual" ]; then
    .venv/bin/python pipeline/runner.py --annual 2>&1 | tee -a "$LOG_FILE"
else
    .venv/bin/python pipeline/runner.py --monthly 2>&1 | tee -a "$LOG_FILE"
fi
PIPELINE_RC=$?

if [ $PIPELINE_RC -ne 0 ]; then
    echo "✗ Pipeline FAILED (exit $PIPELINE_RC)" | tee -a "$LOG_FILE"
    notify "[Informe Regional] Pipeline FAILED" \
           "El pipeline mensual falló con código $PIPELINE_RC. Ver $LOG_FILE en la VM."
    exit $PIPELINE_RC
fi

# ---------------------------------------------------------------------
# 4. Restart dashboard so it picks up the fresh DB
# ---------------------------------------------------------------------
echo "→ Reiniciando dashboard..." | tee -a "$LOG_FILE"
docker compose -f docker-compose.prod.yml restart dashboard 2>&1 | tee -a "$LOG_FILE"

# Wait for healthcheck
echo "→ Esperando healthcheck..." | tee -a "$LOG_FILE"
for i in {1..60}; do
    HEALTH=$(docker inspect --format='{{.State.Health.Status}}' informe-dashboard 2>/dev/null || echo "unknown")
    if [ "$HEALTH" = "healthy" ]; then
        echo "  ✓ Dashboard saludable" | tee -a "$LOG_FILE"
        break
    fi
    sleep 5
done

# ---------------------------------------------------------------------
# 5. Summarize and notify
# ---------------------------------------------------------------------
END_TS=$(date '+%Y-%m-%d %H:%M:%S')
DURATION=$(( $(date +%s) - START_EPOCH ))

# Pull DB row counts for the summary
SUMMARY=$(.venv/bin/python <<'PY'
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
c.close()
PY
)

echo "" | tee -a "$LOG_FILE"
echo "✓ Pipeline completado en ${DURATION}s" | tee -a "$LOG_FILE"
echo "$SUMMARY" | tee -a "$LOG_FILE"

notify "[Informe Regional] Pipeline OK ($MODE)" \
       "Pipeline completado correctamente.

Inicio:    $START_TS
Fin:       $END_TS
Duración:  ${DURATION}s
Modo:      $MODE

Resumen de tablas:
$SUMMARY"

echo "Log completo: $LOG_FILE"

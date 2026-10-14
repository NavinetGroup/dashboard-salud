# Mantenimiento — Informe Regional de Salud

Runbook operacional para mantener el dashboard actualizado. Está pensado para una sola persona ejecutando ~30 min al mes.

---

## 🗓️ Cadencia

| Frecuencia | Acción |
|---|---|
| **5 de cada mes** | Pipeline mensual (scrapers + transform) |
| **15 de julio** | Pipeline anual (refresca proyecciones DANE) |
| **Ad-hoc** | Re-publicar `informe_regional.duckdb` al GitHub Release cuando los datos cambien |

---

## 🤖 Lo que es automático

Estos scrapers descargan datos sin intervención humana:

| Fuente | Endpoint |
|---|---|
| Demografico DANE | URLs públicas de `dane.gov.co` |
| REPS (6 endpoints) | Login "invitado" automático en `prestadores.minsalud.gov.co` |
| Afiliación | ZIPs mensuales en `minsalud.gov.co` |
| SuperSalud IPS/EPS | Excel directo en `docs.supersalud.gov.co` |
| BDUA (EPS por territorio, pirámide de afiliados) | API de datos.gov.co (`d7a5-cnra`, `tq4m-hmg2`). Solo publica el mes vigente: cada corrida archiva su foto en `data/parquet/bdua_*_YYYY_MM.parquet` (no borrarlas: son la única serie histórica) |
| INS PDFs (6 indicadores) | URLs públicas del INS. Solo se usan para el año en curso y para la razón de mortalidad materna |
| INS SIVIGILA microdatos (6 eventos, todos los municipios) | Portal SIVIGILA (SharePoint REST). Archivos anuales finales; el año en curso sale ~agosto del siguiente. Los xlsx crudos (hasta 110 MB) quedan en `data/raw/sivigila/` y solo se vuelven a bajar si el INS los modificó |
| INS SIVIGILA año en curso (preliminar) | Tablero público "006 Vigilancia Rutinaria" del INS (API pública de Power BI, sin login). Semanas completas hasta ~2 semanas atrás; se rotula "(preliminar)". Cuando el INS publique los microdatos finales de ese año, reemplazan automáticamente al preliminar. Si el control `frescura_sivigila_preliminar` avisa, revisar que el tablero siga existiendo con ese nombre |
| CUIPO — ejecución presupuestal en salud (Financiamiento 1–7) | CGR en datos.gov.co, trimestral y acumulado en el año. Se baja un archivo por trimestre (`cuipo_salud_AAAAMM.parquet`) y solo se vuelve a bajar si la CGR actualizó los datasets. Si el control `cuipo_codigo_divipola` falla, apareció un municipio con código CGN `923…` nuevo: agregarlo en `_CGN_DIVIPOLA` (`scrapers/cuipo_scraper.py`). Bogotá y Norte de Santander usan su fondo/instituto de salud (`_FONDOS`) |
| Cofinanciación del régimen subsidiado (Financiamiento 8) | Meta: matriz de continuidad del MSPS, página "matriz-continuidad" (se toma la versión más reciente de cada año). Ejecución: "Resultado LMA" de la ADRES, un Excel por mes que se descarga vía `/api/media`. Si cambian los encabezados del Excel, el scraper falla con un mensaje que nombra las columnas no reconocidas (`scrapers/cofinanciacion_scraper.py`) |
| DANE — nacimientos y defunciones fetales (denominador de sífilis congénita) | Cuadros anuales de estadísticas vitales, por municipio de residencia de la madre. Solo se usan años completos, cuando el DANE publica cifras definitivas (~9 meses después). Mientras un año está en curso, se usa el último año completo, prorrateado a las semanas notificadas. Las tablas de 2023 son .xls protegidas y no se cargan (el dashboard no las necesita) |
| SICODIS — asignaciones SGP salud (denominador de los indicadores SGP) | DNP, reporte nacional en Excel sin login. Años cerrados una vez; el año en curso en cada corrida |

Para correr el ciclo completo:

```powershell
cd "c:\dev\Informe regional v2"
.venv\Scripts\python.exe pipeline\runner.py --run-now
```

Toma ~25 minutos. El resultado: parquets nuevos en `data/parquet/` y tablas refrescadas en `data/informe_regional.duckdb`.

---

## 🖐️ Lo que requiere acción humana

### 1. IRCA (calidad del agua INS) — 1 vez al mes

El scraper de SIVICAP es rechazado por anti-bot. Dos opciones:

#### Opción A — Drop manual del CSV (rápido, una vez al mes)

1. Abre https://sivicap.ins.gov.co/SIVICAP/Account/Login en Chrome/Edge normal.
2. Login: `invitado@ins.gov.co` / `123456` + resuelve el reCAPTCHA.
3. Menú: **Reportes → SIVICAP → IRCA mensual por municipio**.
4. Selecciona año/mes y haz clic en **Exportar CSV**.
5. Copia el archivo descargado a `data/raw/irca_manual/`.
6. Corre `python scrapers/irca_scraper.py` y luego `python pipeline/runner.py --transform-only`.
   El scraper guarda el parquet con el último mes que contienen los datos y mueve el CSV a
   `data/raw/irca_manual/procesados/`, para que no se vuelva a cargar el mes siguiente.

Mientras no haya un CSV nuevo, el pipeline mensual intenta SIVICAP y, si el reCAPTCHA lo
bloquea, la notificación llega como **CON FALLOS** indicando `irca_scraper`: es la señal
para hacer esta descarga manual.

#### Opción B — Sesión persistente (más esfuerzo inicial, automático por semanas)

```powershell
.venv\Scripts\python.exe tools\setup_sivicap_session.py
```

Abre una ventana visible de Chrome con credenciales pre-llenadas. Resuelves el reCAPTCHA UNA vez, presionas ENTER en la terminal. Las cookies persisten en `data/chrome_profile_sivicap/`. A partir de ahí, el scraper headless reutiliza la sesión durante 2-4 semanas hasta que el INS la invalide — y entonces vuelves a correr el setup.

### 2. Desnutrición aguda 2026 — sin solución actual

El INS migró la tabla geográfica del PDF a 3 imágenes PNG embebidas. No es extraíble con texto. Los datos 2025 siguen intactos en la DB. Opciones futuras:

- **Google Cloud Vision API** (~$0.02/año) — extracción OCR con buena precisión
- **Solicitud formal al INS** — vía portal de transparencia, respuesta en 10-15 días
- **Aceptar** — datos 2026 nacionales (total país) sí están como texto en el PDF

---

## 📤 Publicar nueva versión del DB

Cuando termines un ciclo de scraping y quieras que el dashboard online vea los datos nuevos:

```powershell
# Sube el DB actualizado al GitHub Release
gh release upload data-v1 data/informe_regional.duckdb --repo NavinetGroup/dashboard-salud --clobber
```

Luego, **abre Hugging Face Space → Settings → "Factory rebuild"** para que el contenedor descargue el DB nuevo. (Un "Restart" simple no basta — conserva el caché.)

---

## 🧪 Verificar antes de publicar

Cada `transform` termina con el paso **calidad** (`pipeline/quality.py`), unos 45 controles automáticos:
llaves duplicadas, % de filas con código de municipio por fuente, población étnica vs. total,
meses de afiliación con totales idénticos (mes re-etiquetado), rangos plausibles de tasas,
frescura de cada fuente y saltos de filas frente a la carga anterior.

- **ERROR** → el paso `calidad` falla, el runner sale con código 1 y la notificación llega como
  **CON FALLOS**. No publicar el DB hasta entenderlo.
- **WARN** → aparece al final de la notificación (p. ej. fuente atrasada). Revisar, no bloquea.

```powershell
# Correr solo los controles sobre el DB actual
.venv\Scripts\python.exe pipeline\quality.py
```

El histórico queda en las tablas `_calidad_resultados` y `_carga_log` del DB.

```powershell
# Levanta el dashboard local
.venv\Scripts\python.exe -m streamlit run dashboard\app.py
# Abre http://localhost:8501 y revisa que las fechas/cifras se vean correctas
```

Si algo se ve raro, mira los logs:
```powershell
ls logs\run_*.log | sort -descending | select -first 1 | %{ Get-Content $_.FullName -Tail 100 }
```

---

## 🔄 Workflow git completo cada actualización

```powershell
git add data/parquet  # opcional, los parquets están en .gitignore por default
git add scrapers/ pipeline/ README.md MANTENIMIENTO.md
git commit -m "Actualización mensual <YYYY-MM>"
git push origin main
gh release upload data-v1 data/informe_regional.duckdb --repo NavinetGroup/dashboard-salud --clobber
# → luego Factory rebuild en HF Space
```

---

## 🆘 Troubleshooting

| Síntoma | Causa probable | Acción |
|---|---|---|
| `SessionNotCreatedException: ChromeDriver only supports Chrome version X` | El driver cacheado está desfasado | Borra `%APPDATA%\undetected_chromedriver\` y re-corre |
| `SIVICAP: login fallido — sigue en la página de login` | Anti-bot rechazó la sesión headless | Usa Opción A (manual) u Opción B (perfil persistente) |
| `INS [<evento>] PE_X_YYYY: no se encontraron tablas válidas` | INS cambió el layout del PDF | Revisar manualmente el PDF; si es desnutrición, ver sección de limitaciones |
| `HTTP 401` en SuperSalud | URL del Excel cambió | Buscar el nuevo nombre vía SharePoint REST API y actualizar `URL_IPS_XLSX`/`URL_EPS_XLSX` en `scrapers/supersalud_scraper.py` |
| HF Space muestra datos viejos | DB en caché | Settings → Factory rebuild |

---

## 📚 Referencias

- Arquitectura técnica completa: [docs/WEBSCRAPING_GUIDE.md](docs/WEBSCRAPING_GUIDE.md)
- Definiciones de indicadores: [docs/INDICADORES_FUENTES.md](docs/INDICADORES_FUENTES.md)
- Contexto histórico inicial: [docs/archive/CONTEXTO_INICIAL_20250101.md](docs/archive/CONTEXTO_INICIAL_20250101.md)
- Mapeo KPIs ↔ fuentes (referencia personal): [docs/reference/informe_regional_kpis_fuentes.xlsx](docs/reference/informe_regional_kpis_fuentes.xlsx)

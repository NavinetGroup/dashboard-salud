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
| INS PDFs (6 indicadores) | URLs públicas del INS |

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
5. Copia el archivo descargado a `data/raw/irca_manual/` (reemplaza el anterior).
6. Borra `data/parquet/irca_YYYY_MM.parquet` del mes actual.
7. Corre `python pipeline/runner.py --transform-only`.

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

- Arquitectura técnica completa: [WEBSCRAPING_GUIDE.md](WEBSCRAPING_GUIDE.md)
- Definiciones de indicadores: [INDICADORES_FUENTES.md](INDICADORES_FUENTES.md)

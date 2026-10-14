# Mantenimiento — Informe Regional de Salud

Guía del **equipo que procesa los datos** (operador). Los usuarios del tablero no hacen nada de esto: su
aplicación se actualiza sola (ver README).

Todo el procesamiento ocurre en este equipo. El resultado es una base pequeña para el visor
(`data/dist/informe_regional_visor.duckdb`, unos 14 MB) que se publica en una release de GitHub; cada
tablero la descarga al abrirse.

---

## Puesta en marcha (una sola vez)

1. Instale Python 3.12 (python.org) y Google Chrome.
2. Doble clic en **`Preparar equipo.bat`**: crea `.venv` e instala `requirements-pipeline.txt`.
3. Para publicar: instale la GitHub CLI (https://cli.github.com) y ejecute `gh auth login` con una cuenta
   con permiso de escritura en el repositorio.
4. Opcional: copie `informe_regional.example.toml` como `informe_regional.toml` para cambiar la carpeta
   de archivos manuales (por ejemplo, a la biblioteca de SharePoint sincronizada con OneDrive).
5. Doble clic en **`Renovar sesion SIVICAP.bat`** (ver IRCA abajo).

---

## Cada mes

| Paso | Cómo |
|---|---|
| 1. IRCA | Si el mes anterior avisó que SIVICAP pidió login: **`Renovar sesion SIVICAP.bat`**, o deje el CSV a mano en la carpeta de manuales (ver abajo) |
| 2. Procesar y publicar | Doble clic en **`Actualizar datos.bat`**: descarga todas las fuentes, controla la calidad, genera la base del visor y pregunta si publicarla |
| 3. Verificar | `.venv\Scripts\python.exe -m streamlit run dashboard\app.py` muestra la base recién construida |

`Actualizar datos.bat` termina con uno de tres resultados (código de salida del runner):

- **0** — todo bien; se ofrece publicar.
- **1** — alguna fuente falló (típicamente IRCA), pero la base se construyó, pasó los controles y se
  puede publicar: los datos de esa fuente quedan del mes anterior.
- **2** — la base nueva **no** se generó (fallo de transformación o de un control de calidad con nivel
  ERROR). El tablero sigue con la versión anterior; revise el registro antes de reintentar.

Una vez al año (después del 15 de julio, cuando el DANE publica proyecciones):
`.venv\Scripts\python.exe -m pipeline.runner --annual`.

---

## Fuentes automáticas

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
| DANE — nacimientos y defunciones fetales (denominador de sífilis congénita) | Cuadros anuales de estadísticas vitales, por municipio de residencia de la madre. Solo se usan años completos, cuando el DANE publica cifras definitivas (~9 meses después). Mientras un año está en curso, se usa el último año completo, prorrateado a las semanas notificadas. Las tablas de 2023 son .xls protegidas y no se cargan (el tablero no las necesita) |
| INS — evaluación del desempeño de la VSP (Salud pública 10 y 11) | Excel trimestral en la biblioteca "Documentos compartidos" del Portal SIVIGILA. Primero sale PRELIMINAR y luego FINAL; el scraper usa el FINAL apenas existe. Datos por departamento y distrito; el resto de municipios muestra el valor de su departamento. Si el INS cambia el nombre de los archivos y el control `frescura_vsp` avisa, revisar el patrón de nombres en `scrapers/ins_vsp_scraper.py` |
| SICODIS — asignaciones SGP salud (denominador de los indicadores SGP) | DNP, reporte nacional en Excel sin login. Años cerrados una vez; el año en curso en cada corrida |

---

## Archivos descargados a mano

Viven en la **carpeta de manuales**: `data/manual/` por defecto, o la que fije `informe_regional.toml`
(`[rutas] manuales`) o la variable `INFORME_MANUAL_DIR`. Más adelante puede apuntar a la biblioteca de
SharePoint sincronizada con OneDrive, sin cambiar código.

| Subcarpeta | Qué dejar ahí | Qué pasa después |
|---|---|---|
| `irca/` | CSV "IRCA mensual por municipio" exportado de SIVICAP | Se carga y se mueve a `irca/procesados/` con la fecha, para no recargarlo |
| `afiliacion/` | ZIP de cifras de afiliación del MSPS, cuando el sitio no lo entrega | Se usa para el mes que indica el nombre del archivo |

### IRCA (SIVICAP)

SIVICAP protege el inicio de sesión con un reCAPTCHA, que debe resolver una persona.

- **Sesión guardada (recomendado):** **`Renovar sesion SIVICAP.bat`** abre Chrome con las credenciales de
  invitado ya escritas; marque "No soy un robot", inicie sesión y presione ENTER en la ventana negra. La
  sesión queda en `data/chrome_profile_sivicap/` y el scraper la reutiliza durante varias semanas.
  Repítalo cuando el pipeline avise que SIVICAP pidió login.
- **CSV a mano:** en https://sivicap.ins.gov.co (usuario invitado) → Reportes → IRCA mensual por
  municipio → Exportar CSV, y guarde el archivo en `irca/` dentro de la carpeta de manuales.

---

## Controles de calidad

Cada construcción termina con el paso **calidad** (`pipeline/quality.py`, unos 90 controles): llaves
duplicadas, cruce de códigos DANE por fuente, rangos plausibles, frescura de cada fuente y saltos de
filas frente a la carga anterior.

- **ERROR** → la base nueva no se publica (código 2).
- **WARN** → se informa al final; revisar, no bloquea.

Para correrlos sobre la base actual: `.venv\Scripts\python.exe -m pipeline.quality`. El histórico queda
en las tablas `_calidad_resultados` y `_carga_log`.

Cada construcción parte de una base vacía y solo conserva de la anterior esas dos tablas de histórico.

---

## Publicación y actualización de los tableros

- `python -m pipeline.exportar` (lo hace el runner) escribe en `data/dist/` la base del visor y
  `manifest.json` (versión, tamaño, SHA-256).
- `python tools\publicar_datos.py` (lo ofrece `Actualizar datos.bat`) crea la release pública
  `datos-<versión>` con esos dos archivos y la marca como la última.
- Cada tablero, al abrirse (y cada 6 horas si queda abierto), lee `releases/latest/download/manifest.json`;
  si la versión es más nueva que la suya, descarga la base, comprueba el SHA-256 y la reemplaza. Sin
  internet sigue con la que tiene.
- **Actualización manual (sin internet):** copie `data/dist/informe_regional_visor.duckdb` a la carpeta
  `app\data\actualizacion\` del tablero del usuario (USB, correo, SharePoint) y que lo vuelva a abrir.

## Versión portable del tablero

`.venv\Scripts\python.exe tools\build_portable.py` genera `dist/InformeRegional/` y
`dist/InformeRegional_<versión>.zip` (unos 110 MB): Python embebido, los 6 paquetes del visor (en las
mismas versiones del entorno probado), el tablero y la base actual. Se entrega el zip; el usuario lo
descomprime y abre **`Abrir Informe Regional.bat`**, que elige un puerto libre y abre el navegador.
Solo hace falta un zip nuevo cuando cambia el **código** del tablero; los datos se actualizan solos.

---

## Cartografía (mapas de Localización)

Los mapas usan `dashboard/colombia_dptos.geojson` y `dashboard/colombia_mpios.geojson`, generados a partir
del Marco Geoestadístico Nacional del DANE (servicio público, sin login). No los actualiza el pipeline.
Cuando el DANE publique un MGN nuevo (por ejemplo, porque se creó un municipio):
`.venv\Scripts\python.exe tools\build_geojson.py --year 2026`.

---

## Problemas frecuentes

| Síntoma | Causa probable | Acción |
|---|---|---|
| `SessionNotCreatedException: ChromeDriver only supports Chrome version X` | El driver cacheado está desfasado | Borre `%APPDATA%\undetected_chromedriver\` y reintente |
| `irca: SIVICAP no entregó datos (probable reCAPTCHA)` | La sesión guardada venció | `Renovar sesion SIVICAP.bat`, o CSV a mano |
| `INS [<evento>] PE_X_YYYY: no se encontraron tablas válidas` | El INS cambió el formato del PDF | Revisar el PDF; el tablero usa SIVIGILA y solo cae al PDF si falta |
| `HTTP 401` en Supersalud | Cambió la URL del Excel | Actualizar `URL_IPS_XLSX` / `URL_EPS_XLSX` en `scrapers/supersalud_scraper.py` |
| `publicar_datos.py`: falta `gh` o permiso | GitHub CLI no instalada o sin sesión | Instalarla y `gh auth login` |
| Un tablero no se actualiza | Sin internet, o GitHub bloqueado en la red | Actualización manual (ver arriba) |

---

## Referencias

- Fuentes por indicador y su investigación: [docs/FUENTES_INVESTIGACION_2026-10-13.md](docs/FUENTES_INVESTIGACION_2026-10-13.md)
- Fórmulas de Financiamiento (pendientes de validación): [docs/FINANCIAMIENTO_FORMULAS.md](docs/FINANCIAMIENTO_FORMULAS.md)
- Plan del diseño FCT: [docs/PLAN_FCT_2026-10.md](docs/PLAN_FCT_2026-10.md)
- Auditoría del código (octubre 2026): [docs/AUDITORIA_2026-10-13.md](docs/AUDITORIA_2026-10-13.md)

# Manual técnico — Informe Regional de Salud

Guía para quien **opera, mantiene, modifica o reproduce** el sistema: el equipo que procesa y
publica los datos cada mes y quien deba adaptar el código a una fuente nueva, a un cambio de formato
o a otro escenario (otra entidad, otro conjunto de indicadores, otro territorio).

Describe la arquitectura, cada fuente de datos y su scraper, el procesamiento (transformación,
métricas, controles de calidad, exportación), el tablero, la distribución y la actualización
automática, y los procedimientos de operación y extensión.

El manual del usuario final está en `docs/MANUAL_USUARIO.md`.

---

## 1. Visión general

### 1.1 Qué hace el sistema

1. **Descarga** cada mes 13 fuentes públicas (DANE, MSPS, ADRES, INS, Supersalud, CGR, DNP).
2. **Transforma** los archivos a tablas DuckDB, normaliza los códigos DANE (DIVIPOLA) de todas las
   fuentes y **calcula** los indicadores de la FCT para 1.123 municipios, 33 departamentos y el
   total nacional, para cada periodo (año y mes) disponible.
3. **Controla la calidad** (89 controles) y solo publica si no hay errores.
4. **Exporta** una base pequeña (~14 MB) con las tablas de métricas y la **publica** como release de
   GitHub.
5. El **tablero** (Streamlit) la lee. Los usuarios reciben una versión portable que descarga sola la
   base nueva cada mes.

### 1.2 Dos roles, dos equipos

```
Equipo de procesamiento (operador)                       Usuarios
──────────────────────────────────                       ────────
Python 3.12 + .venv + Chrome                             InformeRegional_<versión>.zip
scrapers/  ──►  data/parquet/*.parquet                   (Python embebido + tablero + base)
pipeline/transform ──► data/informe_regional.duckdb      Abrir Informe Regional.bat
pipeline/metricas, quality                                   │
pipeline/exportar ──► data/dist/informe_regional_visor.duckdb │ al abrir: ¿hay versión nueva?
tools/publicar_datos.py ──► GitHub release "datos-<versión>" ─┘ (descarga, SHA-256, instala)
```

- El repositorio **no contiene datos**: `data/` está excluida de git y se genera en el equipo del
  operador. Cada construcción parte de una base vacía.
- El tablero de los usuarios **no procesa nada**: solo lee la base del visor.

### 1.3 Tecnología

| Componente | Herramienta | Versión probada |
|---|---|---|
| Lenguaje | Python | 3.12 |
| Descarga | requests, selenium + undetected-chromedriver (SIVICAP), selenium (REPS), pdfplumber (+ Tesseract opcional) | ver `requirements-pipeline.txt` |
| Transformación | Polars (lectura de Excel con calamine/fastexcel y openpyxl) | 1.40 |
| Base de datos | DuckDB (archivo único, SQL analítico) | 1.5.2 |
| Tablero | Streamlit + Plotly | 1.57 / 6.7 |
| Distribución | Python embebido 3.12 (python.org) + GitHub CLI (`gh`) para publicar | |

---

## 2. Estructura del repositorio

```
Informe regional v2/
├── Preparar equipo.bat            crea .venv e instala requirements-pipeline.txt
├── Actualizar datos.bat           ciclo mensual: procesa, controla, exporta y ofrece publicar
├── Renovar sesion SIVICAP.bat     login manual en SIVICAP (reCAPTCHA) para el scraper de IRCA
├── requirements.txt               paquetes del visor (los que lleva la versión portable)
├── requirements-pipeline.txt      paquetes del procesamiento (incluye los del visor)
├── informe_regional.example.toml  plantilla de configuración local
├── .streamlit/config.toml         tema del tablero (colores) y barra de herramientas mínima
├── scrapers/                      una descarga por fuente (sección 5)
│   ├── settings.py                lee informe_regional.toml / variables de entorno
│   ├── errors.py                  ScrapeError
│   └── geo_normalize.py           códigos DANE para todas las tablas (vistas v_*)
├── pipeline/
│   ├── runner.py                  orquestador: pasos, códigos de salida, log
│   ├── transform.py               parquet → tablas DuckDB
│   ├── metricas.py                indicadores por municipio/departamento/nación y periodo
│   ├── quality.py                 89 controles; bloquea la publicación si hay ERROR
│   └── exportar.py                base del visor + manifest.json
├── dashboard/
│   ├── app.py                     entrada: navegación, barra lateral, versión de datos
│   ├── selection.py               filtros (año, mes, departamento, municipio)
│   ├── data.py                    acceso a la base y actualización automática
│   ├── registry.py                catálogo de indicadores (etiqueta, columna, unidad, fuente…)
│   ├── ui.py                      tarjetas, paneles, escalas, CSS
│   ├── charts.py                  mapas, donas, pirámide (Plotly)
│   ├── views/                     una página por módulo + inicio + ficha
│   ├── colombia_dptos.geojson     mapas (DANE MGN simplificado)
│   └── colombia_mpios.geojson
├── tools/
│   ├── publicar_datos.py          sube data/dist/ a una release de GitHub
│   ├── build_portable.py          genera dist/InformeRegional_<versión>.zip
│   ├── build_geojson.py           regenera los geojson desde el MGN del DANE
│   ├── build_docs.py              genera los .docx de los manuales
│   ├── build_entrega.py           paquete de entrega (código, manuales, tablero, datos)
│   └── setup_sivicap_session.py   sesión de Chrome para SIVICAP
├── docs/                          manuales, fórmulas, investigación de fuentes, auditoría
├── data/                          (no versionada) parquet, bases, manuales, dist, perfil Chrome
└── logs/                          (no versionada) pipeline_<fecha>.log
```

Carpetas de datos (`data/`):

| Carpeta | Contenido |
|---|---|
| `parquet/` | Salida de los scrapers. Es la **fuente de verdad** histórica: la base se reconstruye desde aquí |
| `raw/sivigila/` | Microdatos SIVIGILA crudos (hasta 110 MB por archivo) con su sello `.json` |
| `manual/<fuente>/` | Archivos descargados a mano (IRCA, afiliación); configurable (sección 3.3) |
| `informe_regional.duckdb` | Base completa del operador (tablas crudas, vistas, métricas) |
| `informe_regional.build.duckdb` | Base en construcción; se renombra sobre la anterior si pasa los controles |
| `dist/` | `informe_regional_visor.duckdb` + `manifest.json`: lo que se publica |
| `chrome_profile_sivicap/` | Perfil de Chrome con la sesión de SIVICAP |

---

## 3. Puesta en marcha del equipo de procesamiento

### 3.1 Requisitos

- Windows 10/11 de 64 bits (el proceso corre también en Linux salvo los scrapers con Selenium, que
  requieren Chrome y ChromeDriver en el equipo).
- **Python 3.12** (python.org, con *Add to PATH*). Otras versiones no están probadas: los paquetes
  están fijados para 3.12.
- **Google Chrome** (REPS y SIVICAP se descargan con un navegador).
- **GitHub CLI** (`gh`) solo para publicar; `gh auth login` con una cuenta con permiso de escritura en
  el repositorio.
- Opcional: Poppler y Tesseract (OCR para boletines del INS escaneados). Sin ellos, la etapa de OCR se
  omite y el resto funciona.
- Internet sin proxy que bloquee `datos.gov.co`, `dane.gov.co`, `minsalud.gov.co`, `ins.gov.co`,
  `portalsivigila.ins.gov.co`, `sivicap.ins.gov.co`, `adres.gov.co`, `supersalud.gov.co`,
  `sicodis.dnp.gov.co`, `analysis.windows.net` (Power BI público) y `github.com`.

### 3.2 Instalación

1. Clone o copie el repositorio.
2. Doble clic en **`Preparar equipo.bat`**: crea `.venv` e instala `requirements-pipeline.txt`.
3. Copie `informe_regional.example.toml` como `informe_regional.toml` si quiere cambiar la carpeta de
   manuales o el repositorio de publicación (sección 3.3).
4. Doble clic en **`Renovar sesion SIVICAP.bat`** y siga las instrucciones (sección 4.4).
5. Primera carga completa: `.venv\Scripts\python.exe -m pipeline.runner --run-now` (incluye la
   demografía del DANE, que el ciclo mensual no descarga). Tarda entre 30 y 60 minutos la primera vez
   (microdatos SIVIGILA, REPS); después, los scrapers solo bajan lo nuevo.

### 3.3 Configuración (`informe_regional.toml`)

`scrapers/settings.py` lee el archivo con `tomllib`. Prioridad: variable de entorno > TOML > valor
por defecto.

| Clave TOML | Variable de entorno | Por defecto | Uso |
|---|---|---|---|
| `[rutas] manuales` | `INFORME_MANUAL_DIR` | `data/manual` | Carpeta de archivos descargados a mano. Puede apuntar a una biblioteca de SharePoint sincronizada con OneDrive |
| `[publicacion] carpeta` | `INFORME_PUBLICACION_DIR` | `""` (desactivado) | Carpeta compartida (SharePoint sincronizado, unidad de red) donde se copia cada mes la base del visor. **Canal recomendado dentro de la organización** |
| `[publicacion] repo` | `INFORME_GITHUB_REPO` | `NavinetGroup/dashboard-salud` | Repositorio de GitHub con la release pública `datos-<versión>`; `""` desactiva este canal |
| `[tablero] carpeta_actualizacion` | `INFORME_UPDATE_DIR` | `""` | (Tablero) la misma carpeta compartida, vista desde el equipo del usuario |
| `[tablero] url_actualizacion` | `INFORME_RELEASE_URL` | release *latest* del repositorio | (Tablero) URL base con `manifest.json` y la base; `""` desactiva la descarga |

Un valor vacío (`""`) es un valor explícito y desactiva el canal; solo una clave ausente usa el valor
por defecto. `manual_dir(fuente)` devuelve `<manuales>/<fuente>` y crea la carpeta. Rutas relativas se
resuelven contra la raíz del proyecto; se expanden `~` y variables (`%OneDrive%`).

El tablero lee la sección `[tablero]` del mismo archivo, situado junto a la aplicación: la raíz del
repositorio en el equipo del operador, `app\informe_regional.toml` en la versión portable (sección 7.3).

---

## 4. Operación

### 4.1 Ciclo mensual

Doble clic en **`Actualizar datos.bat`** (equivale a `python -m pipeline.runner --monthly` seguido de
`python tools\publicar_datos.py`). Pasos, en orden:

| # | Paso | Qué hace |
|---|---|---|
| 1–12 | `reps`, `irca`, `afiliacion`, `supersalud`, `bdua`, `sivigila`, `cuipo`, `sicodis`, `cofinanciacion`, `eevv`, `ins_vsp`, `ins_pdf` | Cada scraper descarga lo nuevo a `data/parquet/`. Un fallo no detiene a los demás |
| 13 | `transform` | Base nueva desde cero (`informe_regional.build.duckdb`), conservando solo `_carga_log` y `_calidad_resultados` de la anterior; carga parquet → tablas; `geo_normalize`; `metricas` |
| 14 | `calidad` | 89 controles. Un ERROR detiene la publicación |
| 15 | `publicar` | Renombra la base nueva sobre `informe_regional.duckdb` |
| 16 | `exportar` | Base del visor + `manifest.json` en `data/dist/` |

Código de salida del runner:

| Código | Significado | Qué hacer |
|---|---|---|
| **0** | Todo bien | `Actualizar datos.bat` ofrece publicar |
| **1** | Algún scraper falló (típicamente IRCA), pero la base se construyó, pasó los controles y se exportó. Esa fuente conserva los datos del mes anterior | Publicar; revisar el log y resolver la fuente para el mes siguiente |
| **2** | `transform`, `calidad` o `publicar` fallaron. La base anterior no se tocó; `data/dist/` conserva la exportación anterior | Revisar el log; corregir; `python -m pipeline.runner --transform-only` si el problema no era de descarga |

Si falla `exportar` (código 1), `manifest.json` se borra antes de exportar, así que `publicar_datos.py`
se niega a publicar un archivo viejo.

Cada corrida escribe en consola y en `logs/pipeline_<AAAA-MM-DD>.log`.

**Publicar:** `publicar_datos.py` verifica el SHA-256 de la base exportada, muestra versión, tamaño y
canales, y pide confirmación (con `--si` no pregunta; uso programado). Según `[publicacion]`:

- **Carpeta compartida** (`carpeta`): copia la base (primero a `.part`, luego renombrado atómico) y
  después `manifest.json` a la carpeta. Si la carpeta es una biblioteca de SharePoint sincronizada con
  OneDrive, cada tablero configurado con esa misma biblioteca instala la versión nueva al abrirse. No
  requiere GitHub ni salida a internet.
- **GitHub** (`repo`): crea la release pública `datos-<versión>` con los dos archivos y la marca como
  *latest*; los tableros con `url_actualizacion` apuntando a ese repositorio la descargan.

Se pueden usar los dos canales a la vez. Con ninguno configurado el script se niega a continuar.

### 4.2 Ciclo anual

Después del 15 de julio (publicación de proyecciones del DANE): `python -m pipeline.runner --annual`.
Descarga las proyecciones y reconstruye la base. Si se cambió de año de proyección, los indicadores
por habitante cambian de denominador.

### 4.3 Modo programado

`python -m pipeline.runner` sin opciones deja un planificador (APScheduler, zona `America/Bogota`):
ciclo mensual el día 5 a las 08:00 y anual el 15 de julio a las 08:00. En Windows se puede dejar
como tarea programada con `python -m pipeline.runner --monthly` + `python tools\publicar_datos.py --si`.

### 4.4 IRCA y SIVICAP (reCAPTCHA)

SIVICAP protege el inicio de sesión con reCAPTCHA; un programa no puede resolverlo. Dos caminos:

- **Sesión guardada.** `Renovar sesion SIVICAP.bat` abre Chrome con el perfil
  `data/chrome_profile_sivicap`, escribe el usuario invitado (`invitado@ins.gov.co` / `123456`, publicados
  en la propia página de SIVICAP) y espera. La persona marca "No soy un robot", pulsa *Iniciar Sesión* y
  presiona ENTER en la ventana negra. El scraper reutiliza esa sesión durante varias semanas (modo sin
  ventana). Cuando el pipeline avise `irca: SIVICAP no entregó datos (probable reCAPTCHA)`, repetirlo.
- **CSV a mano.** En SIVICAP (usuario invitado) → Reportes → *IRCA mensual por municipio (Resolución
  622/2020)* → Exportar CSV. Guardar el archivo en `<manuales>/irca/`. En la siguiente corrida se carga,
  se mueve a `irca/procesados/<fecha>_<nombre>` y no se intenta el scraping web.

Si SIVICAP rechaza el usuario invitado ("inicio de sesión no válida" en cualquier navegador), el
problema es del INS: reportarlo por el enlace *Soporte* de la página de login y usar el CSV manual
cuando vuelva. La base conserva los últimos valores cargados.

### 4.5 Archivos manuales

| Subcarpeta de `<manuales>` | Qué dejar | Qué pasa |
|---|---|---|
| `irca/` | CSV exportado de SIVICAP | Se carga y se mueve a `irca/procesados/` |
| `afiliacion/` | ZIP de cifras de afiliación del MSPS cuyo nombre contenga `afiliacion` | Se usa para el mes que indica el Excel interno, si el sitio no lo entregó |

### 4.6 Verificación local

- Base completa: `.venv\Scripts\python.exe -m streamlit run dashboard\app.py` muestra
  `data/informe_regional.duckdb` (la versión en la barra lateral no aparece: es la base del operador).
- Base del visor, tal como la verán los usuarios:
  `set INFORME_DB_PATH=data\dist\informe_regional_visor.duckdb` antes del mismo comando.
- Controles sobre la base actual: `.venv\Scripts\python.exe -m pipeline.quality`.
- Historial: tablas `_calidad_resultados` (control, nivel, ok, detalle) y `_carga_log` (filas por tabla
  y corrida).

---

## 5. Fuentes de datos (scrapers)

Convenciones comunes a todos los scrapers:

- Punto de entrada `run(base_dir=None)`; el runner lo llama solo con `base_dir`. Los parámetros
  adicionales que algunos aceptan quedan en su valor por defecto.
- Contrato: si `run` termina sin excepción, la fuente está al día (incluido "no hay nada nuevo"). Si
  lanza `ScrapeError` (`scrapers/errors.py`), la fuente no pudo actualizarse y el runner lo registra sin
  detener el ciclo.
- Salida en `data/parquet/`, comprimida con zstd. Los archivos existentes **no se borran**: son la
  serie histórica. Cada scraper decide qué vuelve a descargar (sello de fecha, `rowsUpdatedAt`,
  `Modified`, etc.).
- Reintentos ante errores de red o códigos 429/5xx, con espera creciente.
- Nada de datos personales: se agregan por municipio o se descartan las columnas de personas.

### 5.1 `demografico.py` — Proyecciones de población DANE (anual)

| | |
|---|---|
| Fuente | DANE, proyecciones de población Censo 2018, 2018–2042: por área, sexo y edad simple (`PPED-AreaSexoEdadMun-2018-2042_VP.xlsx`, hoja `PobMunicipalxÁreaSexoEdad`) y por pertenencia étnico-racial (`anex-DCD-Proypoblacion-PerteneniaEtnicoRacialmun.xlsx`, hoja `Municipal`) |
| Alimenta | Población total/hombres/mujeres, menores de 5 (denominadores), población étnica; **maestro geográfico** (`geo_maestro`, 1.123 municipios) |
| Acceso | URLs públicas `dane.gov.co`, sin login; requests + openpyxl |
| Periodicidad | Ciclo anual (`--annual` o `--run-now`); se sobrescribe |
| Salida | `demografico_edad_sexo.parquet` (`codigo_dep, nombre_dep, codigo_mun, municipio, anio, area_geografica, sexo, edad, poblacion`), `demografico_etnico.parquet` (`… grupo_etnico, poblacion`) |
| Reglas | Detecta la fila de encabezado buscando `DP`/`COD_DPTO`/`DEPARTAMENTO`; descarta las filas "Total" de área; los 6 grupos étnicos se homogeneizan con `RENAME_ETH` / `ETHNIC_GROUPS` |
| Si cambia la fuente | `URL_AGE`, `URL_ETH`, `SHEET_AGE`, `SHEET_ETH`; la expresión regular de columnas `Hombres_<edad>`; `RENAME_ETH` |
| Fallos | `ScrapeError` si no descarga o no reconoce columnas de edad/étnicas ("¿cambió el formato DANE?") |

### 5.2 `afiliacion_scraper.py` — Cifras de afiliación MSPS (mensual)

| | |
|---|---|
| Fuente | MSPS, "Cifras de afiliación en salud": un ZIP mensual con un Excel (`CIFRAS <MES>-<AÑO>.xlsx`), hoja `CoberturaMunicipio` (o `EPSMunicipio`, `EPS`) |
| Alimenta | Afiliados por régimen y municipio, cobertura, afiliados sin Sisbén IV y poblaciones especiales (Aseguramiento 5–11) |
| Acceso | `minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/{RBC,DOA,DOA/OAS}/…`. El MSPS no tiene nombre estable: se prueban con HEAD varias plantillas (`cifras-afiliacion-salud-<mes>-<año>`, abreviaturas…) además de `HISTORICAL_URLS` para meses conocidos |
| Periodicidad | Los 12 meses anteriores al actual que no tengan parquet. Un mes aún no publicado no es error |
| Salida | `afiliacion_<AAAA>_<MM>.parquet`, columnas renombradas con `RENAME_MAP` (`codigo_dep, departamento, codigo_mun, municipio, afiliados_contributivo, afiliados_subsidiado, afiliados_total, Cobertura, "Afil. Subsidiado sin SISBEN IV"…`), más `anio`, `mes` |
| Reglas | El periodo se toma del nombre del Excel interno, no del mes pedido; si no coinciden se avisa. Desde marzo de 2026 el MSPS incluye `codigo_mun`; antes se cruza por nombre |
| Manual | `<manuales>/afiliacion/*.zip` (también la raíz del proyecto y `data/raw/`) |
| Si cambia la fuente | `HISTORICAL_URLS`, `_URL_DIRS`, `_URL_STEMS`, `MESES_ABBR`, `RENAME_MAP`, lista `preferred` de hojas |

### 5.3 `bdua_scraper.py` — BDUA (ADRES, datos.gov.co) (mensual)

| | |
|---|---|
| Fuente | Datasets Socrata `d7a5-cnra` (subsidiado) y `tq4m-hmg2` (contributivo): afiliados por departamento, municipio, EPS, sexo y grupo de edad |
| Alimenta | EPS por territorio (Aseguramiento 1–3) y pirámide de afiliados |
| Acceso | API SoQL (`/resource/<id>.json`) con `$select … sum(cantidad)`, `$group`, paginada de 50.000; la agregación la hace el servidor. Sin token |
| Periodicidad | La fuente solo publica el mes vigente. Sello = menor `rowsUpdatedAt` de los dos datasets; si ya existe la foto, no hace nada. **Las fotos archivadas son la única serie histórica: no borrarlas** |
| Salida | `bdua_eps_<AAAA_MM>.parquet` (`departamento, municipio, ent_id, ent_nombre, afiliados, regimen, fecha_corte`), `bdua_piramide_<AAAA_MM>.parquet` (`… sexo, grupo_edad, afiliados, regimen, fecha_corte`) |
| Si cambia la fuente | `DATASETS`, `_GEO`, `_QUERIES` (nombres de columnas SoQL) |

### 5.4 `reps_scraper.py` — REPS (MSPS) (mensual)

| | |
|---|---|
| Fuente | Registro Especial de Prestadores, `prestadores.minsalud.gov.co/habilitacion/consultas/`: 6 consultas (`habilitados`, `sedes`, `serviciossedes`, `capacidadesinstaladas`, `medidasseguridad`, `sanciones`) |
| Alimenta | IPS por naturaleza (Prestación 1–4), capacidad instalada (5) |
| Acceso | Selenium (Chrome, ventana fuera de pantalla). Entrada pública: cierra el modal y pulsa el botón de invitado; luego, por consulta, pulsa *Buscar*, fija el separador `|` y *Exportar*. IDs de controles ASP.NET en `ENDPOINTS` |
| Periodicidad | Una foto por mes calendario (`reps_<consulta>_<AAAA_MM>.parquet`); la de `sanciones` tarda 6–8 min (timeout 600 s) |
| Salida | Todas las columnas como texto. `codigo_habilitacion` (los 5 primeros dígitos, rellenado a 10, son el DIVIPOLA municipal) |
| Reglas | Lector tolerante (`latin1`, separador `|` o `;`, líneas partidas) |
| Si cambia la fuente | `ENDPOINTS` (URL, IDs de botones, nombre del archivo, timeout) y `_login` |
| Fallos | `ScrapeError('reps: endpoints sin datos: …')` |

### 5.5 `supersalud_scraper.py` — Entidades intervenidas (mensual)

| | |
|---|---|
| Fuente | Supersalud, listados de entidades en medida preventiva o intervención forzosa, Excel en `docs.supersalud.gov.co/PortalWeb/MedidasEspeciales/Directorio de Entidades/` (uno para IPS, otro para EPS) |
| Alimenta | IPS intervenidas (Prestación 6), EPS intervenidas (Aseguramiento 4) |
| Acceso | requests + openpyxl, sin login |
| Periodicidad | Una foto por mes calendario |
| Salida | `supersalud_{ips,eps}_intervenidas_<AAAA_MM>.parquet`: `numero, entidad, ciudad, departamento, nit, direccion, clase_medida, resolucion, fecha_final_medida, acta_posesion, vencimiento_acta, fecha_actualizacion`. **Los datos del representante legal (nombre, cédula, correo, teléfono) se descartan a propósito** |
| Si cambia la fuente | `URL_IPS_XLSX`, `URL_EPS_XLSX` (un HTTP 401 suele indicar que cambió la URL), `_COLUMN_MAP`, `_REQUIRED` |

### 5.6 `sivigila_scraper.py` — SIVIGILA (INS) (anual + preliminar semanal)

| | |
|---|---|
| Fuente | (1) Microdatos anuales del Portal SIVIGILA (SharePoint REST, biblioteca `Microdatos`), un xlsx por evento y año; (2) tablero público de Power BI "006 Vigilancia Rutinaria" para el año en curso (API pública, sin login) |
| Eventos | 113 desnutrición aguda, 112 mortalidad por desnutrición, 220 dengue grave, 356 intento de suicidio, 875 violencia de género, 740 sífilis congénita. La mortalidad materna (550) sigue viniendo del boletín PDF porque la razón oficial no se reproduce con microdatos |
| Alimenta | Salud pública 2, 3, 4, 6, 7, 8 |
| Periodicidad | Microdatos: se vuelven a bajar si cambia `Modified`; los xlsx crudos quedan en `data/raw/sivigila/`. Rutinaria: cada corrida; se excluye la última semana (incompleta) y se valida que el detalle sume el total |
| Salida | `sivigila_casos_<AAAA>.parquet` (+ `.json` de sellos) y `sivigila_rutinaria_<AAAA>.parquet`: `evento, anio, semana, cod_dpto, cod_mun, casos`. En transform, los microdatos tienen prioridad; la rutinaria solo aporta los años sin microdatos (`fuente = microdatos | rutinaria`) |
| Reglas | Solo `COD_PAIS_R = 170`, se excluyen los ajustes 6 y D (descartados), y la residencia en el exterior |
| **Restricción** | Solo se consulta la tabla `Rutinaria <año>` del modelo público. Otros modelos del INS contienen datos personales: **no deben leerse** |
| Si cambia la fuente | `EVENTS`, `COLUMNS`, `DESCARTADOS`, `LIST_URL`, `RUTINARIA_TITLE`, `RUTINARIA_EVENTS`, `MENU_URL`, nombres de propiedades Power BI en `rutinaria()`. Si el control `frescura_sivigila_preliminar` avisa, comprobar que el tablero siga existiendo con ese nombre |

### 5.7 `ins_pdf_scraper.py` — Informes de evento del INS (por periodo epidemiológico)

| | |
|---|---|
| Fuente | `ins.gov.co/buscador-eventos/Informesdeevento/<EVENTO> PE <ROMANO> <AÑO>.pdf` (13 periodos por año). Eventos: mortalidad materna, desnutrición aguda, mortalidad en menores de 5, intento de suicidio, violencia de género |
| Alimenta | Razón de mortalidad materna (Salud pública 1). Los demás eventos son **respaldo** cuando SIVIGILA no tiene el año |
| Acceso | requests + pdfplumber; extracción en 4 etapas: tablas por líneas, rejilla de palabras, tablas por texto, OCR (Tesseract, opcional). Cada tabla se valida: al menos el 30 % de los nombres deben ser departamentos o distritos conocidos |
| Periodicidad | Todos los PE desde `START_YEAR` (2025) hasta el último completo. Caché positiva (si existe el parquet, no se baja) y **caché negativa** `data/parquet/ins_pdf_sin_datos.json`: un periodo sin boletín o sin tabla útil no se reintenta durante 30 días; los 2 últimos periodos se reintentan siempre |
| Salida | `ins_<evento>_PE_<ROMANO>_<AÑO>[_tabla<i>].parquet` con las columnas del esquema del evento (`EVENTS`) más `anio, periodo_epidemiologico, evento` |
| Si cambia la fuente | La entrada del evento en `EVENTS` (página, tablas, esquema de columnas, `word_grid_options`), `URL_NAME_VARIANTS`, `BASE_INS`, `_COLOMBIA_DEPARTMENTS` |
| Fallos | `ScrapeError` solo si un evento queda sin ningún archivo. Desde 2026 el boletín de desnutrición ya no trae desglose geográfico: los avisos "no tables" para ese evento son esperados |

### 5.8 `irca_scraper.py` — IRCA (SIVICAP, INS) (mensual)

| | |
|---|---|
| Fuente | `sivicap.ins.gov.co`, reporte *IRCA mensual por municipio (Resolución 622/2020)* exportado a CSV |
| Alimenta | Salud pública 5 |
| Acceso | undetected-chromedriver con perfil persistente (`data/chrome_profile_sivicap`) creado con `tools/setup_sivicap_session.py`. Comprueba la sesión abriendo el reporte; si redirige al login, intenta el login automático (casi siempre bloqueado por reCAPTCHA) y falla con instrucciones |
| Manual | `<manuales>/irca/*.csv` tiene **prioridad** sobre el scraping (sección 4.4) |
| Salida | `irca_<AAAA>_<MM>.parquet` (sello = último mes presente en los datos): `anio, mes, codigo_dep, nombre_dep, codigo_mun, municipio, n_muestras, promedio_parametros, promedio_irca, nivel_riesgo` y variantes urbano/rural |
| Reglas | Cada exportación repite meses anteriores; transform conserva una fila por `(anio, mes, codigo_mun)` del archivo más nuevo |
| Si cambia la fuente | `SIVICAP_LOGIN`, `SIVICAP_REPORT`, `COLUMN_MAP`, textos del `<select>` de reportes, XPaths de los botones, prefijo `RptIrca` |

### 5.9 `cuipo_scraper.py` — CUIPO (CGR, datos.gov.co) (trimestral)

| | |
|---|---|
| Fuente | Categoría Única de Información del Presupuesto Ordinario: ingresos `9axr-9gnb`, gastos `4f7r-epif`, programación `d9mu-h6ar`. Trimestral y acumulado en el año (`periodo = AAAAMM01`, MM = 03/06/09/12) |
| Alimenta | Financiamiento 1–7 (numeradores y recaudo/apropiación del FLS) |
| Acceso | SoQL paginada sin agregación en servidor (las agrupaciones sobre ~12 M de filas exceden el tiempo): se bajan las ~25 k filas de salud por periodo y se agregan localmente |
| Filtros | Ámbitos A438 gobernaciones, A439 municipios, A440 Bogotá, A441 San Andrés. Gasto y programación de salud: código MGA o sectorial que empiece por `19`, vigencias 1 y 4. Ingresos: detalle sectorial `FLS…` o fuente que contenga `SALUD`. SGP: `1.2.4.2.02` salud pública, `1.2.4.2.04` oferta |
| Periodicidad | Vuelve a bajar un periodo si su parquet es anterior al `rowsUpdatedAt` de los datasets (la CGR revisa trimestres pasados) |
| Salida | `cuipo_salud_<AAAAMM>.parquet`, una fila por entidad: `fls_recaudo, fls_compromisos, fls_obligaciones, fls_pagos, fls_apropiacion_inicial, fls_apropiacion_definitiva, sgp_{sp,of}_{recaudo,compromisos,pagos}, anio, mes, nivel, codigo_dep, codigo_mun` |
| Reglas | Código CGN → DIVIPOLA: los 5 últimos dígitos, salvo los municipios `923…` mapeados en `_CGN_DIVIPOLA`. `_FONDOS`: el FFDS (`225511001`) representa a Bogotá en las columnas FLS; el IDS (`124754000`) a Norte de Santander en todas |
| Si cambia la fuente | `_CGN_DIVIPOLA` (si el control `cuipo_codigo_divipola` falla apareció un municipio nuevo), `_FONDOS`, IDs de datasets, `AMBITOS`, `_SALUD`, `_SGP`, `START` |

### 5.10 `sicodis_scraper.py` — Asignaciones SGP (DNP) (anual)

| | |
|---|---|
| Fuente | SICODIS, API `sicodis.dnp.gov.co/apiws/ApiSicodisNew`: `/sgp/vigencias` y el Excel `/sgp/archivo_resumen_participaciones/<año>/0/0/Todos/Todos`, hoja `Datos Reporte SGP Detalle` |
| Alimenta | Denominadores de Financiamiento 4–7 |
| Periodicidad | Años cerrados una vez; el vigente en cada corrida (el DNP agrega distribuciones parciales) |
| Salida | `sgp_salud_<AAAA>.parquet`: `codigo_entidad, nombre_entidad, tipo_entidad, sgp_salud, sgp_regimen_subsidiado, sgp_salud_publica, sgp_subsidio_oferta, anio, codigo_dep, codigo_mun` (NULL en gobernaciones) |
| Si cambia la fuente | `API`, ruta del endpoint, `SHEET`, `_COLS`; se exigen ≥ 1.000 entidades |

### 5.11 `cofinanciacion_scraper.py` — Cofinanciación del régimen subsidiado (mensual)

| | |
|---|---|
| Fuente | Meta: MSPS, matriz de continuidad "Monto estimado de recursos del régimen subsidiado" (página `matriz-continuidad.aspx`, ZIP/Excel por año; se toma la versión más reciente). Ejecución: ADRES, "Resultado LMA" mensual (índice `/api/media?where[filename][like]=liquidacion-mensual-de-afiliados`) |
| Alimenta | Financiamiento 8 |
| Periodicidad | Meta del año en curso en cada corrida; LMA de un mes se vuelve a bajar si `updatedAt` es posterior al sello guardado |
| Salida | `cofin_meta_<AAAA>.parquet` (`codigo_mun, meta_mun, meta_dep, anio, version`), `cofin_lma_<AAAA>_<MM>.parquet` (`codigo_mun, girado_mun, girado_dep, anio, mes, stamp`) |
| Reglas | Encabezados de varias filas fusionados como `GRUPO || SUBCOLUMNA`; LMA: hoja `DETALLE`, ancla `DANE`; meta: hoja `MONTO ESTIMADO…`, ancla `CODIGO DANE`. Se exigen ≥ 1.000 municipios |
| Si cambia la fuente | Diccionario `pick` de `_parse_lma`, `_parse_meta`, `MSPS_PAGE`, filtro del índice ADRES. El error nombra las columnas no reconocidas |

### 5.12 `eevv_scraper.py` — Nacimientos y defunciones fetales (DANE) (anual)

| | |
|---|---|
| Fuente | Estadísticas vitales, cuadros por municipio de residencia de la madre (`dane.gov.co/…/nacimientos/nacimientos-<año>` y `…/defunciones-fetales/defunciones-fetales-<año>`) |
| Alimenta | Denominador de la incidencia de sífilis congénita (Salud pública 2) |
| Periodicidad | Solo años completos y definitivos (prefiere `DEFINITIV`; un "año corrido" se omite). Se vuelve a bajar si cambian los nombres de archivo. `START_YEAR = 2024` (las tablas de 2023 son `.xls` protegidos) |
| Salida | `eevv_nacimientos_<AAAA>.parquet`: `codigo_dep, codigo_mun, nacimientos, defunciones_fetales, anio, version` |
| Reglas | Excluye totales (`…000`) y residencia en el exterior (`75…`); conserva `DD999` (sin información). Se exigen ≥ 300.000 nacimientos |
| Si cambia la fuente | `PAGES`, `TITLES`, `START_YEAR`, `_full_year_link` |

### 5.13 `ins_vsp_scraper.py` — Desempeño de la vigilancia en salud pública (INS) (trimestral)

| | |
|---|---|
| Fuente | Portal SIVIGILA, biblioteca "Documentos compartidos" (SharePoint REST, lista `Documentos`): Excel `…DESEMPE…<año> <trimestre romano>… PRELIMINAR|FINAL.xlsx` (se excluyen los de EAPB) |
| Alimenta | Salud pública 10 y 11 |
| Periodicidad | Un archivo por trimestre; FINAL reemplaza a PRELIMINAR. Se vuelve a bajar si cambia `nombre|Modified` |
| Salida | `ins_vsp_<AAAA>_<T>.parquet`: `codigo_entidad, entidad, grupo, subindicador, descripcion, valor, anio, trimestre, estado, fuente` |
| Reglas | Entidades = departamentos (`DD000`) y distritos; se exigen ≥ 33. Valores no numéricos → NULL |
| Si cambia la fuente | `LIBRARY`, filtros de nombre en `_quarter_files`, `_parse`. El control `frescura_vsp` avisa si no aparece un trimestre nuevo |

### 5.14 Capa geográfica: `scrapers/geo_normalize.py`

No es un scraper: `transform.run()` lo llama tras cargar las tablas. Construye:

- `geo_maestro (dep_codigo, mun_codigo, dep_dane, mun_dane)` y `geo_dep` desde `demografico_edad_sexo`.
- Para cada tabla fuente, una vista `v_<tabla>` con `geo_dep_codigo, geo_mun_codigo, geo_dep_dane,
  geo_mun_dane, geo_distrito_codigo`, por tres mecanismos:

| Tipo | Tablas | Cruce |
|---|---|---|
| Con código DIVIPOLA | demográficas, `irca`, `sivigila_casos`, `cuipo_salud`, `cofin_*`, `eevv_nacimientos`, `ins_vsp` | `JOIN` directo con `geo_maestro` / `geo_dep` |
| Por nombre | `bdua_*`, `ins_mortalidad_materna`, `ins_desnutricion_aguda`, `ins_intento_suicidio` (municipio); `ins_mortalidad_menores5`, `ins_violencia_genero`, `supersalud_*` (departamento) | Tabla puente `geo_map_<tabla>` construida con `_key()` (mayúsculas, sin tildes ni puntuación, `¥`→`Ñ`, letras sueltas unidas, sufijos ` ANM`/` CD` eliminados), `DEPT_ALIASES`, `DISTRICTS`, `MUN_ALIASES` |
| Código primero | `reps_*` (5 primeros dígitos de `codigo_habilitacion`), `afiliacion` | Si el código es un DIVIPOLA válido se usa; si no, el puente por nombre |

Para una grafía nueva: agregar el alias en `DEPT_ALIASES` o `MUN_ALIASES` (con alcance por
departamento; no agregar coincidencias difusas). Para una tabla nueva: agregarla a `GEO_SOURCES` o
`CODE_FIRST_SOURCES`. Los controles `*_match_municipio` / `*_match_departamento` miden el cruce.

### 5.15 Mapas: `tools/build_geojson.py`

Genera `dashboard/colombia_dptos.geojson` y `colombia_mpios.geojson` desde el Marco Geoestadístico
Nacional del DANE (ArcGIS REST público, capas 319 y 317), simplificados en servidor
(`maxAllowableOffset` 0,005° y 0,002°), con 4 decimales, un departamento por consulta (el servicio
rechaza la paginación) y anillos reorientados para Plotly (`_rewind`). Ejecutar cuando el DANE
publique un MGN nuevo: `python tools\build_geojson.py --year 2026`. No lo llama el pipeline.

---

## 6. Procesamiento

### 6.1 `pipeline/runner.py`

- Opciones: `--monthly`, `--annual`, `--run-now`, `--transform-only`; sin opción, planificador.
- `_safe(fn, nombre)` ejecuta cada paso y captura `ScrapeError`/`QualityError` (una línea) y cualquier
  otra excepción, incluidos los *panics* nativos de Polars/DuckDB (traceback completo), para que un
  fallo nunca detenga el ciclo. `faulthandler` escribe la pila si un módulo nativo se cae.
- `_transform_step`: borra la base de construcción, copia `_carga_log` y `_calidad_resultados` de la
  base viva (ATTACH de solo lectura) y llama a `transform.run`.
- `_publish_step`: `os.replace(build, live)`; falla si queda un `.wal` (cierre sucio) o si otro proceso
  (un Streamlit abierto sobre la base del operador) la tiene bloqueada.
- Códigos de salida: sección 4.1.

### 6.2 `pipeline/transform.py`

Carga cada familia de parquet en una tabla. Si no hay archivos de una fuente, la tabla no se crea y
se avisa (no es error): las métricas de esa fuente salen `NULL`.

| Tabla | Origen | Regla |
|---|---|---|
| `demografico_edad_sexo`, `demografico_menores5`, `demografico_etnico` | demografico | Agregadas por municipio, año, sexo / grupo étnico (menores: `edad < 5`) |
| `reps_prestadores`, `reps_sedes`, `reps_servicios`, `reps_capacidad`, `reps_medidas_seguridad`, `reps_sanciones` | reps | Última foto mensual (`snapshot`) |
| `irca` | irca | Una fila por `(anio, mes, codigo_mun)`, del archivo más nuevo |
| `afiliacion` | afiliacion | Todos los meses (`union_by_name`) |
| `supersalud_ips_intervenidas`, `supersalud_eps_intervenidas` | supersalud | Última foto |
| `ins_mortalidad_materna`, `ins_desnutricion_aguda`, `ins_mortalidad_menores5`, `ins_intento_suicidio`, `ins_violencia_genero` | ins_pdf | Todos los periodos |
| `bdua_eps`, `bdua_piramide` | bdua | Última foto |
| `sivigila_casos` | sivigila | Microdatos + rutinaria para años sin microdatos (`fuente`) |
| `cuipo_salud`, `sgp_salud`, `cofin_meta`, `cofin_lma`, `eevv_nacimientos`, `ins_vsp` | financiamiento, eevv, vsp | Cargador genérico; `codigo_dep` derivado donde falta |

Luego `geo_normalize.build_all` y `metricas.build_all`.

### 6.3 `pipeline/metricas.py`

**Salida.** `v_metricas_municipio` (1.123 filas), `v_metricas_departamento` (33), `v_metricas_nacional`
(1) con el dato más reciente, y las tablas por periodo `metricas_{municipio,departamento,nacional}_periodo`
y `_anterior`, con `anio_filtro` y `mes_filtro` (`NULL` = último disponible del año). `piramide_afiliados`
por nivel (`municipio`, `departamento`, `nacional` con código 0).

**Grilla de periodos.** Años = unión de los años con afiliación, IRCA o mortalidad materna. Por año,
`(año, NULL)` y `(año, MES)` por cada mes de afiliación. Para cada celda, `_resolve_caps` fija el corte
de cada fuente (periodo epidemiológico máximo del año, mes de afiliación, trimestre VSP, mes de
LMA, trimestre CUIPO, mes IRCA) y cada CTE toma lo último hasta ese corte. La tabla `_anterior`
repite el cálculo para `año − 1` con **los mismos cortes**, para que la tendencia compare periodos
equivalentes (PE IX con PE IX, septiembre con septiembre).

**Rendimiento.** Antes de la grilla, cada vista `v_*` se materializa como tabla temporal (de ~125 s a
~70 s, resultados idénticos).

**Reglas especiales.**

- Población: el año de proyección es el mayor ≤ año seleccionado.
- Un municipio ausente del último reporte de una fuente queda `NULL`; nunca se rellena con un valor
  viejo.
- IRCA: última medición de cada municipio dentro de los 12 meses previos al corte; departamento y
  nación ponderan por número de muestras.
- Boletines INS: la fila propia del departamento excluye los distritos; los distritos alimentan a su
  municipio. Los números del PDF se convierten con `_dd` (miles con punto, decimal con coma).
- SIVIGILA: casos acumulados hasta la semana de corte (última cargada del año). Tasas por 100.000
  habitantes (dengue, suicidio, violencia), por 100 menores de 5 (desnutrición aguda), por 100.000
  menores de 5 (mortalidad por desnutrición) y por 1.000 nacidos vivos + muertes fetales **prorrateados**
  a `semana/52` (sífilis congénita; nacimientos del mayor año ≤ seleccionado). Etiqueta `AAAA sem. 1–N`,
  con "(preliminar)" si hay filas rutinarias.
- CUIPO: último trimestre del alcance (acumulado en el año). Razones `100 × Σnum / Σden`; `NULL` si el
  denominador es 0. Departamento = gobernación, salvo Bogotá (11) = distrito. SGP cruzado con SICODIS
  por año y entidad.
- Cofinanciación: `100 × girado(ene..k) / (meta × k/12)`, con `k` = último mes de LMA del alcance.
  Municipio con `girado_mun/meta_mun`; departamento con las columnas departamentales (Bogotá, las
  municipales); nación con la suma de ambas.
- VSP: valores > 1,5 se dividen por 100 y se acotan a 1. Cumplimiento = media de los grupos 1–7;
  capacidades = subindicador 8-1; cumple ≥ 0,995, parcial entre 0 y 0,995, no cumple = 0. Último
  trimestre con `trimestre × 3 ≤ mes de corte`. Municipios: solo los distritos tienen fila propia.
- Cobertura: municipio = columna del MSPS; departamento/nación = `min(100, 100 × Σafiliados / Σpoblación)`.
- EPS (BDUA): nombre normalizado sin sufijo `-CM`; se excluyen `EAS%` y filas sin afiliados.

**Columnas (resumen).** Demográficos: `pob_total, pob_hombres, pob_mujeres, pob_etnico_total,
pob_indigena, pob_gitana_rrom, pob_raizal, pob_palenquera, pob_negra_afro, pob_ninguno,
pob_con_pertenencia`. Salud pública: `irca_promedio, irca_nivel_riesgo, irca_periodo,
razon_mortalidad_materna, periodo_mortalidad_materna, prevalencia_desnutricion_aguda,
casos_desnutricion_aguda, tasa_intento_suicidio, tasa_mortalidad_menores5_{dnt,ira,eda},
violencia_{fisica,psicologica,sexual}, negligencia_abandono, violencia_genero_intrafamiliar,
sv_{desnutricion,mort_desnutricion,dengue_grave,suicidio,violencia,sifilis}_{casos,tasa}, sv_semana,
periodo_sivigila, vsp_cumplimiento, vsp_capacidades, vsp_subindicadores, vsp_{cumple,parcial,nocumple},
periodo_vsp` y las etiquetas `periodo_*`. Aseguramiento: `afiliados_{subsidiado,contributivo,total},
cobertura_pct, afil_sin_sisben, afil_especiales_sin_sisben, afil_oficio_sin_sisben,
afil_no_pobre_no_vulnerable, periodo_afiliacion, eps_total, eps_contributivo, eps_subsidiado,
eps_fecha_corte, eps_intervenidas`. Prestación: `ips_total, ips_publica, ips_privada, ips_mixta,
ips_intervenidas, capacidad_instalada, camas, consultorios, salas_cirugia, uci_adultos, uci_pediatricas`.
Financiamiento: `fin_comp_recaudo, fin_comp_aprop, fin_pagos_recaudo, fin_sgp_sp_comp,
fin_sgp_sp_pagos, fin_sgp_of_comp, fin_sgp_of_giros, fls_{recaudo,apropiacion_definitiva,compromisos,pagos},
periodo_cuipo, fin_cofinanciacion, cofin_girado, cofin_meta_anual, periodo_cofin`.

Las fórmulas de Financiamiento, con sus supuestos pendientes de validación con Supersalud, están en
`docs/FINANCIAMIENTO_FORMULAS.md`.

### 6.4 `pipeline/quality.py`

`run()` ejecuta los bloques `structure, duplicates, geo_match, consistency, ranges, freshness,
financing, births, vsp, row_jumps`. Un bloque que se cae queda como ERROR. Si hay algún ERROR se
lanza `QualityError` y no se publica; los WARN solo se listan. Resultados en `_calidad_resultados`;
conteos de filas por tabla en `_carga_log`.

| Grupo | Controles (nivel) |
|---|---|
| Estructura | 1.123 municipios y 33 departamentos en las vistas de métricas; llave única `(anio_filtro, mes_filtro, código)` en las tablas por periodo (ERROR) |
| Duplicados | Llaves naturales de `irca`, `afiliacion`, `reps_prestadores`, `supersalud_*`; formato de `codigo_habilitacion` en las 6 tablas REPS (ERROR) |
| Cruce geográfico | ≥ 99,5 % de filas con municipio en afiliación, REPS, IRCA, BDUA; ≥ 99 % en SIVIGILA (ERROR). ≥ 90 % en desnutrición y suicidio del boletín, ≥ 75 % en mortalidad materna, ≥ 90 % de departamento en violencia, menores de 5 y Supersalud (WARN) |
| Consistencia | Población étnica ≈ total (±2 %); población en todos los municipios; ≥ 1.100 municipios con afiliación; ningún par de meses de afiliación con el mismo total (meses re-etiquetados); variación mensual ≤ 3 %; BDUA vs. afiliación ≤ 5 % |
| Rangos | Departamentos dentro de rango: cobertura 0–100, IRCA 0–100, desnutrición 0–20, dengue grave 0–200, mortalidad materna 0–2.000, suicidio 0–1.000, violencia física 0–2.000, mortalidad menores 0–500 (ERROR); cobertura nacional 85–100 (WARN) |
| Frescura | Afiliación ≤ 3 meses, IRCA ≤ 4, REPS ≤ 2, SIVIGILA preliminar ≤ 3 semanas, boletines INS ≤ 3 PE, CUIPO ≤ 6 meses, LMA ≤ 1 mes, nacimientos ≥ año − 2, VSP ≤ 9 meses (WARN) |
| Financiamiento | Todo municipio CUIPO con DIVIPOLA (ERROR); cobertura ≥ 1.050 municipios y 31 gobernaciones (WARN); cruce CUIPO–SICODIS (ERROR); razones nacionales plausibles (WARN); municipios de la meta y la LMA con DIVIPOLA y matriz del año vigente (ERROR) |
| Nacimientos y VSP | Sin huérfanos geográficos (ERROR); 380.000–700.000 nacimientos (WARN); ≥ 37 entidades VSP (WARN); códigos VSP válidos (ERROR) |
| Saltos de filas | Para 20 tablas, cambio frente a la carga anterior: WARN si > 30 %, ERROR si < −50 % o > +100 % |

### 6.5 `pipeline/exportar.py`

Copia a `data/dist/informe_regional_visor.duckdb` las 7 tablas que el tablero usa
(`metricas_*_periodo`, `metricas_*_anterior`, `piramide_afiliados`), crea `_visor_info` (`version`,
`generado`, `ultimo_sivigila`, `ultimo_cuipo`, `ultimo_cofinanciacion`, `ultimo_ins_vsp`) y escribe
`manifest.json` (`version`, `archivo`, `sha256`, `bytes`, `generado`). La versión es
`AAAA.MM.DD-HHMM`; comparada como texto da el orden cronológico.

### 6.6 `tools/publicar_datos.py`

Comprueba que existan el manifiesto y el archivo con el tamaño declarado y que `gh` esté
disponible; pide confirmación (o `--si`); ejecuta `gh release create datos-<versión> <base>
manifest.json --latest`. Cualquiera puede descargar una release de un repositorio público: los
usuarios no necesitan cuenta ni token.

---

## 7. Tablero

### 7.1 Estructura

- `app.py`: configuración de página, logo, CSS, barra lateral con filtros (`selection.sidebar()` →
  `st.session_state['sel']`), versión de datos y avisos de actualización, `st.navigation` con
  Inicio, Ficha territorial y los cinco módulos (`views/*.py`). Las páginas se leen por URL:
  `/ficha`, `/demograficos`, `/salud_publica`, `/aseguramiento`, `/prestacion`, `/financiamiento`.
- `selection.py`: dataclass `Selection` (año, mes, departamento, municipio, filas actual y anterior de
  cada nivel, fila nacional) y los selectores.
- `data.py`: consultas cacheadas (`st.cache_data`, 1 h) sobre `metricas_*_periodo` / `_anterior` /
  `piramide_afiliados`, geojson y la lógica de actualización (7.3).
- `registry.py`: catálogo de indicadores (7.2).
- `ui.py`: componentes HTML/CSS: `kpi_card`, `card_grid`, `panel`, `chart`, `scale_html`,
  `progress_html`, `mini_donut_html`, `spark_svg`, `trend_box`, `module_header`, `footer`, `money`, `fmt`.
  Tarjetas de altura fija (`CARD_H = 262`), colores `_GOOD/_BAD/_FLAT`, barra lateral oscura con chips
  del color de cada módulo.
- `charts.py`: `map_location`, `map_municipios`, `donut_gender`, `donut_ips`, `ring_pct`,
  `pyramid_regimen` (Plotly `go.Choropleth` con proyección mercator y rangos explícitos; sin teselas
  externas, funciona sin internet).

### 7.2 Catálogo de indicadores (`registry.py`)

Cada indicador es un `Indicator(key, label, col, unit, decimals, icon, lower_is_better, trend, source,
period_col, dept_only, pending, fallback)`:

| Campo | Uso |
|---|---|
| `col` | Columna de `metricas_*`. `None` = fuente pendiente (tarjeta gris con el texto `pending`) |
| `lower_is_better` | `True`/`False` colorea la tendencia; `None` = sin dirección (ámbar) |
| `trend` | `pct` cambio relativo, `pp` diferencia en puntos, `abs` diferencia en unidades, `''` sin tendencia |
| `source` | Clave de `SRC` (texto de la fuente en el tooltip y el pie) |
| `period_col` | Columna con la etiqueta "Datos: …" |
| `dept_only` | Sin valor municipal: se muestra el departamental con nota |
| `fallback` | `(columna, columna_periodo, nota)` alternativa si `col` no tiene valor (p. ej. tasa del boletín cuando SIVIGILA no tiene el año) |

Listas `DEMOGRAFICOS`, `SALUD_PUBLICA` (11), `ASEGURAMIENTO` (7) + `SISBEN` (4), `PRESTACION` (4) +
`IPS_INTERV` + `CAPACIDAD` (5), `FINANCIAMIENTO` (11); `FICHA` define qué tarjetas lleva cada franja de
la Ficha; `MODULES` da título, color e icono de cada módulo.

**Para agregar un indicador:** (1) calcular la columna en `metricas.py` en los tres niveles (y en
`_anterior` si tiene tendencia); (2) declararlo en la lista del módulo en `registry.py`; (3) la vista
del módulo lo dibuja con `card_grid`/`kpi_card` (numeración por posición); (4) si procede, un control
de rango en `quality.py`; (5) `pipeline/exportar.py` no cambia (exporta tablas completas).

### 7.3 Origen de datos y actualización automática (`data.py`)

Orden de resolución de la base a leer:

1. `INFORME_DB_PATH` (archivo explícito; sin actualización).
2. `data/informe_regional.duckdb` si existe (equipo del operador; muestra la base recién construida).
3. La base del visor `INFORME_DATA_DIR/informe_regional_visor.duckdb` (por defecto `app/data/`), que
   se actualiza al abrir la aplicación y cada 6 horas si sigue abierta, consultando en este orden:
   - **A1, carpeta propia** `data/actualizacion/`: cualquier `*.duckdb` que sea una base del visor con
     versión mayor se instala (copia a `.part`, verificación, `os.replace` atómico). Los archivos de
     esa carpeta que son bases del visor se borran tras mirarlos, sean nuevos o no; lo que no es una
     base se deja.
   - **A2, carpeta compartida** (`[tablero] carpeta_actualizacion`, p. ej. la biblioteca de SharePoint
     sincronizada con OneDrive donde publica el operador): igual, pero **solo lectura**: nunca borra ni
     escribe en ella. Si la carpeta no existe (OneDrive sin sincronizar), se omite.
   - **B, URL** (`[tablero] url_actualizacion`): descarga `manifest.json` (tiempo máximo 8 s); si la
     versión publicada es mayor, descarga la base por bloques, comprueba el **SHA-256** y la instala.
   - La versión mayor gana; nunca se instala una versión igual o menor. Cualquier fallo (sin red, URL
     bloqueada, carpeta sin sincronizar, archivo dañado o a medio copiar, base bloqueada por otra
     ventana, error de sintaxis en el TOML) deja la copia actual y se informa en la barra lateral ("No
     se pudo comprobar si hay datos más recientes", con el detalle en el tooltip).
   - Sin base, o con una base dañada, la página muestra las instrucciones y se detiene.

Las funciones cacheadas no dibujan elementos de Streamlit (lo harían en cada acierto de caché); el
resultado de la comprobación queda en `_STATUS` y `app.py` muestra el aviso una vez por sesión.

Variables de entorno del tablero (tienen prioridad sobre `informe_regional.toml`): `INFORME_DB_PATH`,
`INFORME_DATA_DIR`, `INFORME_UPDATE_DIR`, `INFORME_RELEASE_URL`, `INFORME_GITHUB_REPO`.

### 7.4 Tema y estilo

`.streamlit/config.toml`: tema claro con el verde Supersalud (`#0B5D5E`), barra de herramientas
mínima. Los colores de módulo viven en `registry.MODULES`; el resto del CSS en `ui.inject_css()`.

### 7.5 Pruebas

No hay suite formal; las comprobaciones usadas en el desarrollo (y recomendadas antes de entregar):

- Cada página con `streamlit.testing.v1.AppTest` (sin navegador): cargar `dashboard/app.py`,
  `switch_page` a cada vista, `run()` y comprobar `at.exception` vacío; también con un municipio
  seleccionado.
- Los escenarios de actualización: sin base y sin internet, archivo nuevo en `actualizacion/`, archivo
  viejo, archivo que no es una base, base dañada. Se simulan con `INFORME_DATA_DIR` en una carpeta
  temporal, `INFORME_RELEASE_URL` apuntando a un puerto cerrado y versiones modificadas en
  `_visor_info`.
- `python -m pipeline.quality` sobre la base construida.

---

## 8. Distribución

### 8.1 Versión portable (`tools/build_portable.py`)

`.venv\Scripts\python.exe tools\build_portable.py` genera `dist/InformeRegional/` y
`dist/InformeRegional_<versión>.zip`:

1. Descarga el Python embebido 3.12 de python.org y habilita `site-packages`.
2. Instala `requirements.txt` con `pip --target`, con las dependencias fijadas a las versiones exactas del
   `.venv` (`pip freeze` como *constraints*): un Starlette o Uvicorn más nuevo que el que espera
   Streamlit sirve páginas en blanco.
3. Recorta lo que el visor no carga: tests, cabeceras C, `pyarrow`, `pydeck`, `altair`, extensiones Jupyter de
   Plotly, demos de Streamlit (cada página se ejecutó sin ellos para comprobarlo).
4. Copia `dashboard/`, `.streamlit/`, la base actual de `data/dist/`, el manual de usuario en Word, y
   crea `abrir.py` (elige el primer puerto libre desde 8765), `app/informe_regional.toml` (sección
   `[tablero]`, editable con el Bloc de notas), `Abrir Informe Regional.bat` y `LEEME.txt`.

```
InformeRegional/
  Abrir Informe Regional.bat
  LEEME.txt
  Manual de usuario.docx
  python/                        intérprete + paquetes
  app/
    abrir.py
    informe_regional.toml        carpeta compartida y URL de actualización
    .streamlit/config.toml
    dashboard/
    data/informe_regional_visor.duckdb
    data/actualizacion/          carpeta de actualización manual
```

Solo hace falta un zip nuevo cuando cambia el **código** del tablero; los datos llegan solos. No
requiere administrador, no modifica el registro ni instala nada.

### 8.2 Publicación en SharePoint

Estructura recomendada en el sitio de SharePoint de la entidad:

```
Informe Regional/
  Tablero/     InformeRegional_<versión>.zip, MANUAL_USUARIO.docx
  Datos/       informe_regional_visor.duckdb + manifest.json   (los deja publicar_datos.py cada mes)
```

1. **Antes de distribuir**, abrir `app\informe_regional.toml` del paquete y escribir en
   `carpeta_actualizacion` la ruta local con la que OneDrive sincroniza `Datos/` en los equipos de los
   usuarios (por ejemplo `C:/Users/<usuario>/<Entidad>/Informe Regional - Datos`; se admiten `~` y
   variables como `%OneDrive%`). Si la entidad no usa GitHub, dejar `url_actualizacion = ""`. Volver a
   comprimir la carpeta `InformeRegional` o regenerar el zip con `build_portable.py` después de cambiar
   la plantilla `CONFIG`.
2. Subir el zip y el manual a `Tablero/`. Los usuarios lo descargan, lo descomprimen en una carpeta
   local (no en OneDrive ni en una unidad de red) y abren el `.bat`.
3. En el equipo del operador, `informe_regional.toml` → `[publicacion] carpeta` apunta a su copia
   sincronizada de `Datos/`. Cada mes `Actualizar datos.bat` deja ahí la base nueva y todos los tableros
   la instalan al abrirse.
4. **Primer arranque en un equipo de la entidad:** Windows marca los archivos descargados (SmartScreen:
   "Más información → Ejecutar de todas formas"). Si la política de la entidad bloquea `.bat` o
   ejecutables sin firma, pedir a TI que permita la carpeta `InformeRegional` (es Python oficial de
   python.org sin modificar; no requiere administrador). Probar en un equipo de la entidad antes de
   anunciarlo.

### 8.3 Actualización de datos: protocolo

```
operador                                  canal                              tablero del usuario
pipeline/exportar ──► manifest.json {version, archivo, sha256, bytes, generado}
tools/publicar_datos ──► carpeta compartida (SharePoint/OneDrive) ──► al abrir: ¿versión mayor? copiar, verificar, instalar
                    └──► release GitHub datos-<versión>           ──► al abrir: GET manifest; ¿mayor? GET base, SHA-256, instalar
```

La versión es `AAAA.MM.DD-HHMM`, así que "mayor" equivale a "más reciente". Cualquier servidor web
que sirva los dos archivos en una URL fija sirve como canal B (`url_actualizacion`); la carpeta
`actualizacion/` del propio tablero queda como último recurso (USB, correo).

---

## 9. Mantenimiento y extensión

### 9.1 Agregar una fuente nueva

1. **Scraper** `scrapers/<fuente>_scraper.py` con `run(base_dir=None)` que escriba
   `data/parquet/<fuente>_<sello>.parquet` y lance `ScrapeError` si no puede actualizar. Reutilizar los
   patrones existentes: sello por periodo, re-descarga por `rowsUpdatedAt`/`Modified`, reintentos.
2. **Runner:** agregar `(fuente.run, '<fuente>')` a la lista del ciclo que corresponda.
3. **Transform:** cargar el parquet en una tabla (cargador genérico de `transform_financiamiento` si
   basta un `read_parquet` con `union_by_name`).
4. **Geo:** declarar la tabla en `geo_normalize.GEO_SOURCES` (con código o por nombre) o en
   `CODE_FIRST_SOURCES`, para obtener `v_<tabla>` con códigos DANE.
5. **Métricas:** CTE en `metricas.py` para municipio, departamento y nación; corte en
   `_resolve_caps` si la fuente tiene periodicidad propia; etiqueta `periodo_<fuente>`.
6. **Calidad:** cruce geográfico, frescura, rango y la tabla en `_TRACKED`.
7. **Registro y vista:** `Indicator` en `registry.py`, clave en `SRC`, tarjeta en la vista.
8. Documentar la fuente en este manual (sección 5).

### 9.2 Cuando una fuente cambia de formato

El síntoma habitual es un `ScrapeError` que nombra la columna, hoja o URL no encontrada, o un control
de calidad que falla. Cada ficha de la sección 5 indica la constante o función que hay que ajustar.
Después: `python -m pipeline.runner --monthly` (o solo el scraper: `python -c "import
scrapers.<x> as s; s.run()"`) y `python -m pipeline.runner --transform-only`.

### 9.3 Paquete de entrega e instalación desde el código fuente

El equipo de soporte recibe el sistema como paquete, no como acceso a un repositorio.
`tools/build_entrega.py` (tras `build_docs.py` y `build_portable.py`, con todo confirmado en git)
genera `dist/Entrega_<fecha>/`:

| Archivo | Contenido |
|---|---|
| `codigo_fuente_<fecha>_<commit>.zip` | El repositorio en ese commit (`git archive`): código, documentación, plantilla de configuración. Sin datos, sin `informe_regional.toml`, sin la maqueta del cliente |
| `InformeRegional_<versión>.zip` | Tablero portable para los usuarios |
| `MANUAL_USUARIO.*`, `MANUAL_TECNICO.*` | Manuales en Word y Markdown |
| `datos_historicos_parquet_<fecha>.zip` | `data/parquet/`: todo lo descargado hasta la fecha. **Conservarlo**: las fotos mensuales de BDUA, REPS y Supersalud no se pueden volver a descargar; el resto se regenera |
| `LEEME_ENTREGA.txt` | Contenido y primeros pasos |

**Instalación desde el zip de código** (sin git):

1. Descomprimir `codigo_fuente_*.zip`; descomprimir `datos_historicos_parquet_*.zip` dentro, en
   `data\parquet\`.
2. Python 3.12 + Chrome; `Preparar equipo.bat`.
3. `informe_regional.example.toml` → `informe_regional.toml`; fijar `[publicacion] carpeta` (y/o `repo`).
4. `python -m pipeline.runner --transform-only` reconstruye la base desde los parquet;
   `streamlit run dashboard\app.py` la muestra. A partir de ahí, el ciclo mensual (sección 4).

**Llevar el código al repositorio de la entidad** (GitHub, GitLab, Azure DevOps): descomprimir el zip
en un repositorio nuevo y confirmar. Si se publican los datos por release de GitHub, cambiar
`[publicacion] repo` en el operador y `url_actualizacion` en la plantilla `CONFIG` de
`build_portable.py` (y en el `app\informe_regional.toml` de los tableros ya entregados). Si se publica
por SharePoint, no hay nada que cambiar en el código.

### 9.4 Reproducir el sistema en otro escenario

- **Otra entidad u otro conjunto de indicadores:** cambiar `registry.py` (indicadores, módulos,
  colores, fuentes) y las vistas; el resto no depende de la FCT.
- **Otro territorio o país:** el maestro geográfico sale de la fuente demográfica
  (`geo_normalize._build_geo_maestro`); los mapas, de `build_geojson.py`; los alias de nombres, de
  `DEPT_ALIASES`/`MUN_ALIASES`. Los scrapers son específicos de cada fuente y se reemplazan.
- **Otro canal de publicación:** `publicar_datos.py` y `[tablero] url_actualizacion`; el protocolo solo
  necesita un `manifest.json` y el archivo en una URL fija o en una carpeta compartida.
- **Servidor en lugar de portable:** el tablero corre con `streamlit run dashboard/app.py` en cualquier
  equipo con `requirements.txt`; `INFORME_DB_PATH` fija la base.

### 9.5 Dependencias

Las versiones están fijadas en `requirements.txt` (visor) y `requirements-pipeline.txt`. Para
actualizar: cambiar la versión, `pip install -r requirements-pipeline.txt`, reconstruir
(`--transform-only`), comprobar que las métricas no cambian, ejecutar las páginas con AppTest y
regenerar el zip. `duckdb` debe ser la misma versión en ambos archivos (la base la escribe el
pipeline y la lee el visor).

### 9.6 Datos personales y seguridad

- Ninguna tabla guarda personas: SIVIGILA se agrega por municipio y semana; Supersalud descarta
  representante legal, cédula, correo y teléfono; BDUA llega agregada por el servidor.
- Del tablero público de Power BI del INS solo se consulta la tabla rutinaria; otros modelos del INS
  exponen datos personales y **no deben consultarse**.
- El repositorio es público: no subir `data/`, `informe_regional.toml`, bases `.duckdb` ni
  `docs/reference/DASHBOARD_FCT.docx` (maqueta del cliente). `.gitignore` ya los excluye.
- La base del visor contiene solo agregados; es pública por diseño (release de GitHub).

---

## 10. Solución de problemas

| Síntoma | Causa probable | Acción |
|---|---|---|
| `irca: SIVICAP no entregó datos (probable reCAPTCHA)` | Sesión guardada vencida | `Renovar sesion SIVICAP.bat` o CSV manual (4.4) |
| SIVICAP: "inicio de sesión no válida" en todos los navegadores | Usuario invitado deshabilitado por el INS | Reportar a Soporte del INS; CSV manual cuando vuelva |
| `SessionNotCreatedException: ChromeDriver only supports Chrome version X` | Driver cacheado desfasado | Borrar `%APPDATA%\undetected_chromedriver\` y reintentar |
| `reps: endpoints sin datos` | Cambió el sitio o tardó más del timeout | Repetir; si persiste, revisar `ENDPOINTS` |
| `INS [<evento>] PE_X_YYYY: no se encontraron tablas válidas` | El INS cambió el formato del PDF | Revisar el PDF y la entrada en `EVENTS`; desnutrición 2026 es esperado |
| `HTTP 401` en Supersalud | Cambió la URL del Excel | Actualizar `URL_IPS_XLSX` / `URL_EPS_XLSX` |
| Control `cuipo_codigo_divipola` falla | Municipio con código CGN `923…` nuevo | Agregarlo a `_CGN_DIVIPOLA` |
| Control `*_match_municipio` falla | Grafía nueva de un municipio | Agregar alias en `MUN_ALIASES` (con departamento) |
| Control `filas_<tabla>` ERROR | La fuente perdió o duplicó filas | Revisar el parquet nuevo; si es legítimo, publicar tras verificar |
| `publicar` falla con `.wal` | Transform cerró mal | Repetir `--transform-only` |
| `publicar` falla por archivo en uso | Un Streamlit abierto sobre la base del operador | Cerrarlo y repetir `--transform-only` |
| `publicar_datos.py`: falta `gh` o permiso | GitHub CLI no instalada o sin sesión | Instalarla y `gh auth login` |
| Un tablero no se actualiza | Carpeta compartida sin sincronizar, sin internet o URL bloqueada | Ver el tooltip de la barra lateral; revisar `app\informe_regional.toml`; actualización manual (8.3) |
| Portable: páginas en blanco | Versiones de Starlette/Uvicorn distintas de las probadas | Regenerar con `build_portable.py` (usa las versiones del `.venv`) |
| Portable: el navegador abre otra aplicación | Otro programa usa el puerto | `abrir.py` ya elige un puerto libre; copiar la URL de la ventana negra |

---

## 11. Referencias

- `docs/MANUAL_USUARIO.md` — manual del usuario del tablero.
- `docs/FINANCIAMIENTO_FORMULAS.md` — fórmulas de Financiamiento y supuestos por validar.
- `docs/FUENTES_INVESTIGACION_2026-10-13.md` — investigación de fuentes por indicador.
- `docs/PLAN_FCT_2026-10.md` — plan del diseño FCT.
- `docs/AUDITORIA_2026-10-13.md` — auditoría del código.
- `tools/build_docs.py` — genera las versiones Word de los manuales.
- `tools/build_entrega.py` — arma el paquete de entrega.

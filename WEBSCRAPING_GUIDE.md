# Informe Regional — Web Scraping System Documentation

## Overview

This document describes the automated web scraping and data pipeline system for the Colombian regional health report ("Informe Regional"). The system periodically collects data from multiple government sources, normalizes and transforms it, and stores it in a unified analytical database (DuckDB) with archival backups in Parquet format.

**Core Components:**
- **6 source-specific scrapers** in `scrapers/` — each handles authentication, download, and parsing
- **Unified transform pipeline** in `pipeline/transform.py` — normalizes all sources to consistent schemas
- **APScheduler orchestrator** in `pipeline/runner.py` — schedules monthly/annual runs or triggers on-demand

---

## Architecture

```
c:\dev\Informe regional v2\
├── scrapers/
│   ├── demografico.py           — DANE population projections (age/sex, ethnicity)
│   ├── reps_scraper.py          — 6 REPS endpoints (MinSalud health facilities)
│   ├── irca_scraper.py          — SIVICAP water quality index (INS)
│   ├── afiliacion_scraper.py    — Monthly affiliation summary (MinSalud ZIP)
│   ├── supersalud_scraper.py    — Intervened facilities (IPS + EPS, direct Excel)
│   └── ins_pdf_scraper.py       — 7 epidemiological indicators from PDFs
├── pipeline/
│   ├── transform.py             — Normalize all raw CSVs → Parquet + DuckDB
│   └── runner.py                — APScheduler orchestrator + CLI
├── data/
│   ├── raw/                     — Timestamped raw CSVs (downloads/scrapes)
│   ├── parquet/                 — Partitioned Parquet files (year/month)
│   └── informe_regional.duckdb  — Unified analytical database
└── requirements.txt             — Python dependencies
```

**Data Flow:**
```
Source (web/API) → Scraper → data/raw/*.csv → transform.py → Parquet + DuckDB
```

---

## Quick Start

### 1. Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Create data directories (auto-created by scrapers)
mkdir -p data/{raw,parquet}
```

### 2. Run All Scrapers & Transform

```bash
# Download all sources once, exit
python pipeline/runner.py --run-now

# Or run specific cycles
python pipeline/runner.py --monthly        # REPS + IRCA + Afiliación + transform
python pipeline/runner.py --annual         # DANE demographics + transform
python pipeline/runner.py --transform-only # Only transform, no scrapers
```

### 3. Start Scheduler

```bash
# Run indefinitely, trigger on schedule (5th of month @ 08:00, July 15 @ 08:00)
python pipeline/runner.py
```

---

## Data Sources

| Source | Scraper | Freq | Auth | Key Data |
|--------|---------|------|------|----------|
| DANE demographics | `demografico.py` | Yearly | None (public URLs) | Population by age/sex/ethnicity, 2018–2042 |
| REPS (6 endpoints) | `reps_scraper.py` | Monthly | Guest button | Health facilities, locations, services, capacity, safety measures, sanctions |
| IRCA water quality | `irca_scraper.py` | Monthly | invitado@ins.gov.co / 123456 | Municipal water quality index + risk levels |
| Affiliation summary | `afiliacion_scraper.py` | Monthly | None (public ZIP) | Health plan enrollment by department/municipality |
| Intervened facilities | `supersalud_scraper.py` | Monthly | None (direct Excel) | IPS and EPS under government intervention |
| Epidemiological indicators | `ins_pdf_scraper.py` | Monthly/Quarterly | None (direct PDFs) | 7 indicators: maternal mortality, congenital syphilis, malnutrition, child mortality, dengue, suicide attempts, gender violence |

---

## Scrapers in Detail

### 1. demografico.py — DANE Population Projections

**Sources:**
- Age/sex: `https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Municipal/PPED-AreaSexoEdadMun-2018-2042_VP.xlsx`
- Ethnicity: `https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Nacional/anex-DCD-Proypoblacion-PerteneniaEtnicoRacialmun.xlsx`

**Key Functions:**
- `detect_header_rows()` — Finds header row(s) in merged-header Excel layouts
- `fuse_headers()` — Combines multi-level headers into single row
- `normalize_name()` — Removes BOM, NBSP, normalizes Unicode (NFKC)

**Process:**
1. Download Excel files via Polars `read_excel()` with custom header detection
2. Filter by valid department codes (DP ≠ null, ÁREA GEOGRÁFICA doesn't contain "Total")
3. Melt wide age/sex columns to tidy long format
4. Extract sex and age from column names using regex
5. Output 3 CSVs: `pped_tidy.csv`, `pper_tidy.csv`, `resumen_demografico.csv`

**Output Schema:**
```
pped_tidy:
  DP | DPNOM | MPIO | DPMP | AÑO | ÁREA GEOGRÁFICA | SEXO | EDAD | POBLACION

pper_tidy:
  DP | DPNOM | MPIO | DPMP | AÑO | ÁREA GEOGRÁFICA | GRUPO | POBLACION

resumen_demografico:
  DP | DPNOM | AÑO | Total hombres | Total mujeres | Total población | Total municipios
```

**Known Issues:**
- DANE servers are slow; may timeout on poor connections
- Multi-level header detection is fragile; if DANE changes Excel layout, may break

---

### 2. reps_scraper.py — Health Facilities (6 Endpoints)

**Source:** `https://prestadores.minsalud.gov.co/habilitacion/`

**6 Endpoints:**
- `prestadores.aspx` — Facility master data (name, ID, location, type)
- `sedes.aspx` — Facility locations/branches
- `servicios.aspx` — Services offered per facility
- `capacidad.aspx` — Bed capacity and resources
- `medidas_seguridad.aspx` — Safety/biosafety measures
- `sanciones.aspx` — Regulatory sanctions history

**Key Functions:**
- `_safe_limpiar()` — Robustly clean malformed rows in pipe-delimited CSV
- Reuses single Selenium login across all 6 queries (efficient)

**Process:**
1. Start headless Chrome with download dir configured
2. Navigate to login page, click guest button
3. For each endpoint: navigate to query page, set separator to `|`, click download
4. Wait for CSV file to appear (`esperar_descarga()`)
5. Parse with robust row-matching (handles uneven field counts)
6. Output `data/raw/reps_<endpoint>_YYYY_MM.csv`

**Output Format:** Pipe-delimited `|`, UTF-8, single header row

**Known Issues:**
- `servicios` endpoint times out on slow connections (network issue, not code)
- Guest login occasionally requires additional modal closing (handled via JavaScript injection)

---

### 3. irca_scraper.py — Water Quality Index (SIVICAP)

**Source:** `https://sivicap.ins.gov.co/` (authentication required)

**Credentials:** `invitado@ins.gov.co` / `123456`

**Key Features:**
- CAPTCHA fallback: if download blocked, checks `data/raw/` for file ≤30 days old and uses it
- Handles Unicode normalization (NFKC)
- Infers separator (`;` or `|`) and encoding (latin1 or utf-8)

**Process:**
1. Start headless Chrome
2. Navigate to login, enter credentials
3. Navigate to municipal report page
4. Try to download CSV export
5. **If CAPTCHA appears:** Check `data/raw/` for recent file (< 30 days old)
   - If found: use it, log warning
   - If not found: log error, skip download
6. Parse CSV with multiple (separator, encoding) attempts
7. Output `data/raw/irca_YYYY_MM.csv`

**Output Schema:**
```
anio | mes | codigo_dep | nombre_dep | codigo_mun | municipio | 
n_muestras | promedio_irca | nivel_riesgo | 
n_muestras_urbano | promedio_irca_urbano | nivel_riesgo_urbano | 
n_muestras_rural | promedio_irca_rural | nivel_riesgo_rural
```

**Fallback Behavior Example:**
```
2026-04-27 10:15:22 WARNING: IRCA CAPTCHA detected, checking for fallback file...
2026-04-27 10:15:23 INFO: Using cached file: data/raw/irca_2026_03.csv (25 days old)
```

---

### 4. afiliacion_scraper.py — Monthly Enrollment Summary

**Source:** MinSalud monthly ZIP files
```
https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/RBC/
  cifras-afiliacion-salud-{mes}-{year}.zip
```

**Key Features:**
- Auto-detects month/year from system date
- Handles Excel files with title rows (CoberturaMunicipio sheet)
- Fallback: if current month's ZIP unavailable, uses cached version

**Process:**
1. Construct ZIP URL for current month
2. Download with `requests`
3. Extract inner Excel file
4. Read `CoberturaMunicipio` sheet
5. Detect unnamed columns → promote row 0 to header, slice row 1 onward
6. Normalize column names (remove BOM/NBSP)
7. Output `data/raw/afiliacion_YYYY_MM.csv`

**Output Schema:**
```
anio | mes | departamento | municipio | regimen | entidad | afiliados
```

**Known Issues:**
- If MinSalud changes ZIP URL pattern, scraper breaks
- Excel file structure with title rows is fragile

---

### 5. supersalud_scraper.py — Intervened Facilities

**Source:** Direct Excel downloads from `docs.supersalud.gov.co`
- IPS Intervenidas: `https://docs.supersalud.gov.co/.../?/ips_intervenidas.xlsx`
- EPS Intervenidas: `https://docs.supersalud.gov.co/.../?/eps_intervenidas.xlsx`

**Key Features:**
- Fallback to `openpyxl` when `fastexcel` fails on decompression errors
- Auto-detects header row (first row with 3+ non-null strings)

**Process:**
1. For each file (IPS, EPS):
   - Try: download + read with Polars `fastexcel` engine
   - Except: fall back to `openpyxl` + manual DataFrame construction
2. Auto-detect header row
3. Normalize columns and filter out empty rows
4. Output `data/raw/supersalud_[ips|eps]_intervenidas_YYYY_MM.csv`

**Output Schema:**
```
Radicado | Entidad | Naturaleza | Departamento | Municipio | 
Motivo_Intervencion | Fecha_Resolucion | Estado
```

**Fallback Example:**
```
2026-04-27 10:20:45 WARNING: fastexcel decompression failed, using openpyxl fallback
2026-04-27 10:20:46 INFO: Successfully read IPS with openpyxl
```

---

### 6. ins_pdf_scraper.py — Epidemiological Indicators

**Source:** INS `epidemiologia.minsalud.gov.co` PDF reports

**7 Indicators:**
1. Mortalidad Materna (p3, col 3)
2. Sífilis Congénita (p1, col 1)
3. Desnutrición Aguda (p2, col 3)
4. Mortalidad Menores 5 (p2, col 1)
5. Dengue (p4, col 1)
6. Intento de Suicidio (p2, col 2)
7. Violencia de Género (p2, col 1)

**Key Features:**
- Dynamic URL construction with period enum (ROMAN = ['I'...'XIII'] for quarters)
- Fallback to previous period if current unavailable
- `pdfplumber` for table extraction with tolerance for formatting variations
- Period detection via filename regex

**Process:**
1. For each indicator:
   - Construct URL with current period (calculated from current month)
   - Try to download + extract table from specific page/column
   - If fails: try previous period
   - If still fails: log warning, skip
2. Parse table with `pdfplumber`, normalize column names
3. Group by department/municipality
4. Output `data/raw/ins_<evento>_PE_<ROMAN>_<year>.csv`

**Output Schema:**
```
periodo | anio | evento | departamento | municipio | valor | tasa
```

**URL Example:**
```
# For Q1 2026:
https://www.epidemiologia.gov.co/inicio/.../PERIODOI-2026.pdf
```

**Known Issues:**
- INS servers are slow, frequently timeout on this machine (network, not code)
- PDF structure varies by indicator; table extraction is fragile
- Column indices (p3:col3, p2:col1) are hardcoded; if INS changes layout, must update manually

---

## Transform Pipeline (pipeline/transform.py)

**Purpose:** Normalize all raw CSVs to consistent schemas, write Parquet + register DuckDB tables

**Key Characteristics:**
- Uses Polars lazy API for efficient processing
- Partitions output by year/month
- Auto-creates DuckDB tables
- Handles missing columns gracefully

**Process per Source:**

### demografico
```python
def transform_demografico(base_dir):
    # Load pped_tidy.csv, pper_tidy.csv, resumen_demografico.csv
    # Rename columns: DP→codigo_dep, DPNOM→nombre_dep, AÑO→anio
    # Write Parquet: data/parquet/demografico/year={anio}/demografico.parquet
    # Register DuckDB table: demografico
```

### reps (6 endpoints)
```python
def transform_reps(base_dir):
    # Load all reps_*_YYYY_MM.csv files
    # For each endpoint: rename common columns, write partitioned Parquet
    # Register 6 DuckDB tables: reps_prestadores, reps_sedes, etc.
```

### irca
```python
def transform_irca(base_dir):
    # Load irca_YYYY_MM.csv
    # Try separators: |, ;, , with encodings: utf-8, latin1
    # Rename: codigo_dep, nombre_dep, codigo_mun, municipio, anio, mes
    # Write: data/parquet/irca/year={anio}/month={mes}/irca.parquet
    # Register: irca
```

### afiliacion
```python
def transform_afiliacion(base_dir):
    # Load afiliacion_YYYY_MM.csv
    # Rename: departamento→nombre_dep, anio, mes
    # Write: data/parquet/afiliacion/year={anio}/month={mes}/afiliacion.parquet
    # Register: afiliacion
```

### supersalud
```python
def transform_supersalud(base_dir):
    # Load supersalud_[ips|eps]_intervenidas_YYYY_MM.csv
    # Rename: Departamento→nombre_dep, Municipio→municipio
    # Write: data/parquet/supersalud_*/year={anio}/month={mes}/...parquet
    # Register: supersalud_ips, supersalud_eps
```

### ins_pdf
```python
def transform_ins_pdf(base_dir):
    # Load all ins_*.csv files
    # Group by evento, rename columns
    # Write: data/parquet/ins_<evento>/year={anio}/...parquet
    # Register 7 tables: ins_mortalidad_materna, ins_sifilis_congenita, ...
```

---

## Orchestration (pipeline/runner.py)

**Scheduler:** APScheduler BlockingScheduler with timezone `America/Bogota`

### Scheduled Jobs

```
Every 5th of month @ 08:00  →  run_monthly()
    ├─ reps_scraper.run()
    ├─ irca_scraper.run()
    ├─ afiliacion_scraper.run()
    ├─ supersalud_scraper.run()
    ├─ ins_pdf_scraper.run()
    └─ transform.run()

Every July 15 @ 08:00      →  run_annual()
    ├─ demografico.run()
    └─ transform.run()
```

### CLI Modes

```bash
python pipeline/runner.py                # Start scheduler, run on schedule (blocking)
python pipeline/runner.py --run-now      # Run all scrapers once, exit
python pipeline/runner.py --monthly      # Run only monthly cycle, exit
python pipeline/runner.py --annual       # Run only annual cycle (demographics), exit
python pipeline/runner.py --transform-only  # Run only transform, no scrapers, exit
```

### Error Handling

All scraper calls wrapped in `_safe()` wrapper:
```python
def _safe(fn, name: str) -> None:
    try:
        log.info(f'>>> Iniciando: {name}')
        fn(base_dir=str(BASE_DIR))
        log.info(f'<<< Completado: {name}')
    except Exception:
        log.error(f'!!! Error en {name}:\n{traceback.format_exc()}')
        # Pipeline continues, doesn't crash on single scraper failure
```

**Logging Output:**
```
2026-04-27 08:00:00 INFO     === Ciclo mensual ===
2026-04-27 08:00:01 INFO     >>> Iniciando: reps_scraper
2026-04-27 08:10:45 INFO     <<< Completado: reps_scraper
2026-04-27 08:10:46 INFO     >>> Iniciando: irca_scraper
2026-04-27 08:15:22 WARNING  IRCA CAPTCHA detected, using cached file
2026-04-27 08:15:23 INFO     <<< Completado: irca_scraper
...
2026-04-27 08:45:00 INFO     === Ciclo mensual completado ===
```

---

## Dependencies

**File:** `requirements.txt`

```
polars              # Data processing (pandas removed due to environment corruption)
duckdb              # Analytical database
apscheduler         # Scheduling
selenium            # Web browser automation
openpyxl            # Excel fallback reader
requests            # HTTP downloads
fastexcel           # Fast Excel reader (with openpyxl fallback)
pdfplumber          # PDF table extraction
urllib3             # HTTP utilities
```

**Why no pandas?**
- Corrupted zlib installation in Python 3.14 environment causes decompression errors
- All code refactored to use Polars exclusively
- openpyxl used as direct fallback for Excel when needed

---

## Data Quality & Normalization

### Common Transformations Applied to All Sources

1. **Unicode Normalization (NFKC)**
   - Removes BOM (U+FEFF)
   - Converts NBSP (U+00A0) to space
   - Normalizes accented characters

2. **Column Name Standardization**
   ```python
   # Common renames across all sources:
   DP / codigo_dep → codigo_dep
   DPNOM / nombre_dep → nombre_dep
   MPIO / codigo_mun → codigo_mun
   AÑO / anio → anio
   MES / mes → mes (where applicable)
   ```

3. **Type Coercion**
   - `codigo_dep`, `codigo_mun` → Int32/Int64
   - `anio`, `mes` → Int32
   - Numeric fields (población, afiliados, etc.) → Int64
   - Dates → handled per-source (some sources don't have explicit dates)

4. **Missing Value Handling**
   - Null codes are removed (e.g., DP = null rows dropped)
   - Text "Total" excluded from geographic filters
   - Missing numeric fields filled with 0 or null depending on context

---

## DuckDB Integration

### Automatic Table Registration

After transform completes, each source is available as a DuckDB table:

```sql
SELECT COUNT(*) FROM demografico;
SELECT * FROM irca WHERE nombre_dep = 'Bogotá';
SELECT anio, mes, SUM(afiliados) FROM afiliacion GROUP BY anio, mes;
SELECT * FROM reps_prestadores WHERE nombre_dep LIKE '%Antioquia%';
```

### Schema Discovery

```bash
# List all tables
duckdb data/informe_regional.duckdb "SELECT * FROM information_schema.tables;"

# Inspect table structure
duckdb data/informe_regional.duckdb "DESCRIBE demografico;"
duckdb data/informe_regional.duckdb "DESCRIBE irca;"
```

### Querying from Python

```python
import duckdb
conn = duckdb.connect('data/informe_regional.duckdb')
result = conn.execute("SELECT * FROM irca LIMIT 10").fetch_all()
conn.close()
```

---

## Known Issues & Workarounds

### 1. Demografico DANE Header Detection
**Status:** ⚠️ Fragile

**Issue:** DANE Excel files have merged headers. Polars `read_excel()` doesn't automatically detect multi-level headers like pandas did.

**Current Approach:**
- `detect_header_rows()` scans for rows containing 'DP', 'COD_DPTO', or 'DEPARTAMENTO'
- `fuse_headers()` merges multi-level headers into single row
- Works for current DANE files but may break if DANE changes Excel structure

**If It Breaks:**
- Check DANE Excel file manually (open in Excel, inspect header rows)
- Update `key_any` tuple in `detect_header_rows()` with new column names
- Adjust `fuse_headers()` logic if multi-level structure changed

### 2. IRCA CAPTCHA Blocking
**Status:** ✓ Handled

**Issue:** SIVICAP frequently shows CAPTCHA that Selenium can't solve.

**Solution:** Fallback to cached file
- If CAPTCHA detected and download fails, check `data/raw/` for file ≤30 days old
- Uses cached file with warning log
- If no recent cached file, logs error but pipeline continues (doesn't crash)

**Manual Workaround:**
- Download IRCA CSV manually from `https://sivicap.ins.gov.co/`
- Save to `data/raw/irca_YYYY_MM.csv`
- Run transform: `python pipeline/runner.py --transform-only`

### 3. Supersalud Excel Decompression
**Status:** ✓ Handled

**Issue:** Some SuperSalud Excel files can't be decompressed by `fastexcel` (zlib error).

**Solution:** Fallback to `openpyxl`
- Tries Polars `read_excel()` with `fastexcel` engine first
- On any exception: silently falls back to `openpyxl`
- Both read to DataFrame, unified downstream processing

### 4. INS PDF Server Timeouts
**Status:** ⚠️ Network-dependent

**Issue:** INS `epidemiologia.minsalud.gov.co` servers are slow, often timeout from this machine.

**Current Behavior:**
- Attempts to download current period
- If timeout: retries previous period
- If both fail: logs warning, skips indicator

**Manual Workaround:**
- Download PDF manually from `https://www.epidemiologia.gov.co/`
- Place in `data/raw/`
- Run: `python pipeline/runner.py --transform-only`

### 5. REPS Servicios Endpoint Timeout
**Status:** ⚠️ Network-dependent

**Issue:** `servicios.aspx` endpoint occasionally times out on slow connections.

**Handling:**
- Wrapped in `_safe()`, doesn't crash pipeline
- Logs error and continues with other REPS endpoints
- Manual re-run usually succeeds

---

## Maintenance

### Adding a New Source

1. **Create scraper:** `scrapers/new_source.py`
   ```python
   def run(base_dir: str = None) -> None:
       base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
       raw_dir = base_dir / 'data' / 'raw'
       raw_dir.mkdir(parents=True, exist_ok=True)
       
       # Download/scrape
       # Parse with Polars
       # Output: data/raw/new_source_YYYY_MM.csv (pipe-delimited, UTF-8)
   ```

2. **Add to runner.py:**
   ```python
   def run_monthly() -> None:
       # ...existing...
       _safe(new_source.run, 'new_source')
   ```

3. **Add transform function:** `pipeline/transform.py`
   ```python
   def transform_new_source(base_dir):
       # Load raw CSV, normalize columns, write Parquet, register DuckDB table
   ```

4. **Call from transform.py `run()`:**
   ```python
   def run(base_dir: str = None) -> None:
       # ...existing...
       transform_new_source(base_dir)
   ```

### Updating Column Names

If a source changes structure:
1. Check raw CSV: `data/raw/<source>_YYYY_MM.csv`
2. Update column name mapping in `transform.py`
3. Re-run transform: `python pipeline/runner.py --transform-only`

### Debugging a Scraper

```bash
# Run scraper directly (skips scheduler)
python scrapers/irca_scraper.py

# Check output
ls -lah data/raw/ | grep irca

# Inspect raw data
head -5 data/raw/irca_2026_04.csv

# Check logs for errors
grep ERROR data/raw/ 2>&1 | tail -20
```

### Querying DuckDB Tables

```bash
# Interactive mode
duckdb data/informe_regional.duckdb

# Within REPL:
SELECT COUNT(*) FROM irca;
SELECT DISTINCT nombre_dep FROM demografico ORDER BY nombre_dep;
SELECT * FROM afiliacion WHERE mes = 4 AND anio = 2026;
```

---

## Performance Notes

### Memory Usage
- Polars processes CSVs in lazy chunks (doesn't load full file into memory)
- Large tables (e.g., reps_prestadores with 60k+ rows) process efficiently
- DuckDB queries use columnar format, excellent for analytics

### Download Time
- DANE Excel files: ~30 seconds each
- REPS 6 endpoints: ~5 minutes total (Selenium + waits)
- IRCA: ~2 minutes (including CAPTCHA detection)
- Afiliación ZIP: ~30 seconds
- SuperSalud Excel: ~1 minute
- INS PDFs: ~3 minutes (or timeout)
- **Total monthly cycle:** ~12 minutes (assuming no timeouts)

### Storage
- `data/raw/`: ~500 MB (all CSVs for ~2 years)
- `data/parquet/`: ~200 MB (compressed columnar)
- `informe_regional.duckdb`: ~100 MB (indices + data)

---

## Future Enhancements

1. **Dash Dashboard** — Interactive scrolly-telling dashboard covering all departments/municipalities
   - Currently designed to support this with normalized DuckDB tables
   - Tables have consistent department/municipality codes for joins

2. **Additional Indicators** — 20+ more scrapers available in `informe_regional.xlsx`
   - Follow same pattern: `scrapers/<new>.py`, add to runner.py and transform.py

3. **Data Quality Metrics** — Row count tracking, null percentage alerts
   - Could log to a separate `data/quality_log.csv` for monitoring

4. **Incremental Updates** — Currently re-processes all months; could optimize to append-only
   - Useful once historical backlog is complete

---

## Support

**Common Issues:**

| Issue | Solution |
|-------|----------|
| "ModuleNotFoundError: No module named 'polars'" | `pip install -r requirements.txt` |
| "FileNotFoundError: data/raw/ does not exist" | Auto-created by scrapers; run one scraper first |
| Selenium timeout | Network issue; retry or run scrapers manually and transform only |
| "IRCA CAPTCHA detected" | Expected; using cached file fallback (check log) |
| DuckDB "table not found" | Run `python pipeline/runner.py --run-now` to populate tables |

**Logs:**
- Visible in console when running `python pipeline/runner.py`
- Logged to stdout/stderr (can redirect to file if needed)

---

**Last Updated:** 2026-04-27  
**System:** Informe Regional v2  
**Python:** 3.12+ (Polars, DuckDB, APScheduler, Selenium)

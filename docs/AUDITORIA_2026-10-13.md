# Code audit: Informe Regional de Salud

**Date:** 2026-10-13
**Scope:** all code in `scrapers/`, `pipeline/`, `dashboard/`, `tools/`, the deploy and infra files, and the git history (about 7,500 lines).
**Method:** four parallel read-only reviews (scrapers, pipeline + DB, dashboard, infra/security). Each finding was checked against the code. The top findings were re-checked with queries against `data/informe_regional.duckdb`. No files were changed.

---

## TL;DR

1. **The dashboard shows wrong numbers today.** Each of these was confirmed in the DB:
   - IPS counts are double (21,790 vs about 11k real), because REPS monthly snapshots are stacked instead of replaced.
   - **Cali has no affiliation data, and "Cali" displays Buenaventura's numbers.** Department aliases are applied to municipality names. About 4M affiliated people are missing from the views (48.4M vs 52.4M).
   - Cartagena and Cúcuta are missing from the municipal REPS views (no name aliases).
   - "May 2026" afiliación is an exact copy of March: the scraper relabels adjacent months.
   - Ethnic population (56.0M) is larger than total population (53.4M): the projection years don't match (2035 vs 2026).
   - Desnutrición is shown as "per 100,000" but the value is per 100, so it is understated 1000×.
   - Department INS values for Atlántico, Bolívar, Magdalena and Valle are taken from an arbitrary row (department vs district).
2. **The production VM would serve stale data and report success.** The cron pipeline writes the DB to a host path the container never reads. `runner.py` always exits 0. Notifications build invalid JSON.
3. **Secrets hygiene is clean.** No tokens or credentials were found in the tree or the history. The only credential is SIVICAP's public guest account.
4. **Data is 4–9 months stale.** The last successful run was 2026-06-17.

---

## Findings by priority

Severity: 🔴 critical, 🟠 high, 🟡 medium, ⚪ low.

### P1: Wrong numbers on the dashboard (fix before showing to the client)

| # | Sev | Where | Defect | Evidence |
|---|---|---|---|---|
| 1 | 🔴 | `scrapers/geo_normalize.py:103,141,163` | `DEPT_ALIASES` is applied to municipality names, so districts collapse to their department. With `setdefault`, Buenaventura is stored as 76001 (Cali). | Buenaventura is coded `76001` in afiliación and REPS (299 rows). "SANTIAGO DE CALI" is unmatched, so the 2.5M people affiliated in Cali are dropped. |
| 2 | 🟠 | `geo_normalize.py` | There are no municipality aliases. "Cartagena de Indias", "San José de Cúcuta", Tumaco, San Andrés, Mompox, Mariquita and others get no code. | 5,447 REPS rows and 33 afiliación rows per month are unmapped. 218 municipalities have NULL `ips_total`. |
| 3 | 🔴 | `scrapers/afiliacion_scraper.py:276-291` | When a month's ZIP is missing, the scraper uses an adjacent month's data and labels it as the requested month. The cache check at :228 then stops the real month from ever being fetched. | "MAYO" totals equal "MARZO" exactly (104,862,078). |
| 4 | 🟠 | `pipeline/transform.py:186-218`, `reps_scraper.py:267`, `supersalud_scraper.py:147` | The `*_*.parquet` glob unions every monthly snapshot with no dedupe, so counts grow with every run. | 122,891 REPS rows vs 62,672 distinct providers. Department `SUM(ips_total)` is 21,790. Supersalud IPS has 49 rows (22 + 27). |
| 5 | 🟠 | `supersalud_scraper.py:63-69` | Header detection picks the "Área responsable" metadata row, so columns become `col_N`. The column name drifts between months. 27 of 49 rows are junk. | |
| 6 | 🟠 | `pipeline/metricas.py:475-627`, `geo_normalize.py:40-51` | District rows share their department's code. `ROW_NUMBER() PARTITION BY geo_dep_codigo` keeps an arbitrary row. | Atlántico dengue shows the Barranquilla value. `v_dift18_departamento` has 3 rows for dept 76. San Andrés (88) is always NULL. |
| 7 | 🟠 | `metricas.py:101,349` | Ethnic population uses `MAX(anio)` (2035); total population uses ≤ 2026. | Ethnic 55.99M > total 53.40M. |
| 8 | 🟠 | `metricas.py:152-258` | "Latest" is chosen per municipality, so one view mixes periods. | Desnutrición spans 12 epidemiological periods. IRCA spans 17 months. |
| 9 | 🟠 | `dashboard/app.py:567,577,585,866` | Desnutrición `prevalencia_por_100` is labelled "por 100,000". | Values are 0.05–1.01. |
| 10 | 🟠 | `dashboard/charts.py:348-365`, `app.py:720` | The violence chart puts rates per 100k and the absolute total on one axis titled "Casos". | Antioquia: 45.4 (rate) next to 6,644 (cases). |
| 11 | 🟠 | `app.py:183,916-932` | Comparisons match by display name, so a municipality with the same name as its department disappears or overwrites the department column. | Affects Arauca, Boyacá, Bogotá, Sucre, Nariño. |
| 12 | 🟠 | `scrapers/ins_pdf_scraper.py:366-368,1057-1067` | Out-of-range table indexes are clamped (duplicating a table). Labels are assigned by position after filtering, so they shift. | Desnutrición 2-table pages are counted twice. |
| 13 | 🟡 | `metricas.py:439,465,529,602`, `dashboard/data.py:242-339`, `app.py:119` | Rates are averaged without weighting, twice (municipality → department → "Nacional"). | National coverage shows 82.6%; the population-weighted figure is 90.7%. |
| 14 | 🟡 | `app.py:582` | The department "desnutrición" DIFT badge actually shows `mort_menores5_pts`. | |
| 15 | 🟡 | `app.py:305,476` | A missing IRCA risk level is displayed as the text "nan". | 18 municipalities in Antioquia. |
| 16 | 🟡 | `app.py:272,300`, `data.py:107,123,368-482` | The header claims one month for every section. When an overlay query fails, values from another period are shown. IRCA months not present in afiliación can't be selected. The default year is the partial 2026. | |
| 17 | 🟡 | `irca_scraper.py:360` | The dedupe ordering is arbitrary across the two SIVICAP formats (Decree 1575 vs Res. 622). | |
| 18 | 🟡 | `ins_pdf_scraper.py` (intento suicidio PE VIII) | Duplicate municipality rows from overlapping tables. | 10 duplicates. |

### P2: Pipeline reliability (failures are hidden as success)

| # | Sev | Where | Defect |
|---|---|---|---|
| 19 | 🔴 | `pipeline/runner.py:42-48,97-99` + every scraper `run()` | `_safe()` swallows every exception and scrapers return `None` on failure, so the runner always exits 0 and logs "Completado". |
| 20 | 🟠 | `scrapers/irca_scraper.py:387-399` | Any CSV in `irca_manual/` is re-ingested every month, stamped with the current month, and SIVICAP is never tried again. |
| 21 | 🟠 | `ins_pdf_scraper.py:938-941` | The rule "any parquet exists for this period" makes bad extractions permanent. Parser fixes never reach past periods. |
| 22 | 🟠 | `ins_pdf_scraper.py:283-298` | `_current_pe` mixes calendar year and ISO week. It scrapes nothing around New Year (verified for 2025-12-29). |
| 23 | 🟠 | `reps_scraper.py:111-127` | On timeout, a `.crdownload` file (or an HTML error page) is renamed and parsed as complete, then cached for the month. |
| 24 | 🟡 | `runner.py:110-115`, `run_monthly_pipeline.sh` | No run lock. APScheduler `misfire_grace_time` is 1 s, so a busy process skips the month. |
| 25 | 🟡 | `transform.py:189-191` | A missing source keeps the old table silently. DROP+CREATE runs without a transaction. |
| 26 | 🟡 | `ins_pdf_scraper.py:333-337,906-909` | No retry on 5xx/429. An HTML 200 response is treated as "not published". Some tables are never geo-validated. |

### P3: Production deploy (SuperSalud VM) blockers

| # | Sev | Where | Defect |
|---|---|---|---|
| 27 | 🔴 | `scripts/run_monthly_pipeline.sh:62-79`, `docker-compose.prod.yml:9`, `Dockerfile:10` | The pipeline writes `./data/informe_regional.duckdb` on the host. The container reads the `informe_data` volume, which was seeded from the GitHub Release. **Monthly refreshes never reach the dashboard.** |
| 28 | 🟠 | `run_monthly_pipeline.sh:9,49-90` | No `set -e`. `git pull`, `pip install` and `docker restart` failures are ignored. A health-check timeout still reports OK. |
| 29 | 🟠 | `Caddyfile:15-18` | `tls internal` is hardcoded and `TLS_MODE`/certs are ignored, plus 1-year HSTS. Users get a certificate error they can't click past. |
| 30 | 🟠 | `run_monthly_pipeline.sh:37-41`, `.env.example:22-26` | The webhook JSON is built by string interpolation (invalid with newlines), and `curl -s ... \|\| true` hides the failure. The SMTP variables are never used. |
| 31 | 🟡 | `dashboard/data.py:22-27`, `deploy/*.ps1` | The DB download has no checksum and is not atomic. A truncated file bricks the app until someone deletes it by hand. |
| 32 | 🟡 | `scripts/install_vm.sh:43,52,69,84` | Requires Ubuntu 24.04 (python3.12), but the IT doc says 22.04 is OK. Uses `curl get.docker.com \| sh`. Chrome is unpinned. The ops user is in the `docker` group (root-equivalent) and also runs the browser scrapers. |
| 33 | 🟡 | `docker-compose.yml:5-6` | The dev compose publishes `8501` on all interfaces and shares service names with prod. Running `docker compose up` on the VM bypasses Caddy. |
| 34 | 🟡 | `requirements.txt` | The image installs unpinned streamlit, pandas, duckdb and plotly. The HF `sdk_version` (1.58.0) differs from the pinned 1.57.0. |
| 35 | 🟡 | `deploy/install.ps1:5,152` | The scheduled task runs a script from user-writable `%LOCALAPPDATA%` with `-ExecutionPolicy Bypass`. |
| 36 | 🟡 | `supersalud_scraper.py:109` | `verify=False` disables TLS checks. |

### P4: Hygiene and maintainability (low)

- **`.gitattributes` (HF boilerplate) applies `*.zip filter=lfs` on `main`.** This is why `data/raw/cifras-afiliacion-salud-marzo-2026.zip` shows as modified even though its content is unchanged.
  - Fix: remove or trim the root `.gitattributes` (`hf/main` is a separate orphan branch with its own), then run `git add --renormalize .`.
- **`.gitignore`:** add `.venv*/` and `.env.*` (with `!.env.example`).
- **`.dockerignore`:** add `**/__pycache__` and `.env*`.
- **Delete the empty `Caddyfile;C/` directory.**
- **Unused variables in `.env.example`:** `PYTHON_VENV` and `DB_RELEASE_URL` are never read.
- **`.env` is `source`d as shell code.**
- **Dead code:**
  - `scrapers/reps_ips_scraper.py` (NameError on import; disabled)
  - `charts.bar_ins` and `_INS_ROWS`
  - `ins_pdf_scraper` `new_files`
  - unused imports in `tools/inspect_pdf.py`
- **Duplication:**
  - accent and column normalization: 4 copies
  - `_register_duckdb` vs `transform.py`
  - REPS driver and login code: 2 copies
  - dashboard indicator sections: about 250 lines that could be one spec-driven helper
  - overlay `ROW_NUMBER` SQL: about 13 copies
- **Inconsistencies:**
  - `dift18_scraper.run()` takes no `base_dir`.
  - SQL is built with f-strings (no external injection path today).
  - DB text is inserted into `unsafe_allow_html` without escaping.
- **Performance:** the 8.9 MB GeoJSON is cached with `cache_data`, so it is deep-copied on every rerun. Every widget change re-renders all 14 sections.

---

## Data freshness (local DB)

| Source | Latest in DB | Lag |
|---|---|---|
| Afiliación | 2026-03 (the "MAYO" label is a copy of March) | ~7 months |
| IRCA | 2026-06 (49 municipalities); most municipalities at 2026-03 | 4–7 months |
| REPS (6 endpoints) | cut-off 2026-06-17 | ~4 months |
| Supersalud IPS/EPS | 2026-06 | ~4 months |
| INS mortalidad materna, sífilis, violencia, suicidio, menores 5 | 2026 PE V | ~5 epidemiological periods |
| INS dengue | 2026 PE IV | ~6 periods |
| INS desnutrición | 2026 PE I | ~9 periods |
| DANE demografía | projections 2018–2042 | OK |
| DIFT18 | 2024 | annual, OK |

---

## Relevance to the client design (FCT mockup, `docs/reference/DASHBOARD_FCT.docx`)

- **Good news:** `v_afiliacion` already includes the 4 Sisbén IV columns that Aseguramiento indicators 8–11 need:
  - sin SISBEN IV
  - Pob. Especiales sin SISBEN IV
  - de Oficio sin SISBEN IV
  - No Pobre No Vulnerable
- **Structural blockers in the dashboard code:**
  - It is a single linear script with no page abstraction, so a landing menu needs `st.navigation` and shared selection state.
  - It has no indicator registry (unit, source, thresholds and icon live in one place).
  - It has no year-over-year series: every query collapses to `rn = 1`, but the mockup's "Tendencia vs. año anterior" needs year N and N-1.
- **Fixing P1 is required first.** The mockup's headline cards (Total IPS, IPS públicas/privadas/mixtas, población étnica, cobertura) are exactly the numbers that are wrong today.

---

## Recommended fix order

1. **Geo matching** (#1, #2): build a municipality alias table and join on DIVIPOLA codes where the source has them. This fixes Cali, Buenaventura, Cartagena and Cúcuta in every source.
2. **Snapshot loading** (#4, #5): load only the latest REPS/Supersalud snapshot, and fix Supersalud header detection.
3. **No relabelling** (#3, #20): remove the afiliación month fallback; archive the IRCA manual CSV after ingesting it and stamp the period from the data.
4. **Make failures visible** (#19, #28, #30): scrapers raise or return a status, the runner exits non-zero, and the script checks every step and builds valid JSON.
5. **Fix the metric views** (#6, #7, #8, #13): handle districts, match the projection years, use one global latest period per source, and use weighted rates.
6. **Fix dashboard labels and bugs** (#9–#11, #14–#16).
7. **Add data-quality checks** after transform: unmapped share, row-count deltas against the previous snapshot, ethnic ≤ total, unique keys. These would have caught most of P1.
8. **Then refresh the data,** after fixes 1–7.
9. **Fix the deploy blockers** (#27–#35) before the VM go-live.
10. **Restructure the dashboard** toward the FCT design.

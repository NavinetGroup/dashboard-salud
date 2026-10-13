# Source research: better and missing data sources

**Date:** 2026-10-13
**Method:** three parallel web research passes. A source was marked *verified* only after a live probe: a Socrata/API query, a metadata read, or downloading a small file. Search-snippet inferences are labelled as such.
**Goal:** replace fragile scrapers where possible, and find sources for the indicators in the client's FCT design (`docs/reference/DASHBOARD_FCT.docx`) that the pipeline doesn't cover yet.

---

## TL;DR

| Area | Result |
|---|---|
| **INS PDF indicators (7)** | ✅ **PDF parsing can be retired.** SIVIGILA microdata covers the previous year (final data). INS Power BI public dashboards cover the current year at municipal level, refreshed weekly. Rates are computed by us from DANE denominators. |
| **REPS** | 🟡 Partial. datos.gov.co `c36g-9fc2` gives IPS by naturaleza (pública/privada/mixta) for all 1,123 municipalities, with no login. Capacidad, servicios, medidas and sanciones still need the Selenium portal. |
| **IRCA** | 🟡 Complement only. datos.gov.co `nxt2-39c3` is annual (2007–2024). Monthly data still comes only from SIVICAP (reCAPTCHA). |
| **Aseguramiento gaps** | ✅ The BDUA datasets on datos.gov.co (monthly snapshot) give EPS per municipality and the age/sex pyramid by regime. The Sisbén IV fields are already in `afiliacion`. |
| **Financiamiento (11)** | 🟡 6 computable from CUIPO (CGR, datos.gov.co, quarterly). Cofinanciación computable from MinSalud and ADRES files. **Circular 030, PNA/NPBS and migrants must come from the client.** |
| **Salud Pública 9–11** | 10 (VSP) and 11 (capacidades) are published by INS at department level. **9 (LSP standards) is not public: request it from INS via Supersalud.** |

⚠️ **Privacy note:** one data-protection finding about a third-party source was reported to the project owner privately and is intentionally not documented here.

---

## 1. Salud Pública (INS)

| # | Indicator | Current year | Previous year (final) | Denominator | Verdict |
|---|---|---|---|---|---|
| 1 | Maternal mortality ratio | Power BI "006 Vigilancia Rutinaria", event 550 | Microdata 550 | DANE births (mother's residence) | Replace PDF. ⚠ Event 550 may include late or coincidental deaths: confirm with INS or label as "notificada" |
| 2 | Sífilis congénita | Power BI "740" | Microdata 740 | DANE births | Replace PDF |
| 3 | Desnutrición aguda <5 (%) | Power BI "113" | Microdata 113 | DANE projection, under-5 population | Replace PDF (fixes the 2026 PNG tables) |
| 4 | Mortality <5 from malnutrition | Power BI "591" | Microdata 112 | DANE projection, under-5 population | Replace PDF |
| 5 | IRCA | see §3 | | | |
| 6 | Dengue grave | Power BI "210 Dengue" (measure `Grave`) | Microdata 220 | DANE total population | Replace PDF |
| 7 | Intento de suicidio | Power BI "356" | Microdata 356 | DANE total population | Replace PDF |
| 8 | Violencia de género | Power BI "875" | Microdata 875 | DANE total population | Replace PDF |
| 9 | LSP standards compliance | — | — | — | **Not public.** INS Dirección de Redes runs it; request via Supersalud |
| 10 | VSP management (%) | INS quarterly XLSX "Indicadores de Evaluación Desempeño" (I-2026 FINAL) | | | Usable, department level. We compute the overall % |
| 11 | Basic capacities (0–5) | INS Power BI "Evaluación de capacidades básicas…" | | | Usable but awkward (schema changes each round); ideally ask for the source file |

**Sources:**
- **SIVIGILA microdata.** A SharePoint REST endpoint with no login:
  - List: `https://portalsivigila.ins.gov.co/_api/web/lists/GetByTitle('Microdatos')/items?$select=CodigoEvento,A_x00f1_o,NombreEvento,FileRef`
  - File: `…/_api/Web/GetFileByServerRelativeUrl('/Microdatos/Datos_<año>_<evento>.xlsx')/$value`
  - One row per case, with residence, occurrence and notification codes (`COD_DPTO_R`, `COD_MUN_R`).
  - Cells are stored as `="…"` strings.
  - Exclude adjusted-out cases (`AJUSTE` 6/D).
  - 2025 was published on 2026-08-06; files can reach 110 MB.
- **INS Power BI.**
  - Report URLs are listed at Portal SIVIGILA `MenuReporteNivel2`.
  - Queryable through the public `querydata` API using the `X-PowerBI-ResourceKey` header.
  - Verified totals match the microdata.
  - Municipal level verified (113 by `CodMunR`: 1,156 values).
  - It is **undocumented**: pin the report keys and alert on schema changes.
  - Use counts, not the built-in `Incidencia` measures.
  - Probe scripts: session scratchpad `pbiq.py` and `pbischema.py`.
- **DANE births.**
  - Example file: `https://www.dane.gov.co/files/operaciones/EEVV/2026/24-sep-2026/anex-EEVV-NacimientosCuadroAnoCorrido-2026pr.xlsx`
  - Cuadro 3 gives births by municipality of the mother's residence, with a lag of about 2 months.
  - The DANE server needs `ciphers DEFAULT@SECLEVEL=1` in Python.
- **datos.gov.co SIVIGILA datasets:** not usable (national data stops at 2019–2021).

## 2. REPS

| Source | Verified | Covers | Verdict |
|---|---|---|---|
| datos.gov.co **`c36g-9fc2`** (MinSalud) "Registro Especial de Prestadores y Sedes" | ✅ | One row per sede (76,821 rows); DIVIPOLA for every municipality; `naturalezajuridica`, `claseprestador`, `ese`. Cut-off 2026-03-12. Stated frequency is annual | **Use for the IPS total and the pública/privada/mixta split** |
| `s2ru-bqt6`, `kjjp-kasm`, `fa2g-cdft` (capacity) | ✅ | Last updated 2022-11-21; names only, no codes | Not usable |
| prestadores.minsalud.gov.co | ✅ | Login; no public bulk endpoint | Keep Selenium for capacidad, servicios, medidas and sanciones |

Example query: `$query=select municipiosede, naturalezajuridica, count(*) where claseprestador='Instituciones Prestadoras de Servicios de Salud - IPS' group by municipiosede, naturalezajuridica`. Read `fecha_corte_reps` on each run.

## 3. IRCA

| Source | Verified | Covers | Verdict |
|---|---|---|---|
| datos.gov.co **`nxt2-39c3`** (INS) | ✅ | **Annual**, 2007–2024, DIVIPOLA, IRCA plus urban/rural and risk level. No month, no sample count. Updated 2025-06-10 | Complement: history backfill, annual view, cross-check |
| SIVICAP | ✅ | Login + reCAPTCHA; no stable open endpoint | Keep as the monthly source (manual or persisted session) |

Option: a formal request (derecho de petición, or the Supersalud inter-agency channel) to INS for a monthly extract or a service account without the CAPTCHA.

## 4. Aseguramiento

| # | Indicator | Source | Verdict |
|---|---|---|---|
| 1–3 | EPS total / contributivo / subsidiado per territory | BDUA datos.gov.co **`d7a5-cnra`** (subsidiado, 27.0M) + **`tq4m-hmg2`** (contributivo, 23.1M), refreshed monthly (2026-10-03) | Use. Count distinct EPS with affiliates; merge "-CM" mobility codes. **No DIVIPOLA codes**, so match on names with geo_normalize |
| 4 | EPS intervenidas | Supersalud CTFT21 Excel (current scraper) + `CTFT21-programa-de-recuperacion.xlsx` | Keep; fix header parsing (audit #5) |
| 5–7 | Affiliated population by regime, coverage | Current afiliación ZIP | Keep |
| — | Population pyramid by regime | BDUA datasets above (sex × UPC age group) | Use. **Snapshot-only: start archiving a dated copy each month** |
| 8–11 | Sisbén IV breakdowns | Already in the `afiliacion` table (4 columns) | Wire into views |

## 5. Financiamiento

The client's label "SIHO – FUT" is outdated. Territorial budget execution moved from FUT to **CUIPO** (in CHIP) around 2022. SIHO covers public hospitals (ESE).

| # | Indicator | Best source | Verdict |
|---|---|---|---|
| 1 | FLS commitments vs income | CUIPO gastos `4f7r-epif` (sector 19.0x commitments) ÷ ingresos `9axr-9gnb` | Compute |
| 2 | FLS commitments / apropiación | CUIPO gastos ÷ programación `d9mu-h6ar` | Compute (apropiación filter needs validating) |
| 3 | FLS payments vs income | CUIPO `pagos` ÷ recaudo | Compute |
| 4–5 | SGP Salud Pública commitments / payments | CUIPO by fuente `1.2.4.2.02`; denominator from SICODIS allocation (programación has no fuente) | Compute, partial |
| 6 | SGP Subsidio a la oferta commitments | CUIPO sector `19.03.28` + SICODIS | Compute |
| 7 | SGP Subsidio a la oferta transfers | SICODIS (allocation) + CUIPO payments | Partial: ask the client for transfer data |
| 8 | Cofinanciación régimen subsidiado | Meta: MinSalud "Monto estimado 2026" (matriz de continuidad). Fulfilled: ADRES monthly LMA "esfuerzo propio" | Compute; confirm the definition with the client |
| 9 | Circular 030 (payments / commitments signed) | Internal MinSalud SAC/PISIS; the public file only has matched receivables | **Request from client** |
| 10 | PNA/NPBS paid / reconocido | Internal (PISIS/SIHO) | **Request from client** |
| 11 | Irregular migrants paid / reconocido | Internal PISIS (Res. 220/2024) | **Request from client** |

**Sources:**
- **CUIPO on datos.gov.co (CGR).**
  - Quarterly, latest **2026-06**; no login.
  - 930 municipalities + 31 departments report sector 19.
  - Entities use **CGN codes**, so a CGN → DIVIPOLA mapping is needed.
  - Large aggregations time out above about 170 s, so page by entity or quarter.
  - Filter FLS by `cod_sectorial` 19.x, not by sección 21 (only 396 municipalities use that).
- **SICODIS (DNP) API.**
  - Example: `https://sicodis.dnp.gov.co/apiws/ApiSicodisNew/sgp/resumen_participaciones/<año>/<mes>/<divipola>`
  - No auth, undocumented. Gives SGP allocations, not execution.
- **ADRES LMA.**
  - Monthly XLSX, one row per DANE municipality × EPS, with SGP, esfuerzo propio, Coljuegos…
  - The page is rendered by JavaScript. File pattern: `/api/media/file/Resumen-liquidacion-mensual-de-afiliados-<Mes>-<Año>.xlsx`
- **MinSalud "Informe de validación FUT-CUIPO"** (quarterly .xlsb, 11 annexes with DANE codes): use it as a **cross-check** for indicators 1–5 before publishing.

---

## Request list for the client (Supersalud)

1. **Circular 030:** commitments and payments from the reconciliation meetings, by territorial entity.
2. **PNA/NPBS:** amounts reconocido vs pagado by territorial entity.
3. **Irregular migrants:** amounts reconocido vs pagado (Res. 220/2024 PISIS data).
4. **LSP quality standards compliance** by departmental lab (from INS Dirección de Redes).
5. **Basic risk-management capacities:** the source file (the published dashboard changes schema every round).
6. **Formula definitions** for Financiamiento 1–8 (numerators and denominators), and whether their "SIHO – FUT" figures come from an internal extract we should match.
7. **Official list of authorised EPS** by territory (not public).
8. Optional: an INS service account or a monthly SIVICAP extract (removes the IRCA manual step).
9. A data-protection matter concerning an INS source (details shared privately).

## Impact on the scraper plan

| Scraper | Decision |
|---|---|
| `ins_pdf_scraper.py` | **Replace** with an `ins_sivigila` scraper: microdata (previous year) + Power BI counts (current year) + DANE denominators. Keep the PDF scraper only as a temporary fallback |
| `reps_scraper.py` | Patch (audit #23). Add a `c36g-9fc2` SODA source for IPS by naturaleza |
| `irca_scraper.py` | Patch (audit #20, #17). Add `nxt2-39c3` as an annual layer |
| `afiliacion_scraper.py` | Patch (audit #3). Add a BDUA `d7a5-cnra`/`tq4m-hmg2` monthly snapshot scraper |
| `supersalud_scraper.py` | Patch the header parsing (audit #5) |
| **New** | `cuipo` (CGR datos.gov.co), `sicodis`, `adres_lma`, `minsalud_cofinanciacion`, `ins_vsp` (XLSX) |
| `demografico.py`, `dift18_scraper.py` | Keep; DANE projections also supply the denominators |

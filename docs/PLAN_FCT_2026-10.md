# Plan: dashboard redesign to the client's FCT design

**Date:** 2026-10-13
**Target:** `docs/reference/DASHBOARD_FCT.docx`, the "Ficha de Caracterización Territorial" mockups from Supersalud Territoriales.
**Starting point:** the audit fixes (steps 1–9) are done. The pipeline produces correct, period-labelled metrics in `metricas_*_periodo` / `v_metricas_*`, and the dashboard only reads them.

---

## 1. Target structure (from the mockups)

| Page | Content |
|---|---|
| **Inicio** | Menu of 6 coloured cards: Ficha (main), Demográficos, Salud Pública, Aseguramiento, Prestación de Servicios, Financiamiento |
| **Localización** | Breadcrumb Colombia > Departamento > Municipio. Three drill-down maps and a map of neighbouring municipalities |
| **Demográficos** | KPI cards (men, women, total, ethnic population). Sex donut. Ethnic-group bars and composition table |
| **Salud Pública** | 11 indicator cards with icon, value, unit and trend vs previous year (arrow and colour) |
| **Aseguramiento** | EPS counts. Affiliated population by regime. Coverage ring with change in percentage points. Affiliated-population pyramid. 4 Sisbén IV cards with sparklines |
| **Prestación** | IPS total / pública / privada / mixta. Installed capacity by type. Intervened IPS and their status. Network composition donut |
| **Financiamiento** | 11 budget-execution indicators shown as gauges with 0–100% red→green bands |
| **Ficha** | One-page summary: 5 colour-banded rows with the key KPIs of each module |

Common elements: Supersalud branding, icon-led KPI cards, a source/period footer on every page.

## 2. Indicator coverage today

✅ available · 🟡 available with pipeline work (no new source) · 🔵 new public source (identified in `FUENTES_INVESTIGACION_2026-10-13.md`) · 🔴 must come from the client

### Demográficos
| Indicator | Status | Notes |
|---|---|---|
| Men / women / total | ✅ | DANE projections |
| Population with ethnic identification + by group | ✅ | `pob_etnico_total − pob_ninguno`; shares per group |
| Localización maps (country → department → municipality, neighbours) | ✅ | DANE MGN 2025, simplified (tools/build_geojson.py); plain polygon maps, no tile server |

### Salud Pública (11)
| # | Indicator | Status | Notes |
|---|---|---|---|
| 1 | Maternal mortality ratio | ✅ | |
| 2 | Congenital syphilis incidence (per 1,000 live births + fetal deaths) | ✅ | SIVIGILA cases ÷ DANE births + fetal deaths (mother's residence), pro-rated to weeks covered; matches INS bulletin level |
| 3 | Acute malnutrition prevalence <5 (%) | ✅ (sparse) | Full municipal coverage after the SIVIGILA rebuild 🔵 |
| 4 | Under-5 mortality from malnutrition | ✅ | Department and district level |
| 5 | IRCA + risk bar | ✅ | |
| 6 | Severe dengue incidence | 🟡 | `dengue_grave_total` / population |
| 7 | Suicide attempt rate | ✅ (sparse) | Full coverage after the SIVIGILA rebuild 🔵 |
| 8 | Gender-violence notification rate | ✅ | |
| 9 | LSP quality standards | 🔴 | Not published (INS Redes) |
| 10 | VSP management indicators | ✅ | INS quarterly performance XLSX (2024-II →): mean of applicable sub-indicators, groups 1–7. Proposed formula: confirm with Supersalud |
| 11 | Basic risk-management capacities | ✅ | Same INS file, sub-indicator 8-1 (% progress in basic capacities), shown as % instead of the 0–5 score. Confirm with Supersalud |
| — | **Trend vs previous year** | 🟡 | Needs *same-period* prior-year values (2026 PE V vs 2025 PE V), not "latest in year". Pipeline addition |

### Aseguramiento
| Indicator | Status | Notes |
|---|---|---|
| EPS authorised: total / contributivo / subsidiado | 🔵 | BDUA datasets (EPS with affiliates per territory) |
| EPS under intervention | ✅ | Supersalud |
| Affiliated population: subsidiado / contributivo | ✅ | |
| Coverage % + change in pp vs previous year | ✅ / 🟡 | Same month of the prior year exists from 2025-07 |
| Affiliated-population pyramid by regime | 🔵 | BDUA (sex × age group). Monthly snapshot only, so we must start archiving |
| 4 Sisbén IV indicators + sparklines | 🟡 | Columns already in `afiliacion`; expose in metricas plus the monthly series |

### Prestación de servicios
| Indicator | Status | Notes |
|---|---|---|
| IPS total / pública / privada / mixta | ✅ | |
| Installed capacity: beds, consultation rooms, surgery rooms, adult ICU, paediatric ICU | 🟡 | REPS `grupo_capacidad` / `coca_nombre`. ⚠ The current "capacidad instalada (camas)" sums everything, including ambulances and dialysis chairs: fix it |
| Intervened IPS (count) | ✅ | |
| Intervention status (in progress / programme / special measure / finished) | 🔴 | The public list only has "Intervención Forzosa" |
| Network composition donut | ✅ | |

### Financiamiento (11)
| # | Status | Notes |
|---|---|---|
| 1–7 | ✅ | CUIPO (CGR, quarterly) + SICODIS (DNP). Built 2026-10-13; formulas pending client validation (docs/FINANCIAMIENTO_FORMULAS.md) |
| 8 | ✅ | MSPS continuity matrix (target) + ADRES monthly LMA (executed); LMA matches MSPS executed matrix 2025 exactly |
| 9–11 | 🔴 | Circular 030, PNA/NPBS, migrants: from the client |

## 3. Phases

| Phase | What | Depends on |
|---|---|---|
| **10a — Shell + components** | `st.navigation` multipage app: Inicio, Ficha, 5 modules, plus the current report kept as "Informe detallado". Shared selection (department / municipality / period) in `session_state`. One **indicator registry** (label, column, unit, icon, period column, "lower is better", source). KPI card / gauge / ring components in Supersalud style | nothing |
| **10b — Pipeline additions (existing sources)** | Same-period prior-year values for trends. Capacity by type (and fix the "camas" sum). Sisbén IV + monthly series. Severe dengue incidence. Ethnic-identification total | nothing |
| **10c — Module pages on existing data** | Demográficos, Salud Pública, Aseguramiento, Prestación, Ficha. Missing indicators handled per the decision below | 10a, 10b |
| **10d — New sources** | BDUA (EPS counts, pyramid, monthly archive). INS SIVIGILA rebuild (replaces PDF parsing). INS VSP. Municipal geometry for Localización. CUIPO + SICODIS + ADRES for Financiamiento | source research |
| **10e — Client data** | LSP, intervention status, Circular 030, PNA/NPBS, migrants, formula definitions. Agree a simple delivery format (CSV/XLSX template) | client |

Each phase ships on its own: after 10c the client sees the new design with every indicator we can already support.

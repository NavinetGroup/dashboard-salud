# Indicadores y Fuentes — Informe Regional

Source: `informe_regional.xlsx` (sheet: Indicadores y fuentes)

---

## Accesibles ✅

### Demográficos

| Indicador | Fuente | Tipo | Periodo | DuckDB table |
|-----------|--------|------|---------|--------------|
| General (edad/sexo/área) | [DANE PPED-AreaSexoEdad 2018-2042](https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Municipal/PPED-AreaSexoEdadMun-2018-2042_VP.xlsx) | Excel directo | Anual | `demografico_edad_sexo` |
| Étnicos | [DANE Pertenencia Étnico-Racial](https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Nacional/anex-DCD-Proypoblacion-PerteneniaEtnicoRacialmun.xlsx) | Excel directo | Anual | `demografico_etnico` |

**Scraper:** `scrapers/demografico.py` — run annually (July)

---

### Acceso y Garantía — Prestación de servicios (REPS)

All 6 endpoints require Selenium login at `https://prestadores.minsalud.gov.co/habilitacion/` (guest button).

| Indicador | URL endpoint | Scraper filename | DuckDB table | Separator |
|-----------|-------------|-----------------|--------------|-----------|
| Prestadores habilitados | [habilitados_reps.aspx](https://prestadores.minsalud.gov.co/habilitacion/consultas/habilitados_reps.aspx) | `Prestadores.csv` | `reps_prestadores` | `\|` |
| Sedes | [sedes_reps.aspx](https://prestadores.minsalud.gov.co/habilitacion/consultas/sedes_reps.aspx) | `Sedes.csv` | `reps_sedes` | `;` |
| Servicios | [serviciossedes_reps.aspx](https://prestadores.minsalud.gov.co/habilitacion/consultas/serviciossedes_reps.aspx) | `ServiciosSedes.csv` | `reps_servicios` | `;` |
| Capacidad instalada | [capacidadesinstaladas_reps.aspx](https://prestadores.minsalud.gov.co/habilitacion/consultas/capacidadesinstaladas_reps.aspx) | `CapacidadesInstaladas.csv` | `reps_capacidad` | `;` |
| Medidas de seguridad | [medidasseguridad_reps.aspx](https://prestadores.minsalud.gov.co/habilitacion/consultas/medidasseguridad_reps.aspx) | `MedidasSeguridad.csv` | `reps_medidas_seguridad` | `;` |
| Sanciones | [sanciones_reps.aspx](https://prestadores.minsalud.gov.co/habilitacion/consultas/sanciones_reps.aspx) | `Sanciones.csv` | `reps_sanciones` | `;` |

**Scraper:** `scrapers/reps_scraper.py` — run monthly  
**Note:** `Prestadores.csv` uses `|` separator; all others use `;`. Scraper sets separator via JS injection on the page.

| Indicador | URL | Tipo | Periodo | DuckDB table |
|-----------|-----|------|---------|--------------|
| IPS intervenidas | [CTFT21 Excel (Supersalud)](https://docs.supersalud.gov.co/PortalWeb/MedidasEspeciales/Directorio%20de%20Entidades/CTFT21-Listado-de-entidades-en-medida-preventiva-y-entidades-en-intervencion-forzosa-administrativa-para-administrar-IPS.xlsx) | Excel directo | Mensual | `supersalud_ips_intervenidas` |

**Scraper:** `scrapers/supersalud_scraper.py`

---

### Acceso y Garantía — Aseguramiento en salud

| Indicador | Fuente | Tipo | Periodo | DuckDB table |
|-----------|--------|------|---------|--------------|
| Afiliación en salud | MinSalud ZIPs (ver URLs abajo) | ZIP → Excel | Mensual | `afiliacion` |
| EPS intervenidas | [Supersalud medida especial](https://www.supersalud.gov.co/es-co/transparencia-y-acceso-a-la-informacion-publica/informacion-especifica-para-grupos-de-interes/entidades-en-medida-especial-liquidacion-y-traslados-de-eps) | Excel directo | Mensual | `supersalud_eps_intervenidas` |

**Afiliación ZIP URLs (known historical):**
```
julio-2025:      https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/DOA/OAS/cifras-afiliacion-salud-julio-2025.zip
agosto-2025:     https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/DOA/OAS/cifras-afiliacion-salud-agosto-2025.zip
septiembre-2025: https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/DOA/OAS/cifras-afiliacion-septiembre-2025.zip
octubre-2025:    https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/DOA/OAS/cifras-afiliacion-salud-oct2025.zip
noviembre-2025:  https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/DOA/cifras-afiliacion-salud-nov-2025.zip
diciembre-2025:  https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/DOA/cifras-afiliacion-salud-dic-2025.zip
enero-2026:      https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/RBC/cifra-afiliacion-salud-enero-2026.zip
febrero-2026:    https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/RBC/cifras-afiliacion-salud-feb-2026.zip
marzo-2026:      https://www.minsalud.gov.co/sites/rid/Lists/BibliotecaDigital/RIDE/VP/RBC/cifras-afiliacion-salud-marzo-2026.zip
```
URL pattern varies by month (folder changes between DOA/OAS, DOA, RBC; filename uses full name, abbrev or "cifra" vs "cifras").  
**Scraper:** `scrapers/afiliacion_scraper.py` — downloads current month only; historical requires direct URL.

---

### Salud Pública — INS PDF (epidemiológicos)

All PDFs from `https://www.ins.gov.co/buscador-eventos/Informesdeevento/`  
**Scraper:** `scrapers/ins_pdf_scraper.py` — covers PE I–XIII for each year from 2025.

| Indicador | Evento key | Página PDF | Tablas | DuckDB table | Freq |
|-----------|-----------|-----------|--------|--------------|------|
| Razón mortalidad materna | `mortalidad_materna` | 2 (0-idx) | 0,1,2 (3 tables) | `ins_mortalidad_materna` | Mensual |
| Incidencia sífilis congénita | `sifilis_congenita` | 0 | header-match DPNOM/MPIO | `ins_sifilis_congenita` | Mensual |
| Prevalencia desnutrición aguda <5 años | `desnutricion_aguda` | 1 | 0,1,2 (3 tables) | `ins_desnutricion_aguda` | Mensual |
| Tasa mortalidad menores 5 años por desnutrición | `mortalidad_menores5` | 1 | 0 (word_grid) | `ins_mortalidad_menores5` | Mensual |
| Índice calidad del agua (IRCA) | — | — | — | `irca` | Mensual |
| Incidencia dengue grave | `dengue` | 3 | 0 (word_grid) | `ins_dengue` | Trimestral |
| Tasa incidencia intento de suicidio | `intento_suicidio` | 1 | 0,1 | `ins_intento_suicidio` | Mensual |
| Tasa notificación violencia de género/intrafamiliar | `violencia_genero` | 1 | 0 (word_grid, PE IV 2025+) | `ins_violencia_genero` | Trimestral |

**IRCA** (separate scraper): `https://sivicap.ins.gov.co/SIVICAP/ReportesCG/ReportesSIVICAP?menuId=228`  
Credentials: `invitado@ins.gov.co` / `123456` — CAPTCHA fallback to cached file ≤30 days.  
**Scraper:** `scrapers/irca_scraper.py`

---

## No accesibles ❌

| Grupo | Indicador | Fuente | Tipo |
|-------|-----------|--------|------|
| Salud Pública | Cumplimiento estándares LSP | SharePoint Supersalud (requiere login) | Excel INS + PDF INVIMA |
| Salud Pública | % cumplimiento indicadores gestión VSP | [SIVIGILA cod=128](https://portalsivigila.ins.gov.co/Paginas/datos.aspx?cod=128) | PDF tabla |
| Salud Pública | Evaluación capacidades básicas gestión riesgo | [SIVIGILA cod=155](https://portalsivigila.ins.gov.co/Paginas/datos.aspx?cod=155) | PDF tabla |
| Financiamiento | Ejecución presupuestal FLS (Compromisos vs Ingresos) | Power BI FT035+FT036 / CUIPO | Dashboard |
| Financiamiento | Ejecución presupuestal FLS (Compromisos) | Power BI FT036 / CUIPO | Dashboard |
| Financiamiento | Ejecución presupuestal (Pagos vs Ingresos) | Power BI FT035+FT036 / CUIPO | Dashboard |
| Financiamiento | Ejecución SGP Salud Pública Compromisos | Power BI FT036 / CUIPO | Dashboard |
| Financiamiento | Ejecución SGP Salud Pública Pagos | Power BI FT036 / CUIPO | Dashboard |
| Financiamiento | Ejecución SGP Subsidio oferta Compromisos | Power BI FT036 / CUIPO | Dashboard |
| Financiamiento | Ejecución SGP Subsidio oferta Giros | Power BI FT036 / CUIPO | Dashboard |
| Financiamiento | Cumplimiento meta cofinanciación RS | Matriz MSPS + LMA ADRES | Excel |
| Financiamiento | Deuda Circular 030/2013 | Power BI CC030 SAC / SAC ET | Dashboard |
| Financiamiento | Total pagos / compromisos firmados | Herramienta seguimiento | Excel |
| Financiamiento | Pagos prestación servicios PNA/NPBS | Power BI FT033 | Dashboard |
| Financiamiento | % Valor pago / Valor reconocido | Power BI FT033 | Dashboard |
| Financiamiento | Pagos migrantes no regulares | Power BI FT033 | Dashboard |
| Financiamiento | % Valor pagado / Valor reconocido | Power BI FT033 | Dashboard |
| DGRARSSSS / ADRES | IGRC rentas cedidas (100% conceptos) | [ADRES rentas cedidas](https://www.adres.gov.co/entidades-territoriales/financiamiento/rentas-cedidas) — página no encontrada | Excel |
| DGRARSSSS / ADRES | INGRC rentas cedidas (NO reporte) | Mismo enlace ADRES — no accesible | Excel |
| DGRARSSSS / ADRES | IGE giro extemporáneo rentas cedidas | Mismo enlace ADRES — no accesible | Excel |
| DGRARSSSS / Juegos Territoriales | Reportes entregados / programados | SQL Server interno `sns-db14prod11` | SSRS |
| DGRARSSSS / Juegos Territoriales | Reportes por municipio (AT276) | SQL Server interno | SSRS |
| DGRARSSSS / Juegos Territoriales | Recaudo PNR Apuestas AT277 / AT219 | SQL Server interno | SSRS |
| DGRARSSSS / Juegos Territoriales | Transferencias AT276 / AT214 | SQL Server interno | SSRS |

---

## Estado actual DuckDB (2026-05-03)

### Tablas de datos

| Tabla | Filas | Estado |
|-------|-------|--------|
| `demografico_edad_sexo` | 11,342,300 | ✅ |
| `demografico_etnico` | 242,352 | ✅ |
| `reps_prestadores` | 61,538 | ✅ |
| `reps_sedes` | 77,339 | ✅ |
| `reps_servicios` | 229,371 | ✅ |
| `reps_capacidad` | 97,905 | ✅ |
| `reps_medidas_seguridad` | 3,443 | ✅ |
| `reps_sanciones` | 788 | ✅ |
| `supersalud_ips_intervenidas` | 22 | ✅ |
| `supersalud_eps_intervenidas` | 11 | ✅ |
| `afiliacion` | 10,161 | ✅ jul 2025 – mar 2026 (9 meses, 1,129 filas/mes) |
| `irca` | 12,171 | ⚠️ datos anteriores; CAPTCHA bloquea actualización |
| `ins_mortalidad_materna` | 776 | ✅ |
| `ins_sifilis_congenita` | 81 | ✅ |
| `ins_desnutricion_aguda` | 1,024 | ✅ |
| `ins_mortalidad_menores5` | 330 | ✅ |
| `ins_dengue` | 556 | ✅ |
| `ins_intento_suicidio` | 268 | ✅ |
| `ins_violencia_genero` | 267 | ✅ |

### Capa geográfica (`scrapers/geo_normalize.py`)

Tabla de referencia DANE: `geo_maestro` (1,123 municipios), `geo_dep` (33 departamentos).  
Puentes de normalización: `geo_map_<tabla>` (nombre crudo → código DIVIPOLA).  
Vistas normalizadas: `v_<tabla>` — añaden `geo_dep_codigo`, `geo_mun_codigo`, `geo_dep_dane`, `geo_mun_dane`.

| Vista | Cobertura geo |
|-------|--------------|
| `v_demografico_edad_sexo` | 100% (códigos nativos) |
| `v_demografico_etnico` | 100% (códigos nativos) |
| `v_irca` | 100% (códigos nativos) |
| `v_afiliacion` | 97% municipios |
| `v_reps_prestadores` | 98% municipios |
| `v_reps_sedes` | 96% municipios |
| `v_reps_servicios` | 94% municipios |
| `v_reps_capacidad` | 97% municipios |
| `v_reps_medidas_seguridad` | 96% municipios |
| `v_reps_sanciones` | 97% municipios |
| `v_ins_mortalidad_materna` | 93% filas (mix dept+mun) |
| `v_ins_sifilis_congenita` | 100% municipios |
| `v_ins_desnutricion_aguda` | 99% municipios |
| `v_ins_intento_suicidio` | 100% municipios |
| `v_ins_mortalidad_menores5` | 92% departamentos |
| `v_ins_dengue` | 91% departamentos |
| `v_ins_violencia_genero` | 86% departamentos |
| `v_supersalud_ips_intervenidas` | 79% (resto: encabezados/blancos) |
| `v_supersalud_eps_intervenidas` | 78% (resto: encabezados/blancos) |

### Vistas de métricas consolidadas (`pipeline/metricas.py`)

| Vista | Filas | Descripción |
|-------|-------|-------------|
| `v_metricas_municipio` | 1,123 | Un indicador por municipio DANE: demografía, IPS, afiliación, IRCA, INS mun-level |
| `v_metricas_departamento` | 33 | Un indicador por departamento: todo lo anterior + fuentes dept-only (dengue, mortalidad <5, suicidio, violencia género, Supersalud) |

**Columnas disponibles (46 en mun / 45 en dept):**  
`pob_hombres/mujeres/total` · `pob_etnico_total` + 6 grupos étnicos · `ips_total/publica/privada/mixta` · `capacidad_instalada` · `ips_intervenidas` · `eps_intervenidas` · `afiliados_subsidiado/contributivo/total` · `irca_promedio/nivel_riesgo` · `razon_mortalidad_materna` · `incidencia_sifilis_congenita` · `prevalencia_desnutricion_aguda` · `tasa_intento_suicidio` · `tasa_mortalidad_menores5_dnt/ira/eda` · `dengue_total/grave/incidencia_x100k` · `violencia_fisica/psicologica/negligencia/sexual/intrafamiliar` · `lsp/vsp/gestion_riesgo` (NULL — no disponible)

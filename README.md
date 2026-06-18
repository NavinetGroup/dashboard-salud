---
title: Informe Regional de Salud
emoji: 🏥
colorFrom: blue
colorTo: green
sdk: streamlit
sdk_version: 1.58.0
app_file: dashboard/app.py
pinned: false
license: mit
---

# Informe Regional de Salud — Colombia

Dashboard interactivo que consolida 8 fuentes oficiales del sector salud colombiano (DANE, MinSalud, INS, SuperSalud) y muestra indicadores comparables para los **33 departamentos** y **1,123 municipios** del país.

---

## 🔗 Acceso al dashboard

| Entorno | URL | Notas |
|---|---|---|
| **En vivo (público)** | https://huggingface.co/spaces/navinetgroup/dashboard-salud | Hosted en Hugging Face Spaces. Carga el DB la primera vez (~10 s). |
| **Repositorio** | https://github.com/NavinetGroup/dashboard-salud | Código + scripts de despliegue. |
| **Datos (DB)** | https://github.com/NavinetGroup/dashboard-salud/releases/tag/data-v1 | Archivo `informe_regional.duckdb` actualizado mensualmente. |

---

## 📊 Qué muestra

8 categorías de indicadores con comparabilidad geográfica completa:

| Categoría | Fuente | Tabla DB | Frecuencia |
|---|---|---|---|
| Demografía (edad/sexo) | DANE PPED | `demografico_edad_sexo` | Anual |
| Demografía étnico-racial | DANE | `demografico_etnico` | Anual |
| Habilitación de prestadores | MinSalud REPS | `reps_prestadores`, `reps_sedes`, `reps_servicios`, `reps_capacidad`, `reps_medidas_seguridad`, `reps_sanciones` | Mensual |
| Calidad del agua (IRCA) | INS SIVICAP | `irca` | Mensual |
| Aseguramiento | MinSalud BDUA | `afiliacion` | Mensual |
| Entidades intervenidas | SuperSalud | `supersalud_ips_intervenidas`, `supersalud_eps_intervenidas` | Mensual |
| Indicadores epidemiológicos | INS PDFs | `ins_mortalidad_materna`, `ins_dengue`, `ins_sifilis_congenita`, `ins_mortalidad_menores5`, `ins_violencia_genero`, `ins_intento_suicidio`, `ins_desnutricion_aguda` | Por periodo epidemiológico (13/año) |
| Desempeño territorial | DIFT 18 | `dift18_departamento`, `dift18_municipio` | Anual |

**Vistas consolidadas:** `v_metricas_municipio` (1,123 filas) y `v_metricas_departamento` (33 filas) — listas para joins desde la app.

---

## 🚀 Cómo levantarlo

### Cloud — Hugging Face Spaces
Ya desplegado. Para una réplica nueva: crear Space con SDK Streamlit, hacer push del repo. El YAML frontmatter de este README configura todo automáticamente.

### Docker (cualquier máquina con Docker)
```bash
docker compose up -d
# → http://localhost:8501
```
El contenedor descarga el DB (~129 MB) desde GitHub Releases en la primera petición.

### Local — Python directo
```bash
pip install -r requirements.txt
streamlit run dashboard/app.py
```

### Windows desktop (instalador automático)
Doble clic en `deploy/install.ps1` → instala Python si falta, configura tarea programada, crea acceso directo en el escritorio.

---

## 🛠️ Mantenimiento

El pipeline de datos se ejecuta una vez al mes para refrescar fuentes mensuales. Ver [MANTENIMIENTO.md](MANTENIMIENTO.md) para el runbook completo (qué es automático, qué requiere acción humana, cómo publicar la versión nueva del DB).

Para la arquitectura técnica del scraping ver [docs/WEBSCRAPING_GUIDE.md](docs/WEBSCRAPING_GUIDE.md) y el catálogo de indicadores en [docs/INDICADORES_FUENTES.md](docs/INDICADORES_FUENTES.md).

## 🏛️ Despliegue corporativo (SuperSalud)

Para desplegar en una VM corporativa con HTTPS + cron automatizado:

- **Lo que IT debe aprovisionar:** [docs/REQUISITOS_VM_IT.md](docs/REQUISITOS_VM_IT.md) (specs, red, DNS, TLS)
- **Cómo desplegarlo paso a paso:** [docs/DESPLIEGUE_SUPERSALUD.md](docs/DESPLIEGUE_SUPERSALUD.md) (~30 min)

Archivos clave para producción: `docker-compose.prod.yml`, `Caddyfile`, `.env.example`, `scripts/install_vm.sh`, `scripts/run_monthly_pipeline.sh`.

---

## 📐 Tamaños y requisitos

- **DB en disco:** 129 MB (slim, agregado por anio/dep/mun/sexo)
- **RAM mínima:** 1 GB (cabe en HF Spaces free, Streamlit Cloud, etc.)
- **Python:** 3.12+
- **Despliegue Docker image:** ~970 MB

---

## ⚠️ Limitaciones conocidas

| Fuente | Estado | Solución |
|---|---|---|
| **IRCA (SIVICAP)** | INS añadió scoring de comportamiento al reCAPTCHA; el scraper headless es rechazado. | Drop manual del CSV en `data/raw/irca_manual/` cada mes, **o** correr una vez `tools/setup_sivicap_session.py` para persistir cookies. |
| **INS desnutrición 2026** | INS migró la tabla geográfica del PDF a 3 bitmaps PNG (no extraíble sin OCR). | Datos 2025 intactos; 2026 sin breakdown departamental hasta que INS revierta el cambio o se integre OCR cloud. |
| **Afiliación abr/may/jun 2026** | MinSalud aún no publica el ZIP. | El scraper hace fallback al mes anterior automáticamente. |

---

## 👥 Contacto

Equipo Navinet Group · `claude.ilam@outlook.com`

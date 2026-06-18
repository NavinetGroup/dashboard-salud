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

Streamlit dashboard for the Colombian regional health report. Reads a pre-built
DuckDB database (downloaded from GitHub Releases on first request) and renders
indicators across all 33 departments and 1,123 municipalities.

## Sources
- DANE — Population projections 2018–2042
- MinSalud REPS — Health facilities, services, capacity, sanctions
- MinSalud BDUA — Health-insurance enrollment
- INS / SIVICAP — Water quality index (IRCA)
- INS — Epidemiological indicators (maternal mortality, dengue, etc.)
- SuperSalud — Intervened entities (IPS / EPS)

## Run locally

```bash
pip install -r requirements.txt
streamlit run dashboard/app.py
```

The dashboard auto-downloads the DuckDB file (~129 MB) from the GitHub Release
on first request and caches it in `data/informe_regional.duckdb`.

## Deploy

- **Hugging Face Spaces** — push this repo; the YAML frontmatter above is detected automatically.
- **Docker** — `docker compose up`
- **Windows desktop** — `deploy/install.ps1`

See `WEBSCRAPING_GUIDE.md` for the data pipeline architecture.

# Informe Regional de Salud — Supersalud

Tablero de caracterización territorial (diseño FCT de Supersalud Territoriales): una ficha por
departamento o municipio y cinco módulos (Demográficos, Salud pública, Aseguramiento, Prestación de
servicios y Financiamiento), con datos públicos de DANE, MSPS, ADRES, INS, CGR, DNP y Supersalud.

## Cómo funciona

```
Equipo de procesamiento (operador)                 Usuarios
─────────────────────────────────                  ────────
scrapers/  → descargan las fuentes                 Abrir Informe Regional.bat
pipeline/  → transforman, calculan y controlan     (versión portable, sin instalar nada)
             la calidad
pipeline/exportar.py → base del visor (~14 MB)  ─►  release de GitHub  ─►  el tablero la descarga
tools/publicar_datos.py                                                     solo al abrirse
```

- **Los datos se procesan solo en el equipo del operador.** El repositorio no trae datos: se generan
  localmente en `data/` (excluida de git).
- **Los usuarios reciben solo el visor:** Python embebido, el tablero y la base pequeña. Se actualiza
  automáticamente con cada publicación mensual; sin internet, se copia a mano el archivo nuevo en
  `app\data\actualizacion\`.

## Usuarios

1. Descomprima `InformeRegional_<versión>.zip` donde quiera (no requiere permisos de administrador).
2. Doble clic en **`Abrir Informe Regional.bat`**. Se abre el navegador con el tablero.
3. La versión de los datos aparece en la barra lateral. Detalles en `LEEME.txt` dentro del zip.

## Operador

| Cuándo | Qué |
|---|---|
| Una vez | `Preparar equipo.bat`, `gh auth login`, `Renovar sesion SIVICAP.bat` |
| Cada mes | `Actualizar datos.bat` (procesa, controla y ofrece publicar) |
| Cuando cambia el código del tablero | `.venv\Scripts\python.exe tools\build_portable.py` y entregar el zip nuevo |

## Documentación

- **[Manual de usuario](docs/MANUAL_USUARIO.md)** (también `docs/MANUAL_USUARIO.docx`): abrir el tablero,
  filtros, lectura de cada módulo, actualización, preguntas frecuentes.
- **[Manual técnico](docs/MANUAL_TECNICO.md)** (también `docs/MANUAL_TECNICO.docx`): arquitectura,
  instalación, operación mensual, cada fuente y su scraper, pipeline, métricas, controles de calidad,
  tablero, distribución, cómo extender o reproducir el sistema, solución de problemas.
- Fórmulas de Financiamiento: [docs/FINANCIAMIENTO_FORMULAS.md](docs/FINANCIAMIENTO_FORMULAS.md).

Los `.docx` se generan desde los `.md` con `.venv\Scripts\python.exe tools\build_docs.py`.

## Estructura

```
dashboard/        tablero (Streamlit): app.py, vistas por módulo, componentes y mapas DANE
pipeline/         transform → métricas → controles de calidad → publicar → exportar (runner.py)
scrapers/         una descarga por fuente; settings.py lee informe_regional.toml
tools/            publicar_datos.py, build_portable.py, build_geojson.py, build_docs.py, setup_sivicap_session.py
docs/             manuales (usuario y técnico), fórmulas de Financiamiento, investigación de fuentes, auditoría
requirements.txt            paquetes del visor
requirements-pipeline.txt   paquetes del procesamiento (incluye los del visor)
informe_regional.example.toml   plantilla de configuración local (carpeta de archivos manuales)
```

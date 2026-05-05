
# -*- coding: utf-8 -*-
"""
Scraper + Procesamiento REPS (IPS por departamento) — lector tolerante
Autor: Raúl Andres Camacho Cruz
Fecha: 2025-12-27

✅ Características:
- 🧹 Limpieza inicial de archivos viejos
- ⬇️ Descarga del CSV desde REPS
- 🧽 Lectura tolerante del CSV (repara filas con más/menos separadores)
- 🔎 Diagnóstico de columnas y clases de prestador
- 📊 Resumen por departamento: Pública / Privada / Mixta / Total_IPS
- 💾 Guardado de IPS_intermedio.csv y Resumen_IPS_por_departamento.csv
"""

import os
import time
import re
import unicodedata
import pandas as pd

# Selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options


# ------------------------------------------------------
# CONFIGURACIÓN INICIAL
# ------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = BASE_DIR  # Descargar aquí mismo

ARCHIVO_ENTRADA = os.path.join(DOWNLOAD_DIR, "Prestadores.csv")
ARCHIVO_SALIDA  = os.path.join(DOWNLOAD_DIR, "Resumen_IPS_por_departamento.csv")

URL_LOGIN    = "https://prestadores.minsalud.gov.co/habilitacion/"
URL_CONSULTA = "https://prestadores.minsalud.gov.co/habilitacion/consultas/habilitados_reps.aspx"


# ------------------------------------------------------
# UTILIDADES
# ------------------------------------------------------

def quitar_tildes(s: str) -> str:
    s = s or ""
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def limpia_texto(s: str) -> str:
    if s is None: return ""
    s = str(s)
    s = s.replace("\ufeff", "").replace("\xa0", " ")  # BOM / NBSP
    s = re.sub(r"\s+", " ", s)  # colapsar espacios
    return s.strip()

def esperar_descarga(desc_dir: str, objetivo_nombre: str, timeout: int = 180) -> str:
    """
    Espera la descarga real. Acepta .crdownload/.tmp. Renombra si hace falta.
    """
    print("⬇️ Esperando la descarga del CSV…")
    t0 = time.time()
    tmp_path = None
    objetivo = os.path.join(desc_dir, objetivo_nombre)

    while True:
        archivos = os.listdir(desc_dir)

        # Archivo final perfecto
        if objetivo_nombre.lower() in [f.lower() for f in archivos]:
            print("✅ Descarga detectada:", objetivo)
            return objetivo

        # Detectar archivo temporal de Chrome
        crs = [f for f in archivos if f.lower().endswith(".crdownload")]
        tmps = [f for f in archivos if f.lower().endswith(".tmp")]

        if crs:
            tmp_path = os.path.join(desc_dir, crs[0])
        elif tmps:
            tmp_path = os.path.join(desc_dir, tmps[0])

        if time.time() - t0 > timeout:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.rename(tmp_path, objetivo)
                    print("⚠️ Tiempo agotado. Renombrado temporal →", objetivo)
                    return objetivo
                except Exception as e:
                    raise TimeoutError(f"❌ La descarga no se completó y no fue posible renombrar el temporal: {e}")
            raise TimeoutError("❌ La descarga no se completó en el tiempo previsto.")
        time.sleep(1)


def leer_csv_tolerante(path: str, sep: str = "|", encoding: str = "latin1") -> pd.DataFrame:
    """
    🧽 Lector tolerante:
    - Lee el encabezado para conocer el número esperado de columnas (N).
    - Repara cada fila:
        * Si tiene > N campos: une los extras dentro del último campo.
        * Si tiene < N campos: rellena con vacíos hasta N.
    - Devuelve DataFrame con nombres originales (limpios).
    """
    print("🧽 Leyendo CSV con lector tolerante…")
    with open(path, "r", encoding=encoding, errors="replace") as f:
        # Leer encabezado
        header_line = f.readline().rstrip("\n\r")
        header_line = header_line.replace("\ufeff", "")
        # Split de encabezado
        raw_cols = header_line.split(sep)
        # Limpiar nombres de columnas
        cols = [limpia_texto(c) for c in raw_cols]
        N = len(cols)
        print(f"🔧 Encabezado detectado: {N} columnas")
        print("🔎 Primeras columnas:", cols[:12])

        # Acumular filas reparadas
        rows = []
        line_num_base = 1  # ya leímos el encabezado

        for idx, line in enumerate(f, start=1):
            line = line.rstrip("\n\r")
            parts = line.split(sep)
            if len(parts) == N:
                rows.append(parts)
            elif len(parts) > N:
                # Unir extras dentro del último campo
                fixed = parts[:N-1] + ["|".join(parts[N-1:])]  # conserva el '|' como texto
                rows.append(fixed)
            else:  # len(parts) < N
                fixed = parts + [""] * (N - len(parts))
                rows.append(fixed)

        df = pd.DataFrame(rows, columns=cols)
        return df


# ------------------------------------------------------
# LIMPIEZA PREVIA
# ------------------------------------------------------

print("🧹 Limpiando archivos previos…")
for f in os.listdir(DOWNLOAD_DIR):
    if f.lower().endswith(".csv") or f.lower().endswith(".tmp") or f.lower().endswith(".crdownload"):
        try:
            os.remove(os.path.join(DOWNLOAD_DIR, f))
        except Exception:
            pass


# ------------------------------------------------------
# CONFIGURAR CHROME (ventana oculta pero funcional)
# ------------------------------------------------------

chrome_options = Options()
chrome_options.add_argument("--window-position=-32000,-32000")   # Fuera del monitor
chrome_options.add_argument("--window-size=1920,1080")
chrome_options.add_argument("--force-device-scale-factor=1")
chrome_options.add_argument("--incognito")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_experimental_option("prefs", {
    "download.default_directory": DOWNLOAD_DIR,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": True
})

driver = webdriver.Chrome(options=chrome_options)
wait = WebDriverWait(driver, 30)

# Permitir descargas por DevTools
try:
    driver.execute_cdp_cmd("Page.setDownloadBehavior", {
        "behavior": "allow",
        "downloadPath": DOWNLOAD_DIR
    })
except Exception:
    pass


# ------------------------------------------------------
# LOGIN
# ------------------------------------------------------

print("🔍 Abriendo login…")
driver.get(URL_LOGIN)
time.sleep(2)

print("🔍 Ingresando al frame 'areawork'…")
driver.switch_to.frame("areawork")

# Cerrar modal si aparece
driver.execute_script("""
try {
    let m = document.querySelector('#exampleModal');
    if(m){
        m.style.display='none';
        m.classList.remove('show');
    }
    let b = document.querySelector('.modal-backdrop');
    if(b) b.remove();
    document.body.classList.remove('modal-open');
} catch(e){}
""")
time.sleep(1)

print("🔍 Haciendo login (usuario invitado)…")
btn_ingresar = wait.until(EC.element_to_be_clickable((By.ID, "Button1")))
btn_ingresar.click()
time.sleep(3)

driver.switch_to.default_content()


# ------------------------------------------------------
# CONSULTA Y EXPORT
# ------------------------------------------------------

print("🔍 Abriendo página de consultas…")
driver.get(URL_CONSULTA)
time.sleep(2)

print("🔍 Ejecutando consulta (Registro Actual)…")
btn_buscar = wait.until(EC.element_to_be_clickable((By.ID, "_ctl0_ibBuscarFtr")))
btn_buscar.click()
time.sleep(5)

print("🔍 Configurando separador '|'…")
sep = wait.until(EC.presence_of_element_located((By.ID, "_ctl0_ContentPlaceHolder1_tbSeparator")))
driver.execute_script("arguments[0].value='|';", sep)
time.sleep(1)

print("⬇️ Exportando CSV…")
btn_export = wait.until(EC.element_to_be_clickable((By.ID, "_ctl0_ContentPlaceHolder1_ibText")))
btn_export.click()

# ------------------------------------------------------
# ESPERAR DESCARGA
# ------------------------------------------------------

archivo_final = esperar_descarga(DOWNLOAD_DIR, "Prestadores.csv", timeout=180)
print("✅ Archivo descargado correctamente:", archivo_final)

driver.quit()


# ------------------------------------------------------
# PROCESAR CSV (LECTOR TOLERANTE)
# ------------------------------------------------------

print("🧹 Iniciando procesamiento del archivo…")

df = leer_csv_tolerante(archivo_final, sep="|", encoding="latin1")
print(f"✅ CSV cargado: {len(df):,} filas, {len(df.columns)} columnas")
print("🔎 Sample (3 filas) para validar alineamiento:")
print(df.head(3).to_string(index=False))

# Limpieza de valores clave
for c in ["depa_nombre","muni_nombre","clpr_nombre","naju_nombre"]:
    if c in df.columns:
        df[c] = df[c].apply(limpia_texto)

if "depa_nombre" in df.columns:
    df["depa_nombre"] = df["depa_nombre"].str.title()
if "muni_nombre" in df.columns:
    df["muni_nombre"] = df["muni_nombre"].str.title()
if "clpr_codigo" in df.columns:
    df["clpr_codigo"] = pd.to_numeric(df["clpr_codigo"].apply(limpia_texto), errors="coerce")

# Diagnóstico de clase
if "clpr_nombre" in df.columns:
    print("🔎 Conteo por clpr_nombre (top 10):")
    print(df["clpr_nombre"].value_counts(dropna=False).head(10).to_string())

if "clpr_codigo" in df.columns:
    print("🔎 Conteo por clpr_codigo:")
    print(df["clpr_codigo"].value_counts(dropna=False).sort_index().to_string())


# ------------------------------------------------------
# FILTRAR IPS (doble criterio: código==1 OR nombre contiene 'IPS')
# ------------------------------------------------------

print("🔍 Filtrando IPS (clpr_codigo==1 OR clpr_nombre contiene 'IPS')…")
if "clpr_codigo" not in df.columns and "clpr_nombre" not in df.columns:
    raise KeyError("❌ No se detectaron 'clpr_codigo' ni 'clpr_nombre' para filtrar IPS.")

mask_codigo = df["clpr_codigo"] == 1 if "clpr_codigo" in df.columns else pd.Series(False, index=df.index)
mask_nombre = df["clpr_nombre"].str.contains("IPS", case=False, na=False) if "clpr_nombre" in df.columns else pd.Series(False, index=df.index)
ips = df[mask_codigo | mask_nombre].copy()
print(f"✅ IPS filtradas: {len(ips):,} filas")

# Guardado intermedio (verificación)
intermedio = os.path.join(DOWNLOAD_DIR, "IPS_intermedio.csv")
ips.to_csv(intermedio, index=False, encoding="utf-8")
print(f"💾 CSV intermedio guardado: {intermedio}")

if ips.empty:
    print("⚠️ No se encontraron IPS con los criterios. Revisa el CSV (clpr_codigo=1 o clpr_nombre contiene 'IPS').")


# ------------------------------------------------------
# NORMALIZAR NATURALEZA JURÍDICA (Pública / Privada / Mixta)
# ------------------------------------------------------

def normaliza_nat(x: str) -> str | None:
    base = quitar_tildes(limpia_texto(x)).lower()
    if base == "publica": return "Pública"
    if base == "privada": return "Privada"
    if base == "mixta":   return "Mixta"
    # (Opcional) if base in ("ese","empresa social del estado"): return "ESE"
    return None

if "naju_nombre" in ips.columns:
    ips["naju_nombre"] = ips["naju_nombre"].apply(normaliza_nat)
    print("🔎 Diagnóstico naturaleza jurídica (normalizada):")
    print(ips["naju_nombre"].value_counts(dropna=False).to_string())
else:
    ips["naju_nombre"] = None
    print("⚠️ 'naju_nombre' no está disponible; el resumen puede salir con ceros.")


# ------------------------------------------------------
# GENERAR RESUMEN POR DEPARTAMENTO
# ------------------------------------------------------

print("📊 Generando resumen por departamento (Privada, Pública, Mixta)…")

if ips.empty:
    resumen = pd.DataFrame(columns=["depa_nombre","Total_IPS","Pública","Privada","Mixta"])
else:
    tabla = pd.crosstab(ips["depa_nombre"], ips["naju_nombre"], dropna=True)

    # Asegurar columnas presentes
    for cat in ["Pública","Privada","Mixta"]:
        if cat not in tabla.columns:
            tabla[cat] = 0

    tabla = tabla[["Pública","Privada","Mixta"]].fillna(0).astype(int)
    tabla["Total_IPS"] = tabla.sum(axis=1)

    resumen = (
        tabla.reset_index()
             [["depa_nombre","Total_IPS","Pública","Privada","Mixta"]]
             .sort_values(by="Total_IPS", ascending=False)
    )

print("🔎 Vista previa (primeros 10 departamentos):")
print(resumen.head(10).to_string(index=False))

print("💾 Guardando reporte final…")
resumen.to_csv(ARCHIVO_SALIDA, index=False, encoding="utf-8")

print("\n===================================")
print("✅ PROCESO COMPLETO")
print("→ Archivo:", ARCHIVO_SALIDA)
print("===================================\n")

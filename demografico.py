
# -*- coding: utf-8 -*-
import pandas as pd
import re
import unicodedata
from pathlib import Path

# ============================================================
# CONFIG: Rutas/URLs y hojas (elige LOCAL o URL)
# ============================================================

USE_URLS = True  # True -> lee directo desde la web del DANE; False -> usa rutas locales

# --- URLs oficiales DANE ---
URL_AGE = 'https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Municipal/PPED-AreaSexoEdadMun-2018-2042_VP.xlsx'  # [1](https://www.dane.gov.co/index.php/estadisticas-por-tema/demografia-y-poblacion/proyecciones-de-poblacion)
URL_ETH = 'https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Nacional/anex-DCD-Proypoblacion-PerteneniaEtnicoRacialmun.xlsx'  # [2](https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Nacional/anex-DCD-Proypoblacion-PerteneniaEtnicoRacialmun.xlsx)

# --- Rutas locales (si USE_URLS=False) ---
SRC_AGE_LOCAL = Path(r'C:\Users\Administrador\OneDrive\Personal Documents\7. Codes & Projects\Projects\Informe regional\PPED-AreaSexoEdadMun-2018-2042_VP.xlsx')
SRC_ETH_LOCAL = Path(r'C:\Users\Administrador\OneDrive\Personal Documents\7. Codes & Projects\Projects\Informe regional\anex-DCD-Proypoblacion-PerteneniaEtnicoRacialmun.xlsx')

# --- Hojas exactas ---
SHEET_AGE = 'PobMunicipalxÁreaSexoEdad'
SHEET_ETH = 'Municipal'

# ============================================================
# UTILIDADES
# ============================================================
def to_num(s):
    return pd.to_numeric(s, errors='coerce')

def normalize_name(s: str) -> str:
    """Quita BOM/NBSP, normaliza Unicode, colapsa y recorta espacios."""
    if s is None:
        return ''
    s = str(s)
    s = s.replace('\ufeff', '').replace('\u00A0', ' ')
    s = unicodedata.normalize('NFKC', s)
    s = ' '.join(s.split())
    return s.strip()

def detect_header_rows(df, key_any=('DP','COD_DPTO','DEPARTAMENTO')):
    """
    Detecta fila de encabezado (hr) y segunda fila (hr2) si hay encabezado multinivel.
    Busca la primera fila que contenga cualquiera de 'key_any' en cualquier columna.
    """
    dfn = df.fillna('')
    candidates = []
    for i in range(len(dfn)):
        row_vals = [normalize_name(v) for v in dfn.iloc[i].tolist()]
        if any(k in row_vals for k in key_any):
            candidates.append(i)
    if not candidates:
        raise RuntimeError('No se encontró la fila de encabezado.')
    hr = candidates[0]
    # Si la fila siguiente tiene medidas (Hombres/Mujeres por edades), tomarla como segundo nivel
    hr2 = None
    if hr + 1 < len(dfn):
        nxt = [normalize_name(v) for v in dfn.iloc[hr+1].tolist()]
        if any(x.startswith('Hombres ') or x.startswith('Mujeres ') or x == 'Total' for x in nxt):
            hr2 = hr + 1
    return hr, hr2

def fuse_headers(df, hr, hr2=None):
    """Fusiona encabezado 1/2 filas: usa la segunda si tiene contenido; si no, la primera."""
    h1 = df.iloc[hr].astype(str)
    if hr2 is not None:
        h2 = df.iloc[hr+1].astype(str)
        merged = [(normalize_name(b) if normalize_name(b) != '' else normalize_name(a)) for a, b in zip(h1, h2)]
    else:
        merged = [normalize_name(x) if pd.notna(x) else '' for x in h1]
    merged = [normalize_name(c) if normalize_name(c) != '' else None for c in merged]
    return merged

def slice_after_header(df, hr, hr2=None):
    start = hr + 1 if hr2 is None else hr2 + 1
    return df.iloc[start:].copy()

def dedupe_columns(df):
    """Evita colisiones de nombres duplicados tras fusionar encabezados."""
    counts = {}
    new_cols = []
    for c in df.columns:
        if c not in counts:
            counts[c] = 0
            new_cols.append(c)
        else:
            counts[c] += 1
            new_cols.append(f"{c}.{counts[c]}")
    df.columns = new_cols

# ============================================================
# 1) BASE TIDY: EDAD/SEXO (EXCLUYENDO ÁREA "TOTAL")
# ============================================================
# Cargar hoja específica SIN encabezado (por celdas combinadas)
if USE_URLS:
    df_age_raw = pd.read_excel(URL_AGE, sheet_name=SHEET_AGE, header=None, engine='openpyxl')  # [1](https://www.dane.gov.co/index.php/estadisticas-por-tema/demografia-y-poblacion/proyecciones-de-poblacion)
else:
    df_age_raw = pd.read_excel(SRC_AGE_LOCAL, sheet_name=SHEET_AGE, header=None, engine='openpyxl')

# Detectar encabezado multinivel y fusionarlo
hr_age, hr2_age = detect_header_rows(df_age_raw, key_any=('DP','COD_DPTO','DEPARTAMENTO'))
age_cols = fuse_headers(df_age_raw, hr_age, hr2_age)
age_df = slice_after_header(df_age_raw, hr_age, hr2_age)
age_df.columns = [normalize_name(c) if c is not None else '' for c in age_cols]
age_df.columns = [normalize_name(c) for c in age_df.columns]
dedupe_columns(age_df)

# Fallback por posición: primeras 6 columnas = [DP, DPNOM, MPIO, DPMP, AÑO, ÁREA GEOGRÁFICA]
expected_id = ['DP','DPNOM','MPIO','DPMP','AÑO','ÁREA GEOGRÁFICA']
if not all(col in age_df.columns for col in expected_id):
    n = len(age_df.columns)
    if n >= 6:
        pos_map = {}
        for i, name in enumerate(expected_id):
            pos_map[age_df.columns[i]] = name
        age_df.rename(columns=pos_map, inplace=True)

# Homologación adicional por alias (por si vinieran con etiquetas del libro étnico)
age_df.rename(columns={
    'COD_DPTO':'DP',
    'DEPARTAMENTO':'DPNOM',
    'COD_DPTO-MPIO':'MPIO',    # código municipio
    'MUNICIPIO':'DPMP',        # nombre municipio
    'AREA GEOGRAFICA':'ÁREA GEOGRÁFICA'
}, inplace=True)

# Verificación de claves mínimas
REQ_AGE = ['DP','DPNOM','MPIO','DPMP','AÑO','ÁREA GEOGRÁFICA']
missing_age = [c for c in REQ_AGE if c not in age_df.columns]
if missing_age:
    raise RuntimeError(f"Faltan columnas en Edad/Sexo: {missing_age}\nColumnas presentes: {list(age_df.columns)}")

# Filtrar registros válidos y excluir "Total"
age_df['DP_num'] = to_num(age_df['DP'])
age_df = age_df[age_df['DP_num'].notna()].drop(columns=['DP_num'])
age_df = age_df[age_df['ÁREA GEOGRÁFICA'].astype(str).str.strip() != 'Total']

# Detectar columnas Hombres/Mujeres por edad (0..100 y "100 años y más")
pat_age = re.compile(r'^(Hombres|Mujeres)\s+(\d{1,3})\s+año(?:s)?(?:\s+y\s+más)?$', re.IGNORECASE)
sexo_age_cols = [c for c in age_df.columns if isinstance(c, str) and pat_age.match(c)]
if not sexo_age_cols:
    raise RuntimeError("No se detectaron columnas de edades (p.ej. 'Hombres 0 años'). Revisa la hoja y encabezado.")

# Pasar a tidy
id_cols_age = ['DP','DPNOM','MPIO','DPMP','AÑO','ÁREA GEOGRÁFICA']
age_long = age_df.melt(id_vars=id_cols_age, value_vars=sexo_age_cols,
                       var_name='SEXO_EDAD', value_name='POBLACION')
m = age_long['SEXO_EDAD'].str.extract(pat_age)
age_long['SEXO'] = m[0].str.upper()
age_long['EDAD'] = m[1].astype(int)     # 0..100 (100 = 100+)
age_long['POBLACION'] = to_num(age_long['POBLACION'])
age_long = age_long.dropna(subset=['POBLACION','SEXO','EDAD'])
age_long['POBLACION'] = age_long['POBLACION'].astype(int)

final_age = age_long[['DP','DPNOM','MPIO','DPMP','AÑO','ÁREA GEOGRÁFICA','SEXO','EDAD','POBLACION']].copy()
final_age['AÑO'] = to_num(final_age['AÑO']).astype('Int64')
final_age.to_csv('pped_tidy.csv', sep='|', index=False, encoding='utf-8')

# ============================================================
# 2) BASE TIDY: PERTENENCIA ÉTNICO-RACIAL (EXCLUYENDO ÁREA "TOTAL")
# ============================================================
if USE_URLS:
    df_eth_raw = pd.read_excel(URL_ETH, sheet_name=SHEET_ETH, header=None, engine='openpyxl')  # [2](https://www.dane.gov.co/files/censo2018/proyecciones-de-poblacion/Nacional/anex-DCD-Proypoblacion-PerteneniaEtnicoRacialmun.xlsx)
else:
    df_eth_raw = pd.read_excel(SRC_ETH_LOCAL, sheet_name=SHEET_ETH, header=None, engine='openpyxl')

# Encabezado (una fila); mismo detector
hr_eth, hr2_eth = detect_header_rows(df_eth_raw, key_any=('COD_DPTO','DEPARTAMENTO','DP'))
eth_cols = fuse_headers(df_eth_raw, hr_eth, hr2_eth)
eth_df = slice_after_header(df_eth_raw, hr_eth, hr2_eth)
eth_df.columns = [normalize_name(c) if c is not None else '' for c in eth_cols]
eth_df.columns = [normalize_name(c) for c in eth_df.columns]
dedupe_columns(eth_df)

# Mapeo explícito a tus estándares:
# DP = COD_DPTO ; DPNOM = DEPARTAMENTO ; MPIO = COD_DPTO-MPIO ; DPMP = MUNICIPIO ; AÑO = AÑO ; ÁREA GEOGRÁFICA = ÁREA GEOGRÁFICA
MAP_ETH = {
    'COD_DPTO': 'DP',
    'DEPARTAMENTO': 'DPNOM',
    'COD_DPTO-MPIO': 'MPIO',    # código municipio
    'MUNICIPIO': 'DPMP',        # nombre municipio
    'AÑO': 'AÑO',
    'ÁREA GEOGRÁFICA': 'ÁREA GEOGRÁFICA',
    'AREA GEOGRAFICA': 'ÁREA GEOGRÁFICA',
    # grupos → estándar corto
    'Gitano(a) o Rrom': 'Gitana o Rrom',
    'Raizal del Archipiélago de San Andrés, Providencia y Santa Catalina': 'Raizal',
    'Palenquero(a) de San Basilio': 'Palenquera de San Basilio',
    'Negro(a), mulato(a), afrodescendiente, afrocolombiano(a)': 'Negra, mulata o afrocolombiana',
    'Ningún grupo étnico-racial': 'Ningún grupo'
}
eth_df.rename(columns={k: v for k, v in MAP_ETH.items() if k in eth_df.columns}, inplace=True)

# Verificación de claves mínimas
REQ_ETH = ['DP','DPNOM','MPIO','DPMP','AÑO','ÁREA GEOGRÁFICA']
missing_eth = [c for c in REQ_ETH if c not in eth_df.columns]
if missing_eth:
    raise RuntimeError(f"Faltan columnas en Étnico-Racial: {missing_eth}\nColumnas presentes: {list(eth_df.columns)}")

# Filtrar válidos y excluir "Total"
eth_df['DP_num'] = to_num(eth_df['DP'])
eth_df = eth_df[eth_df['DP_num'].notna()].drop(columns=['DP_num'])
eth_df = eth_df[eth_df['ÁREA GEOGRÁFICA'].astype(str).str.strip() != 'Total']

# Columnas de pertenencia (si alguna no existe, se pondrá 0 en el resumen)
perten_cols = [
    'Indígena',
    'Gitana o Rrom',
    'Raizal',
    'Palenquera de San Basilio',
    'Negra, mulata o afrocolombiana',
    'Ningún grupo'
]
cols_presentes = [c for c in perten_cols if c in eth_df.columns]
if not cols_presentes:
    raise RuntimeError("No se detectaron columnas de pertenencia étnico-racial. Revisa la hoja y encabezado.")

id_cols_eth = ['DP','DPNOM','MPIO','DPMP','AÑO','ÁREA GEOGRÁFICA']
eth_long = eth_df.melt(id_vars=id_cols_eth, value_vars=cols_presentes,
                       var_name='GRUPO', value_name='POBLACION')
eth_long['POBLACION'] = to_num(eth_long['POBLACION'])
eth_long = eth_long.dropna(subset=['POBLACION'])
eth_long['POBLACION'] = eth_long['POBLACION'].astype(int)

final_eth = eth_long[['DP','DPNOM','MPIO','DPMP','AÑO','ÁREA GEOGRÁFICA','GRUPO','POBLACION']].copy()
final_eth['AÑO'] = to_num(final_eth['AÑO']).astype('Int64')
final_eth.to_csv('pper_tidy.csv', sep='|', index=False, encoding='utf-8')

# ============================================================
# 3) RESUMEN DEMOGRÁFICO (DEPARTAMENTO x AÑO, con DP)
# ============================================================
# Totales por sexo (sumando EDAD y ambas áreas)
sex_tot = final_age.groupby(['DP','DPNOM','AÑO','SEXO'])['POBLACION'].sum().reset_index()
sex_pivot = sex_tot.pivot_table(index=['DP','DPNOM','AÑO'], columns='SEXO',
                                values='POBLACION', fill_value=0).reset_index()
sex_pivot.rename(columns={'HOMBRES':'Total hombres', 'MUJERES':'Total mujeres'}, inplace=True)
sex_pivot['Total población'] = sex_pivot['Total hombres'] + sex_pivot['Total mujeres']

# Totales étnicos (sumando ambas áreas, por grupo)
eth_tot = final_eth.groupby(['DP','DPNOM','AÑO','GRUPO'])['POBLACION'].sum().reset_index()
eth_pivot = eth_tot.pivot_table(index=['DP','DPNOM','AÑO'], columns='GRUPO',
                                values='POBLACION', fill_value=0).reset_index()
# Asegurar columnas
for c in ['Indígena','Gitana o Rrom','Raizal','Palenquera de San Basilio','Negra, mulata o afrocolombiana','Ningún grupo']:
    if c not in eth_pivot.columns:
        eth_pivot[c] = 0

eth_pivot['Total población con pertenencia étnica'] = (
    eth_pivot['Indígena'] +
    eth_pivot['Gitana o Rrom'] +
    eth_pivot['Raizal'] +
    eth_pivot['Palenquera de San Basilio'] +
    eth_pivot['Negra, mulata o afrocolombiana']
)

# Conteo de municipios (códigos MPIO únicos) por DP y Año
mun_count = final_age.groupby(['DP','DPNOM','AÑO'])['MPIO'].nunique().reset_index()
mun_count.rename(columns={'MPIO':'Total municipios'}, inplace=True)

# Unir y calcular %
summary = (sex_pivot
           .merge(eth_pivot, on=['DP','DPNOM','AÑO'], how='left')
           .merge(mun_count, on=['DP','DPNOM','AÑO'], how='left'))
summary['% población Étnica'] = (summary['Total población con pertenencia étnica'] /
                                 summary['Total población']).round(6)

# *** Incluir el código del departamento (DP) en el output ***
summary_final = summary[[
    'AÑO','DP','DPNOM','Total municipios','Total hombres','Total mujeres','Total población',
    'Total población con pertenencia étnica','% población Étnica',
    'Indígena','Gitana o Rrom','Raizal','Palenquera de San Basilio','Negra, mulata o afrocolombiana'
]].copy()

summary_final.rename(columns={
    'AÑO':'Año',
    'DP':'Código Departamento',
    'DPNOM':'Departamento',
    'Indígena':'# Indígena',
    'Gitana o Rrom':'# Gitana o Rrom',
    'Raizal':'# Raizal',
    'Palenquera de San Basilio':'# Palenquera de San Basilio',
    'Negra, mulata o afrocolombiana':'# Negra, mulata o afrocolombiana'
}, inplace=True)

summary_final.to_csv('resumen_demografico.csv', sep='|', index=False, encoding='utf-8')
print('OK -> pped_tidy.csv | pper_tidy.csv | resumen_demografico.csv')

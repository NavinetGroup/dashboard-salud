# Manual de usuario — Informe Regional de Salud

Tablero de caracterización territorial del sistema de salud, en el formato de la Ficha de
Caracterización Territorial (FCT) de Supersalud Territoriales. Muestra, para cada departamento o
municipio de Colombia, los indicadores de cinco módulos: Demográficos, Salud pública,
Aseguramiento, Prestación de servicios y Financiamiento.

Este manual es para quien **consulta** el tablero. Quien procesa y publica los datos cada mes tiene
su propia guía: el Manual técnico.

---

## 1. Instalación y apertura

El tablero se entrega como un archivo comprimido `InformeRegional_<versión>.zip`. No instala nada
en el equipo ni requiere permisos de administrador.

**Requisitos:** Windows 10 u 11 de 64 bits y un navegador (Edge, Chrome o Firefox). Internet es
opcional: solo se usa para buscar datos más recientes.

1. Copie el zip a una carpeta de su equipo (por ejemplo `Documentos`) y **descomprímalo** (clic
   derecho → *Extraer todo*). No lo abra directamente desde el zip ni desde una carpeta de red lenta.
2. Entre a la carpeta `InformeRegional` y haga doble clic en **`Abrir Informe Regional.bat`**.
3. Se abre una ventana negra y, unos segundos después, el navegador con el tablero.
4. **Mantenga la ventana negra abierta** mientras use el tablero. Para salir, cierre esa ventana.

Si Windows muestra el aviso "Windows protegió su PC" (SmartScreen) la primera vez, pulse *Más
información* → *Ejecutar de todas formas*. El tablero funciona por completo en su equipo; no envía
datos a ningún sitio.

Si el navegador no se abre solo, copie en él la dirección que aparece en la ventana negra
(`http://localhost:8765` o un número cercano).

---

## 2. La pantalla

- **Barra lateral (izquierda, verde oscuro):** el logo, el menú de páginas y, abajo, el panel
  **FILTROS**. Al final aparece la versión de los datos cargados (`Datos: versión 2026.10.14-0830`).
- **Área principal:** la página elegida. Cada página empieza con un encabezado del color de su
  módulo, con la ruta `Colombia › Departamento › Municipio · periodo`.

El tablero se ve mejor en una ventana amplia (pantalla de 1366 px de ancho o más). En ventanas
estrechas las tarjetas se reorganizan en menos columnas.

---

## 3. Filtros

Los filtros se aplican a todas las páginas a la vez.

| Filtro | Qué hace |
|---|---|
| **Año de referencia** | Año de los datos. Se ofrecen los años para los que el tablero tiene datos |
| **Mes de referencia** | *Último disponible* muestra el dato más reciente del año; un mes concreto muestra los datos con corte en ese mes (afiliación, IRCA, financiamiento) y el periodo epidemiológico que termina en él |
| **Departamento** | Siempre hay uno elegido |
| **Municipio** | *— Todo el departamento —* muestra las cifras departamentales; un municipio muestra las suyas |

Cada fuente tiene su propia periodicidad, así que **cada tarjeta indica el periodo de sus datos**
("Datos: SEPTIEMBRE 2026", "Datos: 2026 PE IX", "Datos: 2026 sem. 1–36"). El mes elegido es un
tope: la tarjeta muestra lo último publicado hasta ese mes.

Cuando un indicador no existe a nivel municipal (por ejemplo, las EPS intervenidas o la
evaluación de la vigilancia), la tarjeta muestra el valor del departamento y lo dice en una nota:
"Valor de Antioquia".

---

## 4. Cómo leer una tarjeta

Cada indicador es una tarjeta con:

- **Número y título** del indicador, en el orden de la FCT.
- **Icono** en un círculo del color del módulo.
- **Valor** y su unidad (`hab.`, `%`, `por 100.000 hab.`…). `N/D` significa que no hay dato para ese
  territorio y periodo.
- **Recuadro de tendencia**: compara con el mismo periodo del año anterior.
  - Verde: cambió en la dirección favorable (por ejemplo, menos mortalidad o más cobertura).
  - Rojo: cambió en la dirección desfavorable.
  - Ámbar: sin cambio apreciable, o un indicador sin dirección "buena" (por ejemplo, la población).
  - `+0,8 %` es un cambio relativo; `+1,2 pp` es una diferencia en puntos porcentuales; `+12` es
    una diferencia en unidades.
  - Si no hay dato comparable del año anterior, el recuadro no aparece.
- **Datos: periodo** y, cuando aplica, una **nota** (porcentaje del total, número de casos, municipios
  sobre los que se calculó, etc.).
- Al pasar el ratón sobre la tarjeta aparece la **fuente** del dato.

Las tarjetas grises con el rótulo **Fuente pendiente** corresponden a indicadores de la FCT cuya
información no es pública y debe suministrarla Supersalud o el INS (ver la sección 7).

---

## 5. Páginas

### Inicio

Portada con una franja por módulo. Haga clic en una franja para ir a la página. También puede usar
el menú de la barra lateral.

### Ficha territorial

Resumen de una página: una franja por módulo con sus indicadores principales (4 o 5 por módulo),
en el orden de la FCT. Es la vista pensada para imprimir o presentar.

### Demográficos

- Población total, hombres, mujeres y población con pertenencia étnica, con su porcentaje del total.
- **Localización territorial:** tres mapas: Colombia con el departamento resaltado, el departamento
  con sus municipios y, si eligió un municipio, el municipio y sus alrededores.
- Distribución por sexo (dona) y composición étnica (barras y tabla), según las proyecciones del
  DANE con base en el Censo 2018.

### Salud pública

Once indicadores de la FCT. Las tasas se acumulan desde el inicio del año hasta el periodo indicado,
y la tendencia compara con el mismo periodo del año anterior.

| # | Indicador | Lectura |
|---|---|---|
| 1 | Razón de mortalidad materna | Muertes maternas por 100.000 nacidos vivos (boletín INS) |
| 2 | Incidencia de sífilis congénita | Casos por 1.000 nacidos vivos + muertes fetales (SIVIGILA; denominador DANE) |
| 3 | Prevalencia de desnutrición aguda en menores de 5 años | Casos por cada 100 menores de 5 años (SIVIGILA) |
| 4 | Tasa de mortalidad por desnutrición en menores de 5 años | Por 100.000 menores de 5 años (SIVIGILA) |
| 5 | IRCA | Índice de riesgo de la calidad del agua, de 0 (sin riesgo) a 100. La escala muestra la banda: sin riesgo (<5), bajo (5–14), medio (14–35), alto (35–80), inviable sanitariamente (>80) |
| 6 | Incidencia de dengue grave | Por 100.000 habitantes (SIVIGILA) |
| 7 | Tasa de intento de suicidio | Por 100.000 habitantes (SIVIGILA) |
| 8 | Violencia de género e intrafamiliar | Por 100.000 habitantes (SIVIGILA) |
| 9 | Cumplimiento de estándares de calidad de los LSP | Fuente pendiente (INS) |
| 10 | Evaluación del desempeño de la vigilancia en salud pública | Promedio de cumplimiento de los subindicadores (0–100 %), con la dona de subindicadores que cumplen, cumplen parcialmente o no cumplen. Valor departamental |
| 11 | Capacidades básicas de vigilancia | Subindicador 8-1 de la misma evaluación. Valor departamental |

El recuadro **Convenciones** al final de la página explica las etiquetas de periodo. Un periodo con
"(preliminar)" indica que el INS aún no ha publicado la cifra definitiva.

### Aseguramiento

- 1 a 3: EPS que operan en el territorio (total, régimen contributivo, subsidiado).
- 4: EPS intervenidas por Supersalud (por la sede de la EPS; valor departamental).
- 5 y 6: afiliados al régimen subsidiado y al contributivo.
- 7: cobertura de afiliación (anillo). Tope en 100 %.
- Pirámide de afiliados por régimen, sexo y grupo de edad (BDUA, con su fecha de corte).
- 8 a 11: afiliados al régimen subsidiado sin Sisbén IV, poblaciones especiales, afiliados de oficio y
  no pobres no vulnerables, con una línea de tendencia mensual.

### Prestación de servicios

- 1 a 4: IPS habilitadas (total, públicas, privadas, mixtas) y su composición en la dona.
- 5: capacidad instalada (camas, consultorios, salas de cirugía, UCI de adultos y pediátricas).
- 6: IPS intervenidas por Supersalud (valor departamental).
- Estado de las intervenciones: fuente pendiente (Supersalud).

### Financiamiento

Once razones de ejecución presupuestal, en porcentaje:

- 1 a 3: ejecución del Fondo Local de Salud (compromisos y pagos frente al recaudo y a la apropiación).
- 4 a 7: ejecución de los recursos del SGP de salud pública y de subsidio a la oferta frente a la
  asignación del DNP.
- 8: cofinanciación del régimen subsidiado: lo girado en el año frente a la meta anual
  proporcional a los meses transcurridos.
- 9 a 11: Circular 030, pagos PNA/NPBS y pagos a migrantes: fuente pendiente (Supersalud).

Las notas de cada tarjeta muestran los montos en pesos. El texto bajo el encabezado indica el
alcance: el municipio, la gobernación (sin sus municipios) o, para Bogotá, el Fondo Financiero
Distrital de Salud.

---

## 6. Fuentes y periodicidad

| Fuente | Datos | Actualización |
|---|---|---|
| DANE — Proyecciones de población | Población por sexo y pertenencia étnica | Anual |
| DANE — Estadísticas vitales | Nacimientos y defunciones fetales | Anual (cifras definitivas) |
| MSPS — Cifras de afiliación | Afiliados por régimen y municipio, cobertura, Sisbén | Mensual |
| ADRES — BDUA | EPS por territorio, pirámide de afiliados | Mensual |
| MSPS — REPS | Prestadores habilitados y capacidad instalada | Mensual |
| Supersalud — Medidas especiales | IPS y EPS intervenidas | Mensual |
| INS — SIVIGILA | Casos por evento y municipio | Anual (definitivo) y semanal (preliminar) |
| INS — Informes de evento | Razón de mortalidad materna | Por periodo epidemiológico (13 al año) |
| INS — SIVICAP | IRCA mensual por municipio | Mensual |
| INS — Evaluación del desempeño de la VSP | Indicadores 10 y 11 de Salud pública | Trimestral |
| CGR — CUIPO | Ejecución presupuestal en salud | Trimestral |
| DNP — SICODIS | Asignaciones del SGP | Anual |
| MSPS y ADRES | Meta y giros de cofinanciación del régimen subsidiado | Mensual |

---

## 7. Indicadores con fuente pendiente

La FCT incluye información que no está publicada en ninguna fuente abierta. Mientras Supersalud o
el INS la suministren, sus tarjetas aparecen en gris:

- Salud pública 9: cumplimiento de estándares de calidad de los laboratorios de salud pública (INS).
- Prestación: estado de las intervenciones (el listado público solo indica que la medida existe).
- Financiamiento 9, 10 y 11: Circular 030 de 2013, pagos PNA y NPBS, pagos a migrantes no regulares.

---

## 8. Actualización de los datos

Los datos se procesan y publican una vez al mes. El tablero se actualiza solo al abrirse (y cada 6
horas si queda abierto), por dos vías:

- **Carpeta compartida (SharePoint).** El equipo que procesa los datos deja la base nueva en una
  biblioteca de SharePoint (`Informe Regional` → `Datos`). Basta con tener esa biblioteca sincronizada
  en su equipo con OneDrive: el tablero la encuentra solo, sea cual sea su usuario. Si la biblioteca
  tiene otro nombre, quien le entregó el tablero habrá ajustado la ruta en
  `InformeRegional\app\informe_regional.toml`.
- **Internet.** Busca la última versión publicada en la dirección configurada (`url_actualizacion`);
  si es más nueva que la suya, la descarga (unos 14 MB), la verifica y la instala.

En ambos casos aparece el aviso "Datos actualizados a la versión …" y la versión nueva en la barra
lateral. Si ninguna de las dos vías está disponible (sin red, carpeta sin sincronizar), sigue
mostrando la versión que tiene y la barra lateral indica "No se pudo comprobar si hay datos más
recientes".

**Actualización manual:** si le comparten el archivo `informe_regional_visor.duckdb` (por correo o
USB), cópielo en la carpeta `InformeRegional\app\data\actualizacion\` y vuelva a abrir el tablero. El
archivo se instala y desaparece de esa carpeta.

El tablero nunca retrocede a una versión anterior ni instala un archivo dañado.

---

## 9. Preguntas frecuentes

**El navegador no se abre.** Copie en el navegador la dirección que muestra la ventana negra
(`http://localhost:8765` o similar).

**La ventana negra se cierra sola o muestra un error.** Descomprima el zip de nuevo en una carpeta
local (no en el zip, no en una unidad de red) y vuelva a intentarlo. Si el error persiste, envíe una
foto de la ventana al equipo que administra el tablero.

**Aparece "No hay datos para mostrar todavía".** La carpeta `app\data` no tiene datos. Conecte el equipo
a internet y recargue la página (F5), o use la actualización manual.

**Aparece "El archivo de datos está dañado o incompleto".** Use la actualización manual o conecte el
equipo a internet y recargue: el tablero descargará de nuevo la última versión.

**Una tarjeta muestra N/D.** La fuente no tiene dato para ese territorio y periodo (por ejemplo, un
municipio que el boletín del INS no lista). Pruebe el nivel departamental o un periodo anterior.

**El tablero se ve cortado o desordenado.** Amplíe la ventana del navegador o reduzca el zoom
(Ctrl y −). Si cambió de tamaño la ventana, recargue con F5.

**¿Puedo compartir el tablero?** Sí: entregue el zip. Cada persona lo descomprime en su equipo. Los
datos se actualizan solos en cada copia.

**¿Puedo imprimir o exportar?** Use la impresión del navegador (Ctrl+P) sobre la página deseada; la
Ficha territorial está pensada para eso. Los gráficos de Plotly permiten guardar la imagen desde su
menú al pasar el ratón.

**¿Cómo sé de cuándo son los datos?** La versión en la barra lateral es la fecha de publicación; cada
tarjeta indica el periodo de su fuente.

---

## 10. Glosario

| Término | Significado |
|---|---|
| **BDUA** | Base de Datos Única de Afiliados (ADRES) |
| **EPS / IPS** | Entidad Promotora de Salud / Institución Prestadora de Servicios de Salud |
| **FLS** | Fondo Local de Salud (presupuesto de salud de la entidad territorial) |
| **IRCA** | Índice de Riesgo de la Calidad del Agua para consumo humano (0 = sin riesgo, 100 = inviable) |
| **LMA** | Liquidación Mensual de Afiliados (ADRES): giros del régimen subsidiado |
| **LSP** | Laboratorio de Salud Pública |
| **PE** | Periodo epidemiológico: 13 periodos de 4 semanas por año (PE I a PE XIII) |
| **REPS** | Registro Especial de Prestadores de Servicios de Salud |
| **SGP** | Sistema General de Participaciones (transferencias de la Nación) |
| **Sisbén IV** | Clasificación socioeconómica vigente para el régimen subsidiado |
| **SIVICAP** | Sistema de Información de la Vigilancia de la Calidad del Agua Potable (INS) |
| **SIVIGILA** | Sistema de Vigilancia en Salud Pública (INS) |
| **VSP** | Vigilancia en Salud Pública |

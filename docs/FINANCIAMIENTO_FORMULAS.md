# Financiamiento — fórmulas propuestas para validar con Supersalud

*Fecha: 2026-10-13. Estado: los indicadores 1 a 8 ya están calculados y publicados en el dashboard, pero son una propuesta. Cada punto marcado como **Pregunta** necesita confirmación del cliente antes de darlos por oficiales.*

## Fuentes

| Fuente | Qué aporta | Frecuencia |
|---|---|---|
| **CUIPO** (Contraloría General, datos.gov.co): ingresos `9axr-9gnb`, gastos `4f7r-epif`, programación `d9mu-h6ar` | Recaudo, apropiación, compromisos y pagos de cada entidad territorial | Trimestral, acumulado en el año (marzo, junio, septiembre, diciembre). Disponible desde 2023 |
| **SICODIS** (DNP) | Asignación SGP del año por participación: salud pública, subsidio a la oferta y régimen subsidiado | Anual, con distribuciones parciales durante el año |
| **Matriz de continuidad** (MSPS), "Monto estimado de recursos del régimen subsidiado" | Meta anual de esfuerzo propio que cada municipio y departamento se compromete a girar al régimen subsidiado | Anual, con ajustes de SGP y de Coljuegos durante el año. Se usa la versión más reciente |
| **Resultado LMA** (ADRES), Liquidación Mensual de Afiliados | Esfuerzo propio efectivamente girado cada mes, por municipio, EPS y fuente | Mensual. El mes en curso se publica a comienzos de ese mes |

CUIPO reemplazó al FUT; la etiqueta "SIHO – FUT" del diseño corresponde hoy a CUIPO.

## Definiciones de base

- **Ingresos del Fondo Local de Salud (FLS):** recaudo de las filas de ingresos que cumplen alguna de dos condiciones:
  - tienen detalle sectorial *FLS-…* (salud pública, aseguramiento, prestación de servicios, otros gastos);
  - su fuente de financiación es de salud (SGP salud, SGSSS y sus rendimientos o recursos del balance).

  Hacen falta las dos condiciones porque cerca del 20 % de los municipios no marca el detalle FLS.
- **Gasto en salud:** filas de gastos con código programático MGA 19xx (Salud y Protección Social) o detalle sectorial 19.xx.
  - El detalle sectorial no se diligenció en 2023.
  - Solo cuenta el gasto de la vigencia actual (incluye vigencias futuras de la vigencia actual).
  - No cuentan las reservas ni las cuentas por pagar de años anteriores.
- **SGP del año:** fuentes de la vigencia `1.2.4.2.02` (salud pública) y `1.2.4.2.04` (subsidio a la oferta). No cuentan los recursos del balance de años anteriores.
- **Cobertura territorial:**
  - Municipio: su propio presupuesto.
  - Departamento: el presupuesto de la gobernación, sin sumar sus municipios.
  - Nacional: la suma de todas las entidades.
- **Bogotá:** se usa el Fondo Financiero Distrital de Salud para los indicadores FLS, y el distrito para los indicadores SGP, porque el distrito es quien ejecuta el SGP de salud pública.
- **Norte de Santander:** se usa el Instituto Departamental de Salud. Caldas y Nariño ya consolidan su instituto de salud dentro de la gobernación.

## Indicadores

| # | Indicador (diseño FCT) | Fórmula propuesta | Valor nacional, junio 2026 |
|---|---|---|---|
| 1 | Compromisos vs. ingresos FLS | compromisos en salud ÷ ingresos FLS recaudados | 108,5 % |
| 2 | Compromisos FLS | compromisos en salud ÷ apropiación definitiva en salud | 53,6 % |
| 3 | Pagos vs. ingresos | pagos en salud ÷ ingresos FLS recaudados | 87,8 % |
| 4 | SGP salud pública — compromisos | compromisos con fuente SGP salud pública ÷ asignación SICODIS de salud pública del año | 69,6 % |
| 5 | SGP salud pública — pagos | pagos con fuente SGP salud pública ÷ asignación SICODIS de salud pública | 27,6 % |
| 6 | SGP subsidio a la oferta — compromisos | compromisos con fuente SGP subsidio a la oferta ÷ asignación SICODIS de subsidio a la oferta | 30,4 % |
| 7 | SGP subsidio a la oferta — giros | recaudo (giros recibidos) de SGP subsidio a la oferta ÷ asignación SICODIS | 46,6 % |
| 8 | Cumplimiento de la meta de cofinanciación del régimen subsidiado | esfuerzo propio girado de enero al mes de corte (LMA) ÷ (meta anual de la matriz MSPS × meses ÷ 12). 100 % significa que la entidad va al día con su meta | 96,6 % a octubre de 2026 (101,1 % en todo 2025) |
| 9–11 | Circular 030, PNA/NPBS, migrantes | Información interna: debe entregarla Supersalud o MSPS | — |

**Detalle del indicador 8.**
- *Esfuerzo propio* incluye Coljuegos, las rentas cedidas que gira la ADRES (licores, cigarrillo, cerveza, juegos de suerte y azar) y lo que la entidad territorial gira directamente a la EPS. Son los mismos componentes de la "Matriz ejecutada" del MSPS.
- Verificación: la suma de enero a diciembre de 2025 en la LMA coincide al peso con la Matriz ejecutada 2025 en los 1.107 municipios, tanto en el componente municipal como en el departamental.
- Municipio: su esfuerzo municipal.
- Departamento: el esfuerzo departamental. Incluye las áreas no municipalizadas de Amazonas, Guainía y Vaupés. Bogotá se mide con su esfuerzo distrital.
- Nacional: suma del esfuerzo municipal y el departamental.

Como los valores de los indicadores 1 a 7 son acumulados en el año, suben de un trimestre a otro. La flecha de tendencia compara con el mismo trimestre del año anterior, en puntos porcentuales.

## Preguntas para Supersalud

1. **Indicador 1:**
   - **Pregunta:** ¿el denominador es el *recaudo* o el *presupuesto definitivo de ingresos*?
   - **Contexto:** con recaudo, el valor supera el 100 % a mitad de año, porque los compromisos se adquieren contra la apropiación y no contra la caja.
2. **Indicador 2:**
   - **Pregunta:** ¿"compromisos FLS" se mide sobre la apropiación definitiva, o sobre la inicial?
3. **Indicadores 4 a 7:**
   - **Pregunta:** ¿el denominador es la asignación SICODIS del año (la que usamos) o el recaudo?
   - **Contexto:** el SGP se gira en doceavas, así que en junio lo esperable es cerca del 50 % girado.
4. **Indicador 7:**
   - **Pregunta:** ¿"giros" son los recursos que recibe la entidad (lo que usamos), o los giros directos que el MSPS hace a las ESE?
   - **Contexto:** si son los giros directos a las ESE, necesitamos el reporte de giros del MSPS.
5. **Indicador 8:**
   - **Pregunta:** ¿la meta debe prorratearse por meses (lo que hacemos), o compararse con la meta anual completa? En el segundo caso, el indicador muestra el avance hacia el 100 % a fin de año.
   - **Pregunta:** ¿se usa la última versión de la matriz (con ajustes) o la proyectada inicial?
6. **Departamentos:**
   - **Pregunta:** ¿el indicador departamental debe ser el de la gobernación sola (como está hoy) o el de la gobernación más sus municipios?
7. **Arauca:**
   - **Pregunta:** ¿pueden suministrar estos datos por otra vía?
   - **Contexto:** la Unidad Administrativa Especial de Salud de Arauca no reporta a CUIPO, así que la gobernación aparece con ingresos FLS en cero.

## Limitaciones conocidas

- CUIPO llega con unos tres o cuatro meses de rezago. En octubre de 2026, el último trimestre publicado es junio de 2026.
- El 98 % de los municipios reporta en cada trimestre (1.101 de 1.123 en junio de 2026). Los que no reportan aparecen como "N/D".
- Muchas gobernaciones registran 0 % de compromisos de subsidio a la oferta a junio, pese a haber recibido los giros. Es lo que reportan, no un error del cálculo, y conviene confirmarlo con el cliente.

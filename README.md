# Estudio de ocupación del espectro radioeléctrico · 840 – 860 MHz

**Examen 3 — Internet de las Cosas** · ETL y toma de decisiones
Campaña de monitoreo móvil en el sector occidental de Medellín, para la **Agencia Nacional del Espectro (ANE)**.

Sistema completo de extracción, transformación y carga de una campaña de medición de radiofrecuencia, con modelo de toma de decisiones y dashboard interactivo sobre servidor web.

---

## Tabla de contenido

1. [El problema](#1-el-problema)
2. [Requisitos e instalación](#2-requisitos-e-instalación)
3. [Cómo ejecutarlo](#3-cómo-ejecutarlo)
4. [Arquitectura](#4-arquitectura)
5. [Estructura del proyecto](#5-estructura-del-proyecto)
6. [La fuente de datos](#6-la-fuente-de-datos)
7. [El proceso ETL en detalle](#7-el-proceso-etl-en-detalle)
8. [Resultados: calidad de los datos](#8-resultados-calidad-de-los-datos)
9. [Resultados: la ruta](#9-resultados-la-ruta)
10. [Resultados: incidencia de la temperatura](#10-resultados-incidencia-de-la-temperatura)
11. [Resultados: ocupación por canal](#11-resultados-ocupación-por-canal)
12. [Resultados: modelo de decisión](#12-resultados-modelo-de-decisión)
13. [Resultados: fuentes extrapoladas (bonificación)](#13-resultados-fuentes-extrapoladas-bonificación)
14. [El dashboard](#14-el-dashboard)
15. [Artefactos generados](#15-artefactos-generados)
16. [Decisiones de diseño y limitaciones](#16-decisiones-de-diseño-y-limitaciones)
17. [Solución de problemas](#17-solución-de-problemas)

---

## 1. El problema

Una estación móvil de monitoreo recorrió el occidente de Medellín midiendo la ocupación de la banda
celular de **840 a 860 MHz** con un receptor USRP controlado por GNU Radio. El objetivo del estudio es
determinar el **nivel de contaminación del espectro** para que el Ministerio TIC defina el plan de
frecuencias de la ciudad.

La banda se divide en **cuatro canales consecutivos de 5 MHz**:

| Canal | Banda |
|:---:|---|
| A | 840 – 845 MHz |
| B | 845 – 850 MHz |
| C | 850 – 855 MHz |
| D | 855 – 860 MHz |

Criterios del estudio:

- Un canal se considera **ocupado / contaminado** si supera **−60 dBm**
- La potencia media de ocupación se calcula con la **sumatoria de Parseval** para señales discretas

Entregables: un **informe técnico** (25 pts), un **dashboard interactivo sobre servidor web** (25 pts) y,
como bonificación, la **estimación por extrapolación** de la ubicación geográfica de las fuentes.

---

## 2. Requisitos e instalación

### Entorno verificado

| Componente | Versión probada | Mínimo requerido |
|---|---|---|
| Python | 3.13.15 | 3.9 |
| numpy | 2.5.3 | 1.24 |
| pandas | 3.0.6 | 2.0 |
| scipy | 1.18.1 | 1.10 |
| pyarrow | 25.0.1 | 12.0 |
| matplotlib | 3.11.2 | 3.7 |
| plotly | 7.1.0 | 5.18 |
| dash | 4.4.1 | 2.14 |
| python-docx | 1.2.0 | 1.0 |
| Flask | 3.1.3 | *(lo arrastra dash)* |

### Para qué se usa cada dependencia

| Paquete | Uso en el proyecto |
|---|---|
| **numpy** | Álgebra vectorizada, conversiones dBm ↔ mW, sumatoria de Parseval, regresión OLS implementada a mano |
| **pandas** | Dataframes del datalake y persistencia en Parquet/CSV |
| **scipy** | `interpolate.griddata` (mallas de los mapas de calor), `optimize.minimize` (localización de fuentes), `stats` (correlaciones y pruebas de hipótesis) |
| **pyarrow** | Backend de Parquet de las tres capas del datalake |
| **matplotlib** | Las 10 figuras PNG que se embeben en el informe Word |
| **plotly** | Gráficas interactivas y mapas del dashboard |
| **dash** | Servidor web y sistema de *callbacks* (usa Flask por debajo) |
| **python-docx** | Generación del documento `.docx` entregable |

### Instalación

```bash
pip install -r requirements.txt
```

O directamente:

```bash
pip install numpy pandas scipy pyarrow matplotlib plotly dash python-docx
```

> **Conexión a internet:** solo la necesita el dashboard, para descargar los *tiles* de OpenStreetMap
> que sirven de cartografía base. No requiere ningún token ni cuenta. Todo el resto del pipeline
> funciona sin red.

---

## 3. Cómo ejecutarlo

### Paso 1 — Procesar todo

```bash
python run_pipeline.py
```

Ejecuta las nueve etapas en orden y tarda unos **13 segundos**. Deja el datalake poblado, las 10 figuras
en `informe/figuras/` y el documento Word listo.

Salida esperada:

```
ETAPA 1 - EXTRACCION (capa bronce)              [OK]
ETAPA 2 - PERFILADO DE CALIDAD                  [OK]
ETAPA 3 - TRANSFORMACION E IMPUTACION           [OK]
ETAPA 4 - INDICADORES DE PARSEVAL (capa oro)    [OK]
ETAPA 5 - ANALISIS DE INCIDENCIA TERMICA        [OK]
ETAPA 6 - MODELO DE TOMA DE DECISIONES          [OK]
ETAPA 7 - EXTRAPOLACION DE FUENTES              [OK]
ETAPA 8 - GENERACION DE FIGURAS                 [OK]
ETAPA 9 - INFORME TECNICO EN WORD               [OK]
PIPELINE COMPLETADO EN 13.3 s
```

Para reprocesar sin regenerar figuras ni informe (más rápido):

```bash
python run_pipeline.py --sin-informe
```

### Paso 2 — Levantar el dashboard

```bash
python dashboard/app.py
```

Abrir **http://127.0.0.1:8050** en el navegador.

> El dashboard lee el datalake al arrancar, así que **el paso 1 debe haberse ejecutado antes**.

### Ejecutar una etapa suelta

Cada módulo es ejecutable por separado e imprime su propio informe por consola. **Hay que lanzarlos
desde su propia carpeta**, porque los módulos de `etl/` se importan entre sí por nombre:

```bash
cd etl && python extract.py
```

```bash
cd etl && python quality.py
```

```bash
cd etl && python transform.py
```

```bash
cd etl && python indicators.py
```

```bash
cd etl && python temperatura.py
```

```bash
cd modelo && python decision.py
```

```bash
cd modelo && python extrapolacion.py
```

```bash
cd informe && python figuras.py
```

```bash
cd informe && python generar_informe.py
```

Cada etapa depende de las anteriores: `indicators.py` necesita que `transform.py` ya haya escrito la
capa plata, y así sucesivamente. Si tienes dudas, `run_pipeline.py` las ejecuta todas en el orden
correcto.

---

## 4. Arquitectura

Sigue la arquitectura de referencia de la asignatura — *sensores → colector → ETL → almacenamiento →
modelo → visualización* — implementada como un **datalake de tres capas** (patrón *medallion*):

```
   .txt del sensor          ┌──────────┐
   ANTENNA1.csv      ──────►│  BRONCE  │  crudo, sin modificar, auditable
                            └────┬─────┘
                                 │  quality.py  (diagnostica, NO modifica)
                                 │  transform.py (corrige e imputa)
                            ┌────▼─────┐
                            │  PLATA   │  limpio, validado, calibrado
                            └────┬─────┘  + bitácora de cada celda tocada
                                 │  indicators.py (Parseval)
                            ┌────▼─────┐
                            │   ORO    │  indicadores de negocio
                            └────┬─────┘
                   ┌─────────────┼─────────────┐
                   ▼             ▼             ▼
              decision.py   extrapolacion   dashboard
              (hipótesis     (fuentes)      (Dash/Flask)
               y acciones)                   informe (.docx)
```

**Por qué el diagnóstico va separado de la corrección:** el enunciado exige reportar *cuántos datos se
modificaron y por qué*. `quality.py` solo emite un dictamen por medición sin tocar nada;
`transform.py` consume ese dictamen y aplica las correcciones llevando una bitácora. Sin esa
separación, el número de imputaciones no sería trazable ni auditable.

**Por qué el dashboard no recalcula nada:** consume exclusivamente la capa oro. Si el ETL se vuelve a
ejecutar con datos nuevos, el dashboard los refleja sin tocar una línea de su código.

---

## 5. Estructura del proyecto

```
Parcial 3 - Iot/
│
├── run_pipeline.py                 Orquestador de las 9 etapas
├── requirements.txt                Dependencias
├── README.md                       Este archivo
├── Examen 03 2026 20.pdf           Enunciado
│
├── etl/
│   ├── config.py                   Parámetros globales: umbrales, canales, reglas, paletas
│   ├── extract.py             [1]  Lectura de los .txt y del S11 → capa BRONCE
│   ├── quality.py             [2]  11 reglas de validación y dictamen (no modifica nada)
│   ├── transform.py           [3]  Descarte, imputación y calibración → capa PLATA
│   ├── indicators.py          [4]  Sumatoria de Parseval por canal → capa ORO
│   └── temperatura.py         [5]  Correlación parcial, OLS y cota física del ruido térmico
│
├── modelo/
│   ├── decision.py            [6]  ISE + cascada de hipótesis → acciones para la ANE
│   └── extrapolacion.py       [7]  Multilateración RSS para localizar las fuentes
│
├── informe/
│   ├── figuras.py             [8]  Genera las 10 gráficas PNG
│   ├── generar_informe.py     [9]  Construye el documento Word
│   ├── figuras/                    01_ruta.png … 10_antena.png
│   └── Informe_ANE_Ocupacion_840_860MHz.docx
│
├── dashboard/
│   ├── app.py                      Servidor web Dash: 6 pestañas, 3 callbacks
│   └── estilo.py                   Sistema de diseño (paleta, tipografía, CSS)
│
├── datalake/
│   ├── bronce/                     medidas_crudas · antena_s11 · eje_frecuencias
│   ├── plata/                      medidas_limpias · banderas · bitácora · índices
│   └── oro/                        indicadores · perfil · decisiones · fuentes
│
├── datos/medidas_2026_20/          FUENTE ORIGINAL (no se modifica nunca)
│   ├── 001.txt … 061.txt           61 mediciones de la campaña
│   ├── medidaprueba.txt            2 capturas de verificación (se descartan)
│   ├── medidapureba2.txt
│   ├── ANTENNA1.csv                Barrido S11 de la antena (Agilent N9914A)
│   ├── medir_celular.py            Flowgraph GNU Radio que generó los datos
│   └── biblioteca.py               Bloque de muestreo del flowgraph
│
└── Presentaciones/                 Sesiones 7 a 10 del curso
```

---

## 6. La fuente de datos

Cada archivo `.txt` contiene **una sola fila con 1029 campos** separados por coma:

| Posiciones | Contenido |
|---|---|
| 0 – 1023 | Espectro de potencia en dBm, de 840 MHz a 860 MHz |
| 1024 | Temperatura del sensor (°C) |
| 1025 | Longitud |
| 1026 | Latitud |
| 1027 | Altura (m) |
| 1028 | Error de distancia del GPS (HDOP) |

**Geometría de la medida**, derivada del flowgraph `medir_celular.py`:

- FFT de **1024 puntos** sobre una tasa de muestreo de **20 MHz** → resolución de **19.53 kHz por bin**
- Frecuencia central **850 MHz**; tras el `fftshift` el bin 0 corresponde a 840 MHz
- Cada traza es una **retención de máximos sobre 100 barridos** (no un promedio)
- El espectro se calcula como `20·log10(|FFT(x)| / N)`, es decir ya viene normalizado

`ANTENNA1.csv` es el barrido del parámetro **S11 de la antena de monitoreo**, medido con un analizador
Agilent N9914A entre 700 y 950 MHz. Se usa para calibrar.

---

## 7. El proceso ETL en detalle

### Las 11 reglas de validación

| Regla | Qué detecta | Severidad |
|---|---|---|
| R1 ESTRUCTURA | Cardinalidad ≠ 1029 o campos no numéricos | descarte |
| R2 COMPLETITUD | NaN o infinitos en espectro o metadatos | imputable |
| R3 GPS_SIN_FIX | `lat = lon = 0` → el receptor GNSS no obtuvo solución | imputable |
| R4 GPS_FUERA_RANGO | Coordenadas o altura fuera del valle de Aburrá | imputable |
| R5 GPS_IMPRECISO | HDOP por encima de 2.0 | aviso |
| R6 RANGO_FISICO | Potencias fuera del rango útil del receptor | descarte |
| R7 NIVEL_ANOMALO | Traza desplazada en nivel (z-score robusto con MAD) | descarte |
| R8 TRAZA_PLANA | Desviación estándar nula → receptor congelado | descarte |
| R9 FUGA_LO_DC | Pico espurio en el bin central (offset DC del zero-IF) | imputable |
| R10 TEMP_OPERACION | Sensor fuera de su ventana térmica de operación | aviso |
| R11 NO_CAMPANA | Archivo de prueba, ajeno a la campaña | descarte |

### Las tres técnicas de corrección

**T1 · Fuga de oscilador local** — *interpolación lineal en potencia sobre el eje de frecuencia*

Fue el hallazgo más relevante del perfilado y **no era visible a simple vista**. El receptor del USRP es
de conversión directa (*zero-IF*): el desbalance de continua del mezclador y la fuga del oscilador
local se suman a la componente de continua de la señal en banda base. Tras el `fftshift` esa componente
cae exactamente en el **bin 512 = 850.000 MHz**, que es justo la **frontera entre los canales B y C**.

Se detectó en **28 de las 63 mediciones**, con excesos de hasta **+26.3 dB** sobre los bins vecinos. De
no corregirse se habría contabilizado como ocupación real, inflando simultáneamente el indicador de los
dos canales centrales.

La interpolación se ejecuta en **potencia lineal (mW), no en decibelios**: promediar dB equivale a una
media geométrica de potencias y subestimaría el nivel real de la envolvente.

**T2 · Georreferenciación** — *interpolación lineal sobre la secuencia de la ruta*

Dos mediciones tenían la posición inutilizable pero el espectro perfectamente válido. Como la estación
es móvil y recorre una trayectoria continua, la posición se reconstruye interpolando entre las
posiciones válidas anterior y posterior.

| Archivo | Longitud | Latitud | Altura |
|---|---|---|---|
| `008.txt` | 0.000000 → −75.600790 | 0.000000 → 6.226360 | 0.0 → 1545.0 |
| `017.txt` | −75.584725 → −75.586284 | 6.198835 → 6.199575 | 1565.0 → 1529.8 |

`008.txt` registró todo en cero con HDOP 4.4: la coordenada (0, 0) está en el golfo de Guinea, a 9000 km
del área de estudio. `017.txt` reportó HDOP **17.3**, más de diez veces el valor típico de la campaña.

**T3 · Calibración por desacople de antena** — *de-embedding del S11*

En la banda de estudio el S11 pasa de **−5.79 dB a 840 MHz** a **−8.65 dB a 860 MHz**: la antena está
desadaptada y, lo que importa aquí, **de forma dependiente de la frecuencia**.

De |Γ|² = 10^(S11/10) se obtiene la pérdida por desacople `L = −10·log10(1 − |Γ|²)`, que vale
**1.33 dB** en el extremo inferior y **0.64 dB** en el superior. Ese **gradiente de 0.69 dB**
penalizaba sistemáticamente al canal A frente al canal D y habría contaminado la comparación entre
bloques, que es justamente el objeto del estudio.

No es imputación sino **calibración determinista**. Su efecto no es despreciable: **1474 muestras**
cambian de lado respecto del umbral de ocupación de −60 dBm al aplicarla, es decir pasan de declararse
libres a declararse ocupadas o al revés.

### Por qué NO se censura el piso de ruido

Se evaluó sustituir por un valor constante las muestras más débiles —una transformación habitual en
estudios de ocupación— y **se decidió no hacerlo**, por dos razones:

1. **Los datos no ofrecen un punto de corte natural.** El histograma del espectro es prácticamente
   continuo, con la moda del ruido en torno a −67 dBm y sin un valle que separe el lóbulo de ruido del
   de señal. Cualquier umbral sería arbitrario y difícil de sostener frente a la pregunta de por qué
   ese valor y no otro.
2. **No cambiaría el resultado.** La potencia de Parseval es una suma en el dominio **lineal**,
   dominada por los bins fuertes: llevar un bin de −66 dBm hasta −95 dBm le resta a esa suma del orden
   de 10⁻⁷ mW frente a un total de 10⁻⁴ mW. Se comprobó numéricamente que censurar desplaza la potencia
   media de cada canal **menos de 0.1 dB** y deja la clasificación de los cuatro bloques **exactamente
   igual**.

Añadir un parámetro arbitrario sin ganancia alguna en la detección habría empeorado la trazabilidad del
estudio sin mejorar su resultado.

### Orden de las operaciones

```
P0  DESCARTE                3 mediciones
P1  FUGA DE LO             81 celdas espectrales     T1
P2  GEORREFERENCIACIÓN      6 celdas de metadato     T2
P3  CALIBRACIÓN ANTENA  61 440 celdas espectrales    T3
```

El orden no es arbitrario: primero se corrigen los **artefactos instrumentales** (P1) y solo después se
**calibra** (P3), porque no tiene sentido aplicar un desplazamiento de nivel sobre un espurio.

---

## 8. Resultados: calidad de los datos

### Índices globales

| Dimensión | Cumplimiento | Definición aplicada |
|---|---:|---|
| Completitud | **100.00 %** | Celdas presentes y finitas sobre el total |
| Validez | **99.97 %** | Muestras dentro del rango físico del receptor |
| Unicidad | **100.00 %** | Mediciones no duplicadas |
| Consistencia | **95.24 %** | Mediciones sin defecto de severidad alta |
| Exactitud | **95.24 %** | Mediciones con georreferenciación confiable |
| **ÍNDICE GLOBAL** | **98.09 %** | Promedio de las cinco dimensiones |

### Reglas activadas

| Regla | Severidad | Mediciones | Archivos |
|---|---|---:|---|
| R9 FUGA_LO_DC | imputable | **28** | 003, 004, 005, 007, 008, 009, 010, 011… |
| R3 GPS_SIN_FIX | imputable | 2 | `008.txt`, `medidaprueba.txt` |
| R5 GPS_IMPRECISO | aviso | 2 | `008.txt`, `017.txt` |
| R10 TEMP_OPERACION | aviso | 2 | `medidaprueba.txt`, `medidapureba2.txt` |
| R11 NO_CAMPANA | descarte | 2 | `medidaprueba.txt`, `medidapureba2.txt` |
| R6 RANGO_FISICO | descarte | 1 | `016.txt` |
| R7 NIVEL_ANOMALO | descarte | 1 | `016.txt` |

### Mediciones descartadas

| Archivo | Reglas | Evidencia |
|---|---|---|
| `016.txt` | R6 + R7 | pico −3.6 dBm · mediana −27.7 dBm (z = 2.7) |
| `medidaprueba.txt` | R3, R9, R10, R11 | DC +26.3 dB · T = 35.2 °C |
| `medidapureba2.txt` | R10, R11 | T = 38.1 °C |

**`016.txt`** tiene la traza completa desplazada **+55 dB** respecto de `015.txt` y **+35 dB** respecto de
`017.txt`, conservando la misma forma espectral (correlación de 0.70 con sus vecinas). Un salto de nivel
de ese tamaño entre dos posiciones GPS separadas por menos de 400 m es físicamente imposible:
corresponde a un error de ganancia del *front-end* o a compresión del receptor. No es recuperable
porque se desconoce el factor de ganancia exacto aplicado.

**Los dos archivos de prueba** se identifican con **tres evidencias independientes**: el nombre del
archivo, la temperatura del sensor (35.2 y 38.1 °C, muy por debajo de los 42.8–50.4 °C de toda la
campaña, es decir el equipo aún no había estabilizado) y, en el primero, la ausencia total de fix GPS.

**Balance final: 60 de 63 mediciones conservadas (95.2 %).**

---

## 9. Resultados: la ruta

La secuencia numérica de los archivos (001 a 061) es la **única marca temporal disponible**: el sensor no
registra estampa de tiempo.

| Parámetro | Valor |
|---|---|
| Puntos válidos georreferenciados | 60 |
| Longitud total recorrida | **26.02 km** |
| Separación media entre muestras | 441 m |
| Extensión en latitud | 6.158005 a 6.243257 °N |
| Extensión en longitud | −75.609505 a −75.569140 °O |
| Cobertura | 9.42 km (N–S) × 4.47 km (E–O) |
| Rango de altura | 1499.0 a 1589.6 m s. n. m. |
| HDOP | mediana 0.90 · máximo 17.30 |
| Posiciones imputadas | 2 |

El recorrido describe un **circuito cerrado**: arranca en el extremo norte, desciende por el costado
occidental ganando altura hasta los 1589.6 m, gira hacia el oriente en el extremo sur y regresa por el
costado oriental hasta un punto próximo al de partida.

Esta geometría en lazo es **favorable para el estudio** porque rodea el área en lugar de atravesarla, lo
que mejora la diversidad angular de las observaciones y con ello la capacidad de discriminar la
dirección de las fuentes.

---

## 10. Resultados: incidencia de la temperatura

> ### No existe evidencia de que la temperatura del sensor degrade la calidad de los datos.

### El problema metodológico

La temperatura crece de forma casi monótona durante la campaña (de 42.8 a 50.4 °C) simplemente porque el
equipo se calienta mientras opera. La correlación entre temperatura y orden de medición es
**r = +0.869 (p ≈ 2 × 10⁻¹⁹)**, prácticamente determinista. Como la estación se desplaza en el tiempo, la
temperatura queda además correlacionada con la **posición** y, por tanto, con el entorno radioeléctrico.

Una correlación simple entre temperatura y cualquier métrica de calidad sería **espuria**: estaría
midiendo el efecto del recorrido, no el del calentamiento.

### Correlaciones simples frente a parciales

| Métrica de calidad | r simple | r parcial (control: orden) | p parcial | ¿Significativa? |
|---|---:|---:|---:|:---:|
| Piso de ruido (p5) | +0.216 | **−0.019** | 0.886 | NO |
| Fuga de oscilador local | −0.261 | **+0.118** | 0.372 | NO |
| Error de distancia GPS | −0.102 | **+0.065** | 0.625 | NO |
| Número de banderas | −0.274 | **+0.031** | 0.818 | NO |
| Rango dinámico | −0.068 | **+0.241** | 0.066 | NO |

Las correlaciones simples ya son débiles y, al controlar por el orden, **se desvanecen**. Ninguna
mantiene asociación significativa al 5 %. Además **el signo de varias se invierte** al aplicar el
control, que es la firma clásica de una relación espuria inducida por una variable de confusión.

### Regresión multivariada

`piso_ruido ~ temperatura + orden + altura` sobre las 60 mediciones válidas:

| Variable | Coeficiente | Error estándar | t | p | ¿Significativa? |
|---|---:|---:|---:|---:|:---:|
| intercepto | −57.4989 | 87.2418 | −0.66 | 0.513 | NO |
| temperatura (°C) | −0.7827 | 1.9472 | −0.40 | **0.689** | NO |
| orden de medición | +0.2095 | 0.1659 | +1.26 | 0.212 | NO |
| altura (m) | +0.0082 | 0.0075 | +1.09 | 0.279 | NO |

**R² ajustado = 0.038.** El modelo completo no explica prácticamente nada y ninguna variable es
significativa.

### El argumento definitivo: la cota física

La potencia de ruido a la entrada de un receptor es `N = k·T·B·F`. Si la temperatura física pasa de
42.8 °C a 50.4 °C, es decir de 315.96 K a 323.56 K, el incremento **máximo** del piso de ruido
atribuible al término kT es:

```
10 · log10(323.56 / 315.96) = 0.103 dB
```

El coeficiente ajustado implicaría un efecto de **5.95 dB** sobre el rango de la campaña, **58 veces la
cota física**. Un resultado imposible, que confirma que ese coeficiente es ruido de estimación y no un
efecto real.

El contraste entre grupos apunta igual: piso frío −77.48 dBm vs. caliente −74.91 dBm, diferencia
**+2.57 dB con p = 0.384**, no significativa.

### Lo que sí depende de la temperatura

El único efecto real es el **criterio de validez de campaña**. Las dos capturas de prueba se realizaron a
35.2 y 38.1 °C, muy por debajo de la ventana de operación estabilizada (40–55 °C), lo que permitió
identificarlas como ajenas a la campaña con una evidencia independiente del nombre del archivo.

Es decir: **la temperatura no sirve para predecir la calidad de un dato, pero sí para verificar que el
instrumento estaba en régimen cuando lo tomó.**

---

## 11. Resultados: ocupación por canal

### La sumatoria de Parseval

El teorema de Parseval establece que la energía de una señal es la misma en el dominio del tiempo o en
el de la frecuencia. En su forma discreta:

```
Σ |x[n]|²  =  (1/N) · Σ |X[k]|²
```

El sensor entrega el espectro ya normalizado como `S[k] = 20·log10(|X[k]|/N)` en dBm, de modo que
`10^(S[k]/10)` es directamente la potencia del bin *k*. Restringiendo la suma a los 256 bins de cada
canal de 5 MHz:

```
Potencia TOTAL  :  P_total = Σ 10^(S[k]/10)          [mW]
Potencia MEDIA  :  P_media = P_total / 256           [mW]   ← la que exige el enunciado
```

> La suma se realiza **siempre en potencia lineal**. Sumar decibelios sería físicamente incorrecto: el
> dB es logarítmico y la potencia solo es aditiva en su dominio lineal.

### Canalización

| Canal | Banda | Bins de la FFT | Ancho |
|:---:|---|---|---|
| A | 840 – 845 MHz | 0 – 255 | 256 × 19.53 kHz = 5 MHz |
| B | 845 – 850 MHz | 256 – 511 | 256 × 19.53 kHz = 5 MHz |
| C | 850 – 855 MHz | 512 – 767 | 256 × 19.53 kHz = 5 MHz |
| D | 855 – 860 MHz | 768 – 1023 | 256 × 19.53 kHz = 5 MHz |

### Resultados

| Canal | Banda | P media | P mediana | P máx | % puntos ocupados | IC 95 % de la ocupación | Domina en |
|:---:|---|---:|---:|---:|---:|:---:|---:|
| **C** | 850 – 855 | **−33.90** | **−45.07** | −19.30 | **86.7 %** | **75.8 – 93.1 %** | **51 / 60** |
| B | 845 – 850 | −36.49 | −62.89 | −24.97 | 33.3 % | 22.7 – 45.9 % | 8 |
| D | 855 – 860 | −48.20 | −65.76 | −37.76 | 31.7 % | 21.3 – 44.2 % | 0 |
| **A** | 840 – 845 | **−56.72** | **−66.88** | −43.71 | **28.3 %** | 18.5 – 40.8 % | 1 |

*(potencias en dBm)*

**Por qué tres estadísticos de agregación espacial**, cada uno responde a una pregunta distinta:

- La **media** se calcula en el dominio lineal y representa la potencia total que el área recibe, pero la
  dominan unos pocos puntos muy calientes.
- La **mediana** describe el nivel que encuentra un usuario típico y es robusta frente a esos extremos.
- El **porcentaje de puntos ocupados** mide la extensión territorial del problema.

**La brecha entre media y mediana es en sí misma un diagnóstico:** en el canal B supera los **26 dB**,
señal inequívoca de contaminación muy localizada; en el canal C es de apenas **11 dB**, lo que indica una
ocupación generalizada en toda el área.

### Qué diferencias entre canales son reales

La ocupación es una proporción estimada sobre **60 mediciones**, así que tiene incertidumbre. El
intervalo de confianza del 95 % se calcula por el **método de Wilson**, preferible a la aproximación
normal porque esta última se comporta mal con proporciones cercanas a 0 o a 1 — justamente el caso del
canal más contaminado.

El resultado obliga a matizar el orden de preferencia:

```
C   ████████████████████████░░░░░░  75.8 ── 86.7 ── 93.1 %
B      ██████████████░░░░░░░░░░░░░  22.7 ── 33.3 ── 45.9 %   ┐
D     █████████████░░░░░░░░░░░░░░░  21.3 ── 31.7 ── 44.2 %   ├ se solapan
A    ████████████░░░░░░░░░░░░░░░░░  18.5 ── 28.3 ── 40.8 %   ┘
```

**Los canales A, B y D son estadísticamente indistinguibles al 95 %.** El orden entre ellos es una
estimación puntual, no un resultado que la campaña sostenga. Lo único firmemente establecido es la
separación del canal C, cuyo intervalo no se solapa con ningún otro.

La consecuencia práctica es doble: la decisión de **excluir el canal C está sólidamente respaldada**, y
la elección entre A, B y D puede apoyarse en otros criterios (nivel de pico, proximidad a los focos,
planificación) sin contradecir los datos, pero debería confirmarse con una campaña de mayor tamaño
muestral.

### Frecuencias extremas

| Criterio | Frecuencia | Canal | Bin | P media | % de la ruta ocupada |
|---|---|:---:|---:|---:|---:|
| **Más contaminada** | **853.1445 MHz** | C | 673 | −27.07 dBm | **93.3 %** |
| **Menos contaminada** | **840.4688 MHz** | A | 24 | −58.98 dBm | **15.0 %** |

El criterio de selección pesa **70 % la potencia media espacial y 30 % la persistencia**. El desempate
por persistencia es necesario porque una portadora presente en todo el recorrido contamina el plan de
frecuencias mucho más que un pico intenso pero puntual.

---

## 12. Resultados: modelo de decisión

### El Índice de Saturación Espectral (ISE)

Construido con la misma lógica del AQI trabajado en clase: se mapea una magnitud física continua a una
escala normalizada de 0 a 100 por tramos lineales, y cada tramo lleva asociada una categoría y una
acción.

```
ISE = 0.6 · I(P_mediana) + 0.4 · (% del área ocupada)
      └── INTENSIDAD ──┘   └──── EXTENSIÓN ────┘
```

Combina dos componentes, igual que cualquier índice de contaminación ambiental. **Se usa la mediana
espacial y no la media lineal** en la componente de intensidad porque la media en mW la domina un puñado
de puntos muy calientes y reportaría como saturado un canal que en realidad está limpio en casi toda la
ciudad.

| ISE | Categoría | Lectura para la Agencia |
|---|---|---|
| 0 – 25 | Libre | Bloque disponible sin restricciones |
| 25 – 50 | Moderado | Emisiones presentes pero compatibles con nuevas asignaciones |
| 50 – 75 | Contaminado | Requiere coordinación geográfica y control de potencia |
| 75 – 100 | Saturado | No asignable sin una acción de control previa |

### Las hipótesis de decisión

Se evalúan en cascada, de la condición más restrictiva a la menos. Los puntos de corte del porcentaje de
área ocupada siguen la **Recomendación UIT-R SM.1880**: por encima del 50 % el canal se considera
congestionado, entre 30 y 50 % de uso intensivo, entre 15 y 30 % de uso ligero, y por debajo del 15 %
prácticamente libre.

| # | Hipótesis | Condición | Decisión |
|---|---|---|---|
| H1 | Canal congestionado | % área ≥ 50 % | NO ASIGNAR |
| H2 | Fondo por encima del umbral | P mediana > −60 dBm | NO ASIGNAR |
| H3 | Contaminación localizada intensiva | % área ≥ 30 % | ASIGNAR CON RESTRICCIÓN |
| H4 | Uso ligero | % área ≥ 15 % | ASIGNAR |
| H5 | Canal libre | resto | ASIGNAR PRIORITARIO |

### Resultado

| Canal | Banda | P mediana | % área | ISE | (nivel / extensión) | Categoría | Hipótesis | **Decisión** | Prioridad |
|:---:|---|---:|---:|---:|---|---|:---:|---|---|
| **C** | 850 – 855 | −45.07 | 86.7 % | **79.6** | 74.9 / 86.7 | Saturado | H1 | **NO ASIGNAR** | ALTA |
| B | 845 – 850 | −62.89 | 33.3 % | 40.4 | 45.2 / 33.3 | Moderado | H3 | Asignar con restricción | MEDIA |
| D | 855 – 860 | −65.76 | 31.7 % | 36.9 | 40.4 / 31.7 | Moderado | H3 | Asignar con restricción | MEDIA |
| **A** | 840 – 845 | −66.88 | 28.3 % | **34.5** | 38.5 / 28.3 | Moderado | H4 | **ASIGNAR** | BAJA |

### Recomendación a la Agencia

| Concepto | Resultado |
|---|---|
| Orden de preferencia | **A > D > B > C** |
| Canales recomendados | A, D, B |
| Canal NO recomendado | **C** |
| Espectro utilizable | **15 MHz** |
| Espectro comprometido | **5 MHz (25 % de la banda)** |

**Acciones concretas:**

1. **Asignar en orden A > D > B.** Es el orden inverso al índice de saturación y maximiza la
   probabilidad de operación sin interferencia.
2. **No asignar el canal C** hasta ejecutar una acción de control. Es el único bloque que supera el
   umbral de congestión de la UIT y su contaminación **no es localizada sino generalizada**, de modo que
   no puede resolverse con zonas de exclusión. Un concesionario operaría con relación señal-interferencia
   degradada en toda la zona.
3. **Verificación en sitio de 853.1445 MHz**, la portadora individual más contaminante, activa en el
   93 % del área. Contrastar contra el registro de licencias vigentes.
4. **Ampliar la campaña** hacia el occidente y suroccidente: el modelo de extrapolación sitúa los focos
   principales fuera del perímetro recorrido.
5. **Monitoreo semestral** de los bloques que se asignen, con el mismo ETL e indicadores.

---

## 13. Resultados: fuentes extrapoladas (bonificación)

### Primer resultado: no existe una única fuente por banda

El enunciado pide «la fuente» de cada banda, en singular. **El dato dice otra cosa**, y conviene
demostrarlo antes de localizar nada. Se ajustó un modelo de fuente única sobre los 60 puntos de la ruta:

| Canal | R² de fuente única | Residuo | Puesto del punto más potente por cercanía |
|:---:|---:|---:|---|
| A | +0.070 | 7.9 dB | 6 de 60 |
| B | +0.122 | 18.3 dB | 15 de 60 |
| C | +0.093 | 9.2 dB | 6 de 60 |
| D | +0.114 | 13.8 dB | 31 de 60 |

Explica entre el 7 y el 12 % de la varianza. **El diagnóstico decisivo es la última columna**: si
existiera un emisor dominante, el punto donde se midió más potencia tendría que ser también el *más
cercano* a la fuente estimada. En el canal D queda en el puesto 31 de 60, y en algunos ajustes la
correlación entre potencia y logaritmo de la distancia llega a ser **negativa** — el modelo predice lo
contrario de lo medido.

**La razón es física.** Una banda celular no la emite un transmisor sino una **red** de estaciones base.
En una malla urbana densa cada punto de la ruta está próximo a alguna estación, de modo que el campo no
decae desde un centro único sino que presenta múltiples máximos locales. El detector de máximos encuentra
**entre 9 y 12 focos por canal**, exactamente lo que cabe esperar de una red celular real.

### Enfoque correcto: localización por gradiente local

Si el campo global no responde a una fuente única pero el **entorno de cada máximo sí**, la localización
debe hacerse foco por foco. Alrededor del punto más potente de cada canal, la correlación entre potencia
y logaritmo de la distancia sube a **+0.53 … +0.77** en un radio de 1500 m: ahí el modelo sí aplica.

```
P(d) = 10·log10( 10^((P₀ − 10·n·log10(d/d₀))/10) + 10^(ruido/10) )
```

El término de ruido **no es opcional**: un receptor real nunca mide menos que su propio ruido, así que
lejos del emisor la potencia se aplana en el piso en lugar de seguir cayendo. Sin él, los puntos lejanos
—que están todos en el piso y no aportan información de distancia— tiran del ajuste como si aún
siguieran la ley de propagación y sesgan la posición. La suma se hace en potencia **lineal**, que es
donde señal y ruido son aditivos. El piso se estima como el percentil 5 del canal sobre toda la ruta.

Incluirlo reduce la incertidumbre sin mover las posiciones: el radio del 95 % del canal C baja de 490 a
**462 m**, el del D de 792 a **724 m** y el del A de 3176 a **2888 m**.

1. **Detectar los máximos locales** del campo medido. Cada uno corresponde al entorno de una estación base.
2. **Tomar el foco dominante** del canal y los puntos de la ruta dentro de su radio de influencia.
3. **Ajustar** por mínimos cuadrados no lineales, resolviendo para la posición del emisor. Se minimiza el
   residuo **en decibelios** porque el desvanecimiento por sombra urbana es log-normal, es decir gaussiano
   en el dominio logarítmico.
4. **Validar.** La confianza se deriva primero de la calidad del gradiente y después del ajuste: si la
   potencia no decae con la distancia alrededor del foco, el ajuste no significa nada por bueno que sea
   su residuo.

**Sigue siendo extrapolación y no interpolación:** `griddata` solo estima valores *dentro* de la
envolvente convexa de los puntos medidos y por construcción nunca situaría un emisor fuera de la ruta.
Aquí se resuelve para el parámetro *posición*, que cae fuera del recorrido en los cinco casos.

El exponente se fija en **n = 3.2** (urbano típico). Dejándolo libre, `n` y la distancia son casi
intercambiables —un transmisor lejano y potente con n bajo produce casi el mismo perfil que uno cercano y
débil con n alto— y el optimizador empuja la solución contra el borde de la región de búsqueda.

### Emisores localizados

| Objetivo | Focos | Foco dominante | Emisor estimado | Respecto al foco | Gradiente | R² | Incert. 95 % | Confianza |
|---|---:|---|---|---|---:|---:|---:|---|
| **Frec. 853.145 MHz** | 10 | `024.txt` | 6.168465, −75.604607 | E a 132 m | **+0.77** | **0.737** | ±417 m | **ALTA** |
| **Canal C** | 10 | `024.txt` | 6.167097, −75.604988 | SSE a 189 m | **+0.71** | **0.726** | ±462 m | **ALTA** |
| Canal D | 9 | `045.txt` | 6.205394, −75.571548 | SSO a 40 m | +0.75 | 0.566 | ±724 m | MEDIA |
| Canal A | 12 | `024.txt` | 6.170225, −75.609252 | ONO a 423 m | +0.75 | 0.426 | ±2888 m | **BAJA** |
| Canal B | 9 | `034.txt` | 6.186114, −75.586873 | NNE a 785 m | +0.53 | 0.307 | ±1406 m | BAJA |

### Validación cruzada

El resultado más sólido no es una coordenada aislada sino **una coincidencia**. El foco `024.txt` aparece
como máximo dominante en **tres de los cinco objetivos** — canal A, canal C y la frecuencia crítica — y
los emisores estimados a partir de cada uno caen todos a pocos centenares de metros del mismo punto,
alrededor de **6.168, −75.605**.

Son ajustes **independientes**, sobre bandas de frecuencia distintas, que convergen en el mismo
emplazamiento. La interpretación natural es que se trata de una **estación base multiportadora** emitiendo
simultáneamente en varios canales de la banda, que es exactamente como opera una red celular. Ese
emplazamiento es el primer objetivo a verificar en sitio.

Los canales **A y B se reportan como zona de interés, no como posición de transmisor**.

En el canal B el gradiente es débil (+0.53) y el residuo alto (18.3 dB). En el canal A el problema es
distinto y más revelador: `023.txt` está a 310 m del foco y mide −53.8 dBm, mientras `022.txt` está a
1058 m —3.4 veces más lejos— y mide **6 dB más fuerte**. Con un solo emisor eso es imposible. El ajuste
no puede conciliarlo y empuja la posición hacia afuera; la incertidumbre resultante de ±2888 m cubre
toda el área de estudio.

Por eso la clasificación de confianza incluye un **veto por incertidumbre**: si el radio del 95 % supera
el propio radio de ajuste (1500 m), la estimación no está localizando nada y se degrada a BAJA, por
bueno que parezca el ajuste. Dar una coordenada precisa en esos casos sería deshonesto.

---

## 14. El dashboard

Servidor web construido con **Dash sobre Flask**. Seis pestañas:

| Pestaña | Contenido |
|---|---|
| **Mediciones y ruta** | Mapa con los 60 puntos georreferenciados y la trayectoria. Selector para colorear por secuencia, temperatura, altura o error GPS. *Hover* con el detalle completo de cada punto. |
| **Mapas de calor** | Superficie interpolada por canal A/B/C/D, temperatura del sensor y frecuencia más contaminada, sobre cartografía de Medellín. Incluye la fuente extrapolada y una vista de curvas de nivel. |
| **Espectro** | Perfil de ocupación de la banda completa con los cuatro bloques sombreados, marcadores de las frecuencias extremas y gráfica de persistencia. |
| **Modelo de decisión** | ISE, potencias y extensión territorial por canal; tabla de decisiones y panel de acciones recomendadas. |
| **Fuentes** | Tabla de emisores extrapolados con su lectura técnica individual. |
| **Calidad del dato** | Dimensiones de calidad, reglas activadas y bitácora de imputación. |

### Legibilidad de los mapas

La potencia **no se pinta con una rampa continua** sino con **bandas discretas de límites fijos y
absolutos**, con un corte perceptual duro (azul claro → amarillo) justo en el umbral de −60 dBm:

```
 ≤−85   −85   −75   −65  │  −60   −50   −40   −30≥
 ████   ████  ████  ████ │ ████  ████  ████  ████
    azul oscuro → claro  │   amarillo → rojo
          LIBRE          │      OCUPADO
```

Tres consecuencias:

1. El lector distingue **de un vistazo** la zona libre de la contaminada, sin consultar la leyenda.
2. Como los límites son **los mismos para los cuatro canales**, los mapas son directamente comparables
   entre sí. Con una escala autonormalizada por canal, esa comparación sería engañosa.
3. Los **puntos medidos usan la misma escala que la superficie**, de modo que la interpolación no puede
   sugerir algo distinto de lo que realmente se midió.

La superficie se construye con `scipy.interpolate.griddata` en modo **lineal exclusivamente**: fuera de
la envolvente convexa de los puntos medidos el resultado es NaN y **la zona queda en blanco**. Rellenarla
con `nearest` generaría sectores radiales artificiales que se leerían como cobertura real donde no se
midió nada.

### Diseño

Sistema de diseño en `dashboard/estilo.py`, inspirado en el lenguaje visual de Apple: fondo neutro
`#F5F5F7`, tarjetas blancas con esquinas de 18 px y sombra difusa sin bordes marcados, tipografía
`-apple-system` / SF Pro con *letter-spacing* negativo en los títulos, un único acento azul `#0071E3`,
controles segmentados tipo iOS y jerarquía construida con peso y tamaño tipográfico.

---

## 15. Artefactos generados

### Capa bronce — crudo, auditable

| Archivo | Contenido |
|---|---|
| `medidas_crudas.parquet` | 63 × 1029 valores tal como los entregó el sensor |
| `antena_s11.parquet` | 801 puntos de S11 + pérdida por desacople calculada |
| `eje_frecuencias.parquet` | Mapeo bin → frecuencia |

### Capa plata — limpio y trazable

| Archivo | Contenido |
|---|---|
| `medidas_limpias.parquet` | 60 mediciones procesadas |
| `banderas_calidad.parquet` | Dictamen y reglas activas por medición |
| `reporte_reglas.csv` | Resumen agregado de las 11 reglas |
| `indices_calidad.csv` | Las 5 dimensiones + índice global |
| `bitacora_imputacion.csv` | Cada celda modificada, con técnica y motivo |
| `detalle_gps_imputado.csv` | Valor original → valor imputado |
| `mediciones_descartadas.csv` | Qué se descartó y por qué |
| `meta_transformacion.csv` | Métricas sueltas que cita el informe |
| `exceso_dc.parquet` | Magnitud de la fuga de LO por medición |

### Capa oro — indicadores de negocio

| Archivo | Contenido |
|---|---|
| `indicadores_por_punto.parquet` | Parseval, ocupación y canal dominante por punto |
| `perfil_espectral.parquet` | Perfil de los 1024 bins |
| `resumen_canales.csv` | Agregados por canal A/B/C/D |
| `decisiones_canales.csv` | ISE, hipótesis y acción por canal |
| `recomendacion_global.csv` | Síntesis para el plan de frecuencias |
| `frecuencias_extremas.csv` | Frecuencia más y menos contaminada |
| `fuentes_estimadas.csv` | Emisores extrapolados |
| `metricas_temperatura.csv` · `correlaciones_temperatura.csv` · `regresion_temperatura.csv` | Análisis térmico |

### Informe

`informe/Informe_ANE_Ocupacion_840_860MHz.docx` — **11 secciones, 18 tablas, 10 figuras**.

Todas las cifras del texto se leen de los artefactos del datalake: **el informe no tiene ningún número
escrito a mano**, de modo que si el ETL cambia, el informe se regenera coherente.

| Figura | Contenido |
|---|---|
| `01_ruta.png` | Trayectoria de la estación móvil |
| `02_calidad.png` | Reglas activadas y dimensiones de calidad |
| `03_etl.png` | Corrección de la fuga de LO y descarte de `016.txt` |
| `04_perfil_espectral.png` | Perfil de la banda y ocupación por frecuencia |
| `05_frecuencias_extremas.png` | Frecuencia más y menos contaminada |
| `06_canales.png` | Comparativa de los cuatro canales |
| `07_temperatura.png` | Análisis de incidencia térmica |
| `08_mapas_canales.png` | Mapas de calor A/B/C/D |
| `09_mapas_temperatura_fmax.png` | Temperatura y frecuencia crítica |
| `10_antena.png` | Adaptación de antena y corrección aplicada |

---

## 16. Decisiones de diseño y limitaciones

### Decisiones tomadas y su justificación

| Decisión | Por qué |
|---|---|
| Umbral de rango físico en **−5 dBm** y no −10 | El espectro es `20·log10(\|FFT\|/N)` sobre muestras del ADC, así que 0 dB es fondo de escala y el punto de compresión de 1 dB está unos 5 dB por debajo. Con −10 se descartaban `024.txt` y `034.txt`, que son **señales reales fuertes**, no fallos. |
| ISE de **dos componentes** | La media lineal la dominan unos pocos puntos calientes y clasificaba el canal B como saturado cuando está limpio en el 68 % del área. |
| Umbrales de extensión **UIT-R SM.1880** | Para que los puntos de corte no sean arbitrarios sino un estándar internacional defendible. |
| `griddata` solo **lineal**, sin `nearest` | Rellenar fuera del casco convexo inventa cobertura donde no se midió. |
| Exponente de propagación **fijo** | Resuelve la degeneración n ↔ distancia que hacía el problema no identificable. |
| Interpolar la fuga de LO en **potencia lineal** | Promediar dB es una media geométrica de potencias y subestima la envolvente. |
| Detección de nivel anómalo con **mediana y MAD** | Con media y desviación estándar, el propio outlier contamina el estadístico de referencia. |
| **No censurar** el piso de ruido | No hay punto de corte natural en el histograma, y se verificó que censurar mueve la potencia de cada canal menos de 0.1 dB sin alterar la clasificación. Habría sido un parámetro arbitrario sin ganancia. |

### Limitaciones declaradas

- **Una sola sesión de medición.** La ocupación celular varía con la hora y el día, así que los
  resultados describen un instante, no un promedio estadístico del uso del espectro.
- **Potencias no calibradas en unidades absolutas.** Se corrigió el desacople de la antena, pero no se
  dispone de su patrón de radiación ni de la ganancia absoluta de la cadena de recepción. Los valores en
  dBm son comparables entre sí pero no trasladables a un límite de exposición.
- **Retención de máximos, no promedio.** Cada traza es el máximo sobre 100 barridos, lo que sobreestima
  la ocupación media real. Hace la evaluación conservadora, apropiado para una decisión regulatoria,
  pero debe tenerse presente.
- **Cobertura limitada al circuito recorrido.** Fuera de la envolvente convexa no se reporta ningún
  valor interpolado: los mapas no deben leerse como cobertura de toda la ciudad.

---

## 17. Solución de problemas

**`GPUInitializationError: WebGL2 is required to display this map`**

Los mapas de Plotly usan MapLibre, que **exige WebGL2**. No es un problema del código: el navegador no lo
soporta o lo tiene deshabilitado. Prueba con otro navegador; en Chrome el estado se revisa en
`chrome://gpu`. Mientras tanto, **cada mapa tiene debajo una vista de curvas de nivel en SVG puro** que
no necesita WebGL, así que la información geográfica nunca queda inaccesible.

**`FileNotFoundError` al arrancar el dashboard**

El dashboard lee el datalake al iniciar. Ejecuta primero `python run_pipeline.py`.

**`Address already in use` en el puerto 8050**

Hay otra instancia corriendo. En Windows:

```bash
netstat -ano | findstr :8050
```

y termina el PID, o cambia la constante `PUERTO` en `dashboard/app.py`.

**Los mapas tardan en aparecer**

La primera carga descarga los *tiles* de OpenStreetMap. Requiere conexión a internet, pero ningún token.

**`ModuleNotFoundError: No module named 'config'`**

Estás lanzando un módulo desde la raíz (`python etl/quality.py`). Los módulos de `etl/` se importan
entre sí por nombre, así que hay que ejecutarlos desde su propia carpeta:

```bash
cd etl && python quality.py
```

O usa `run_pipeline.py`, que ya resuelve las rutas por ti.

---

<div align="center">

**Estudio técnico de ocupación espectral** · Internet de las Cosas · Examen 3
Universidad Pontificia Bolivariana

</div>

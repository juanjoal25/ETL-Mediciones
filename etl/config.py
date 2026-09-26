# -*- coding: utf-8 -*-
"""
config.py - Parametros globales del proceso ETL de ocupacion espectral.

Proyecto : Examen 3 - Internet de las Cosas (UPB)
Cliente  : Agencia Nacional del Espectro (ANE)
Banda    : 840 MHz - 860 MHz, sector occidental de Medellin

Todos los modulos del pipeline importan de aqui para que no existan
"numeros magicos" repartidos por el codigo.
"""

import os

# ---------------------------------------------------------------------------
# RUTAS DEL PROYECTO
# ---------------------------------------------------------------------------
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DIR_DATOS = os.path.join(RAIZ, "datos", "medidas_2026_20")
DIR_LAKE = os.path.join(RAIZ, "datalake")
DIR_INFORME = os.path.join(RAIZ, "informe")
DIR_FIGURAS = os.path.join(DIR_INFORME, "figuras")

# Capas del datalake (arquitectura medallion: bronze -> silver -> gold)
LAKE_BRONCE = os.path.join(DIR_LAKE, "bronce")   # crudo tal cual se extrajo
LAKE_PLATA = os.path.join(DIR_LAKE, "plata")     # limpio, validado e imputado
LAKE_ORO = os.path.join(DIR_LAKE, "oro")         # indicadores para el modelo

ARCHIVO_ANTENA = os.path.join(DIR_DATOS, "ANTENNA1.csv")

# ---------------------------------------------------------------------------
# GEOMETRIA DE LA MEDIDA (definida por el flowgraph GNU Radio medir_celular.py)
# ---------------------------------------------------------------------------
N_BINS = 1024                   # tamano de la FFT del sensor
N_COLUMNAS = 1029               # 1024 espectro + 5 metadatos
F_INICIO_HZ = 840e6             # primer bin tras el fftshift (fc - fs/2)
F_FIN_HZ = 860e6                # limite superior de la banda medida
ANCHO_BANDA_HZ = F_FIN_HZ - F_INICIO_HZ          # 20 MHz = samp_rate del USRP
RBW_HZ = ANCHO_BANDA_HZ / N_BINS                 # 19.53125 kHz por bin
F_CENTRAL_HZ = 850e6            # fc del USRP -> cae exactamente en el bin 512

# Nombres de las columnas de metadatos, en el orden en que los escribe el sensor
COLS_META = ["temperatura", "longitud", "latitud", "altura", "error_distancia"]

# ---------------------------------------------------------------------------
# CANALIZACION SOLICITADA POR LA ANE: 4 bloques consecutivos de 5 MHz
# ---------------------------------------------------------------------------
ANCHO_CANAL_HZ = 5e6
BINS_POR_CANAL = int(ANCHO_CANAL_HZ / RBW_HZ)    # 256 bins por canal

CANALES = {
    "A": (840e6, 845e6),
    "B": (845e6, 850e6),
    "C": (850e6, 855e6),
    "D": (855e6, 860e6),
}

# ---------------------------------------------------------------------------
# REGLA DE NEGOCIO DEL ESTUDIO
# ---------------------------------------------------------------------------
UMBRAL_OCUPACION_DBM = -60.0    # canal ocupado/contaminado si supera -60 dBm

# ---------------------------------------------------------------------------
# UMBRALES DE VALIDACION DE CALIDAD
# ---------------------------------------------------------------------------
# Ventana geografica valida para el occidente de Medellin (bounding box amplio)
LAT_MIN, LAT_MAX = 6.10, 6.40
LON_MIN, LON_MAX = -75.70, -75.45
ALT_MIN, ALT_MAX = 1400.0, 1900.0   # el valle de Aburra esta entre ~1450-1800 m

HDOP_MAX = 2.0                  # error de distancia aceptable para georreferenciar
HDOP_SOSPECHOSO = 1.5           # umbral de advertencia

# Rango dinamico fisico del receptor USRP (ganancia 40 dB, antena de monitoreo).
# El espectro se calcula como 20*log10(|FFT|/N) sobre las muestras del ADC, de
# modo que 0 dB equivale al fondo de escala del conversor. El punto de
# compresion de 1 dB de la cadena de recepcion se situa unos 5 dB por debajo:
# por encima de -5 dB la medida ya no es lineal y deja de ser confiable.
DBM_MAX_FISICO = -5.0
DBM_MIN_FISICO = -120.0

# Deteccion de traza desplazada en nivel (error de ganancia / AGC)
Z_MEDIANA_MAX = 2.5             # z-score de la mediana de la traza

# Fuga de oscilador local (DC leakage) del receptor de conversion directa.
# En un zero-IF el offset DC aparece en el bin central tras el fftshift.
BIN_DC = N_BINS // 2            # bin 512 == 850.000 MHz
ANCHO_DC = 1                    # se corrigen los bins BIN_DC +/- ANCHO_DC
DELTA_DC_DB = 6.0               # se declara fuga si supera a sus vecinos en 6 dB

# Temperatura de operacion del sensor (USRP + GPSDO)
TEMP_MIN_OPERACION = 40.0       # por debajo el equipo no ha estabilizado
TEMP_MAX_OPERACION = 55.0

# Archivos que no pertenecen a la campana de medicion
PATRONES_DESCARTE = ["prueba", "pureba"]

# ---------------------------------------------------------------------------
# MODELO DE DECISION: Indice de Saturacion Espectral (ISE)
# ---------------------------------------------------------------------------
# Analogo al AQI visto en la sesion 9: se mapea una magnitud fisica continua
# (potencia Parseval en dBm) a un indice 0-100 por tramos lineales, y cada
# tramo lleva asociada una categoria y una accion regulatoria.
#   (dBm_bajo, dBm_alto, ISE_bajo, ISE_alto, categoria, color)
TRAMOS_ISE = [
    (-95.0, -75.0, 0, 25, "Libre", "#2E933C"),
    (-75.0, -60.0, 25, 50, "Moderado", "#F2C14E"),
    (-60.0, -45.0, 50, 75, "Contaminado", "#F26430"),
    (-45.0, -20.0, 75, 100, "Saturado", "#C1292E"),
]

# El ISE combina DOS componentes, igual que cualquier indice de contaminacion
# ambiental: la INTENSIDAD del contaminante y la EXTENSION del territorio
# afectado. Una portadora muy fuerte en un solo punto no degrada el plan de
# frecuencias de la ciudad tanto como una emision moderada presente en toda
# el area, y una media puramente lineal no distingue esos dos casos.
PESO_ISE_NIVEL = 0.6        # intensidad: potencia mediana espacial del canal
PESO_ISE_EXTENSION = 0.4    # extension: % de puntos de la ruta por encima de -60 dBm

# Umbrales de clasificacion de ocupacion segun la Recomendacion UIT-R SM.1880
# (Spectrum Occupancy Measurements and Evaluation): se toma el porcentaje del
# area en que el canal supera el umbral de deteccion.
OCUPACION_CONGESTIONADO = 50.0   # canal congestionado
OCUPACION_ALTA = 30.0            # uso intensivo
OCUPACION_MODERADA = 15.0        # uso ligero; por debajo se considera libre

# ---------------------------------------------------------------------------
# MODELO DE PROPAGACION PARA LA EXTRAPOLACION DE FUENTES (bonificacion)
# ---------------------------------------------------------------------------
EXP_PERDIDA_N = 3.2             # exponente de perdida log-distancia urbano
D0_M = 100.0                    # distancia de referencia del modelo
RADIO_TIERRA_M = 6371000.0


def crear_directorios():
    """Crea la estructura de carpetas del datalake y del informe."""
    for d in (DIR_LAKE, LAKE_BRONCE, LAKE_PLATA, LAKE_ORO,
              DIR_INFORME, DIR_FIGURAS):
        os.makedirs(d, exist_ok=True)

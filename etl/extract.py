# -*- coding: utf-8 -*-
"""
extract.py - FASE 1 DEL ETL: EXTRACCION (capa BRONCE del datalake)

Responsabilidad unica: leer las fuentes de datos crudas SIN modificarlas y
dejarlas en una estructura tabular homogenea. Toda decision de limpieza se
toma mas adelante, para que la capa bronce sea trazable y auditable.

Fuentes:
  1) 63 archivos .txt de la estacion movil (1 fila x 1029 valores CSV)
  2) ANTENNA1.csv - barrido S11 de la antena de monitoreo (Agilent N9914A),
     necesario para des-incrustar la respuesta de la antena de las medidas.
"""

import os
import glob

import numpy as np
import pandas as pd

import config as cfg


def _leer_archivo_medida(ruta):
    """
    Lee un archivo de medida y devuelve (vector_float, incidencias).

    El sensor escribe una sola fila CSV con 1029 campos. Se valida la
    cardinalidad y la convertibilidad numerica de cada campo; cualquier
    desviacion se reporta como incidencia de extraccion en vez de reventar
    el pipeline (robustez: un archivo corrupto no debe tumbar la campana).
    """
    incidencias = []
    with open(ruta, "r", encoding="utf-8", errors="replace") as fo:
        contenido = fo.read().strip()

    campos = [c.strip() for c in contenido.split(",") if c.strip() != ""]

    valores = []
    for pos, campo in enumerate(campos):
        try:
            valores.append(float(campo))
        except ValueError:
            valores.append(np.nan)
            incidencias.append("campo_no_numerico@%d" % pos)

    if len(valores) != cfg.N_COLUMNAS:
        incidencias.append("cardinalidad=%d" % len(valores))
        # Se normaliza a 1029 posiciones: se recorta o se rellena con NaN
        if len(valores) > cfg.N_COLUMNAS:
            valores = valores[:cfg.N_COLUMNAS]
        else:
            valores = valores + [np.nan] * (cfg.N_COLUMNAS - len(valores))

    return np.array(valores, dtype=float), incidencias


def extraer_medidas():
    """
    Recorre la carpeta de datos y construye el DataFrame crudo de la campana.

    Devuelve
    --------
    df : DataFrame indexado por 'archivo' con columnas
         bin_0000..bin_1023 + temperatura, longitud, latitud, altura,
         error_distancia + 'orden' (secuencia temporal) e 'incidencias_extraccion'.
    """
    rutas = sorted(glob.glob(os.path.join(cfg.DIR_DATOS, "*.txt")))
    if not rutas:
        raise FileNotFoundError("No se encontraron medidas en %s" % cfg.DIR_DATOS)

    filas, nombres, incid = [], [], []
    for ruta in rutas:
        vec, inc = _leer_archivo_medida(ruta)
        filas.append(vec)
        nombres.append(os.path.basename(ruta))
        incid.append(";".join(inc) if inc else "")

    matriz = np.vstack(filas)

    cols_espectro = ["bin_%04d" % k for k in range(cfg.N_BINS)]
    df = pd.DataFrame(matriz, columns=cols_espectro + cfg.COLS_META)
    df.insert(0, "archivo", nombres)
    df["incidencias_extraccion"] = incid

    # El nombre numerico del archivo (001..061) es la secuencia temporal de la
    # campana: es la unica marca de tiempo disponible, el sensor no guarda
    # timestamp. Los archivos de prueba quedan al final con orden NaN.
    def _orden(nombre):
        raiz = os.path.splitext(nombre)[0]
        return int(raiz) if raiz.isdigit() else np.nan

    df["orden"] = df["archivo"].map(_orden)
    df = df.sort_values(["orden", "archivo"], na_position="last").reset_index(drop=True)

    return df


def extraer_respuesta_antena():
    """
    Lee el barrido S11 de la antena de monitoreo (formato Agilent/Keysight).

    El archivo trae una cabecera con lineas '!' y el bloque de datos entre
    BEGIN y END con pares 'frecuencia_Hz,S11_dB'.

    Devuelve
    --------
    df : DataFrame con columnas frecuencia_hz, s11_db, gamma2, perdida_desacople_db

    La perdida por desacople se obtiene de |Gamma|^2 = 10^(S11/10):
        L_mismatch [dB] = -10*log10(1 - |Gamma|^2)
    Es la fraccion de potencia que la antena refleja en lugar de entregar al
    receptor; hay que sumarsela a la medida para estimar la potencia incidente.
    """
    if not os.path.exists(cfg.ARCHIVO_ANTENA):
        return None

    frec, s11 = [], []
    with open(cfg.ARCHIVO_ANTENA, "r", encoding="utf-8", errors="replace") as fo:
        for linea in fo:
            linea = linea.strip()
            if not linea or linea.startswith("!") or linea in ("BEGIN", "END"):
                continue
            partes = linea.split(",")
            if len(partes) != 2:
                continue
            try:
                frec.append(float(partes[0]))
                s11.append(float(partes[1]))
            except ValueError:
                continue

    df = pd.DataFrame({"frecuencia_hz": frec, "s11_db": s11})
    df["gamma2"] = 10.0 ** (df["s11_db"] / 10.0)
    df["perdida_desacople_db"] = -10.0 * np.log10(1.0 - df["gamma2"])
    return df


def eje_frecuencias():
    """Vector de las 1024 frecuencias centrales de bin, en Hz."""
    return cfg.F_INICIO_HZ + np.arange(cfg.N_BINS) * cfg.RBW_HZ


def main():
    cfg.crear_directorios()

    print("[EXTRACCION] Leyendo medidas de la estacion movil...")
    df = extraer_medidas()
    print("  - archivos leidos      : %d" % len(df))
    print("  - columnas por archivo : %d" % cfg.N_COLUMNAS)
    print("  - incidencias de lectura: %d" % (df["incidencias_extraccion"] != "").sum())

    salida = os.path.join(cfg.LAKE_BRONCE, "medidas_crudas.parquet")
    df.to_parquet(salida, index=False)
    print("  -> %s" % salida)

    print("[EXTRACCION] Leyendo respuesta S11 de la antena...")
    ant = extraer_respuesta_antena()
    if ant is not None:
        en_banda = ant[(ant.frecuencia_hz >= cfg.F_INICIO_HZ) &
                       (ant.frecuencia_hz <= cfg.F_FIN_HZ)]
        print("  - puntos totales : %d (%.0f - %.0f MHz)"
              % (len(ant), ant.frecuencia_hz.min() / 1e6, ant.frecuencia_hz.max() / 1e6))
        print("  - en banda 840-860 MHz: S11 de %.2f a %.2f dB -> desacople %.2f a %.2f dB"
              % (en_banda.s11_db.max(), en_banda.s11_db.min(),
                 en_banda.perdida_desacople_db.min(), en_banda.perdida_desacople_db.max()))
        ruta_ant = os.path.join(cfg.LAKE_BRONCE, "antena_s11.parquet")
        ant.to_parquet(ruta_ant, index=False)
        print("  -> %s" % ruta_ant)
    else:
        print("  ! No se encontro ANTENNA1.csv, se omite la calibracion de antena")

    # Eje de frecuencias: metadato de la malla espectral
    pd.DataFrame({
        "bin": np.arange(cfg.N_BINS),
        "frecuencia_hz": eje_frecuencias(),
    }).to_parquet(os.path.join(cfg.LAKE_BRONCE, "eje_frecuencias.parquet"), index=False)

    print("[EXTRACCION] Completada.\n")
    return df


if __name__ == "__main__":
    main()

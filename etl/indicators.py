# -*- coding: utf-8 -*-
"""
indicators.py - FASE 4 DEL ETL: CARGA DE INDICADORES (capa ORO)

Transforma el espectro limpio en los indicadores que consume el modelo de
toma de decisiones y el dashboard. Es la frontera entre el mundo fisico
(dBm por bin) y el mundo de negocio de la ANE (canal ocupado / libre).

FUNDAMENTO: TEOREMA DE PARSEVAL EN FORMA DISCRETA
-------------------------------------------------
Para una secuencia x[n] de N muestras y su DFT X[k], Parseval establece

        sum_{n=0}^{N-1} |x[n]|^2  =  (1/N) * sum_{k=0}^{N-1} |X[k]|^2

es decir, la energia calculada en el tiempo es la misma que la calculada en
la frecuencia. Dividiendo entre N se obtiene la POTENCIA MEDIA de la senal:

        P_media = (1/N) * sum_n |x[n]|^2 = (1/N^2) * sum_k |X[k]|^2

El sensor ya entrego el espectro normalizado, S[k] = 20*log10(|X[k]|/N) dBm,
de modo que |X[k]/N|^2 = 10^(S[k]/10) es directamente la potencia del bin k.
Restringiendo la suma a los bins de un canal se obtiene:

    Potencia TOTAL del canal (energia integrada en los 5 MHz):
        P_total = sum_{k in canal} 10^(S[k]/10)                    [mW]

    Potencia MEDIA de ocupacion del canal (la que pide el enunciado):
        P_media = (1/Nc) * sum_{k in canal} 10^(S[k]/10)           [mW]

con Nc = 256 bins por canal. La suma SIEMPRE se hace en potencia lineal:
sumar decibelios seria fisicamente incorrecto, porque el dB es logaritmico y
la potencia es aditiva solo en su dominio lineal.

Un canal se declara OCUPADO / CONTAMINADO cuando P_media supera -60 dBm.
"""

import os

import numpy as np
import pandas as pd

import config as cfg


def dbm_a_mw(x):
    return 10.0 ** (np.asarray(x, dtype=float) / 10.0)


def mw_a_dbm(x):
    return 10.0 * np.log10(np.maximum(np.asarray(x, dtype=float), 1e-30))


def bins_de_canal(canal):
    """Indices de los bins que pertenecen a un canal de 5 MHz."""
    f_ini, f_fin = cfg.CANALES[canal]
    k_ini = int(round((f_ini - cfg.F_INICIO_HZ) / cfg.RBW_HZ))
    k_fin = int(round((f_fin - cfg.F_INICIO_HZ) / cfg.RBW_HZ))
    return np.arange(k_ini, min(k_fin, cfg.N_BINS))


def parseval_canal(S, indices):
    """
    Aplica la sumatoria de Parseval sobre un subconjunto de bins.

    Devuelve un diccionario con la potencia total y la potencia media del
    canal, ambas en mW y en dBm, para cada una de las mediciones de S.
    """
    p_lineal = dbm_a_mw(S[:, indices])
    p_total_mw = p_lineal.sum(axis=1)
    p_media_mw = p_total_mw / len(indices)
    return {
        "p_total_mw": p_total_mw,
        "p_total_dbm": mw_a_dbm(p_total_mw),
        "p_media_mw": p_media_mw,
        "p_media_dbm": mw_a_dbm(p_media_mw),
        "p_pico_dbm": S[:, indices].max(axis=1),
        # Ocupacion espectral: fraccion de los 256 bins del canal que en ESTE
        # punto geografico superan el umbral de -60 dBm. Complementa a Parseval
        # porque distingue una portadora estrecha y muy fuerte de una emision
        # ancha y moderada que integran la misma potencia.
        "ocupacion_pct": 100.0 * (S[:, indices] > cfg.UMBRAL_OCUPACION_DBM).mean(axis=1),
    }


def indicadores_por_medicion(df):
    """
    Calcula, para cada punto geografico de la ruta, los indicadores de los
    cuatro canales A, B, C y D.
    """
    cols = [c for c in df.columns if c.startswith("bin_")]
    S = df[cols].to_numpy(dtype=float)

    salida = df[["archivo", "orden"] + cfg.COLS_META].copy()
    salida["gps_imputado"] = df["gps_imputado"].values
    salida["dc_imputado"] = df["dc_imputado"].values

    for canal in cfg.CANALES:
        idx = bins_de_canal(canal)
        r = parseval_canal(S, idx)
        salida["P_%s_dbm" % canal] = r["p_media_dbm"]
        salida["Ptot_%s_dbm" % canal] = r["p_total_dbm"]
        salida["Ppico_%s_dbm" % canal] = r["p_pico_dbm"]
        salida["Ocup_%s_pct" % canal] = r["ocupacion_pct"]
        salida["Ocupado_%s" % canal] = r["p_media_dbm"] > cfg.UMBRAL_OCUPACION_DBM

    # Canal mas fuerte en cada punto: sirve para el mapa de dominancia
    p_cols = ["P_%s_dbm" % c for c in cfg.CANALES]
    salida["canal_dominante"] = salida[p_cols].idxmax(axis=1).str[2]
    return salida


def resumen_por_canal(ind):
    """
    Agrega los indicadores de los 60 puntos de la ruta en una fila por canal.

    La agregacion espacial de potencias se hace en el dominio LINEAL (media de
    mW y luego conversion a dBm): es la potencia media que "ve" el area de
    estudio. Se reportan ademas la mediana en dBm, mas robusta frente a puntos
    calientes aislados, y el percentil 90 como indicador de peor caso.
    """
    filas = []
    for canal, (f_ini, f_fin) in cfg.CANALES.items():
        p_dbm = ind["P_%s_dbm" % canal].to_numpy()
        p_mw = dbm_a_mw(p_dbm)
        ocup = ind["Ocup_%s_pct" % canal].to_numpy()
        ocupado = ind["Ocupado_%s" % canal].to_numpy()

        filas.append({
            "canal": canal,
            "f_inicio_mhz": f_ini / 1e6,
            "f_fin_mhz": f_fin / 1e6,
            "P_media_dbm": mw_a_dbm(p_mw.mean()),
            "P_mediana_dbm": float(np.median(p_dbm)),
            "P_p90_dbm": float(np.percentile(p_dbm, 90)),
            "P_max_dbm": float(p_dbm.max()),
            "P_min_dbm": float(p_dbm.min()),
            "pct_puntos_ocupados": 100.0 * ocupado.mean(),
            "n_puntos_ocupados": int(ocupado.sum()),
            "ocupacion_espectral_pct": float(ocup.mean()),
            "n_puntos_dominante": int((ind["canal_dominante"] == canal).sum()),
        })

    R = pd.DataFrame(filas)
    # Indice de contaminacion relativo: normaliza la potencia media al rango
    # observado para poder rankear los cuatro canales en una escala comun 0-100
    p = R["P_media_dbm"]
    R["indice_relativo"] = (100.0 * (p - p.min()) / (p.max() - p.min())).round(1)
    return R.sort_values("P_media_dbm", ascending=False).reset_index(drop=True)


def perfil_espectral(df):
    """
    Perfil promedio de la banda: una fila por bin con la potencia media
    espacial y el porcentaje de puntos de la ruta en que ese bin esta ocupado.

    De aqui salen la "frecuencia mas contaminada" y la "menos contaminada"
    que pide el informe.
    """
    cols = [c for c in df.columns if c.startswith("bin_")]
    S = df[cols].to_numpy(dtype=float)

    p_media_mw = dbm_a_mw(S).mean(axis=0)
    frecuencias = cfg.F_INICIO_HZ + np.arange(cfg.N_BINS) * cfg.RBW_HZ

    perfil = pd.DataFrame({
        "bin": np.arange(cfg.N_BINS),
        "frecuencia_hz": frecuencias,
        "frecuencia_mhz": frecuencias / 1e6,
        "P_media_dbm": mw_a_dbm(p_media_mw),
        "P_max_dbm": S.max(axis=0),
        "P_mediana_dbm": np.median(S, axis=0),
        "ocupacion_pct": 100.0 * (S > cfg.UMBRAL_OCUPACION_DBM).mean(axis=0),
    })
    perfil["canal"] = pd.cut(
        perfil["frecuencia_hz"],
        bins=[cfg.CANALES[c][0] for c in "ABCD"] + [cfg.CANALES["D"][1]],
        labels=list("ABCD"), right=False, include_lowest=True).astype(str)
    return perfil


def frecuencias_extremas(perfil):
    """
    Selecciona la frecuencia mas y la menos contaminada del sistema.

    Criterio: se ordena por potencia media espacial (Parseval) y, ante
    potencias comparables, se desempata por porcentaje de ocupacion, porque
    una portadora presente en toda la ruta contamina el plan de frecuencias
    mucho mas que un pico intenso pero puntual.
    """
    p = perfil.copy()
    # Puntaje combinado normalizado 0-1: 70 % potencia, 30 % persistencia
    pn = (p.P_media_dbm - p.P_media_dbm.min()) / (p.P_media_dbm.max() - p.P_media_dbm.min())
    on = p.ocupacion_pct / 100.0
    p["puntaje"] = 0.7 * pn + 0.3 * on

    peor = p.loc[p["puntaje"].idxmax()]
    mejor = p.loc[p["puntaje"].idxmin()]
    return peor, mejor, p


def main():
    cfg.crear_directorios()
    df = pd.read_parquet(os.path.join(cfg.LAKE_PLATA, "medidas_limpias.parquet"))

    print("[INDICADORES] Aplicando sumatoria de Parseval sobre %d mediciones..." % len(df))
    for canal in cfg.CANALES:
        idx = bins_de_canal(canal)
        print("  Canal %s: %.0f-%.0f MHz -> bins %d..%d (%d bins de %.2f kHz)"
              % (canal, cfg.CANALES[canal][0] / 1e6, cfg.CANALES[canal][1] / 1e6,
                 idx[0], idx[-1], len(idx), cfg.RBW_HZ / 1e3))

    ind = indicadores_por_medicion(df)
    res = resumen_por_canal(ind)
    perfil = perfil_espectral(df)
    peor, mejor, perfil = frecuencias_extremas(perfil)

    print("\n  RESUMEN POR CANAL (ordenado de mas a menos contaminado)")
    print("  %-6s %-14s %11s %11s %11s %9s %9s" %
          ("canal", "banda MHz", "P_med dBm", "P_mediana", "P_max", "%pts occ", "%ocup esp"))
    for _, f in res.iterrows():
        print("  %-6s %5.0f - %-6.0f %11.2f %11.2f %11.2f %8.1f%% %8.1f%%"
              % (f.canal, f.f_inicio_mhz, f.f_fin_mhz, f.P_media_dbm,
                 f.P_mediana_dbm, f.P_max_dbm, f.pct_puntos_ocupados,
                 f.ocupacion_espectral_pct))

    print("\n  Frecuencia MAS contaminada : %.4f MHz (bin %d) -> %.2f dBm, ocupada en %.1f%% de la ruta"
          % (peor.frecuencia_mhz, peor.bin, peor.P_media_dbm, peor.ocupacion_pct))
    print("  Frecuencia MENOS contaminada: %.4f MHz (bin %d) -> %.2f dBm, ocupada en %.1f%% de la ruta"
          % (mejor.frecuencia_mhz, mejor.bin, mejor.P_media_dbm, mejor.ocupacion_pct))

    ind.to_parquet(os.path.join(cfg.LAKE_ORO, "indicadores_por_punto.parquet"), index=False)
    res.to_csv(os.path.join(cfg.LAKE_ORO, "resumen_canales.csv"), index=False, encoding="utf-8")
    perfil.to_parquet(os.path.join(cfg.LAKE_ORO, "perfil_espectral.parquet"), index=False)
    pd.DataFrame([
        {"tipo": "mas_contaminada", **peor.to_dict()},
        {"tipo": "menos_contaminada", **mejor.to_dict()},
    ]).to_csv(os.path.join(cfg.LAKE_ORO, "frecuencias_extremas.csv"), index=False, encoding="utf-8")

    print("\n[INDICADORES] Capa oro consolidada.\n")
    return ind, res, perfil


if __name__ == "__main__":
    main()

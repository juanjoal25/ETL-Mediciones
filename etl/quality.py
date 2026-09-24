# -*- coding: utf-8 -*-
"""
quality.py - FASE 2 DEL ETL: PERFILADO Y REPORTE DE CALIDAD

No modifica ningun dato. Su unica responsabilidad es DIAGNOSTICAR: aplica un
conjunto de reglas de validacion sobre la capa bronce y emite un dictamen por
cada medicion (VALIDA / IMPUTABLE / DESCARTADA) junto con las banderas que lo
justifican. La fase de transformacion consume este dictamen.

Se separa el diagnostico de la correccion porque el enunciado exige reportar
"cuantos datos ha modificado y por que": sin una capa de diagnostico explicita
ese numero no seria trazable.

REGLAS IMPLEMENTADAS
--------------------
R1  ESTRUCTURA      Cardinalidad != 1029 o campos no numericos.
R2  COMPLETITUD     NaN/Inf en el espectro o en los metadatos.
R3  GPS_SIN_FIX     lon==0 y lat==0 -> el receptor GNSS no obtuvo solucion.
R4  GPS_FUERA_RANGO Coordenadas o altura fuera del valle de Aburra.
R5  GPS_IMPRECISO   Error de distancia (HDOP) por encima del umbral.
R6  RANGO_FISICO    Potencias fuera del rango util del receptor USRP.
R7  NIVEL_ANOMALO   Traza completa desplazada en nivel (error de ganancia/AGC),
                    detectado por z-score robusto de la mediana de la traza.
R8  TRAZA_PLANA     Desviacion estandar nula -> receptor congelado.
R9  FUGA_LO_DC      Pico espurio en el bin central (offset DC del zero-IF).
R10 TEMP_OPERACION  Sensor fuera de su ventana termica de operacion.
R11 NO_CAMPANA      Archivo de prueba, ajeno a la campana de medicion.
"""

import os

import numpy as np
import pandas as pd

import config as cfg


# Severidad de cada regla: define el dictamen final de la medicion.
#   'descarte'  -> la medicion completa no es utilizable
#   'imputable' -> el defecto es local y se puede reconstruir
#   'aviso'     -> se conserva, pero se marca menor confianza
SEVERIDAD = {
    "R1_ESTRUCTURA": "descarte",
    "R2_COMPLETITUD": "imputable",
    "R3_GPS_SIN_FIX": "imputable",
    "R4_GPS_FUERA_RANGO": "imputable",
    "R5_GPS_IMPRECISO": "aviso",
    "R6_RANGO_FISICO": "descarte",
    "R7_NIVEL_ANOMALO": "descarte",
    "R8_TRAZA_PLANA": "descarte",
    "R9_FUGA_LO_DC": "imputable",
    "R10_TEMP_OPERACION": "aviso",
    "R11_NO_CAMPANA": "descarte",
}

DESCRIPCION = {
    "R1_ESTRUCTURA": "Estructura columnar invalida",
    "R2_COMPLETITUD": "Valores faltantes o no finitos",
    "R3_GPS_SIN_FIX": "GPS sin solucion de navegacion (lat=lon=0)",
    "R4_GPS_FUERA_RANGO": "Georreferenciacion fuera del area de estudio",
    "R5_GPS_IMPRECISO": "Error de distancia GPS elevado",
    "R6_RANGO_FISICO": "Potencia fuera del rango util del receptor",
    "R7_NIVEL_ANOMALO": "Traza desplazada en nivel (error de ganancia)",
    "R8_TRAZA_PLANA": "Traza sin variacion espectral (receptor congelado)",
    "R9_FUGA_LO_DC": "Fuga de oscilador local en el bin central",
    "R10_TEMP_OPERACION": "Temperatura del sensor fuera de operacion",
    "R11_NO_CAMPANA": "Archivo de prueba ajeno a la campana",
}


def _cols_espectro(df):
    return [c for c in df.columns if c.startswith("bin_")]


def _vecinos_dc():
    """Indices de los bins vecinos usados como referencia del pico DC."""
    c, w = cfg.BIN_DC, cfg.ANCHO_DC
    izq = list(range(c - w - 3, c - w))
    der = list(range(c + w + 1, c + w + 4))
    return izq + der


def evaluar(df):
    """
    Aplica las 11 reglas y devuelve (df_banderas, detalle_dc).

    df_banderas : una fila por medicion, una columna booleana por regla,
                  mas 'dictamen', 'n_banderas' y 'detalle'.
    detalle_dc  : Series con el exceso en dB del bin DC sobre sus vecinos.
    """
    cols = _cols_espectro(df)
    S = df[cols].to_numpy(dtype=float)
    n = len(df)

    B = pd.DataFrame(index=df.index)
    B["archivo"] = df["archivo"].values
    detalle = [[] for _ in range(n)]

    # --- R1 estructura -----------------------------------------------------
    B["R1_ESTRUCTURA"] = (df["incidencias_extraccion"].fillna("") != "").values

    # --- R2 completitud ----------------------------------------------------
    no_finito_esp = ~np.isfinite(S)
    meta = df[cfg.COLS_META].to_numpy(dtype=float)
    no_finito_meta = ~np.isfinite(meta)
    B["R2_COMPLETITUD"] = no_finito_esp.any(axis=1) | no_finito_meta.any(axis=1)

    # --- R3 GPS sin fix ----------------------------------------------------
    lon, lat, alt = df["longitud"].values, df["latitud"].values, df["altura"].values
    sin_fix = (np.abs(lon) < 1e-9) & (np.abs(lat) < 1e-9)
    B["R3_GPS_SIN_FIX"] = sin_fix

    # --- R4 GPS fuera de rango --------------------------------------------
    fuera = (~sin_fix) & (
        (lat < cfg.LAT_MIN) | (lat > cfg.LAT_MAX) |
        (lon < cfg.LON_MIN) | (lon > cfg.LON_MAX) |
        (alt < cfg.ALT_MIN) | (alt > cfg.ALT_MAX)
    )
    # la altura en cero acompana siempre al fix perdido: se marca como R3, no R4
    B["R4_GPS_FUERA_RANGO"] = fuera

    # --- R5 GPS impreciso --------------------------------------------------
    hdop = df["error_distancia"].values
    B["R5_GPS_IMPRECISO"] = hdop > cfg.HDOP_MAX
    for i in np.where(B["R5_GPS_IMPRECISO"].values)[0]:
        detalle[i].append("HDOP=%.1f" % hdop[i])

    # --- R6 rango fisico del receptor -------------------------------------
    maximos = np.nanmax(S, axis=1)
    minimos = np.nanmin(S, axis=1)
    B["R6_RANGO_FISICO"] = (maximos > cfg.DBM_MAX_FISICO) | (minimos < cfg.DBM_MIN_FISICO)
    for i in np.where(B["R6_RANGO_FISICO"].values)[0]:
        detalle[i].append("pico=%.1f dBm" % maximos[i])

    # --- R7 nivel anomalo (z-score robusto sobre la mediana de la traza) ---
    # Se usa mediana/MAD en vez de media/desviacion para que el propio outlier
    # no contamine el estadistico de referencia.
    medianas = np.nanmedian(S, axis=1)
    med_ref = np.nanmedian(medianas)
    mad = np.nanmedian(np.abs(medianas - med_ref))
    sigma = 1.4826 * mad if mad > 0 else np.nanstd(medianas)
    z = (medianas - med_ref) / sigma if sigma > 0 else np.zeros(n)
    B["R7_NIVEL_ANOMALO"] = np.abs(z) > cfg.Z_MEDIANA_MAX
    for i in np.where(B["R7_NIVEL_ANOMALO"].values)[0]:
        detalle[i].append("mediana=%.1f dBm (z=%.1f)" % (medianas[i], z[i]))

    # --- R8 traza plana ----------------------------------------------------
    B["R8_TRAZA_PLANA"] = np.nanstd(S, axis=1) < 1e-6

    # --- R9 fuga de oscilador local en el bin central ----------------------
    vec = _vecinos_dc()
    ref = np.nanmedian(S[:, vec], axis=1)
    centro = np.nanmax(S[:, cfg.BIN_DC - cfg.ANCHO_DC: cfg.BIN_DC + cfg.ANCHO_DC + 1], axis=1)
    exceso_dc = centro - ref
    B["R9_FUGA_LO_DC"] = exceso_dc > cfg.DELTA_DC_DB
    for i in np.where(B["R9_FUGA_LO_DC"].values)[0]:
        detalle[i].append("DC +%.1f dB" % exceso_dc[i])

    # --- R10 temperatura fuera de operacion --------------------------------
    T = df["temperatura"].values
    B["R10_TEMP_OPERACION"] = (T < cfg.TEMP_MIN_OPERACION) | (T > cfg.TEMP_MAX_OPERACION)
    for i in np.where(B["R10_TEMP_OPERACION"].values)[0]:
        detalle[i].append("T=%.1f C" % T[i])

    # --- R11 archivos ajenos a la campana ----------------------------------
    nombre_bajo = df["archivo"].str.lower()
    ajeno = np.zeros(n, dtype=bool)
    for patron in cfg.PATRONES_DESCARTE:
        ajeno |= nombre_bajo.str.contains(patron).values
    B["R11_NO_CAMPANA"] = ajeno

    # --- dictamen ----------------------------------------------------------
    reglas = [c for c in B.columns if c.startswith("R")]
    B["n_banderas"] = B[reglas].sum(axis=1)

    def _dictamen(fila):
        activas = [r for r in reglas if fila[r]]
        if any(SEVERIDAD[r] == "descarte" for r in activas):
            return "DESCARTADA"
        if any(SEVERIDAD[r] == "imputable" for r in activas):
            return "IMPUTABLE"
        if activas:
            return "VALIDA_CON_AVISO"
        return "VALIDA"

    B["dictamen"] = B.apply(_dictamen, axis=1)
    B["reglas_activas"] = B[reglas].apply(
        lambda f: ";".join([r for r in reglas if f[r]]), axis=1)
    B["detalle"] = [" | ".join(d) for d in detalle]

    return B, pd.Series(exceso_dc, index=df.index, name="exceso_dc_db")


def resumen(B):
    """Construye el resumen agregado que alimenta el informe de calidad."""
    reglas = [c for c in B.columns if c.startswith("R")]
    filas = []
    for r in reglas:
        n = int(B[r].sum())
        filas.append({
            "regla": r,
            "descripcion": DESCRIPCION[r],
            "severidad": SEVERIDAD[r],
            "mediciones_afectadas": n,
            "porcentaje": round(100.0 * n / len(B), 2),
            "archivos": ", ".join(B.loc[B[r], "archivo"].tolist()[:8]),
        })
    return pd.DataFrame(filas)


def indicadores_globales(df, B):
    """
    Metricas DAMA de calidad de datos a nivel de dataset.

    Completitud  : % de celdas presentes y finitas
    Validez      : % de celdas dentro del rango fisico esperado
    Unicidad     : % de mediciones no duplicadas
    Consistencia : % de mediciones sin banderas de severidad alta
    Exactitud    : % de mediciones con georreferenciacion confiable
    """
    cols = _cols_espectro(df)
    S = df[cols].to_numpy(dtype=float)
    meta = df[cfg.COLS_META].to_numpy(dtype=float)
    total_celdas = S.size + meta.size

    completitud = 100.0 * (np.isfinite(S).sum() + np.isfinite(meta).sum()) / total_celdas

    en_rango = ((S >= cfg.DBM_MIN_FISICO) & (S <= cfg.DBM_MAX_FISICO)).sum()
    validez = 100.0 * en_rango / S.size

    duplicados = df[cols].duplicated().sum()
    unicidad = 100.0 * (len(df) - duplicados) / len(df)

    graves = B["dictamen"].eq("DESCARTADA").sum()
    consistencia = 100.0 * (len(B) - graves) / len(B)

    gps_malo = (B["R3_GPS_SIN_FIX"] | B["R4_GPS_FUERA_RANGO"] | B["R5_GPS_IMPRECISO"]).sum()
    exactitud = 100.0 * (len(B) - gps_malo) / len(B)

    global_ = np.mean([completitud, validez, unicidad, consistencia, exactitud])

    return pd.DataFrame([
        {"dimension": "Completitud", "valor_pct": round(completitud, 2),
         "definicion": "Celdas presentes y finitas sobre el total"},
        {"dimension": "Validez", "valor_pct": round(validez, 2),
         "definicion": "Muestras dentro del rango fisico del receptor"},
        {"dimension": "Unicidad", "valor_pct": round(unicidad, 2),
         "definicion": "Mediciones no duplicadas"},
        {"dimension": "Consistencia", "valor_pct": round(consistencia, 2),
         "definicion": "Mediciones sin defecto de severidad alta"},
        {"dimension": "Exactitud", "valor_pct": round(exactitud, 2),
         "definicion": "Mediciones con georreferenciacion confiable"},
        {"dimension": "INDICE GLOBAL", "valor_pct": round(global_, 2),
         "definicion": "Promedio de las cinco dimensiones"},
    ])


def main():
    cfg.crear_directorios()
    df = pd.read_parquet(os.path.join(cfg.LAKE_BRONCE, "medidas_crudas.parquet"))

    print("[CALIDAD] Evaluando %d mediciones contra 11 reglas..." % len(df))
    B, exceso_dc = evaluar(df)
    R = resumen(B)
    G = indicadores_globales(df, B)

    print("\n  Dictamen:")
    for k, v in B["dictamen"].value_counts().items():
        print("    %-18s %d" % (k, v))

    print("\n  Reglas activadas:")
    for _, f in R[R.mediciones_afectadas > 0].iterrows():
        print("    %-20s %-9s %2d medicion(es)  %s"
              % (f.regla, "[%s]" % f.severidad, f.mediciones_afectadas, f.descripcion))

    print("\n  Indices de calidad:")
    for _, f in G.iterrows():
        print("    %-14s %6.2f %%" % (f.dimension, f.valor_pct))

    B.to_parquet(os.path.join(cfg.LAKE_PLATA, "banderas_calidad.parquet"), index=False)
    R.to_csv(os.path.join(cfg.LAKE_PLATA, "reporte_reglas.csv"), index=False, encoding="utf-8")
    G.to_csv(os.path.join(cfg.LAKE_PLATA, "indices_calidad.csv"), index=False, encoding="utf-8")
    exceso_dc.to_frame().assign(archivo=df["archivo"].values).to_parquet(
        os.path.join(cfg.LAKE_PLATA, "exceso_dc.parquet"), index=False)

    print("\n[CALIDAD] Reporte escrito en la capa plata.\n")
    return B, R, G


if __name__ == "__main__":
    main()

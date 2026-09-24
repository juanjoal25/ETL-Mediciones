# -*- coding: utf-8 -*-
"""
transform.py - FASE 3 DEL ETL: LIMPIEZA, IMPUTACION Y CALIBRACION (capa PLATA)

Consume la capa bronce + el dictamen de quality.py y produce un dataset
homogeneo apto para el modelo, llevando la cuenta exacta de cada celda
modificada (el enunciado exige reportar "cuantos datos ha modificado y por que").

ORDEN DE OPERACIONES (importa, y esta justificado)
--------------------------------------------------
  P0  Descarte de mediciones con dictamen DESCARTADA.
  P1  T1 - Imputacion de la fuga de oscilador local (dominio frecuencia).
  P2  T2 - Imputacion de georreferenciacion (dominio espacio-temporal).
  P3  T3 - Calibracion por desacople de antena (correccion determinista).
  P4  T4 - Regla de negocio del enunciado: valores < -65.0 dBm -> -95.0 dBm.

Se corrigen primero los artefactos instrumentales (P1) y despues se calibra
(P3), porque la calibracion es un desplazamiento en nivel que no tiene sentido
aplicar sobre un espurio. La regla de censura del enunciado (P4) va de ultima
porque opera sobre la medida ya calibrada, que es la que representa la potencia
realmente incidente sobre la antena.

TECNICAS DE IMPUTACION EMPLEADAS
--------------------------------
  T1  Interpolacion lineal en potencia lineal (mW) sobre el eje de frecuencia.
      Se aplica a los 3 bins centrales contaminados por la fuga de LO. Es
      valida porque la envolvente espectral de una portadora celular es suave
      en una ventana de 59 kHz (3 bins x 19.53 kHz).
  T2  Interpolacion lineal sobre la secuencia de la ruta. La estacion es movil
      y se desplaza de forma aproximadamente continua, de modo que la posicion
      de una medicion sin fix se estima a partir de las mediciones anterior y
      posterior con fix valido.
  T3  Des-incrustacion (de-embedding) de la perdida por desacople de la antena,
      calculada del barrido S11 medido con el Agilent N9914A. No es imputacion
      sino correccion sistematica: compensa un sesgo dependiente de frecuencia
      que favorecia artificialmente al canal A frente al canal D.
  T4  Sustitucion por valor constante (censura del piso de ruido) impuesta por
      el enunciado: toda muestra por debajo de -65.0 dBm se lleva a -95.0 dBm.
"""

import os

import numpy as np
import pandas as pd

import config as cfg
import quality


def dbm_a_mw(x):
    """Convierte dBm a mW (dominio lineal de potencia)."""
    return 10.0 ** (np.asarray(x, dtype=float) / 10.0)


def mw_a_dbm(x):
    """Convierte mW a dBm protegiendo el logaritmo de ceros."""
    return 10.0 * np.log10(np.maximum(np.asarray(x, dtype=float), 1e-30))


# ---------------------------------------------------------------------------
# T1 - FUGA DE OSCILADOR LOCAL
# ---------------------------------------------------------------------------
def imputar_fuga_lo(S, afectadas):
    """
    Reemplaza los bins contaminados por el offset DC del receptor zero-IF.

    En un receptor de conversion directa el offset DC del mezclador y la fuga
    del oscilador local se suman en la componente de continua de la senal
    banda base. Tras el numpy.fft.fftshift esa componente cae exactamente en
    el bin N/2, es decir en 850.000 MHz, que es justo la frontera entre los
    canales B y C. De no corregirse, el espurio se contabilizaria como
    ocupacion real y sesgaria el indicador de ambos canales.

    Parametros
    ----------
    S : ndarray (n_mediciones, 1024) en dBm
    afectadas : array booleano de mediciones donde se detecto la fuga

    Devuelve (S_corregido, n_celdas_modificadas)
    """
    S = S.copy()
    c, w = cfg.BIN_DC, cfg.ANCHO_DC
    objetivo = np.arange(c - w, c + w + 1)                 # bins 511, 512, 513
    apoyo = np.array(list(range(c - w - 3, c - w)) +
                     list(range(c + w + 1, c + w + 4)))     # 508..510 y 514..516

    n_mod = 0
    for i in np.where(afectadas)[0]:
        # La interpolacion se hace en potencia lineal, no en dB: promediar
        # decibelios equivale a una media geometrica de potencias y subestima
        # el nivel real de la envolvente.
        p_apoyo = dbm_a_mw(S[i, apoyo])
        p_interp = np.interp(objetivo, apoyo, p_apoyo)
        S[i, objetivo] = mw_a_dbm(p_interp)
        n_mod += len(objetivo)

    return S, n_mod


# ---------------------------------------------------------------------------
# T2 - GEORREFERENCIACION
# ---------------------------------------------------------------------------
def imputar_posicion(df, banderas):
    """
    Reconstruye la posicion de las mediciones sin fix GPS o con HDOP excesivo.

    La estacion es movil y recorre una ruta continua, de modo que la posicion
    en el instante k puede estimarse interpolando linealmente entre las
    posiciones validas anterior y posterior en la secuencia de medicion. Es el
    equivalente espacio-temporal de la interpolacion de la sesion 7 del curso.

    Devuelve (df_corregido, n_celdas_modificadas, detalle)
    """
    df = df.copy()
    sospechosa = (banderas["R3_GPS_SIN_FIX"] |
                  banderas["R4_GPS_FUERA_RANGO"] |
                  banderas["R5_GPS_IMPRECISO"]).to_numpy()

    df["gps_imputado"] = sospechosa
    n_mod, detalle = 0, []

    orden = df["orden"].to_numpy(dtype=float)
    validas = ~sospechosa

    for col in ("longitud", "latitud", "altura"):
        v = df[col].to_numpy(dtype=float).copy()
        if validas.sum() >= 2:
            v_imp = np.interp(orden[sospechosa], orden[validas], v[validas])
            for pos, idx in enumerate(np.where(sospechosa)[0]):
                detalle.append({
                    "archivo": df["archivo"].iloc[idx],
                    "campo": col,
                    "valor_original": v[idx],
                    "valor_imputado": float(v_imp[pos]),
                    "tecnica": "T2_interp_lineal_ruta",
                })
            v[sospechosa] = v_imp
            n_mod += int(sospechosa.sum())
        df[col] = v

    return df, n_mod, pd.DataFrame(detalle)


# ---------------------------------------------------------------------------
# T3 - CALIBRACION DE ANTENA
# ---------------------------------------------------------------------------
def calibrar_antena(S, frecuencias, df_antena):
    """
    Des-incrusta la perdida por desacople de la antena de monitoreo.

    De la medida S11 se obtiene el coeficiente de reflexion en potencia
    |Gamma|^2 = 10^(S11/10). La fraccion de potencia que la antena entrega al
    receptor es (1 - |Gamma|^2), por lo que la potencia realmente incidente es

        P_incidente[dBm] = P_medida[dBm] + L_desacople(f)[dB]
        L_desacople(f)   = -10*log10(1 - |Gamma(f)|^2)

    En esta antena L_desacople pasa de 1.33 dB en 840 MHz a 0.64 dB en 860 MHz.
    Ese gradiente de 0.7 dB a lo largo de la banda inflaba sistematicamente el
    canal A respecto del canal D: corregirlo es indispensable para comparar
    los cuatro canales en condiciones equivalentes.

    Devuelve (S_calibrado, correccion_por_bin_db)
    """
    if df_antena is None or df_antena.empty:
        return S.copy(), np.zeros(S.shape[1])

    correccion = np.interp(frecuencias,
                           df_antena["frecuencia_hz"].to_numpy(),
                           df_antena["perdida_desacople_db"].to_numpy())
    return S + correccion[None, :], correccion


# ---------------------------------------------------------------------------
# T4 - REGLA DE CENSURA DEL ENUNCIADO
# ---------------------------------------------------------------------------
def aplicar_regla_piso(S):
    """
    Regla del enunciado: toda muestra < -65.0 dBm se sustituye por -95.0 dBm.

    Interpretacion tecnica: el enunciado fija en -65 dBm el umbral de deteccion
    util del sistema de monitoreo. Por debajo de ese nivel no se puede afirmar
    que exista emision, solo ruido del receptor, de modo que la muestra se
    censura llevandola a un piso convencional de -95 dBm. El efecto practico es
    eliminar la contribucion del ruido termico a la suma de Parseval, que de
    otro modo acumularia 256 bins de ruido por canal y enmascararia la
    diferencia entre un canal limpio y uno ocupado.

    Devuelve (S_censurado, n_celdas_modificadas)
    """
    S = S.copy()
    mascara = S < cfg.UMBRAL_PISO_DBM
    S[mascara] = cfg.VALOR_PISO_DBM
    return S, int(mascara.sum())


# ---------------------------------------------------------------------------
# ORQUESTACION
# ---------------------------------------------------------------------------
def transformar(df_crudo, banderas, df_antena):
    """Ejecuta P0..P4 y devuelve (df_limpio, bitacora, detalle_gps, correccion)."""
    cols = [c for c in df_crudo.columns if c.startswith("bin_")]
    frecuencias = cfg.F_INICIO_HZ + np.arange(cfg.N_BINS) * cfg.RBW_HZ
    bitacora = []

    n_celdas_inicial = df_crudo[cols].size + df_crudo[cfg.COLS_META].size

    # --- P0: descarte -------------------------------------------------------
    conservar = banderas["dictamen"].ne("DESCARTADA").to_numpy()
    descartadas = banderas.loc[~conservar, ["archivo", "reglas_activas", "detalle"]]
    df = df_crudo.loc[conservar].reset_index(drop=True)
    B = banderas.loc[conservar].reset_index(drop=True)
    bitacora.append({
        "paso": "P0_DESCARTE",
        "tecnica": "Eliminacion de registro",
        "unidad": "mediciones",
        "cantidad": int((~conservar).sum()),
        "motivo": "Dictamen DESCARTADA: fuera de rango fisico, nivel anomalo o archivo de prueba",
    })

    S = df[cols].to_numpy(dtype=float)

    # --- P1: fuga de oscilador local ---------------------------------------
    S, n_dc = imputar_fuga_lo(S, B["R9_FUGA_LO_DC"].to_numpy())
    bitacora.append({
        "paso": "P1_FUGA_LO",
        "tecnica": "T1 Interpolacion lineal en potencia (eje frecuencia)",
        "unidad": "celdas espectrales",
        "cantidad": n_dc,
        "motivo": "Offset DC del receptor zero-IF en el bin 512 (850.000 MHz), frontera B/C",
    })

    # --- P2: georreferenciacion --------------------------------------------
    df, n_gps, detalle_gps = imputar_posicion(df, B)
    bitacora.append({
        "paso": "P2_GEORREFERENCIACION",
        "tecnica": "T2 Interpolacion lineal sobre la secuencia de la ruta",
        "unidad": "celdas de metadato",
        "cantidad": n_gps,
        "motivo": "GPS sin solucion de navegacion o error de distancia (HDOP) por encima de %.1f" % cfg.HDOP_MAX,
    })

    # --- P3: calibracion de antena -----------------------------------------
    S_cal, correccion = calibrar_antena(S, frecuencias, df_antena)
    bitacora.append({
        "paso": "P3_CALIBRACION_ANTENA",
        "tecnica": "T3 De-embedding de la perdida por desacople (S11)",
        "unidad": "celdas espectrales",
        "cantidad": int(S.size) if df_antena is not None else 0,
        "motivo": "Compensacion del gradiente de %.2f dB entre 840 y 860 MHz medido con el Agilent N9914A"
                  % (correccion[0] - correccion[-1]),
    })

    # Sensibilidad: cuantas muestras cambian de lado del umbral por calibrar
    cruces = int((((S < cfg.UMBRAL_PISO_DBM) & (S_cal >= cfg.UMBRAL_PISO_DBM)) |
                  ((S >= cfg.UMBRAL_PISO_DBM) & (S_cal < cfg.UMBRAL_PISO_DBM))).sum())

    # --- P4: regla de censura del enunciado ---------------------------------
    S_final, n_piso = aplicar_regla_piso(S_cal)
    bitacora.append({
        "paso": "P4_REGLA_PISO",
        "tecnica": "T4 Sustitucion por constante (censura de piso de ruido)",
        "unidad": "celdas espectrales",
        "cantidad": n_piso,
        "motivo": "Regla del enunciado: muestras < %.1f dBm se llevan a %.1f dBm"
                  % (cfg.UMBRAL_PISO_DBM, cfg.VALOR_PISO_DBM),
    })

    df[cols] = S_final
    # Se anexan las trazas de calidad de una sola vez para no fragmentar el frame
    df = pd.concat([df, pd.DataFrame({
        "dictamen_calidad": B["dictamen"].values,
        "reglas_activas": B["reglas_activas"].values,
        "dc_imputado": B["R9_FUGA_LO_DC"].values,
    }, index=df.index)], axis=1)

    bit = pd.DataFrame(bitacora)
    bit["pct_del_dataset"] = (100.0 * bit["cantidad"] / n_celdas_inicial).round(3)

    meta = {
        "celdas_totales": n_celdas_inicial,
        "cruces_umbral_por_calibracion": cruces,
        "descartadas": descartadas,
        "correccion_antena_db": correccion,
        "frecuencias_hz": frecuencias,
    }
    return df, bit, detalle_gps, meta


def main():
    cfg.crear_directorios()

    df_crudo = pd.read_parquet(os.path.join(cfg.LAKE_BRONCE, "medidas_crudas.parquet"))
    ruta_ant = os.path.join(cfg.LAKE_BRONCE, "antena_s11.parquet")
    df_antena = pd.read_parquet(ruta_ant) if os.path.exists(ruta_ant) else None

    banderas, _ = quality.evaluar(df_crudo)

    print("[TRANSFORMACION] Aplicando limpieza, imputacion y calibracion...")
    df, bit, detalle_gps, meta = transformar(df_crudo, banderas, df_antena)

    print("\n  Bitacora de modificaciones:")
    for _, f in bit.iterrows():
        print("    %-24s %-52s %7d %-20s (%.3f %% del dataset)"
              % (f.paso, f.tecnica, f.cantidad, f.unidad, f.pct_del_dataset))

    print("\n  Mediciones descartadas:")
    for _, f in meta["descartadas"].iterrows():
        print("    %-20s %-40s %s" % (f.archivo, f.reglas_activas, f.detalle))

    print("\n  Posiciones imputadas:")
    for arch in detalle_gps["archivo"].unique():
        sub = detalle_gps[detalle_gps.archivo == arch]
        val = {r.campo: (r.valor_original, r.valor_imputado) for r in sub.itertuples()}
        print("    %-16s lon %.6f -> %.6f | lat %.6f -> %.6f | alt %.1f -> %.1f"
              % (arch, val["longitud"][0], val["longitud"][1],
                 val["latitud"][0], val["latitud"][1],
                 val["altura"][0], val["altura"][1]))

    print("\n  Mediciones conservadas : %d de %d" % (len(df), len(df_crudo)))
    print("  Muestras que cruzan el umbral por la calibracion de antena: %d"
          % meta["cruces_umbral_por_calibracion"])

    df.to_parquet(os.path.join(cfg.LAKE_PLATA, "medidas_limpias.parquet"), index=False)
    bit.to_csv(os.path.join(cfg.LAKE_PLATA, "bitacora_imputacion.csv"), index=False, encoding="utf-8")
    # Metricas sueltas de la transformacion que el informe necesita citar
    pd.DataFrame([{
        "mediciones_entrada": len(df_crudo),
        "mediciones_conservadas": len(df),
        "celdas_totales": meta["celdas_totales"],
        "cruces_umbral_por_calibracion": meta["cruces_umbral_por_calibracion"],
        "gradiente_antena_db": float(meta["correccion_antena_db"][0] -
                                     meta["correccion_antena_db"][-1]),
    }]).to_csv(os.path.join(cfg.LAKE_PLATA, "meta_transformacion.csv"),
               index=False, encoding="utf-8")
    detalle_gps.to_csv(os.path.join(cfg.LAKE_PLATA, "detalle_gps_imputado.csv"), index=False, encoding="utf-8")
    meta["descartadas"].to_csv(os.path.join(cfg.LAKE_PLATA, "mediciones_descartadas.csv"),
                               index=False, encoding="utf-8")

    print("\n[TRANSFORMACION] Capa plata consolidada.\n")
    return df, bit


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
temperatura.py - ANALISIS DE INCIDENCIA TERMICA SOBRE LA CALIDAD DEL DATO

Responde la pregunta del enunciado: "identificar si la temperatura del sensor
tiene una incidencia con la calidad de los datos medidos".

EL PROBLEMA METODOLOGICO
------------------------
La temperatura del USRP crece de forma casi monotona a lo largo de la campana
(el equipo se calienta mientras opera). Por eso temperatura y ORDEN DE MEDICION
estan fuertemente correlacionadas, y con ellas tambien la POSICION, porque la
estacion se desplaza en el tiempo. Una correlacion simple entre temperatura y
cualquier metrica de calidad seria espuria: estaria midiendo el efecto del
recorrido, no el del calentamiento del receptor.

La estrategia es por tanto:
  1. Cuantificar el grado de confusion (temperatura vs orden vs altura).
  2. Calcular CORRELACIONES PARCIALES que descuenten el efecto del tiempo.
  3. Ajustar una REGRESION MULTIVARIADA piso_ruido ~ T + orden + altura y
     evaluar la significancia del coeficiente de temperatura.
  4. Contrastar el resultado empirico contra la COTA FISICA TEORICA: cuanto
     PUEDE subir el piso de ruido por el calentamiento observado.

COTA FISICA
-----------
La potencia de ruido termico a la entrada del receptor es N = k*T*B*F. Si la
temperatura fisica pasa de T1 a T2 (en kelvin), el incremento maximo atribuible
al termino kT es 10*log10(T2/T1). Para 42.8 C -> 50.4 C (315.9 K -> 323.6 K)
eso son apenas 0.10 dB. Cualquier variacion observada muy por encima de ese
valor NO puede explicarse por ruido termico y debe atribuirse a deriva de la
figura de ruido / ganancia del front-end, o simplemente al cambio de entorno
radioelectrico a lo largo de la ruta.
"""

import os

import numpy as np
import pandas as pd
from scipy import stats

import config as cfg

CERO_ABSOLUTO_K = 273.15


def correlacion_parcial(x, y, z):
    """
    Correlacion parcial de Pearson entre x e y, controlando por z.

    Se obtiene correlacionando los residuos de regresar x sobre z con los
    residuos de regresar y sobre z: mide la asociacion que queda entre x e y
    una vez removido todo lo que ambas comparten con z.

    Devuelve (r_parcial, p_valor).
    """
    x, y, z = map(np.asarray, (x, y, z))
    Z = np.column_stack([np.ones_like(z), z])

    rx = x - Z @ np.linalg.lstsq(Z, x, rcond=None)[0]
    ry = y - Z @ np.linalg.lstsq(Z, y, rcond=None)[0]

    r, _ = stats.pearsonr(rx, ry)
    n, k = len(x), 1
    gl = n - k - 2
    if abs(r) >= 1.0 or gl <= 0:
        return r, 0.0
    t = r * np.sqrt(gl / (1.0 - r ** 2))
    p = 2.0 * stats.t.sf(abs(t), gl)
    return r, p


def ols(y, X, nombres):
    """
    Minimos cuadrados ordinarios con errores estandar, estadistico t y p-valor.

    Se implementa a mano (numpy) para no anadir dependencias y para dejar
    explicita la matematica: beta = (X'X)^-1 X'y.
    """
    X = np.column_stack([np.ones(len(y))] + [np.asarray(c, dtype=float) for c in X])
    y = np.asarray(y, dtype=float)
    n, k = X.shape

    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta
    gl = n - k
    s2 = (resid @ resid) / gl
    se = np.sqrt(np.diag(s2 * XtX_inv))
    t = beta / se
    p = 2.0 * stats.t.sf(np.abs(t), gl)

    sst = ((y - y.mean()) ** 2).sum()
    r2 = 1.0 - (resid @ resid) / sst
    r2_aj = 1.0 - (1.0 - r2) * (n - 1) / gl

    tabla = pd.DataFrame({
        "variable": ["intercepto"] + list(nombres),
        "coeficiente": beta,
        "error_estandar": se,
        "t": t,
        "p_valor": p,
        "significativo_5pct": p < 0.05,
    })
    return tabla, r2, r2_aj


def metricas_de_calidad(df_crudo, banderas):
    """
    Construye, por medicion, las metricas de calidad que se van a contrastar
    contra la temperatura. Se calculan sobre el espectro CRUDO, antes de la
    calibracion de antena, para que la deriva instrumental que se quiere medir
    no quede mezclada con una correccion aplicada por el propio proceso.
    """
    cols = [c for c in df_crudo.columns if c.startswith("bin_")]
    S = df_crudo[cols].to_numpy(dtype=float)

    # Piso de ruido: percentil 5 de la traza. Es robusto porque las emisiones
    # ocupan una fraccion minoritaria de los 1024 bins.
    piso = np.percentile(S, 5, axis=1)

    # Exceso del bin DC sobre sus vecinos: mide la fuga de oscilador local,
    # que es el artefacto instrumental sensible a la deriva del mezclador.
    c, w = cfg.BIN_DC, cfg.ANCHO_DC
    vec = list(range(c - w - 3, c - w)) + list(range(c + w + 1, c + w + 4))
    exceso_dc = S[:, c - w:c + w + 1].max(axis=1) - np.median(S[:, vec], axis=1)

    reglas = [x for x in banderas.columns if x.startswith("R")]

    return pd.DataFrame({
        "archivo": df_crudo["archivo"].values,
        "orden": df_crudo["orden"].values,
        "temperatura": df_crudo["temperatura"].values,
        "altura": df_crudo["altura"].values,
        "hdop": df_crudo["error_distancia"].values,
        "piso_ruido_dbm": piso,
        "rango_dinamico_db": S.max(axis=1) - piso,
        "exceso_dc_db": exceso_dc,
        "n_banderas": banderas[reglas].sum(axis=1).values,
    })


def analizar(df_crudo, banderas):
    """Ejecuta el analisis completo y devuelve un diccionario de resultados."""
    M = metricas_de_calidad(df_crudo, banderas)

    # Solo la campana real: los archivos de prueba y la traza con error de
    # ganancia distorsionarian por completo cualquier regresion.
    valido = banderas["dictamen"].ne("DESCARTADA").to_numpy()
    M = M.loc[valido].dropna(subset=["orden"]).reset_index(drop=True)

    T = M["temperatura"].to_numpy()
    orden = M["orden"].to_numpy()
    alt = M["altura"].to_numpy()

    # --- 1. Grado de confusion --------------------------------------------
    r_to, p_to = stats.pearsonr(T, orden)
    r_ta, p_ta = stats.pearsonr(T, alt)

    # --- 2. Correlaciones simples y parciales ------------------------------
    objetivos = {
        "piso_ruido_dbm": "Piso de ruido (percentil 5 de la traza)",
        "exceso_dc_db": "Fuga de oscilador local en el bin central",
        "hdop": "Error de distancia del GPS",
        "n_banderas": "Numero de banderas de calidad activas",
        "rango_dinamico_db": "Rango dinamico de la traza",
    }
    filas = []
    for col, desc in objetivos.items():
        y = M[col].to_numpy(dtype=float)
        if np.std(y) < 1e-12:
            continue
        r_s, p_s = stats.pearsonr(T, y)
        rho, p_rho = stats.spearmanr(T, y)
        r_p, p_p = correlacion_parcial(T, y, orden)
        filas.append({
            "metrica": col,
            "descripcion": desc,
            "r_pearson": r_s, "p_pearson": p_s,
            "rho_spearman": rho, "p_spearman": p_rho,
            "r_parcial_ctrl_orden": r_p, "p_parcial": p_p,
            "significativa_5pct": p_p < 0.05,
        })
    correlaciones = pd.DataFrame(filas)

    # --- 3. Regresion multivariada del piso de ruido ------------------------
    tabla_ols, r2, r2_aj = ols(
        M["piso_ruido_dbm"].to_numpy(),
        [T, orden, alt],
        ["temperatura_C", "orden_medicion", "altura_m"])

    # Modelo univariado de referencia (el que daria una lectura ingenua)
    tabla_simple, r2_simple, _ = ols(
        M["piso_ruido_dbm"].to_numpy(), [T], ["temperatura_C"])

    # --- 4. Cota fisica del ruido termico -----------------------------------
    t1, t2 = T.min(), T.max()
    cota_db = 10.0 * np.log10((t2 + CERO_ABSOLUTO_K) / (t1 + CERO_ABSOLUTO_K))
    pendiente_obs = float(tabla_ols.loc[tabla_ols.variable == "temperatura_C", "coeficiente"].iloc[0])
    efecto_obs_db = pendiente_obs * (t2 - t1)

    # --- 5. Contraste de grupos frio vs caliente ----------------------------
    mediana_T = np.median(T)
    frio = M.loc[T <= mediana_T, "piso_ruido_dbm"].to_numpy()
    caliente = M.loc[T > mediana_T, "piso_ruido_dbm"].to_numpy()
    t_stat, p_t = stats.ttest_ind(caliente, frio, equal_var=False)

    return {
        "metricas": M,
        "correlaciones": correlaciones,
        "ols": tabla_ols, "r2": r2, "r2_ajustado": r2_aj,
        "ols_simple": tabla_simple, "r2_simple": r2_simple,
        "confusion": {"r_temp_orden": r_to, "p_temp_orden": p_to,
                      "r_temp_altura": r_ta, "p_temp_altura": p_ta},
        "fisica": {"T_min_C": float(t1), "T_max_C": float(t2),
                   "delta_T_C": float(t2 - t1),
                   "cota_teorica_db": float(cota_db),
                   "pendiente_observada_db_por_C": pendiente_obs,
                   "efecto_observado_db": float(efecto_obs_db)},
        "grupos": {"mediana_T": float(mediana_T),
                   "piso_frio_dbm": float(frio.mean()),
                   "piso_caliente_dbm": float(caliente.mean()),
                   "diferencia_db": float(caliente.mean() - frio.mean()),
                   "t": float(t_stat), "p_valor": float(p_t)},
    }


def main():
    import quality

    cfg.crear_directorios()
    df_crudo = pd.read_parquet(os.path.join(cfg.LAKE_BRONCE, "medidas_crudas.parquet"))
    banderas, _ = quality.evaluar(df_crudo)

    print("[TEMPERATURA] Analizando incidencia termica sobre la calidad...")
    R = analizar(df_crudo, banderas)

    c = R["confusion"]
    print("\n  1) CONFUSION (por que no basta una correlacion simple)")
    print("     temperatura vs orden de medicion : r = %+.3f (p = %.2e)" % (c["r_temp_orden"], c["p_temp_orden"]))
    print("     temperatura vs altura            : r = %+.3f (p = %.3f)" % (c["r_temp_altura"], c["p_temp_altura"]))

    print("\n  2) CORRELACIONES (simple vs parcial controlando el orden)")
    print("     %-22s %9s %9s %9s %9s" % ("metrica", "r simple", "rho", "r parcial", "p parcial"))
    for _, f in R["correlaciones"].iterrows():
        print("     %-22s %+9.3f %+9.3f %+9.3f %9.4f %s"
              % (f.metrica, f.r_pearson, f.rho_spearman, f.r_parcial_ctrl_orden,
                 f.p_parcial, "<-- significativa" if f.significativa_5pct else ""))

    print("\n  3) REGRESION piso_ruido ~ temperatura + orden + altura   (R2aj = %.3f)" % R["r2_ajustado"])
    for _, f in R["ols"].iterrows():
        print("     %-16s beta = %+8.4f   ee = %6.4f   t = %+6.2f   p = %.4f %s"
              % (f.variable, f.coeficiente, f.error_estandar, f.t, f.p_valor,
                 "*" if f.significativo_5pct else ""))
    print("     Modelo univariado de referencia: R2 = %.3f" % R["r2_simple"])

    fis = R["fisica"]
    print("\n  4) CONTRASTE CON LA COTA FISICA")
    print("     Calentamiento observado        : %.1f C (%.1f -> %.1f)"
          % (fis["delta_T_C"], fis["T_min_C"], fis["T_max_C"]))
    print("     Cota teorica por ruido termico : %.3f dB  (10*log10(T2/T1))" % fis["cota_teorica_db"])
    print("     Efecto observado en el modelo  : %.3f dB  (%.3f dB/C)"
          % (fis["efecto_observado_db"], fis["pendiente_observada_db_por_C"]))

    g = R["grupos"]
    print("\n  5) GRUPOS FRIO (<= %.1f C) vs CALIENTE" % g["mediana_T"])
    print("     piso frio = %.2f dBm | piso caliente = %.2f dBm | diferencia = %+.2f dB (p = %.3f)"
          % (g["piso_frio_dbm"], g["piso_caliente_dbm"], g["diferencia_db"], g["p_valor"]))

    R["metricas"].to_csv(os.path.join(cfg.LAKE_ORO, "metricas_temperatura.csv"),
                         index=False, encoding="utf-8")
    R["correlaciones"].to_csv(os.path.join(cfg.LAKE_ORO, "correlaciones_temperatura.csv"),
                              index=False, encoding="utf-8")
    R["ols"].to_csv(os.path.join(cfg.LAKE_ORO, "regresion_temperatura.csv"),
                    index=False, encoding="utf-8")
    print("\n[TEMPERATURA] Analisis guardado en la capa oro.\n")
    return R


if __name__ == "__main__":
    main()

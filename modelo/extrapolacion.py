# -*- coding: utf-8 -*-
"""
extrapolacion.py - BONIFICACION: LOCALIZACION DE LAS FUENTES DE CONTAMINACION

Estima, para cada canal A/B/C/D y para la frecuencia mas contaminada, el lugar
geografico del transmisor que mejor explica el patron de potencias observado, y
lo extrapola FUERA del recorrido de la estacion movil.

FUNDAMENTO: MODELO DE PROPAGACION LOG-DISTANCIA
-----------------------------------------------
En un entorno urbano la potencia recibida decae con el logaritmo de la
distancia al transmisor:

    P_rx(d) [dBm] = P_0 [dBm] - 10 * n * log10( d / d_0 )

donde P_0 es la potencia de referencia a la distancia d_0 y n el exponente de
perdida de trayecto (n = 2 en espacio libre, n entre 2.7 y 3.5 en zona urbana
densa como el occidente de Medellin).

Cada punto de la ruta aporta una ecuacion. El sistema se resuelve por minimos
cuadrados no lineales minimizando el residuo en decibelios:

    min  sum_i [ P_medida_i - ( P_0 - 10*n*log10(d_i/d_0) ) ]^2

Se minimiza en dB y no en mW porque el error de medida de un analizador de
espectro es aproximadamente gaussiano en el dominio logaritmico (el
desvanecimiento por sombra urbana es log-normal, con desviacion tipica de 6 a
10 dB, que es justo el orden de los residuos que se obtienen).

POR QUE ES EXTRAPOLACION Y NO INTERPOLACION
--------------------------------------------
La interpolacion (griddata de la sesion 7) solo puede estimar valores DENTRO de
la envolvente convexa de los puntos medidos: por construccion nunca situaria una
fuente fuera de la ruta. Aqui se ajusta un modelo fisico parametrico y se
resuelve para el parametro "posicion del emisor", que cae fuera del recorrido.
Es el mismo principio de la multilateracion por nivel de senal recibida (RSS).

TRES DECISIONES DE MODELADO QUE HACEN EL PROBLEMA IDENTIFICABLE
----------------------------------------------------------------
1) SE FIJA EL EXPONENTE n. Si se deja libre, n y la distancia son practicamente
   intercambiables: un transmisor lejano y potente con n bajo produce casi el
   mismo perfil que uno cercano y debil con n alto. Esa degeneracion hace que el
   optimizador empuje la solucion al borde de la region de busqueda y el
   resultado deje de tener sentido fisico. Fijando n al valor urbano tipico la
   solucion se vuelve estable: se verifico que la posicion estimada no cambia al
   ampliar la region de busqueda de 2 km a 20 km.

2) SE USAN LOS K PUNTOS MAS FUERTES. Lejos del emisor la medida la dominan otras
   fuentes y la sombra urbana, y el modelo de una sola fuente deja de aplicar.
   Cerca, el gradiente de potencia si responde a la geometria. Restringirse al
   entorno del maximo es el equivalente radioelectrico de ajustar una curva solo
   donde la senal supera el ruido.

3) SE USA LA POTENCIA DE PICO DEL CANAL, no la potencia media de Parseval. El
   pico corresponde a la portadora dominante, que es la que efectivamente
   proviene de UN emisor; la potencia media integra 5 MHz donde conviven varios.

Como contraste independiente se calcula ademas el CENTROIDE PONDERADO POR
POTENCIA, un estimador robusto que siempre cae dentro del area medida y que
sirve para validar la direccion obtenida por el ajuste.
"""

import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "etl"))
import config as cfg

K_PUNTOS = 12                   # numero de puntos mas fuertes usados en el ajuste
MARGEN_BUSQUEDA_M = 8000.0      # extension de la malla mas alla de la ruta
N_MALLA = 90                    # resolucion del barrido grueso por eje
N_BOOTSTRAP = 300               # repeticiones para la incertidumbre

ROSA = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]


def a_metros(lat, lon, lat0, lon0):
    """
    Proyeccion equirectangular local (plano tangente) centrada en (lat0, lon0).

    Para un area de pocos kilometros el error frente a una proyeccion geodesica
    rigurosa es de centimetros, despreciable frente a la incertidumbre del GPS.
    """
    lat0r = np.radians(lat0)
    x = np.radians(np.asarray(lon) - lon0) * cfg.RADIO_TIERRA_M * np.cos(lat0r)
    y = np.radians(np.asarray(lat) - lat0) * cfg.RADIO_TIERRA_M
    return x, y


def a_grados(x, y, lat0, lon0):
    """Inversa de a_metros: de coordenadas locales a latitud/longitud."""
    lat0r = np.radians(lat0)
    lon = lon0 + np.degrees(np.asarray(x) / (cfg.RADIO_TIERRA_M * np.cos(lat0r)))
    lat = lat0 + np.degrees(np.asarray(y) / cfg.RADIO_TIERRA_M)
    return lat, lon


def rumbo(acimut_deg):
    """Convierte un acimut en grados al punto cardinal de 16 rumbos."""
    return ROSA[int(round(acimut_deg / 22.5)) % 16]


def _p0_optimo(d, p_obs, n):
    """
    Con la posicion y el exponente fijos, la potencia de referencia P_0 tiene
    solucion cerrada: es la media de P_obs + 10*n*log10(d/d_0).
    """
    return float(np.mean(p_obs + 10.0 * n * np.log10(d / cfg.D0_M)))


def _sse(pos, x, y, p_obs, n):
    """Suma de cuadrados del error para una posicion candidata de la fuente."""
    d = np.maximum(np.hypot(x - pos[0], y - pos[1]), cfg.D0_M / 10.0)
    p0 = _p0_optimo(d, p_obs, n)
    r = p_obs - (p0 - 10.0 * n * np.log10(d / cfg.D0_M))
    return float(r @ r)


def centroide_ponderado(lat, lon, p_dbm):
    """
    Centro de masa de la potencia: promedio de las posiciones pesado por la
    potencia LINEAL de cada punto. Estimador robusto e independiente del modelo
    de propagacion, util para validar la direccion del ajuste.
    """
    w = 10.0 ** (np.asarray(p_dbm) / 10.0)
    return float(np.average(lat, weights=w)), float(np.average(lon, weights=w))


def localizar_fuente(lat, lon, p_dbm, etiqueta="", n=cfg.EXP_PERDIDA_N, k=K_PUNTOS):
    """
    Estima la posicion de la fuente que mejor explica las potencias observadas.

    Devuelve un diccionario con la posicion estimada, los parametros del modelo
    de propagacion, la bondad del ajuste, el acimut y la incertidumbre.
    """
    lat, lon, p_dbm = map(np.asarray, (lat, lon, p_dbm))

    # Centroide de la ruta completa: es el origen del sistema local y el punto
    # desde el que se reporta el acimut hacia la fuente.
    lat0, lon0 = float(lat.mean()), float(lon.mean())

    # Seleccion de los k puntos mas fuertes (ver decision de modelado 2)
    sel = np.argsort(p_dbm)[-min(k, len(p_dbm)):]
    lat_f, lon_f, p_f = lat[sel], lon[sel], p_dbm[sel]
    x, y = a_metros(lat_f, lon_f, lat0, lon0)

    # --- Etapa 1: barrido grueso de la malla -------------------------------
    gx = np.linspace(x.min() - MARGEN_BUSQUEDA_M, x.max() + MARGEN_BUSQUEDA_M, N_MALLA)
    gy = np.linspace(y.min() - MARGEN_BUSQUEDA_M, y.max() + MARGEN_BUSQUEDA_M, N_MALLA)
    GX, GY = np.meshgrid(gx, gy)

    mejor, mejor_sse = None, np.inf
    for xs, ys in zip(GX.ravel(), GY.ravel()):
        s = _sse((xs, ys), x, y, p_f, n)
        if s < mejor_sse:
            mejor_sse, mejor = s, (xs, ys)

    # --- Etapa 2: refinamiento local ---------------------------------------
    opt = minimize(_sse, mejor, args=(x, y, p_f, n), method="Nelder-Mead",
                   options={"maxiter": 6000, "xatol": 1e-2, "fatol": 1e-6})
    xs, ys = opt.x

    d = np.maximum(np.hypot(x - xs, y - ys), cfg.D0_M / 10.0)
    p0 = _p0_optimo(d, p_f, n)
    r = p_f - (p0 - 10.0 * n * np.log10(d / cfg.D0_M))
    rmse = float(np.sqrt((r @ r) / len(r)))
    sst = float(((p_f - p_f.mean()) ** 2).sum())
    r2 = 1.0 - float(r @ r) / sst if sst > 0 else np.nan

    # --- Etapa 3: incertidumbre por bootstrap ------------------------------
    rng = np.random.default_rng(20262)
    muestras = []
    for _ in range(N_BOOTSTRAP):
        idx = rng.integers(0, len(x), len(x))
        o = minimize(_sse, (xs, ys), args=(x[idx], y[idx], p_f[idx], n),
                     method="Nelder-Mead",
                     options={"maxiter": 800, "xatol": 1e-1, "fatol": 1e-3})
        muestras.append(o.x)
    muestras = np.array(muestras)
    radio95 = float(np.percentile(np.hypot(muestras[:, 0] - xs, muestras[:, 1] - ys), 95))

    lat_s, lon_s = a_grados(xs, ys, lat0, lon0)
    acimut = float(np.degrees(np.arctan2(xs, ys)) % 360.0)
    distancia = float(np.hypot(xs, ys))

    # Distancia de la fuente al punto mas cercano de TODA la ruta: si es grande,
    # la estimacion es una verdadera extrapolacion fuera del recorrido.
    xr, yr = a_metros(lat, lon, lat0, lon0)
    d_min_ruta = float(np.hypot(xr - xs, yr - ys).min())

    lat_c, lon_c = centroide_ponderado(lat, lon, p_dbm)

    return {
        "etiqueta": etiqueta,
        "latitud": float(lat_s),
        "longitud": float(lon_s),
        "P0_dbm_a_100m": p0,
        "exponente_n": float(n),
        "rmse_db": rmse,
        "r2": float(r2),
        "n_puntos_usados": int(len(x)),
        "acimut_deg": acimut,
        "rumbo": rumbo(acimut),
        "distancia_al_centroide_m": distancia,
        "radio_incertidumbre_95_m": radio95,
        "dist_minima_a_la_ruta_m": d_min_ruta,
        "fuera_de_la_ruta": bool(d_min_ruta > 200.0),
        "centroide_lat": lat_c,
        "centroide_lon": lon_c,
    }


def clasificar_confianza(r):
    """
    Traduce la bondad del ajuste a un nivel de confianza interpretable.

    Un RMSE alto o un R2 bajo significan que el patron espacial no responde a
    UNA sola fuente puntual: puede haber varios emisores simultaneos en el
    bloque, o la ruta no rodea lo suficiente al transmisor (mala dilucion
    geometrica de la precision).
    """
    if r["r2"] >= 0.6 and r["rmse_db"] <= 5.0:
        return "ALTA"
    if r["r2"] >= 0.25 and r["rmse_db"] <= 8.0:
        return "MEDIA"
    return "BAJA"


def interpretacion(r):
    """Frase de lectura tecnica del resultado, para el informe y el dashboard."""
    if r["confianza"] == "ALTA":
        return ("Emisor unico dominante bien resuelto: a %.1f km del centro de la ruta en direccion "
                "%s (acimut %.0f grados), con incertidumbre de %.0f m."
                % (r["distancia_al_centroide_m"] / 1000.0, r["rumbo"], r["acimut_deg"],
                   r["radio_incertidumbre_95_m"]))
    if r["confianza"] == "MEDIA":
        return ("Direccion del foco bien determinada (%s, acimut %.0f grados) pero la distancia es "
                "menos precisa: el bloque probablemente contiene mas de un emisor activo."
                % (r["rumbo"], r["acimut_deg"]))
    return ("El patron espacial no se explica por una sola fuente puntual (R2 = %.2f, RMSE = %.1f dB). "
            "Se reporta unicamente la direccion predominante (%s) como indicio, y se recomienda "
            "goniometria en sitio para confirmar." % (r["r2"], r["rmse_db"], r["rumbo"]))


def main():
    cfg.crear_directorios()
    ind = pd.read_parquet(os.path.join(cfg.LAKE_ORO, "indicadores_por_punto.parquet"))
    perfil = pd.read_parquet(os.path.join(cfg.LAKE_ORO, "perfil_espectral.parquet"))

    print("[EXTRAPOLACION] Localizando fuentes por multilateracion RSS")
    print("  Modelo: P(d) = P0 - 10*%.1f*log10(d/%.0f m) | %d puntos mas fuertes por canal\n"
          % (cfg.EXP_PERDIDA_N, cfg.D0_M, K_PUNTOS))

    resultados = []
    for canal in cfg.CANALES:
        r = localizar_fuente(ind["latitud"].to_numpy(), ind["longitud"].to_numpy(),
                             ind["Ppico_%s_dbm" % canal].to_numpy(), "Canal %s" % canal)
        r["canal"] = canal
        r["banda"] = "%.0f - %.0f MHz" % (cfg.CANALES[canal][0] / 1e6, cfg.CANALES[canal][1] / 1e6)
        r["confianza"] = clasificar_confianza(r)
        r["interpretacion"] = interpretacion(r)
        resultados.append(r)

    # --- Fuente de la frecuencia mas contaminada ---------------------------
    pn = (perfil.P_media_dbm - perfil.P_media_dbm.min()) / \
         (perfil.P_media_dbm.max() - perfil.P_media_dbm.min())
    peor = perfil.assign(puntaje=0.7 * pn + 0.3 * perfil.ocupacion_pct / 100.0) \
                 .sort_values("puntaje", ascending=False).iloc[0]

    df = pd.read_parquet(os.path.join(cfg.LAKE_PLATA, "medidas_limpias.parquet"))
    rf = localizar_fuente(df["latitud"].to_numpy(), df["longitud"].to_numpy(),
                          df["bin_%04d" % int(peor["bin"])].to_numpy(),
                          "Frecuencia %.4f MHz" % peor["frecuencia_mhz"])
    rf["canal"] = "F_MAX"
    rf["banda"] = "%.4f MHz" % peor["frecuencia_mhz"]
    rf["confianza"] = clasificar_confianza(rf)
    rf["interpretacion"] = interpretacion(rf)
    resultados.append(rf)

    for r in resultados:
        print("  %-10s (%s)" % (r["etiqueta"], r["banda"]))
        print("    Fuente estimada : %.6f , %.6f   [%s a %.2f km, acimut %.0f grados]"
              % (r["latitud"], r["longitud"], r["rumbo"],
                 r["distancia_al_centroide_m"] / 1000.0, r["acimut_deg"]))
        print("    Modelo ajustado : P0 = %.1f dBm a %.0f m, n = %.2f (fijo)"
              % (r["P0_dbm_a_100m"], cfg.D0_M, r["exponente_n"]))
        print("    Bondad          : RMSE = %.2f dB, R2 = %.3f -> confianza %s"
              % (r["rmse_db"], r["r2"], r["confianza"]))
        print("    Incertidumbre   : +/- %.0f m (95%%) | %.0f m del punto mas cercano de la ruta"
              % (r["radio_incertidumbre_95_m"], r["dist_minima_a_la_ruta_m"]))
        print("    Lectura tecnica : %s\n" % r["interpretacion"])

    F = pd.DataFrame(resultados)
    F.to_csv(os.path.join(cfg.LAKE_ORO, "fuentes_estimadas.csv"), index=False, encoding="utf-8")
    print("[EXTRAPOLACION] Fuentes guardadas en la capa oro.\n")
    return F


if __name__ == "__main__":
    main()

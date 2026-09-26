# -*- coding: utf-8 -*-
"""
extrapolacion.py - BONIFICACION: LOCALIZACION DE LAS FUENTES DE CONTAMINACION

Estima el lugar geografico de los emisores responsables de la contaminacion de
cada canal, y los situa en el mapa por extrapolacion a partir del gradiente de
potencia medido.

PRIMER RESULTADO: NO EXISTE UNA UNICA FUENTE POR BANDA
-------------------------------------------------------
El enunciado pide "la fuente" de cada banda, en singular. El dato dice otra
cosa, y conviene demostrarlo antes de localizar nada.

Se ajusto un modelo de fuente unica sobre los 60 puntos de la ruta y explica
practicamente nada de la varianza observada (R2 entre 0.07 y 0.12 segun el
canal, con residuos de 8 a 18 dB). El diagnostico decisivo es que el punto de
maxima potencia medida NO resulta ser el mas cercano a la fuente asi estimada:
en algunos canales queda en la posicion 27 de 60, y la correlacion entre la
potencia observada y el logaritmo de la distancia a esa fuente llega a ser
NEGATIVA. Es decir, el modelo de fuente unica predice lo contrario de lo que
se midio.

La razon es fisica: una banda celular no la emite un transmisor, la emite una
RED de estaciones base. En una malla urbana densa cada punto de la ruta esta
cerca de alguna estacion, de modo que el campo no decae desde un centro sino
que presenta multiples maximos locales. El detector de focos de este modulo
encuentra entre 9 y 12 por canal, que es justo lo que cabe esperar de una red
celular real.

ENFOQUE CORRECTO: LOCALIZACION POR GRADIENTE LOCAL
---------------------------------------------------
Si el campo global no responde a una fuente unica, pero el ENTORNO de cada
maximo si, entonces la localizacion debe hacerse foco por foco. Se comprobo
que alrededor del punto mas potente de cada canal la correlacion entre la
potencia y el logaritmo de la distancia sube a valores de 0.69 a 0.80 en un
radio de un kilometro: ahi el modelo de propagacion si aplica.

El procedimiento es entonces:

  1. Detectar los maximos locales del campo medido (los focos de contaminacion).
  2. Tomar el foco dominante de cada canal y los puntos de la ruta que caen
     dentro de su radio de influencia.
  3. Ajustar sobre ellos el modelo log-distancia

         P_rx(d) [dBm] = P_0 - 10 * n * log10( d / d_0 )

     por minimos cuadrados no lineales, resolviendo para la posicion del
     emisor. Se minimiza el residuo en decibelios porque el desvanecimiento por
     sombra urbana es log-normal, es decir gaussiano en el dominio logaritmico.
  4. Validar el resultado y declarar la confianza a partir de la bondad del
     ajuste y de la estabilidad de la solucion.

POR QUE ES EXTRAPOLACION Y NO INTERPOLACION
--------------------------------------------
La interpolacion de malla (griddata, sesion 7) solo estima valores DENTRO de la
envolvente convexa de los puntos medidos: por construccion nunca situaria un
emisor fuera de la ruta. Aqui se ajusta un modelo fisico parametrico y se
resuelve para el parametro posicion, que cae fuera del recorrido. Es el mismo
principio de la localizacion por nivel de senal recibida (RSS).

SE FIJA EL EXPONENTE DE PROPAGACION
------------------------------------
n se fija al valor urbano tipico. Dejandolo libre, n y la distancia resultan
practicamente intercambiables -un transmisor lejano y potente con n bajo produce
casi el mismo perfil que uno cercano y debil con n alto- y el optimizador
empuja la solucion contra el borde de la region de busqueda.
"""

import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "etl"))
import config as cfg

RADIO_FOCO_M = 1500.0       # radio de influencia usado para el ajuste local
RADIO_VECINDAD_M = 900.0    # radio para declarar un punto maximo local
MARGEN_BUSQUEDA_M = 3000.0  # extension de la malla alrededor del foco
N_MALLA = 121               # resolucion del barrido grueso por eje
N_BOOTSTRAP = 300           # repeticiones para la incertidumbre

ROSA = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]


# ---------------------------------------------------------------------------
# GEOMETRIA
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# PASO 1: DETECCION DE FOCOS
# ---------------------------------------------------------------------------
def detectar_focos(x, y, p_dbm, radio=RADIO_VECINDAD_M, umbral=None):
    """
    Encuentra los maximos locales del campo de potencia medido.

    Un punto es foco si supera el umbral de ocupacion y ninguno de sus vecinos
    dentro de 'radio' tiene mas potencia. Cada foco corresponde, en la practica,
    al entorno de una estacion base.

    Devuelve los indices de los focos, ordenados de mayor a menor potencia.
    """
    umbral = cfg.UMBRAL_OCUPACION_DBM if umbral is None else umbral
    focos = []
    for i in range(len(p_dbm)):
        if p_dbm[i] <= umbral:
            continue
        d = np.hypot(x - x[i], y - y[i])
        vecinos = (d > 0) & (d <= radio)
        if vecinos.sum() >= 2 and p_dbm[i] >= p_dbm[vecinos].max():
            focos.append(i)
    return sorted(focos, key=lambda i: -p_dbm[i])


# ---------------------------------------------------------------------------
# PASO 2: AJUSTE DEL MODELO DE PROPAGACION
# ---------------------------------------------------------------------------
def modelo_potencia(x, y, xs, ys, p0, n, ruido_dbm):
    """
    Potencia predicha en (x, y) por un emisor situado en (xs, ys).

        P(d) = 10*log10( 10^((P0 - 10*n*log10(d/d0))/10) + 10^(ruido/10) )

    La suma del PISO DE RUIDO dentro del logaritmo es lo que distingue este
    modelo del log-distancia puro, y es fisicamente necesaria: un receptor real
    nunca mide menos que su propio ruido, de modo que lejos del emisor la
    potencia observada se aplana en el piso en lugar de seguir cayendo hacia
    menos infinito. Sin ese termino, los puntos lejanos -que estan todos en el
    piso y no aportan informacion de distancia- tiran del ajuste como si
    todavia siguieran la ley de propagacion, y sesgan la posicion estimada.

    La suma se hace en potencia LINEAL, que es donde las contribuciones de
    senal y ruido son aditivas.
    """
    d = np.maximum(np.hypot(x - xs, y - ys), 10.0)
    senal_mw = 10.0 ** ((p0 - 10.0 * n * np.log10(d / cfg.D0_M)) / 10.0)
    ruido_mw = 10.0 ** (ruido_dbm / 10.0)
    return 10.0 * np.log10(senal_mw + ruido_mw)


def _p0_inicial(d, p_obs, n):
    """
    Semilla para P_0: la solucion cerrada del modelo SIN piso de ruido.

    Al anadir el termino de ruido, P_0 deja de tener solucion analitica y pasa
    a ajustarse junto con la posicion, pero este valor sigue siendo un buen
    punto de partida para el optimizador.
    """
    return float(np.mean(p_obs + 10.0 * n * np.log10(d / cfg.D0_M)))


def _sse(params, x, y, p_obs, n, ruido_dbm):
    """Suma de cuadrados del error para (xs, ys, P0) candidatos."""
    xs, ys, p0 = params
    r = p_obs - modelo_potencia(x, y, xs, ys, p0, n, ruido_dbm)
    return float(r @ r)


def _sse_pos(pos, x, y, p_obs, n, ruido_dbm):
    """
    Error para una posicion candidata, optimizando P_0 por dentro.

    Se usa en el barrido grueso: recorrer la malla resolviendo P_0 en cada
    celda es mucho mas rapido que optimizar las tres variables a la vez, y
    localiza bien la cuenca del minimo antes del refinamiento.
    """
    d = np.maximum(np.hypot(x - pos[0], y - pos[1]), 10.0)
    p0 = _p0_inicial(d, p_obs, n)
    mejor = np.inf
    for ajuste in (-6.0, -3.0, 0.0, 3.0, 6.0):
        s = _sse((pos[0], pos[1], p0 + ajuste), x, y, p_obs, n, ruido_dbm)
        mejor = min(mejor, s)
    return mejor


def gradiente_local(x, y, p_dbm, i_foco, radio):
    """
    Mide si alrededor del foco la potencia decae realmente con la distancia.

    Es la prueba previa que decide si tiene sentido ajustar el modelo: devuelve
    la correlacion entre la potencia observada y -log10(distancia al foco). Un
    valor alto significa que el entorno se comporta como el campo de un emisor
    cercano; un valor bajo, que ahi conviven varios y el modelo no aplica.
    """
    d = np.hypot(x - x[i_foco], y - y[i_foco])
    sel = d <= radio
    if sel.sum() < 4:
        return np.nan, sel
    return float(np.corrcoef(p_dbm[sel], -np.log10(np.maximum(d[sel], 20.0)))[0, 1]), sel


def localizar_emisor(lat, lon, p_dbm, etiqueta="", n=cfg.EXP_PERDIDA_N,
                     radio=RADIO_FOCO_M):
    """
    Localiza el emisor dominante de un canal a partir del gradiente local.

    Devuelve un diccionario con el foco de partida, la posicion extrapolada del
    emisor, la bondad del ajuste y la incertidumbre por bootstrap.
    """
    lat, lon, p_dbm = map(np.asarray, (lat, lon, p_dbm))
    lat0, lon0 = float(lat.mean()), float(lon.mean())
    x, y = a_metros(lat, lon, lat0, lon0)

    # --- focos del canal ---------------------------------------------------
    focos = detectar_focos(x, y, p_dbm)
    i = focos[0] if focos else int(np.argmax(p_dbm))

    # --- validez del gradiente antes de ajustar ----------------------------
    r_grad, sel = gradiente_local(x, y, p_dbm, i, radio)
    if sel.sum() < 4:
        sel = np.argsort(np.hypot(x - x[i], y - y[i]))[:6]
        sel = np.isin(np.arange(len(x)), sel)
        r_grad, _ = gradiente_local(x, y, p_dbm, i, radio * 2)

    xs_, ys_, p_ = x[sel], y[sel], p_dbm[sel]

    # Piso de ruido del canal, estimado sobre TODA la ruta: es el nivel por
    # debajo del cual el receptor ya no distingue senal, y define donde el
    # modelo deja de decaer.
    ruido_dbm = float(np.percentile(p_dbm, 5))

    # --- barrido grueso alrededor del foco ---------------------------------
    g = np.linspace(-MARGEN_BUSQUEDA_M, MARGEN_BUSQUEDA_M, N_MALLA)
    mejor, mejor_sse = None, np.inf
    for dx in g:
        for dy in g:
            s = _sse_pos((x[i] + dx, y[i] + dy), xs_, ys_, p_, n, ruido_dbm)
            if s < mejor_sse:
                mejor_sse, mejor = s, (x[i] + dx, y[i] + dy)

    # --- refinamiento conjunto de posicion y potencia de referencia --------
    d0 = np.maximum(np.hypot(xs_ - mejor[0], ys_ - mejor[1]), 10.0)
    semilla = (mejor[0], mejor[1], _p0_inicial(d0, p_, n))
    opt = minimize(_sse, semilla, args=(xs_, ys_, p_, n, ruido_dbm),
                   method="Nelder-Mead",
                   options={"maxiter": 8000, "xatol": 1e-2, "fatol": 1e-5})
    px, py, p0 = opt.x

    res = p_ - modelo_potencia(xs_, ys_, px, py, p0, n, ruido_dbm)
    rmse = float(np.sqrt((res @ res) / len(res)))
    sst = float(((p_ - p_.mean()) ** 2).sum())
    r2 = 1.0 - float(res @ res) / sst if sst > 0 else np.nan

    # --- incertidumbre por bootstrap ---------------------------------------
    rng = np.random.default_rng(20262)
    muestras = []
    for _ in range(N_BOOTSTRAP):
        idx = rng.integers(0, len(xs_), len(xs_))
        o = minimize(_sse, (px, py, p0),
                     args=(xs_[idx], ys_[idx], p_[idx], n, ruido_dbm),
                     method="Nelder-Mead",
                     options={"maxiter": 900, "xatol": 1e-1, "fatol": 1e-3})
        muestras.append(o.x[:2])
    muestras = np.array(muestras)
    radio95 = float(np.percentile(np.hypot(muestras[:, 0] - px, muestras[:, 1] - py), 95))

    lat_e, lon_e = a_grados(px, py, lat0, lon0)
    acimut = float(np.degrees(np.arctan2(px - x[i], py - y[i])) % 360.0)

    return {
        "etiqueta": etiqueta,
        "n_focos": len(focos),
        "foco": "",                                   # lo rellena main()
        "foco_lat": float(lat[i]), "foco_lon": float(lon[i]),
        "foco_dbm": float(p_dbm[i]),
        "latitud": float(lat_e), "longitud": float(lon_e),
        "P0_dbm_a_100m": p0,
        "exponente_n": float(n),
        "n_puntos_usados": int(sel.sum()),
        "corr_gradiente": float(r_grad),
        "rmse_db": rmse, "r2": float(r2),
        "acimut_deg": acimut, "rumbo": rumbo(acimut),
        "dist_al_foco_m": float(np.hypot(px - x[i], py - y[i])),
        "radio_incertidumbre_95_m": radio95,
        "dist_minima_a_la_ruta_m": float(np.hypot(x - px, y - py).min()),
    }


def identificabilidad_global(lat, lon, p_dbm, n=cfg.EXP_PERDIDA_N):
    """
    Contraste que demuestra que una sola fuente NO explica el campo.

    Ajusta el modelo de fuente unica usando TODOS los puntos de la ruta y
    devuelve su R2. Un valor bajo es la evidencia de que la contaminacion
    proviene de una red distribuida y no de un emisor aislado.
    """
    lat, lon, p_dbm = map(np.asarray, (lat, lon, p_dbm))
    lat0, lon0 = float(lat.mean()), float(lon.mean())
    x, y = a_metros(lat, lon, lat0, lon0)

    ruido_dbm = float(np.percentile(p_dbm, 5))

    g = np.linspace(-8000, 8000, 80)
    mejor, mejor_sse = None, np.inf
    for dx in g:
        for dy in g:
            s = _sse_pos((dx, dy), x, y, p_dbm, n, ruido_dbm)
            if s < mejor_sse:
                mejor_sse, mejor = s, (dx, dy)

    d0 = np.maximum(np.hypot(x - mejor[0], y - mejor[1]), 10.0)
    opt = minimize(_sse, (mejor[0], mejor[1], _p0_inicial(d0, p_dbm, n)),
                   args=(x, y, p_dbm, n, ruido_dbm), method="Nelder-Mead",
                   options={"maxiter": 5000})
    px, py, p0 = opt.x

    res = p_dbm - modelo_potencia(x, y, px, py, p0, n, ruido_dbm)
    sst = float(((p_dbm - p_dbm.mean()) ** 2).sum())
    r2 = 1.0 - float(res @ res) / sst

    # Prueba adicional: el punto mas potente deberia ser el mas cercano
    i_max = int(np.argmax(p_dbm))
    orden = np.argsort(np.hypot(x - px, y - py))
    puesto = int(np.where(orden == i_max)[0][0]) + 1
    corr = float(np.corrcoef(p_dbm, -np.log10(np.maximum(np.hypot(x - px, y - py), 10)))[0, 1])
    return {"r2": r2, "rmse_db": float(np.sqrt((res @ res) / len(res))),
            "puesto_del_maximo": puesto, "n_puntos": len(x), "corr_p_logd": corr}


# ---------------------------------------------------------------------------
# INTERPRETACION
# ---------------------------------------------------------------------------
def clasificar_confianza(r):
    """
    Confianza del resultado, derivada de tres comprobaciones.

    1. El GRADIENTE pesa mas que el ajuste: si la potencia no decae con la
       distancia alrededor del foco, el resultado no significa nada por bueno
       que sea su residuo.
    2. El AJUSTE (R2 y residuo) mide cuanto del patron queda explicado.
    3. La INCERTIDUMBRE actua como veto. Si el radio del 95 % supera el propio
       radio de ajuste, la estimacion no esta localizando nada: el intervalo es
       mas grande que la zona sobre la que se calculo, de modo que la posicion
       concreta carece de valor practico aunque el ajuste parezca aceptable.
       Ese caso se degrada a confianza BAJA.
    """
    if r["radio_incertidumbre_95_m"] > RADIO_FOCO_M:
        return "BAJA"
    if r["corr_gradiente"] >= 0.65 and r["r2"] >= 0.60 and r["rmse_db"] <= 7.0:
        return "ALTA"
    if r["corr_gradiente"] >= 0.45 and r["r2"] >= 0.35 and r["rmse_db"] <= 12.0:
        return "MEDIA"
    return "BAJA"


def interpretacion(r):
    """Frase de lectura tecnica del resultado, para el informe y el dashboard."""
    if r["confianza"] == "ALTA":
        return ("Emisor dominante bien resuelto. El campo alrededor del foco decae con la "
                "distancia como predice el modelo (correlacion %.2f), y el ajuste situa el "
                "transmisor a %.0f m del punto de medicion mas potente, en direccion %s. "
                "Incertidumbre de %.0f m."
                % (r["corr_gradiente"], r["dist_al_foco_m"], r["rumbo"],
                   r["radio_incertidumbre_95_m"]))
    if r["confianza"] == "MEDIA":
        return ("Foco bien identificado pero emisor resuelto solo de forma aproximada "
                "(correlacion del gradiente %.2f, R2 %.2f). La zona es correcta; la posicion "
                "exacta dentro de ella requiere una medicion complementaria."
                % (r["corr_gradiente"], r["r2"]))
    if r["radio_incertidumbre_95_m"] > RADIO_FOCO_M:
        return ("No se resuelve un emisor unico en este canal. La incertidumbre de la posicion "
                "(%.0f m) supera la propia zona sobre la que se calculo, senal de que hay mas de "
                "una emision activa alrededor del foco: se observan puntos lejanos mas fuertes que "
                "otros mas cercanos, lo que ningun transmisor aislado puede producir. Se reporta el "
                "foco medido (%s) como zona de interes, no una posicion de transmisor."
                % (r["radio_incertidumbre_95_m"], r["foco"] or "el maximo medido"))
    return ("No se resuelve un emisor unico en este canal: alrededor del foco conviven varias "
            "emisiones y la potencia no decae de forma limpia con la distancia (correlacion "
            "%.2f, residuo %.1f dB). Se reporta el foco medido como zona de interes, no una "
            "posicion de transmisor." % (r["corr_gradiente"], r["rmse_db"]))


# ---------------------------------------------------------------------------
def main():
    cfg.crear_directorios()
    ind = pd.read_parquet(os.path.join(cfg.LAKE_ORO, "indicadores_por_punto.parquet"))
    perfil = pd.read_parquet(os.path.join(cfg.LAKE_ORO, "perfil_espectral.parquet"))
    lat = ind["latitud"].to_numpy()
    lon = ind["longitud"].to_numpy()

    print("[EXTRAPOLACION] Localizacion de fuentes de contaminacion")
    print("  Modelo: P(d) = 10*log10( 10^((P0 - 10*%.1f*log10(d/%.0f m))/10) + 10^(ruido/10) )"
          % (cfg.EXP_PERDIDA_N, cfg.D0_M))
    print("  El termino de ruido impide que los puntos lejanos, que estan todos en el")
    print("  piso del receptor, tiren del ajuste como si aun siguieran la ley de propagacion.")
    print("  Ajuste sobre los puntos a menos de %.0f m del foco dominante\n" % RADIO_FOCO_M)

    # --- Contraste previo: una sola fuente NO explica el campo -------------
    print("  " + "-" * 72)
    print("  CONTRASTE: ajuste de FUENTE UNICA sobre los %d puntos de la ruta" % len(ind))
    print("  " + "-" * 72)
    globales = []
    for canal in cfg.CANALES:
        g = identificabilidad_global(lat, lon, ind["Ppico_%s_dbm" % canal].to_numpy())
        g["canal"] = canal
        globales.append(g)
        print("    Canal %s: R2 = %+.3f | residuo %.1f dB | el punto mas potente queda "
              "en el puesto %d de %d por cercania"
              % (canal, g["r2"], g["rmse_db"], g["puesto_del_maximo"], g["n_puntos"]))
    print("\n    => Una sola fuente no explica el campo medido. La contaminacion")
    print("       proviene de una RED de emisores, no de un transmisor aislado.\n")

    # --- Localizacion por gradiente local ----------------------------------
    resultados = []
    for canal in cfg.CANALES:
        v = ind["Ppico_%s_dbm" % canal].to_numpy()
        r = localizar_emisor(lat, lon, v, "Canal %s" % canal)
        x, y = a_metros(lat, lon, lat.mean(), lon.mean())
        focos = detectar_focos(x, y, v)
        r["foco"] = ind["archivo"].iloc[focos[0] if focos else int(np.argmax(v))]
        r["canal"] = canal
        r["banda"] = "%.0f - %.0f MHz" % (cfg.CANALES[canal][0] / 1e6,
                                          cfg.CANALES[canal][1] / 1e6)
        r["r2_fuente_unica"] = [g["r2"] for g in globales if g["canal"] == canal][0]
        r["confianza"] = clasificar_confianza(r)
        r["interpretacion"] = interpretacion(r)
        resultados.append(r)

    # --- Frecuencia mas contaminada ----------------------------------------
    pn = (perfil.P_media_dbm - perfil.P_media_dbm.min()) / \
         (perfil.P_media_dbm.max() - perfil.P_media_dbm.min())
    peor = perfil.assign(puntaje=0.7 * pn + 0.3 * perfil.ocupacion_pct / 100.0) \
                 .sort_values("puntaje", ascending=False).iloc[0]
    df = pd.read_parquet(os.path.join(cfg.LAKE_PLATA, "medidas_limpias.parquet"))
    v = df["bin_%04d" % int(peor["bin"])].to_numpy()
    rf = localizar_emisor(df["latitud"].to_numpy(), df["longitud"].to_numpy(), v,
                          "Frecuencia %.4f MHz" % peor["frecuencia_mhz"])
    x, y = a_metros(df["latitud"].to_numpy(), df["longitud"].to_numpy(),
                    df["latitud"].mean(), df["longitud"].mean())
    focos = detectar_focos(x, y, v)
    rf["foco"] = df["archivo"].iloc[focos[0] if focos else int(np.argmax(v))]
    rf["canal"] = "F_MAX"
    rf["banda"] = "%.4f MHz" % peor["frecuencia_mhz"]
    rf["r2_fuente_unica"] = np.nan
    rf["confianza"] = clasificar_confianza(rf)
    rf["interpretacion"] = interpretacion(rf)
    resultados.append(rf)

    # --- Reporte -----------------------------------------------------------
    for r in resultados:
        print("  %s (%s)" % (r["etiqueta"], r["banda"]))
        print("    Focos detectados : %d maximos locales en la ruta" % r["n_focos"])
        print("    Foco dominante   : %s en %.6f, %.6f  (%.1f dBm)"
              % (r["foco"], r["foco_lat"], r["foco_lon"], r["foco_dbm"]))
        print("    Gradiente local  : corr(P, -log d) = %+.2f sobre %d puntos"
              % (r["corr_gradiente"], r["n_puntos_usados"]))
        print("    Emisor estimado  : %.6f, %.6f  -> %s a %.0f m del foco"
              % (r["latitud"], r["longitud"], r["rumbo"], r["dist_al_foco_m"]))
        print("    Bondad           : R2 = %+.3f, RMSE = %.2f dB -> confianza %s"
              % (r["r2"], r["rmse_db"], r["confianza"]))
        print("    Incertidumbre    : +/- %.0f m (95%%) | %.0f m del punto mas cercano de la ruta"
              % (r["radio_incertidumbre_95_m"], r["dist_minima_a_la_ruta_m"]))
        print("    Lectura tecnica  : %s\n" % r["interpretacion"])

    F = pd.DataFrame(resultados)
    F.to_csv(os.path.join(cfg.LAKE_ORO, "fuentes_estimadas.csv"), index=False, encoding="utf-8")
    pd.DataFrame(globales).to_csv(os.path.join(cfg.LAKE_ORO, "contraste_fuente_unica.csv"),
                                  index=False, encoding="utf-8")
    print("[EXTRAPOLACION] Resultados guardados en la capa oro.\n")
    return F


if __name__ == "__main__":
    main()

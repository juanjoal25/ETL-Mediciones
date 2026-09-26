# -*- coding: utf-8 -*-
"""
decision.py - MODELO DE TOMA DE DECISIONES PARA LA ANE

Implementa el esquema de la sesion 9 del curso:

    MODELO  ->  ESTIMACIONES  ->  HIPOTESIS  ->  DECISIONES

igual que en el ejemplo del AQI: una magnitud fisica continua se mapea a un
indice normalizado por tramos lineales, cada tramo define una categoria, y
cada categoria dispara una accion concreta que la autoridad puede ejecutar.

  ESTIMACION : potencia media de ocupacion por canal, via sumatoria de Parseval
  INDICE     : ISE - Indice de Saturacion Espectral, escala 0-100
  HIPOTESIS  : reglas booleanas sobre el ISE y sobre el umbral de -60 dBm
  DECISION   : recomendacion de uso del canal para el plan de frecuencias

ANALOGIA CON EL AQI (sesion 9)
------------------------------
El AQI interpola linealmente entre puntos de corte de concentracion:

    AQI = (I_hi - I_lo)/(C_hi - C_lo) * (C - C_lo) + I_lo

Aqui se usa exactamente la misma forma funcional, cambiando la concentracion
de PM2.5 por la potencia media del canal en dBm. La diferencia conceptual es
que el AQI mide dano a la salud y el ISE mide dano al recurso espectral: en
ambos casos se trata de un bien comun que se degrada por contaminacion.
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "etl"))
import config as cfg


def _categoria(ise):
    """Categoria y color asociados a un valor del indice 0-100."""
    for _, _, i_lo, i_hi, categoria, color in cfg.TRAMOS_ISE:
        if i_lo <= ise <= i_hi:
            return categoria, color
    return cfg.TRAMOS_ISE[-1][4], cfg.TRAMOS_ISE[-1][5]


def subindice_nivel(p_dbm):
    """
    Componente de INTENSIDAD del ISE: mapea una potencia en dBm a 0-100 por
    interpolacion lineal entre puntos de corte, con la misma forma funcional
    del AQI de la sesion 9:

        I = (I_hi - I_lo)/(C_hi - C_lo) * (C - C_lo) + I_lo
    """
    p = float(np.clip(p_dbm, cfg.TRAMOS_ISE[0][0], cfg.TRAMOS_ISE[-1][1]))
    for c_lo, c_hi, i_lo, i_hi, _, _ in cfg.TRAMOS_ISE:
        if c_lo <= p <= c_hi:
            return float((i_hi - i_lo) / (c_hi - c_lo) * (p - c_lo) + i_lo)
    return 100.0


def calcular_ise(p_mediana_dbm, pct_puntos_ocupados):
    """
    Indice de Saturacion Espectral de un canal, en escala 0-100.

        ISE = w_nivel * I(P_mediana) + w_extension * (% del area ocupada)

    Se usa la MEDIANA espacial de la potencia Parseval y no la media lineal,
    porque la media en mW la domina un punado de puntos muy calientes y
    reportaria como saturado un canal que en realidad esta limpio en casi toda
    la ciudad. La mediana describe el nivel que encuentra un usuario tipico; la
    componente de extension recupera la informacion de cuanto territorio esta
    efectivamente afectado.

    Devuelve (ise, categoria, color, subindice_nivel, subindice_extension).
    """
    i_nivel = subindice_nivel(p_mediana_dbm)
    i_ext = float(np.clip(pct_puntos_ocupados, 0.0, 100.0))
    ise = cfg.PESO_ISE_NIVEL * i_nivel + cfg.PESO_ISE_EXTENSION * i_ext
    categoria, color = _categoria(ise)
    return float(round(ise, 1)), categoria, color, round(i_nivel, 1), round(i_ext, 1)


# ---------------------------------------------------------------------------
# HIPOTESIS DE DECISION
# ---------------------------------------------------------------------------
# Cada hipotesis es una regla booleana evaluada sobre los indicadores del canal.
# El orden importa: se aplica la primera que resulte verdadera, de la condicion
# mas restrictiva a la menos restrictiva.
#
# Los puntos de corte del porcentaje de area ocupada siguen la clasificacion de
# ocupacion de la Recomendacion UIT-R SM.1880: por encima del 50 % el canal se
# considera congestionado, entre 30 y 50 % de uso intensivo, entre 15 y 30 % de
# uso ligero y por debajo del 15 % practicamente libre.
HIPOTESIS = [
    {
        "id": "H1",
        "nombre": "Canal congestionado",
        "regla": lambda r: r["pct_puntos_ocupados"] >= cfg.OCUPACION_CONGESTIONADO,
        "decision": "NO ASIGNAR",
        "accion": ("Excluir el canal del plan de frecuencias para el occidente de Medellin. "
                   "Ordenar inspeccion tecnica en sitio y procedimiento de deteccion de emisiones "
                   "no autorizadas; verificar las licencias vigentes de los operadores que emiten "
                   "en el bloque antes de considerar cualquier reasignacion."),
        "prioridad": "ALTA",
    },
    {
        "id": "H2",
        "nombre": "Nivel de fondo por encima del umbral en todo el area",
        "regla": lambda r: r["P_mediana_dbm"] > cfg.UMBRAL_OCUPACION_DBM,
        "decision": "NO ASIGNAR",
        "accion": ("Reservar el canal. El nivel tipico del area ya supera el umbral de -60 dBm, "
                   "de modo que un nuevo concesionario operaria con relacion senal a interferencia "
                   "degradada en toda la zona. Requiere campana de monitoreo complementaria."),
        "prioridad": "ALTA",
    },
    {
        "id": "H3",
        "nombre": "Contaminacion localizada de uso intensivo",
        "regla": lambda r: r["pct_puntos_ocupados"] >= cfg.OCUPACION_ALTA,
        "decision": "ASIGNAR CON RESTRICCION",
        "accion": ("Asignable con coordinacion geografica. La contaminacion se concentra en zonas "
                   "puntuales: definir zonas de exclusion alrededor de los focos identificados por "
                   "el modelo de extrapolacion y exigir control de potencia al concesionario."),
        "prioridad": "MEDIA",
    },
    {
        "id": "H4",
        "nombre": "Uso ligero del canal",
        "regla": lambda r: r["pct_puntos_ocupados"] >= cfg.OCUPACION_MODERADA,
        "decision": "ASIGNAR",
        "accion": ("Canal apto para asignacion. Es la mejor opcion disponible en la banda. Incluir "
                   "clausula de monitoreo periodico semestral para verificar que el nivel de fondo "
                   "no se degrade con la entrada de nuevos operadores."),
        "prioridad": "BAJA",
    },
    {
        "id": "H5",
        "nombre": "Canal libre",
        "regla": lambda r: True,
        "decision": "ASIGNAR PRIORITARIO",
        "accion": ("Canal libre, recomendado como primera opcion del plan de frecuencias para la "
                   "ciudad de Medellin."),
        "prioridad": "BAJA",
    },
]


def evaluar_canal(fila):
    """Aplica la cascada de hipotesis a un canal y devuelve su decision."""
    ise, categoria, color, i_nivel, i_ext = calcular_ise(
        fila["P_mediana_dbm"], fila["pct_puntos_ocupados"])

    for h in HIPOTESIS:
        if h["regla"](fila):
            return {
                "canal": fila["canal"],
                "banda": "%.0f - %.0f MHz" % (fila["f_inicio_mhz"], fila["f_fin_mhz"]),
                "P_media_dbm": round(float(fila["P_media_dbm"]), 2),
                "P_mediana_dbm": round(float(fila["P_mediana_dbm"]), 2),
                "P_max_dbm": round(float(fila["P_max_dbm"]), 2),
                "pct_puntos_ocupados": round(float(fila["pct_puntos_ocupados"]), 1),
                "ocupacion_espectral_pct": round(float(fila["ocupacion_espectral_pct"]), 1),
                "supera_umbral_60dBm": bool(fila["P_mediana_dbm"] > cfg.UMBRAL_OCUPACION_DBM),
                "ISE": ise,
                "ISE_nivel": i_nivel,
                "ISE_extension": i_ext,
                "categoria": categoria,
                "color": color,
                "hipotesis": h["id"],
                "hipotesis_nombre": h["nombre"],
                "decision": h["decision"],
                "accion": h["accion"],
                "prioridad": h["prioridad"],
            }
    raise RuntimeError("Ninguna hipotesis aplico al canal %s" % fila["canal"])


def aplicar_modelo(resumen_canales):
    """Evalua los cuatro canales y devuelve la tabla de decisiones ordenada."""
    decisiones = [evaluar_canal(f) for _, f in resumen_canales.iterrows()]
    D = pd.DataFrame(decisiones).sort_values("ISE", ascending=False).reset_index(drop=True)
    D["ranking_contaminacion"] = np.arange(1, len(D) + 1)
    return D


def recomendacion_global(D, resumen=None):
    """
    Redacta el juicio de valor consolidado que se entrega a la Agencia.

    Incorpora la significancia estadistica: con solo 60 mediciones, el orden de
    preferencia entre canales puede no ser distinguible del azar de muestreo, y
    presentarlo como firme seria enganoso. Si los intervalos de Wilson de dos
    canales se solapan, la Agencia debe saber que esa diferencia no esta
    respaldada por la muestra.
    """
    peor = D.iloc[0]
    mejor = D.iloc[-1]
    asignables = D[D.decision.str.startswith("ASIGNAR")]["canal"].tolist()
    no_asignables = D[D.decision == "NO ASIGNAR"]["canal"].tolist()

    empatados = []
    if resumen is not None and "ocup_ic_bajo" in resumen.columns:
        R = resumen.sort_values("pct_puntos_ocupados", ascending=False).reset_index(drop=True)
        limpio = R.iloc[-1]
        empatados = [f.canal for _, f in R.iterrows()
                     if f.canal != limpio.canal and f.ocup_ic_bajo <= limpio.ocup_ic_alto]

    return {
        "canales_indistinguibles_del_mejor": empatados,
        "orden_estadisticamente_firme": len(empatados) == 0,
        "canal_mas_contaminado": peor["canal"],
        "banda_mas_contaminada": peor["banda"],
        "ise_max": peor["ISE"],
        "categoria_max": peor["categoria"],
        "canal_menos_contaminado": mejor["canal"],
        "banda_menos_contaminada": mejor["banda"],
        "ise_min": mejor["ISE"],
        "categoria_min": mejor["categoria"],
        "canales_recomendados": asignables,
        "canales_no_recomendados": no_asignables,
        "espectro_util_mhz": len(asignables) * cfg.ANCHO_CANAL_HZ / 1e6,
        "espectro_perdido_mhz": len(no_asignables) * cfg.ANCHO_CANAL_HZ / 1e6,
        "pct_banda_inutilizable": 100.0 * len(no_asignables) / len(D),
    }


def main():
    cfg.crear_directorios()
    res = pd.read_csv(os.path.join(cfg.LAKE_ORO, "resumen_canales.csv"))

    print("[MODELO] Evaluando hipotesis de decision sobre los 4 canales...\n")
    D = aplicar_modelo(res)

    for _, f in D.iterrows():
        print("  CANAL %s  (%s)" % (f.canal, f.banda))
        print("    Estimacion Parseval : mediana %.2f dBm | media %.2f dBm | pico %.2f dBm" %
              (f.P_mediana_dbm, f.P_media_dbm, f.P_max_dbm))
        print("    Extension           : %.1f %% de los puntos de la ruta por encima de -60 dBm"
              % f.pct_puntos_ocupados)
        print("    ISE                 : %.1f / 100  -> %s   (nivel %.1f x %.1f + extension %.1f x %.1f)"
              % (f.ISE, f.categoria, cfg.PESO_ISE_NIVEL, f.ISE_nivel,
                 cfg.PESO_ISE_EXTENSION, f.ISE_extension))
        print("    Hipotesis           : %s - %s" % (f.hipotesis, f.hipotesis_nombre))
        print("    DECISION            : %s  [prioridad %s]" % (f.decision, f.prioridad))
        print("    Accion              : %s\n" % f.accion)

    G = recomendacion_global(D, res)
    print("  RECOMENDACION GLOBAL A LA ANE")
    print("    Mas contaminado  : canal %s (%s) ISE %.1f - %s"
          % (G["canal_mas_contaminado"], G["banda_mas_contaminada"], G["ise_max"], G["categoria_max"]))
    print("    Menos contaminado: canal %s (%s) ISE %.1f - %s"
          % (G["canal_menos_contaminado"], G["banda_menos_contaminada"], G["ise_min"], G["categoria_min"]))
    print("    Recomendados     : %s" % ", ".join(G["canales_recomendados"]))
    print("    No recomendados  : %s" % (", ".join(G["canales_no_recomendados"]) or "ninguno"))
    print("    Espectro util    : %.0f MHz de %.0f MHz (%.0f %% inutilizable)"
          % (G["espectro_util_mhz"], G["espectro_util_mhz"] + G["espectro_perdido_mhz"],
             G["pct_banda_inutilizable"]))

    emp = G["canales_indistinguibles_del_mejor"]
    print("\n  SIGNIFICANCIA ESTADISTICA DEL ORDEN")
    if emp:
        print("    Los canales %s NO se distinguen del canal %s al 95 %%: sus intervalos"
              % (", ".join(emp), G["canal_menos_contaminado"]))
        print("    de Wilson se solapan. El orden de preferencia entre ellos es una")
        print("    estimacion puntual, no un resultado respaldado por la muestra.")
        print("    Lo unico que la campana sostiene con firmeza es la separacion del canal %s."
              % G["canal_mas_contaminado"])
    else:
        print("    El orden entre canales es estadisticamente firme al 95 %.")

    D.to_csv(os.path.join(cfg.LAKE_ORO, "decisiones_canales.csv"), index=False, encoding="utf-8")
    pd.DataFrame([G]).to_csv(os.path.join(cfg.LAKE_ORO, "recomendacion_global.csv"),
                             index=False, encoding="utf-8")
    print("\n[MODELO] Decisiones guardadas en la capa oro.\n")
    return D, G


if __name__ == "__main__":
    main()

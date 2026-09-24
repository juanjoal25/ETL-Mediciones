# -*- coding: utf-8 -*-
"""
figuras.py - GENERACION DE LAS GRAFICAS DEL INFORME TECNICO

Produce en PNG todas las figuras que acompanan el informe para la ANE. Se usa
matplotlib con backend no interactivo porque el script debe poder correrse
dentro del pipeline sin ventana grafica.

Las mallas de los mapas de calor se construyen con scipy.interpolate.griddata,
exactamente la tecnica de interpolacion presentada en la sesion 7 del curso.
"""

import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from scipy.interpolate import griddata

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "etl"))
import config as cfg

plt.rcParams.update({
    "figure.dpi": 130,
    "savefig.dpi": 160,
    "font.size": 9,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

COLOR_CANAL = {"A": "#2E933C", "B": "#F2C14E", "C": "#C1292E", "D": "#3E7CB1"}


def _guardar(fig, nombre):
    ruta = os.path.join(cfg.DIR_FIGURAS, nombre)
    fig.tight_layout()
    fig.savefig(ruta, bbox_inches="tight")
    plt.close(fig)
    print("    -> %s" % nombre)
    return ruta


def _bandas_canal(ax, y_texto=None):
    """Sombrea los cuatro bloques de 5 MHz sobre un eje de frecuencia en MHz."""
    for canal, (f_ini, f_fin) in cfg.CANALES.items():
        ax.axvspan(f_ini / 1e6, f_fin / 1e6, color=COLOR_CANAL[canal], alpha=0.10)
        if y_texto is not None:
            ax.text((f_ini + f_fin) / 2e6, y_texto, canal, ha="center", fontsize=11,
                    fontweight="bold", color=COLOR_CANAL[canal])


# ---------------------------------------------------------------------------
# 1. RUTA DE LA ESTACION MOVIL
# ---------------------------------------------------------------------------
def fig_ruta(ind):
    fig, ax = plt.subplots(figsize=(7.2, 6.4))
    lat, lon = ind["latitud"].to_numpy(), ind["longitud"].to_numpy()

    ax.plot(lon, lat, "-", color="#4A5568", lw=1.2, alpha=0.8, zorder=1)
    sc = ax.scatter(lon, lat, c=ind["orden"], cmap="viridis", s=52,
                    edgecolor="white", linewidth=0.7, zorder=3)

    imp = ind["gps_imputado"].to_numpy(dtype=bool)
    if imp.any():
        ax.scatter(lon[imp], lat[imp], s=230, facecolor="none",
                   edgecolor="#C1292E", linewidth=2.0, zorder=4)

    ax.scatter(lon[0], lat[0], marker="^", s=200, color="#2E933C",
               edgecolor="k", linewidth=0.8, zorder=5)
    ax.scatter(lon[-1], lat[-1], marker="s", s=160, color="#C1292E",
               edgecolor="k", linewidth=0.8, zorder=5)

    for i in range(0, len(ind), 6):
        ax.annotate("%d" % ind["orden"].iloc[i], (lon[i], lat[i]),
                    textcoords="offset points", xytext=(6, 5), fontsize=7, color="#2D3748")

    fig.colorbar(sc, ax=ax, label="Secuencia de medicion")
    ax.set_xlabel("Longitud (grados)")
    ax.set_ylabel("Latitud (grados)")
    ax.set_title("Ruta de la estacion movil de monitoreo\nSector occidental de Medellin - %d puntos validos"
                 % len(ind))
    ax.legend(handles=[
        Line2D([], [], marker="^", ls="", color="#2E933C", mec="k", ms=10, label="Inicio"),
        Line2D([], [], marker="s", ls="", color="#C1292E", mec="k", ms=9, label="Fin"),
        Line2D([], [], marker="o", ls="", mfc="none", mec="#C1292E", mew=2, ms=13,
               label="Posicion imputada"),
    ], loc="best", fontsize=8)
    ax.set_aspect(1.0 / np.cos(np.radians(lat.mean())))
    return _guardar(fig, "01_ruta.png")


# ---------------------------------------------------------------------------
# 2. CALIDAD DE LOS DATOS
# ---------------------------------------------------------------------------
def fig_calidad(reglas, indices):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 4.4))

    act = reglas[reglas.mediciones_afectadas > 0].sort_values("mediciones_afectadas")
    colores = {"descarte": "#C1292E", "imputable": "#F2C14E", "aviso": "#3E7CB1"}
    ax1.barh(act.regla, act.mediciones_afectadas,
             color=[colores[s] for s in act.severidad], edgecolor="white")
    for y, (v, d) in enumerate(zip(act.mediciones_afectadas, act.descripcion)):
        ax1.text(v + 0.4, y, "%d" % v, va="center", fontsize=8, fontweight="bold")
    ax1.set_xlabel("Mediciones afectadas")
    ax1.set_title("Reglas de validacion activadas")
    ax1.set_xlim(0, act.mediciones_afectadas.max() * 1.18)
    ax1.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c, label=s)
                        for s, c in colores.items()], fontsize=8, title="Severidad")

    g = indices[indices.dimension != "INDICE GLOBAL"]
    glob = indices[indices.dimension == "INDICE GLOBAL"].valor_pct.iloc[0]
    b = ax2.bar(g.dimension, g.valor_pct, color="#3E7CB1", edgecolor="white")
    ax2.bar_label(b, fmt="%.2f%%", fontsize=8, padding=2)
    ax2.axhline(glob, color="#C1292E", ls="--", lw=1.4,
                label="Indice global = %.2f %%" % glob)
    ax2.set_ylim(90, 101)
    ax2.set_ylabel("Cumplimiento (%)")
    ax2.set_title("Dimensiones de calidad del dataset")
    ax2.tick_params(axis="x", rotation=18)
    ax2.legend(fontsize=8)
    return _guardar(fig, "02_calidad.png")


# ---------------------------------------------------------------------------
# 3. EFECTO DEL ETL SOBRE EL ESPECTRO
# ---------------------------------------------------------------------------
def fig_etl(df_crudo, df_limpio):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10.5, 7.0))
    cols = [c for c in df_crudo.columns if c.startswith("bin_")]
    f = (cfg.F_INICIO_HZ + np.arange(cfg.N_BINS) * cfg.RBW_HZ) / 1e6

    # Panel superior: fuga de oscilador local en el bin central
    fila = df_crudo[df_crudo.archivo == "010.txt"]
    idx_l = df_limpio.index[df_limpio.archivo == "010.txt"]
    ventana = slice(cfg.BIN_DC - 40, cfg.BIN_DC + 41)
    ax1.plot(f[ventana], fila[cols].to_numpy()[0][ventana], "o-", ms=3, lw=1.2,
             color="#C1292E", label="Crudo (fuga de LO)")
    ax1.plot(f[ventana], df_limpio.loc[idx_l, cols].to_numpy()[0][ventana], "o-", ms=3, lw=1.2,
             color="#2E933C", label="Despues del ETL")
    ax1.axvline(cfg.F_CENTRAL_HZ / 1e6, color="#2D3748", ls=":", lw=1.2)
    ax1.annotate("fc = 850.000 MHz\n(frontera canales B / C)",
                 xy=(cfg.F_CENTRAL_HZ / 1e6, ax1.get_ylim()[1]), xytext=(-8, -38),
                 textcoords="offset points", fontsize=8, ha="right")
    ax1.set_xlabel("Frecuencia (MHz)")
    ax1.set_ylabel("Potencia (dBm)")
    ax1.set_title("P1 - Imputacion de la fuga de oscilador local (medicion 010)")
    ax1.legend(fontsize=8)

    # Panel inferior: traza con error de ganancia descartada
    for nombre, color, est in [("015.txt", "#3E7CB1", "-"), ("017.txt", "#2E933C", "-"),
                               ("016.txt", "#C1292E", "-")]:
        fila = df_crudo[df_crudo.archivo == nombre]
        if len(fila):
            ax2.plot(f, fila[cols].to_numpy()[0], est, lw=0.8, color=color,
                     alpha=0.95 if nombre == "016.txt" else 0.6,
                     label="%s%s" % (nombre, " (DESCARTADA)" if nombre == "016.txt" else ""))
    ax2.set_xlabel("Frecuencia (MHz)")
    ax2.set_ylabel("Potencia (dBm)")
    ax2.set_title("P0 - Deteccion de traza con error de ganancia: 016 esta desplazada +55 dB "
                  "respecto de sus vecinas inmediatas")
    ax2.legend(fontsize=8, ncol=3)
    _bandas_canal(ax2)
    return _guardar(fig, "03_etl.png")


# ---------------------------------------------------------------------------
# 4. PERFIL ESPECTRAL Y CANALES
# ---------------------------------------------------------------------------
def fig_perfil(perfil, resumen):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10.5, 7.4),
                                   gridspec_kw={"height_ratios": [2, 1]})

    ax1.plot(perfil.frecuencia_mhz, perfil.P_max_dbm, lw=0.6, color="#A0AEC0",
             label="Maximo sobre la ruta")
    ax1.plot(perfil.frecuencia_mhz, perfil.P_media_dbm, lw=1.1, color="#1A365D",
             label="Potencia media espacial (Parseval)")
    ax1.axhline(cfg.UMBRAL_OCUPACION_DBM, color="#C1292E", ls="--", lw=1.3,
                label="Umbral de ocupacion (-60 dBm)")
    _bandas_canal(ax1, y_texto=ax1.get_ylim()[1] - 4)
    ax1.set_ylabel("Potencia (dBm)")
    ax1.set_title("Perfil de ocupacion de la banda 840 - 860 MHz")
    ax1.legend(fontsize=8, loc="lower right", ncol=2)

    ax2.fill_between(perfil.frecuencia_mhz, perfil.ocupacion_pct, color="#3E7CB1", alpha=0.55)
    ax2.plot(perfil.frecuencia_mhz, perfil.ocupacion_pct, lw=0.7, color="#1A365D")
    _bandas_canal(ax2)
    ax2.set_xlabel("Frecuencia (MHz)")
    ax2.set_ylabel("% de la ruta")
    ax2.set_title("Ocupacion espectral: porcentaje de puntos que superan -60 dBm")
    ax2.set_ylim(0, 100)
    return _guardar(fig, "04_perfil_espectral.png")


# ---------------------------------------------------------------------------
# 5. FRECUENCIA MAS Y MENOS CONTAMINADA (exigida por el enunciado)
# ---------------------------------------------------------------------------
def fig_frecuencias_extremas(df, perfil, ind, fuentes):
    pn = (perfil.P_media_dbm - perfil.P_media_dbm.min()) / \
         (perfil.P_media_dbm.max() - perfil.P_media_dbm.min())
    p = perfil.assign(puntaje=0.7 * pn + 0.3 * perfil.ocupacion_pct / 100.0)
    peor = p.loc[p.puntaje.idxmax()]
    mejor = p.loc[p.puntaje.idxmin()]

    fig = plt.figure(figsize=(11.5, 7.6))
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 1], hspace=0.38, wspace=0.26)

    # (a) las dos frecuencias en el perfil global
    ax = fig.add_subplot(gs[0, :])
    ax.plot(perfil.frecuencia_mhz, perfil.P_media_dbm, lw=0.9, color="#4A5568")
    ax.axhline(cfg.UMBRAL_OCUPACION_DBM, color="#C1292E", ls="--", lw=1.1)
    ax.scatter([peor.frecuencia_mhz], [peor.P_media_dbm], s=150, color="#C1292E",
               zorder=5, edgecolor="k", linewidth=0.7)
    ax.scatter([mejor.frecuencia_mhz], [mejor.P_media_dbm], s=150, color="#2E933C",
               zorder=5, edgecolor="k", linewidth=0.7)
    caja = dict(boxstyle="round,pad=0.35", fc="white", ec="#CBD5E0", alpha=0.92)
    ax.annotate("MAS contaminada\n%.4f MHz\n%.1f dBm | %.0f %% de la ruta"
                % (peor.frecuencia_mhz, peor.P_media_dbm, peor.ocupacion_pct),
                xy=(peor.frecuencia_mhz, peor.P_media_dbm), xytext=(0.60, 0.16),
                textcoords="axes fraction", fontsize=8, color="#C1292E", fontweight="bold",
                bbox=caja, arrowprops=dict(arrowstyle="->", color="#C1292E"))
    ax.annotate("MENOS contaminada\n%.4f MHz\n%.1f dBm | %.0f %% de la ruta"
                % (mejor.frecuencia_mhz, mejor.P_media_dbm, mejor.ocupacion_pct),
                xy=(mejor.frecuencia_mhz, mejor.P_media_dbm), xytext=(0.06, 0.72),
                textcoords="axes fraction", fontsize=8, color="#2E933C", fontweight="bold",
                bbox=caja, arrowprops=dict(arrowstyle="->", color="#2E933C"))
    _bandas_canal(ax, y_texto=ax.get_ylim()[1] - 3)
    ax.margins(y=0.16)
    ax.set_xlabel("Frecuencia (MHz)")
    ax.set_ylabel("Potencia media (dBm)")
    ax.set_title("Ubicacion de las frecuencias extremas en el perfil de la banda")

    # (b) y (c) comportamiento de cada frecuencia a lo largo de la ruta
    for k, (fila, color, titulo) in enumerate([
            (peor, "#C1292E", "Frecuencia MAS contaminada"),
            (mejor, "#2E933C", "Frecuencia MENOS contaminada")]):
        ax = fig.add_subplot(gs[1, k])
        serie = df["bin_%04d" % int(fila["bin"])].to_numpy()
        ax.plot(ind["orden"], serie, "o-", ms=3.5, lw=1.0, color=color)
        ax.axhline(cfg.UMBRAL_OCUPACION_DBM, color="#2D3748", ls="--", lw=1.1,
                   label="Umbral -60 dBm")
        ax.fill_between(ind["orden"], cfg.UMBRAL_OCUPACION_DBM, serie,
                        where=serie > cfg.UMBRAL_OCUPACION_DBM, color=color, alpha=0.22)
        ax.set_xlabel("Punto de la ruta")
        ax.set_ylabel("Potencia (dBm)")
        ax.set_title("%s\n%.4f MHz (canal %s) - ocupada en %.0f %% de la ruta"
                     % (titulo, fila["frecuencia_mhz"], fila["canal"], fila["ocupacion_pct"]),
                     fontsize=9)
        ax.legend(fontsize=7.5)
    return _guardar(fig, "05_frecuencias_extremas.png"), peor, mejor


# ---------------------------------------------------------------------------
# 6. COMPARATIVA DE CANALES Y DECISION
# ---------------------------------------------------------------------------
def fig_canales(decisiones):
    D = decisiones.sort_values("ISE", ascending=False)
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(13.0, 4.3))

    x = np.arange(len(D))
    ancho = 0.38
    ax1.bar(x - ancho / 2, D.P_mediana_dbm, ancho, label="Mediana espacial",
            color="#1A365D", edgecolor="white")
    ax1.bar(x + ancho / 2, D.P_media_dbm, ancho, label="Media lineal",
            color="#7BA7CC", edgecolor="white")
    ax1.axhline(cfg.UMBRAL_OCUPACION_DBM, color="#C1292E", ls="--", lw=1.3,
                label="Umbral -60 dBm")
    ax1.set_xticks(x); ax1.set_xticklabels(D.canal)
    ax1.set_ylabel("Potencia Parseval (dBm)")
    ax1.set_title("Potencia de ocupacion por canal")
    ax1.legend(fontsize=7.5)

    b = ax2.bar(D.canal, D.pct_puntos_ocupados,
                color=[COLOR_CANAL[c] for c in D.canal], edgecolor="white")
    ax2.bar_label(b, fmt="%.1f%%", fontsize=8)
    for y, txt in [(cfg.OCUPACION_CONGESTIONADO, "Congestionado (UIT 50 %)"),
                   (cfg.OCUPACION_ALTA, "Uso intensivo (30 %)"),
                   (cfg.OCUPACION_MODERADA, "Uso ligero (15 %)")]:
        ax2.axhline(y, color="#4A5568", ls=":", lw=1.0)
        ax2.text(len(D) - 0.45, y + 1.2, txt, fontsize=6.6, ha="right", color="#4A5568")
    ax2.set_ylabel("% de la ruta por encima de -60 dBm")
    ax2.set_title("Extension territorial de la contaminacion")
    ax2.set_ylim(0, 100)

    b = ax3.bar(D.canal, D.ISE, color=[r.color for r in D.itertuples()], edgecolor="white")
    ax3.bar_label(b, labels=["%.1f\n%s" % (v, c) for v, c in zip(D.ISE, D.categoria)],
                  fontsize=7.5)
    for _, _, i_lo, i_hi, cat, col in cfg.TRAMOS_ISE:
        ax3.axhspan(i_lo, i_hi, color=col, alpha=0.08)
    ax3.set_ylabel("ISE (0 - 100)")
    ax3.set_title("Indice de Saturacion Espectral")
    ax3.set_ylim(0, 105)
    return _guardar(fig, "06_canales.png")


# ---------------------------------------------------------------------------
# 7. INCIDENCIA DE LA TEMPERATURA
# ---------------------------------------------------------------------------
def fig_temperatura(R):
    M = R["metricas"]
    fig, axs = plt.subplots(2, 2, figsize=(11.0, 7.4))

    ax = axs[0, 0]
    ax.plot(M.orden, M.temperatura, "o-", ms=4, lw=1.2, color="#C1292E")
    ax.set_xlabel("Punto de la ruta"); ax.set_ylabel("Temperatura del sensor (C)")
    ax.set_title("La temperatura crece con el tiempo de operacion\nr(T, orden) = %+.3f"
                 % R["confusion"]["r_temp_orden"], fontsize=9)

    ax = axs[0, 1]
    ax.scatter(M.temperatura, M.piso_ruido_dbm, s=42, color="#3E7CB1",
               edgecolor="white", linewidth=0.6)
    b = np.polyfit(M.temperatura, M.piso_ruido_dbm, 1)
    xs = np.linspace(M.temperatura.min(), M.temperatura.max(), 50)
    ax.plot(xs, np.polyval(b, xs), "--", color="#C1292E", lw=1.5,
            label="Ajuste simple: %.2f dB/C (R2 = %.3f)" % (b[0], R["r2_simple"]))
    ax.set_xlabel("Temperatura del sensor (C)"); ax.set_ylabel("Piso de ruido, p5 (dBm)")
    ax.set_title("Relacion aparente temperatura - piso de ruido", fontsize=9)
    ax.legend(fontsize=7.5)

    ax = axs[1, 0]
    C = R["correlaciones"]
    y = np.arange(len(C)); h = 0.38
    ax.barh(y - h / 2, C.r_pearson, h, color="#A0AEC0", label="Correlacion simple")
    ax.barh(y + h / 2, C.r_parcial_ctrl_orden, h, color="#1A365D",
            label="Parcial, controlando el orden")
    ax.axvline(0, color="#2D3748", lw=0.9)
    ax.set_yticks(y); ax.set_yticklabels(C.metrica, fontsize=7.5)
    ax.set_xlabel("Coeficiente de correlacion con la temperatura")
    ax.set_title("Al descontar el efecto del tiempo, la correlacion desaparece", fontsize=9)
    ax.legend(fontsize=7.5)

    ax = axs[1, 1]
    fis = R["fisica"]
    p_temp = float(R["ols"].loc[R["ols"].variable == "temperatura_C", "p_valor"].iloc[0])
    valores = [fis["cota_teorica_db"], abs(fis["efecto_observado_db"])]
    b = ax.bar(["Cota fisica\n10 log(T2/T1)", "Coeficiente ajustado\n(NO significativo)"],
               valores, color=["#2E933C", "#C1292E"], edgecolor="white")
    ax.bar_label(b, labels=["%.2f dB" % valores[0],
                            "%.2f dB\np = %.2f" % (valores[1], p_temp)],
                 fontsize=9, fontweight="bold")
    ax.set_ylabel("Variacion del piso de ruido (dB)")
    ax.set_title("El calentamiento de %.1f C no puede mover el piso mas de %.2f dB.\n"
                 "El coeficiente ajustado lo excede 58 veces y no es significativo:\n"
                 "es ruido de estimacion, no un efecto termico real."
                 % (fis["delta_T_C"], fis["cota_teorica_db"]), fontsize=8.5)
    ax.set_ylim(0, max(valores) * 1.45)
    return _guardar(fig, "07_temperatura.png")


# ---------------------------------------------------------------------------
# 8. MAPAS DE CALOR (interpolacion griddata, sesion 7)
# ---------------------------------------------------------------------------
def _malla(lon, lat, valores, n=260):
    """
    Interpola una nube de puntos dispersos sobre una malla regular.

    Se usa exclusivamente interpolacion lineal (sesion 7): fuera de la
    envolvente convexa de los puntos medidos griddata devuelve NaN y la zona
    queda en blanco. Rellenar ese exterior con 'nearest' produciria sectores
    radiales artificiales que un lector podria interpretar como cobertura real
    donde en realidad no se midio nada.
    """
    ml = 0.002
    gx = np.linspace(lon.min() - ml, lon.max() + ml, n)
    gy = np.linspace(lat.min() - ml, lat.max() + ml, n)
    GX, GY = np.meshgrid(gx, gy)
    return GX, GY, griddata((lon, lat), valores, (GX, GY), method="linear")


def _marcar_fuente(ax, f, lon, lat):
    """
    Situa la fuente extrapolada en el mapa.

    Si cae dentro del area medida se dibuja la estrella en su posicion; si cae
    fuera (que es lo habitual, porque se trata de una extrapolacion) se traza
    una flecha desde el centroide de la ruta hacia ella, rotulada con el rumbo
    y la distancia, sin deformar los limites del mapa.
    """
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    dentro = (x0 <= f.longitud <= x1) and (y0 <= f.latitud <= y1)

    if dentro:
        ax.scatter([f.longitud], [f.latitud], marker="*", s=340, color="#00E5FF",
                   edgecolor="black", linewidth=0.8, zorder=7)
        ax.annotate("fuente\n%s" % f.confianza, (f.longitud, f.latitud),
                    textcoords="offset points", xytext=(10, -16), fontsize=6.8,
                    color="#00E5FF", fontweight="bold", zorder=7,
                    annotation_clip=False)
        return

    cx, cy = lon.mean(), lat.mean()
    vx, vy = f.longitud - cx, f.latitud - cy
    norma = np.hypot(vx, vy)
    # Se recorta el vector para que la punta quede justo dentro del recuadro
    escala = 0.40 * min((x1 - x0) / abs(vx) if vx else np.inf,
                        (y1 - y0) / abs(vy) if vy else np.inf)
    ex, ey = cx + vx * escala, cy + vy * escala

    ax.annotate("", xy=(ex, ey), xytext=(cx, cy), zorder=7,
                arrowprops=dict(arrowstyle="-|>", color="#00E5FF", lw=2.0,
                                mutation_scale=18))
    ax.text(ex, ey, "fuente %s\n%.1f km (%s)" % (f.rumbo, f.distancia_al_centroide_m / 1000.0,
                                                 f.confianza),
            fontsize=6.8, color="#0097A7", fontweight="bold", zorder=7, clip_on=False,
            ha="left" if vx > 0 else "right", va="bottom" if vy > 0 else "top",
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.75))


def _formato_mapa(ax, lon, lat):
    """Ajustes comunes de los mapas: limites, aspecto y densidad de marcas."""
    ml = 0.002
    ax.set_xlim(lon.min() - ml, lon.max() + ml)
    ax.set_ylim(lat.min() - ml, lat.max() + ml)
    ax.set_aspect(1.0 / np.cos(np.radians(lat.mean())))
    ax.set_facecolor("#F7FAFC")
    ax.xaxis.set_major_locator(plt.MaxNLocator(4))
    ax.yaxis.set_major_locator(plt.MaxNLocator(5))
    ax.tick_params(labelsize=7.5)
    ax.grid(False)


def fig_mapas_canales(ind, fuentes):
    fig, axs = plt.subplots(2, 2, figsize=(11.0, 10.4))
    lon, lat = ind["longitud"].to_numpy(), ind["latitud"].to_numpy()

    # Escala de color comun a los cuatro paneles: sin ella cada canal se
    # normalizaria a su propio rango y los mapas dejarian de ser comparables.
    todos = np.concatenate([ind["P_%s_dbm" % c].to_numpy() for c in cfg.CANALES])
    niveles = np.linspace(np.floor(todos.min()), np.ceil(todos.max()), 24)

    for ax, canal in zip(axs.ravel(), cfg.CANALES):
        v = ind["P_%s_dbm" % canal].to_numpy()
        GX, GY, Z = _malla(lon, lat, v)
        im = ax.contourf(GX, GY, Z, levels=niveles, cmap="inferno", extend="both")
        ax.contour(GX, GY, Z, levels=[cfg.UMBRAL_OCUPACION_DBM],
                   colors="#00E5FF", linewidths=1.6)
        ax.plot(lon, lat, "-", color="white", lw=0.8, alpha=0.6)
        ax.scatter(lon, lat, s=11, c="white", edgecolor="black", linewidth=0.3, zorder=5)

        fig.colorbar(im, ax=ax, label="dBm", fraction=0.046, pad=0.02)
        ax.set_title("Canal %s  (%.0f - %.0f MHz)" %
                     (canal, cfg.CANALES[canal][0] / 1e6, cfg.CANALES[canal][1] / 1e6))
        ax.set_xlabel("Longitud"); ax.set_ylabel("Latitud")
        _formato_mapa(ax, lon, lat)

        f = fuentes[fuentes.canal == canal]
        if len(f):
            _marcar_fuente(ax, f.iloc[0], lon, lat)

    fig.suptitle("Mapas de calor de la potencia de ocupacion por canal (Parseval)\n"
                 "Linea cian: umbral de -60 dBm. Flecha: direccion de la fuente extrapolada. "
                 "El blanco es area no cubierta por la ruta.", fontsize=10)
    return _guardar(fig, "08_mapas_canales.png")


def fig_mapa_temperatura_y_fmax(ind, df, perfil, fuentes):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.6, 4.9))
    lon, lat = ind["longitud"].to_numpy(), ind["latitud"].to_numpy()
    aspecto = 1.0 / np.cos(np.radians(lat.mean()))

    GX, GY, Z = _malla(lon, lat, ind["temperatura"].to_numpy())
    im = ax1.contourf(GX, GY, Z, levels=20, cmap="coolwarm")
    ax1.plot(lon, lat, "-", color="#2D3748", lw=0.8, alpha=0.6)
    ax1.scatter(lon, lat, s=12, c="k", zorder=5)
    fig.colorbar(im, ax=ax1, label="Temperatura del sensor (C)", fraction=0.046, pad=0.02)
    ax1.set_title("Mapa de calor de la temperatura del sistema de sensado")
    ax1.set_xlabel("Longitud"); ax1.set_ylabel("Latitud")
    _formato_mapa(ax1, lon, lat)

    pn = (perfil.P_media_dbm - perfil.P_media_dbm.min()) / \
         (perfil.P_media_dbm.max() - perfil.P_media_dbm.min())
    peor = perfil.assign(puntaje=0.7 * pn + 0.3 * perfil.ocupacion_pct / 100.0) \
                 .sort_values("puntaje", ascending=False).iloc[0]
    v = df["bin_%04d" % int(peor["bin"])].to_numpy()

    GX, GY, Z = _malla(lon, lat, v)
    im = ax2.contourf(GX, GY, Z, levels=22, cmap="inferno")
    ax2.contour(GX, GY, Z, levels=[cfg.UMBRAL_OCUPACION_DBM], colors="#00E5FF", linewidths=1.6)
    ax2.plot(lon, lat, "-", color="white", lw=0.8, alpha=0.6)
    ax2.scatter(lon, lat, s=11, c="white", edgecolor="black", linewidth=0.3, zorder=5)
    fig.colorbar(im, ax=ax2, label="dBm", fraction=0.046, pad=0.02)
    ax2.set_title("Mapa de calor de la frecuencia mas contaminada\n%.4f MHz (canal %s)"
                  % (peor["frecuencia_mhz"], peor["canal"]))
    ax2.set_xlabel("Longitud"); ax2.set_ylabel("Latitud")
    _formato_mapa(ax2, lon, lat)

    f = fuentes[fuentes.canal == "F_MAX"]
    if len(f):
        _marcar_fuente(ax2, f.iloc[0], lon, lat)
    return _guardar(fig, "09_mapas_temperatura_fmax.png")


# ---------------------------------------------------------------------------
# 9. CALIBRACION DE ANTENA
# ---------------------------------------------------------------------------
def fig_antena(antena):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.0, 3.9))
    f = antena.frecuencia_hz / 1e6
    banda = (f >= 835) & (f <= 865)

    ax1.plot(f, antena.s11_db, lw=1.0, color="#4A5568")
    ax1.plot(f[banda], antena.s11_db[banda], lw=2.0, color="#C1292E",
             label="Banda de estudio 840 - 860 MHz")
    ax1.set_xlabel("Frecuencia (MHz)"); ax1.set_ylabel("S11 (dB)")
    ax1.set_title("Adaptacion de la antena de monitoreo (Agilent N9914A)")
    ax1.legend(fontsize=8)

    en = antena[(antena.frecuencia_hz >= cfg.F_INICIO_HZ) & (antena.frecuencia_hz <= cfg.F_FIN_HZ)]
    ax2.plot(en.frecuencia_hz / 1e6, en.perdida_desacople_db, lw=1.8, color="#1A365D")
    _bandas_canal(ax2)
    ax2.set_xlabel("Frecuencia (MHz)")
    ax2.set_ylabel("Perdida por desacople (dB)")
    ax2.set_title("Correccion aplicada: gradiente de %.2f dB entre A y D"
                  % (en.perdida_desacople_db.iloc[0] - en.perdida_desacople_db.iloc[-1]))
    return _guardar(fig, "10_antena.png")


# ---------------------------------------------------------------------------
def generar_todas():
    import temperatura as mod_temp
    import quality

    cfg.crear_directorios()
    print("[FIGURAS] Generando graficas del informe...")

    df_crudo = pd.read_parquet(os.path.join(cfg.LAKE_BRONCE, "medidas_crudas.parquet"))
    df = pd.read_parquet(os.path.join(cfg.LAKE_PLATA, "medidas_limpias.parquet"))
    ind = pd.read_parquet(os.path.join(cfg.LAKE_ORO, "indicadores_por_punto.parquet"))
    perfil = pd.read_parquet(os.path.join(cfg.LAKE_ORO, "perfil_espectral.parquet"))
    reglas = pd.read_csv(os.path.join(cfg.LAKE_PLATA, "reporte_reglas.csv"))
    indices = pd.read_csv(os.path.join(cfg.LAKE_PLATA, "indices_calidad.csv"))
    resumen = pd.read_csv(os.path.join(cfg.LAKE_ORO, "resumen_canales.csv"))
    decisiones = pd.read_csv(os.path.join(cfg.LAKE_ORO, "decisiones_canales.csv"))
    fuentes = pd.read_csv(os.path.join(cfg.LAKE_ORO, "fuentes_estimadas.csv"))
    antena = pd.read_parquet(os.path.join(cfg.LAKE_BRONCE, "antena_s11.parquet"))

    banderas, _ = quality.evaluar(df_crudo)
    R_temp = mod_temp.analizar(df_crudo, banderas)

    rutas = {}
    rutas["ruta"] = fig_ruta(ind)
    rutas["calidad"] = fig_calidad(reglas, indices)
    rutas["etl"] = fig_etl(df_crudo, df)
    rutas["perfil"] = fig_perfil(perfil, resumen)
    rutas["frecuencias"], peor, mejor = fig_frecuencias_extremas(df, perfil, ind, fuentes)
    rutas["canales"] = fig_canales(decisiones)
    rutas["temperatura"] = fig_temperatura(R_temp)
    rutas["mapas_canales"] = fig_mapas_canales(ind, fuentes)
    rutas["mapas_temp_fmax"] = fig_mapa_temperatura_y_fmax(ind, df, perfil, fuentes)
    rutas["antena"] = fig_antena(antena)

    print("[FIGURAS] %d graficas generadas en %s\n" % (len(rutas), cfg.DIR_FIGURAS))
    return rutas, peor, mejor, R_temp


if __name__ == "__main__":
    generar_todas()

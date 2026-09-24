# -*- coding: utf-8 -*-
"""
app.py - DASHBOARD INTERACTIVO DE OCUPACION ESPECTRAL SOBRE SERVIDOR WEB

Programa entregable del Examen 3. Levanta un servidor web (Dash sobre Flask)
que publica el resultado del proceso de ETL para la Agencia Nacional del
Espectro.

VISTAS EXIGIDAS POR EL ENUNCIADO
--------------------------------
  - Ubicacion de las mediciones                     -> pestana "Mediciones"
  - Ruta de las mediciones                          -> pestana "Mediciones"
  - Mapa de calor por canal A, B, C y D             -> pestana "Mapas de calor"
  - Mapa de calor de la temperatura del sensado     -> pestana "Mapas de calor"
  - Mapa de calor de la frecuencia mas contaminada  -> pestana "Mapas de calor"
  - Fuentes extrapoladas (bonificacion)             -> superpuestas en los mapas

ARQUITECTURA
------------
El dashboard consume EXCLUSIVAMENTE la capa oro del datalake. No recalcula
nada: la visualizacion queda desacoplada del procesamiento, de modo que si el
ETL se vuelve a ejecutar con datos nuevos el dashboard los refleja sin tocar
una linea de su codigo. Es el patron "DATA-CACHE + MODELO -> VIZ" de la
arquitectura de referencia de la asignatura.

LEGIBILIDAD DE LOS MAPAS
------------------------
La potencia no se pinta con una rampa continua sino con BANDAS DISCRETAS de
limites fijos y absolutos, con un corte perceptual duro (azul claro -> amarillo)
justo en el umbral de -60 dBm que define la ocupacion. Asi el lector distingue
de un vistazo la zona libre de la contaminada, y como los limites son los
mismos para los cuatro canales, los cuatro mapas son directamente comparables
entre si.

EJECUCION
---------
    python dashboard/app.py
    Abrir http://127.0.0.1:8050 en el navegador.
"""

import os
import sys

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output
from scipy.interpolate import griddata

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "etl"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
import estilo as es

PUERTO = 8050


# ===========================================================================
# CARGA DE DATOS (capa oro del datalake)
# ===========================================================================
def cargar_datos():
    """Lee los artefactos del datalake que alimentan todas las vistas."""
    D = {}
    D["ind"] = pd.read_parquet(os.path.join(cfg.LAKE_ORO, "indicadores_por_punto.parquet"))
    D["perfil"] = pd.read_parquet(os.path.join(cfg.LAKE_ORO, "perfil_espectral.parquet"))
    D["resumen"] = pd.read_csv(os.path.join(cfg.LAKE_ORO, "resumen_canales.csv"))
    D["decisiones"] = pd.read_csv(os.path.join(cfg.LAKE_ORO, "decisiones_canales.csv"))
    D["fuentes"] = pd.read_csv(os.path.join(cfg.LAKE_ORO, "fuentes_estimadas.csv"))
    D["limpio"] = pd.read_parquet(os.path.join(cfg.LAKE_PLATA, "medidas_limpias.parquet"))
    D["indices"] = pd.read_csv(os.path.join(cfg.LAKE_PLATA, "indices_calidad.csv"))
    D["bitacora"] = pd.read_csv(os.path.join(cfg.LAKE_PLATA, "bitacora_imputacion.csv"))
    D["reglas"] = pd.read_csv(os.path.join(cfg.LAKE_PLATA, "reporte_reglas.csv"))

    # Frecuencia mas y menos contaminada: mismo criterio que usa el informe
    p = D["perfil"]
    pn = (p.P_media_dbm - p.P_media_dbm.min()) / (p.P_media_dbm.max() - p.P_media_dbm.min())
    p = p.assign(puntaje=0.7 * pn + 0.3 * p.ocupacion_pct / 100.0)
    D["f_peor"] = p.loc[p.puntaje.idxmax()]
    D["f_mejor"] = p.loc[p.puntaje.idxmin()]
    D["serie_f_peor"] = D["limpio"]["bin_%04d" % int(D["f_peor"]["bin"])].to_numpy()
    return D


DATOS = cargar_datos()


# ===========================================================================
# ESCALAS DE COLOR POR BANDAS DISCRETAS
# ===========================================================================
# Limites ABSOLUTOS de potencia, iguales para los cuatro canales. El salto de
# color entre la cuarta y la quinta banda cae exactamente en el umbral de
# ocupacion de -60 dBm que fija el enunciado.
BANDAS_DBM = [-100, -85, -75, -65, -60, -50, -40, -30, -10]
COLORES_DBM = [
    "#2C5282",   # <= -85  sin actividad
    "#4A86C8",   # -85 a -75
    "#8FBEE3",   # -75 a -65
    "#CFE6F5",   # -65 a -60   ultimo tramo LIBRE
    "#FFD93D",   # -60 a -50   primer tramo OCUPADO
    "#F79C42",   # -50 a -40
    "#EE6C4D",   # -40 a -30
    "#C1272D",   # > -30       saturado
]
ETIQUETAS_DBM = ["Sin actividad", "Muy bajo", "Bajo", "Al limite",
                 "Ocupado", "Alto", "Muy alto", "Saturado"]

COLORES_TEMP = ["#3B6FB0", "#6FA3D6", "#A9CBE8", "#F7D774", "#F0A04B", "#D9622B"]


def escala_discreta(bandas, colores):
    """
    Construye una escala de color escalonada para Plotly a partir de una lista
    de limites y una de colores.

    Plotly interpola linealmente entre las paradas de color, de modo que para
    obtener bandas planas cada color debe declararse DOS VECES: al inicio y al
    final de su tramo. El resultado son escalones nitidos en lugar de un
    degradado continuo, que es lo que hace el mapa legible de un vistazo.
    """
    lo, hi = bandas[0], bandas[-1]
    rango = hi - lo
    escala = []
    for i, color in enumerate(colores):
        escala.append([(bandas[i] - lo) / rango, color])
        escala.append([(bandas[i + 1] - lo) / rango, color])
    return escala


def barra_color(bandas, titulo, etiquetas=None):
    """Configuracion de la leyenda de color, con marcas en los limites de banda."""
    cfg_barra = dict(
        title=dict(text=titulo, side="right", font=dict(size=11, color=es.TINTA_2)),
        tickvals=bandas, ticktext=["%g" % b for b in bandas],
        tickfont=dict(size=10, color=es.TINTA_2),
        outlinewidth=0, thickness=13, len=0.82, x=1.005,
        bgcolor="rgba(255,255,255,0.7)",
    )
    if etiquetas:
        # Se rotulan los tramos, no los limites: es mas facil de leer
        centros = [(bandas[i] + bandas[i + 1]) / 2 for i in range(len(etiquetas))]
        cfg_barra["tickvals"] = centros
        cfg_barra["ticktext"] = ["%s  (%g a %g)" % (t, bandas[i], bandas[i + 1])
                                 for i, t in enumerate(etiquetas)]
    return cfg_barra


# ===========================================================================
# UTILIDADES DE GRAFICACION
# ===========================================================================
def _plantilla(fig, alto=460, titulo=None, subtitulo=None):
    """Aplica el tema claro comun a todas las figuras."""
    encabezado = None
    if titulo:
        encabezado = dict(
            text=("<b>%s</b>" % titulo) +
                 ("<br><span style='font-size:12px;color:%s'>%s</span>" % (es.TINTA_2, subtitulo)
                  if subtitulo else ""),
            font=dict(size=15.5, color=es.TINTA), x=0, xanchor="left", y=0.97)
    fig.update_layout(
        height=alto, title=encabezado,
        paper_bgcolor=es.SUPERFICIE, plot_bgcolor=es.SUPERFICIE,
        font=dict(family=es.FUENTE, color=es.TINTA, size=12),
        margin=dict(l=52, r=28, t=70 if titulo else 22, b=46),
        legend=dict(bgcolor="rgba(255,255,255,0.85)", bordercolor=es.BORDE,
                    borderwidth=1, font=dict(size=11.5)),
        hoverlabel=dict(bgcolor="white", bordercolor=es.BORDE,
                        font=dict(family=es.FUENTE, size=12.5, color=es.TINTA)),
    )
    fig.update_xaxes(gridcolor=es.BORDE, zerolinecolor=es.BORDE, linecolor=es.BORDE,
                     tickfont=dict(size=11, color=es.TINTA_2),
                     title_font=dict(size=12, color=es.TINTA_2))
    fig.update_yaxes(gridcolor=es.BORDE, zerolinecolor=es.BORDE, linecolor=es.BORDE,
                     tickfont=dict(size=11, color=es.TINTA_2),
                     title_font=dict(size=12, color=es.TINTA_2))
    return fig


def _mapa_base(fig, lat, lon, titulo=None, subtitulo=None, zoom=12.8):
    """
    Configura el mapa sobre cartografia OpenStreetMap.

    Se usa el estilo 'open-street-map' porque no requiere token de acceso: el
    dashboard funciona sin credenciales externas.
    """
    encabezado = None
    if titulo:
        encabezado = dict(
            text=("<b>%s</b>" % titulo) +
                 ("<br><span style='font-size:12px;color:%s'>%s</span>" % (es.TINTA_2, subtitulo)
                  if subtitulo else ""),
            font=dict(size=15.5, color=es.TINTA), x=0.005, xanchor="left", y=0.975)
    fig.update_layout(
        map=dict(style="open-street-map",
                 center=dict(lat=float(np.mean(lat)), lon=float(np.mean(lon))),
                 zoom=zoom),
        title=encabezado,
        paper_bgcolor=es.SUPERFICIE,
        font=dict(family=es.FUENTE, color=es.TINTA, size=12),
        margin=dict(l=0, r=0, t=64 if titulo else 0, b=0), height=660,
        legend=dict(bgcolor="rgba(255,255,255,0.9)", bordercolor=es.BORDE, borderwidth=1,
                    x=0.012, y=0.985, xanchor="left", yanchor="top",
                    font=dict(size=11.5)),
        hoverlabel=dict(bgcolor="white", bordercolor=es.BORDE,
                        font=dict(family=es.FUENTE, size=12.5, color=es.TINTA)),
    )
    return fig


def _malla_interpolada(lon, lat, valores, n=150):
    """
    Interpola los valores dispersos sobre una malla regular (sesion 7).

    Solo interpolacion lineal: fuera de la envolvente convexa de los puntos
    medidos el resultado es NaN y la zona queda transparente. Rellenarla
    generaria cobertura ficticia donde no se midio.
    """
    ml = 0.002
    gx = np.linspace(lon.min() - ml, lon.max() + ml, n)
    gy = np.linspace(lat.min() - ml, lat.max() + ml, n)
    GX, GY = np.meshgrid(gx, gy)
    Z = griddata((lon, lat), valores, (GX, GY), method="linear")
    return gx, gy, Z


def _nota_mapa(fig, lineas):
    """Cuadro flotante con las cifras clave de la capa que se esta viendo."""
    fig.add_annotation(
        x=0.012, y=0.022, xref="paper", yref="paper",
        xanchor="left", yanchor="bottom", showarrow=False, align="left",
        text="<br>".join(lineas),
        font=dict(size=11.5, color=es.TINTA),
        bgcolor="rgba(255,255,255,0.93)", bordercolor=es.BORDE,
        borderwidth=1, borderpad=11)
    return fig


# ===========================================================================
# VISTA 1: UBICACION Y RUTA DE LAS MEDICIONES
# ===========================================================================
def fig_ubicacion(colorear_por="orden"):
    ind = DATOS["ind"]
    ajustes = {
        "orden": ("Secuencia", "Viridis", ind["orden"], ""),
        "temperatura": ("Temp. (C)", "RdYlBu_r", ind["temperatura"], " C"),
        "altura": ("Altura (m)", "Cividis", ind["altura"], " m"),
        "error_distancia": ("Error GPS", "Reds", ind["error_distancia"], ""),
    }
    titulo_barra, escala, valores, unidad = ajustes[colorear_por]

    fig = go.Figure()
    fig.add_trace(go.Scattermap(
        lat=ind.latitud, lon=ind.longitud, mode="lines",
        line=dict(width=3.2, color="rgba(29,29,31,0.35)"),
        name="Ruta recorrida", hoverinfo="skip"))

    fig.add_trace(go.Scattermap(
        lat=ind.latitud, lon=ind.longitud, mode="markers",
        marker=dict(size=14, color=valores, colorscale=escala,
                    colorbar=dict(title=dict(text=titulo_barra, side="right",
                                             font=dict(size=11, color=es.TINTA_2)),
                                  tickfont=dict(size=10, color=es.TINTA_2),
                                  outlinewidth=0, thickness=13, len=0.8, x=1.005,
                                  bgcolor="rgba(255,255,255,0.7)")),
        name="Mediciones",
        customdata=np.column_stack([
            ind.archivo, ind.orden, ind.temperatura, ind.altura,
            ind.error_distancia, ind.P_A_dbm, ind.P_B_dbm, ind.P_C_dbm, ind.P_D_dbm,
            ind.canal_dominante, np.where(ind.gps_imputado, "si", "no")]),
        hovertemplate=(
            "<b>%{customdata[0]}</b>  ·  punto %{customdata[1]}<br>"
            "<span style='color:#6E6E73'>%{lat:.5f}, %{lon:.5f}</span><br><br>"
            "Temperatura  %{customdata[2]:.1f} C<br>"
            "Altura  %{customdata[3]:.0f} m   ·   HDOP  %{customdata[4]:.1f}<br><br>"
            "<b>Potencia Parseval</b><br>"
            "A %{customdata[5]:.1f}   B %{customdata[6]:.1f}<br>"
            "C %{customdata[7]:.1f}   D %{customdata[8]:.1f}  dBm<br>"
            "Canal dominante  %{customdata[9]}<br>"
            "GPS imputado  %{customdata[10]}<extra></extra>")))

    for lat, lon, txt, color in [
            (ind.latitud.iloc[0], ind.longitud.iloc[0], "Inicio", es.VERDE),
            (ind.latitud.iloc[-1], ind.longitud.iloc[-1], "Fin", es.ROJO)]:
        fig.add_trace(go.Scattermap(
            lat=[lat], lon=[lon], mode="markers+text",
            marker=dict(size=19, color=color), text=[txt], textposition="top center",
            textfont=dict(color=color, size=13, family=es.FUENTE),
            name=txt, hoverinfo="skip"))

    imp = ind[ind.gps_imputado]
    if len(imp):
        fig.add_trace(go.Scattermap(
            lat=imp.latitud, lon=imp.longitud, mode="markers",
            marker=dict(size=27, color="rgba(245,166,35,0.40)"),
            name="Posicion imputada", text=imp.archivo,
            hovertemplate="<b>%{text}</b><br>Posicion reconstruida por interpolacion<extra></extra>"))

    lat_v, lon_v = ind.latitud.to_numpy(), ind.longitud.to_numpy()
    dx = np.diff(lon_v) * 111320.0 * np.cos(np.radians(lat_v[:-1].mean()))
    dy = np.diff(lat_v) * 110540.0
    recorrido = float(np.hypot(dx, dy).sum()) / 1000.0

    _mapa_base(fig, ind.latitud, ind.longitud,
               "Ubicacion y ruta de las mediciones",
               "%d puntos validos  ·  recorrido de %.1f km  ·  el color indica %s"
               % (len(ind), recorrido, titulo_barra.lower()))
    return _nota_mapa(fig, [
        "<b>%d</b> mediciones georreferenciadas" % len(ind),
        "<b>%.1f km</b> de recorrido  ·  <b>%.0f m</b> entre muestras"
        % (recorrido, recorrido * 1000 / max(len(ind) - 1, 1)),
        "<b>%d</b> posiciones reconstruidas por imputacion" % int(ind.gps_imputado.sum()),
    ])


# ===========================================================================
# VISTA 2: MAPAS DE CALOR
# ===========================================================================
def _config_capa(capa):
    """Devuelve (valores, bandas, colores, etiquetas, unidad, titulo, subtitulo, fuente)."""
    ind = DATOS["ind"]

    if capa in cfg.CANALES:
        v = ind["P_%s_dbm" % capa].to_numpy()
        dec = DATOS["decisiones"].set_index("canal").loc[capa]
        sub = ("Potencia media de ocupacion (Parseval)  ·  mediana %.1f dBm  ·  "
               "ocupado en el %.1f %% del area  ·  %s"
               % (dec.P_mediana_dbm, dec.pct_puntos_ocupados, dec.decision))
        return (v, BANDAS_DBM, COLORES_DBM, ETIQUETAS_DBM, "dBm",
                "Canal %s  ·  %.0f a %.0f MHz" % (capa, cfg.CANALES[capa][0] / 1e6,
                                                  cfg.CANALES[capa][1] / 1e6),
                sub, DATOS["fuentes"][DATOS["fuentes"].canal == capa])

    if capa == "TEMP":
        v = ind["temperatura"].to_numpy()
        bandas = list(np.round(np.linspace(np.floor(v.min()), np.ceil(v.max()),
                                           len(COLORES_TEMP) + 1), 1))
        return (v, bandas, COLORES_TEMP, None, "C",
                "Temperatura del sistema de sensado",
                "Deriva termica del receptor a lo largo de la campana  ·  "
                "de %.1f a %.1f C  ·  sin incidencia demostrable en la calidad"
                % (v.min(), v.max()), None)

    v = DATOS["serie_f_peor"]
    fp = DATOS["f_peor"]
    return (v, BANDAS_DBM, COLORES_DBM, ETIQUETAS_DBM, "dBm",
            "Frecuencia mas contaminada  ·  %.4f MHz" % fp.frecuencia_mhz,
            "Portadora dominante del sistema, en el canal %s  ·  supera -60 dBm en el "
            "%.0f %% de la ruta" % (fp.canal, fp.ocupacion_pct),
            DATOS["fuentes"][DATOS["fuentes"].canal == "F_MAX"])


def fig_mapa_calor(capa):
    """
    Mapa de calor de la capa seleccionada sobre la cartografia de Medellin.

    capa: 'A', 'B', 'C', 'D' (potencia Parseval del canal), 'TEMP'
    (temperatura del sensor) o 'FMAX' (frecuencia mas contaminada).
    """
    ind = DATOS["ind"]
    lon, lat = ind.longitud.to_numpy(), ind.latitud.to_numpy()
    valores, bandas, colores, etiquetas, unidad, titulo, subtitulo, fuente = _config_capa(capa)

    escala = escala_discreta(bandas, colores)
    cmin, cmax = bandas[0], bandas[-1]

    # La superficie se dibuja proyectando la MALLA INTERPOLADA sobre la
    # cartografia. No se usa un mapa de densidad de kernel porque este
    # interpreta el valor como un PESO, y una potencia en dBm es negativa:
    # como peso carece de sentido fisico. Aqui cada celda de la malla se
    # colorea con el valor que la interpolacion lineal predice en ese punto,
    # que es exactamente la tecnica de la sesion 7 del curso.
    gx, gy, Z = _malla_interpolada(lon, lat, valores)
    GX, GY = np.meshgrid(gx, gy)
    valido = np.isfinite(Z)

    fig = go.Figure()
    fig.add_trace(go.Scattermap(
        lat=GY[valido], lon=GX[valido], mode="markers",
        marker=dict(size=7, color=Z[valido], colorscale=escala,
                    cmin=cmin, cmax=cmax, opacity=0.60,
                    colorbar=barra_color(bandas, unidad, etiquetas)),
        hoverinfo="skip", name="Superficie interpolada", showlegend=False))

    fig.add_trace(go.Scattermap(
        lat=lat, lon=lon, mode="lines",
        line=dict(width=2, color="rgba(29,29,31,0.30)"),
        name="Ruta", hoverinfo="skip"))

    # Los puntos medidos se colorean con la MISMA escala que la superficie:
    # asi se ve de inmediato cuales estan por encima del umbral y la
    # interpolacion no puede sugerir algo distinto de lo que se midio.
    fig.add_trace(go.Scattermap(
        lat=lat, lon=lon, mode="markers",
        marker=dict(size=13, color=valores, colorscale=escala,
                    cmin=cmin, cmax=cmax, showscale=False),
        name="Puntos medidos",
        customdata=np.column_stack([ind.archivo, valores]),
        hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]:.2f} " + unidad +
                      "<extra></extra>"))

    if fuente is not None and len(fuente):
        f = fuente.iloc[0]
        fig.add_trace(go.Scattermap(
            lat=[f.latitud], lon=[f.longitud], mode="markers+text",
            marker=dict(size=21, color=es.ACENTO),
            text=["Fuente estimada"], textposition="top right",
            textfont=dict(color=es.ACENTO, size=12.5, family=es.FUENTE),
            name="Fuente extrapolada",
            hovertemplate=("<b>Fuente extrapolada</b><br>"
                           "%.6f, %.6f<br>%s a %.2f km del centro de la ruta<br>"
                           "R2 %.3f  ·  RMSE %.2f dB  ·  confianza %s<extra></extra>")
                          % (f.latitud, f.longitud, f.rumbo,
                             f.distancia_al_centroide_m / 1000.0, f.r2, f.rmse_db,
                             f.confianza)))

    _mapa_base(fig, lat, lon, titulo, subtitulo)

    if capa == "TEMP":
        notas = ["Media <b>%.1f C</b>  ·  rango <b>%.1f a %.1f C</b>"
                 % (valores.mean(), valores.min(), valores.max()),
                 "La deriva sigue el tiempo de operacion, no la posicion"]
    else:
        n_ocu = int((valores > cfg.UMBRAL_OCUPACION_DBM).sum())
        notas = ["Umbral de ocupacion  <b>%.0f dBm</b>" % cfg.UMBRAL_OCUPACION_DBM,
                 "Supera el umbral en <b>%d de %d</b> puntos  (<b>%.1f %%</b>)"
                 % (n_ocu, len(valores), 100.0 * n_ocu / len(valores)),
                 "Mediana <b>%.1f dBm</b>  ·  pico <b>%.1f dBm</b>"
                 % (np.median(valores), valores.max())]
    return _nota_mapa(fig, notas)


def fig_contorno(capa):
    """Curvas de nivel de la malla interpolada, complemento cuantitativo del mapa."""
    ind = DATOS["ind"]
    lon, lat = ind.longitud.to_numpy(), ind.latitud.to_numpy()
    valores, bandas, colores, etiquetas, unidad, titulo, _, _ = _config_capa(capa)

    gx, gy, Z = _malla_interpolada(lon, lat, valores, n=170)
    paso = (bandas[-1] - bandas[0]) / 18.0

    fig = go.Figure(go.Contour(
        x=gx, y=gy, z=Z,
        colorscale=escala_discreta(bandas, colores),
        zmin=bandas[0], zmax=bandas[-1],
        contours=dict(start=bandas[0], end=bandas[-1], size=paso,
                      showlabels=True,
                      labelfont=dict(size=9.5, color="rgba(29,29,31,0.75)")),
        line=dict(width=0.4, color="rgba(255,255,255,0.55)"),
        colorbar=barra_color(bandas, unidad, etiquetas),
        connectgaps=False, hoverinfo="skip"))

    if capa != "TEMP":
        # Curva unica del umbral: separa visualmente lo libre de lo ocupado
        fig.add_trace(go.Contour(
            x=gx, y=gy, z=Z, showscale=False,
            contours=dict(start=cfg.UMBRAL_OCUPACION_DBM, end=cfg.UMBRAL_OCUPACION_DBM,
                          size=1, coloring="none", showlabels=False),
            line=dict(width=2.4, color=es.TINTA), name="Umbral -60 dBm",
            hoverinfo="skip"))

    fig.add_trace(go.Scatter(
        x=lon, y=lat, mode="lines+markers",
        line=dict(color="rgba(29,29,31,0.35)", width=1.2),
        marker=dict(size=5, color="white", line=dict(color=es.TINTA, width=1)),
        name="Ruta medida",
        hovertemplate="%{x:.5f}, %{y:.5f}<extra></extra>"))

    _plantilla(fig, alto=520, titulo="Curvas de nivel  ·  %s" % titulo,
               subtitulo="Interpolacion lineal sobre la malla (griddata). "
                         "La linea negra marca el umbral de -60 dBm."
                         if capa != "TEMP" else "Interpolacion lineal sobre la malla (griddata).")
    fig.update_xaxes(title="Longitud")
    fig.update_yaxes(title="Latitud", scaleanchor="x",
                     scaleratio=1.0 / np.cos(np.radians(lat.mean())))
    return fig


# ===========================================================================
# VISTA 3: ESPECTRO
# ===========================================================================
def fig_espectro(mostrar_maximo=True):
    p = DATOS["perfil"]
    fig = go.Figure()

    for canal, (f_ini, f_fin) in cfg.CANALES.items():
        fig.add_vrect(x0=f_ini / 1e6, x1=f_fin / 1e6,
                      fillcolor=es.COLOR_CANAL[canal], opacity=0.055, line_width=0,
                      annotation_text="Canal %s" % canal, annotation_position="top left",
                      annotation_font=dict(color=es.COLOR_CANAL[canal], size=12.5))

    if mostrar_maximo:
        fig.add_trace(go.Scatter(
            x=p.frecuencia_mhz, y=p.P_max_dbm, mode="lines",
            line=dict(color="rgba(110,110,115,0.35)", width=1),
            name="Maximo sobre la ruta", hoverinfo="skip"))

    fig.add_trace(go.Scatter(
        x=p.frecuencia_mhz, y=p.P_media_dbm, mode="lines",
        line=dict(color=es.ACENTO, width=1.7),
        name="Potencia media (Parseval)",
        hovertemplate="<b>%{x:.4f} MHz</b><br>%{y:.2f} dBm<extra></extra>"))

    fig.add_hline(y=cfg.UMBRAL_OCUPACION_DBM,
                  line=dict(color=es.ROJO, dash="dash", width=1.6),
                  annotation_text="Umbral de ocupacion  -60 dBm",
                  annotation_position="bottom right",
                  annotation_font=dict(color=es.ROJO, size=11.5))

    for fila, color, texto in [(DATOS["f_peor"], es.ROJO, "Mas contaminada"),
                               (DATOS["f_mejor"], es.VERDE, "Menos contaminada")]:
        fig.add_trace(go.Scatter(
            x=[fila.frecuencia_mhz], y=[fila.P_media_dbm], mode="markers",
            marker=dict(size=13, color=color, line=dict(color="white", width=2)),
            name="%s  ·  %.4f MHz" % (texto, fila.frecuencia_mhz),
            hovertemplate="<b>%s</b><br>%.4f MHz<br>%.2f dBm<br>ocupada en %.1f %% de la ruta<extra></extra>"
                          % (texto, fila.frecuencia_mhz, fila.P_media_dbm, fila.ocupacion_pct)))

    _plantilla(fig, alto=500, titulo="Perfil de ocupacion de la banda",
               subtitulo="840 a 860 MHz  ·  resolucion de %.2f kHz por punto" % (cfg.RBW_HZ / 1e3))
    fig.update_xaxes(title="Frecuencia (MHz)")
    fig.update_yaxes(title="Potencia (dBm)")
    return fig


def fig_ocupacion_espectral():
    p = DATOS["perfil"]
    fig = go.Figure(go.Scatter(
        x=p.frecuencia_mhz, y=p.ocupacion_pct, mode="lines", fill="tozeroy",
        line=dict(color=es.ACENTO, width=1),
        fillcolor="rgba(0,113,227,0.16)",
        hovertemplate="<b>%{x:.4f} MHz</b><br>%{y:.1f} %% de la ruta<extra></extra>",
        name="Ocupacion"))
    for canal, (f_ini, f_fin) in cfg.CANALES.items():
        fig.add_vrect(x0=f_ini / 1e6, x1=f_fin / 1e6,
                      fillcolor=es.COLOR_CANAL[canal], opacity=0.055, line_width=0)
    _plantilla(fig, alto=330, titulo="Persistencia de la ocupacion",
               subtitulo="Porcentaje de los puntos de la ruta en que cada frecuencia supera -60 dBm")
    fig.update_xaxes(title="Frecuencia (MHz)")
    fig.update_yaxes(title="% de la ruta", range=[0, 100])
    return fig


# ===========================================================================
# VISTA 4: MODELO DE DECISION
# ===========================================================================
def fig_ise():
    D = DATOS["decisiones"].sort_values("ISE", ascending=False)
    fig = go.Figure(go.Bar(
        x=D.canal, y=D.ISE,
        marker=dict(color=[es.COLOR_CANAL[c] for c in D.canal],
                    line=dict(width=0)),
        width=0.52,
        text=["<b>%.1f</b><br><span style='font-size:11px'>%s</span>" % (v, c)
              for v, c in zip(D.ISE, D.categoria)],
        textposition="outside", textfont=dict(size=14, color=es.TINTA),
        hovertemplate="<b>Canal %{x}</b><br>ISE %{y:.1f} de 100<extra></extra>"))
    for _, _, i_lo, i_hi, cat, _ in cfg.TRAMOS_ISE:
        fig.add_hline(y=i_hi, line=dict(color=es.BORDE, width=1, dash="dot"),
                      annotation_text=cat, annotation_position="right",
                      annotation_font=dict(size=10.5, color=es.TINTA_3))
    _plantilla(fig, alto=430, titulo="Indice de Saturacion Espectral",
               subtitulo="60 %% intensidad (mediana espacial) + 40 %% extension territorial")
    fig.update_yaxes(title="ISE (0 a 100)", range=[0, 118])
    fig.update_xaxes(title="")
    return fig


def fig_comparativa_canales():
    D = DATOS["decisiones"].sort_values("ISE", ascending=False)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=D.canal, y=D.P_mediana_dbm, name="Mediana espacial",
                         marker_color=es.ACENTO, width=0.3,
                         hovertemplate="Canal %{x}<br>%{y:.2f} dBm<extra></extra>"))
    fig.add_trace(go.Bar(x=D.canal, y=D.P_media_dbm, name="Media lineal",
                         marker_color="#9FC7F0", width=0.3,
                         hovertemplate="Canal %{x}<br>%{y:.2f} dBm<extra></extra>"))
    fig.add_hline(y=cfg.UMBRAL_OCUPACION_DBM,
                  line=dict(color=es.ROJO, dash="dash", width=1.6),
                  annotation_text="-60 dBm", annotation_position="right",
                  annotation_font=dict(color=es.ROJO, size=11.5))
    _plantilla(fig, alto=430, titulo="Potencia de ocupacion",
               subtitulo="Sumatoria de Parseval  ·  la brecha entre media y mediana revela "
                         "si la contaminacion es localizada")
    fig.update_yaxes(title="dBm")
    fig.update_xaxes(title="")
    fig.update_layout(barmode="group", bargap=0.45)
    return fig


def fig_extension():
    D = DATOS["decisiones"].sort_values("ISE", ascending=False)
    fig = go.Figure(go.Bar(
        x=D.canal, y=D.pct_puntos_ocupados, width=0.52,
        marker=dict(color=[es.COLOR_CANAL[c] for c in D.canal], line=dict(width=0)),
        text=["<b>%.1f %%</b>" % v for v in D.pct_puntos_ocupados],
        textposition="outside", textfont=dict(size=13.5, color=es.TINTA),
        hovertemplate="Canal %{x}<br>%{y:.1f} %% del area<extra></extra>"))
    for y, txt, color in [(cfg.OCUPACION_CONGESTIONADO, "Congestionado", es.ROJO),
                          (cfg.OCUPACION_ALTA, "Uso intensivo", es.AMBAR),
                          (cfg.OCUPACION_MODERADA, "Uso ligero", es.VERDE)]:
        fig.add_hline(y=y, line=dict(color=color, dash="dot", width=1.3),
                      annotation_text="%s  %.0f %%" % (txt, y),
                      annotation_position="top left",
                      annotation_font=dict(size=10.5, color=color))
    _plantilla(fig, alto=430, titulo="Extension territorial",
               subtitulo="Puntos de la ruta por encima de -60 dBm  ·  umbrales UIT-R SM.1880")
    fig.update_yaxes(title="% de la ruta", range=[0, 112])
    fig.update_xaxes(title="")
    return fig


# ===========================================================================
# COMPONENTES DE INTERFAZ
# ===========================================================================
def tarjeta_metrica(etiqueta, valor, detalle, color=None):
    return html.Div([
        html.Div(etiqueta, style=es.ETIQUETA),
        html.Div(valor, style={"fontSize": "30px", "fontWeight": "600",
                               "letterSpacing": "-0.03em",
                               "color": color or es.TINTA, "margin": "9px 0 5px 0",
                               "fontVariantNumeric": "tabular-nums"}),
        html.Div(detalle, style={"fontSize": "12.5px", "color": es.TINTA_2,
                                 "lineHeight": "1.45"}),
    ], style={**es.TARJETA, "flex": "1 1 190px", "minWidth": "190px"})


def fila_metricas():
    D = DATOS["decisiones"]
    peor, mejor = D.iloc[0], D.iloc[-1]
    ind = DATOS["ind"]
    calidad = DATOS["indices"].iloc[-1].valor_pct
    perdido = len(D[D.decision == "NO ASIGNAR"]) * 5

    return html.Div([
        tarjeta_metrica("Mas contaminado", "Canal %s" % peor.canal,
                        "%s · ISE %.1f · %s" % (peor.banda, peor.ISE, peor.categoria), es.ROJO),
        tarjeta_metrica("Mas limpio", "Canal %s" % mejor.canal,
                        "%s · ISE %.1f · %s" % (mejor.banda, mejor.ISE, mejor.categoria), es.VERDE),
        tarjeta_metrica("Frecuencia critica", "%.3f" % DATOS["f_peor"].frecuencia_mhz,
                        "MHz · %.1f dBm · ocupada en %.0f %% de la ruta"
                        % (DATOS["f_peor"].P_media_dbm, DATOS["f_peor"].ocupacion_pct), es.NARANJA),
        tarjeta_metrica("Mediciones validas", "%d" % len(ind),
                        "de 63 · calidad %.2f %% · %d imputadas"
                        % (calidad, int(ind.gps_imputado.sum()))),
        tarjeta_metrica("Espectro comprometido", "%d MHz" % perdido,
                        "de %.0f MHz estudiados" % (cfg.ANCHO_BANDA_HZ / 1e6), es.ROJO),
    ], style={"display": "flex", "gap": "16px", "flexWrap": "wrap", "marginBottom": "26px"})


def segmentado(id_control, opciones, valor):
    """Radio buttons presentados como un control segmentado."""
    return html.Div(
        dcc.RadioItems(id=id_control, options=opciones, value=valor,
                       className="segmentado", inline=True,
                       labelStyle={}, inputStyle={}),
        style={"marginBottom": "20px"})


def encabezado_panel(titulo, subtitulo=None):
    hijos = [html.H2(titulo, style=es.TITULO_SECCION)]
    if subtitulo:
        hijos.append(html.P(subtitulo, style=es.SUBTITULO_SECCION))
    return html.Div(hijos)


def insignia(texto, color):
    return html.Span(texto, className="insignia", style={
        "color": color, "background": color + "1A"})


def tabla(encabezados, filas, alineacion_num=None):
    """Tabla con el estilo limpio definido en la hoja de estilo global."""
    alineacion_num = alineacion_num or set()
    cab = html.Thead(html.Tr([
        html.Th(h, style={"textAlign": "right"} if i in alineacion_num else {})
        for i, h in enumerate(encabezados)]))
    cuerpo = html.Tbody([
        html.Tr([html.Td(c, className="num" if i in alineacion_num else "",
                         style={"textAlign": "right"} if i in alineacion_num else {})
                 for i, c in enumerate(fila)]) for fila in filas])
    return html.Table([cab, cuerpo], className="limpia")


def tabla_decisiones():
    D = DATOS["decisiones"]
    filas = []
    for _, f in D.iterrows():
        filas.append([
            html.Span("Canal %s" % f.canal,
                      style={"fontWeight": "600", "color": es.COLOR_CANAL[f.canal]}),
            f.banda,
            "%.2f dBm" % f.P_mediana_dbm,
            "%.2f dBm" % f.P_media_dbm,
            "%.1f %%" % f.pct_puntos_ocupados,
            html.Span("%.1f" % f.ISE, style={"fontWeight": "600"}),
            insignia(f.categoria, f.color),
            f.hipotesis,
            insignia(f.decision, es.COLOR_DECISION.get(f.decision, es.TINTA_2)),
        ])
    return tabla(["Canal", "Banda", "P mediana", "P media", "% area ocupada",
                  "ISE", "Categoria", "Hipotesis", "Decision"],
                 filas, alineacion_num={2, 3, 4, 5})


def panel_acciones():
    bloques = []
    for _, f in DATOS["decisiones"].iterrows():
        color = es.COLOR_DECISION.get(f.decision, es.TINTA_2)
        bloques.append(html.Div([
            html.Div([
                html.Span("Canal %s" % f.canal, style={
                    "fontWeight": "600", "fontSize": "17px", "letterSpacing": "-0.02em",
                    "color": es.COLOR_CANAL[f.canal]}),
                html.Span(f.banda, style={"color": es.TINTA_3, "fontSize": "13px",
                                          "marginLeft": "10px"}),
                html.Span(insignia(f.decision, color), style={"float": "right"}),
            ]),
            html.Div("Hipotesis %s — %s   ·   prioridad %s"
                     % (f.hipotesis, f.hipotesis_nombre, f.prioridad),
                     style={"color": es.TINTA_2, "fontSize": "12.5px",
                            "margin": "12px 0 7px 0"}),
            html.Div(f.accion, style={"color": es.TINTA, "fontSize": "13.5px",
                                      "lineHeight": "1.6"}),
        ], style={"background": es.SUPERFICIE_2, "borderRadius": es.RADIO_CHICO,
                  "padding": "20px 22px", "marginBottom": "13px",
                  "borderLeft": "3px solid %s" % color}))
    return html.Div(bloques)


def tabla_fuentes():
    colores = {"ALTA": es.VERDE, "MEDIA": es.AMBAR, "BAJA": es.ROJO}
    filas = []
    for _, f in DATOS["fuentes"].iterrows():
        nombre = "Canal %s" % f.canal if f.canal != "F_MAX" else "Frecuencia %s" % f.banda
        filas.append([
            html.Span(nombre, style={"fontWeight": "600"}),
            "%.6f" % f.latitud, "%.6f" % f.longitud, f.rumbo,
            "%.2f km" % (f.distancia_al_centroide_m / 1000.0),
            "%.2f dB" % f.rmse_db, "%.3f" % f.r2,
            insignia(f.confianza, colores[f.confianza]),
        ])
    return tabla(["Objetivo", "Latitud", "Longitud", "Rumbo", "Distancia",
                  "RMSE", "R2", "Confianza"], filas, alineacion_num={1, 2, 4, 5, 6})


def bloque_calidad():
    R = DATOS["reglas"][DATOS["reglas"].mediciones_afectadas > 0]
    B = DATOS["bitacora"]
    I = DATOS["indices"]
    colores_sev = {"descarte": es.ROJO, "imputable": es.AMBAR, "aviso": es.ACENTO}

    dimensiones = html.Div([
        html.Div([
            html.Div(f.dimension.title(), style={**es.ETIQUETA, "fontSize": "10.5px"}),
            html.Div("%.2f %%" % f.valor_pct, style={
                "fontSize": "25px", "fontWeight": "600", "letterSpacing": "-0.02em",
                "margin": "7px 0 3px 0",
                "color": es.ACENTO if f.dimension == "INDICE GLOBAL" else es.TINTA}),
            html.Div(f.definicion, style={"fontSize": "11.5px", "color": es.TINTA_2,
                                          "lineHeight": "1.4"}),
        ], style={"flex": "1 1 170px", "background": es.SUPERFICIE_2,
                  "borderRadius": es.RADIO_CHICO, "padding": "17px 19px"})
        for _, f in I.iterrows()
    ], style={"display": "flex", "gap": "13px", "flexWrap": "wrap", "marginBottom": "30px"})

    return html.Div([
        dimensiones,
        html.H3("Reglas de validacion activadas",
                style={**es.TITULO_SECCION, "fontSize": "16px", "margin": "0 0 14px 0"}),
        tabla(["Regla", "Severidad", "Mediciones", "Descripcion del defecto"],
              [[f.regla, insignia(f.severidad.upper(), colores_sev[f.severidad]),
                "%d" % f.mediciones_afectadas, f.descripcion] for _, f in R.iterrows()],
              alineacion_num={2}),
        html.H3("Bitacora de imputacion",
                style={**es.TITULO_SECCION, "fontSize": "16px", "margin": "34px 0 14px 0"}),
        tabla(["Paso", "Tecnica", "Celdas", "Unidad", "Motivo"],
              [[f.paso, f.tecnica, "%d" % f.cantidad, f.unidad, f.motivo]
               for _, f in B.iterrows()], alineacion_num={2}),
    ])


# ===========================================================================
# APLICACION
# ===========================================================================
app = Dash(__name__, title="Ocupacion espectral 840-860 MHz | ANE")
server = app.server          # objeto Flask, por si se despliega con WSGI

app.index_string = """<!DOCTYPE html>
<html>
<head>
  {%%metas%%}<title>{%%title%%}</title>{%%favicon%%}{%%css%%}
  <style>%s</style>
</head>
<body>{%%app_entry%%}<footer>{%%config%%}{%%scripts%%}{%%renderer%%}</footer></body>
</html>""" % es.css_global()

GRAFICO = {"displayModeBar": "hover", "displaylogo": False,
           "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"]}


def panel(titulo, subtitulo, contenido):
    return html.Div([encabezado_panel(titulo, subtitulo), contenido], style=es.PANEL)


app.layout = html.Div([

    # ----- cabecera --------------------------------------------------------
    html.Div(html.Div([
        html.Div("Agencia Nacional del Espectro", style={
            **es.ETIQUETA, "color": es.ACENTO, "marginBottom": "9px"}),
        html.H1("Ocupacion del espectro radioelectrico", style={
            "margin": "0", "fontSize": "36px", "fontWeight": "600",
            "letterSpacing": "-0.035em", "color": es.TINTA}),
        html.P("Banda 840 – 860 MHz  ·  campana de monitoreo movil en el "
               "sector occidental de Medellin", style={
            "margin": "10px 0 0 0", "color": es.TINTA_2, "fontSize": "16px",
            "fontWeight": "400"}),
    ], style={"maxWidth": "1500px", "margin": "0 auto", "padding": "0 34px"}),
        style={"background": es.SUPERFICIE, "padding": "44px 0 38px 0",
               "borderBottom": "1px solid %s" % es.BORDE, "marginBottom": "30px"}),

    html.Div([
        fila_metricas(),

        dcc.Tabs(id="tabs", value="t1", className="tabs-contenedor",
                 parent_className="tabs-contenedor", children=[

            # --- MEDICIONES Y RUTA -----------------------------------------
            dcc.Tab(label="Mediciones y ruta", value="t1",
                    className="tab-item", selected_className="tab-item--sel", children=[
                html.Div(style={"height": "26px"}),
                panel("Ubicacion y ruta de la estacion movil",
                      "La secuencia numerica de los archivos es la unica marca temporal "
                      "disponible: ordenando por ella se reconstruye la trayectoria. "
                      "Pasa el cursor sobre un punto para ver su detalle completo.",
                      html.Div([
                          segmentado("color-puntos", [
                              {"label": "Secuencia", "value": "orden"},
                              {"label": "Temperatura", "value": "temperatura"},
                              {"label": "Altura", "value": "altura"},
                              {"label": "Error GPS", "value": "error_distancia"}], "orden"),
                          dcc.Graph(id="g-ubicacion", config=GRAFICO),
                      ])),
            ]),

            # --- MAPAS DE CALOR --------------------------------------------
            dcc.Tab(label="Mapas de calor", value="t2",
                    className="tab-item", selected_className="tab-item--sel", children=[
                html.Div(style={"height": "26px"}),
                panel("Distribucion geografica de la contaminacion",
                      "Los limites de las bandas de color son absolutos e iguales para los "
                      "cuatro canales, con el corte azul a amarillo justo en el umbral de "
                      "-60 dBm: lo azul esta libre, lo calido esta ocupado. El area en "
                      "blanco no fue cubierta por la ruta.",
                      html.Div([
                          segmentado("capa-mapa", [
                              {"label": "Canal A", "value": "A"},
                              {"label": "Canal B", "value": "B"},
                              {"label": "Canal C", "value": "C"},
                              {"label": "Canal D", "value": "D"},
                              {"label": "Temperatura", "value": "TEMP"},
                              {"label": "Frecuencia critica", "value": "FMAX"}], "C"),
                          dcc.Graph(id="g-mapa-calor", config=GRAFICO),
                          html.Div(style={"height": "22px"}),
                          dcc.Graph(id="g-contorno", config=GRAFICO),
                      ])),
            ]),

            # --- ESPECTRO ---------------------------------------------------
            dcc.Tab(label="Espectro", value="t3",
                    className="tab-item", selected_className="tab-item--sel", children=[
                html.Div(style={"height": "26px"}),
                panel("Perfil espectral de la banda",
                      "Potencia promediada sobre los 60 puntos validos de la ruta, con los "
                      "cuatro bloques de 5 MHz sombreados.",
                      html.Div([
                          dcc.Checklist(
                              id="ver-maximo", value=["max"], className="segmentado",
                              options=[{"label": "Mostrar la envolvente de maximos",
                                        "value": "max"}]),
                          html.Div(style={"height": "20px"}),
                          dcc.Graph(id="g-espectro", config=GRAFICO),
                          dcc.Graph(figure=fig_ocupacion_espectral(), config=GRAFICO),
                      ])),
            ]),

            # --- DECISION ---------------------------------------------------
            dcc.Tab(label="Modelo de decision", value="t4",
                    className="tab-item", selected_className="tab-item--sel", children=[
                html.Div(style={"height": "26px"}),
                panel("Indicadores por canal",
                      "El modelo traduce cada estimacion numerica en una hipotesis booleana "
                      "y cada hipotesis en una accion administrativa concreta.",
                      html.Div([
                          html.Div([
                              html.Div(dcc.Graph(figure=fig_ise(), config=GRAFICO),
                                       style={"flex": "1 1 330px"}),
                              html.Div(dcc.Graph(figure=fig_comparativa_canales(), config=GRAFICO),
                                       style={"flex": "1 1 330px"}),
                              html.Div(dcc.Graph(figure=fig_extension(), config=GRAFICO),
                                       style={"flex": "1 1 330px"}),
                          ], style={"display": "flex", "gap": "14px", "flexWrap": "wrap"}),
                          html.Div(style={"height": "26px"}),
                          tabla_decisiones(),
                      ])),
                panel("Acciones recomendadas a la Agencia",
                      "Una accion por canal, derivada de la hipotesis que resulto verdadera.",
                      panel_acciones()),
            ]),

            # --- FUENTES ----------------------------------------------------
            dcc.Tab(label="Fuentes", value="t5",
                    className="tab-item", selected_className="tab-item--sel", children=[
                html.Div(style={"height": "26px"}),
                panel("Fuentes de contaminacion estimadas por extrapolacion",
                      "Multilateracion sobre el nivel de senal recibida con modelo "
                      "log-distancia P(d) = P0 − 10·n·log10(d/d0), n = %.1f, ajustado por "
                      "minimos cuadrados no lineales sobre los 12 puntos de mayor potencia "
                      "de cada canal." % cfg.EXP_PERDIDA_N,
                      html.Div([
                          tabla_fuentes(),
                          html.Div(style={"height": "26px"}),
                          html.Div([
                              html.Div([
                                  html.Div(("Canal %s" % f.canal) if f.canal != "F_MAX"
                                           else "Frecuencia %s" % f.banda,
                                           style={"fontWeight": "600", "fontSize": "14px",
                                                  "marginBottom": "6px"}),
                                  html.Div(f.interpretacion,
                                           style={"fontSize": "13px", "color": es.TINTA_2,
                                                  "lineHeight": "1.6"}),
                              ], style={"background": es.SUPERFICIE_2,
                                        "borderRadius": es.RADIO_CHICO,
                                        "padding": "17px 20px", "marginBottom": "11px"})
                              for _, f in DATOS["fuentes"].iterrows()]),
                      ])),
            ]),

            # --- CALIDAD ----------------------------------------------------
            dcc.Tab(label="Calidad del dato", value="t6",
                    className="tab-item", selected_className="tab-item--sel", children=[
                html.Div(style={"height": "26px"}),
                panel("Calidad de la fuente de datos",
                      "Resultado del perfilado contra once reglas de validacion y registro "
                      "de cada celda modificada por el proceso de imputacion.",
                      bloque_calidad()),
            ]),
        ]),

        html.Div("Estudio tecnico de ocupacion espectral  ·  Internet de las Cosas  ·  "
                 "Examen 3", style={
            "textAlign": "center", "color": es.TINTA_3, "fontSize": "12.5px",
            "padding": "44px 0 18px 0"}),

    ], style={"maxWidth": "1500px", "margin": "0 auto", "padding": "0 34px 30px 34px"}),

], style={"background": es.FONDO, "minHeight": "100vh"})


# ---------------------------------------------------------------------------
# CALLBACKS
# ---------------------------------------------------------------------------
@app.callback(Output("g-ubicacion", "figure"), Input("color-puntos", "value"))
def actualizar_ubicacion(color):
    return fig_ubicacion(color)


@app.callback(Output("g-mapa-calor", "figure"), Output("g-contorno", "figure"),
              Input("capa-mapa", "value"))
def actualizar_mapa(capa):
    return fig_mapa_calor(capa), fig_contorno(capa)


@app.callback(Output("g-espectro", "figure"), Input("ver-maximo", "value"))
def actualizar_espectro(valor):
    return fig_espectro("max" in (valor or []))


if __name__ == "__main__":
    print("=" * 72)
    print(" DASHBOARD DE OCUPACION ESPECTRAL 840 - 860 MHz")
    print(" Mediciones cargadas   : %d" % len(DATOS["ind"]))
    print(" Canal mas contaminado : %s (ISE %.1f)"
          % (DATOS["decisiones"].iloc[0].canal, DATOS["decisiones"].iloc[0].ISE))
    print(" Servidor en http://127.0.0.1:%d" % PUERTO)
    print("=" * 72)
    app.run(debug=False, port=PUERTO)

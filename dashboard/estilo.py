# -*- coding: utf-8 -*-
"""
estilo.py - SISTEMA DE DISENO DEL DASHBOARD

Centraliza la paleta, la tipografia y los estilos de los componentes para que
la interfaz sea coherente y el codigo de app.py se ocupe solo de los datos.

El lenguaje visual sigue los principios de diseno de Apple: fondo claro y
neutro, tarjetas blancas con esquinas muy redondeadas y sombra difusa en lugar
de bordes marcados, un unico color de acento, jerarquia construida con el peso
y el tamano de la tipografia (no con cajas de colores), y mucho espacio en
blanco entre bloques.
"""

# ---------------------------------------------------------------------------
# PALETA
# ---------------------------------------------------------------------------
FONDO = "#F5F5F7"           # gris neutro de fondo
SUPERFICIE = "#FFFFFF"      # tarjetas y paneles
SUPERFICIE_2 = "#FAFAFC"    # filas alternas y zonas hundidas
BORDE = "#E5E5EA"           # separadores muy sutiles

TINTA = "#1D1D1F"           # texto principal, casi negro
TINTA_2 = "#6E6E73"         # texto secundario
TINTA_3 = "#9A9AA0"         # texto terciario y etiquetas

ACENTO = "#0071E3"          # azul de accion
ACENTO_SUAVE = "#E8F1FD"

VERDE = "#34A853"
AMBAR = "#F5A623"
NARANJA = "#F2760C"
ROJO = "#D93025"

COLOR_CANAL = {"A": "#34A853", "B": "#F5A623", "C": "#D93025", "D": "#0071E3"}
COLOR_DECISION = {
    "NO ASIGNAR": ROJO,
    "ASIGNAR CON RESTRICCION": AMBAR,
    "ASIGNAR": VERDE,
    "ASIGNAR PRIORITARIO": VERDE,
}

FUENTE = ('-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", '
          '"Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif')

SOMBRA = "0 1px 3px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.06)"
SOMBRA_SUAVE = "0 1px 2px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.04)"
RADIO = "18px"
RADIO_CHICO = "12px"


# ---------------------------------------------------------------------------
# ESTILOS DE COMPONENTE
# ---------------------------------------------------------------------------
TARJETA = {
    "background": SUPERFICIE,
    "borderRadius": RADIO,
    "boxShadow": SOMBRA_SUAVE,
    "padding": "22px 26px",
}

PANEL = {
    "background": SUPERFICIE,
    "borderRadius": RADIO,
    "boxShadow": SOMBRA,
    "padding": "26px 30px",
    "marginBottom": "22px",
}

TITULO_SECCION = {
    "fontSize": "21px",
    "fontWeight": "600",
    "color": TINTA,
    "letterSpacing": "-0.02em",
    "margin": "0 0 4px 0",
}

SUBTITULO_SECCION = {
    "fontSize": "14px",
    "color": TINTA_2,
    "margin": "0 0 22px 0",
    "lineHeight": "1.5",
}

ETIQUETA = {
    "fontSize": "11px",
    "fontWeight": "600",
    "color": TINTA_3,
    "textTransform": "uppercase",
    "letterSpacing": "0.07em",
}


def css_global():
    """
    Hoja de estilo inyectada en el index de Dash.

    Cubre lo que no se puede expresar con estilos en linea: la reescritura de
    los radio buttons como control segmentado, las pestanas, el scrollbar y el
    suavizado de fuentes.
    """
    return """
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; }
    body {
        background: %(fondo)s;
        color: %(tinta)s;
        font-family: %(fuente)s;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }

    /* ---- Control segmentado (radio buttons al estilo de iOS) ----
       Dash marca la opcion activa con la clase .selected en el <label> y
       envuelve el <input> en un <span>, de modo que el estilo se engancha a
       esa clase y oculta por completo el circulo nativo del radio.         */
    .segmentado { display: inline-flex; background: #EFEFF2; border-radius: 11px;
                  padding: 3px; gap: 2px; flex-wrap: wrap; }
    .segmentado label {
        position: relative; display: inline-flex; align-items: center;
        padding: 7px 16px; border-radius: 9px; cursor: pointer;
        font-size: 13px; font-weight: 500; color: %(tinta2)s;
        transition: background .18s ease, color .18s ease, box-shadow .18s ease;
        white-space: nowrap; margin: 0; user-select: none;
    }
    .segmentado label:hover { color: %(tinta)s; }
    .segmentado .dash-options-list-option-wrapper { display: none; }
    .segmentado input { position: absolute; opacity: 0; width: 0; height: 0;
                        pointer-events: none; }
    .segmentado label.selected,
    .segmentado label:has(input:checked) {
        background: #FFFFFF; color: %(tinta)s; font-weight: 600;
        box-shadow: 0 1px 3px rgba(0,0,0,.10);
    }

    /* ---- Pestanas ---- */
    .tabs-contenedor { border: none !important; }
    .tab-item {
        border: none !important; background: transparent !important;
        color: %(tinta2)s !important; font-size: 14.5px !important;
        font-weight: 500 !important; padding: 10px 2px !important;
        margin-right: 30px !important; border-bottom: 2px solid transparent !important;
        transition: color .18s ease, border-color .18s ease;
    }
    .tab-item:hover { color: %(tinta)s !important; }
    .tab-item--sel {
        color: %(tinta)s !important; font-weight: 600 !important;
        border-bottom: 2px solid %(tinta)s !important;
    }

    /* ---- Tablas ---- */
    table.limpia { width: 100%%; border-collapse: collapse; font-size: 13.5px; }
    table.limpia th {
        text-align: left; padding: 11px 14px; font-size: 11px; font-weight: 600;
        color: %(tinta3)s; text-transform: uppercase; letter-spacing: .06em;
        border-bottom: 1px solid %(borde)s; white-space: nowrap;
    }
    table.limpia td {
        padding: 13px 14px; color: %(tinta)s;
        border-bottom: 1px solid %(borde)s; vertical-align: middle;
    }
    table.limpia tbody tr:last-child td { border-bottom: none; }
    table.limpia tbody tr { transition: background .15s ease; }
    table.limpia tbody tr:hover { background: %(superficie2)s; }
    .num { font-variant-numeric: tabular-nums; }

    /* ---- Insignias ---- */
    .insignia {
        display: inline-block; padding: 4px 11px; border-radius: 999px;
        font-size: 11.5px; font-weight: 600; letter-spacing: .01em;
        white-space: nowrap;
    }

    /* ---- Scrollbar ---- */
    ::-webkit-scrollbar { width: 11px; height: 11px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: #C7C7CC; border-radius: 99px;
                                border: 3px solid %(fondo)s; }
    ::-webkit-scrollbar-thumb:hover { background: #AEAEB2; }

    .js-plotly-plot .plotly .modebar { opacity: .25; transition: opacity .2s; }
    .js-plotly-plot:hover .plotly .modebar { opacity: 1; }
    """ % dict(fondo=FONDO, tinta=TINTA, tinta2=TINTA_2, tinta3=TINTA_3,
               borde=BORDE, superficie2=SUPERFICIE_2, fuente=FUENTE)

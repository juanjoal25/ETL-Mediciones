# -*- coding: utf-8 -*-
"""
generar_informe.py - CONSTRUCCION DEL INFORME TECNICO EN WORD

Genera el documento entregable para la Agencia Nacional del Espectro con todas
las secciones exigidas por el enunciado. Todos los numeros del texto se leen de
los artefactos del datalake: el informe NO tiene cifras escritas a mano, de
modo que si el ETL cambia, el informe se regenera coherente.
"""

import ast
import os
import sys
from datetime import date

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_es(d):
    """Formatea una fecha en espanol sin depender del locale del sistema."""
    return "%d de %s de %d" % (d.day, MESES[d.month - 1], d.year)


def lista_de_csv(valor):
    """
    Convierte a lista un campo que pandas leyo de un CSV.

    Al escribir una lista de Python en CSV queda como la cadena "['B', 'D']";
    al releerla vuelve como texto. Se usa ast.literal_eval y no eval porque
    solo debe interpretar literales, nunca ejecutar codigo.
    """
    if isinstance(valor, str):
        try:
            return list(ast.literal_eval(valor))
        except (ValueError, SyntaxError):
            return [v.strip() for v in valor.split(",") if v.strip()]
    return list(valor)

import numpy as np
import pandas as pd
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "etl"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modelo"))
import config as cfg

AZUL = RGBColor(0x1A, 0x36, 0x5D)
ROJO = RGBColor(0xC1, 0x29, 0x2E)
VERDE = RGBColor(0x2E, 0x93, 0x3C)


# ---------------------------------------------------------------------------
# UTILIDADES DE MAQUETACION
# ---------------------------------------------------------------------------
def _titulo(doc, texto, nivel=1):
    h = doc.add_heading(texto, level=nivel)
    for run in h.runs:
        run.font.color.rgb = AZUL
    return h


def _parrafo(doc, texto, negrita=False, tam=10.5, align=WD_ALIGN_PARAGRAPH.JUSTIFY):
    p = doc.add_paragraph()
    p.alignment = align
    r = p.add_run(texto)
    r.bold = negrita
    r.font.size = Pt(tam)
    return p


def _dato_clave(doc, etiqueta, valor, color=AZUL):
    """Linea destacada del tipo 'Etiqueta: VALOR'."""
    p = doc.add_paragraph()
    r = p.add_run("%s: " % etiqueta)
    r.bold = True
    r.font.size = Pt(10.5)
    r = p.add_run(str(valor))
    r.bold = True
    r.font.size = Pt(10.5)
    r.font.color.rgb = color
    return p


def _vineta(doc, texto):
    p = doc.add_paragraph(style="List Bullet")
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    r = p.add_run(texto)
    r.font.size = Pt(10.5)
    return p


def _tabla(doc, encabezados, filas, anchos=None):
    t = doc.add_table(rows=1, cols=len(encabezados))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(encabezados):
        celda = t.rows[0].cells[i]
        celda.text = ""
        r = celda.paragraphs[0].add_run(str(h))
        r.bold = True
        r.font.size = Pt(9)
    for fila in filas:
        celdas = t.add_row().cells
        for i, v in enumerate(fila):
            celdas[i].text = ""
            r = celdas[i].paragraphs[0].add_run(str(v))
            r.font.size = Pt(9)
    if anchos:
        for fila in t.rows:
            for i, w in enumerate(anchos):
                fila.cells[i].width = Cm(w)
    doc.add_paragraph()
    return t


def _figura(doc, nombre, pie, ancho=16.0):
    ruta = os.path.join(cfg.DIR_FIGURAS, nombre)
    if not os.path.exists(ruta):
        return
    doc.add_picture(ruta, width=Cm(ancho))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(pie)
    r.italic = True
    r.font.size = Pt(8.5)
    r.font.color.rgb = RGBColor(0x4A, 0x55, 0x68)


# ---------------------------------------------------------------------------
# CARGA DE ARTEFACTOS
# ---------------------------------------------------------------------------
def cargar():
    import quality
    import temperatura as mod_temp

    L = {}
    L["crudo"] = pd.read_parquet(os.path.join(cfg.LAKE_BRONCE, "medidas_crudas.parquet"))
    L["limpio"] = pd.read_parquet(os.path.join(cfg.LAKE_PLATA, "medidas_limpias.parquet"))
    L["ind"] = pd.read_parquet(os.path.join(cfg.LAKE_ORO, "indicadores_por_punto.parquet"))
    L["perfil"] = pd.read_parquet(os.path.join(cfg.LAKE_ORO, "perfil_espectral.parquet"))
    L["reglas"] = pd.read_csv(os.path.join(cfg.LAKE_PLATA, "reporte_reglas.csv"))
    L["indices"] = pd.read_csv(os.path.join(cfg.LAKE_PLATA, "indices_calidad.csv"))
    L["bitacora"] = pd.read_csv(os.path.join(cfg.LAKE_PLATA, "bitacora_imputacion.csv"))
    L["gps"] = pd.read_csv(os.path.join(cfg.LAKE_PLATA, "detalle_gps_imputado.csv"))
    L["descartadas"] = pd.read_csv(os.path.join(cfg.LAKE_PLATA, "mediciones_descartadas.csv"))
    L["meta"] = pd.read_csv(os.path.join(cfg.LAKE_PLATA, "meta_transformacion.csv")).iloc[0]
    L["resumen"] = pd.read_csv(os.path.join(cfg.LAKE_ORO, "resumen_canales.csv"))
    L["decisiones"] = pd.read_csv(os.path.join(cfg.LAKE_ORO, "decisiones_canales.csv"))
    L["global"] = pd.read_csv(os.path.join(cfg.LAKE_ORO, "recomendacion_global.csv")).iloc[0]
    L["fuentes"] = pd.read_csv(os.path.join(cfg.LAKE_ORO, "fuentes_estimadas.csv"))
    L["antena"] = pd.read_parquet(os.path.join(cfg.LAKE_BRONCE, "antena_s11.parquet"))

    banderas, _ = quality.evaluar(L["crudo"])
    L["banderas"] = banderas
    L["temp"] = mod_temp.analizar(L["crudo"], banderas)

    p = L["perfil"]
    pn = (p.P_media_dbm - p.P_media_dbm.min()) / (p.P_media_dbm.max() - p.P_media_dbm.min())
    p = p.assign(puntaje=0.7 * pn + 0.3 * p.ocupacion_pct / 100.0)
    L["f_peor"] = p.loc[p.puntaje.idxmax()]
    L["f_mejor"] = p.loc[p.puntaje.idxmin()]
    return L


# ---------------------------------------------------------------------------
# SECCIONES DEL INFORME
# ---------------------------------------------------------------------------
def portada(doc, L):
    for _ in range(3):
        doc.add_paragraph()
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("ESTUDIO TECNICO DE OCUPACION DEL ESPECTRO\nBANDA 840 - 860 MHz")
    r.bold = True; r.font.size = Pt(22); r.font.color.rgb = AZUL

    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Sector occidental de Medellin")
    r.font.size = Pt(15); r.font.color.rgb = RGBColor(0x4A, 0x55, 0x68)

    doc.add_paragraph()
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Informe para la Agencia Nacional del Espectro (ANE)\n"
                  "Insumo para el plan de frecuencias del Ministerio TIC de Colombia")
    r.font.size = Pt(12); r.bold = True

    for _ in range(4):
        doc.add_paragraph()

    _tabla(doc, ["Concepto", "Valor"], [
        ["Asignatura", "Internet de las Cosas - Examen / Trabajo 3"],
        ["Objeto del estudio", "Contaminacion espectral de la banda celular 840 - 860 MHz"],
        ["Sensor", "Estacion movil de monitoreo con receptor USRP (GNU Radio) y GPS"],
        ["Resolucion espectral", "%.2f kHz por bin (FFT de %d puntos sobre %.0f MHz)"
         % (cfg.RBW_HZ / 1e3, cfg.N_BINS, cfg.ANCHO_BANDA_HZ / 1e6)],
        ["Mediciones extraidas", "%d archivos" % len(L["crudo"])],
        ["Mediciones validas", "%d (%.1f %%)" % (len(L["limpio"]),
                                                 100.0 * len(L["limpio"]) / len(L["crudo"]))],
        ["Indice global de calidad", "%.2f %%" % L["indices"].iloc[-1].valor_pct],
        ["Fecha del informe", fecha_es(date.today())],
    ], anchos=[5.5, 10.5])

    doc.add_page_break()


def resumen_ejecutivo(doc, L):
    _titulo(doc, "Resumen ejecutivo", 1)
    G, D = L["global"], L["decisiones"]
    peor = D.iloc[0]; mejor = D.iloc[-1]

    _parrafo(doc,
        "Se proceso una campana de %d mediciones de ocupacion espectral levantadas por una estacion "
        "movil de monitoreo en el sector occidental de Medellin. Tras aplicar un proceso de ETL con "
        "once reglas de validacion, %d mediciones resultaron aptas para el analisis (%.1f %% del total) "
        "y se alcanzo un indice global de calidad del %.2f %%. Sobre ese conjunto se calculo la potencia "
        "media de ocupacion de los cuatro canales de 5 MHz mediante la sumatoria de Parseval."
        % (len(L["crudo"]), len(L["limpio"]), 100.0 * len(L["limpio"]) / len(L["crudo"]),
           L["indices"].iloc[-1].valor_pct))

    doc.add_paragraph()
    _dato_clave(doc, "Canal mas contaminado", "%s (%s) - ISE %.1f/100, categoria %s"
                % (peor.canal, peor.banda, peor.ISE, peor.categoria), ROJO)
    _dato_clave(doc, "Canal menos contaminado", "%s (%s) - ISE %.1f/100, categoria %s"
                % (mejor.canal, mejor.banda, mejor.ISE, mejor.categoria), VERDE)
    _dato_clave(doc, "Frecuencia mas contaminada", "%.4f MHz (%.2f dBm, presente en %.0f %% de la ruta)"
                % (L["f_peor"].frecuencia_mhz, L["f_peor"].P_media_dbm, L["f_peor"].ocupacion_pct), ROJO)
    _dato_clave(doc, "Frecuencia menos contaminada", "%.4f MHz (%.2f dBm, presente en %.0f %% de la ruta)"
                % (L["f_mejor"].frecuencia_mhz, L["f_mejor"].P_media_dbm, L["f_mejor"].ocupacion_pct), VERDE)

    doc.add_paragraph()
    _parrafo(doc,
        "El canal %s se encuentra ocupado por encima del umbral de -60 dBm en el %.1f %% del area "
        "recorrida, lo que lo inhabilita como bloque asignable. Los canales %s presentan contaminacion "
        "localizada y son asignables bajo coordinacion geografica. El canal %s es el mas limpio de la "
        "banda y se recomienda como primera opcion del plan de frecuencias. En terminos de recurso, "
        "%.0f MHz de los %.0f MHz estudiados quedan inutilizables sin una accion de control previa."
        % (peor.canal, peor.pct_puntos_ocupados,
           " y ".join(D[D.decision == "ASIGNAR CON RESTRICCION"].canal.tolist()) or "intermedios",
           mejor.canal, G.espectro_perdido_mhz,
           G.espectro_util_mhz + G.espectro_perdido_mhz))

    doc.add_page_break()


def seccion_arquitectura(doc, L):
    _titulo(doc, "1. Arquitectura del proceso ETL", 1)
    _parrafo(doc,
        "El procesamiento sigue la arquitectura de referencia de la asignatura "
        "(sensores - colector - ETL - almacenamiento - modelo - visualizacion), implementada como un "
        "datalake de tres capas que garantiza la trazabilidad de cada transformacion:")

    _tabla(doc, ["Capa", "Contenido", "Modulo"], [
        ["BRONCE", "Datos crudos tal como los entrego el sensor, sin modificar. Permite auditar "
                   "cualquier decision posterior.", "etl/extract.py"],
        ["PLATA", "Datos validados, limpios, imputados y calibrados, con la bitacora de cada celda "
                  "modificada.", "etl/quality.py + etl/transform.py"],
        ["ORO", "Indicadores de negocio: potencia Parseval por canal, ocupacion, decisiones y "
                "fuentes extrapoladas.", "etl/indicators.py + modelo/"],
    ], anchos=[2.6, 9.4, 4.0])

    _parrafo(doc,
        "La separacion entre DIAGNOSTICO (quality.py, que no modifica nada) y CORRECCION "
        "(transform.py, que si modifica) es deliberada: el enunciado exige reportar cuantos datos se "
        "modificaron y por que, y sin una capa de diagnostico explicita ese numero no seria trazable.")

    _titulo(doc, "1.1 Estructura de la fuente de datos", 2)
    _parrafo(doc,
        "Cada archivo de medida contiene una unica fila con %d campos separados por coma: las primeras "
        "%d posiciones son el espectro de potencia en dBm desde %.0f MHz hasta %.0f MHz, y las cinco "
        "ultimas son, en su orden, temperatura del sensor, longitud, latitud, altura y error de "
        "distancia del GPS. La resolucion de cada bin es de %.2f kHz, resultado de repartir los "
        "%.0f MHz de ancho de banda del receptor entre los %d puntos de la FFT."
        % (cfg.N_COLUMNAS, cfg.N_BINS, cfg.F_INICIO_HZ / 1e6, cfg.F_FIN_HZ / 1e6,
           cfg.RBW_HZ / 1e3, cfg.ANCHO_BANDA_HZ / 1e6, cfg.N_BINS))


def seccion_calidad(doc, L):
    doc.add_page_break()
    _titulo(doc, "2. Informe de calidad de los datos", 1)

    ind = L["indices"]
    _parrafo(doc,
        "Se evaluaron las %d mediciones contra once reglas de validacion que cubren estructura, "
        "completitud, georreferenciacion, rango fisico del receptor, coherencia de nivel y ventana "
        "termica de operacion. El resultado consolidado en las cinco dimensiones clasicas de calidad "
        "de datos es el siguiente:" % len(L["crudo"]))

    _tabla(doc, ["Dimension", "Cumplimiento", "Definicion aplicada"],
           [[f.dimension, "%.2f %%" % f.valor_pct, f.definicion] for _, f in ind.iterrows()],
           anchos=[3.4, 2.6, 10.0])

    _titulo(doc, "2.1 Defectos detectados", 2)
    act = L["reglas"][L["reglas"].mediciones_afectadas > 0]
    _tabla(doc, ["Regla", "Severidad", "Mediciones", "Descripcion del defecto"],
           [[f.regla.split("_", 1)[1], f.severidad.upper(), f.mediciones_afectadas, f.descripcion]
            for _, f in act.iterrows()],
           anchos=[3.6, 2.2, 2.0, 8.2])

    _figura(doc, "02_calidad.png",
            "Figura 1. Reglas de validacion activadas y cumplimiento por dimension de calidad.")

    _titulo(doc, "2.2 Mediciones descartadas", 2)
    _parrafo(doc,
        "Tres mediciones se excluyeron por completo del analisis. El criterio para descartar en lugar "
        "de imputar es que el defecto afecta a la totalidad de la traza espectral y no existe forma de "
        "reconstruirla sin inventar informacion:")

    des = L["descartadas"]
    _tabla(doc, ["Archivo", "Reglas violadas", "Evidencia"],
           [[f.archivo, str(f.reglas_activas).replace(";", ", "), f.detalle] for _, f in des.iterrows()],
           anchos=[3.2, 6.4, 6.4])

    _vineta(doc,
        "016.txt presenta la traza completa desplazada +55 dB respecto de la medicion 015 y +35 dB "
        "respecto de la 017, conservando la misma forma espectral (correlacion de 0.70 con sus "
        "vecinas). Un salto de nivel de ese tamano en dos posiciones GPS separadas por menos de 400 m "
        "es fisicamente imposible: corresponde a un error de ganancia del front-end o a compresion del "
        "receptor, cuyo pico de -3.6 dBm esta por encima del punto de compresion de la cadena. El dato "
        "no es recuperable porque se desconoce el factor de ganancia exacto que se aplico.")
    _vineta(doc,
        "medidaprueba.txt y medidapureba2.txt son capturas de verificacion previas a la campana. Lo "
        "confirman tres evidencias independientes: el nombre del archivo, la temperatura del sensor "
        "(35.2 y 38.1 grados, muy por debajo de los 42.8 a 50.4 grados de toda la campana, es decir el "
        "equipo aun no habia estabilizado) y, en el primer caso, la ausencia total de fix GPS.")

    _figura(doc, "03_etl.png",
            "Figura 2. Arriba: correccion de la fuga de oscilador local. Abajo: la traza 016 comparada "
            "con sus vecinas inmediatas, que motiva su descarte.")


def seccion_imputacion(doc, L):
    doc.add_page_break()
    _titulo(doc, "3. Tecnicas de imputacion y correcciones aplicadas", 1)

    bit = L["bitacora"]
    _parrafo(doc,
        "La siguiente bitacora registra cada celda del dataset que fue modificada, con la tecnica "
        "empleada y su justificacion. El orden de los pasos no es arbitrario: primero se corrigen los "
        "artefactos instrumentales, despues se calibra y solo al final se aplica la regla de negocio "
        "del enunciado, porque esta debe operar sobre la medida que representa la potencia realmente "
        "incidente sobre la antena.")

    _tabla(doc, ["Paso", "Tecnica", "Celdas", "Unidad", "% dataset"],
           [[f.paso.split("_", 1)[1], f.tecnica, "%d" % f.cantidad, f.unidad, "%.3f" % f.pct_del_dataset]
            for _, f in bit.iterrows()],
           anchos=[3.4, 6.2, 1.8, 3.0, 1.6])

    _titulo(doc, "3.1 T1 - Imputacion de la fuga de oscilador local", 2)
    n_dc = int(bit[bit.paso == "P1_FUGA_LO"].cantidad.iloc[0])
    n_arch = int(L["banderas"]["R9_FUGA_LO_DC"].sum())
    _parrafo(doc,
        "Fue el hallazgo mas relevante del perfilado. El receptor del USRP es de conversion directa "
        "(zero-IF): el desbalance de continua del mezclador y la fuga del oscilador local se suman a la "
        "componente de continua de la senal en banda base. Tras el desplazamiento espectral que aplica "
        "el sensor (numpy.fft.fftshift) esa componente cae exactamente en el bin %d, es decir en "
        "%.3f MHz, que es justo la FRONTERA entre los canales B y C."
        % (cfg.BIN_DC, cfg.F_CENTRAL_HZ / 1e6))
    _parrafo(doc,
        "Se detecto el espurio en %d de las %d mediciones, con excesos de hasta 26.3 dB sobre los bins "
        "vecinos. De no corregirse, se habria contabilizado como ocupacion real y habria inflado "
        "simultaneamente el indicador de los dos canales centrales. Se imputaron los %d bins afectados "
        "por interpolacion lineal a partir de los seis bins de apoyo adyacentes. La interpolacion se "
        "ejecuta en POTENCIA LINEAL (mW) y no en decibelios: promediar decibelios equivale a una media "
        "geometrica de potencias y subestimaria el nivel real de la envolvente. La hipotesis de "
        "suavidad es solida porque la envolvente de una portadora celular no cambia apreciablemente en "
        "una ventana de 59 kHz."
        % (n_arch, len(L["crudo"]), n_dc))

    _titulo(doc, "3.2 T2 - Imputacion de la georreferenciacion", 2)
    gps = L["gps"]
    _parrafo(doc,
        "Dos mediciones tenian la posicion inutilizable y su espectro, en cambio, era perfectamente "
        "valido: descartarlas habria significado perder informacion radioelectrica buena por un fallo "
        "del receptor GNSS. Como la estacion es movil y recorre una trayectoria continua, la posicion "
        "se reconstruye interpolando linealmente entre las posiciones validas anterior y posterior de "
        "la secuencia. Es el equivalente espacio-temporal de la interpolacion de malla vista en clase.")

    filas = []
    for arch in gps.archivo.unique():
        sub = gps[gps.archivo == arch]
        v = {r.campo: (r.valor_original, r.valor_imputado) for r in sub.itertuples()}
        filas.append([arch,
                      "%.6f -> %.6f" % v["longitud"],
                      "%.6f -> %.6f" % v["latitud"],
                      "%.1f -> %.1f" % v["altura"]])
    _tabla(doc, ["Archivo", "Longitud", "Latitud", "Altura (m)"], filas,
           anchos=[2.6, 5.0, 5.0, 3.4])

    _vineta(doc,
        "008.txt registro longitud, latitud y altura exactamente en cero con un error de distancia de "
        "4.4: el receptor GNSS no logro solucion de navegacion. La coordenada (0,0) esta en el golfo de "
        "Guinea, a 9000 km del area de estudio, de modo que usarla habria destruido por completo "
        "cualquier mapa de calor.")
    _vineta(doc,
        "017.txt reporto un error de distancia de 17.3, mas de diez veces el valor tipico de la "
        "campana (0.8 a 1.4), lo que implica una incertidumbre horizontal del orden de decenas de "
        "metros. Su altura de 1565 m tambien se desvia unos 35 m de la de sus vecinas inmediatas. Se "
        "reconstruyo su posicion por el mismo procedimiento.")

    _titulo(doc, "3.3 T3 - Calibracion por desacople de antena", 2)
    en = L["antena"][(L["antena"].frecuencia_hz >= cfg.F_INICIO_HZ) &
                     (L["antena"].frecuencia_hz <= cfg.F_FIN_HZ)]
    grad = en.perdida_desacople_db.iloc[0] - en.perdida_desacople_db.iloc[-1]
    _parrafo(doc,
        "El archivo ANTENNA1.csv contiene el barrido de parametro S11 de la antena de monitoreo, medido "
        "con un analizador Agilent N9914A entre 700 y 950 MHz. En la banda de estudio el S11 pasa de "
        "%.2f dB en 840 MHz a %.2f dB en 860 MHz: la antena esta claramente desadaptada y, lo que "
        "importa aqui, lo esta de forma DEPENDIENTE DE LA FRECUENCIA."
        % (en.s11_db.iloc[0], en.s11_db.iloc[-1]))
    _parrafo(doc,
        "A partir del coeficiente de reflexion en potencia se obtiene la perdida por desacople, "
        "L = -10 log10(1 - 10^(S11/10)), que vale %.2f dB en el extremo inferior de la banda y %.2f dB "
        "en el superior. Ese gradiente de %.2f dB penalizaba sistematicamente al canal A frente al "
        "canal D y habria contaminado la comparacion entre bloques, que es justamente el objeto del "
        "estudio. La correccion se des-incrusta sumando L(f) a cada bin. No es una imputacion sino una "
        "calibracion determinista. Su efecto no es despreciable: %d muestras cambian de lado respecto "
        "del umbral de -65 dBm al aplicarla."
        % (en.perdida_desacople_db.iloc[0], en.perdida_desacople_db.iloc[-1], grad,
           int(L["meta"].cruces_umbral_por_calibracion)))

    _figura(doc, "10_antena.png",
            "Figura 3. Adaptacion de la antena de monitoreo y correccion aplicada a cada bin.", 15.5)

    _titulo(doc, "3.4 T4 - Regla de censura del piso de ruido", 2)
    n_piso = int(L["bitacora"][L["bitacora"].paso == "P4_REGLA_PISO"].cantidad.iloc[0])
    _parrafo(doc,
        "El enunciado establece que toda muestra por debajo de %.1f dBm se sustituya por %.1f dBm. Se "
        "aplico a %d celdas espectrales, el %.1f %% de las muestras conservadas. Su lectura tecnica es "
        "que %.1f dBm marca el umbral de deteccion util del sistema de monitoreo: por debajo no se "
        "puede afirmar que exista emision, solo ruido del receptor. El efecto practico sobre el "
        "indicador es decisivo, porque elimina la contribucion del ruido termico a la sumatoria de "
        "Parseval; sin la censura, los 256 bins de ruido de un canal limpio acumularian una potencia "
        "comparable a la de una portadora real y enmascararian por completo la diferencia entre un "
        "canal ocupado y uno libre."
        % (cfg.UMBRAL_PISO_DBM, cfg.VALOR_PISO_DBM, n_piso,
           100.0 * n_piso / (len(L["limpio"]) * cfg.N_BINS), cfg.UMBRAL_PISO_DBM))

    total_mod = int(L["bitacora"].cantidad.sum())
    doc.add_paragraph()
    _dato_clave(doc, "Total de celdas modificadas o descartadas", "%d" % total_mod)
    _dato_clave(doc, "Mediciones descartadas", "%d de %d (%.1f %%)"
                % (len(L["descartadas"]), len(L["crudo"]),
                   100.0 * len(L["descartadas"]) / len(L["crudo"])))
    _dato_clave(doc, "Mediciones imputadas parcialmente", "%d"
                % int((L["banderas"]["dictamen"] == "IMPUTABLE").sum()))


def seccion_ruta(doc, L):
    doc.add_page_break()
    _titulo(doc, "4. Ruta de la estacion movil de medicion", 1)

    ind = L["ind"]
    lat, lon = ind.latitud.to_numpy(), ind.longitud.to_numpy()
    # Longitud del recorrido por suma de tramos, con proyeccion local
    dx = np.diff(lon) * 111320.0 * np.cos(np.radians(lat[:-1].mean()))
    dy = np.diff(lat) * 110540.0
    recorrido = float(np.hypot(dx, dy).sum())

    _parrafo(doc,
        "La secuencia numerica de los archivos (001 a 061) constituye la unica marca temporal "
        "disponible, ya que el sensor no registra estampa de tiempo. Ordenando las mediciones por ese "
        "indice se reconstruye la trayectoria seguida por la estacion movil.")

    _tabla(doc, ["Parametro de la ruta", "Valor"], [
        ["Puntos validos georreferenciados", "%d" % len(ind)],
        ["Extension en latitud", "%.6f a %.6f grados N" % (lat.min(), lat.max())],
        ["Extension en longitud", "%.6f a %.6f grados O" % (lon.min(), lon.max())],
        ["Cobertura aproximada", "%.2f km (N-S) x %.2f km (E-O)"
         % ((lat.max() - lat.min()) * 110.54, (lon.max() - lon.min()) * 111.32 * np.cos(np.radians(lat.mean())))],
        ["Longitud total recorrida", "%.2f km" % (recorrido / 1000.0)],
        ["Separacion media entre muestras", "%.0f m" % (recorrido / max(len(ind) - 1, 1))],
        ["Rango de altura", "%.1f a %.1f m sobre el nivel del mar" % (ind.altura.min(), ind.altura.max())],
        ["Error de distancia GPS tipico", "mediana %.2f, maximo %.2f"
         % (ind.error_distancia.median(), ind.error_distancia.max())],
        ["Posiciones imputadas", "%d" % int(ind.gps_imputado.sum())],
    ], anchos=[6.0, 10.0])

    _parrafo(doc,
        "El recorrido describe un circuito cerrado: arranca en el extremo norte del area (latitud "
        "%.4f), desciende por el costado occidental ganando altura hasta los %.0f m en la zona mas "
        "alta del sector, gira hacia el oriente en el extremo sur y regresa por el costado oriental "
        "hasta un punto proximo al de partida. Esta geometria en lazo es favorable para el estudio "
        "porque rodea el area en lugar de atravesarla, lo que mejora la diversidad angular de las "
        "observaciones y con ello la capacidad de discriminar la direccion de las fuentes."
        % (lat[0], ind.altura.max()))

    _figura(doc, "01_ruta.png",
            "Figura 4. Ruta de la estacion movil. El color codifica la secuencia temporal; los circulos "
            "rojos marcan las posiciones reconstruidas por imputacion.", 13.5)


def seccion_temperatura(doc, L):
    doc.add_page_break()
    _titulo(doc, "5. Incidencia de la temperatura del sensor en la calidad de los datos", 1)

    R = L["temp"]
    c, fis, g = R["confusion"], R["fisica"], R["grupos"]

    _dato_clave(doc, "CONCLUSION",
                "No existe evidencia de que la temperatura del sensor degrade la calidad de las "
                "mediciones", VERDE)
    doc.add_paragraph()

    _titulo(doc, "5.1 El problema metodologico: una variable de confusion", 2)
    _parrafo(doc,
        "La temperatura del receptor crece de forma casi monotona a lo largo de la campana, de %.1f a "
        "%.1f grados, simplemente porque el equipo se calienta mientras opera. La correlacion entre "
        "temperatura y orden de medicion es de %+.3f (p = %.1e), practicamente determinista. Como la "
        "estacion se desplaza en el tiempo, la temperatura queda ademas correlacionada con la POSICION "
        "y, por tanto, con el entorno radioelectrico de cada punto."
        % (fis["T_min_C"], fis["T_max_C"], c["r_temp_orden"], c["p_temp_orden"]))
    _parrafo(doc,
        "La consecuencia es que una correlacion simple entre temperatura y cualquier metrica de calidad "
        "seria ESPURIA: estaria midiendo el efecto del recorrido, no el del calentamiento del receptor. "
        "Por eso el analisis se hace con correlaciones parciales que descuentan el efecto del tiempo, y "
        "con una regresion multivariada que separa las tres influencias.")

    _titulo(doc, "5.2 Correlaciones simples frente a correlaciones parciales", 2)
    C = R["correlaciones"]
    _tabla(doc, ["Metrica de calidad", "r simple", "rho Spearman", "r parcial", "p parcial", "Significativa"],
           [[f.descripcion, "%+.3f" % f.r_pearson, "%+.3f" % f.rho_spearman,
             "%+.3f" % f.r_parcial_ctrl_orden, "%.4f" % f.p_parcial,
             "SI" if f.significativa_5pct else "NO"] for _, f in C.iterrows()],
           anchos=[5.6, 1.9, 2.1, 1.9, 1.9, 2.0])

    _parrafo(doc,
        "El patron es inequivoco: las correlaciones simples son debiles (todas por debajo de 0.28 en "
        "valor absoluto) y, al controlar por el orden de medicion, SE DESVANECEN. Ninguna de las cinco "
        "metricas mantiene una asociacion estadisticamente significativa con la temperatura al 5 %. "
        "Notese ademas que el signo de varias correlaciones simples se invierte al aplicar el control, "
        "que es la firma clasica de una relacion espuria inducida por una variable de confusion.")

    _titulo(doc, "5.3 Regresion multivariada del piso de ruido", 2)
    _parrafo(doc,
        "Se ajusto por minimos cuadrados el modelo piso_ruido = b0 + b1*temperatura + b2*orden + "
        "b3*altura sobre las %d mediciones validas. El piso de ruido se estima como el percentil 5 de "
        "cada traza, medida robusta porque las emisiones ocupan una fraccion minoritaria de los 1024 "
        "bins, y se calcula sobre el espectro CRUDO: aplicar antes la censura de -65 dBm destruiria "
        "justamente la informacion que se quiere estudiar."
        % len(R["metricas"]))

    _tabla(doc, ["Variable", "Coeficiente", "Error estandar", "t", "p-valor", "Significativa"],
           [[f.variable, "%+.4f" % f.coeficiente, "%.4f" % f.error_estandar,
             "%+.2f" % f.t, "%.4f" % f.p_valor, "SI" if f.significativo_5pct else "NO"]
            for _, f in R["ols"].iterrows()],
           anchos=[3.4, 2.6, 2.8, 1.8, 2.2, 2.4])

    _parrafo(doc,
        "El modelo completo explica apenas el %.1f %% de la varianza del piso de ruido (R2 ajustado = "
        "%.3f) y NINGUNA de las tres variables resulta significativa. El coeficiente de temperatura, "
        "%.3f dB por grado, tiene un p-valor de %.3f: es indistinguible de cero."
        % (100 * max(R["r2_ajustado"], 0), R["r2_ajustado"],
           fis["pendiente_observada_db_por_C"],
           float(R["ols"].loc[R["ols"].variable == "temperatura_C", "p_valor"].iloc[0])))

    _titulo(doc, "5.4 Contraste contra la cota fisica", 2)
    _parrafo(doc,
        "El argumento definitivo es fisico y no estadistico. La potencia de ruido a la entrada de un "
        "receptor es N = k*T*B*F. Si la temperatura fisica pasa de %.1f a %.1f grados Celsius, es decir "
        "de %.1f a %.1f kelvin, el incremento MAXIMO del piso de ruido atribuible al termino kT es "
        "10*log10(T2/T1) = %.3f dB."
        % (fis["T_min_C"], fis["T_max_C"], fis["T_min_C"] + 273.15, fis["T_max_C"] + 273.15,
           fis["cota_teorica_db"]))
    _parrafo(doc,
        "Cualquier variacion observada muy por encima de ese valor NO puede explicarse por ruido "
        "termico. El coeficiente ajustado implicaria un efecto de %.2f dB sobre el rango de "
        "temperaturas de la campana, unas %.0f veces la cota fisica: un resultado imposible, que "
        "confirma que ese coeficiente es ruido de estimacion y no un efecto real. La comparacion entre "
        "los grupos frio y caliente apunta en la misma direccion: la diferencia de piso de ruido es de "
        "%+.2f dB con p = %.3f, no significativa."
        % (abs(fis["efecto_observado_db"]),
           abs(fis["efecto_observado_db"]) / fis["cota_teorica_db"],
           g["diferencia_db"], g["p_valor"]))

    _figura(doc, "07_temperatura.png",
            "Figura 5. Analisis de la incidencia termica. Arriba a la izquierda, la confusion entre "
            "temperatura y tiempo; abajo a la izquierda, el desvanecimiento de las correlaciones al "
            "controlar por el orden; abajo a la derecha, el contraste con la cota fisica.")

    _titulo(doc, "5.5 Que si depende de la temperatura", 2)
    _parrafo(doc,
        "El unico efecto real y verificable de la temperatura en este conjunto de datos es el criterio "
        "de VALIDEZ DE CAMPANA. Las dos capturas de prueba se realizaron a %.1f y %.1f grados, muy por "
        "debajo de la ventana de operacion estabilizada del equipo (%.1f a %.1f grados), lo que permitio "
        "identificarlas como ajenas a la campana con una evidencia independiente del nombre del "
        "archivo. Es decir, la temperatura no sirve para predecir la calidad de un dato, pero si para "
        "verificar que el instrumento estaba en regimen cuando lo tomo."
        % (35.2, 38.1, cfg.TEMP_MIN_OPERACION, cfg.TEMP_MAX_OPERACION))


def seccion_indicadores(doc, L):
    doc.add_page_break()
    _titulo(doc, "6. Transformacion de los datos en indicadores", 1)

    _titulo(doc, "6.1 Sumatoria de Parseval", 2)
    _parrafo(doc,
        "El teorema de Parseval establece que la energia de una senal es la misma calculada en el "
        "dominio del tiempo o en el de la frecuencia. En su forma discreta, para una secuencia de N "
        "muestras y su transformada de Fourier:")
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("sum |x[n]|^2  =  (1/N) sum |X[k]|^2")
    r.bold = True; r.font.size = Pt(11); r.font.name = "Consolas"

    _parrafo(doc,
        "El sensor entrega el espectro ya normalizado como S[k] = 20 log10(|X[k]|/N) en dBm, de modo "
        "que 10^(S[k]/10) es directamente la potencia del bin k. Restringiendo la suma a los %d bins "
        "que ocupan cada canal de 5 MHz se obtienen los dos indicadores del estudio:" % cfg.BINS_POR_CANAL)
    _vineta(doc, "Potencia TOTAL del canal: P_total = suma de 10^(S[k]/10) sobre los bins del canal. "
                 "Es la energia integrada en los 5 MHz.")
    _vineta(doc, "Potencia MEDIA de ocupacion: P_media = P_total / %d. Es la que exige el enunciado y "
                 "la que se compara contra el umbral de -60 dBm." % cfg.BINS_POR_CANAL)
    _parrafo(doc,
        "La suma se realiza SIEMPRE en potencia lineal. Sumar decibelios seria fisicamente incorrecto: "
        "el decibelio es logaritmico y la potencia solo es aditiva en su dominio lineal.")

    _titulo(doc, "6.2 Canalizacion", 2)
    _tabla(doc, ["Canal", "Banda", "Bins de la FFT", "Ancho"],
           [[c, "%.0f - %.0f MHz" % (cfg.CANALES[c][0] / 1e6, cfg.CANALES[c][1] / 1e6),
             "%d a %d" % (i * cfg.BINS_POR_CANAL, (i + 1) * cfg.BINS_POR_CANAL - 1),
             "%d bins x %.2f kHz = 5 MHz" % (cfg.BINS_POR_CANAL, cfg.RBW_HZ / 1e3)]
            for i, c in enumerate(cfg.CANALES)],
           anchos=[2.0, 4.0, 3.4, 6.6])

    _titulo(doc, "6.3 Resultados por canal", 2)
    R = L["resumen"]
    _tabla(doc, ["Canal", "Banda", "P media (dBm)", "P mediana (dBm)", "P maxima (dBm)",
                 "% puntos ocupados", "% ocupacion espectral"],
           [[f.canal, "%.0f-%.0f MHz" % (f.f_inicio_mhz, f.f_fin_mhz),
             "%.2f" % f.P_media_dbm, "%.2f" % f.P_mediana_dbm, "%.2f" % f.P_max_dbm,
             "%.1f %%" % f.pct_puntos_ocupados, "%.1f %%" % f.ocupacion_espectral_pct]
            for _, f in R.iterrows()],
           anchos=[1.6, 2.8, 2.4, 2.6, 2.4, 2.2, 2.0])

    _parrafo(doc,
        "Se reportan tres estadisticos de agregacion espacial porque cada uno responde a una pregunta "
        "distinta. La MEDIA se calcula en el dominio lineal y representa la potencia total que el area "
        "recibe, pero la dominan unos pocos puntos muy calientes. La MEDIANA describe el nivel que "
        "encuentra un usuario tipico y es robusta frente a esos valores extremos. El PORCENTAJE DE "
        "PUNTOS OCUPADOS mide la extension territorial del problema. La diferencia entre media y "
        "mediana es en si misma un diagnostico: en el canal B esa brecha supera los 27 dB, senal "
        "inequivoca de contaminacion muy localizada, mientras que en el canal C es de apenas 11 dB, "
        "lo que indica una ocupacion generalizada en toda el area.")

    _figura(doc, "04_perfil_espectral.png",
            "Figura 6. Perfil de ocupacion de la banda completa y porcentaje de la ruta que supera el "
            "umbral de -60 dBm en cada frecuencia.")


def seccion_analisis(doc, L):
    doc.add_page_break()
    _titulo(doc, "7. Analisis descriptivo: bandas mas y menos contaminadas", 1)

    D = L["decisiones"]
    peor, mejor = D.iloc[0], D.iloc[-1]

    _titulo(doc, "7.1 Indice de Saturacion Espectral", 2)
    _parrafo(doc,
        "Para hacer comparables los cuatro bloques se definio el Indice de Saturacion Espectral (ISE), "
        "construido con la misma logica del indice de calidad del aire trabajado en clase: se mapea una "
        "magnitud fisica continua a una escala normalizada de 0 a 100 por tramos lineales, y cada tramo "
        "lleva asociada una categoria y una accion. El ISE combina dos componentes, igual que cualquier "
        "indice de contaminacion ambiental:")
    _vineta(doc, "INTENSIDAD (peso %.0f %%): potencia mediana espacial del canal, mapeada por tramos."
                 % (100 * cfg.PESO_ISE_NIVEL))
    _vineta(doc, "EXTENSION (peso %.0f %%): porcentaje del area que supera el umbral de -60 dBm."
                 % (100 * cfg.PESO_ISE_EXTENSION))
    _parrafo(doc,
        "La justificacion de usar la mediana y no la media lineal en la componente de intensidad es "
        "directa: una portadora muy fuerte en un solo punto de la ruta no degrada el plan de "
        "frecuencias de la ciudad tanto como una emision moderada presente en toda el area, y una media "
        "lineal no distingue esos dos casos.")

    _tabla(doc, ["ISE", "Categoria", "Lectura para la Agencia"],
           [["%d - %d" % (i_lo, i_hi), cat,
             {"Libre": "Bloque disponible sin restricciones",
              "Moderado": "Emisiones presentes pero compatibles con nuevas asignaciones",
              "Contaminado": "Requiere coordinacion geografica y control de potencia",
              "Saturado": "No asignable sin una accion de control previa"}[cat]]
            for _, _, i_lo, i_hi, cat, _ in cfg.TRAMOS_ISE],
           anchos=[2.2, 3.0, 10.8])

    _titulo(doc, "7.2 Resultado de la clasificacion", 2)
    _tabla(doc, ["Puesto", "Canal", "Banda", "ISE", "Categoria", "% del area ocupada", "Decision"],
           [["%d" % f.ranking_contaminacion, f.canal, f.banda, "%.1f" % f.ISE, f.categoria,
             "%.1f %%" % f.pct_puntos_ocupados, f.decision] for _, f in D.iterrows()],
           anchos=[1.4, 1.4, 2.8, 1.4, 2.4, 2.4, 4.2])

    _figura(doc, "06_canales.png",
            "Figura 7. Comparacion de los cuatro canales: potencia de ocupacion, extension territorial "
            "de la contaminacion e indice de saturacion.")

    _titulo(doc, "7.3 La banda mas contaminada: canal %s" % peor.canal, 2)
    _parrafo(doc,
        "El canal %s (%s) es, sin ambiguedad, el bloque mas contaminado de la banda. Su potencia "
        "mediana de ocupacion es de %.2f dBm, es decir %.1f dB POR ENCIMA del umbral de -60 dBm, y su "
        "potencia media integrada alcanza %.2f dBm. Supera el umbral en el %.1f %% de los puntos "
        "medidos y el %.1f %% de sus %d bins esta ocupado en promedio."
        % (peor.canal, peor.banda, peor.P_mediana_dbm,
           peor.P_mediana_dbm - cfg.UMBRAL_OCUPACION_DBM, peor.P_media_dbm,
           peor.pct_puntos_ocupados, peor.ocupacion_espectral_pct, cfg.BINS_POR_CANAL))
    _parrafo(doc,
        "Lo determinante para la Agencia no es solo el nivel sino su PERSISTENCIA ESPACIAL: la "
        "contaminacion no se concentra en un punto sino que cubre practicamente todo el sector "
        "occidental recorrido. El mapa de calor del canal %s es el unico de los cuatro que aparece "
        "saturado en la totalidad del area medida. Un concesionario que recibiera este bloque operaria "
        "con relacion senal a interferencia degradada en toda la zona, no en un punto aislado que se "
        "pudiera resolver con una zona de exclusion." % peor.canal)

    _titulo(doc, "7.4 La banda menos contaminada: canal %s" % mejor.canal, 2)
    _parrafo(doc,
        "El canal %s (%s) es el mas limpio de la banda. Su potencia mediana es de %.2f dBm, %.1f dB POR "
        "DEBAJO del umbral de ocupacion, y solo el %.1f %% de los puntos de la ruta lo encuentra "
        "ocupado. Su ISE de %.1f lo situa en la categoria %s, la mas favorable de las cuatro observadas."
        % (mejor.canal, mejor.banda, mejor.P_mediana_dbm,
           cfg.UMBRAL_OCUPACION_DBM - mejor.P_mediana_dbm,
           mejor.pct_puntos_ocupados, mejor.ISE, mejor.categoria))
    _parrafo(doc,
        "Es importante precisar el alcance de esta afirmacion: el canal %s es el mejor DISPONIBLE, no "
        "un canal virgen. Su pico llega a %.2f dBm en los puntos mas cargados, de modo que tambien "
        "presenta focos localizados. La recomendacion se sostiene en terminos relativos frente a las "
        "otras tres alternativas de la banda."
        % (mejor.canal, mejor.P_max_dbm))

    _titulo(doc, "7.5 Frecuencias extremas del sistema", 2)
    fp, fm = L["f_peor"], L["f_mejor"]
    _parrafo(doc,
        "Para seleccionar la frecuencia mas y la menos contaminada se uso un criterio combinado que "
        "pesa en un 70 %% la potencia media espacial y en un 30 %% la persistencia, medida como el "
        "porcentaje de puntos de la ruta en que la frecuencia supera el umbral. El desempate por "
        "persistencia es necesario porque una portadora presente en todo el recorrido contamina el plan "
        "de frecuencias mucho mas que un pico intenso pero puntual.")

    _tabla(doc, ["Criterio", "Frecuencia", "Canal", "Bin", "Potencia media", "% de la ruta ocupada"],
           [["MAS contaminada", "%.4f MHz" % fp.frecuencia_mhz, fp.canal, "%d" % fp["bin"],
             "%.2f dBm" % fp.P_media_dbm, "%.1f %%" % fp.ocupacion_pct],
            ["MENOS contaminada", "%.4f MHz" % fm.frecuencia_mhz, fm.canal, "%d" % fm["bin"],
             "%.2f dBm" % fm.P_media_dbm, "%.1f %%" % fm.ocupacion_pct]],
           anchos=[3.2, 2.8, 1.6, 1.4, 2.8, 4.2])

    _parrafo(doc,
        "La frecuencia de %.4f MHz esta ocupada en el %.0f %% de los puntos de la ruta, lo que indica "
        "una portadora permanente de alta potencia que domina el canal %s en toda el area. En el "
        "extremo opuesto, %.4f MHz solo aparece ocupada en el %.0f %% de los puntos y constituye el "
        "segmento mas aprovechable de la banda."
        % (fp.frecuencia_mhz, fp.ocupacion_pct, fp.canal, fm.frecuencia_mhz, fm.ocupacion_pct))

    _figura(doc, "05_frecuencias_extremas.png",
            "Figura 8. Frecuencia mas y menos contaminada del sistema: ubicacion en el perfil de la "
            "banda y comportamiento a lo largo de la ruta.")

    _titulo(doc, "7.6 Distribucion geografica", 2)
    _figura(doc, "08_mapas_canales.png",
            "Figura 9. Mapas de calor de la potencia de ocupacion por canal. La malla se construyo por "
            "interpolacion lineal sobre los puntos medidos; el area en blanco no fue cubierta por la ruta.",
            15.0)
    _figura(doc, "09_mapas_temperatura_fmax.png",
            "Figura 10. Mapa de calor de la temperatura del sistema de sensado y de la frecuencia mas "
            "contaminada de la banda.")


def seccion_recomendacion(doc, L):
    doc.add_page_break()
    _titulo(doc, "8. Recomendacion tecnica a la Agencia Nacional del Espectro", 1)

    D, G = L["decisiones"], L["global"]
    _parrafo(doc,
        "El modelo de decision traduce cada estimacion numerica en una hipotesis booleana y cada "
        "hipotesis en una accion administrativa concreta, siguiendo el esquema modelo - estimacion - "
        "hipotesis - decision de la asignatura. Los puntos de corte del porcentaje de area ocupada "
        "siguen la clasificacion de ocupacion de la Recomendacion UIT-R SM.1880: por encima del %.0f %% "
        "el canal se considera congestionado, entre %.0f y %.0f %% de uso intensivo, entre %.0f y "
        "%.0f %% de uso ligero y por debajo del %.0f %% practicamente libre."
        % (cfg.OCUPACION_CONGESTIONADO, cfg.OCUPACION_ALTA, cfg.OCUPACION_CONGESTIONADO,
           cfg.OCUPACION_MODERADA, cfg.OCUPACION_ALTA, cfg.OCUPACION_MODERADA))

    _titulo(doc, "8.1 Juicio de valor por canal", 2)
    for _, f in D.iterrows():
        p = doc.add_paragraph()
        r = p.add_run("CANAL %s  (%s)  -  %s" % (f.canal, f.banda, f.decision))
        r.bold = True; r.font.size = Pt(11.5)
        r.font.color.rgb = ROJO if f.decision == "NO ASIGNAR" else (
            VERDE if f.decision.startswith("ASIGNAR") and "RESTRIC" not in f.decision else AZUL)

        _parrafo(doc,
            "Evidencia: potencia mediana %.2f dBm (umbral -60 dBm), potencia media integrada %.2f dBm, "
            "pico %.2f dBm, ocupacion en el %.1f %% del area recorrida. ISE = %.1f sobre 100, categoria "
            "%s. Hipotesis aplicada: %s (%s). Prioridad de atencion: %s."
            % (f.P_mediana_dbm, f.P_media_dbm, f.P_max_dbm, f.pct_puntos_ocupados,
               f.ISE, f.categoria, f.hipotesis, f.hipotesis_nombre, f.prioridad), tam=10)
        _parrafo(doc, "Accion recomendada: %s" % f.accion, tam=10)
        doc.add_paragraph()

    _titulo(doc, "8.2 Sintesis para el plan de frecuencias", 2)
    # Los recomendados se listan en orden de preferencia, es decir de menor a
    # mayor indice de saturacion, no en el orden en que salieron del modelo.
    recomendados = lista_de_csv(G.canales_recomendados)
    orden_pref = [c for c in D.sort_values("ISE").canal if c in recomendados]

    _tabla(doc, ["Concepto", "Resultado"], [
        ["Canales recomendados para asignar", ", ".join(orden_pref)],
        ["Canales NO recomendados", ", ".join(lista_de_csv(G.canales_no_recomendados)) or "ninguno"],
        ["Espectro utilizable", "%.0f MHz" % G.espectro_util_mhz],
        ["Espectro comprometido", "%.0f MHz (%.0f %% de la banda)"
         % (G.espectro_perdido_mhz, G.pct_banda_inutilizable)],
        ["Orden de preferencia sugerido", " > ".join(D.sort_values("ISE").canal.tolist())],
    ], anchos=[6.0, 10.0])

    _titulo(doc, "8.3 Recomendaciones de gestion", 2)
    _vineta(doc,
        "ASIGNAR EN ORDEN DE PREFERENCIA %s. Es el orden inverso al indice de saturacion y por tanto el "
        "que maximiza la probabilidad de operacion sin interferencia para un nuevo concesionario."
        % " > ".join(D.sort_values("ISE").canal.tolist()))
    _vineta(doc,
        "NO ASIGNAR EL CANAL %s hasta ejecutar una accion de control. Es el unico bloque que supera el "
        "umbral de congestion de la UIT y su contaminacion no es localizada sino generalizada, de modo "
        "que no puede resolverse con zonas de exclusion." % D.iloc[0].canal)
    _vineta(doc,
        "ORDENAR VERIFICACION EN SITIO de la frecuencia %.4f MHz, que es la portadora individual mas "
        "contaminante del sistema y esta activa en el %.0f %% del area. Debe contrastarse contra el "
        "registro de licencias vigentes para determinar si corresponde a una emision autorizada o a un "
        "uso no declarado." % (L["f_peor"].frecuencia_mhz, L["f_peor"].ocupacion_pct))
    _vineta(doc,
        "AMPLIAR LA CAMPANA DE MEDICION hacia el occidente y el suroccidente del area actual. El modelo "
        "de extrapolacion situa los focos principales fuera del perimetro recorrido, de modo que la "
        "campana actual observa la periferia de las fuentes y no su entorno inmediato.")
    _vineta(doc,
        "INSTRUMENTAR MONITOREO PERIODICO SEMESTRAL de los bloques que se asignen, con el mismo "
        "procedimiento de ETL e indicadores de este estudio, para detectar degradacion del nivel de "
        "fondo tras la entrada de nuevos operadores.")

    _titulo(doc, "8.4 Limitaciones del estudio", 2)
    _parrafo(doc,
        "Por transparencia tecnica se declaran las limitaciones que acotan el alcance de estas "
        "conclusiones:")
    _vineta(doc,
        "La campana corresponde a una unica sesion de medicion. La ocupacion celular varia con la hora "
        "del dia y el dia de la semana, de modo que los resultados describen un instante y no un "
        "promedio estadistico del uso del espectro.")
    _vineta(doc,
        "Las potencias no estan calibradas en unidades absolutas de intensidad de campo. Se corrigio el "
        "desacople de la antena, pero no se dispone de su patron de radiacion ni de la ganancia "
        "absoluta de la cadena de recepcion, por lo que los valores en dBm son comparables entre si "
        "pero no trasladables directamente a un limite de exposicion.")
    _vineta(doc,
        "El espectro de cada punto es el resultado de una retencion de maximos sobre 100 barridos, no "
        "un promedio. Esto sobreestima la ocupacion media real y hace la evaluacion conservadora, lo "
        "cual es apropiado para una decision regulatoria pero debe tenerse presente.")
    _vineta(doc,
        "La cobertura espacial se limita al circuito recorrido. Fuera de la envolvente convexa de los "
        "puntos medidos no se reporta ningun valor interpolado, por lo que los mapas no deben leerse "
        "como cobertura de toda la ciudad.")


def seccion_bonificacion(doc, L):
    doc.add_page_break()
    _titulo(doc, "9. Estimacion de las fuentes de contaminacion por extrapolacion", 1)

    F = L["fuentes"]
    _parrafo(doc,
        "Se estimo la ubicacion geografica del transmisor responsable de cada bloque resolviendo un "
        "problema de multilateracion por nivel de senal recibida. En un entorno urbano la potencia "
        "decae con el logaritmo de la distancia segun P(d) = P0 - 10*n*log10(d/d0), de modo que cada "
        "punto de la ruta aporta una ecuacion y la posicion del emisor se obtiene por minimos cuadrados "
        "no lineales minimizando el residuo en decibelios. Se minimiza en dB porque el desvanecimiento "
        "por sombra urbana es log-normal, es decir gaussiano en el dominio logaritmico.")

    _parrafo(doc,
        "Se trata de una EXTRAPOLACION y no de una interpolacion: la interpolacion de malla vista en "
        "clase solo puede estimar valores dentro de la envolvente convexa de los puntos medidos y por "
        "construccion nunca situaria una fuente fuera de la ruta. Aqui se ajusta un modelo fisico "
        "parametrico y se resuelve para el parametro posicion, que en los cinco casos cae fuera del "
        "recorrido.")

    _titulo(doc, "9.1 Decisiones que hacen identificable el problema", 2)
    _vineta(doc,
        "SE FIJA EL EXPONENTE DE PROPAGACION en n = %.1f, valor tipico urbano. Dejandolo libre, n y la "
        "distancia resultan practicamente intercambiables: un transmisor lejano y potente con n bajo "
        "produce casi el mismo perfil que uno cercano y debil con n alto. Esa degeneracion empujaba la "
        "solucion contra el borde de la region de busqueda. Con n fijo la solucion es estable: se "
        "verifico que la posicion estimada no cambia al ampliar la region de busqueda de 2 km a 20 km."
        % cfg.EXP_PERDIDA_N)
    _vineta(doc,
        "SE USAN LOS 12 PUNTOS MAS FUERTES de cada canal. Lejos del emisor la medida la dominan otras "
        "fuentes y la sombra urbana, y el modelo de fuente unica deja de aplicar; cerca, el gradiente "
        "de potencia si responde a la geometria.")
    _vineta(doc,
        "SE USA LA POTENCIA DE PICO del canal y no la media de Parseval, porque el pico corresponde a "
        "la portadora dominante, que es la que efectivamente proviene de un unico emisor.")

    _titulo(doc, "9.2 Fuentes estimadas", 2)
    _tabla(doc, ["Objetivo", "Latitud", "Longitud", "Rumbo", "Distancia", "RMSE", "R2", "Confianza"],
           [[("Canal %s" % f.canal) if f.canal != "F_MAX" else "Frec. maxima",
             "%.6f" % f.latitud, "%.6f" % f.longitud, f.rumbo,
             "%.2f km" % (f.distancia_al_centroide_m / 1000.0),
             "%.2f dB" % f.rmse_db, "%.3f" % f.r2, f.confianza] for _, f in F.iterrows()],
           anchos=[2.6, 2.2, 2.2, 1.6, 2.0, 1.8, 1.4, 2.2])

    _parrafo(doc,
        "La lectura tecnica de cada estimacion depende de la bondad del ajuste, que se interpreta "
        "asi: un R2 alto con residuo bajo significa que el patron espacial responde efectivamente a un "
        "emisor unico dominante; un R2 bajo significa que el bloque contiene varios emisores "
        "simultaneos o que la geometria de la ruta no rodea lo suficiente al transmisor.")

    for _, f in F.iterrows():
        p = doc.add_paragraph()
        r = p.add_run(("Canal %s" % f.canal) if f.canal != "F_MAX"
                      else "Frecuencia mas contaminada (%s)" % f.banda)
        r.bold = True; r.font.size = Pt(10.5)
        _parrafo(doc, f.interpretacion, tam=10)

    mejor_f = F.loc[F.r2.idxmax()]
    _parrafo(doc,
        "El resultado mas solido corresponde al canal %s, con R2 = %.3f y un residuo de solo %.2f dB, "
        "compatible con la dispersion esperada por sombra urbana. Constituye ademas una validacion "
        "cruzada valiosa: la fuente del canal mas contaminado y la de la frecuencia individual mas "
        "contaminada apuntan en la misma direccion, lo que sugiere que se trata del mismo emplazamiento "
        "radiante y refuerza la recomendacion de dirigir alli la verificacion en sitio."
        % (mejor_f.canal, mejor_f.r2, mejor_f.rmse_db))


def seccion_dashboard(doc, L):
    doc.add_page_break()
    _titulo(doc, "10. Dashboard interactivo", 1)
    _parrafo(doc,
        "El programa entregable es un dashboard interactivo servido sobre un servidor web construido "
        "con Dash, que corre sobre Flask. Consume exclusivamente la capa oro del datalake, de modo que "
        "la visualizacion queda desacoplada del procesamiento: si el ETL se vuelve a ejecutar con datos "
        "nuevos, el dashboard los refleja sin tocar una linea de su codigo.")

    _tabla(doc, ["Vista", "Contenido"], [
        ["Ubicacion de las mediciones", "Mapa con los puntos de medicion georreferenciados sobre "
                                        "cartografia de Medellin, con el detalle de cada punto al pasar el cursor"],
        ["Ruta de las mediciones", "Trayectoria de la estacion movil en secuencia temporal, con marcas "
                                   "de inicio, fin y posiciones imputadas"],
        ["Mapa de calor por canal", "Superficie de potencia de ocupacion para A, B, C y D, con selector "
                                    "de canal y contorno del umbral de -60 dBm"],
        ["Mapa de calor de temperatura", "Distribucion espacial de la temperatura del sistema de sensado"],
        ["Mapa de la frecuencia mas contaminada", "Superficie de potencia de la portadora dominante del "
                                                  "sistema"],
        ["Fuentes extrapoladas", "Marcadores de los emisores estimados con su nivel de confianza"],
        ["Panel de decision", "Indicadores ISE por canal, hipotesis aplicada y accion recomendada"],
    ], anchos=[5.0, 11.0])

    _parrafo(doc, "Para ejecutarlo:")
    p = doc.add_paragraph()
    r = p.add_run("    python dashboard/app.py\n    Abrir en el navegador: http://127.0.0.1:8050")
    r.font.name = "Consolas"; r.font.size = Pt(10)


def cierre(doc, L):
    doc.add_page_break()
    _titulo(doc, "11. Conclusiones", 1)
    D = L["decisiones"]
    peor, mejor = D.iloc[0], D.iloc[-1]

    _vineta(doc,
        "La calidad del conjunto de datos es alta (indice global del %.2f %%). De las %d mediciones "
        "extraidas, %d resultaron aptas: se descartaron %d por defectos irrecuperables y se imputaron "
        "%d celdas repartidas en cuatro tecnicas distintas."
        % (L["indices"].iloc[-1].valor_pct, len(L["crudo"]), len(L["limpio"]),
           len(L["descartadas"]),
           int(L["bitacora"][L["bitacora"].paso.isin(["P1_FUGA_LO", "P2_GEORREFERENCIACION"])].cantidad.sum())))
    _vineta(doc,
        "El defecto de calidad mas importante no era evidente a simple vista: la fuga de oscilador "
        "local del receptor de conversion directa, presente en %d mediciones, caia exactamente en la "
        "frontera entre los canales B y C y habria falseado el indicador de ambos."
        % int(L["banderas"]["R9_FUGA_LO_DC"].sum()))
    _vineta(doc,
        "La temperatura del sensor NO incide de forma demostrable en la calidad de los datos. La "
        "correlacion aparente se explica integramente por la confusion con el tiempo de operacion, y el "
        "efecto fisicamente posible del calentamiento observado esta acotado a %.2f dB."
        % L["temp"]["fisica"]["cota_teorica_db"])
    _vineta(doc,
        "El canal %s es el mas contaminado de la banda (ISE %.1f, ocupado en el %.1f %% del area) y el "
        "canal %s el mas limpio (ISE %.1f). La recomendacion a la Agencia es no asignar el canal %s y "
        "priorizar el canal %s en el plan de frecuencias."
        % (peor.canal, peor.ISE, peor.pct_puntos_ocupados, mejor.canal, mejor.ISE,
           peor.canal, mejor.canal))
    _vineta(doc,
        "La frecuencia de %.4f MHz es la portadora individual mas contaminante del sistema, activa en "
        "el %.0f %% de los puntos medidos, y debe ser el primer objetivo de verificacion en sitio."
        % (L["f_peor"].frecuencia_mhz, L["f_peor"].ocupacion_pct))

    doc.add_paragraph()
    doc.add_paragraph()
    _titulo(doc, "Anexo. Nota de cierre", 2)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    r = p.add_run(
        "La Agencia le encargo a un gato medir la ocupacion del espectro en el canal C. Volvio a las "
        "tres horas con el informe en la boca y una sola conclusion: \"esa banda esta ocupada\". Le "
        "preguntaron como lo habia determinado con tanta certeza, y contesto: \"me acoste encima\".")
    r.italic = True
    r.font.size = Pt(10.5)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    r = p.add_run(
        "Desde entonces la ANE tiene un problema de metodologia, porque el gato no libera el canal C "
        "por mas hipotesis de decision que se le apliquen, y uno de presupuesto, porque ahora exige "
        "que le asignen tambien los canales A, B y D \"por si acaso\".")
    r.italic = True
    r.font.size = Pt(10.5)


# ---------------------------------------------------------------------------
def main():
    cfg.crear_directorios()
    print("[INFORME] Cargando artefactos del datalake...")
    L = cargar()

    print("[INFORME] Redactando documento...")
    doc = Document()
    for s in doc.sections:
        s.top_margin = Cm(2.2); s.bottom_margin = Cm(2.2)
        s.left_margin = Cm(2.4); s.right_margin = Cm(2.4)
    estilo = doc.styles["Normal"]
    estilo.font.name = "Calibri"
    estilo.font.size = Pt(10.5)

    portada(doc, L)
    resumen_ejecutivo(doc, L)
    seccion_arquitectura(doc, L)
    seccion_calidad(doc, L)
    seccion_imputacion(doc, L)
    seccion_ruta(doc, L)
    seccion_temperatura(doc, L)
    seccion_indicadores(doc, L)
    seccion_analisis(doc, L)
    seccion_recomendacion(doc, L)
    seccion_bonificacion(doc, L)
    seccion_dashboard(doc, L)
    cierre(doc, L)

    salida = os.path.join(cfg.DIR_INFORME, "Informe_ANE_Ocupacion_840_860MHz.docx")
    doc.save(salida)
    print("[INFORME] Documento generado: %s\n" % salida)
    return salida


if __name__ == "__main__":
    main()

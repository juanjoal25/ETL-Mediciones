# -*- coding: utf-8 -*-
"""
run_pipeline.py - ORQUESTADOR DEL PROCESO COMPLETO

Ejecuta de principio a fin el estudio de ocupacion espectral:

    EXTRACCION -> CALIDAD -> TRANSFORMACION -> INDICADORES
                                                    |
                          +-------------------------+
                          |
             MODELO DE DECISION + EXTRAPOLACION DE FUENTES
                          |
                    FIGURAS -> INFORME EN WORD

Uso:
    python run_pipeline.py              ejecuta todas las etapas
    python run_pipeline.py --sin-informe   omite figuras e informe (mas rapido)

Al terminar, el dashboard se levanta con:
    python dashboard/app.py
"""

import os
import sys
import time
import traceback

RAIZ = os.path.dirname(os.path.abspath(__file__))
for sub in ("etl", "modelo", "informe"):
    sys.path.insert(0, os.path.join(RAIZ, sub))


def _etapa(numero, titulo, funcion):
    """Ejecuta una etapa del pipeline midiendo su duracion y capturando fallos."""
    print("\n" + "=" * 78)
    print(" ETAPA %d - %s" % (numero, titulo))
    print("=" * 78)
    t0 = time.time()
    try:
        resultado = funcion()
        print("  [OK] etapa completada en %.1f s" % (time.time() - t0))
        return resultado
    except Exception:
        print("  [FALLO] la etapa no pudo completarse:")
        traceback.print_exc()
        raise


def main(con_informe=True):
    import config as cfg
    import extract, quality, transform, indicators, temperatura
    import decision, extrapolacion

    cfg.crear_directorios()

    print("\n" + "#" * 78)
    print("#  ESTUDIO TECNICO DE OCUPACION ESPECTRAL 840 - 860 MHz")
    print("#  Agencia Nacional del Espectro  |  Sector occidental de Medellin")
    print("#" * 78)

    t0 = time.time()
    _etapa(1, "EXTRACCION (capa bronce)", extract.main)
    _etapa(2, "PERFILADO DE CALIDAD", quality.main)
    _etapa(3, "TRANSFORMACION E IMPUTACION (capa plata)", transform.main)
    _etapa(4, "INDICADORES DE PARSEVAL (capa oro)", indicators.main)
    _etapa(5, "ANALISIS DE INCIDENCIA TERMICA", temperatura.main)
    _etapa(6, "MODELO DE TOMA DE DECISIONES", decision.main)
    _etapa(7, "EXTRAPOLACION DE FUENTES (bonificacion)", extrapolacion.main)

    if con_informe:
        import figuras, generar_informe
        _etapa(8, "GENERACION DE FIGURAS", figuras.generar_todas)
        _etapa(9, "INFORME TECNICO EN WORD", generar_informe.main)

    print("\n" + "#" * 78)
    print("#  PIPELINE COMPLETADO EN %.1f s" % (time.time() - t0))
    print("#")
    print("#  Datalake  : %s" % cfg.DIR_LAKE)
    if con_informe:
        print("#  Informe   : %s" % os.path.join(cfg.DIR_INFORME,
                                                 "Informe_ANE_Ocupacion_840_860MHz.docx"))
        print("#  Figuras   : %s" % cfg.DIR_FIGURAS)
    print("#")
    print("#  Para levantar el dashboard:   python dashboard/app.py")
    print("#  Luego abrir:                  http://127.0.0.1:8050")
    print("#" * 78 + "\n")


if __name__ == "__main__":
    main(con_informe="--sin-informe" not in sys.argv)

"""
Pone al dia docs/*.md distinguiendo documento VIVO de registro FECHADO.

El criterio
-----------
No todos los .md se tratan igual, por la misma razon por la que en el informe
de titulo el 49,9 % de septiembre se conserva: reescribir una cifra dentro de
un documento con fecha de emision lo falsea.

  VIVO    describe el sistema actual y no lleva fecha  -> se corrige el texto.
  FECHADO lleva fecha de emision o es el registro de una decision pasada
          -> se le pone un aviso arriba y una marca en cada afirmacion
             superada, pero NO se reescribe el cuerpo.

Se escriben solo hechos ESTRUCTURALES (cuantos detectores, cuantos cabezales,
que clasificador). Los KPI no se copian aqui: viven en
reports/MEJORA_ENSEMBLE_v4.md, que declara la procedencia de cada cifra.
Duplicarlos crearia otra copia que envejece.

Uso:  python scripts/actualizar_docs_internos.py [--aplicar]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

FUENTE = "reports/MEJORA_ENSEMBLE_v4.md"

AVISO = """
> ### ⚠ Estado del documento — revisado el 9 de noviembre de 2026
>
> Este documento conserva su contenido original con fecha. Describe el sistema
> tal como era, y partes de su descripcion del meta-ensemble han quedado
> superadas. Lo que cambio, en terminos estructurales:
>
> | Lo que dice el documento | Lo vigente |
> |---|---|
> | Meta-clasificador XGBoost unico | **Tres cabezales**: `full` y `noart` son **regresion logistica**; solo el cabezal facial es XGBoost |
> | Temperatura T=0.581 | Umbral de produccion **0.8764** (cabezal `full`); cada cabezal tiene el suyo |
> | 5 modelos de vision | **Seis** detectores (A ViT, B sdxl-detector, C probe CLIP ViT-L/14, D detector de arte IA, E SigLIP2, F umm-maybe) |
> | El meta usa 3 features | El cabezal `full` usa **7** |
>
> Las metricas vigentes, cada una con su procedencia declarada (dentro o fuera
> de muestra), estan en [`%s`](../%s). No se copian aqui para no crear otra
> copia que envejezca.
""" % (FUENTE, FUENTE)

# (archivo, trato)
TRATO = {
    "ESTRUCTURA_PROYECTO.md": "vivo",
    "INFORME_TECNICO_DEEPGUARD_AI.md": "fechado",
    "TESIS_AUDITORIA_TECNICA_DEEPGUARD_AI.md": "fechado",
    "REPORTE_SEGURIDAD_Y_CAMBIOS.md": "fechado",
    "REPORT_NEXT_GEN_UPGRADE.md": "fechado",
    "INFORME_CAMBIOS_IMPLEMENTADOS.md": "fechado",
}

# Correcciones en el documento VIVO: (viejo, nuevo)
VIVO_SUBS = [
    ("# 5 modelos ensemble (ViT, SDXL, CLIP, AiArt, SigLIP)",
     "# 6 detectores (ViT, SDXL, probe CLIP, AiArt, SigLIP2, umm-maybe)"),
    ("# XGBoost + Temperature Scaling (T=0.581)",
     "# 3 cabezales: full/noart logreg + face XGBoost"),
    ("| Meta-ensemble | XGBoost + T-Scaling (T=0.581) | 2.x |",
     "| Meta-ensemble | 3 cabezales (full/noart logreg, face XGBoost), umbral 0.8764 | 2.x |"),
]

# Marcas en linea para los documentos FECHADOS: (archivo, ancla, marca)
MARCA = " <!-- SUPERADO nov-2026: ver reports/MEJORA_ENSEMBLE_v4.md -->"
EN_LINEA = [
    ("INFORME_TECNICO_DEEPGUARD_AI.md",
     "El corazón del sistema es un **meta-ensemble** XGBoost que combina las predicciones de cinco modelos de Deep Learning",
     "\n\n> **[Superado en noviembre de 2026]** El meta-ensemble tiene ahora tres\n"
     "> cabezales: `full` y `noart` son regresion logistica y solo el cabezal\n"
     "> facial es XGBoost. Los detectores son seis, no cinco. Ver\n"
     "> `reports/MEJORA_ENSEMBLE_v4.md`.\n"),
    ("INFORME_TECNICO_DEEPGUARD_AI.md",
     "Sobre los scores del ensemble opera un **XGBoost** (profundidad=2, regularización L2) con **Temperature Scaling** calibrado a T=0.581",
     "\n\n> **[Superado en noviembre de 2026]** El cabezal principal es una\n"
     "> regresion logistica con umbral de produccion 0.8764. Ver\n"
     "> `reports/MEJORA_ENSEMBLE_v4.md`.\n"),
    ("TESIS_AUDITORIA_TECNICA_DEEPGUARD_AI.md",
     "1. Reentrenar el meta-ensemble XGBoost incorporando las 8-9 señales completas (en vez de solo 3), evaluando si el \"Consensus Override\" manual puede simplificarse o eliminarse con un modelo mejor calibrado.",
     "\n\n> **[Ejecutado en noviembre de 2026]** Esta recomendacion se llevo a cabo.\n"
     "> El cabezal principal paso de 3 a 7 features y de XGBoost a regresion\n"
     "> logistica, elegida por su error leave-one-source-out y no por su ajuste.\n"
     "> El detalle y las mediciones estan en `reports/MEJORA_ENSEMBLE_v4.md`.\n"),
]

# Sustituciones DENTRO de una celda de tabla de un documento fechado. Una fila
# no admite un bloque de cita, y un comentario HTML tras el pipe cae en la
# celda siguiente sin decirle nada al lector. Aqui se cierra el circulo en el
# propio texto de la celda.
EN_CELDA = [
    ("TESIS_AUDITORIA_TECNICA_DEEPGUARD_AI.md",
     "Métrica F1=94.7% del informe técnico final no es trazable a ningún "
     "benchmark documentado",
     "Métrica F1=94.7% del informe técnico final no es trazable a ningún "
     "benchmark documentado — **confirmado y resuelto en noviembre de 2026**: "
     "ese 94,7 % se calculaba sobre el cabezal facial aislado y no sobre el "
     "sistema, que mezcla ese cabezal con el track completo; medido por la via "
     "de produccion daba un 11 %. Ver `reports/MEJORA_ENSEMBLE_v4.md` §4.1"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true")
    args = ap.parse_args()
    cambios = 0

    for nombre, trato in TRATO.items():
        p = DOCS / nombre
        if not p.exists():
            print(f"  FALTA  {nombre}")
            continue
        texto = p.read_text(encoding="utf-8")
        original = texto

        if trato == "vivo":
            for viejo, nuevo in VIVO_SUBS:
                if viejo in texto:
                    texto = texto.replace(viejo, nuevo)
                    print(f"  corregido  {nombre}: {viejo[:46]}...")
                    cambios += 1
                else:
                    print(f"  SIN HALLAR {nombre}: {viejo[:46]}...")
        else:
            if "Estado del documento — revisado el 9 de noviembre" in texto:
                print(f"  ya avisado {nombre}")
            else:
                # El aviso va tras el titulo H1 y su subtitulo, antes del cuerpo
                lineas = texto.split("\n")
                corte = 1
                while corte < len(lineas) and (
                        lineas[corte].startswith("#")
                        or lineas[corte].strip() == ""
                        or lineas[corte].startswith("**")):
                    corte += 1
                lineas.insert(corte, AVISO)
                texto = "\n".join(lineas)
                print(f"  aviso      {nombre}")
                cambios += 1

        for arch, ancla, nota in EN_LINEA:
            if arch != nombre:
                continue
            if ancla not in texto:
                print(f"  SIN HALLAR {nombre}: ancla {ancla[:42]}...")
                continue
            if MARCA in texto[texto.index(ancla):texto.index(ancla) + len(ancla) + 120]:
                print(f"  ya marcado {nombre}: {ancla[:42]}...")
                continue
            reemplazo = ancla + MARCA + nota
            texto = texto.replace(ancla, reemplazo, 1)
            print(f"  marcado    {nombre}: {ancla[:42]}...")
            cambios += 1

        for arch, viejo_c, nuevo_c in EN_CELDA:
            if arch != nombre:
                continue
            if nuevo_c in texto:
                print(f"  ya cerrado {nombre}: {viejo_c[:42]}...")
            elif viejo_c in texto:
                texto = texto.replace(viejo_c, nuevo_c, 1)
                print(f"  cerrado    {nombre}: {viejo_c[:42]}...")
                cambios += 1
            else:
                print(f"  SIN HALLAR {nombre}: celda {viejo_c[:38]}...")

        if args.aplicar and texto != original:
            p.write_text(texto, encoding="utf-8")

    print(f"\n  {cambios} cambios"
          f"{'' if args.aplicar else ' (SIMULACION — usa --aplicar)'}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())

"""
Reescribe las tablas de los entregables que no se arreglan sustituyendo cifras.

Diferencia con scripts/actualizar_cifras_entregables.py
-------------------------------------------------------
Aquel cambia una cifra por otra dentro de un `run`, que es lo correcto cuando
el texto alrededor sigue siendo verdad. Hay dos tablas donde no basta:

  INFORME, tabla 40 — composicion del conjunto de datos
      Declara seis fuentes y 14.000 imagenes. El conjunto actual tiene nueve
      fuentes y 60.000. No es una cifra equivocada: faltan filas.

  INFORME, tabla 5 — progresion de configuraciones
      Las tres filas son la historia del proyecto: pesos fijos (0,1 %), meta
      con arte IA incluido (6,4 %), meta con arte IA separado (49,9 %).
      Sobreescribir la ultima borraria el hito de septiembre. Lo que
      corresponde es ANADIR la configuracion de noviembre, porque la
      progresion 0,1 -> 6,4 -> 49,9 -> 94,0 dice mas que cualquier cifra
      suelta.

Como anade filas sin romper el formato
--------------------------------------
`table.add_row()` crea una fila con el estilo de la tabla pero pierde el
formato propio de las celdas (sombreado, bordes, tipografia de la fila). Aqui
se copia el XML de una fila existente que sirva de modelo y se reemplaza el
texto de sus celdas, de modo que la fila nueva es indistinguible de sus
vecinas.

Seguridad
---------
Sin --aplicar no escribe nada: vuelca el resultado en un archivo aparte con
sufijo .PRUEBA.docx para poder revisarlo. Con --aplicar deja respaldo con sello
de tiempo, igual que el otro script.

Uso
---
    python scripts/actualizar_tablas_entregables.py            # simulacion
    python scripts/actualizar_tablas_entregables.py --aplicar  # escribe
"""
import argparse
import copy
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INFORME = (ROOT / "evaluacion 2 proyecto de tituulo"
           / "TIHI84_U2_ES2_InformeDeepScan_RojasLiapiz.docx")

# ── tabla 40: composicion del conjunto de entrenamiento y validacion ─────────
# Tomado de scripts/score_dataset_v2.py (PLAN) y confirmado contra el recuento
# real de reports/dataset_v2_scores.csv.
FUENTES = [
    ("COCO train2017",        "Auténtico", "Fotografía natural de escenas diversas",             "12.000"),
    ("CelebA",                "Auténtico", "Retratos fotográficos de prensa",                     "7.000"),
    ("FaceForensics++ real",  "Auténtico", "Fotogramas de video comprimido con rostros",          "7.000"),
    ("COCO val2017",          "Auténtico", "Fotografía natural, partición independiente",         "4.000"),
    ("ELSA multigenerador",   "Sintético", "Difusión latente de varios generadores",             "14.000"),
    ("DiffusionDB",           "Sintético", "Arte generado mediante difusión latente",             "6.000"),
    ("FaceForensics++ fake",  "Sintético", "Deepfakes de intercambio de rostro",                  "5.000"),
    ("Midjourney",            "Sintético", "Imágenes generadas de temática variada",              "4.000"),
    ("SD-turbo deportivo",    "Sintético", "Imágenes sintéticas de apariencia fotorrealista",     "1.000"),
]
TOTAL = ("Total", "—", "Nueve fuentes independientes", "60.000")

# ── tabla 5: progresion de configuraciones ───────────────────────────────────
# Las dos cifras salen de la misma medicion (reports/produccion_ffpp.json),
# por la via de produccion y en terminos de banda de evidencia, que es la
# definicion que usan las columnas de esa tabla.
FILA_NUEVA_T5 = (
    "Meta-ensemble recalibrado y peso del track facial corregido (implementado)",
    "94,0 %",
    "0,5 %",
)


def texto_de_celda(celda, nuevo: str) -> None:
    """Cambia el texto conservando el formato del primer `run`.

    Se escribe sobre el primer run y se vacian los demas, en vez de reconstruir
    el parrafo: asi la celda mantiene tipografia, tamano y color.
    """
    parrafos = celda.paragraphs
    if not parrafos:
        celda.text = nuevo
        return
    par = parrafos[0]
    if par.runs:
        par.runs[0].text = nuevo
        for r in par.runs[1:]:
            r.text = ""
    else:
        par.add_run(nuevo)
    for extra in parrafos[1:]:
        for r in extra.runs:
            r.text = ""


def clonar_fila(tabla, modelo_idx: int):
    """Duplica una fila existente al final, conservando su formato."""
    modelo = tabla.rows[modelo_idx]._tr
    nueva = copy.deepcopy(modelo)
    modelo.addnext(nueva)
    return tabla.rows[modelo_idx + 1]


def rellenar(fila, valores) -> None:
    for celda, v in zip(fila.cells, valores):
        texto_de_celda(celda, v)


def rehacer_tabla_fuentes(tabla) -> list[str]:
    """Deja la tabla con las nueve fuentes actuales mas la fila de total."""
    cambios = []
    necesarias = len(FUENTES) + 1          # fuentes + total
    existentes = len(tabla.rows) - 1       # sin la cabecera
    cambios.append(f"t40: {existentes} filas de datos -> {necesarias}")

    # Se clona siempre la primera fila de datos como modelo de formato.
    while len(tabla.rows) - 1 < necesarias:
        clonar_fila(tabla, 1)
    while len(tabla.rows) - 1 > necesarias:
        ultima = tabla.rows[-1]._tr
        ultima.getparent().remove(ultima)

    for i, vals in enumerate(FUENTES + [TOTAL], start=1):
        rellenar(tabla.rows[i], vals)
    cambios.append(f"t40: nueve fuentes y total 60.000 escritos")
    return cambios


def anadir_configuracion(tabla) -> list[str]:
    """Anade la configuracion de noviembre al final de la progresion."""
    ya = any("peso del track facial" in (c.text or "")
             for r in tabla.rows for c in r.cells)
    if ya:
        return ["t5: la fila nueva ya estaba, no se duplica"]
    modelo = len(tabla.rows) - 1
    nueva = clonar_fila(tabla, modelo)
    rellenar(nueva, FILA_NUEVA_T5)
    return [f"t5: fila anadida -> {FILA_NUEVA_T5[1]} / {FILA_NUEVA_T5[2]}"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true",
                    help="escribe sobre el documento; sin esta opcion deja "
                         "un .PRUEBA.docx aparte")
    args = ap.parse_args()

    if not INFORME.exists():
        print(f"ERROR: no existe {INFORME}")
        return 1
    from docx import Document
    d = Document(str(INFORME))
    print(f"{INFORME.name}: {len(d.tables)} tablas\n")

    # Las tablas se localizan por contenido, no por indice: si alguien inserta
    # una tabla antes, un indice fijo apuntaria a otra cosa y la reescribiria.
    t_fuentes = t_config = None
    for i, t in enumerate(d.tables):
        cab = " | ".join((c.text or "").strip().lower()
                         for c in t.rows[0].cells)
        if "fuente" in cab and "naturaleza del material" in cab:
            t_fuentes, i_fuentes = t, i
        if "configuraci" in cab and "deepfakes" in cab:
            t_config, i_config = t, i

    if t_fuentes is None:
        print("ERROR: no encuentro la tabla de composicion del conjunto "
              "(cabecera con 'Fuente' y 'Naturaleza del material').")
        return 2
    if t_config is None:
        print("ERROR: no encuentro la tabla de progresion de configuraciones "
              "(cabecera con 'Configuracion' y 'Deepfakes').")
        return 2
    print(f"  tabla de fuentes      -> indice {i_fuentes}")
    print(f"  tabla de progresion   -> indice {i_config}\n")

    cambios = rehacer_tabla_fuentes(t_fuentes)
    cambios += anadir_configuracion(t_config)
    print("=== CAMBIOS ===")
    for c in cambios:
        print(f"  {c}")

    if not args.aplicar:
        prueba = INFORME.with_suffix(".PRUEBA.docx")
        d.save(str(prueba))
        print(f"\nSimulacion: el original no se toco.")
        print(f"Resultado para revisar -> {prueba}")
        return 0

    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    copia = INFORME.with_suffix(f".{sello}.bak.docx")
    shutil.copy2(INFORME, copia)
    d.save(str(INFORME))
    print(f"\n  guardado {INFORME.name}  (respaldo: {copia.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

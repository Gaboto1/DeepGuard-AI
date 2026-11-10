"""
Lee los entregables YA actualizados y comprueba que dicen lo que deben decir.

Por que no basta con la simulacion
----------------------------------
scripts/actualizar_cifras_entregables.py declara cuantas veces espera encontrar
cada clave y avisa si el recuento no cuadra. Eso detecta que una clave dejo de
alcanzar sus ocurrencias, pero NO detecta que el texto final sea incorrecto.

Caso real de esta sesion: la frase del KPI-02 mencionaba el 12,5 % como valor
historico, y la clave corta '12,5 %' se aplicaba despues dentro de la misma
pasada, dejando escrito 'frente al 0,7 % de septiembre de 2026'. El recuento
era 5 tanto con el texto correcto como con el corrupto —la clave larga consumia
una ocurrencia y la corta reencontraba la recien escrita— de modo que dos
caminos distintos daban el mismo numero.

La unica comprobacion que cierra ese hueco es leer el resultado. Este script lo
hace al reves que el otro: en vez de buscar lo viejo para cambiarlo, busca lo
NUEVO para confirmarlo, y busca lo viejo para asegurarse de que ya no esta.

Salida: reports/verificacion_entregables.txt (y codigo de salida distinto de 0
si algo falla, para poder encadenarlo)
"""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SALIDA = ROOT / "reports" / "verificacion_entregables.txt"

DOCS = {
    "INFORME": (ROOT / "evaluacion 2 proyecto de tituulo"
                / "TIHI84_U2_ES2_InformeDeepScan_RojasLiapiz.docx"),
    "GUION": ROOT / "ev 4" / "TIHI84_U3_ES4_Guion_Defensa_RojasLiapiz.docx",
    "DEFENSA": (ROOT / "ev 4"
                / "TIHI84_U3_ES4_Defensa_DeepScan_RojasLiapiz.pptx"),
}

# (documento, texto que DEBE aparecer, cuantas veces como minimo)
#
# Los minimos son POR DOCUMENTO. En el primer intento puse aqui los totales de
# los tres archivos juntos y el script reporto tres fallos que no existian: los
# documentos estaban bien y mis expectativas mal. Derivados de la estructura:
# el KPI-01 lleva su cifra en la celda de valor y en la justificacion SMART,
# y el 94,0 % aparece ademas en la fila nueva de la tabla de progresion.
DEBE_APARECER = [
    ("INFORME", "94,0 %", 3),
    ("INFORME", "0,7 %", 2),
    ("INFORME", "0,990", 2),
    ("INFORME", "60.000 imágenes", 3),
    ("INFORME", "nueve fuentes", 3),
    ("INFORME", "81 pruebas", 3),
    # Sexta pasada: latencia. El valor y la meta del KPI-04 y la meta del SLA
    # se corrigieron contra la medicion real (reports/latencia_medida.json).
    ("INFORME", "11,7 s (p95)", 1),
    ("INFORME", "≤ 15 s en el percentil 95", 1),
    ("INFORME", "≤ 90 s en el percentil 95", 1),
    ("INFORME", "restando semantic_analysis.analysis_time", 1),
    ("INFORME", "realizada en noviembre de 2026", 1),
    ("INFORME", "frente al 12,5 % de septiembre de 2026", 1),
    ("INFORME", "y de un 49,9 % en septiembre de 2026", 1),
    ("INFORME", "conjunto retenido", 2),
    ("INFORME", "ELSA multigenerador", 1),
    ("INFORME", "Nueve fuentes independientes", 1),
    ("INFORME", "peso del track facial", 1),
    ("GUION", "Ochenta y una pruebas", 1),
    ("GUION", "Sesenta mil imágenes", 1),
    ("GUION", "nueve fuentes independientes", 1),
    ("GUION", "0,992", 1),
    ("GUION", "0,35 a 0,99", 1),
    ("GUION", "5,7 % con pesos fijos y 12,5 % en septiembre de 2026", 1),
    ("DEFENSA", "0,992", 1),
    ("DEFENSA", "0,35 a 0,99", 1),
    ("DEFENSA", "81", 1),
    # Cuarta pasada: la tabla de cifras del guion y la lamina 13 seguian
    # diciendo 14.000 imagenes y 6 fuentes mientras el cuerpo del guion ya
    # decia "Sesenta mil". Eran celdas con la cifra sola, que un barrido del
    # texto corrido no ve.
    ("GUION", "60.000", 1),
    ("DEFENSA", "60.000", 1),
    ("DEFENSA", "9 fuentes", 1),
]

# (documento, texto que NO debe quedar, motivo)
NO_DEBE_QUEDAR = [
    ("INFORME", "frente al 0,7 % de septiembre de 2026",
     "la referencia historica quedo sustituida por el valor nuevo"),
    ("INFORME", "14.000 imágenes", "tamano del conjunto anterior"),
    ("INFORME", "58 pruebas", "recuento de pruebas anterior"),
    ("INFORME", "0,883", "AUC anterior"),
    ("INFORME", "Seis fuentes independientes",
     "total de la tabla de composicion, ya reescrita"),
    ("GUION", "0,53 a 0,86", "rango de AUC medido dentro de muestra"),
    ("GUION", "Cincuenta y ocho pruebas", "recuento anterior, escrito con letras"),
    ("GUION", "Catorce mil imágenes", "tamano anterior, escrito con letras"),
    ("GUION", "(antes 5,7 %)", "cadena de valores historicos incompleta"),
    ("DEFENSA", "0,883", "AUC anterior"),
    ("DEFENSA", "0,53 a 0,86", "rango anterior"),
    ("DEFENSA", "Ningún detector aislado cubre todas las técnicas",
     "afirmacion que las mediciones fuera de muestra no sostienen"),
    # El recuento real de la suite es 81 (pytest, 2026-11-09, quinta pasada).
    # Declarar 75 o 78 es tan falso como declarar 90: la suite crece cada vez
    # que una regresion se guarda con una prueba, y el entregable tiene que
    # seguirla. Las tres ultimas llegaron con
    # backend/tests/test_config_independiente_del_cwd.py.
    ("INFORME", "75 pruebas", "recuento de la tercera pasada"),
    ("GUION", "Setenta y cinco", "mismo recuento, escrito con letras"),
    ("DEFENSA", "75 pruebas", "mismo recuento en la lamina de estado"),
    ("INFORME", "78 pruebas", "recuento de la cuarta pasada: la suite da 81"),
    ("GUION", "Setenta y ocho", "recuento de la cuarta pasada, con letras"),
    ("DEFENSA", "78 pruebas", "recuento de la cuarta pasada en la lamina 17"),
    # El KPI-04 declaraba "< 3 s" midiendo con un campo que incluye el
    # analisis semantico y que nunca bajo de 17,3 s sobre 49 analisis reales.
    # Aislado el ensemble, la mediana es 5,3 s: tampoco eran 3. La meta de
    # "<= 5 s" tampoco se cumplia, con un p95 de 11,7 s.
    ("INFORME", "< 3 s", "valor de latencia falso: el minimo medido es 3,43 s"),
    ("INFORME", "≤ 5 s en el percentil 95",
     "meta de latencia incumplida: el p95 medido es 11,7 s"),
    ("INFORME", "entre 1 y 3 segundos",
     "justificacion SMART basada en una medicion que no existe"),
    ("GUION", "14.000", "tamano anterior en la tabla de cifras de consulta"),
    ("DEFENSA", "14.000", "tamano anterior en la lamina de evidencia"),
    ("DEFENSA", "6 fuentes", "numero de fuentes anterior"),
]

# Lo que debe CONSERVARSE: historia que seria falso reescribir.
DEBE_CONSERVARSE = [
    ("INFORME", "49,9 %",
     "hito de septiembre en la tabla de progresion y en la justificacion SMART"),
    ("INFORME", "12,5 %",
     "mismo hito, columna de falsas alarmas"),
    ("INFORME", "seis fuentes",
     "parrafo de lecciones aprendidas: narra cuando se construyo ese conjunto"),
    ("INFORME", "0,1 %", "punto de partida de la progresion"),
    # El 14.000 del informe NO es un residuo: es la cantidad que aporta ELSA
    # multigenerador en la tabla de composicion, y la columna suma 60.000
    # exacto. Se afirma aqui para que una futura pasada que persiga el 14.000
    # como cifra obsoleta no se lo lleve por delante.
    ("INFORME", "14.000", "cantidad de ELSA multigenerador en la tabla 40"),
    ("INFORME", "0.75", "AUC del promedio ponderado en la tabla de metodos"),
    ("INFORME", "0.975", "AUC del detector de arte sobre obra grafica"),
    ("GUION", "0,975", "AUC que justifico separar el detector de arte"),
    ("GUION", "0,609", "el otro extremo de esa medicion"),
    ("GUION", "0,863", "AUC del probe CLIP que motivo el cabezal facial"),
    ("GUION", "91 %", "peso que concentraba el detector de arte"),
]


def texto_docx(p: Path) -> str:
    from docx import Document
    d = Document(str(p))
    partes = [par.text or "" for par in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            for c in row.cells:
                partes.append(c.text or "")
    return "\n".join(partes)


def texto_pptx(p: Path) -> str:
    from pptx import Presentation
    pr = Presentation(str(p))
    partes = []
    for s in pr.slides:
        for sh in s.shapes:
            if sh.has_text_frame:
                partes.append(sh.text_frame.text or "")
            if getattr(sh, "has_table", False):
                for row in sh.table.rows:
                    for c in row.cells:
                        partes.append(c.text_frame.text or "")
    return "\n".join(partes)


def main() -> int:
    buf = io.StringIO()

    def di(*a):
        linea = " ".join(str(x) for x in a)
        print(linea)
        buf.write(linea + "\n")

    textos = {}
    for nombre, p in DOCS.items():
        if not p.exists():
            di(f"ERROR: falta {p}")
            return 1
        textos[nombre] = (texto_pptx(p) if p.suffix == ".pptx"
                          else texto_docx(p))
        di(f"{nombre:8s} {len(textos[nombre]):>7,} caracteres  {p.name}")

    fallos = 0

    di("\n=== DEBE APARECER (cifras y textos nuevos) ===")
    for doc, txt, minimo in DEBE_APARECER:
        n = textos[doc].count(txt)
        ok = n >= minimo
        fallos += 0 if ok else 1
        di(f"  {'ok ' if ok else 'NO '} {doc:8s} {n:3d}x (>= {minimo})  "
           f"{txt[:58]}")

    di("\n=== NO DEBE QUEDAR (texto superado) ===")
    for doc, txt, motivo in NO_DEBE_QUEDAR:
        n = textos[doc].count(txt)
        ok = n == 0
        fallos += 0 if ok else 1
        di(f"  {'ok ' if ok else 'NO '} {doc:8s} {n:3d}x  {txt[:44]:44s} "
           f"| {motivo[:40]}")

    di("\n=== DEBE CONSERVARSE (historia que no se reescribe) ===")
    for doc, txt, motivo in DEBE_CONSERVARSE:
        n = textos[doc].count(txt)
        ok = n >= 1
        fallos += 0 if ok else 1
        di(f"  {'ok ' if ok else 'NO '} {doc:8s} {n:3d}x  {txt[:16]:16s} "
           f"| {motivo[:58]}")

    di(f"\n{'TODO CORRECTO' if fallos == 0 else f'{fallos} COMPROBACIONES FALLIDAS'}")
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(buf.getvalue(), encoding="utf-8")
    print(f"-> {SALIDA}")
    return 0 if fallos == 0 else 3


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    raise SystemExit(main())

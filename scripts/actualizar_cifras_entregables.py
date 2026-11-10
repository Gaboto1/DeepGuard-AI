"""
Sustituye cifras en el informe ES2, el guion y la presentacion de la defensa.

Por que un script y no edicion a mano
-------------------------------------
Las mismas metricas aparecen repetidas en los tres documentos: el AUC esta en
una tabla del informe, en la justificacion SMART de un KPI, en un parrafo del
guion y en una diapositiva. Cambiar a mano deja atras alguna ocurrencia, y una
cifra vieja contradiciendo a la nueva dentro del mismo entregable es peor que
no haber actualizado nada. Este script aplica cada sustitucion en los tres
documentos a la vez y cuenta cuantas veces la aplico.

Garantias
---------
1. Preserva el formato: sustituye el texto DENTRO de cada `run`, de modo que
   negrita, tamano y color se mantienen. No reescribe el parrafo.
2. Avisa de lo que no encontro. Una clave con cero coincidencias significa que
   el texto del documento no es el que se supuso, y entonces la cifra vieja
   sigue ahi: el script lo marca en vez de callarlo.
3. Detecta cifras partidas entre runs. Word puede dividir "0,883" en dos runs;
   la sustitucion por run no la veria. El script compara contra el texto
   completo del parrafo y avisa de esos casos para corregirlos a mano.
4. No escribe nada sin --aplicar. Por defecto solo informa.

Uso
---
    python scripts/actualizar_cifras_entregables.py               # simulacion
    python scripts/actualizar_cifras_entregables.py --aplicar     # escribe
    python scripts/actualizar_cifras_entregables.py --mapa m.json # otro mapa

Formato del mapa (JSON). Dos formas, mezclables:

    {"texto viejo": "texto nuevo"}

    {"texto viejo": {"nuevo": "texto nuevo",
                     "contexto": "subcadena que debe estar en el parrafo",
                     "docs": ["parte del nombre de archivo"],
                     "veces": 3}}

Las claves se aplican de la mas larga a la mas corta, para que "0,883" no se
sustituya dentro de "AUC 0,883" cuando ambas sean claves.

Por que hace falta `contexto`
-----------------------------
Una cifra puede aparecer con dos significados. "seis fuentes" esta en el
informe describiendo el conjunto actual —y hay que actualizarlo a nueve— pero
tambien en la seccion de lecciones aprendidas, narrando el momento en que se
construyo ese conjunto de seis. Ahi "seis" es historia y cambiarlo falsea el
relato.

La alternativa seria usar como clave la frase entera para desambiguar, y no
funciona: Word parte los parrafos en multiples `run`, de modo que una frase
larga casi nunca vive dentro de un unico run y la sustitucion no la alcanza.
Una clave corta con guarda de contexto sobre el texto COMPLETO del parrafo
resuelve las dos cosas a la vez.

`veces` declara cuantas sustituciones se esperan. Si el recuento no coincide,
el script lo marca: protege de que un cambio en los documentos haga que una
clave deje de encontrar sus ocurrencias en silencio.
"""
import argparse
import json
import shutil

from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DOCX = [
    ROOT / "evaluacion 2 proyecto de tituulo"
         / "TIHI84_U2_ES2_InformeDeepScan_RojasLiapiz.docx",
    ROOT / "ev 4" / "TIHI84_U3_ES4_Guion_Defensa_RojasLiapiz.docx",
]
PPTX = [
    ROOT / "ev 4" / "TIHI84_U3_ES4_Defensa_DeepScan_RojasLiapiz.pptx",
]
MAPA_DEFECTO = ROOT / "reports" / "mapa_cifras.json"


def normalizar(bruto: dict) -> list:
    """Admite las dos formas del mapa y devuelve una lista ordenada.

    Cada entrada queda como un dict con viejo, nuevo, contexto, no_contexto,
    docs y veces. Se ordena de la clave mas larga a la mas corta para que una
    cifra corta no se sustituya dentro de una frase mas larga que tambien sea
    clave.
    """
    items = []
    for viejo, bruto_v in bruto.items():
        # Claves de metadatos del propio mapa: documentan por que el mapa es
        # como es, y no son texto a buscar en los documentos.
        if viejo.endswith("__"):
            continue
        # Una misma cifra puede necesitar varias reglas con guardas distintas.
        # Caso real: el '58' del recuento de pruebas aparece como celda suelta
        # en una tabla del guion y en una lamina de la presentacion, y en cada
        # sitio hay que acotarlo por una ubicacion diferente. JSON no admite
        # la clave repetida, de modo que el valor puede ser una lista de reglas.
        reglas = bruto_v if isinstance(bruto_v, list) else [bruto_v]
        for v in reglas:
            _agregar(items, viejo, v)
    items.sort(key=lambda e: -len(e["viejo"]))
    # Identificador por REGLA, no por clave: dos reglas de '58' con guardas
    # distintas tienen que contarse por separado o el recuento declarado de
    # cada una saltaria contra la suma de ambas.
    for i, e in enumerate(items):
        e["id"] = i
    return items


def _agregar(items: list, viejo: str, v) -> None:
    """Normaliza una sola regla y la anade a la lista."""
    if isinstance(v, dict):
        desconocidas = set(v) - {"nuevo", "contexto", "no_contexto",
                                 "docs", "veces", "nota",
                                 "ubicaciones", "no_ubicaciones"}
        if desconocidas:
            raise SystemExit(
                f"ERROR en el mapa: la clave '{viejo}' trae opciones no "
                f"reconocidas {sorted(desconocidas)}. Un nombre mal "
                f"escrito dejaria la guarda sin efecto y la sustitucion "
                f"se aplicaria donde no debe.")
        items.append({"viejo": viejo, "nuevo": v["nuevo"],
                      "contexto": v.get("contexto"),
                      "no_contexto": v.get("no_contexto"),
                      "ubicaciones": v.get("ubicaciones"),
                      "no_ubicaciones": v.get("no_ubicaciones"),
                      "docs": v.get("docs"), "veces": v.get("veces")})
    else:
        items.append({"viejo": viejo, "nuevo": v, "contexto": None,
                      "no_contexto": None, "ubicaciones": None,
                      "no_ubicaciones": None, "docs": None,
                      "veces": None})


def sustituir_en_runs(parrafos, mapa, conteo, partidas, saltadas, origen):
    """Aplica el mapa run a run y registra lo que queda partido entre runs."""
    for par in parrafos:
        for e in mapa:
            # El texto del parrafo se relee en cada clave, no una vez por
            # parrafo. Una sustitucion previa pudo cambiarlo, y con el texto
            # obsoleto la clave siguiente encuentra su cifra en la cadena vieja,
            # no la halla en ningun run —porque ya fue sustituida— y la reporta
            # como "partida entre runs". Es un aviso falso que llevaria a
            # corregir a mano algo ya corregido, o a dudar de todo el informe.
            texto_par = par.text or ""
            viejo, nuevo = e["viejo"], e["nuevo"]
            if viejo not in texto_par:
                continue
            if e["docs"] and not any(d.lower() in origen.lower()
                                     for d in e["docs"]):
                saltadas.append((origen, viejo, "documento", texto_par[:90]))
                continue
            if e["contexto"] and e["contexto"] not in texto_par:
                # Misma cifra, otro significado: se deja como esta.
                saltadas.append((origen, viejo, "contexto", texto_par[:90]))
                continue
            if e["no_contexto"] and e["no_contexto"] in texto_par:
                # Guarda negativa: aqui la cifra es historia, no estado actual.
                saltadas.append((origen, viejo, "no_contexto", texto_par[:90]))
                continue
            if e["no_ubicaciones"] and any(u in origen
                                           for u in e["no_ubicaciones"]):
                saltadas.append((origen, viejo, "ubicacion", texto_par[:90]))
                continue
            if e["ubicaciones"] and not any(u in origen
                                            for u in e["ubicaciones"]):
                saltadas.append((origen, viejo, "ubicacion", texto_par[:90]))
                continue
            tocado = False
            for run in par.runs:
                if viejo in run.text:
                    run.text = run.text.replace(viejo, nuevo)
                    conteo[e["id"]] += 1
                    tocado = True
            if not tocado:
                # Esta en el parrafo pero en ningun run completo: Word la partio
                partidas.append((origen, viejo, texto_par[:120]))


def recorrer_docx(path: Path, mapa, conteo, partidas, saltadas):
    from docx import Document
    d = Document(str(path))
    sustituir_en_runs(d.paragraphs, mapa, conteo, partidas, saltadas,
                      f"{path.name}#cuerpo")
    # El indice de tabla va en la ubicacion porque en una tabla cada celda es
    # su propio parrafo: la guarda de contexto no puede ver la etiqueta de la
    # fila, de modo que la unica forma de proteger una celda concreta —por
    # ejemplo la fila historica de una tabla de progresion— es por ubicacion.
    for ti, t in enumerate(d.tables):
        for row in t.rows:
            for c in row.cells:
                sustituir_en_runs(c.paragraphs, mapa, conteo, partidas,
                                  saltadas, f"{path.name}#t{ti}")
    return d


def recorrer_pptx(path: Path, mapa, conteo, partidas, saltadas):
    from pptx import Presentation
    pr = Presentation(str(path))
    for si, s in enumerate(pr.slides, 1):
        for sh in s.shapes:
            if sh.has_text_frame:
                sustituir_en_runs(sh.text_frame.paragraphs, mapa, conteo,
                                  partidas, saltadas, f"{path.name}#sl{si}")
            if getattr(sh, "has_table", False):
                for row in sh.table.rows:
                    for c in row.cells:
                        sustituir_en_runs(c.text_frame.paragraphs, mapa,
                                          conteo, partidas, saltadas,
                                          f"{path.name}#sl{si}t")
    return pr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mapa", type=Path, default=MAPA_DEFECTO)
    ap.add_argument("--aplicar", action="store_true",
                    help="escribe los cambios; sin esta opcion solo informa")
    args = ap.parse_args()

    if not args.mapa.exists():
        print(f"ERROR: falta el mapa {args.mapa}")
        print('  Formato: {"0,883": "0,99xx", "49,9 %": "xx,x %"}')
        return 1
    bruto = json.loads(args.mapa.read_text(encoding="utf-8"))
    mapa = normalizar(bruto)
    print(f"Mapa: {len(mapa)} sustituciones desde {args.mapa.name}")
    print(f"Modo: {'APLICAR (escribe)' if args.aplicar else 'simulacion'}\n")

    conteo: Counter = Counter()
    partidas: list = []
    saltadas: list = []
    documentos = []

    for p in DOCX:
        if not p.exists():
            print(f"  [!] no existe: {p.name}")
            continue
        documentos.append((p, recorrer_docx(p, mapa, conteo, partidas,
                                            saltadas)))
    for p in PPTX:
        if not p.exists():
            print(f"  [!] no existe: {p.name}")
            continue
        documentos.append((p, recorrer_pptx(p, mapa, conteo, partidas,
                                            saltadas)))

    print("=== SUSTITUCIONES ===")
    sin_encontrar = []
    descuadres = []
    for e in mapa:
        viejo, veces = e["viejo"], e["veces"]
        n = conteo[e["id"]]
        if n == 0:
            sin_encontrar.append(viejo)
        marca = "   " if n else " !!"
        if veces is not None and n != veces:
            marca = " ##"
            descuadres.append((viejo, n, veces))
        extra = ""
        if e["contexto"]:
            extra += f"  [si: {e['contexto'][:24]}]"
        if e["no_contexto"]:
            extra += f"  [no: {e['no_contexto'][:24]}]"
        if e["docs"]:
            extra += f"  [docs: {','.join(d[:12] for d in e['docs'])}]"
        print(f"{marca} {n:3d}x  {viejo[:38]:38s} -> {e['nuevo'][:30]}{extra}")

    total = sum(conteo.values())
    print(f"\n  total: {total} sustituciones en {len(documentos)} documentos")

    if sin_encontrar:
        print(f"\n=== NO ENCONTRADAS ({len(sin_encontrar)}) ===")
        print("  El texto supuesto no esta en los documentos. La cifra vieja")
        print("  SIGUE AHI: hay que revisar estas a mano.")
        for v in sin_encontrar:
            print(f"    - {v}")

    if descuadres:
        print(f"\n=== RECUENTO INESPERADO ({len(descuadres)}) ===")
        print("  Se declaro cuantas veces debia aparecer y no cuadra. O el")
        print("  documento cambio, o la clave alcanza mas o menos de lo")
        print("  previsto. Revisar antes de aplicar.")
        for viejo, n, veces in descuadres:
            print(f"    '{viejo}': {n} encontradas, {veces} esperadas")

    if saltadas:
        porque = Counter(m for _, _, m, _ in saltadas)
        print(f"\n=== OMITIDAS A PROPOSITO ({len(saltadas)}) ===")
        print(f"  {dict(porque)} — la cifra estaba, pero la guarda la excluyo.")
        for origen, viejo, motivo, ctx in saltadas[:12]:
            print(f"    [{motivo}] {origen}: '{viejo}' en \"{ctx}\"")
        if len(saltadas) > 12:
            print(f"    ... y {len(saltadas) - 12} mas")

    if partidas:
        print(f"\n=== CIFRAS PARTIDAS ENTRE RUNS ({len(partidas)}) ===")
        print("  Word dividio el texto; la sustitucion por run no las alcanza.")
        for origen, viejo, ctx in partidas:
            print(f"    {origen}: '{viejo}' en \"{ctx}\"")

    if not args.aplicar:
        print("\nSimulacion: no se escribio nada. Usa --aplicar para guardar.")
        return 0 if not (sin_encontrar or partidas or descuadres) else 2

    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    for p, doc in documentos:
        copia = p.with_suffix(f".{sello}.bak{p.suffix}")
        shutil.copy2(p, copia)
        doc.save(str(p))
        print(f"  guardado {p.name}  (respaldo: {copia.name})")
    print("\nListo.")
    return 0


if __name__ == "__main__":
    # La consola de Windows usa cp1252 y los mapas llevan caracteres que no
    # existen en esa pagina de codigos: el guion reventaba con
    # UnicodeEncodeError al IMPRIMIR un "<=" de una meta, despues de haber
    # aplicado ya parte de las sustituciones. Un informe a medias es peor que
    # ninguno, porque no se sabe que quedo hecho.
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())

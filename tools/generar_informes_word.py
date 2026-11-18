# -*- coding: utf-8 -*-
"""
Genera los dos informes vigentes en Word, en la carpeta informes/:

- DeepScan_Auditoria_2026-11-17.docx      (desde reports/AUDITORIA_20261117.md)
- DeepScan_Informe_Tecnico_2026-11-18.docx (estado del proyecto a esa fecha)

Cada cifra declara de donde sale y si es dentro o fuera de muestra, igual que
los informes en Markdown de reports/. Si una cifra cambia, se cambia aqui y se
vuelve a ejecutar:

    python tools/generar_informes_word.py

El indice se rellena al abrir el documento en Word (o con el paso de Word que
usa scripts de verificacion); python-docx no puede calcular paginas.
"""
from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "informes"

AUTOR = "Gabriel Rojas y Vicente Liapiz"
INSTITUCION = "INACAP · Ingeniería en Informática · Proyecto de Título"

NAVY = RGBColor(0x08, 0x2A, 0x4A)
AZUL = RGBColor(0x1E, 0x63, 0xD4)
TEXTO = RGBColor(0x1F, 0x2D, 0x3D)
GRIS = RGBColor(0x5B, 0x6B, 0x7D)
ROJO = RGBColor(0xB4, 0x23, 0x23)
AMBAR = RGBColor(0x9A, 0x6A, 0x00)
VERDE = RGBColor(0x1D, 0x7A, 0x45)
FUENTE = "Calibri"

ANCHO_UTIL_CM = 21.59 - 2 * 2.5


# =============================================================================
# Utilidades de formato
# =============================================================================

def _sombra(celda, hex_color: str) -> None:
    tcPr = celda._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def _bordes_tabla(tabla, color="C9D3DF", interior=True) -> None:
    tblPr = tabla._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    lados = ["top", "left", "bottom", "right"] + (["insideH", "insideV"] if interior else [])
    for lado in lados:
        e = OxmlElement(f"w:{lado}")
        e.set(qn("w:val"), "single")
        e.set(qn("w:sz"), "4")
        e.set(qn("w:space"), "0")
        e.set(qn("w:color"), color)
        b.append(e)
    tblPr.append(b)


def _margenes_celda(tabla, arriba=60, lado=100) -> None:
    tblPr = tabla._tbl.tblPr
    m = OxmlElement("w:tblCellMar")
    for nombre, v in (("top", arriba), ("bottom", arriba), ("left", lado), ("right", lado)):
        e = OxmlElement(f"w:{nombre}")
        e.set(qn("w:w"), str(v))
        e.set(qn("w:type"), "dxa")
        m.append(e)
    tblPr.append(m)


def _no_partir_fila(fila) -> None:
    trPr = fila._tr.get_or_add_trPr()
    e = OxmlElement("w:cantSplit")
    trPr.append(e)


def _repetir_cabecera(fila) -> None:
    trPr = fila._tr.get_or_add_trPr()
    e = OxmlElement("w:tblHeader")
    trPr.append(e)


def _runs(parrafo, texto: str, tam: float | None = None, color: RGBColor | None = None,
          negrita_base: bool = False) -> None:
    """Escribe texto con **negrita**, *cursiva* y `codigo` en linea."""
    for trozo in re.split(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`)", texto):
        if not trozo:
            continue
        if trozo.startswith("**"):
            r = parrafo.add_run(trozo[2:-2])
            r.bold = True
        elif trozo.startswith("*") and trozo.endswith("*") and len(trozo) > 2:
            r = parrafo.add_run(trozo[1:-1])
            r.italic = True
            r.bold = negrita_base or None
        elif trozo.startswith("`"):
            r = parrafo.add_run(trozo[1:-1])
            r.font.name = "Consolas"
            r._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
            r.font.size = Pt((tam or 11) - 1.5)
        else:
            r = parrafo.add_run(trozo)
            r.bold = negrita_base or None
        if tam and not trozo.startswith("`"):
            r.font.size = Pt(tam)
        if color is not None:
            r.font.color.rgb = color


def _campo(parrafo, instruccion: str, marcador: str = "") -> None:
    r = parrafo.add_run()
    f1 = OxmlElement("w:fldChar")
    f1.set(qn("w:fldCharType"), "begin")
    r._r.append(f1)
    r2 = parrafo.add_run()
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = instruccion
    r2._r.append(it)
    r3 = parrafo.add_run()
    f2 = OxmlElement("w:fldChar")
    f2.set(qn("w:fldCharType"), "separate")
    r3._r.append(f2)
    parrafo.add_run(marcador)
    r4 = parrafo.add_run()
    f3 = OxmlElement("w:fldChar")
    f3.set(qn("w:fldCharType"), "end")
    r4._r.append(f3)


class Informe:
    def __init__(self, titulo_corto: str) -> None:
        self.d = Document()
        self.titulo_corto = titulo_corto
        self._estilos()
        s = self.d.sections[0]
        s.page_width, s.page_height = Cm(21.59), Cm(27.94)
        for lado in ("left_margin", "right_margin"):
            setattr(s, lado, Cm(2.5))
        s.top_margin, s.bottom_margin = Cm(2.3), Cm(2.2)
        s.different_first_page_header_footer = True

    # ------------------------------------------------------------- estilos
    def _estilos(self) -> None:
        st = self.d.styles
        n = st["Normal"]
        n.font.name = FUENTE
        n.element.rPr.rFonts.set(qn("w:eastAsia"), FUENTE)
        n.font.size = Pt(11)
        n.font.color.rgb = TEXTO
        n.paragraph_format.space_after = Pt(6)
        n.paragraph_format.line_spacing = 1.15

        for nombre, tam, color, antes, despues in (
                ("Heading 1", 16, NAVY, 20, 8),
                ("Heading 2", 13, AZUL, 14, 4),
                ("Heading 3", 11.5, NAVY, 10, 2)):
            h = st[nombre]
            h.font.name = FUENTE
            h.element.rPr.rFonts.set(qn("w:eastAsia"), FUENTE)
            h.element.rPr.rFonts.set(qn("w:ascii"), FUENTE)
            h.element.rPr.rFonts.set(qn("w:hAnsi"), FUENTE)
            h.font.size = Pt(tam)
            h.font.bold = True
            h.font.italic = False
            h.font.color.rgb = color
            pf = h.paragraph_format
            pf.space_before = Pt(antes)
            pf.space_after = Pt(despues)
            pf.keep_with_next = True

        for nombre in ("List Bullet", "List Number"):
            lb = st[nombre]
            lb.font.name = FUENTE
            lb.font.size = Pt(11)
            lb.paragraph_format.space_after = Pt(3)

        for nombre, tam, color in (("TOC 1", 11, NAVY), ("TOC 2", 10.5, TEXTO)):
            try:
                t = st[nombre]
            except KeyError:
                from docx.enum.style import WD_STYLE_TYPE
                t = st.add_style(nombre, WD_STYLE_TYPE.PARAGRAPH)
            t.font.name = FUENTE
            t.font.size = Pt(tam)
            t.font.color.rgb = color
            t.paragraph_format.space_after = Pt(2)

    # ------------------------------------------------------------- bloques
    def portada(self, titulo: str, subtitulo: str, lineas: list[str], resumen: str) -> None:
        d = self.d
        for _ in range(5):
            d.add_paragraph()
        p = d.add_paragraph()
        _runs(p, "DEEPSCAN", 11, AZUL, True)
        p.paragraph_format.space_after = Pt(4)
        p = d.add_paragraph()
        _runs(p, titulo, 28, NAVY, True)
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing = 1.0
        p = d.add_paragraph()
        _runs(p, subtitulo, 14, GRIS)
        p.paragraph_format.space_after = Pt(18)
        self._regla(AZUL, 12)
        for l in lineas:
            p = d.add_paragraph()
            _runs(p, l, 11, TEXTO)
            p.paragraph_format.space_after = Pt(2)
        d.add_paragraph()
        p = d.add_paragraph()
        _runs(p, resumen, 10.5, GRIS)
        p.paragraph_format.line_spacing = 1.25
        self.salto()

    def _regla(self, color: RGBColor, grosor: int = 8) -> None:
        p = self.d.add_paragraph()
        pPr = p._p.get_or_add_pPr()
        bdr = OxmlElement("w:pBdr")
        b = OxmlElement("w:bottom")
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), str(grosor))
        b.set(qn("w:space"), "1")
        b.set(qn("w:color"), str(color))
        bdr.append(b)
        pPr.append(bdr)
        p.paragraph_format.space_after = Pt(10)

    def indice(self) -> None:
        p = self.d.add_paragraph()
        _runs(p, "Contenido", 16, NAVY, True)
        p.paragraph_format.space_after = Pt(10)
        p = self.d.add_paragraph()
        _campo(p, 'TOC \\o "1-2" \\h \\z \\u', "Actualiza el índice: clic derecho → Actualizar campo.")
        self.salto()

    def pie(self) -> None:
        s = self.d.sections[0]
        p = s.footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        _runs(p, f"DeepScan · {self.titulo_corto}  ·  ", 8.5, GRIS)
        r = p.add_run("Página ")
        r.font.size, r.font.color.rgb = Pt(8.5), GRIS
        _campo(p, "PAGE", "1")
        r = p.add_run(" de ")
        r.font.size, r.font.color.rgb = Pt(8.5), GRIS
        _campo(p, "NUMPAGES", "1")
        for r in p.runs:
            r.font.size = Pt(8.5)
            r.font.color.rgb = GRIS

    def h1(self, t: str) -> None:
        self.d.add_heading(t, level=1)

    def h2(self, t: str) -> None:
        self.d.add_heading(t, level=2)

    def h3(self, t: str) -> None:
        self.d.add_heading(t, level=3)

    def p(self, t: str, color: RGBColor | None = None, tam: float | None = None):
        par = self.d.add_paragraph()
        _runs(par, t, tam, color)
        return par

    def vinetas(self, items: list[str], estilo: str = "List Bullet") -> None:
        for it in items:
            par = self.d.add_paragraph(style=estilo)
            _runs(par, it)

    def salto(self) -> None:
        self.d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def nota(self, titulo: str, texto: str, tipo: str = "info") -> None:
        fondo, borde, color = {
            "info": ("EEF4FD", "1E63D4", AZUL),
            "aviso": ("FFF6E0", "C99A1A", AMBAR),
            "grave": ("FDECEC", "C42B2B", ROJO),
            "ok": ("EAF6EF", "1D7A45", VERDE),
        }[tipo]
        t = self.d.add_table(rows=1, cols=1)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        c = t.cell(0, 0)
        c.width = Cm(ANCHO_UTIL_CM)
        _sombra(c, fondo)
        tcPr = c._tc.get_or_add_tcPr()
        bd = OxmlElement("w:tcBorders")
        for lado in ("top", "bottom", "right"):
            e = OxmlElement(f"w:{lado}")
            e.set(qn("w:val"), "nil")
            bd.append(e)
        e = OxmlElement("w:left")
        e.set(qn("w:val"), "single")
        e.set(qn("w:sz"), "24")
        e.set(qn("w:color"), borde)
        bd.append(e)
        tcPr.append(bd)
        _margenes_celda(t, 100, 160)
        par = c.paragraphs[0]
        _runs(par, titulo, 10.5, color, True)
        par.paragraph_format.space_after = Pt(2)
        for linea in texto.split("\n\n"):
            q = c.add_paragraph()
            _runs(q, linea, 10.5)
            q.paragraph_format.space_after = Pt(3)
        self.d.add_paragraph().paragraph_format.space_after = Pt(2)

    def tabla(self, cab: list[str], filas: list[list[str]], anchos_cm: list[float],
              colores: dict[int, dict[str, RGBColor]] | None = None, tam: float = 9.5) -> None:
        total = sum(anchos_cm)
        anchos = [a * ANCHO_UTIL_CM / total for a in anchos_cm]
        t = self.d.add_table(rows=1, cols=len(cab))
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        _bordes_tabla(t)
        _margenes_celda(t)
        fila = t.rows[0]
        _repetir_cabecera(fila)
        for i, h in enumerate(cab):
            c = fila.cells[i]
            c.width = Cm(anchos[i])
            _sombra(c, "082A4A")
            c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            par = c.paragraphs[0]
            _runs(par, h, tam, RGBColor(0xFF, 0xFF, 0xFF), True)
            par.paragraph_format.space_after = Pt(0)
        for k, datos in enumerate(filas):
            fila = t.add_row()
            _no_partir_fila(fila)
            for i, v in enumerate(datos):
                c = fila.cells[i]
                c.width = Cm(anchos[i])
                if k % 2 == 1:
                    _sombra(c, "F3F6FA")
                c.vertical_alignment = WD_ALIGN_VERTICAL.TOP
                par = c.paragraphs[0]
                color = (colores or {}).get(i, {}).get(v)
                _runs(par, v, tam, color)
                if color is not None:
                    for r in par.runs:
                        r.bold = True
                par.paragraph_format.space_after = Pt(0)
                par.paragraph_format.line_spacing = 1.05
        self.d.add_paragraph().paragraph_format.space_after = Pt(4)

    def guardar(self, nombre: str) -> Path:
        SALIDA.mkdir(exist_ok=True)
        ruta = SALIDA / nombre
        self.d.core_properties.author = AUTOR
        self.d.core_properties.title = f"DeepScan — {self.titulo_corto}"
        self.d.save(ruta)
        return ruta


GRAVEDAD = {0: {"Alta": ROJO, "Media": AMBAR, "Baja": GRIS}}


# =============================================================================
# 1. Auditoría
# =============================================================================

def auditoria() -> Path:
    I = Informe("Auditoría del proyecto, 17 de noviembre de 2026")
    I.portada(
        "Auditoría del proyecto",
        "Revisión completa de seguridad, dependencias, API en vivo, frontend, "
        "coherencia de datos e higiene del repositorio",
        [f"**Fecha de la auditoría:** 17 de noviembre de 2026",
         f"**Verificación en producción:** 18 de noviembre de 2026",
         f"**Autores:** {AUTOR}",
         INSTITUCION,
         "**Fuente:** reports/AUDITORIA_20261117.md (commit d8b7811 y 4bdea31)"],
        "Cada hallazgo se comprobó contra el sistema real —la API publicada en "
        "Render, la página publicada en GitHub Pages o el código— y no por "
        "inspección del texto. Las correcciones llevan una prueba automatizada "
        "que falla si el defecto vuelve.")
    I.pie()
    I.indice()

    I.h1("1. Resumen")
    I.p("Se encontraron **doce hallazgos**: cuatro de gravedad alta, cinco de "
        "gravedad media y tres de gravedad baja. Once están corregidos y "
        "verificados. El que queda abierto, la licencia de los datos de "
        "entrenamiento, no se resuelve con código: es una decisión del dueño del "
        "proyecto antes de cobrar por el servicio.")
    I.tabla(["Gravedad", "Hallazgos", "Corregidos", "Abiertos"],
            [["Alta", "4", "3", "1 (licencia de datos)"],
             ["Media", "5", "5", "0"],
             ["Baja", "3", "3", "0"]],
            [3, 3, 3, 6], colores=GRAVEDAD)
    I.nota("Estado al 18 de noviembre de 2026",
           "La API se volvió a desplegar en Render y las tres correcciones de "
           "seguridad están comprobadas en producción: el historial global responde "
           "404 y una subida real de 105 MB se rechaza con 413. El monitor de salud "
           "de GitHub Actions está reactivado y su última ejecución terminó bien.",
           "ok")

    I.h1("2. Alcance y método")
    I.p("La revisión cubrió seis frentes:")
    I.vinetas([
        "**Seguridad:** secretos en archivos e historial de git, endpoints expuestos, "
        "límites de subida, exposición de configuración.",
        "**Dependencias:** que todo lo que el código importa esté declarado, y "
        "vulnerabilidades conocidas en Python y npm.",
        "**API en vivo:** CORS, endpoints que usa la página, facturación.",
        "**Frontend:** que cada pantalla funcione contra la API publicada.",
        "**Coherencia de datos y documentos:** que las cifras de README, informes y "
        "entregables coincidan con las medidas.",
        "**Higiene del repositorio:** carpetas privadas, archivos grandes, restos.",
    ])
    I.p("Un hallazgo se da por cerrado solo cuando la corrección está comprobada en "
        "el sistema real y existe una prueba que falla si el defecto reaparece.")

    I.h1("3. Hallazgos")
    I.tabla(
        ["Gravedad", "Hallazgo", "Estado"],
        [["Alta", "`scikit-learn`, `joblib` y `lightgbm` no estaban en `requirements.txt`. "
                  "Una instalación nueva no cargaba ningún cabezal del meta-ensemble y caía "
                  "en silencio a pesos fijos.",
          "Corregido: versiones exactas fijadas y prueba."],
         ["Alta", "Límite de subida de 500 MB frente a 512 MB de RAM en Render, con el archivo "
                  "leído entero en memoria y copiado en Base64: una sola subida podía tumbar la API.",
          "Corregido: 100 MB y rechazo previo por `Content-Length`, con prueba."],
         ["Alta", "`/api/v1/history` devolvía los análisis de todos los usuarios sin pedir identidad.",
          "Corregido: desactivado por defecto, con prueba."],
         ["Alta", "Los cabezales están entrenados con OpenFake, licencia CC BY-NC 4.0 (no "
                  "comercial), mientras el proyecto plantea un modelo de pago.",
          "Documentado. Decisión pendiente antes de cobrar."],
         ["Media", "python-multipart 0.0.6 y starlette 0.27 con vulnerabilidades de denegación "
                   "de servicio en el procesado de subidas.",
          "Corregido: FastAPI 0.115.14 y python-multipart 0.0.20."],
         ["Media", "Next.js 14.0.4 con un aviso crítico y axios con varios altos.",
          "Corregido: Next.js 14.2.35 y axios 1.21 (ver riesgo aceptado)."],
         ["Media", "El objeto de configuración mostraba fragmentos de claves al imprimirse "
                   "(visto en un mensaje de error de pytest).",
          "Corregido: `repr=False` en los campos con credenciales, con prueba."],
         ["Media", "Un cabezal que no cargaba solo dejaba un aviso (`warning`).",
          "Corregido: ahora es un error que explica la consecuencia."],
         ["Media", "El README describía otro sistema (un solo ViT, 0,3 s por imagen, 500 MB) "
                   "y afirmaba una licencia MIT que no existe.",
          "Corregido: reescrito con cifras medidas y su procedencia."],
         ["Baja", "`ESTRUCTURA_PROYECTO.md` describía los cabezales anteriores.", "Corregido."],
         ["Baja", "El monitor de salud de GitHub Actions estaba desactivado por inactividad "
                  "desde el 1 de noviembre.",
          "Reactivado el 18 de noviembre; ejecución en verde."],
         ["Baja", "«API» aparecía en el menú principal de la página.",
          "Movido al pie de página."]],
        [2.2, 9.5, 5.3], colores=GRAVEDAD)

    I.h2("3.1 Dependencias de los modelos sin declarar")
    I.p("**Qué pasaba.** El meta-ensemble, que decide el resultado final, se guarda "
        "como modelos LightGBM serializados con `joblib`. Ninguna de esas librerías "
        "estaba en `backend/requirements.txt`. En el equipo de desarrollo funcionaba "
        "porque estaban instaladas a mano.")
    I.p("**Consecuencia.** En una instalación limpia los tres cabezales fallaban al "
        "cargar y el sistema seguía funcionando con pesos fijos, sin ningún error "
        "visible, con un detector bastante peor que el medido.")
    I.p("**Corrección.** Se fijaron `scikit-learn==1.8.0`, `joblib==1.5.3`, "
        "`lightgbm==4.6.0` y `xgboost==3.2.0`. La prueba `test_requisitos_modelos` "
        "comprueba que todo lo que importan los modelos esté declarado, y un cabezal "
        "que no carga queda registrado como error.")

    I.h2("3.2 Una sola subida podía tumbar la API")
    I.p("**Qué pasaba.** La API aceptaba archivos de hasta 500 MB, los leía enteros "
        "en memoria y los copiaba en Base64 para enviarlos al worker. El plan de "
        "Render tiene 512 MB de RAM.")
    I.p("**Corrección.** El límite baja a 100 MB, el mismo que el acuerdo de servicio "
        "promete para video, y la API rechaza con 413 por la cabecera "
        "`Content-Length` antes de leer el archivo. La prueba `test_limite_subida` "
        "verifica que archivo y copia caben con holgura en la RAM disponible.")
    I.p("**Verificado en producción el 18 de noviembre:** una subida real de 105 MB "
        "recibe 413, «El archivo supera el máximo de 100 MB».")

    I.h2("3.3 Historial global expuesto")
    I.p("**Qué pasaba.** `GET /api/v1/history` devolvía los resultados de los "
        "análisis de todos los usuarios a cualquiera que lo pidiera. La página no lo "
        "usaba: guarda el historial de cada persona en su propio navegador.")
    I.p("**Corrección.** El endpoint responde 404 salvo que se active "
        "`HISTORIAL_PUBLICO=true`. Prueba: `test_historial_global`. "
        "**Verificado en producción:** responde 404.")

    I.h2("3.4 Licencia de los datos de entrenamiento")
    I.p("Desde el 17 de noviembre los cabezales del meta-ensemble incluyen 13.877 "
        "filas de OpenFake (ComplexDataLab), publicado bajo **CC BY-NC 4.0, uso no "
        "comercial**. Para un proyecto de título no es un problema. Un servicio de "
        "pago no puede apoyarse en esos pesos.")
    I.nota("Decisión pendiente del dueño",
           "Antes de cobrar hay dos caminos: reentrenar los cabezales sin las filas de "
           "OpenFake (`scripts/train_meta_dual_head.py --sin-externo`) con otra fuente "
           "externa de licencia comercial, u obtener una licencia del autor. Los "
           "detectores preentrenados de HuggingFace también tienen licencias propias que "
           "revisar.", "aviso")

    I.h1("4. Lo que se comprobó y está bien")
    I.vinetas([
        "**Secretos:** ninguno en los archivos versionados ni en todo el historial de git, "
        "incluido el token de Cloudflare expuesto en una sesión anterior. Los `.env` "
        "versionados solo contienen ejemplos y la URL pública de la API.",
        "**Carpetas privadas** (`privado/`, `ev 4/`, `evaluacion*/`, `data/`): fuera del "
        "repositorio.",
        "**CORS:** los cinco endpoints que usa la página aceptan el origen de GitHub Pages "
        "y las cabeceras de identidad.",
        "**Facturación en vivo:** catálogo, contratación simulada, licencia anual de 365 "
        "días y rechazo de licencias manipuladas.",
        "**Repositorio:** ningún archivo versionado supera 2 MB; sin restos `.bak`, `.orig` "
        "ni logs.",
    ])

    I.h1("5. Riesgo aceptado")
    I.p("Quedan dos avisos de `npm audit` que solo se resuelven saltando a Next.js 16, "
        "un cambio de versión mayor. Ninguno aplica a este despliegue:")
    I.vinetas([
        "Los de Next.js (optimizador de imágenes, Server Components, *request smuggling* en "
        "*rewrites*, caché de `next/image`) afectan a un **servidor de Next en ejecución**. "
        "La página se publica como HTML estático en GitHub Pages: ese servidor no existe.",
        "El de PostCSS se ejecuta solo al **compilar**, sobre el CSS propio del proyecto; "
        "no procesa datos de terceros.",
    ])
    I.p("Si el frontend pasa a servirse con `next start`, hay que actualizar.")

    I.h1("6. Verificación en producción — 18 de noviembre de 2026")
    I.p("Tras el despliegue manual en Render, comprobado contra la API publicada:")
    I.tabla(["Comprobación", "Resultado"],
            [["`GET /api/v1/history`", "404"],
             ["Subida real de 105 MB a `/api/v1/analyze`",
              "413 `archivo_demasiado_grande`, «supera el máximo de 100 MB»"],
             ["`/api/v1/health`", "modo `api-only`, Redis conectado"],
             ["`/api/v1/billing/plans`", "catálogo de planes servido"],
             ["Monitor de salud (GitHub Actions)", "activo; ejecución del 18 nov en verde"],
             ["Análisis real de extremo a extremo", "imagen de prueba analizada en 19,9 s"]],
            [7, 10])

    I.h1("7. Acciones pendientes del dueño")
    I.tabla(["Acción", "Estado"],
            [["Desplegar la API en Render (*Manual Deploy*)", "Hecho el 18 nov"],
             ["Reactivar el monitor de salud", "Hecho el 18 nov"],
             ["Rotar `DEEPGUARD_BILLING_KEY` en Render si se usó la clave que se pegó "
              "en la conversación", "Pendiente"],
             ["Decidir la licencia del repositorio y, antes de cobrar, resolver la de "
              "los datos de entrenamiento", "Pendiente"]],
            [12, 5], colores={1: {"Hecho el 18 nov": VERDE, "Pendiente": AMBAR}})
    return I.guardar("DeepScan_Auditoria_2026-11-17.docx")


# =============================================================================
# 2. Informe técnico del proyecto
# =============================================================================

def informe_tecnico() -> Path:
    I = Informe("Informe técnico del proyecto, 18 de noviembre de 2026")
    I.portada(
        "Informe técnico del proyecto",
        "Sistema de análisis forense digital para la detección de contenido "
        "visual generado o manipulado por inteligencia artificial",
        ["**Versión:** 18 de noviembre de 2026",
         f"**Autores:** {AUTOR}",
         INSTITUCION,
         "**En vivo:** https://gaboto1.github.io/DeepGuard-AI/",
         "**Sustituye a:** los informes técnicos de mayo a julio de 2026 (DeepGuard AI), "
         "conservados en informes/versiones_anteriores"],
        "Estado del sistema tal como funciona en producción a esta fecha. Toda cifra "
        "indica de qué archivo sale y si se midió dentro o fuera de muestra: «fuera "
        "de muestra» significa sobre imágenes y generadores que el sistema no vio "
        "nunca durante su entrenamiento.")
    I.pie()
    I.indice()

    # ---------------------------------------------------------------- 1
    I.h1("1. Resumen ejecutivo")
    I.p("DeepScan recibe una imagen o un video y responde **cuánta evidencia hay** de "
        "que fue generado o manipulado por inteligencia artificial. No da un «real» o "
        "«falso»: da una de cinco bandas de evidencia, el desglose de cada detector, "
        "los metadatos forenses del archivo y un informe sellado criptográficamente "
        "que permite demostrar después que no se alteró.")
    I.p("El sistema está publicado y funcionando: la página en GitHub Pages, la API "
        "en Render, la cola en Upstash Redis y el cómputo en una GPU local.")
    I.tabla(["Indicador", "Valor", "Meta", "Medición"],
            [["KPI-01 · Deepfake facial señalado", "**95,0 %**", "≥ 60 %",
              "dentro de muestra (FaceForensics++)"],
             ["KPI-02 · Falsas alarmas en fotografía auténtica", "**0,9 %**", "≤ 8 %",
              "fuera de muestra (LFW + ImageNet)"],
             ["KPI-03 · AUC", "**0,995**", "≥ 0,90", "fuera de muestra"],
             ["KPI-04 · Latencia del ensemble (p95)", "**11,7 s**", "≤ 15 s",
              "vía de producción, GPU dedicada"],
             ["Imágenes de IA señaladas", "**84,9 %**", "—",
              "fuera de muestra (FLUX y DALL·E 3)"],
             ["Pruebas automatizadas", "**138**", "—", "pytest, todas en verde"]],
            [6.5, 2.2, 2, 6])
    I.nota("Dónde es menos fiable",
           "Sobre fotografía moderna de alta resolución «en la calle» (Reddit) las falsas "
           "alarmas suben al **14,2 %**. El cabezal facial está entrenado con intercambio de "
           "rostro y no reconoce rostros enteramente sintéticos. Es un análisis "
           "probabilístico: orienta una verificación, no reemplaza un peritaje.", "aviso")

    # ---------------------------------------------------------------- 2
    I.h1("2. Qué hace el sistema")
    I.tabla(["Función", "Detalle"],
            [["Análisis de imagen", "Seis detectores especializados, un meta-ensemble que "
                                    "aprende a combinarlos y una lectura semántica de la "
                                    "escena con LLaVA-1.5-7B"],
             ["Análisis de video", "Muestreo de fotogramas con análisis de consistencia "
                                   "temporal y de flujo óptico; hasta 100 MB por archivo"],
             ["Resultado", "Cinco bandas de evidencia, desglose por detector, mapa de "
                           "atención, metadatos forenses y procedencia C2PA si existe"],
             ["Cadena de custodia", "Cada informe se firma con HMAC-SHA256 sobre la huella "
                                    "SHA-256 del archivo, el score y la marca de tiempo"],
             ["Planes", "Gratuito (5 análisis al día, sin registro), Profesional y Pericial, "
                        "con cobro en modo demostración"],
             ["Historial", "Guardado en el navegador de cada persona; el servidor no expone "
                           "los análisis de otros"]],
            [4, 13])

    I.h2("2.1 Cómo leer el resultado")
    I.p("La página traduce la probabilidad de manipulación a una banda. Las bandas "
        "son el mensaje principal; el porcentaje es secundario.")
    I.tabla(["Probabilidad", "Banda", "Qué significa"],
            [["menos de 20 %", "Evidencia muy baja", "Ninguna señal relevante"],
             ["20 – 40 %", "Evidencia baja", "Señales débiles dentro de la variación normal"],
             ["40 – 60 %", "Inconclusa", "Los detectores no coinciden; conviene revisión manual"],
             ["60 – 80 %", "Evidencia moderada", "Varias señales de generación o edición"],
             ["80 % o más", "Evidencia fuerte", "Señales consistentes en varios detectores"]],
            [3.5, 4, 9.5])

    # ---------------------------------------------------------------- 3
    I.h1("3. Arquitectura")
    I.p("El sistema separa la parte pública, que es gratuita y siempre está "
        "disponible, del cómputo, que necesita una GPU:")
    I.tabla(["Componente", "Tecnología", "Función"],
            [["Página web", "Next.js 14.2.35, exportación estática en GitHub Pages",
              "Subida de archivos, resultado, planes, historial local"],
             ["API", "FastAPI 0.115.14 en Render, modo `API_ONLY`",
              "Valida, aplica cuotas, encola y entrega resultados; no carga modelos"],
             ["Cola y resultados", "Redis en Upstash (TLS)",
              "Broker de Celery, resultados y latido del worker"],
             ["Worker de cómputo", "Celery 5.6 con GPU local (RTX 4070 SUPER, 12 GB)",
              "Seis detectores, meta-ensemble, LLaVA; colas images, videos y default"],
             ["Monitor", "GitHub Actions", "Comprueba API y Redis cada 3 horas"]],
            [3.3, 6.2, 7.5])
    I.p("Flujo de un análisis: la página envía el archivo a la API; la API lo valida "
        "(tipo, tamaño, cuota del plan) y lo encola en Redis con la prioridad del plan; "
        "el worker lo toma, lo analiza y escribe el resultado; la página consulta el "
        "estado hasta recibirlo. El worker escribe un latido en Redis cada 30 segundos "
        "con caducidad de 90; la API lo usa para decir a la página si hay capacidad de "
        "cómputo disponible.")
    I.nota("Condición de servicio",
           "La página analiza solo mientras el worker está encendido. Es el componente de "
           "cómputo del despliegue, no un entorno de pruebas.", "info")

    # ---------------------------------------------------------------- 4
    I.h1("4. Cómo se analiza una imagen")
    I.h2("4.1 Los seis detectores")
    I.tabla(["Detector", "Modelo", "Qué aporta"],
            [["Face-Deepfake ViT", "prithivMLmods/Deep-Fake-Detector-v2-Model",
              "Rostros manipulados"],
             ["SDXL Detector", "Organika/sdxl-detector", "Imagen generada por difusión"],
             ["Sonda CLIP ViT-L/14", "CLIP ViT-L/14 + MLP propio",
              "Huella de generadores, entrenada en el proyecto"],
             ["AI Art Detector", "haywoodsloan/ai-image-detector-deploy",
              "Ilustración y arte generado"],
             ["SigLIP 2 Deepfake", "prithivMLmods/Deepfake-Detect-Siglip2",
              "Deepfake general"],
             ["AI-Human Detector", "umm-maybe/AI-image-detector",
              "Fotografía real frente a generada"]],
            [4, 6.5, 6.5])
    I.p("Junto a ellos se calculan dos señales forenses clásicas —espectro de "
        "frecuencias y residuo de ruido SRM— y un detector de imágenes fuera de "
        "dominio que reduce la confianza cuando la imagen no se parece a nada de lo "
        "entrenado.")

    I.h2("4.2 Compuerta de contenido y rama de rostro")
    I.p("Antes de combinar, una compuerta basada en CLIP clasifica la imagen como "
        "**fotografía** u **obra gráfica** (umbral 0,55), porque los detectores se "
        "comportan de forma distinta en cada caso. Si MTCNN encuentra un rostro, se "
        "evalúa además una **rama de rostro** con su propio cabezal.")

    I.h2("4.3 Meta-ensemble")
    I.p("Tres cabezales LightGBM aprenden a combinar las salidas de los detectores: "
        "uno general, uno para fotografía sin arte y uno para rostros. Se reentrenaron "
        "y adoptaron el 17 de noviembre de 2026 (sección 6).")
    I.p("En fotografía, el score con rostro es el **máximo** entre la rama de rostro y "
        "la de imagen completa (mezcla «o»): un rostro que no es un intercambio no "
        "puede rebajar una imagen que la rama completa reconoce como generada. En obra "
        "gráfica se conserva una mezcla lineal con peso 0,30.")

    I.h2("4.4 Lectura semántica y metadatos")
    I.p("LLaVA-1.5-7B, cuantizado a 4 bits (unos 7,1 GB de VRAM), describe la escena y "
        "señala incoherencias visuales. En paralelo se leen los metadatos: EXIF, "
        "software de edición, generadores de IA declarados en XMP y manifiestos de "
        "procedencia C2PA. Un archivo que declara haber sido creado por una IA es la "
        "evidencia más directa posible, aunque se borra al reenviar la imagen.")

    I.h2("4.5 Sello de custodia")
    I.p("El resultado se sella con HMAC-SHA256 sobre la huella SHA-256 del archivo "
        "original, el score y la marca de tiempo, con una clave que nunca sale del "
        "servidor. Permite comprobar después que un informe corresponde a ese archivo "
        "exacto y que no se modificó.")

    # ---------------------------------------------------------------- 5
    I.h1("5. Cómo se mide")
    I.p("Hasta septiembre de 2026 toda cifra de validación se calculaba sobre las mismas "
        "fuentes con las que se entrenaba. Eso compara configuraciones entre sí, pero no "
        "dice qué pasa ante una fotografía o un generador nuevos. Desde noviembre las "
        "cifras de calidad se miden **fuera de muestra**:")
    I.tabla(["Conjunto", "Contenido", "Uso"],
            [["E1 · Retenido", "7.000 imágenes: LFW (2.000) e ImageNet (2.000) auténticas; "
                               "FLUX (1.500) y DALL·E 3 (1.500) generadas",
              "Confirmación oficial sobre 2.000; desarrollo en un tramo aparte"],
             ["E2 · Reddit", "Subconjunto «reddit» de OpenFake: fotografía moderna «en la "
                             "calle» (632 en confirmación)",
              "Segundo conjunto de confirmación, desde el 16 nov"],
             ["FaceForensics++", "Vídeos de intercambio de rostro",
              "KPI-01; dentro de muestra, es el único material de este tipo disponible"]],
            [3.2, 8.5, 5.3])
    I.p("El criterio de adopción se escribe y se versiona **antes** de entrenar ningún "
        "candidato (`reports/CRITERIO_AMPLIADO_20261116.md`, commit 148ca9f). Cada "
        "conjunto se parte en desarrollo y confirmación, y la confirmación se mira una "
        "sola vez. Las variantes se reevalúan con las mismas funciones de producción; "
        "la variante de control reprodujo el score de producción con diferencia máxima "
        "0,00 sobre 4.865 imágenes.")

    # ---------------------------------------------------------------- 6
    I.h1("6. Resultados")
    I.h2("6.1 El cambio adoptado el 17 de noviembre")
    I.p("Un retrato fotorrealista generado por IA se puntuaba en un 18 %. El análisis "
        "encontró una **fuga de stacking**: la sonda CLIP se entrena con las mismas "
        "fuentes que el meta-ensemble, donde es casi perfecta, así que el segundo nivel "
        "aprendió a fiarse de ella (64 % del peso). Sobre fotografía moderna esa sonda "
        "falla mucho: AUC 0,79 frente a 0,987 en el retenido.")
    I.p("Se añadieron 13.877 imágenes externas de OpenFake —fotografía de LAION y Pexels "
        "y 45 generadores modernos, excluidos FLUX y DALL·E 3 para no contaminar el "
        "retenido— y se reentrenaron los cabezales.")
    I.tabla(["Conjunto de confirmación", "Métrica", "Antes", "Después"],
            [["E1 · Retenido (2.000)", "Falsas alarmas", "1,20 %", "**0,90 %**"],
             ["", "IA señalada", "78,0 %", "**84,9 %**"],
             ["", "AUC", "0,9887", "**0,9947**"],
             ["E2 · Reddit (632)", "Falsas alarmas", "18,67 %", "**14,24 %**"],
             ["", "IA señalada", "75,3 %", "**84,8 %**"],
             ["", "AUC", "0,840", "**0,911**"],
             ["FaceForensics++ (KPI-01)", "Deepfake facial señalado", "94,0 %", "**95,0 %**"]],
            [5.5, 5, 3, 3])
    I.p("Un reentrenamiento de control **sin** los datos externos no cambió nada: la "
        "mejora la ponen los datos, no el reentrenamiento. Medido después por la vía de "
        "producción completa, con el sistema ya instalado, el resultado fue idéntico a "
        "la predicción. El retrato que abrió el caso pasó del 18 % al 51 %: ya no se "
        "declara auténtico, aunque queda en «inconclusa».")

    I.h2("6.2 Indicadores del proyecto")
    I.tabla(["KPI", "Definición", "Meta", "Valor", "Fuente"],
            [["KPI-01", "Deepfakes faciales señalados", "≥ 60 %", "95,0 %",
              "`reports/produccion_ffpp*.json`"],
             ["KPI-02", "Fotografía auténtica marcada por error", "≤ 8 %", "0,9 %",
              "`reports/heldout_eval_bandas.json`"],
             ["KPI-03", "AUC fuera de muestra", "≥ 0,90", "0,995",
              "`reports/heldout_eval.json`"],
             ["KPI-04", "Latencia del ensemble, p95", "≤ 15 s", "11,7 s",
              "`reports/latencia_medida.json`"]],
            [1.8, 5.2, 1.8, 1.9, 6.3])

    I.h2("6.3 Latencia")
    I.p("Medida sobre análisis reales por la vía de producción "
        "(`reports/latencia_medida.json`, 41 análisis con la GPU dedicada):")
    I.tabla(["", "Mediana", "Percentil 95"],
            [["Análisis completo, lo que espera el usuario", "32,4 s", "61,6 s"],
             ["Solo el ensemble, sin la lectura semántica", "5,3 s", "11,7 s"]],
            [9, 4, 4])
    I.p("Si otras aplicaciones ocupan la VRAM, LLaVA pasa en parte a la CPU y un "
        "análisis puede tardar decenas de minutos (mediana de 1.709 s en los 8 casos "
        "medidos así). Por eso el worker comprueba la memoria libre antes de arrancar.")

    I.h2("6.4 Evolución")
    I.p("Las cifras de septiembre se midieron dentro de muestra y con una confusión "
        "entre clase y origen de los datos; se conservan como registro de lo que se "
        "creía entonces, no como término de comparación válido.")
    I.tabla(["", "Septiembre 2026", "9 nov 2026", "17 nov 2026 (vigente)"],
            [["Deepfakes faciales señalados", "49,9 %", "94,0 %", "95,0 %"],
             ["Falsas alarmas en fotografía", "12,5 %", "1,20 % *", "0,90 %"],
             ["AUC", "0,883", "0,9887 *", "0,9947"],
             ["Pruebas automatizadas", "58", "78", "138"]],
            [6, 3.5, 3.5, 4])
    I.p("* Valor remedido el 17 de noviembre con el procedimiento nuevo. El informe del "
        "9 de noviembre publicó un 0,7 % que se calculó antes de un cambio de código "
        "posterior; la corrección está documentada en `reports/MEJORA_ENSEMBLE_v4.md`, "
        "sección 12.", GRIS, 9.5)

    # ---------------------------------------------------------------- 7
    I.h1("7. Modelo de negocio")
    I.p("El recurso escaso es el **tiempo de GPU**: con una tarjeta y concurrencia 2, "
        "el techo práctico ronda los 150 análisis por hora. Por eso se cobra por "
        "capacidad y no por calidad: el análisis es idéntico en todos los planes.")
    I.tabla(["", "Gratuito", "Profesional", "Pericial"],
            [["Precio mensual", "$0", "$9.990 CLP", "$29.990 CLP"],
             ["Precio anual", "—", "$99.900 CLP", "$299.900 CLP"],
             ["Cuota", "5 análisis al día", "300 al mes", "1.500 al mes"],
             ["Prioridad en la cola", "1", "5", "9"],
             ["Video y análisis por lote", "—", "sí", "sí"],
             ["Acceso por API", "—", "—", "sí"],
             ["Historial", "1 día", "90 días", "365 días"]],
            [5, 3.5, 4, 4])
    I.p("**Implementado:** catálogo, licencias firmadas sin base de datos ni datos "
        "personales, contador de consumo en Redis, identidad anónima por dispositivo, "
        "prioridad en la cola según el plan y pasarela simulada que recorre el flujo "
        "completo sin mover dinero.")
    I.p("**Deliberadamente no implementado:** la llamada real a Flow o Mercado Pago y "
        "la concesión de licencias por webhook. Una integración de cobro a medias en "
        "una página pública puede aceptar dinero real que nadie sabe devolver, y un "
        "webhook sin verificar la firma de la pasarela permitiría regalarse una "
        "suscripción. Ambas cosas se escriben juntas, con la cuenta de la pasarela "
        "creada y supervisando la primera transacción. Tampoco está generado aún el "
        "informe PDF sellado, que es el derecho que más justifica el precio.")
    I.nota("Antes de cobrar",
           "Resolver la licencia no comercial de los datos de entrenamiento (sección 10) "
           "y la parte tributaria: boleta o factura, IVA e inscripción de la actividad en "
           "el SII. Detalle en `reports/MODELO_DE_NEGOCIO.md`.", "aviso")

    # ---------------------------------------------------------------- 8
    I.h1("8. Operación")
    I.h2("8.1 Puesta en marcha del worker")
    I.p("`INICIAR PAGINA WEB.bat`, o el acceso directo «DeepScan Worker», abre el "
        "panel de control del worker. El panel:")
    I.vinetas([
        "comprueba el entorno, que no haya otro worker y la memoria de GPU libre;",
        "arranca el worker y muestra la carga de cada uno de los diez pasos (2 a 4 minutos);",
        "enseña en vivo la memoria y el uso de la GPU, cada análisis con su resultado y "
        "duración, y si la página publicada ve el worker;",
        "guarda toda la salida en `reports/worker.log`.",
    ])
    I.p("Cerrar el panel detiene el worker: corre dentro de un *job object* de Windows "
        "y nunca queda un proceso huérfano ocupando la GPU. La versión de consola sigue "
        "disponible en `scripts/worker_consola.bat`.")
    I.h2("8.2 Despliegue y vigilancia")
    I.vinetas([
        "**Página:** se publica sola en GitHub Pages con cada push a `main` que cambie `frontend/`.",
        "**API:** Render no se redespliega sola; tras cambiar el backend hay que hacer "
        "*Manual Deploy* en su panel.",
        "**Monitor:** GitHub Actions comprueba API y Redis cada 3 horas.",
        "**Caída de Redis:** procedimiento en `docs/RUNBOOK_REDIS_DOWN.md`.",
    ])
    I.h2("8.3 Secretos")
    I.p("`DEEPGUARD_SIGNING_KEY` (sello de custodia) y `DEEPGUARD_BILLING_KEY` "
        "(licencias) son independientes a propósito y viven solo en el entorno de "
        "Render y en `backend/.env`, que nunca se versiona. Comprometer la facturación "
        "no debe comprometer la prueba forense.")

    # ---------------------------------------------------------------- 9
    I.h1("9. Calidad y seguridad")
    I.p("La batería de **138 pruebas automatizadas** cubre la fusión de detectores, el "
        "parser de LLaVA, cuotas y licencias, límites de subida, el catálogo que muestra "
        "la página, las dependencias de los modelos y el panel del worker. Se ejecuta "
        "con `venv\\Scripts\\python -m pytest -q` desde `backend/`.")
    I.p("La auditoría del 17 de noviembre (documento aparte en esta misma carpeta) "
        "encontró doce hallazgos, cuatro graves. Once están corregidos y verificados en "
        "producción; el restante es la licencia de los datos.")

    # ---------------------------------------------------------------- 10
    I.h1("10. Límites conocidos")
    I.vinetas([
        "**Fotografía moderna «en la calle»:** 14,2 % de falsas alarmas en Reddit, frente "
        "al 0,9 % en LFW e ImageNet. El sistema es mucho más fiable con fotografía del "
        "estilo de su entrenamiento que con fotografía moderna de alta resolución.",
        "**Rostros enteramente sintéticos:** el cabezal facial aprendió intercambio de "
        "rostro y no los reconoce. La mezcla «o» evita que los rebaje, pero no los detecta "
        "por sí mismo.",
        "**KPI-01 es un techo:** se mide dentro de muestra, porque FaceForensics++ es el "
        "único material de intercambio de rostro disponible.",
        "**La sonda CLIP sigue entrenada solo con fuentes antiguas.** El arreglo de fondo "
        "es reentrenarla con fotografía moderna, reservando otra parte de OpenFake para el "
        "meta-ensemble.",
        "**Licencia de datos:** los cabezales vigentes usan OpenFake, CC BY-NC 4.0.",
        "**Un solo worker:** la capacidad depende de un equipo y una tarjeta.",
    ])

    # ---------------------------------------------------------------- 11
    I.h1("11. Trabajo pendiente")
    I.tabla(["Tarea", "Por qué"],
            [["Reentrenar la sonda CLIP con fotografía moderna",
              "Ataca la causa de las falsas alarmas en Reddit"],
             ["Cabezal facial con retratos sintéticos como clase positiva",
              "Hoy no reconoce rostros generados; exige revalidar KPI-01"],
             ["Informe PDF sellado", "Es el derecho de pago con más valor"],
             ["Resolver la licencia de los datos y la del repositorio", "Requisito para cobrar"],
             ["Integración real con Flow y verificación de firma del webhook",
              "Solo con la cuenta creada y supervisión"],
             ["50 a 100 fotografías propias del dueño para validación",
              "Material real del caso de uso, fuera de cualquier fuente pública"]],
            [8, 9])

    # ---------------------------------------------------------------- 12
    I.h1("12. Procedencia de las cifras")
    I.tabla(["Cifra", "Archivo", "Tipo"],
            [["KPI-01, 95,0 %", "`reports/produccion_ffpp*.json`", "dentro de muestra"],
             ["KPI-02, 0,9 %", "`reports/heldout_eval_bandas.json`", "fuera de muestra"],
             ["KPI-03, 0,995", "`reports/heldout_eval.json`", "fuera de muestra"],
             ["KPI-04 y latencias", "`reports/latencia_medida.json`", "vía de producción"],
             ["Confirmación E1 y E2", "`reports/repeticion_oficial.json`, "
                                      "`reports/repeticion_e2_conf.json`", "fuera de muestra"],
             ["Control sin datos externos", "`reports/repeticion_dev_control.json`", "desarrollo"],
             ["Criterio de adopción", "`reports/CRITERIO_AMPLIADO_20261116.md`", "previo al entrenamiento"],
             ["Registro completo", "`reports/MEJORA_ENSEMBLE_v4.md`", "—"]],
            [4.5, 8, 4.5])
    return I.guardar("DeepScan_Informe_Tecnico_2026-11-18.docx")


if __name__ == "__main__":
    for ruta in (auditoria(), informe_tecnico()):
        print("escrito:", ruta.relative_to(RAIZ))

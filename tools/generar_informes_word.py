# -*- coding: utf-8 -*-
"""
Genera los informes vigentes en Word, en la carpeta informes/ (local, fuera
del repositorio), con el formato de la plantilla de INACAP
(TIHI84_U2_ES2_Plantilla_informe_Guia_ABPro):

- DeepScan_Informe_del_Proyecto_2026-11-25.docx
    Copia del informe ES2, que ya sigue la plantilla y se mantiene al dia con
    scripts/actualizar_cifras_entregables.py y scripts/verificar_entregables.py.
- DeepScan_Auditoria_2026-11-17.docx
    La auditoria (reports/AUDITORIA_20261117.md) montada SOBRE el informe ES2:
    misma portada, estilos Titulo1 / Subtitulo1 / PARRAFO / PIE DE FOTO,
    tablas con el mismo formato y el pie "Desarrollo del Proyecto de Titulo".
    Se conserva la portada y se sustituye el cuerpo.

    python tools/generar_informes_word.py

El indice es un campo TOC: se rellena al abrir el documento en Word
(clic derecho > Actualizar campo) o con el paso de Word de la verificacion.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

RAIZ = Path(__file__).resolve().parent.parent
ES2 = RAIZ / "evaluacion 2 proyecto de tituulo" / "TIHI84_U2_ES2_InformeDeepScan_RojasLiapiz.docx"
SALIDA = RAIZ / "informes"
AUTORES = "Gabriel Rojas y Vicente Liapiz"

ANCHO_DXA = 12240 - 2 * 1418          # carta, margenes de la plantilla
CABECERA = "1F3D6A"                   # mismos colores que las tablas del ES2
CEBRA = "EDF2F7"
BORDE = "9AA7B4"


# =============================================================================
# Utilidades sobre el documento base
# =============================================================================

def _texto(parrafo: Paragraph, nuevo: str) -> None:
    """Cambia el texto conservando el formato del primer run."""
    runs = parrafo.runs
    runs[0].text = nuevo
    for r in runs[1:]:
        r._r.getparent().remove(r._r)


def _celda_texto(celda, nuevo: str) -> None:
    _texto(celda.paragraphs[0], nuevo)
    for p in celda.paragraphs[1:]:
        p._p.getparent().remove(p._p)


class Plantilla:
    """Un documento con el formato del ES2: portada propia y cuerpo nuevo."""

    def __init__(self, titulo_informe: str, subtitulo_informe: str,
                 entregable: str, fecha: str) -> None:
        self.d = docx.Document(ES2)
        self.n_tabla = 0
        self._portada(titulo_informe, subtitulo_informe, entregable, fecha)
        self._vaciar_cuerpo()

    # ------------------------------------------------------------- portada
    def _portada(self, titulo, subtitulo, entregable, fecha) -> None:
        ps = self.d.paragraphs
        _texto(next(p for p in ps if p.text.startswith("Informe de Desarrollo")), titulo)
        _texto(next(p for p in ps if p.text.startswith("Evaluación Sumativa")), subtitulo)
        # La plantilla deja tres parrafos vacios antes de la tabla de la portada
        # y la tabla no cabe: se parte y «Docente» y «Fecha» pasan a la pagina
        # 2 (le ocurre tambien al informe ES2). Con uno basta.
        t = self.d.tables[0]
        previo = t._tbl.getprevious()
        quitados = 0
        while quitados < 2 and previo is not None and previo.tag == qn("w:p") \
                and not Paragraph(previo, self.d).text.strip():
            anterior = previo.getprevious()
            previo.getparent().remove(previo)
            previo, quitados = anterior, quitados + 1
        # Y una linea en blanco menos entre el subtitulo del sistema y el
        # titulo del informe, para que quepa la ultima fila («Fecha»).
        tit = next(p for p in self.d.paragraphs if p.text == titulo)._p
        vacio = tit.getprevious()
        if vacio is not None and vacio.tag == qn("w:p") and not Paragraph(vacio, self.d).text.strip():
            vacio.getparent().remove(vacio)
        for fila in t.rows:
            clave = fila.cells[0].text.strip()
            if clave.startswith("Entregable"):
                _celda_texto(fila.cells[1], entregable)
            elif clave.startswith("Fecha"):
                _celda_texto(fila.cells[1], fecha)

    def _vaciar_cuerpo(self) -> None:
        """Deja portada y el titulo «Contenido»; quita indice y cuerpo del ES2."""
        cuerpo = self.d.element.body
        hijos = list(cuerpo)
        i_contenido = next(i for i, e in enumerate(hijos)
                           if e.tag == qn("w:p") and Paragraph(e, self.d).text.strip() == "Contenido")
        for e in hijos[i_contenido + 1:]:
            if e.tag != qn("w:sectPr"):
                cuerpo.remove(e)
        # Indice como campo, para que Word ponga las paginas.
        p = self.d.add_paragraph(style="toc 1")
        self._campo(p, 'TOC \\h \\z \\t "Título1;1;Subtitulo1;2"',
                    "Clic derecho → Actualizar campo para generar el índice.")
        self.salto()

    @staticmethod
    def _campo(parrafo, instruccion: str, marcador: str) -> None:
        for tipo, texto in (("begin", None), ("instr", instruccion), ("separate", None),
                            ("texto", marcador), ("end", None)):
            r = parrafo.add_run()
            if tipo == "instr":
                it = OxmlElement("w:instrText")
                it.set(qn("xml:space"), "preserve")
                it.text = texto
                r._r.append(it)
            elif tipo == "texto":
                r.text = texto
            else:
                f = OxmlElement("w:fldChar")
                f.set(qn("w:fldCharType"), tipo)
                r._r.append(f)

    # ------------------------------------------------------------- bloques
    def salto(self) -> None:
        from docx.enum.text import WD_BREAK
        self.d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def titulo(self, texto: str) -> None:
        p = self.d.add_paragraph(texto, style="Título1")
        p.paragraph_format.keep_with_next = True

    def subtitulo(self, numero: str, texto: str) -> None:
        p = self.d.add_paragraph(f"{numero}\t{texto}", style="Subtitulo1")
        # El estilo Subtitulo1 de la plantilla trae su propia lista numerada,
        # y el numero ya va escrito: sin esto sale «1. 2.1». numId 0 la anula
        # solo en este parrafo.
        numPr = OxmlElement("w:numPr")
        for tag, val in (("w:ilvl", "0"), ("w:numId", "0")):
            e = OxmlElement(tag)
            e.set(qn("w:val"), val)
            numPr.append(e)
        pPr = p._p.get_or_add_pPr()
        pPr.insert(1, numPr)
        p.paragraph_format.keep_with_next = True
        p.paragraph_format.space_before = docx.shared.Pt(6)

    def parrafo(self, texto: str, estilo: str = "PARRAFO") -> Paragraph:
        """Texto con **negrita** en linea, en el estilo de cuerpo del ES2."""
        p = self.d.add_paragraph(style=estilo)
        partes = texto.split("**")
        for k, trozo in enumerate(partes):
            if trozo:
                r = p.add_run(trozo)
                if k % 2 == 1:
                    r.bold = True
        return p

    def apartado(self, texto: str) -> None:
        """Cabecera de bloque dentro de un subtitulo: PARRAFO en negrita, como
        «Gestión de cambios» en el ES2."""
        self.parrafo(f"**{texto}**")

    def lista(self, items: list[str]) -> None:
        for letra, it in zip("abcdefghijklmnopqrstuvwxyz", items):
            self.parrafo(f"{letra}) {it}")

    def referencia(self, texto: str) -> None:
        p = self.d.add_paragraph(style="Estilo3")
        partes = texto.split("*")
        for k, trozo in enumerate(partes):
            if trozo:
                r = p.add_run(trozo)
                if k % 2 == 1:
                    r.italic = True

    def tabla(self, pie: str, cab: list[str], filas: list[list[str]],
              anchos: list[float], negrita_col0: set[str] | None = None) -> None:
        self.n_tabla += 1
        cap = self.d.add_paragraph(f"Tabla {self.n_tabla}. {pie}", style="PIE DE FOTO")
        cap.paragraph_format.keep_with_next = True
        corta = len(filas) <= 8   # las cortas, enteras en una pagina con su pie
        total = sum(anchos)
        w = [int(a * ANCHO_DXA / total) for a in anchos]
        t = self.d.add_table(rows=1 + len(filas), cols=len(cab))
        tblPr = t._tbl.tblPr
        jc = OxmlElement("w:jc")
        jc.set(qn("w:val"), "center")
        tblPr.append(jc)
        bordes = OxmlElement("w:tblBorders")
        for lado in ("top", "left", "bottom", "right", "insideH", "insideV"):
            e = OxmlElement(f"w:{lado}")
            for k, v in (("val", "single"), ("sz", "4"), ("space", "0"), ("color", BORDE)):
                e.set(qn(f"w:{k}"), v)
            bordes.append(e)
        tblPr.append(bordes)
        grid = t._tbl.tblGrid
        for gc, ancho in zip(grid.findall(qn("w:gridCol")), w):
            gc.set(qn("w:w"), str(ancho))
        for i, fila in enumerate(t.rows):
            datos = cab if i == 0 else filas[i - 1]
            if i == 0:
                trPr = fila._tr.get_or_add_trPr()
                trPr.append(OxmlElement("w:tblHeader"))
            else:
                trPr = fila._tr.get_or_add_trPr()
                trPr.append(OxmlElement("w:cantSplit"))
            for j, (celda, valor) in enumerate(zip(fila.cells, datos)):
                tcPr = celda._tc.get_or_add_tcPr()
                tcW = OxmlElement("w:tcW")
                tcW.set(qn("w:type"), "dxa")
                tcW.set(qn("w:w"), str(w[j]))
                tcPr.append(tcW)
                fondo = CABECERA if i == 0 else (CEBRA if i % 2 == 0 else None)
                if fondo:
                    shd = OxmlElement("w:shd")
                    shd.set(qn("w:val"), "clear")
                    shd.set(qn("w:color"), "auto")
                    shd.set(qn("w:fill"), fondo)
                    tcPr.append(shd)
                p = celda.paragraphs[0]
                p.paragraph_format.space_after = docx.shared.Twips(40)
                if corta and i < len(filas):
                    p.paragraph_format.keep_with_next = True
                partes = valor.split("**")
                for k, trozo in enumerate(partes):
                    if not trozo:
                        continue
                    r = p.add_run(trozo)
                    r.font.size = docx.shared.Pt(8.5)
                    if i == 0:
                        r.bold = True
                        r.font.color.rgb = docx.shared.RGBColor(0xFF, 0xFF, 0xFF)
                    elif k % 2 == 1 or (j == 0 and negrita_col0 and valor in negrita_col0):
                        r.bold = True
        self.d.add_paragraph(style="PARRAFO")

    def guardar(self, nombre: str) -> Path:
        SALIDA.mkdir(exist_ok=True)
        cp = self.d.core_properties
        cp.author = AUTORES
        cp.last_modified_by = AUTORES
        ruta = SALIDA / nombre
        self.d.save(ruta)
        return ruta


# =============================================================================
# Auditoría
# =============================================================================

def auditoria() -> Path:
    D = Plantilla("Informe de Auditoría del Proyecto",
                  "Revisión técnica — Noviembre de 2026",
                  "Auditoría técnica del proyecto",
                  "17 de noviembre de 2026 · seguimiento al 25 de noviembre")

    # ---------------------------------------------------------------- I
    D.titulo("Introducción")
    D.parrafo("El presente informe documenta la auditoría técnica de DeepScan, sistema de "
              "análisis forense digital para la detección de contenido visual generado o "
              "manipulado por inteligencia artificial, realizada el 17 de noviembre de 2026 "
              "sobre el sistema en producción: la página web publicada en GitHub Pages, la "
              "API en Render, la cola de tareas en Upstash Redis y el worker de cómputo con "
              "GPU.")
    D.parrafo("El objetivo fue comprobar que el sistema publicado es seguro, que su "
              "instalación es reproducible y que lo que declaran sus documentos coincide con "
              "lo que el sistema hace. Los hallazgos se contrastaron con el sistema real o "
              "con el código, y las correcciones de mayor riesgo en el código cuentan con "
              "una prueba automatizada que falla si el defecto reaparece.")
    D.parrafo("Se identificaron **doce hallazgos**: cuatro de gravedad alta, cinco de gravedad "
              "media y tres de gravedad baja. Once están corregidos; los que afectan a la API y "
              "al monitor se verificaron en producción el 18 de noviembre de 2026. El restante, "
              "la licencia no comercial de una fuente de datos de entrenamiento, no se resuelve "
              "con código: es una decisión del equipo previa a cualquier cobro por el servicio. "
              "El 25 de noviembre se añadió un seguimiento con dos observaciones nuevas "
              "(sección 4.3).")

    # ---------------------------------------------------------------- II
    D.titulo("Alcance y metodología")
    D.subtitulo("2.1", "Frentes revisados.")
    D.parrafo("La revisión cubrió seis frentes, elegidos por ser los que pueden afectar a "
              "un usuario del servicio o a la validez de los resultados declarados.")
    D.tabla("Frentes revisados y criterio aplicado",
            ["Frente", "Qué se revisó"],
            [["Seguridad", "Secretos en los archivos y en todo el historial de git, endpoints "
                           "expuestos, límites de subida y exposición de la configuración"],
             ["Dependencias", "Que todo lo que el código importa esté declarado, y "
                              "vulnerabilidades conocidas en los paquetes de Python y npm"],
             ["API en vivo", "CORS, endpoints que utiliza la página y flujo de facturación"],
             ["Frontend", "Que cada pantalla funcione contra la API publicada"],
             ["Coherencia documental", "Que las cifras del README, los informes y los "
                                       "entregables coincidan con las medidas"],
             ["Higiene del repositorio", "Carpetas privadas, archivos de gran tamaño y restos "
                                         "de trabajo"]],
            [3.2, 9])
    D.subtitulo("2.2", "Criterio de cierre de un hallazgo.")
    D.parrafo("Un hallazgo se da por cerrado cuando la corrección está aplicada y comprobada por "
              "el medio que corresponde: una prueba automatizada si es un defecto de código que "
              "puede reaparecer, la respuesta del sistema publicado si afecta al despliegue, o la "
              "lectura del documento si es de documentación. Cuatro de las correcciones cuentan "
              "con prueba de regresión (Anexo A): dependencias de los modelos, límite de subida, "
              "historial y exposición de credenciales en la configuración.")

    # ---------------------------------------------------------------- III
    D.titulo("Hallazgos")
    D.subtitulo("3.1", "Resumen de hallazgos.")
    D.tabla("Hallazgos por gravedad y estado",
            ["Gravedad", "Hallazgos", "Corregidos", "Abiertos"],
            [["Alta", "4", "3", "1 (licencia de datos)"],
             ["Media", "5", "5", "0"],
             ["Baja", "3", "3", "0"],
             ["Total", "12", "11", "1"]],
            [3, 2.5, 2.5, 4], negrita_col0={"Alta", "Total"})
    D.tabla("Detalle de los hallazgos",
            ["Gravedad", "Hallazgo", "Estado"],
            [["Alta", "scikit-learn, joblib y lightgbm no estaban en requirements.txt: una "
                      "instalación nueva no cargaba ningún cabezal del meta-ensemble y caía en "
                      "silencio a pesos fijos", "Corregido, versiones fijadas y prueba"],
             ["Alta", "Límite de subida de 500 MB frente a 512 MB de RAM en Render, con el "
                      "archivo leído entero en memoria y copiado en Base64",
              "Corregido: 100 MB y rechazo previo, con prueba"],
             ["Alta", "El endpoint /api/v1/history devolvía los análisis de todos los usuarios "
                      "sin pedir identidad", "Corregido: desactivado, con prueba"],
             ["Alta", "Cabezales entrenados con OpenFake, licencia CC BY-NC 4.0 (no comercial), "
                      "frente a un modelo de negocio de pago",
              "Documentado; decisión pendiente antes de cobrar"],
             ["Media", "python-multipart 0.0.6 y starlette 0.27 con vulnerabilidades de "
                       "denegación de servicio en el procesado de subidas",
              "Corregido: FastAPI 0.115.14, python-multipart 0.0.20"],
             ["Media", "Next.js 14.0.4 con un aviso crítico y axios con avisos altos",
              "Corregido: Next.js 14.2.35, axios 1.21"],
             ["Media", "La configuración mostraba fragmentos de claves al imprimirse",
              "Corregido: campos ocultos, con prueba"],
             ["Media", "Un cabezal que no cargaba solo dejaba un aviso",
              "Corregido: se registra como error"],
             ["Media", "El README describía otro sistema y declaraba una licencia MIT inexistente",
              "Corregido: reescrito con cifras medidas"],
             ["Baja", "ESTRUCTURA_PROYECTO.md describía los cabezales anteriores", "Corregido"],
             ["Baja", "Monitor de salud de GitHub Actions desactivado por inactividad desde el "
                      "1 de noviembre", "Reactivado el 18 de noviembre"],
             ["Baja", "«API» aparecía en el menú principal de la página",
              "Movido al pie de página"]],
            [1.8, 7.6, 3.6], negrita_col0={"Alta"})

    D.subtitulo("3.2", "Dependencias de los modelos sin declarar.")
    D.parrafo("**Descripción.** El meta-ensemble, que decide el resultado final de cada "
              "análisis, se guarda como modelos LightGBM serializados con joblib. Ninguna de "
              "esas librerías figuraba en backend/requirements.txt. En el equipo de "
              "desarrollo funcionaba porque estaban instaladas manualmente.")
    D.parrafo("**Impacto.** En una instalación limpia los tres cabezales fallaban al cargar y "
              "el sistema continuaba operando con pesos fijos, sin ningún error visible y con "
              "una capacidad de detección muy inferior a la medida y declarada.")
    D.parrafo("**Corrección.** Se fijaron las versiones exactas scikit-learn 1.8.0, joblib "
              "1.5.3, lightgbm 4.6.0 y xgboost 3.2.0. La prueba test_requisitos_modelos "
              "comprueba que todo lo que importan los modelos esté declarado, y un cabezal que "
              "no carga queda registrado como error con su consecuencia.")

    D.subtitulo("3.3", "Límite de subida y memoria de la API.")
    D.parrafo("**Descripción.** La API aceptaba archivos de hasta 500 MB, los leía enteros en "
              "memoria y los copiaba en Base64 para enviarlos al worker, mientras el plan de "
              "Render dispone de 512 MB de RAM.")
    D.parrafo("**Impacto.** Una sola petición podía agotar la memoria y detener la API para "
              "todos los usuarios, un caso de denegación de servicio sin necesidad de "
              "credenciales.")
    D.parrafo("**Corrección.** El límite se redujo a 100 MB, el mismo que el acuerdo de nivel de "
              "servicio comprometido para video, y la API rechaza con el código HTTP 413 a "
              "partir de la cabecera Content-Length, antes de leer el archivo. La prueba "
              "test_limite_subida verifica que el archivo y su copia caben con holgura en la "
              "memoria disponible.")

    D.subtitulo("3.4", "Historial global expuesto.")
    D.parrafo("**Descripción.** GET /api/v1/history devolvía los resultados de los análisis de "
              "todos los usuarios a cualquier persona que lo solicitara. La página no lo "
              "utilizaba, porque guarda el historial de cada usuario en su propio navegador.")
    D.parrafo("**Impacto.** Exposición de información de terceros, clasificada en OWASP Top 10 "
              "como control de acceso defectuoso (A01:2021).")
    D.parrafo("**Corrección.** El endpoint responde 404 salvo que se active expresamente la "
              "variable HISTORIAL_PUBLICO. Prueba asociada: test_historial_global.")

    D.subtitulo("3.5", "Licencia de los datos de entrenamiento.")
    D.parrafo("Desde el 17 de noviembre de 2026 los cabezales del meta-ensemble incorporan "
              "13.877 imágenes del conjunto OpenFake (ComplexDataLab), publicado bajo licencia "
              "Creative Commons Atribución-NoComercial 4.0. Para un proyecto de título la "
              "licencia no supone un problema; para un servicio de pago, sí.")
    D.parrafo("Antes de cobrar existen dos alternativas: reentrenar los cabezales sin esas "
              "filas, con otra fuente externa de licencia comercial, u obtener una licencia del "
              "autor. Los detectores preentrenados de HuggingFace tienen también licencias "
              "propias que deben revisarse para un uso comercial.")

    D.subtitulo("3.6", "Hallazgos de gravedad media y baja.")
    D.parrafo("Los cinco hallazgos de gravedad media se corrigieron actualizando dependencias "
              "con vulnerabilidades conocidas, ocultando las credenciales en la representación "
              "de la configuración, elevando a error la carga fallida de un cabezal y "
              "reescribiendo el README con cifras medidas y su procedencia. Los tres de "
              "gravedad baja corresponden a documentación desactualizada, al monitor de salud "
              "desactivado y a la ubicación del enlace a la API en la página.")

    # ---------------------------------------------------------------- IV
    D.titulo("Verificación")
    D.subtitulo("4.1", "Aspectos comprobados sin hallazgos.")
    D.lista([
        "Secretos: ninguno en los archivos versionados ni en todo el historial de git. Los "
        "archivos de entorno versionados contienen solo ejemplos y la URL pública de la API.",
        "Carpetas privadas (entregables, evaluaciones y datos): fuera del repositorio.",
        "CORS: los cinco endpoints que utiliza la página aceptan el origen de GitHub Pages y "
        "las cabeceras de identidad.",
        "Facturación: catálogo, contratación simulada, licencia anual de 365 días y rechazo de "
        "licencias manipuladas.",
        "Repositorio: ningún archivo versionado supera 2 MB y no quedan restos de trabajo.",
    ])
    D.subtitulo("4.2", "Verificación en producción.")
    D.parrafo("Tras el despliegue manual de la API en Render, el 18 de noviembre de 2026 se "
              "comprobó contra el sistema publicado:")
    D.tabla("Verificación en producción, 18 de noviembre de 2026",
            ["Comprobación", "Resultado"],
            [["GET /api/v1/history", "404"],
             ["Subida real de 105 MB a /api/v1/analyze",
              "413, «El archivo supera el máximo de 100 MB»"],
             ["GET /api/v1/health", "Modo api-only, Redis conectado"],
             ["GET /api/v1/billing/plans", "Catálogo de planes servido"],
             ["Monitor de salud (GitHub Actions)", "Activo; ejecución del 18 de noviembre exitosa"],
             ["Análisis real de extremo a extremo",
              "Un análisis puntual, en 19,9 s (mediana formal: 32,4 s)"]],
            [6, 6.5])
    D.subtitulo("4.3", "Seguimiento del 25 de noviembre.")
    D.parrafo("Al contrastar con el código las afirmaciones de la defensa se encontraron dos "
              "defectos que la auditoría del 17 de noviembre no detectó, pese a que el primero "
              "contradecía lo que los documentos declaraban sobre privacidad.")
    D.tabla("Observaciones del seguimiento",
            ["Observación", "Estado"],
            [["El archivo original se borraba una hora después desde un hilo que moría con el "
              "worker: había 131 sin borrar. Además, la cola guardaba los argumentos de cada "
              "tarea, con la imagen en Base64, durante 24 horas",
              "Corregido y verificado con un análisis real: 0 originales en disco y sin imagen "
              "en Redis. Cinco pruebas nuevas (143 en total)"],
             ["La API publicada declara inválido un sello legítimo, porque no comparte la clave "
              "de firma con el worker. Con la clave del worker, 181 de 181 sellos verifican y "
              "uno alterado se rechaza",
              "Pendiente: igualar la clave en el entorno de la API"]],
            [8, 4.5])

    # ---------------------------------------------------------------- V
    D.titulo("Riesgo aceptado")
    D.parrafo("Persisten dos avisos de npm audit cuya corrección exige migrar a Next.js 16, un "
              "cambio de versión mayor. Se aceptan porque ninguno aplica al despliegue actual:")
    D.lista([
        "Los avisos de Next.js afectan a un servidor de Next en ejecución (optimizador de "
        "imágenes, Server Components, rewrites). La página se publica como HTML estático en "
        "GitHub Pages, de modo que ese servidor no existe.",
        "El aviso de PostCSS se ejecuta solo durante la compilación, sobre el CSS propio del "
        "proyecto, y no procesa datos de terceros.",
    ])
    D.parrafo("Si el frontend pasara a servirse con un servidor de Next.js, la actualización "
              "dejaría de ser opcional.")

    # ---------------------------------------------------------------- VI
    D.titulo("Plan de acción")
    D.subtitulo("6.1", "Acciones del equipo.")
    D.tabla("Acciones derivadas de la auditoría",
            ["Acción", "Responsable", "Estado"],
            [["Desplegar la API corregida en Render", "Equipo", "Realizado el 18 nov"],
             ["Reactivar el monitor de salud", "Equipo", "Realizado el 18 nov"],
             ["Rotar la clave de facturación en Render", "Equipo", "Pendiente"],
             ["Definir la licencia del repositorio", "Equipo", "Pendiente"],
             ["Resolver la licencia de los datos de entrenamiento antes de cobrar",
              "Equipo", "Pendiente"],
             ["Igualar DEEPGUARD_SIGNING_KEY entre la API y el worker", "Equipo", "Pendiente"],
             ["Desplegar en Render el borrado de la copia de la API", "Equipo", "Pendiente"]],
            [8, 2.5, 3])

    # ---------------------------------------------------------------- VII
    D.titulo("Conclusiones")
    D.parrafo("Tras las correcciones no se encontraron secretos en el repositorio ni análisis "
              "de terceros accesibles, y la instalación es reproducible: las dependencias de las "
              "que depende el resultado están declaradas con su versión exacta. El cierre del "
              "historial y el límite de subida se verificaron en producción.")
    D.parrafo("El hallazgo más instructivo no fue de seguridad sino de reproducibilidad: un "
              "sistema que, ante una dependencia ausente, sigue funcionando con un detector "
              "peor y sin avisar, es más peligroso que uno que falla. El seguimiento dejó una "
              "segunda lección: una declaración de privacidad debe comprobarse mirando el disco "
              "y la cola, no leyendo la intención del código.")
    D.parrafo("Queda abierta una decisión que no es técnica: la licencia no comercial de los "
              "datos de entrenamiento. Es compatible con el proyecto de título, pero condiciona "
              "cualquier paso hacia la explotación comercial del servicio.")

    # ---------------------------------------------------------------- VIII
    D.titulo("Referencias bibliográficas")
    for ref in [
        "Creative Commons. (s.f.). *Atribución-NoComercial 4.0 Internacional (CC BY-NC 4.0)*. "
        "https://creativecommons.org/licenses/by-nc/4.0/deed.es",
        "Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *RFC 9110: HTTP semantics*. "
        "Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9110",
        "INACAP. (2024). *Guía para citas y referencias bibliográficas según Norma APA 7ª "
        "edición*. https://digital.inacap.cl/documentos/biblioteca/Norma_APA_7ma_ed_v2.pdf",
        "Livernoche, V., Arodi, A., Musulan, A., Yang, Z., Salvail, A., Marceau Caron, G., "
        "Godbout, J.-F., & Rabbany, R. (2025). *OpenFake: An open dataset and platform toward "
        "real-world deepfake detection*. arXiv. https://arxiv.org/abs/2509.09495",
        "National Institute of Standards and Technology. (2024a). *CVE-2024-24762* [Base de "
        "datos]. National Vulnerability Database. https://nvd.nist.gov/vuln/detail/CVE-2024-24762",
        "National Institute of Standards and Technology. (2024b). *CVE-2024-47874* [Base de "
        "datos]. National Vulnerability Database. https://nvd.nist.gov/vuln/detail/CVE-2024-47874",
        "National Institute of Standards and Technology. (2025). *CVE-2025-29927* [Base de "
        "datos]. National Vulnerability Database. https://nvd.nist.gov/vuln/detail/CVE-2025-29927",
        "OWASP Foundation. (2021). *OWASP Top 10:2021 — The ten most critical web application "
        "security risks*. https://owasp.org/Top10/",
    ]:
        D.referencia(ref)

    # ---------------------------------------------------------------- IX
    D.titulo("Anexos")
    D.parrafo("**Anexo A. Pruebas automatizadas incorporadas por la auditoría**")
    D.tabla("Pruebas que protegen las correcciones",
            ["Prueba", "Qué garantiza"],
            [["test_requisitos_modelos", "Todo lo que importan los modelos está declarado en "
                                         "requirements.txt"],
             ["test_limite_subida", "El límite cabe en la RAM de Render y una subida enorme se "
                                    "rechaza sin leerla; la configuración no muestra secretos"],
             ["test_historial_global", "El historial de todos los usuarios no es accesible"],
             ["test_retencion (25 nov)", "El original se borra al terminar, también si el "
                                         "análisis falla, y Redis no guarda la imagen"],
             ["test_catalogo_frontend", "Los precios y cuotas que muestra la página coinciden "
                                        "con los del servidor"]],
            [4.5, 8])
    D.parrafo("**Anexo B. Fuentes**")
    D.parrafo("El registro completo de la auditoría se conserva en el repositorio del proyecto "
              "en reports/AUDITORIA_20261117.md, y las correcciones en los commits d8b7811 "
              "(auditoría) y 4bdea31 (verificación en producción).")
    return D.guardar("DeepScan_Auditoria_2026-11-17.docx")


def informe_proyecto() -> Path:
    SALIDA.mkdir(exist_ok=True)
    destino = SALIDA / "DeepScan_Informe_del_Proyecto_2026-11-25.docx"
    shutil.copy2(ES2, destino)
    return destino


if __name__ == "__main__":
    for ruta in (informe_proyecto(), auditoria()):
        print("escrito:", ruta.relative_to(RAIZ))

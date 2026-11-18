# -*- coding: utf-8 -*-
"""
Figuras 5, 8 y 9 del informe ES2 (componentes, infraestructura y arquitectura),
redibujadas el 18 nov 2026 con el estado real del sistema: tres cabezales
LightGBM, politica "gated" del detector de arte IA, LLaVA en cada analisis,
7,1 GB de VRAM medidos al arranque y GitHub Actions sin pruebas automatizadas.

Mismo tamano (1953 px de ancho, 155 ppp), paleta y disposicion que las
originales, para sustituirlas en el documento sin alterar la maquetacion.

    python tools/figuras_informe.py <carpeta de salida>
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402

DPI = 155
ANCHO_PX = 1953

NAVY = "#24406b"
AZUL = "#2f6fb5"
DORADO = "#b8860b"
TEAL = "#2a8a9a"
TEXTO = "#1f2d3d"
GRIS = "#6f7f92"
F_PRES = "#e9eef6"
F_COMP = "#e5f3f0"
F_BROKER = "#fff4d6"
F_ROJO = "#fdeee8"
F_GRIS = "#f0f0f0"


def lienzo(alto_px):
    fig = plt.figure(figsize=(ANCHO_PX / DPI, alto_px / DPI), dpi=DPI)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100 * alto_px / ANCHO_PX)
    ax.axis("off")
    return fig, ax


def caja(ax, x, y, w, h, texto, fondo, borde, tam=7.2, color=TEXTO, negrita=False, lw=1.3):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.8",
                                fc=fondo, ec=borde, lw=lw))
    ax.text(x + w / 2, y + h / 2, texto, ha="center", va="center", fontsize=tam,
            color=color, fontweight="bold" if negrita else "normal", linespacing=1.35)


def grupo(ax, x, y, w, h, etiqueta=None, color=GRIS, tam=7.5, estilo="--", fondo="none"):
    ax.add_patch(Rectangle((x, y), w, h, fill=fondo != "none", fc=fondo, ec=color,
                           lw=1.0, ls=estilo))
    if etiqueta:
        ax.text(x + w / 2, y + h + 0.6, etiqueta, ha="center", va="bottom", fontsize=tam,
                color=color, style="italic")


def flecha(ax, x1, y1, x2, y2, color=NAVY, estilo="-|>", ls="-", etiqueta=None, rad=0.0):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=estilo, mutation_scale=9,
                                 color=color, lw=1.1, ls=ls,
                                 connectionstyle=f"arc3,rad={rad}"))
    if etiqueta:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.9, etiqueta, ha="center", va="bottom",
                fontsize=6.3, color=NAVY)


def titulo(ax, y, texto):
    ax.text(50, y, texto, ha="center", va="center", fontsize=11, fontweight="bold", color=NAVY)


# =============================================================================
def figura_componentes(ruta):
    fig, ax = lienzo(1157)
    H = 100 * 1157 / ANCHO_PX
    titulo(ax, H - 2.2, "Diagrama de componentes — DeepScan")

    grupo(ax, 2.5, 39.5, 30, 14.5, "Capa de presentación")
    grupo(ax, 36, 39.5, 30, 14.5, "Capa de orquestación")
    grupo(ax, 69.5, 39.5, 28, 14.5, "Mensajería")
    caja(ax, 5.5, 47.5, 24, 5, "UI Next.js 14\n(TypeScript)", F_PRES, NAVY)
    caja(ax, 5.5, 41, 24, 4.2, "Cliente HTTP\n(polling)", F_PRES, NAVY)
    caja(ax, 39, 47.5, 24, 5, "API FastAPI\n(OpenAPI 3.1)", F_PRES, NAVY)
    caja(ax, 39, 41, 24, 4.2, "Validador de archivos\n(límite 100 MB)", F_PRES, NAVY)
    caja(ax, 72, 44, 23, 6.5, "Broker Redis\n(Upstash, TLS)\ncola + resultados", F_BROKER, DORADO)
    flecha(ax, 17.5, 47.5, 17.5, 45.3)
    flecha(ax, 29.5, 43, 39, 43, etiqueta="HTTPS/REST")
    flecha(ax, 63, 50, 72, 48.5, etiqueta="publica")
    flecha(ax, 83.5, 44, 83.5, 35.6, color=GRIS, ls="--")
    ax.text(84.5, 37.4, "consume tarea", ha="left", va="center", fontsize=6.3, color=GRIS)

    grupo(ax, 2.5, 2, 95, 33.5, "Capa de cómputo — Worker Celery (GPU local)")
    filas = [
        ["Orquestador de\nanálisis", "Compuerta de tipo\nde contenido (CLIP)", "Detector OOD\n(heurístico)"],
        ["Ensemble de 6\ndetectores GPU\n(PyTorch)", "Meta-ensemble\n3 cabezales LightGBM\n(completo · sin arte · facial)", "Señales CPU\nFFT · SRM · ELA"],
        ["Correcciones\nforenses (4 reglas)", "Inspección semántica\nLLaVA-1.5-7B (4 bits)", "Grad-CAM++\n(mapa de calor)"],
        [None, "Servicio de custodia\nHMAC-SHA256", None],
    ]
    xs = [6.5, 37, 67.5]
    ys = [28.5, 20.5, 12.5, 4.5]
    for fy, fila in zip(ys, filas):
        for fx, t in zip(xs, fila):
            if t:
                caja(ax, fx, fy, 25.5, 5.6, t, F_COMP, TEAL, tam=6.9)
    c = 12.75
    flecha(ax, xs[0] + 25.5, ys[0] + 2.8, xs[1], ys[0] + 2.8)
    flecha(ax, xs[1] + 25.5, ys[0] + 2.8, xs[2], ys[0] + 2.8)
    flecha(ax, xs[0] + c, ys[0], xs[0] + c, ys[1] + 5.6)
    flecha(ax, xs[0] + 25.5, ys[1] + 2.8, xs[1], ys[1] + 2.8)
    flecha(ax, xs[2], ys[1] + 2.8, xs[1] + 25.5, ys[1] + 2.8)
    flecha(ax, xs[1] + 2, ys[1], xs[0] + 20, ys[2] + 5.6)
    flecha(ax, xs[0] + 25.5, ys[2] + 2.8, xs[1], ys[2] + 2.8)
    flecha(ax, xs[1] + c, ys[2], xs[1] + c, ys[3] + 5.6)
    fig.savefig(ruta, dpi=DPI)
    plt.close(fig)


# =============================================================================
def figura_infraestructura(ruta):
    fig, ax = lienzo(1097)
    H = 100 * 1097 / ANCHO_PX
    titulo(ax, H - 2.2, "Diagrama de infraestructura — DeepScan")

    grupo(ax, 2.5, 30, 95, 21, color=AZUL)
    ax.text(50, 51.9, "NUBE PÚBLICA (capa gratuita)", ha="center", fontsize=7.5,
            color=AZUL, fontweight="bold")
    caja(ax, 5.5, 41.5, 25, 8, "GitHub Pages\n\nCDN global\nHTTPS automático\nSin servidor propio", F_PRES, NAVY)
    caja(ax, 37.5, 41.5, 25, 8, "Render.com\n\n512 MB RAM · 0.1 vCPU\nContenedor Linux\nSuspensión por inactividad", F_PRES, NAVY)
    caja(ax, 69.5, 41.5, 25, 8, "Upstash Redis\n\n256 MB · TLS\n10.000 comandos/día\nPersistencia AOF", F_PRES, NAVY)
    caja(ax, 21.5, 32.5, 57, 5.5,
         "GitHub Actions — publicación automática del frontend\n"
         "y verificación de salud de la API y Redis cada 3 horas", F_GRIS, GRIS)

    grupo(ax, 2.5, 2, 95, 23.5, color=TEAL)
    ax.text(50, 26.2, "INFRAESTRUCTURA LOCAL (estación de cómputo)", ha="center", fontsize=7.5,
            color=TEAL, fontweight="bold")
    caja(ax, 5.5, 14, 27, 8.5, "GPU NVIDIA\nRTX 4070 SUPER\n12 GB GDDR6X\nCUDA 12.4", F_COMP, TEAL)
    caja(ax, 36.5, 14, 27, 8.5, "CPU AMD Ryzen 7 7700X\n32 GB DDR5\nWindows 11", F_COMP, TEAL)
    caja(ax, 67.5, 14, 27, 8.5, "Almacenamiento NVMe\n~24 GB de pesos de modelos\n(14 GB de LLaVA)\nCaché HuggingFace", F_COMP, TEAL)
    caja(ax, 5.5, 4, 89, 7.5,
         "Worker Celery — 6 detectores GPU + LLaVA-1.5-7B (4 bits) residentes (7,1 GB de VRAM, medidos al arranque)\n"
         "+ meta-ensemble de 3 cabezales LightGBM + señales CPU (FFT, SRM, ELA)\n"
         "Compuerta de contenido reutiliza el CLIP ViT-L/14 del detector C: 0 VRAM adicional",
         F_COMP, TEAL, tam=7)
    fig.savefig(ruta, dpi=DPI)
    plt.close(fig)


# =============================================================================
def figura_arquitectura(ruta):
    fig, ax = lienzo(1217)
    H = 100 * 1217 / ANCHO_PX
    titulo(ax, H - 2.2, "Diagrama de arquitectura — DeepScan (microservicios asíncronos)")

    caja(ax, 5, 52, 90, 5,
         "CAPA DE PRESENTACIÓN — Next.js 14 + TypeScript · GitHub Pages · polling HTTP",
         NAVY, NAVY, tam=7.5, color="white", negrita=True)
    flecha(ax, 50, 52, 50, 50.6, color=GRIS)
    caja(ax, 5, 44.3, 90, 6,
         "CAPA DE ORQUESTACIÓN — FastAPI (OpenAPI 3.1) sobre Render.com\n"
         "Gateway sin estado · validación MIME · límite de carga 100 MB · CORS estricto · publicación de tareas",
         AZUL, AZUL, tam=7.2, color="white", negrita=True)
    flecha(ax, 50, 44.3, 50, 42.9, color=GRIS)
    caja(ax, 5, 37.6, 90, 5,
         "CAPA DE MENSAJERÍA — Upstash Redis (TLS) · cola Celery · resultados con TTL 24 h",
         DORADO, DORADO, tam=7.5, color="white", negrita=True)
    flecha(ax, 50, 37.6, 50, 36.2, color=GRIS)

    ax.add_patch(Rectangle((5, 4.5), 90, 31.5, fc="#f6fafb", ec=TEAL, lw=1.2))
    ax.text(50, 34.4, "CAPA DE CÓMPUTO — Worker Celery sobre GPU local", ha="center",
            fontsize=7.5, color=TEAL, fontweight="bold")
    caja(ax, 8, 27, 40, 5.5, "Compuerta de tipo de contenido\nCLIP ViT-L/14 zero-shot\nfotografía vs obra gráfica", F_COMP, TEAL, tam=6.6)
    caja(ax, 52, 27, 40, 5.5, "Detector OOD (heurístico)\n5 señales de imagen\nafiche / texto renderizado", F_COMP, TEAL, tam=6.6)
    flecha(ax, 28, 27, 28, 25.3, color=TEAL)
    ax.text(50, 24.4, "Ensemble de detectores GPU (PyTorch)", ha="center", fontsize=6.6,
            color=NAVY, style="italic")
    det = [("A · ViT\nrostros", F_PRES, NAVY), ("B · SDXL\ndetector", F_PRES, NAVY),
           ("C · CLIP\nprobe MLP", F_PRES, NAVY), ("D · Arte IA\n(solo en fotografía)", F_ROJO, "#c0392b"),
           ("E · SigLIP\ndeepfake", F_PRES, NAVY), ("F · AI-Human\ndetector", F_PRES, NAVY)]
    for i, (t, fo, bo) in enumerate(det):
        caja(ax, 8 + i * 14.2, 17.8, 12.6, 5.2, t, fo, bo, tam=6.4)
    flecha(ax, 50, 17.8, 50, 16.3, color=GRIS)
    caja(ax, 8, 7, 27.5, 8.6,
         "Meta-ensemble · 3 cabezales LightGBM\ncompleto · sin arte IA · facial\n"
         "mezcla «o» con rostro\ncalibración por temperatura", "#e8f5ec", "#2e8b57", tam=6.4)
    caja(ax, 36.3, 7, 27.5, 8.6,
         "Análisis semántico\nLLaVA-1.5-7B (4 bits)\ncoherencia visual de la escena\nfusionado con el porcentaje",
         "#e8f5ec", "#2e8b57", tam=6.4)
    caja(ax, 64.5, 7, 27.5, 8.6,
         "Correcciones forenses (4 reglas)\n+ señales CPU: FFT · SRM · ELA\n+ cadena de custodia HMAC-SHA256",
         "#e8f5ec", "#2e8b57", tam=6.4)
    flecha(ax, 35.5, 11.3, 36.3, 11.3, color=GRIS)
    flecha(ax, 63.8, 11.3, 64.5, 11.3, color=GRIS)
    ax.text(50, 2.2,
            "El detector de arte IA (D) participa en el porcentaje forense solo en fotografía; "
            "en obra gráfica queda fuera. Su puntuación se informa siempre por separado.",
            ha="center", fontsize=6.4, color="#c0392b", style="italic")
    fig.savefig(ruta, dpi=DPI)
    plt.close(fig)


if __name__ == "__main__":
    salida = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    salida.mkdir(parents=True, exist_ok=True)
    figura_componentes(salida / "figura5_componentes.png")
    figura_infraestructura(salida / "figura8_infraestructura.png")
    figura_arquitectura(salida / "figura9_arquitectura.png")
    print("ok", salida)

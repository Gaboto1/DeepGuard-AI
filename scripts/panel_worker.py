# -*- coding: utf-8 -*-
"""
Panel de control del worker GPU de DeepScan.

Sustituye a la ventana de consola de `INICIAR PAGINA WEB.bat`. Hace lo mismo
que hacia aquella -comprobar el equipo, arrancar Celery con la GPU y guardar
toda su salida en reports/worker.log- pero lo presenta como una aplicacion:

- el estado en una palabra (apagado, cargando, en servicio, analizando);
- la carga de cada modelo, paso a paso, en vez de un muro de texto;
- memoria y uso de la GPU en vivo;
- cada analisis que llega, con su resultado y lo que tardo;
- si la pagina publicada ve de verdad a este worker (consulta /health);
- el registro, filtrado a lo que importa, con el detalle tecnico a un clic.

Todo sale de la salida real del worker y de nvidia-smi: el panel no inventa
estados. Si una linea del worker cambia de formato, el paso correspondiente se
queda sin marcar, pero el worker sigue funcionando igual.

El worker se lanza dentro de un "job object" de Windows: si el panel se cierra
o se cuelga, el worker muere con el. Sin eso podria quedar un worker huerfano
ocupando la GPU sin nadie que lea su salida.

La version de consola sigue disponible en scripts/worker_consola.bat.
"""
from __future__ import annotations

import ctypes
import json
import math
import os
import queue
import re
import statistics
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from collections import deque
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BACKEND = RAIZ / "backend"
LOG = RAIZ / "reports" / "worker.log"
LOG_PANEL = RAIZ / "reports" / "panel_worker.log"
CELERY = BACKEND / "venv" / "Scripts" / "celery.exe"
ICONO = Path(__file__).resolve().parent / "deepscan.ico"
PAGINA = "https://gaboto1.github.io/DeepGuard-AI/"

# Mismo umbral y misma justificacion que scripts/preparar_worker.ps1.
VRAM_MINIMA_MIB = 8700

# Procesos que suelen llevarse VRAM en este equipo, para poder nombrarlos.
GOLOSOS = re.compile(
    r"opera|chrome|msedge|firefox|league|riotclient|wallpaper|discord|spotify|"
    r"overwolf|bluestacks|genesis|chatgpt|copilot|ms-teams|steamwebhelper", re.I)

SIN_VENTANA = 0x08000000      # CREATE_NO_WINDOW
SUSPENDIDO = 0x00000004       # CREATE_SUSPENDED

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _url_api() -> str:
    try:
        for linea in (RAIZ / "frontend" / ".env.production").read_text(encoding="utf-8").splitlines():
            if linea.startswith("NEXT_PUBLIC_API_URL="):
                return linea.split("=", 1)[1].strip().rstrip("/")
    except OSError:
        pass
    return "https://deepguard-ai-api.onrender.com"


# =============================================================================
# Lectura de la salida del worker (sin interfaz: se prueba por separado)
# =============================================================================

# Pasos de carga en el orden en que aparecen. Cada uno se da por terminado
# cuando el worker escribe la linea que lo confirma; no se presupone el orden,
# de modo que si el codigo cambia la secuencia el panel sigue acertando.
PASOS = [
    ("vit",     "Detector facial ViT",        "rostros manipulados",   re.compile(r"SUCCESS.*\[face-deepfake-vit\]")),
    ("sdxl",    "Detector SDXL",              "imagen generada",       re.compile(r"SUCCESS.*\[sdxl-detector\]")),
    ("clip",    "Sonda CLIP ViT-L/14",        "huella de generadores", re.compile(r"SUCCESS.*\[CLIP-C\]")),
    ("arte",    "Detector de obra gráfica",   "ilustración y arte",    re.compile(r"SUCCESS.*\[ai-art-detector\]")),
    ("siglip",  "SigLIP 2",                   "deepfake general",      re.compile(r"SUCCESS.*\[siglip-deepfake\]")),
    ("humano",  "Detector IA o humano",       "fotografía",            re.compile(r"SUCCESS.*\[ai-human-detector\]")),
    ("rostros", "Compuerta y rostros",        "tipo de contenido",     re.compile(r"Face detector \(MTCNN\) loaded")),
    ("meta",    "Meta-ensemble",              "3 cabezales LightGBM",  re.compile(r"SUCCESS.*\[meta:face\]")),
    ("llava",   "LLaVA-1.5 7B",               "lectura de la escena",  re.compile(r"LLaVA listo")),
    ("cola",    "Conexión con la cola",       "Upstash Redis",         re.compile(r"\bready\.\s*$")),
]
CLAVES = [p[0] for p in PASOS]

RE_LOGURU = re.compile(
    r"^\d{4}-\d\d-\d\d (\d\d:\d\d:\d\d)\.\d+ \| (\w+)\s*\| [\w.]+:[\w<>]+:\d+ - (.*)$")
RE_CELERY = re.compile(r"^\[\d{4}-\d\d-\d\d (\d\d:\d\d:\d\d),\d+: (\w+)/[\w-]+\] (.*)$")
RE_TAREA = r"Task app\.tasks\.analysis_tasks\.analyze_(image|video)_task\[([0-9a-f-]+)\] "
RE_RECIBIDA = re.compile(RE_TAREA + r"received")
RE_OK = re.compile(RE_TAREA + r"succeeded in ([0-9.]+)s")
RE_FALLO = re.compile(RE_TAREA + r"(?:raised|failed)")
RE_PCT = re.compile(r"'manipulation_probability': ([0-9.]+)")
RE_INICIO = re.compile(r"inicializando modelos GPU")

TIPO = {"image": "Imagen", "video": "Video"}


def coma(x: float, dec: int = 1) -> str:
    return f"{x:.{dec}f}".replace(".", ",")


def banda(pct: float) -> str:
    """Las cinco bandas que muestra la pagina (ComoLeerElResultado)."""
    if pct < 20:
        return "muy baja"
    if pct < 40:
        return "baja"
    if pct < 60:
        return "inconclusa"
    if pct < 80:
        return "moderada"
    return "fuerte"


def clasificar(linea: str):
    """(hora, nivel, mensaje). Nivel 'otro' para lo que no es una linea de log."""
    m = RE_LOGURU.match(linea)
    if m:
        return m.group(1), m.group(2).upper(), m.group(3)
    m = RE_CELERY.match(linea)
    if m:
        return m.group(1), m.group(2).upper(), m.group(3)
    return "", "OTRO", linea


def resumen_simple(linea: str):
    """
    Version legible de una linea para la vista normal del registro, o None si
    en esa vista no aporta (latidos, barras de progreso, avisos de librerias).
    """
    hora, nivel, msg = clasificar(linea)
    if nivel in ("OTRO", "DEBUG"):
        return None
    if nivel == "WARNING" and ("site-packages" in msg or "does not have exif" in msg):
        return None
    m = RE_OK.search(msg)
    if m:
        pct = RE_PCT.search(msg)
        extra = f" · {coma(float(pct.group(1)), 0)} % (evidencia {banda(float(pct.group(1)))})" if pct else ""
        return hora, "SUCCESS", f"{TIPO[m.group(1)]} {m.group(2)[:8]} analizada en {coma(float(m.group(3)))} s{extra}"
    m = RE_RECIBIDA.search(msg)
    if m:
        return hora, "INFO", f"{TIPO[m.group(1)]} {m.group(2)[:8]} recibida, analizando"
    if len(msg) > 240:
        msg = msg[:240] + "…"
    return hora, nivel, msg


class Lector:
    """Convierte la salida del worker en estado. No sabe nada de la interfaz."""

    def __init__(self) -> None:
        self.reiniciar()

    def reiniciar(self) -> None:
        self.hechos: set[str] = set()
        self.fallidos: set[str] = set()
        self.cargando = False
        self.listo = False
        self.t_inicio_carga: float | None = None
        self.t_listo: float | None = None
        self.en_curso: dict[str, float] = {}
        self.completados = 0
        self.errores = 0
        self.duraciones: deque[float] = deque(maxlen=200)
        self.actividad: deque[dict] = deque(maxlen=40)
        self.avisos: list[str] = []
        self.ultimo_error = ""
        self.version = 0          # sube cada vez que cambia algo visible

    def paso_actual(self) -> str | None:
        if not self.cargando or self.listo:
            return None
        for clave in CLAVES:
            if clave not in self.hechos:
                return clave
        return None

    def _aviso(self, texto: str) -> None:
        if texto not in self.avisos:
            self.avisos.append(texto)

    def _entrada(self, tid: str, tipo: str) -> dict:
        for a in self.actividad:
            if a["id"] == tid:
                return a
        a = {"id": tid, "tipo": tipo, "estado": "curso", "t0": time.time(),
             "hora": datetime.now().strftime("%H:%M:%S"), "dur": None, "pct": None}
        self.actividad.appendleft(a)
        return a

    def procesar(self, linea: str) -> bool:
        antes = self.version
        hora, nivel, msg = clasificar(linea)

        if RE_INICIO.search(linea):
            self.cargando = True
            self.t_inicio_carga = time.time()
            self.version += 1

        for clave, _, _, patron in PASOS:
            if clave not in self.hechos and patron.search(linea):
                self.hechos.add(clave)
                self.cargando = True
                if clave == "cola":
                    self.listo = True
                    self.t_listo = time.time()
                self.version += 1

        if "CARGA FALLIDA" in linea:
            self.fallidos.add("meta")
            self._aviso("Un cabezal del meta-ensemble no cargó: el worker usa pesos "
                        "fijos y detecta peor. Revisa el registro.")
            self.version += 1
        if "VRAM INSUFICIENTE" in linea:
            self.fallidos.add("llava")
            self._aviso("LLaVA no cabe entero en la GPU y corre en parte en CPU: cada "
                        "análisis tardará minutos. Cierra navegadores y juegos y reinicia.")
            self.version += 1

        m = RE_RECIBIDA.search(linea)
        if m:
            tipo, tid = m.group(1), m.group(2)
            self.en_curso[tid] = time.time()
            self._entrada(tid, tipo)
            self.version += 1

        m = RE_OK.search(linea)
        if m:
            tipo, tid, dur = m.group(1), m.group(2), float(m.group(3))
            self.en_curso.pop(tid, None)
            a = self._entrada(tid, tipo)
            a["estado"], a["dur"] = "ok", dur
            pct = RE_PCT.search(linea)
            if pct:
                a["pct"] = float(pct.group(1))
            self.completados += 1
            self.duraciones.append(dur)
            self.version += 1

        m = RE_FALLO.search(linea)
        if m:
            tipo, tid = m.group(1), m.group(2)
            t0 = self.en_curso.pop(tid, None)
            a = self._entrada(tid, tipo)
            a["estado"] = "error"
            a["dur"] = time.time() - t0 if t0 else None
            self.errores += 1
            self.ultimo_error = msg[:300]
            self.version += 1
        elif nivel in ("ERROR", "CRITICAL"):
            self.ultimo_error = msg[:300]
            self.version += 1

        return self.version != antes


# =============================================================================
# Sistema: comprobaciones previas, GPU, procesos
# =============================================================================

def _sin_ventana_kwargs() -> dict:
    return {"creationflags": SIN_VENTANA} if os.name == "nt" else {}


def leer_gpu() -> dict | None:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,memory.free,"
             "utilization.gpu,temperature.gpu,name", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, **_sin_ventana_kwargs())
        c = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
        # Algunos controladores dan la temperatura con decimales ("50.24").
        n = [int(float(x)) for x in c[:5]]
        return {"usada": n[0], "total": n[1], "libre": n[2],
                "uso": n[3], "temp": n[4], "nombre": c[5]}
    except Exception:
        return None


def workers_ajenos(excluir: set[int] | None = None) -> list:
    import psutil
    excluir = excluir or set()
    hallados = []
    for p in psutil.process_iter(["pid", "ppid", "name", "cmdline"]):
        try:
            if p.info["pid"] in excluir or p.info["pid"] == os.getpid():
                continue
            cmd = " ".join(p.info["cmdline"] or []).lower()
            if "celery" in cmd and "worker" in cmd and "panel_worker" not in cmd:
                hallados.append(p)
        except Exception:
            continue
    # Solo las raices: celery.exe lanza un python.exe hijo, y es el mismo worker.
    pids = {p.info["pid"] for p in hallados}
    return [p for p in hallados if p.info["ppid"] not in pids]


def comprobar() -> dict:
    res = {"errores": [], "ajenos": [], "gpu": None, "golosos": []}
    if not CELERY.exists():
        res["errores"].append("No hay entorno virtual en backend\\venv. Créalo con "
                              "«python -m venv venv» e instala requirements.txt.")
    if not (BACKEND / ".env").exists():
        res["errores"].append("Falta backend\\.env. Sin él el worker busca un Redis local "
                              "en vez de Upstash y nunca recibe tareas.")
    res["ajenos"] = [p.info["pid"] for p in workers_ajenos()]
    res["gpu"] = leer_gpu()
    if res["gpu"] and res["gpu"]["libre"] < VRAM_MINIMA_MIB:
        import psutil
        uso: dict[str, int] = {}
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                n = (p.info["name"] or "").removesuffix(".exe")
                if GOLOSOS.search(n):
                    uso[n] = uso.get(n, 0) + p.info["memory_info"].rss
            except Exception:
                continue
        res["golosos"] = [n for n, _ in sorted(uso.items(), key=lambda x: -x[1])][:6]
    return res


def matar_arbol(pid: int, espera: float = 8.0) -> None:
    import psutil
    try:
        raiz = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    procs = raiz.children(recursive=True) + [raiz]
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    _, vivos = psutil.wait_procs(procs, timeout=espera)
    for p in vivos:
        try:
            p.kill()
        except Exception:
            pass


class _Trabajo:
    """Job object de Windows con KILL_ON_JOB_CLOSE: el worker muere con el panel."""

    def __init__(self) -> None:
        self.h = None
        if os.name != "nt":
            return
        from ctypes import wintypes
        k = ctypes.windll.kernel32

        class BASICA(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("a", "b", "c", "d", "e", "f")]

        class EXTENDIDA(ctypes.Structure):
            _fields_ = [("Basica", BASICA), ("Io", IO),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k.CreateJobObjectW.restype = wintypes.HANDLE
        h = k.CreateJobObjectW(None, None)
        if not h:
            return
        info = EXTENDIDA()
        info.Basica.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if k.SetInformationJobObject(wintypes.HANDLE(h), 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.h = h

    def adoptar(self, proc: subprocess.Popen) -> None:
        """Mete el proceso (creado suspendido) en el job y lo reanuda."""
        from ctypes import wintypes
        handle = wintypes.HANDLE(int(proc._handle))  # noqa: SLF001
        try:
            if self.h:
                ctypes.windll.kernel32.AssignProcessToJobObject(wintypes.HANDLE(self.h), handle)
        finally:
            # Reanudar siempre: un fallo del job no puede dejar el worker congelado.
            ctypes.windll.ntdll.NtResumeProcess(handle)


# =============================================================================
# Interfaz
# =============================================================================

# Dentro de backend\venv, Tk no encuentra su biblioteca Tcl (busca en
# <python>\lib\tcl8.6 y esta en <python>\tcl\tcl8.6): el Python base abre
# ventanas y el del venv falla con "Can't find a usable init.tcl". Se le
# indica la ruta antes de crear la ventana.
for _var, _sub in (("TCL_LIBRARY", "tcl8.6"), ("TK_LIBRARY", "tk8.6")):
    _ruta = Path(sys.base_prefix) / "tcl" / _sub
    if _var not in os.environ and _ruta.is_dir():
        os.environ[_var] = str(_ruta)

import tkinter as tk                    # noqa: E402
from tkinter import font as tkfont      # noqa: E402
from tkinter import messagebox          # noqa: E402

# La paleta de la pagina (frontend/src/app/globals.css), para que el panel y
# la web se reconozcan como el mismo producto.
BG = "#080c15"
SUP = "#0f1623"
SUP2 = "#141c2a"
ELEV = "#1a2436"
BORDE = "#1e2d42"
BORDE2 = "#253348"
TX = "#cdd5e0"
TX2 = "#9aa7b6"
TX3 = "#6f7f92"
AZUL = "#1e63d4"
AZUL2 = "#2f76ec"
VERDE = "#3fb67a"
AMBAR = "#d4ad2a"
NARANJA = "#d98a3a"
ROJO = "#e05555"

COLOR_BANDA = {"muy baja": VERDE, "baja": VERDE, "inconclusa": AMBAR,
               "moderada": NARANJA, "fuerte": ROJO}


def dibujar_icono(tam: int):
    from PIL import Image, ImageDraw
    k = 4
    s = tam * k
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.23), fill=(30, 99, 212, 255))
    escudo = [(0.50, 0.16), (0.78, 0.26), (0.78, 0.50), (0.73, 0.63), (0.63, 0.75),
              (0.50, 0.84), (0.37, 0.75), (0.27, 0.63), (0.22, 0.50), (0.22, 0.26)]
    d.polygon([(x * s, y * s) for x, y in escudo], outline=(255, 255, 255, 255),
              width=max(2, int(s * 0.055)))
    d.line([(0.37 * s, 0.50 * s), (0.47 * s, 0.60 * s), (0.64 * s, 0.40 * s)],
           fill=(255, 255, 255, 255), width=max(2, int(s * 0.065)), joint="curve")
    return im.resize((tam, tam), Image.LANCZOS)


def asegurar_ico() -> None:
    if ICONO.exists():
        return
    try:
        dibujar_icono(256).save(ICONO, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                              (64, 64), (128, 128), (256, 256)])
    except Exception:
        pass


class Icono(tk.Canvas):
    """Indicador de estado dibujado (no depende de que la fuente tenga el glifo)."""

    def __init__(self, padre, tam: int, fondo: str) -> None:
        super().__init__(padre, width=tam, height=tam, bg=fondo, highlightthickness=0, bd=0)
        self.tam = tam
        self.estado = "pendiente"
        self.angulo = 0
        self.poner("pendiente")

    def poner(self, estado: str) -> None:
        self.estado = estado
        self._dibujar()

    def girar(self) -> None:
        if self.estado == "activo":
            self.angulo = (self.angulo - 24) % 360
            self._dibujar()

    def _dibujar(self) -> None:
        self.delete("all")
        t = self.tam
        m = max(1, t * 0.1)
        g = max(1.5, t * 0.13)
        if self.estado == "pendiente":
            self.create_oval(m, m, t - m, t - m, outline=BORDE2, width=g)
        elif self.estado == "activo":
            self.create_oval(m, m, t - m, t - m, outline=BORDE, width=g)
            self.create_arc(m, m, t - m, t - m, start=self.angulo, extent=110,
                            style="arc", outline=AZUL2, width=g)
        elif self.estado == "hecho":
            self.create_oval(m, m, t - m, t - m, fill=VERDE, outline="")
            self.create_line(t * .3, t * .52, t * .45, t * .66, t * .71, t * .37,
                             fill=SUP, width=max(1.5, t * .13), capstyle="round", joinstyle="round")
        elif self.estado in ("error", "aviso"):
            c = ROJO if self.estado == "error" else AMBAR
            self.create_oval(m, m, t - m, t - m, fill=c, outline="")
            if self.estado == "error":
                self.create_line(t * .35, t * .35, t * .65, t * .65, fill=SUP, width=max(1.5, t * .12), capstyle="round")
                self.create_line(t * .65, t * .35, t * .35, t * .65, fill=SUP, width=max(1.5, t * .12), capstyle="round")
            else:
                self.create_line(t * .5, t * .28, t * .5, t * .58, fill=SUP, width=max(1.5, t * .12), capstyle="round")
                self.create_oval(t * .44, t * .66, t * .56, t * .78, fill=SUP, outline="")


class Boton(tk.Label):
    ESTILOS = {
        "primario":   (AZUL, "#ffffff", AZUL2),
        "secundario": (SUP2, TX, ELEV),
        "peligro":    ("#2a1216", "#f08080", "#3a171c"),
        "fantasma":   (SUP, TX2, SUP2),
    }

    def __init__(self, padre, texto: str, comando, tipo: str = "secundario", f=None, px=lambda n: n) -> None:
        fondo, frente, self._hover = self.ESTILOS[tipo]
        super().__init__(padre, text=texto, bg=fondo, fg=frente, font=f, cursor="hand2",
                         padx=px(16), pady=px(7), bd=0,
                         highlightthickness=1,
                         highlightbackground=BORDE2 if tipo in ("secundario", "fantasma") else fondo)
        self._fondo = fondo
        self._comando = comando
        self.bind("<Enter>", lambda e: self.config(bg=self._hover))
        self.bind("<Leave>", lambda e: self.config(bg=self._fondo))
        self.bind("<Button-1>", lambda e: self._comando())


class Tarjeta(tk.Frame):
    def __init__(self, padre, titulo: str, app: "Panel") -> None:
        super().__init__(padre, bg=SUP, highlightthickness=1, highlightbackground=BORDE)
        px = app.px
        tk.Label(self, text=titulo.upper(), bg=SUP, fg=TX3, font=app.f_etiqueta,
                 anchor="w").pack(fill="x", padx=px(16), pady=(px(13), 0))
        self.valor = tk.Label(self, text="—", bg=SUP, fg=TX, font=app.f_cifra, anchor="w")
        self.valor.pack(fill="x", padx=px(16), pady=(px(2), 0))
        self.barra = tk.Canvas(self, height=px(4), bg=SUP, highlightthickness=0)
        self.barra.pack(fill="x", padx=px(16), pady=(px(6), 0))
        self.sub = tk.Label(self, text="", bg=SUP, fg=TX2, font=app.f_peq, anchor="w")
        self.sub.pack(fill="x", padx=px(16), pady=(px(5), px(13)))
        self._frac = None
        self._color = AZUL
        self.barra.bind("<Configure>", lambda e: self._pintar())

    def poner(self, valor: str, sub: str = "", frac: float | None = None, color: str = AZUL) -> None:
        self.valor.config(text=valor)
        self.sub.config(text=sub)
        self._frac, self._color = frac, color
        self._pintar()

    def _pintar(self) -> None:
        b = self.barra
        b.delete("all")
        w, h = b.winfo_width(), int(b["height"])
        b.create_rectangle(0, 0, w, h, fill=SUP2, outline="")
        if self._frac is not None:
            b.create_rectangle(0, 0, max(0, min(1, self._frac)) * w, h, fill=self._color, outline="")


class Panel:
    def __init__(self, auto: bool = True, forzar: bool = False) -> None:
        if os.name == "nt":
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DeepScan.Worker")
            except Exception:
                pass

        self.root = tk.Tk()
        self.root.withdraw()
        self.escala = max(1.0, self.root.winfo_fpixels("1i") / 96)
        self._fuentes()

        self.q: queue.Queue = queue.Queue()
        self.lector = Lector()
        self.trabajo = _Trabajo()
        self.proc: subprocess.Popen | None = None
        self.parando = False
        self.fase = "apagado"
        self.comprobacion: dict | None = None
        self.gpu: dict | None = None
        self.api: dict = {"estado": None, "t": None}
        self.lineas: deque = deque(maxlen=4000)
        self.detalle = False
        self._version_vista = -1
        self._ultima_linea = ""

        self._construir()
        self.root.report_callback_exception = self._excepcion
        self.root.protocol("WM_DELETE_WINDOW", self.cerrar)

        threading.Thread(target=self._sondear_gpu, daemon=True).start()
        threading.Thread(target=self._sondear_api, daemon=True).start()
        self.root.after(60, self._bombear)
        self.root.after(80, self._animar)
        self.root.after(1000, self._cada_segundo)

        self.root.deiconify()
        self._barra_oscura()
        if auto:
            self.root.after(300, lambda: self.iniciar(forzar=forzar))

    # ------------------------------------------------------------- utilidades
    def px(self, n: float) -> int:
        return int(round(n * self.escala))

    def _fuentes(self) -> None:
        fams = set(tkfont.families(self.root))

        def elegir(*c):
            return next((x for x in c if x in fams), "TkDefaultFont")

        txt = elegir("Segoe UI Variable Text", "Segoe UI", "Helvetica")
        disp = elegir("Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI", "Helvetica")
        mono = elegir("Cascadia Mono", "Consolas", "Courier New")
        self.f_marca = (disp, 15, "bold")
        self.f_titulo = (disp, 17, "bold")
        self.f_seccion = (txt, 10, "bold")
        self.f_txt = (txt, 10)
        self.f_peq = (txt, 9)
        self.f_etiqueta = (txt, 8, "bold")
        self.f_cifra = (disp, 19, "bold")
        self.f_boton = (txt, 10, "bold")
        self.f_mono = (mono, 9)

    def _barra_oscura(self) -> None:
        if os.name != "nt":
            return
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            v = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(v), ctypes.sizeof(v))
        except Exception:
            pass

    def _excepcion(self, exc, val, tb) -> None:
        texto = "".join(traceback.format_exception(exc, val, tb))
        try:
            with LOG_PANEL.open("a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{texto}")
        except OSError:
            pass
        messagebox.showerror("DeepScan Worker", f"Error en el panel:\n\n{val}\n\nDetalle en reports\\panel_worker.log")

    # ------------------------------------------------------------ construcción
    def _construir(self) -> None:
        r = self.root
        px = self.px
        r.title("DeepScan · Worker GPU")
        r.configure(bg=BG)
        r.geometry(f"{px(1120)}x{px(830)}")
        r.minsize(px(940), px(680))
        asegurar_ico()
        try:
            if ICONO.exists():
                r.iconbitmap(default=str(ICONO))
            from PIL import ImageTk
            self._img_icono = ImageTk.PhotoImage(dibujar_icono(64))
            r.iconphoto(True, self._img_icono)
            self._img_logo = ImageTk.PhotoImage(dibujar_icono(px(30)))
        except Exception:
            self._img_logo = None

        cont = tk.Frame(r, bg=BG)
        cont.pack(fill="both", expand=True, padx=px(22), pady=(px(16), px(20)))
        cont.columnconfigure(0, weight=1)
        cont.rowconfigure(3, weight=1)

        # --- cabecera
        cab = tk.Frame(cont, bg=BG)
        cab.grid(row=0, column=0, sticky="ew", pady=(0, px(14)))
        if self._img_logo:
            tk.Label(cab, image=self._img_logo, bg=BG).pack(side="left")
        marca = tk.Frame(cab, bg=BG)
        marca.pack(side="left", padx=(px(10), 0))
        tk.Label(marca, text="DeepScan", bg=BG, fg="#ffffff", font=self.f_marca).pack(side="left")
        tk.Label(marca, text="  Worker GPU", bg=BG, fg=TX3, font=self.f_txt).pack(side="left", pady=(px(4), 0))

        self.pildora = tk.Frame(cab, bg=SUP, highlightthickness=1, highlightbackground=BORDE2)
        self.pildora.pack(side="right")
        self.punto = tk.Canvas(self.pildora, width=px(10), height=px(10), bg=SUP, highlightthickness=0)
        self.punto.pack(side="left", padx=(px(12), px(7)), pady=px(7))
        self.txt_pildora = tk.Label(self.pildora, text="APAGADO", bg=SUP, fg=TX2, font=self.f_etiqueta)
        self.txt_pildora.pack(side="left", padx=(0, px(13)))
        self.lbl_gpu_nombre = tk.Label(cab, text="", bg=BG, fg=TX3, font=self.f_peq)
        self.lbl_gpu_nombre.pack(side="right", padx=(0, px(14)))

        # --- estado principal
        self.heroe = tk.Frame(cont, bg=SUP, highlightthickness=1, highlightbackground=BORDE)
        self.heroe.grid(row=1, column=0, sticky="ew")
        self.heroe.columnconfigure(0, weight=1)
        izq = tk.Frame(self.heroe, bg=SUP)
        izq.grid(row=0, column=0, sticky="ew", padx=px(22), pady=px(18))
        self.lbl_titulo = tk.Label(izq, text="", bg=SUP, fg="#ffffff", font=self.f_titulo, anchor="w", justify="left")
        self.lbl_titulo.pack(fill="x")
        self.lbl_sub = tk.Label(izq, text="", bg=SUP, fg=TX2, font=self.f_txt, anchor="w", justify="left")
        self.lbl_sub.pack(fill="x", pady=(px(3), 0))
        self.lbl_api = tk.Label(izq, text="", bg=SUP, fg=TX3, font=self.f_peq, anchor="w")
        self.lbl_api.pack(fill="x", pady=(px(9), 0))
        self.botones = tk.Frame(self.heroe, bg=SUP)
        self.botones.grid(row=0, column=1, sticky="e", padx=px(22))
        self.franja = tk.Frame(self.heroe, bg=SUP)
        self.franja.grid(row=1, column=0, columnspan=2, sticky="ew")
        izq.bind("<Configure>", lambda e: self._ajustar_texto(e.width))

        # --- cifras
        cifras = tk.Frame(cont, bg=BG)
        cifras.grid(row=2, column=0, sticky="ew", pady=px(14))
        self.t_vram = Tarjeta(cifras, "Memoria de GPU", self)
        self.t_uso = Tarjeta(cifras, "Uso de GPU", self)
        self.t_analisis = Tarjeta(cifras, "Análisis en esta sesión", self)
        self.t_tiempo = Tarjeta(cifras, "Tiempo por análisis", self)
        for i, t in enumerate((self.t_vram, self.t_uso, self.t_analisis, self.t_tiempo)):
            cifras.columnconfigure(i, weight=1, uniform="c")
            t.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else px(12), 0))

        # --- cuerpo
        cuerpo = tk.Frame(cont, bg=BG)
        cuerpo.grid(row=3, column=0, sticky="nsew")
        cuerpo.columnconfigure(1, weight=1)
        cuerpo.rowconfigure(0, weight=1)

        arr = tk.Frame(cuerpo, bg=SUP, highlightthickness=1, highlightbackground=BORDE, width=px(390))
        arr.grid(row=0, column=0, sticky="nsw", padx=(0, px(12)))
        arr.grid_propagate(False)
        arr.columnconfigure(0, weight=1)
        self._construir_arranque(arr)

        der = tk.Frame(cuerpo, bg=BG)
        der.grid(row=0, column=1, sticky="nsew")
        der.columnconfigure(0, weight=1)
        der.rowconfigure(1, weight=1)
        self._construir_actividad(der)
        self._construir_registro(der)

        self._pintar_fase()

    def _encabezado(self, padre, texto: str, derecha: str = ""):
        fila = tk.Frame(padre, bg=SUP)
        fila.pack(fill="x", padx=self.px(18), pady=(self.px(14), self.px(8)))
        tk.Label(fila, text=texto, bg=SUP, fg=TX, font=self.f_seccion).pack(side="left")
        lbl = tk.Label(fila, text=derecha, bg=SUP, fg=TX3, font=self.f_peq)
        lbl.pack(side="right")
        return fila, lbl

    def _construir_arranque(self, padre) -> None:
        px = self.px
        caja = tk.Frame(padre, bg=SUP)
        caja.pack(fill="both", expand=True)
        _, self.lbl_progreso = self._encabezado(caja, "Arranque")
        self.barra_carga = tk.Canvas(caja, height=px(3), bg=SUP2, highlightthickness=0)
        self.barra_carga.pack(fill="x", padx=px(18), pady=(0, px(8)))

        self.filas: dict[str, tuple] = {}
        previos = [("entorno", "Entorno y configuración", "backend\\venv y .env"),
                   ("unico", "Sin otro worker", "una sola GPU, un solo worker"),
                   ("vram", "Memoria de GPU libre", f"conviene {VRAM_MINIMA_MIB:,} MiB".replace(",", "."))]
        for clave, nombre, det in previos + [(c, n, d) for c, n, d, _ in PASOS]:
            if clave == "vit":
                tk.Frame(caja, bg=BORDE, height=1).pack(fill="x", padx=px(18), pady=px(5))
            f = tk.Frame(caja, bg=SUP)
            f.pack(fill="x", padx=px(18), pady=px(2))
            ic = Icono(f, px(15), SUP)
            ic.pack(side="left", padx=(0, px(10)))
            n = tk.Label(f, text=nombre, bg=SUP, fg=TX3, font=self.f_txt, anchor="w")
            n.pack(side="left")
            d = tk.Label(f, text=det, bg=SUP, fg=TX3, font=self.f_peq, anchor="e")
            d.pack(side="right")
            self.filas[clave] = (ic, n, d)

    def _construir_actividad(self, padre) -> None:
        caja = tk.Frame(padre, bg=SUP, highlightthickness=1, highlightbackground=BORDE)
        caja.grid(row=0, column=0, sticky="ew", pady=(0, self.px(12)))
        _, self.lbl_act_total = self._encabezado(caja, "Actividad reciente")
        self.lista_act = tk.Frame(caja, bg=SUP)
        self.lista_act.pack(fill="x", padx=self.px(18), pady=(0, self.px(12)))
        self._iconos_act: list[Icono] = []

    def _construir_registro(self, padre) -> None:
        px = self.px
        caja = tk.Frame(padre, bg=SUP, highlightthickness=1, highlightbackground=BORDE)
        caja.grid(row=1, column=0, sticky="nsew")
        fila, _ = self._encabezado(caja, "Registro")
        self.b_detalle = tk.Label(fila, text="Mostrar detalle técnico", bg=SUP, fg=AZUL2,
                                  font=self.f_peq, cursor="hand2")
        self.b_detalle.pack(side="right")
        self.b_detalle.bind("<Button-1>", lambda e: self._alternar_detalle())
        b_log = tk.Label(fila, text="Abrir worker.log", bg=SUP, fg=TX3, font=self.f_peq, cursor="hand2")
        b_log.pack(side="right", padx=(0, px(16)))
        b_log.bind("<Button-1>", lambda e: self._abrir_log())

        marco = tk.Frame(caja, bg=BG, highlightthickness=1, highlightbackground=BORDE)
        marco.pack(fill="both", expand=True, padx=px(18), pady=(0, px(16)))
        self.txt = tk.Text(marco, bg=BG, fg=TX2, font=self.f_mono, bd=0, wrap="word",
                           padx=px(12), pady=px(10), insertbackground=TX, relief="flat",
                           selectbackground=BORDE2, height=8, spacing1=1, spacing3=1)
        self.txt.pack(fill="both", expand=True)
        self.txt.tag_config("hora", foreground=TX3)
        self.txt.tag_config("SUCCESS", foreground=VERDE)
        self.txt.tag_config("WARNING", foreground=AMBAR)
        self.txt.tag_config("ERROR", foreground=ROJO)
        self.txt.tag_config("CRITICAL", foreground=ROJO)
        self.txt.tag_config("INFO", foreground=TX)
        self.txt.tag_config("DEBUG", foreground=TX3)
        self.txt.tag_config("OTRO", foreground=TX3)
        self.txt.tag_config("PANEL", foreground=AZUL2)
        self.txt.config(state="disabled")

    def _ajustar_texto(self, ancho: int) -> None:
        for l in (self.lbl_titulo, self.lbl_sub):
            l.config(wraplength=max(200, ancho - 10))

    # ------------------------------------------------------------- acciones
    def iniciar(self, forzar: bool = False) -> None:
        if self.proc:
            return
        self.fase = "comprobando"
        self.lector.reiniciar()
        self._pintar_fase()
        self._nota("Comprobando el equipo antes de arrancar…")

        def tarea():
            self.q.put(("comprobado", comprobar(), forzar))

        threading.Thread(target=tarea, daemon=True).start()

    def _tras_comprobar(self, res: dict, forzar: bool) -> None:
        self.comprobacion = res
        if res["errores"]:
            self.fase = "bloqueado"
        elif res["ajenos"]:
            self.fase = "duplicado"
        elif res["gpu"] and res["gpu"]["libre"] < VRAM_MINIMA_MIB and not forzar:
            self.fase = "poca_vram"
        else:
            self._arrancar()
            return
        self._pintar_fase()

    def _arrancar(self) -> None:
        env = os.environ.copy()
        env.update({
            "TRANSFORMERS_CACHE": str(RAIZ / "models"),
            "HF_HOME": str(RAIZ / "models"),
            "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "NO_COLOR": "1",
        })
        cmd = [str(CELERY), "-A", "app.celery_app", "worker", "--loglevel=info", "-P", "threads",
               "-Q", "images,videos,default", "-c", "2", "-n", "deepguard-worker@%h"]
        flags = SIN_VENTANA | (SUSPENDIDO if self.trabajo.h else 0)
        try:
            self.proc = subprocess.Popen(cmd, cwd=str(BACKEND), env=env, stdin=subprocess.DEVNULL,
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         creationflags=flags)
        except OSError as e:
            self.fase = "caido"
            self.lector.ultimo_error = f"No se pudo lanzar Celery: {e}"
            self._pintar_fase()
            return
        if self.trabajo.h:
            self.trabajo.adoptar(self.proc)
        self.parando = False
        self.fase = "cargando"
        self.t_arranque = time.time()
        self._nota("Worker lanzado. Cargando los modelos en la GPU (2 a 4 minutos).")
        threading.Thread(target=self._leer_salida, args=(self.proc,), daemon=True).start()
        self._pintar_fase()

    def detener(self, y_cerrar: bool = False) -> None:
        if not self.proc:
            if y_cerrar:
                self.root.destroy()
            return
        n = len(self.lector.en_curso)
        if n and not y_cerrar:
            if not messagebox.askyesno(
                    "Detener el worker",
                    f"Hay {n} análisis en curso. Se interrumpirán y se repetirán solos "
                    "la próxima vez que arranques el worker.\n\n¿Detener ahora?"):
                return
        self.parando = True
        self.fase = "deteniendo"
        self._pintar_fase()
        self._nota("Deteniendo el worker…")
        pid = self.proc.pid

        def tarea():
            matar_arbol(pid)
            if y_cerrar:
                self.q.put(("cerrar",))

        threading.Thread(target=tarea, daemon=True).start()

    def detener_ajenos(self) -> None:
        pids = (self.comprobacion or {}).get("ajenos", [])
        if not pids:
            return
        if not messagebox.askyesno(
                "Detener el otro worker",
                "Hay un worker funcionando fuera de este panel (probablemente en una "
                f"ventana de consola, PID {', '.join(map(str, pids))}).\n\n"
                "Si está analizando algo, ese análisis se repetirá al volver a arrancar.\n\n"
                "¿Detenerlo y arrancar aquí?"):
            return

        def tarea():
            for p in pids:
                matar_arbol(p)
            time.sleep(1.5)
            self.q.put(("reintentar",))

        self.fase = "comprobando"
        self._pintar_fase()
        threading.Thread(target=tarea, daemon=True).start()

    def cerrar(self) -> None:
        if self.proc:
            if not messagebox.askyesno(
                    "Cerrar DeepScan Worker",
                    "Al cerrar el panel se detiene el worker y la página deja de "
                    "analizar imágenes.\n\n¿Detener y cerrar?"):
                return
            self.detener(y_cerrar=True)
        else:
            self.root.destroy()

    def _abrir_log(self) -> None:
        try:
            os.startfile(str(LOG))  # noqa: S606
        except Exception:
            messagebox.showinfo("DeepScan Worker", f"Todavía no hay registro en\n{LOG}")

    def _alternar_detalle(self) -> None:
        self.detalle = not self.detalle
        self.b_detalle.config(text="Ocultar detalle técnico" if self.detalle else "Mostrar detalle técnico")
        self.txt.config(state="normal")
        self.txt.delete("1.0", "end")
        for item in self.lineas:
            self._escribir(item, refrescar=False)
        self.txt.see("end")
        self.txt.config(state="disabled")

    # ------------------------------------------------------------- hilos
    def _leer_salida(self, proc: subprocess.Popen) -> None:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8", errors="replace") as f:
            f.write(f"\n{'=' * 70}\n=== ARRANQUE {datetime.now():%Y-%m-%d %H:%M:%S} (panel)\n{'=' * 70}\n")
            f.flush()
            for crudo in iter(proc.stdout.readline, b""):
                texto = crudo.decode("utf-8", errors="replace")
                f.write(texto)
                f.flush()
                # Las barras de progreso reescriben la linea con \r: solo vale el final.
                limpio = ANSI.sub("", texto.rstrip("\r\n").split("\r")[-1]).rstrip()
                if limpio:
                    self.q.put(("linea", limpio))
            codigo = proc.wait()
            f.write(f"\n=== FIN {datetime.now():%Y-%m-%d %H:%M:%S} (codigo {codigo})\n")
        self.q.put(("fin", codigo))

    def _sondear_gpu(self) -> None:
        while True:
            self.q.put(("gpu", leer_gpu()))
            time.sleep(2)

    def _sondear_api(self) -> None:
        url = _url_api() + "/api/v1/health"
        while True:
            try:
                with urllib.request.urlopen(url, timeout=25) as r:
                    datos = json.loads(r.read().decode("utf-8"))
                estado = "si" if datos.get("workers_online") else "no"
            except Exception:
                estado = "error"
            self.q.put(("api", estado))
            time.sleep(20 if self.fase in ("cargando", "servicio") else 45)

    # ------------------------------------------------------------- bucle
    def _bombear(self) -> None:
        cambio = False
        try:
            for _ in range(600):
                msg = self.q.get_nowait()
                tipo = msg[0]
                if tipo == "linea":
                    linea = msg[1]
                    self._ultima_linea = linea
                    if self.lector.procesar(linea):
                        cambio = True
                    self._registrar(linea)
                    if self.lector.listo and self.fase == "cargando":
                        self.fase = "servicio"
                        self._nota("Worker listo. La página ya puede analizar imágenes.")
                        cambio = True
                elif tipo == "gpu":
                    self.gpu = msg[1]
                    self._pintar_gpu()
                elif tipo == "api":
                    self.api = {"estado": msg[1], "t": time.time()}
                    self._pintar_api()
                elif tipo == "comprobado":
                    self._tras_comprobar(msg[1], msg[2])
                elif tipo == "reintentar":
                    self.iniciar()
                elif tipo == "fin":
                    self.proc = None
                    if self.parando:
                        self.fase = "apagado"
                        self._nota("Worker detenido. La página ya no analiza imágenes.")
                    else:
                        self.fase = "caido"
                        self._nota(f"El worker terminó solo (código {msg[1]}).")
                    self.lector.en_curso.clear()
                    cambio = True
                elif tipo == "cerrar":
                    self.root.destroy()
                    return
        except queue.Empty:
            pass
        if cambio or self.lector.version != self._version_vista:
            self._version_vista = self.lector.version
            self._pintar_fase()
        self.root.after(60, self._bombear)

    def _animar(self) -> None:
        for ic, _, _ in self.filas.values():
            ic.girar()
        for ic in self._iconos_act:
            ic.girar()
        self._pintar_punto()
        self.root.after(80, self._animar)

    def _cada_segundo(self) -> None:
        if self.fase in ("cargando", "servicio"):
            self._pintar_textos()
            if self.lector.en_curso:
                self._pintar_actividad()
        self._pintar_api()
        self.root.after(1000, self._cada_segundo)

    # ------------------------------------------------------------- registro
    def _nota(self, texto: str) -> None:
        self._registrar(None, nota=texto)

    def _registrar(self, linea: str | None, nota: str | None = None) -> None:
        if nota is not None:
            item = ("nota", datetime.now().strftime("%H:%M:%S"), nota)
        else:
            item = ("linea", linea)
        self.lineas.append(item)
        self._escribir(item)

    def _escribir(self, item, refrescar: bool = True) -> None:
        if item[0] == "nota":
            hora, nivel, msg = item[1], "PANEL", item[2]
        elif self.detalle:
            hora, nivel, msg = clasificar(item[1])
            if nivel == "OTRO":
                hora, msg = "", item[1]
        else:
            r = resumen_simple(item[1])
            if r is None:
                return
            hora, nivel, msg = r
        t = self.txt
        abajo = t.yview()[1] > 0.995
        if refrescar:
            t.config(state="normal")
        if hora:
            t.insert("end", hora + "  ", "hora")
        t.insert("end", msg + "\n", nivel)
        if refrescar:
            exceso = int(t.index("end-1c").split(".")[0]) - 2500
            if exceso > 0:
                t.delete("1.0", f"{exceso}.0")
            if abajo:
                t.see("end")
            t.config(state="disabled")

    # ------------------------------------------------------------- pintado
    FASES = {
        # fase: (texto de la pildora, color, late)
        "apagado":     ("APAGADO", TX3, False),
        "comprobando": ("COMPROBANDO", AMBAR, True),
        "bloqueado":   ("NO PUEDE ARRANCAR", ROJO, False),
        "duplicado":   ("OTRO WORKER ACTIVO", AMBAR, False),
        "poca_vram":   ("POCA MEMORIA DE GPU", AMBAR, False),
        "cargando":    ("CARGANDO MODELOS", AMBAR, True),
        "servicio":    ("EN SERVICIO", VERDE, True),
        "deteniendo":  ("DETENIENDO", AMBAR, True),
        "caido":       ("DETENIDO CON ERROR", ROJO, False),
    }

    def _estado_pildora(self):
        if self.fase == "servicio" and self.lector.en_curso:
            return "ANALIZANDO", AZUL2, True
        return self.FASES[self.fase]

    def _pintar_punto(self) -> None:
        _, color, late = self._estado_pildora()
        c = self.punto
        c.delete("all")
        s = int(c["width"])
        if late:
            a = (math.sin(time.time() * 3.2) + 1) / 2
            r = s / 2 * (0.55 + 0.45 * a)
            c.create_oval(s / 2 - r, s / 2 - r, s / 2 + r, s / 2 + r, fill=self._mezcla(color, SUP, 0.55), outline="")
        c.create_oval(s * .25, s * .25, s * .75, s * .75, fill=color, outline="")

    @staticmethod
    def _mezcla(a: str, b: str, t: float) -> str:
        ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
        cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
        return "#" + "".join(f"{int(x + (y - x) * t):02x}" for x, y in zip(ca, cb))

    def _pintar_fase(self) -> None:
        texto, color, _ = self._estado_pildora()
        self.txt_pildora.config(text=texto, fg=color)
        self.pildora.config(highlightbackground=self._mezcla(color, SUP, 0.6))
        self._pintar_textos()
        self._pintar_botones()
        self._pintar_franja()
        self._pintar_pasos()
        self._pintar_cifras()
        self._pintar_actividad()

    def _pintar_textos(self) -> None:
        L = self.lector
        f = self.fase
        c = self.comprobacion or {}
        g = c.get("gpu") or {}
        titulo, sub = "", ""
        if f == "apagado":
            titulo = "El worker está apagado"
            sub = "La página acepta imágenes pero no puede analizarlas hasta que lo inicies."
        elif f == "comprobando":
            titulo = "Comprobando el equipo…"
            sub = "Entorno, otros workers y memoria de GPU libre."
        elif f == "bloqueado":
            titulo = "Falta algo para poder arrancar"
            sub = "  ".join(c.get("errores", []))
        elif f == "duplicado":
            titulo = "Ya hay un worker funcionando fuera de este panel"
            sub = ("Dos workers en una sola GPU se pelean la memoria y los dos van lentos. "
                   "Detén el otro para arrancar aquí, o déjalo y cierra este panel.")
        elif f == "poca_vram":
            titulo = f"Hay poca memoria de GPU libre: {g.get('libre', 0):,} MiB de {g.get('total', 0):,}".replace(",", ".")
            apps = ", ".join(c.get("golosos") or [])
            sub = (f"Conviene tener {VRAM_MINIMA_MIB:,} MiB. ".replace(",", ".") +
                   "Con menos, el análisis semántico corre en parte en CPU y cada imagen puede tardar "
                   "decenas de minutos." + (f" Cierra primero: {apps}." if apps else ""))
        elif f == "cargando":
            hechos = sum(1 for k in CLAVES if k in L.hechos)
            t = time.time() - getattr(self, "t_arranque", time.time())
            titulo = f"Cargando los modelos · {hechos} de {len(CLAVES)}"
            sub = (f"Llevamos {self._duracion(t)}. Suele tardar entre 2 y 4 minutos; "
                   "mientras tanto la página no procesa imágenes.")
        elif f == "servicio":
            n = len(L.en_curso)
            titulo = (f"Analizando {n} {'imagen' if n == 1 else 'imágenes'} ahora mismo"
                      if n else "En servicio")
            desde = datetime.fromtimestamp(L.t_listo).strftime("%H:%M") if L.t_listo else "—"
            dur = self._duracion(time.time() - L.t_listo) if L.t_listo else ""
            sub = f"La página está analizando con esta GPU. Activo desde las {desde} ({dur})."
        elif f == "deteniendo":
            titulo = "Deteniendo el worker…"
            sub = "Liberando la GPU."
        elif f == "caido":
            titulo = "El worker se detuvo inesperadamente"
            sub = L.ultimo_error or self._ultima_linea or "Revisa el registro para ver la causa."
            if len(sub) > 260:
                sub = sub[:260] + "…"
        self.lbl_titulo.config(text=titulo)
        self.lbl_sub.config(text=sub)

    def _pintar_botones(self) -> None:
        for w in self.botones.winfo_children():
            w.destroy()
        f = self.fase
        bs = []
        pagina = ("Abrir la página", lambda: webbrowser.open(PAGINA), "secundario")
        if f in ("apagado", "caido"):
            bs = [pagina, ("Iniciar worker" if f == "apagado" else "Volver a iniciar", self.iniciar, "primario")]
        elif f == "bloqueado":
            bs = [("Volver a comprobar", self.iniciar, "primario")]
        elif f == "duplicado":
            bs = [("Volver a comprobar", self.iniciar, "secundario"),
                  ("Detener el otro y arrancar", self.detener_ajenos, "primario")]
        elif f == "poca_vram":
            bs = [("Arrancar igual", lambda: self.iniciar(forzar=True), "secundario"),
                  ("Volver a comprobar", self.iniciar, "primario")]
        elif f in ("cargando", "servicio"):
            bs = [pagina, ("Detener", self.detener, "peligro")]
        for i, (t, cmd, tipo) in enumerate(bs):
            Boton(self.botones, t, cmd, tipo, f=self.f_boton, px=self.px).pack(
                side="left", padx=(0 if i == 0 else self.px(10), 0))

    def _pintar_franja(self) -> None:
        for w in self.franja.winfo_children():
            w.destroy()
        for aviso in self.lector.avisos:
            fila = tk.Frame(self.franja, bg="#1d1808")
            fila.pack(fill="x")
            tk.Frame(fila, bg=AMBAR, width=self.px(3)).pack(side="left", fill="y")
            tk.Label(fila, text=aviso, bg="#1d1808", fg=AMBAR, font=self.f_peq, anchor="w",
                     justify="left", wraplength=self.px(980)).pack(fill="x", padx=self.px(16), pady=self.px(8))

    def _pintar_api(self) -> None:
        e, t = self.api["estado"], self.api["t"]
        if e is None:
            self.lbl_api.config(text="Consultando si la página ve el worker…", fg=TX3)
            return
        hace = f"comprobado hace {self._duracion(time.time() - t)}"
        if e == "si" and self.fase != "servicio":
            # Puede ser el latido de un worker anterior: la clave de Redis
            # dura 90 s despues de que el worker muere.
            texto, color = (f"●  La página aún ve un worker, pero este no está listo: el aviso de "
                            f"uno anterior tarda hasta 90 s en caducar · {hace}"), TX3
        elif e == "si":
            texto, color = f"●  La página publicada ve este worker · {hace}", VERDE
        elif e == "no":
            if self.fase == "servicio":
                texto, color = f"●  La página aún no ve el worker (se avisa cada 30 s) · {hace}", AMBAR
            else:
                texto, color = f"●  La página no ve ningún worker · {hace}", TX3
        else:
            texto, color = f"●  No se pudo consultar la API publicada · {hace}", TX3
        self.lbl_api.config(text=texto, fg=color)

    def _pintar_pasos(self) -> None:
        L = self.lector
        c = self.comprobacion
        f = self.fase

        def poner(clave, estado, det=None):
            ic, n, d = self.filas[clave]
            ic.poner(estado)
            n.config(fg=TX if estado != "pendiente" else TX3)
            if det is not None:
                d.config(text=det)

        if c is None or f == "comprobando":
            e = "activo" if f == "comprobando" else "pendiente"
            for k in ("entorno", "unico", "vram"):
                poner(k, e)
        else:
            poner("entorno", "error" if c["errores"] else "hecho")
            poner("unico", "aviso" if c["ajenos"] else "hecho",
                  f"otro activo · PID {', '.join(map(str, c['ajenos']))}" if c["ajenos"] else "una sola GPU, un solo worker")
            g = c.get("gpu")
            if g:
                libre = f"{g['libre']:,} de {g['total']:,} MiB".replace(",", ".")
                poner("vram", "hecho" if g["libre"] >= VRAM_MINIMA_MIB else "aviso", libre)
            else:
                poner("vram", "aviso", "nvidia-smi no responde")

        actual = L.paso_actual() if f == "cargando" else None
        if f == "cargando" and not L.cargando:
            actual = CLAVES[0]
        for clave, _, det, _ in PASOS:
            if clave in L.fallidos:
                poner(clave, "aviso")
            elif clave in L.hechos:
                poner(clave, "hecho")
            elif clave == actual:
                poner(clave, "activo")
            elif f == "caido" and L.cargando and clave == L.paso_actual():
                poner(clave, "error")
            else:
                poner(clave, "pendiente")

        hechos = sum(1 for k in CLAVES if k in L.hechos)
        self.lbl_progreso.config(text=f"{hechos}/{len(CLAVES)}" if hechos else "")
        b = self.barra_carga
        b.update_idletasks()
        w = b.winfo_width()
        b.delete("all")
        b.create_rectangle(0, 0, w * hechos / len(CLAVES), 10,
                           fill=VERDE if hechos == len(CLAVES) else AZUL2, outline="")

    def _pintar_gpu(self) -> None:
        g = self.gpu
        if not g:
            self.t_vram.poner("—", "nvidia-smi no responde")
            self.t_uso.poner("—", "")
            return
        frac = g["usada"] / g["total"]
        color = ROJO if frac > 0.95 else AMBAR if frac > 0.85 else AZUL2
        self.t_vram.poner(f"{coma(g['usada'] / 1024)} / {coma(g['total'] / 1024)} GiB",
                          f"libres {coma(g['libre'] / 1024)} GiB", frac, color)
        self.t_uso.poner(f"{g['uso']} %", f"{g['temp']} °C", g["uso"] / 100,
                         AZUL2 if g["temp"] < 80 else NARANJA)
        nombre = g["nombre"].replace("NVIDIA GeForce ", "")
        self.lbl_gpu_nombre.config(text=nombre)

    def _pintar_cifras(self) -> None:
        L = self.lector
        en = len(L.en_curso)
        partes = []
        if en:
            partes.append(f"{en} en curso")
        partes.append(f"{L.errores} con error" if L.errores else "ninguno con error")
        self.t_analisis.poner(str(L.completados), " · ".join(partes))
        if L.duraciones:
            med = statistics.median(L.duraciones)
            self.t_tiempo.poner(f"{coma(med)} s", f"mediana · último {coma(L.duraciones[-1])} s")
        else:
            self.t_tiempo.poner("—", "sin análisis todavía")

    def _pintar_actividad(self) -> None:
        for w in self.lista_act.winfo_children():
            w.destroy()
        self._iconos_act = []
        L = self.lector
        px = self.px
        self.lbl_act_total.config(text=(f"{L.completados} completado{'s' if L.completados != 1 else ''}" if L.completados else ""))
        items = list(L.actividad)[:5]
        if not items:
            msg = ("Todavía no ha llegado ningún análisis. Cuando alguien suba una imagen en la "
                   "página aparecerá aquí, con su resultado y lo que tardó."
                   if self.fase == "servicio" else
                   "Los análisis aparecerán aquí cuando el worker esté en servicio.")
            tk.Label(self.lista_act, text=msg, bg=SUP, fg=TX3, font=self.f_peq, anchor="w",
                     justify="left", wraplength=px(600)).pack(fill="x", pady=(0, px(4)))
            return
        for i, a in enumerate(items):
            if i:
                tk.Frame(self.lista_act, bg=BORDE, height=1).pack(fill="x")
            fila = tk.Frame(self.lista_act, bg=SUP)
            fila.pack(fill="x", pady=px(6))
            ic = Icono(fila, px(13), SUP)
            ic.poner({"curso": "activo", "ok": "hecho", "error": "error"}[a["estado"]])
            ic.pack(side="left", padx=(0, px(10)))
            self._iconos_act.append(ic)
            tk.Label(fila, text=a["hora"], bg=SUP, fg=TX3, font=self.f_mono).pack(side="left")
            tk.Label(fila, text=f"   {TIPO[a['tipo']]}", bg=SUP, fg=TX, font=self.f_txt).pack(side="left")
            tk.Label(fila, text=f"  {a['id'][:8]}", bg=SUP, fg=TX3, font=self.f_mono).pack(side="left")
            if a["estado"] == "curso":
                der = f"analizando · {self._duracion(time.time() - a['t0'])}"
                tk.Label(fila, text=der, bg=SUP, fg=AZUL2, font=self.f_peq).pack(side="right")
            elif a["estado"] == "error":
                tk.Label(fila, text="falló · ver registro", bg=SUP, fg=ROJO, font=self.f_peq).pack(side="right")
            else:
                if a["dur"] is not None:
                    tk.Label(fila, text=f"{coma(a['dur'])} s", bg=SUP, fg=TX3, font=self.f_mono,
                             width=7, anchor="e").pack(side="right")
                if a["pct"] is not None:
                    b = banda(a["pct"])
                    tk.Label(fila, text=f"{coma(a['pct'], 0)} %  evidencia {b}", bg=SUP,
                             fg=COLOR_BANDA[b], font=self.f_peq).pack(side="right", padx=(0, px(14)))

    @staticmethod
    def _duracion(s: float) -> str:
        s = int(max(0, s))
        if s < 60:
            return f"{s} s"
        if s < 3600:
            return f"{s // 60} min {s % 60:02d} s"
        return f"{s // 3600} h {(s % 3600) // 60:02d} min"

    def correr(self) -> None:
        self.root.mainloop()


def main() -> int:
    # --sin-arrancar  abre el panel sin lanzar el worker
    # --forzar        arranca aunque la VRAM libre este por debajo del umbral
    Panel(auto="--sin-arrancar" not in sys.argv, forzar="--forzar" in sys.argv).correr()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

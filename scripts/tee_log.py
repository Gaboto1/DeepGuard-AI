# -*- coding: utf-8 -*-
"""
Duplica lo que recibe por la entrada estandar: a la pantalla y a un archivo.

Por que existe
--------------
El worker se lanza en una ventana visible para poder vigilarlo, pero entonces
su salida se va con la ventana: el 9 de noviembre de 2026 el worker murio y no
quedo nada que mirar para saber por que. Hacen falta las dos cosas a la vez,
pantalla y archivo.

Windows no trae `tee`, y las dos alternativas obvias fallan:

- `Tee-Object` de PowerShell envuelve cada linea de stderr de un ejecutable
  nativo en un NativeCommandError, con su traza y su `CategoryInfo`. Como
  celery escribe casi todo por stderr, el log quedaria ilegible. Comprobado.
- `celery --logfile` manda el log al archivo EN LUGAR de a la consola, y ademas
  no recoge lo que la aplicacion escribe con loguru.

Asi que se usa una tuberia de cmd contra este guion, que no interpreta nada:
copia bytes y hace flush en cada linea, para que lo ultimo que el worker alcanzo
a decir antes de morir este en el archivo y no en un bufer.

Uso
---
    programa.exe 2>&1 | python scripts/tee_log.py reports/worker.log
"""
import sys
from datetime import datetime
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: tee_log.py <archivo de destino>", file=sys.stderr)
        return 2

    destino = Path(sys.argv[1])
    destino.parent.mkdir(parents=True, exist_ok=True)

    # Se ABRE EN MODO ANADIR, no se trunca: si el worker se reinicia varias
    # veces seguidas -que es justo lo que pasa cuando algo va mal- truncar
    # borraria el arranque anterior, que es el que explica la caida.
    with destino.open("a", encoding="utf-8", errors="replace") as f:
        f.write(f"\n{'=' * 70}\n")
        f.write(f"=== ARRANQUE {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        f.write(f"{'=' * 70}\n")
        f.flush()

        # Se lee en modo binario y se decodifica aqui: la consola de Windows
        # puede entregar bytes que no son UTF-8 validos (los colores ANSI y
        # los acentos de la pagina de codigos local), y una excepcion de
        # decodificacion aqui dejaria al worker sin salida a mitad de camino.
        entrada = sys.stdin.buffer
        salida = sys.stdout.buffer
        for linea in iter(entrada.readline, b""):
            salida.write(linea)
            salida.flush()
            f.write(linea.decode("utf-8", errors="replace"))
            f.flush()

        f.write(f"\n=== FIN {datetime.now():%Y-%m-%d %H:%M:%S} "
                f"(la tuberia se cerro: el proceso termino)\n")
        f.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

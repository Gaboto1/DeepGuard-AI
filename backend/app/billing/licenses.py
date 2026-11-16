# -*- coding: utf-8 -*-
"""
Licencias firmadas: identidad de un suscriptor sin base de datos ni contrasenas.

Por que no hay usuarios ni contrasenas
--------------------------------------
Para cobrar una suscripcion hace falta saber quien es el que paga, pero no hace
falta guardar una contrasena ni datos personales. Guardar credenciales obliga a
protegerlas, a gestionar recuperaciones y a responder por una filtracion; en un
proyecto de una sola persona eso es mas riesgo que valor.

Aqui el suscriptor recibe una **licencia firmada**: una cadena corta que lleva
dentro su plan y su fecha de caducidad, sellada con HMAC-SHA256. El servidor la
verifica con su clave y no necesita consultar nada. No hay sesion, no hay
tabla de usuarios y no hay contrasena que robar.

Lo que esto SI exige tener claro:

- **La licencia es un portador.** Quien la tenga, la usa. Es el mismo modelo
  que una clave de API, y por eso caduca y se puede revocar por lista.
- **La clave de firma no puede faltar ni ser de ejemplo.** Sin
  DEEPGUARD_BILLING_KEY el modulo queda deshabilitado y todo el mundo es plan
  gratuito: se prefiere no cobrar antes que aceptar licencias falsificables.
  Es la misma postura que custody_service.py toma con su clave de sellos.
- **No reutiliza la clave de la cadena de custodia.** Son dos competencias
  distintas: una acredita un peritaje y la otra autoriza un cobro. Compartir
  clave significa que comprometer la facturacion compromete la prueba forense.

Formato
-------
    <payload en base64url>.<firma en base64url>

El payload es un JSON compacto con `sub` (a quien se emitio), `plan`, `iat` y
`exp` en segundos epoch. Se firma el payload codificado, no el JSON crudo, para
que la verificacion no dependa de como se serialice.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Optional

from loguru import logger

from app.config import settings

# Valores de ejemplo que NO pueden pasar por clave real. Misma idea que la
# lista de custody_service.py: un placeholder en produccion es peor que nada,
# porque da apariencia de seguridad.
_PLACEHOLDERS = {
    "", "changeme", "cambiame", "placeholder", "ejemplo", "example",
    "test", "secret", "clave", "tu_clave_aqui", "your_key_here",
}

VERSION = 1


class LicenciaInvalida(Exception):
    """La licencia no verifica, caduco o esta mal formada."""


@dataclass(frozen=True)
class Licencia:
    sub: str
    plan: str
    emitida: int
    caduca: int

    @property
    def vigente(self) -> bool:
        return time.time() < self.caduca


def _clave() -> Optional[bytes]:
    """La clave de firma, o None si no hay una utilizable."""
    bruta = (getattr(settings, "DEEPGUARD_BILLING_KEY", "")
             or os.getenv("DEEPGUARD_BILLING_KEY", ""))
    if not bruta or bruta.strip().lower() in _PLACEHOLDERS:
        return None
    # Una clave corta se rompe por fuerza bruta en un portatil. 32 caracteres
    # es el minimo razonable para un HMAC que autoriza un cobro.
    if len(bruta) < 32:
        logger.warning(
            "[billing] DEEPGUARD_BILLING_KEY tiene menos de 32 caracteres; "
            "las licencias quedan deshabilitadas. Genera una con "
            "`python -c \"import secrets;print(secrets.token_hex(32))\"`."
        )
        return None
    return bruta.encode()


def habilitado() -> bool:
    """True si se pueden emitir y verificar licencias."""
    return _clave() is not None


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def emitir(sub: str, plan: str, dias: int = 30) -> str:
    """
    Firma una licencia. `sub` identifica al suscriptor (un id de pago, un
    correo con hash, lo que la pasarela devuelva): aqui no se interpreta.
    """
    clave = _clave()
    if clave is None:
        raise LicenciaInvalida(
            "No hay DEEPGUARD_BILLING_KEY utilizable: no se pueden emitir "
            "licencias."
        )
    ahora = int(time.time())
    payload = {
        "v": VERSION,
        "sub": str(sub),
        "plan": str(plan),
        "iat": ahora,
        "exp": ahora + int(dias) * 86400,
    }
    cuerpo = _b64e(json.dumps(payload, separators=(",", ":"),
                              sort_keys=True).encode())
    firma = _b64e(hmac.new(clave, cuerpo.encode(), hashlib.sha256).digest())
    return f"{cuerpo}.{firma}"


def verificar(token: str) -> Licencia:
    """
    Comprueba la firma y la vigencia. Lanza LicenciaInvalida si algo falla.

    Nunca dice *por que* falla mas alla de lo imprescindible: distinguir
    "firma mala" de "caducada" ayuda a quien intenta falsificarla.
    """
    clave = _clave()
    if clave is None:
        raise LicenciaInvalida("Las licencias estan deshabilitadas.")
    if not token or token.count(".") != 1:
        raise LicenciaInvalida("Licencia mal formada.")

    cuerpo, firma = token.split(".", 1)
    esperada = _b64e(hmac.new(clave, cuerpo.encode(), hashlib.sha256).digest())
    # compare_digest y no ==: la comparacion normal se corta en el primer byte
    # distinto y filtra la firma correcta midiendo tiempos.
    if not hmac.compare_digest(firma, esperada):
        raise LicenciaInvalida("Licencia no valida.")

    try:
        datos = json.loads(_b64d(cuerpo))
    except Exception:
        raise LicenciaInvalida("Licencia no valida.")

    if datos.get("v") != VERSION:
        raise LicenciaInvalida("Version de licencia no soportada.")

    lic = Licencia(
        sub=str(datos.get("sub", "")),
        plan=str(datos.get("plan", "")),
        emitida=int(datos.get("iat", 0)),
        caduca=int(datos.get("exp", 0)),
    )
    if not lic.vigente:
        raise LicenciaInvalida("Licencia caducada.")
    return lic

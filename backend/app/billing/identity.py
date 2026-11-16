# -*- coding: utf-8 -*-
"""
De una peticion HTTP a "quien es y que plan tiene".

Dos clases de identidad, a proposito
------------------------------------
**Suscriptor**: trae una licencia firmada en la cabecera `X-DeepScan-License`
(o `Authorization: Bearer ...`). La firma se verifica con HMAC, de modo que la
identidad es tan fuerte como la clave del servidor.

**Anonimo**: no trae licencia. Se le asigna una identidad a partir del
identificador de dispositivo que el navegador manda en `X-DeepScan-Device`, y
si no lo manda, de la IP. Es deliberadamente debil: ver la nota de
`usage.py` sobre por que endurecerla perjudicaria mas de lo que protege.

La identidad anonima se **somete a hash** antes de usarse como clave. Una IP es
un dato personal en varias jurisdicciones y no hay ninguna razon para guardarla
en claro en Redis solo para contar hasta cinco. Con el hash, el contador
funciona igual y lo que queda almacenado no identifica a nadie.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

from app.billing import licenses
from app.billing.plans import Plan, PLAN_POR_DEFECTO, obtener as obtener_plan

CABECERA_LICENCIA = "X-DeepScan-License"
CABECERA_DISPOSITIVO = "X-DeepScan-Device"


@dataclass(frozen=True)
class Identidad:
    clave: str          # con lo que se indexa el contador de consumo
    plan: Plan
    es_suscriptor: bool
    caduca: Optional[int] = None
    motivo_rechazo: Optional[str] = None   # si traia licencia y no valia

    def to_dict(self) -> dict:
        return {
            "plan": self.plan.id,
            "plan_nombre": self.plan.nombre,
            "es_suscriptor": self.es_suscriptor,
            "caduca": self.caduca,
            "motivo_rechazo": self.motivo_rechazo,
        }


def _hash(valor: str) -> str:
    """12 hex: colisiones despreciables para contar cuotas, y no reversible."""
    return hashlib.sha256(valor.encode()).hexdigest()[:12]


def _cabecera(request, nombre: str) -> str:
    """
    Lee una cabecera sin depender de mayusculas.

    Starlette las entrega en un mapa insensible a mayusculas, de modo que con
    una peticion real `get("X-DeepScan-License")` funciona. Pero apoyarse en
    esa garantia ata este modulo al framework y a su version, y hace que
    cualquier doble de prueba con un dict normal falle en silencio
    -degradando a anonimo- en lugar de dar error. Se normaliza aqui.
    """
    h = getattr(request, "headers", {}) or {}
    try:
        v = h.get(nombre) or h.get(nombre.lower()) or ""
    except Exception:
        return ""
    return str(v).strip()


def _ip_de(request) -> str:
    """
    IP del cliente teniendo en cuenta el proxy.

    En Render la aplicacion esta detras de un balanceador, de modo que
    `request.client.host` es la IP del proxy y seria la misma para todo el
    mundo: sin mirar X-Forwarded-For, todos los anonimos compartirian cuota.
    Se toma el primer salto de la cadena, que es el cliente original.
    """
    reenviada = _cabecera(request, "X-Forwarded-For")
    if reenviada:
        return reenviada.split(",")[0].strip()
    cliente = getattr(request, "client", None)
    return getattr(cliente, "host", "") or "desconocido"


def resolver(request) -> Identidad:
    """
    Nunca lanza. Una licencia invalida degrada a anonimo con el motivo
    anotado, en lugar de rechazar la peticion: el usuario sigue pudiendo usar
    el plan gratuito mientras renueva.
    """
    token = _cabecera(request, CABECERA_LICENCIA)
    if not token:
        auth = _cabecera(request, "Authorization")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()

    motivo = None
    if token:
        try:
            lic = licenses.verificar(token)
            return Identidad(
                clave=f"lic:{_hash(lic.sub)}",
                plan=obtener_plan(lic.plan),
                es_suscriptor=True,
                caduca=lic.caduca,
            )
        except licenses.LicenciaInvalida as e:
            motivo = str(e)

    dispositivo = _cabecera(request, CABECERA_DISPOSITIVO)
    semilla = dispositivo if dispositivo else f"ip:{_ip_de(request)}"
    return Identidad(
        clave=f"anon:{_hash(semilla)}",
        plan=PLAN_POR_DEFECTO,
        es_suscriptor=False,
        motivo_rechazo=motivo,
    )

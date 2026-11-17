# -*- coding: utf-8 -*-
"""
Pasarelas de pago: una interfaz y tres implementaciones.

Por que hay una interfaz y no una integracion directa
-----------------------------------------------------
La pasarela es la pieza que mas probablemente haya que cambiar, y la decision
no es tecnica sino de disponibilidad en Chile:

- **Stripe** es la mejor opcion tecnica para suscripciones, pero su
  disponibilidad para empresas chilenas es dudosa: las guias se contradicen y
  varias indican que hace falta constituir una sociedad en EE. UU. Hay que
  confirmarlo en la lista oficial de paises de Stripe antes de comprometerse.
- **Flow** es la alternativa local mas citada para suscripciones en Chile.
- **Mercado Pago** conviene si ademas se quiere cobrar en el resto de LATAM.
- **Transbank/Webpay** es el estandar chileno, pero orientado a pago unico.

Aislar todo eso detras de `PasarelaDePago` permite elegir mas tarde sin tocar
el resto del sistema, y permite que las pruebas corran sin red ni credenciales.

Estado de cada implementacion
-----------------------------
- `PasarelaSimulada`: **funciona hoy**. No mueve dinero. Emite la licencia
  directamente para poder recorrer el flujo completo en una demo y en las
  pruebas automatizadas. Es la que se usa mientras no haya credenciales.
- `PasarelaFlow` y `PasarelaMercadoPago`: **el andamio esta, la llamada HTTP
  no**. Leen sus credenciales del entorno y se declaran no disponibles si
  faltan. Deliberadamente no se han completado sin que el dueno del proyecto
  cree las cuentas: una integracion de cobro a medias, desplegada en una
  pagina publica, puede acabar aceptando dinero real que nadie puede devolver.

Ninguna credencial vive en el codigo ni en el repositorio. Todas se leen del
entorno, y sin ellas la pasarela correspondiente simplemente no aparece.
"""
from __future__ import annotations

import os
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from loguru import logger

from app.billing import licenses
from app.billing.plans import Plan


@dataclass(frozen=True)
class Checkout:
    """Lo que hay que devolverle al navegador para que el usuario pague."""

    proveedor: str
    referencia: str
    url_pago: Optional[str]
    # Solo la pasarela simulada entrega la licencia aqui. Una pasarela real la
    # entrega despues, por webhook, cuando el pago se confirma de verdad.
    licencia: Optional[str] = None
    simulado: bool = False
    mensaje: str = ""

    def to_dict(self) -> dict:
        return {
            "proveedor": self.proveedor,
            "referencia": self.referencia,
            "url_pago": self.url_pago,
            "licencia": self.licencia,
            "simulado": self.simulado,
            "mensaje": self.mensaje,
        }


class PasarelaDePago(ABC):
    id: str = "abstracta"
    nombre: str = "Pasarela"

    @abstractmethod
    def disponible(self) -> bool:
        """True si esta configurada y se puede usar."""

    @abstractmethod
    def crear_checkout(self, plan: Plan, email: str,
                       periodo: str = "mensual") -> Checkout:
        """Inicia un cobro y devuelve a donde mandar al usuario."""


class PasarelaSimulada(PasarelaDePago):
    """
    Recorre el flujo completo sin mover dinero.

    Existe por dos razones. La primera es poder demostrar el modelo de negocio
    en la defensa sin necesidad de una cuenta de cobro ni de una tarjeta. La
    segunda es que las pruebas automatizadas necesitan un camino que no salga
    a la red.

    Emite una licencia real y firmada: lo unico que falta es el cobro. Por eso
    `simulado` viaja en la respuesta y la interfaz debe decirlo con claridad,
    para que nadie crea que ha pagado.
    """

    id = "simulada"
    nombre = "Simulada (demostracion)"

    def disponible(self) -> bool:
        return licenses.habilitado()

    def crear_checkout(self, plan: Plan, email: str,
                       periodo: str = "mensual") -> Checkout:
        from app.billing.plans import PERIODOS
        dias = PERIODOS.get(periodo, 30)
        ref = f"sim_{secrets.token_hex(8)}"
        if plan.precio_clp == 0:
            return Checkout(self.id, ref, None, None, True,
                            "El plan gratuito no requiere pago.")
        token = licenses.emitir(sub=email or ref, plan=plan.id, dias=dias)
        logger.info(f"[billing] checkout simulado {ref} plan={plan.id}")
        return Checkout(
            proveedor=self.id, referencia=ref, url_pago=None, licencia=token,
            simulado=True,
            mensaje=(f"Pago simulado: no se ha cobrado nada. La licencia es "
                     f"real y caduca en {dias} dias."),
        )


class _PasarelaExterna(PasarelaDePago):
    """Base de las pasarelas reales: credenciales del entorno, nunca del codigo."""

    variables: tuple[str, ...] = ()
    documentacion: str = ""

    def _credenciales(self) -> dict[str, str]:
        return {v: os.getenv(v, "") for v in self.variables}

    def disponible(self) -> bool:
        return all(self._credenciales().values()) and licenses.habilitado()

    def _faltan(self) -> list[str]:
        return [k for k, v in self._credenciales().items() if not v]

    def crear_checkout(self, plan: Plan, email: str,
                       periodo: str = "mensual") -> Checkout:
        raise NotImplementedError(
            f"{self.nombre} no esta implementada todavia. Faltan las "
            f"credenciales {self._faltan()} y la llamada HTTP a su API. "
            f"Documentacion: {self.documentacion}"
        )


class PasarelaFlow(_PasarelaExterna):
    """
    Flow — la alternativa local mas citada para suscripciones en Chile.

    Pendiente: crear la cuenta, obtener apiKey y secretKey, e implementar
    `payment/create` firmando los parametros con HMAC-SHA256 segun su
    documentacion. El webhook de confirmacion debe verificar esa misma firma
    ANTES de emitir la licencia: un webhook sin verificar es una puerta para
    que cualquiera se regale un plan de pago.
    """

    id = "flow"
    nombre = "Flow"
    variables = ("FLOW_API_KEY", "FLOW_SECRET_KEY")
    documentacion = "https://www.flow.cl/docs/api.html"


class PasarelaMercadoPago(_PasarelaExterna):
    """
    Mercado Pago — conviene si ademas se quiere cobrar fuera de Chile.

    Pendiente: crear la aplicacion, obtener el access token e implementar
    `preapproval` (suscripcion recurrente). Igual que con Flow, el webhook
    debe validarse contra la firma antes de dar nada por pagado.
    """

    id = "mercadopago"
    nombre = "Mercado Pago"
    variables = ("MERCADOPAGO_ACCESS_TOKEN",)
    documentacion = "https://www.mercadopago.cl/developers/es/docs"


_REGISTRO: dict[str, PasarelaDePago] = {
    p.id: p for p in (PasarelaSimulada(), PasarelaFlow(), PasarelaMercadoPago())
}


def disponibles() -> list[PasarelaDePago]:
    return [p for p in _REGISTRO.values() if p.disponible()]


def obtener(proveedor: Optional[str]) -> Optional[PasarelaDePago]:
    """
    La pasarela pedida si esta configurada; si no, la primera disponible.

    Devuelve None cuando no hay ninguna, que es el estado por defecto de un
    despliegue recien clonado. La interfaz debe tratarlo como "todavia no se
    puede contratar", no como un error.
    """
    if proveedor:
        p = _REGISTRO.get(proveedor.lower())
        if p and p.disponible():
            return p
        return None
    libres = disponibles()
    return libres[0] if libres else None

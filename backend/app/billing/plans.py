# -*- coding: utf-8 -*-
"""
Planes y derechos de uso de DeepScan.

Por que este modelo y no otro
-----------------------------
El recurso escaso de DeepScan no es el almacenamiento ni el ancho de banda: es
el **tiempo de GPU**. Cada analisis ocupa una tarjeta durante unos 32 segundos
de mediana -5 s el ensemble y el resto el analisis semantico- y el worker corre
con concurrencia 2. Eso son del orden de 150 analisis por hora como techo
practico. Un modelo de negocio honesto tiene que medir **analisis**, no
usuarios ni megabytes, porque es lo unico que cuesta.

De ahi tres decisiones:

1. **Gratis con cuota diaria, sin cuenta.** La friccion de registrarse mata el
   caso de uso principal: alguien recibe una imagen dudosa por WhatsApp y
   quiere comprobarla ahora. La cuota diaria protege la GPU sin pedir nada.
2. **El plan de pago vende prioridad y el informe sellado**, no "mas IA". El
   analisis es el mismo; lo que cambia es que no esperas en la cola detras de
   los gratuitos y que te llevas un PDF con la cadena de custodia HMAC-SHA256
   que el sistema ya emite. Para una redaccion o un perito, ese sello es el
   producto: es lo que permite sostener la verificacion ante un tercero.
3. **Nada de "analisis ilimitados".** Con una sola GPU seria una promesa que no
   se puede cumplir, y prometer capacidad que no existe es la forma mas rapida
   de perder al primer cliente serio.

Los precios estan en pesos chilenos porque el cliente objetivo declarado en el
informe -medios de comunicacion y organizaciones de verificacion- es local, y
porque las pasarelas disponibles en Chile (Flow, Webpay, Mercado Pago) liquidan
en CLP. Se dejan como constantes y no incrustados en el frontend para que
cambiarlos sea un solo commit.

Referencia de mercado: las herramientas equivalentes cobran por creditos o por
analisis con cuota mensual (Copyleaks, Winston AI, Pangram), con los analisis
de imagen consumiendo bastante mas que los de texto. El esquema de cuota
mensual con prioridad es el habitual del sector.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass(frozen=True)
class Plan:
    """Un plan y lo que da derecho a hacer."""

    id: str
    nombre: str
    descripcion: str

    # Cuotas. None = no se aplica ese limite en este plan.
    analisis_por_dia: Optional[int]
    analisis_por_mes: Optional[int]

    # Prioridad en la cola. Mayor = se atiende antes. Celery soporta
    # prioridades en la cola 'images' (x-max-priority = 10).
    prioridad: int

    # Derechos
    informe_pdf_sellado: bool
    acceso_api: bool
    analisis_por_lote: bool
    historial_dias: int
    video: bool

    # Precio mensual en pesos chilenos. 0 = gratuito.
    precio_clp: int = 0
    # Precio por un ano pagado de una vez: diez meses, dos de regalo. Es el
    # descuento anual habitual del sector y, para un servicio con un solo
    # equipo detras, el que mejor se sostiene: cobra por adelantado sin
    # comprometer mas capacidad que la mensual.
    precio_anual_clp: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Catalogo ────────────────────────────────────────────────────────────────
#
# Las cuotas se fijan contra la capacidad real, no contra lo que suena bien:
# el techo practico del worker son ~150 analisis/hora. El plan pericial, con
# 1.500 al mes, son 50 al dia: cabe de sobra incluso con varios suscriptores.

GRATIS = Plan(
    id="gratis",
    nombre="Gratuito",
    descripcion=(
        "Para comprobar una imagen suelta. Sin registro y sin tarjeta: "
        "el análisis completo con los seis detectores y el meta-ensemble."
    ),
    analisis_por_dia=5,
    analisis_por_mes=None,
    prioridad=1,
    informe_pdf_sellado=False,
    acceso_api=False,
    analisis_por_lote=False,
    historial_dias=1,
    video=False,
    precio_clp=0,
)

PRO = Plan(
    id="pro",
    nombre="Profesional",
    descripcion=(
        "Para quien verifica a diario. Cola prioritaria, informe PDF con el "
        "sello de cadena de custodia, historial de 90 días y análisis de video."
    ),
    analisis_por_dia=None,
    analisis_por_mes=300,
    prioridad=5,
    informe_pdf_sellado=True,
    acceso_api=False,
    analisis_por_lote=True,
    historial_dias=90,
    video=True,
    precio_clp=9990,
    precio_anual_clp=99900,
)

PERICIAL = Plan(
    id="pericial",
    nombre="Pericial",
    descripcion=(
        "Para redacciones y peritajes. Todo lo del plan Profesional más acceso "
        "por API, prioridad máxima y un año de historial."
    ),
    analisis_por_dia=None,
    analisis_por_mes=1500,
    prioridad=9,
    informe_pdf_sellado=True,
    acceso_api=True,
    analisis_por_lote=True,
    historial_dias=365,
    video=True,
    precio_clp=29990,
    precio_anual_clp=299900,
)

PLANES: dict[str, Plan] = {p.id: p for p in (GRATIS, PRO, PERICIAL)}

# Periodos de contratacion y su duracion en dias.
PERIODOS = {"mensual": 30, "anual": 365}
PLAN_POR_DEFECTO = GRATIS


def obtener(plan_id: Optional[str]) -> Plan:
    """
    Devuelve el plan pedido, o el gratuito si no existe.

    Se cae al gratuito en lugar de lanzar: un identificador desconocido -un
    token viejo, un plan retirado- no debe dejar al usuario sin servicio, solo
    sin privilegios.
    """
    if not plan_id:
        return PLAN_POR_DEFECTO
    return PLANES.get(str(plan_id).lower(), PLAN_POR_DEFECTO)


def catalogo_publico() -> list[dict]:
    """El catalogo tal como lo consume la pagina de precios."""
    return [p.to_dict() for p in (GRATIS, PRO, PERICIAL)]

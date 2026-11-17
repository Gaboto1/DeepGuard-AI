# -*- coding: utf-8 -*-
"""
Endpoints del modelo de negocio: catalogo, estado de la cuenta y contratacion.

Todos son de solo lectura salvo `/checkout`, y ninguno puede dejar sin servicio
a nadie: si la facturacion esta apagada o mal configurada, responden con el
plan gratuito en lugar de fallar. Ver la nota del interruptor en
`app/billing/__init__.py`.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, Field

from app import billing
from app.billing import identity, plans, providers, usage

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


class SolicitudCheckout(BaseModel):
    plan: str = Field(..., description="id del plan: pro | pericial")
    email: str = Field("", max_length=200,
                       description="opcional; identifica la licencia")
    proveedor: str = Field("", description="pasarela; vacio = la disponible")
    periodo: str = Field("mensual", description="mensual | anual")


@router.get("/plans")
async def listar_planes() -> JSONResponse:
    """El catalogo y el estado real del cobro, para la pagina de precios."""
    libres = providers.disponibles()
    return JSONResponse({
        "planes": plans.catalogo_publico(),
        "moneda": "CLP",
        "cuota_aplicada": billing.habilitado(),
        "pasarelas": [{"id": p.id, "nombre": p.nombre} for p in libres],
        "se_puede_contratar": bool(libres),
        "nota": (
            "La contratacion esta en modo demostracion mientras no haya una "
            "pasarela de pago configurada."
            if not libres or all(getattr(p, "id", "") == "simulada" for p in libres)
            else ""
        ),
    })


@router.get("/me")
async def mi_estado(request: Request) -> JSONResponse:
    """
    Plan vigente y consumo. Lo consulta la pagina para pintar el contador y
    decidir si ofrece mejorar de plan.
    """
    ident = identity.resolver(request)
    consumo = usage.consultar(ident.clave, ident.plan)
    return JSONResponse({
        "identidad": ident.to_dict(),
        "plan": ident.plan.to_dict(),
        "consumo": consumo.to_dict(),
        "cuota_aplicada": billing.habilitado(),
    })


@router.post("/checkout")
async def crear_checkout(peticion: SolicitudCheckout,
                         request: Request) -> JSONResponse:
    """
    Inicia la contratacion de un plan.

    Con la pasarela simulada devuelve la licencia en el acto y lo dice. Con una
    pasarela real devolveria una URL a la que mandar al usuario, y la licencia
    solo se emitiria despues, al confirmarse el cobro por webhook.
    """
    plan = plans.obtener(peticion.plan)
    if plan.precio_clp == 0:
        return JSONResponse(status_code=400, content={
            "error": "El plan gratuito no se contrata: es el de partida.",
        })

    pasarela = providers.obtener(peticion.proveedor or None)
    if pasarela is None:
        return JSONResponse(status_code=503, content={
            "error": "no_hay_pasarela",
            "mensaje": (
                "Todavia no hay ninguna pasarela de pago configurada, de modo "
                "que no se puede contratar. El catalogo y las cuotas si "
                "funcionan."
            ),
            "faltan": ["DEEPGUARD_BILLING_KEY"] + [
                v for p in (providers.PasarelaFlow(),
                            providers.PasarelaMercadoPago())
                for v in p.variables
            ],
        })

    try:
        if peticion.periodo not in plans.PERIODOS:
            return JSONResponse(status_code=400, content={
                "error": "periodo_invalido",
                "mensaje": f"Periodo desconocido: {peticion.periodo}"})
        res = pasarela.crear_checkout(plan, peticion.email or "",
                                      periodo=peticion.periodo)
    except NotImplementedError as e:
        return JSONResponse(status_code=501, content={
            "error": "pasarela_incompleta", "mensaje": str(e)})
    except Exception as e:
        logger.error(f"[billing] checkout fallido: {type(e).__name__}: {e}")
        return JSONResponse(status_code=500, content={
            "error": "checkout_fallido",
            "mensaje": "No se pudo iniciar el cobro."})

    return JSONResponse(res.to_dict())


@router.post("/webhook/{proveedor}")
async def webhook(proveedor: str, request: Request) -> JSONResponse:
    """
    Confirmacion de pago de la pasarela.

    Deliberadamente NO emite ninguna licencia todavia. Un webhook que concede
    un plan sin verificar la firma de la pasarela es una puerta abierta: basta
    con una peticion POST para regalarse una suscripcion. La verificacion de
    firma es especifica de cada pasarela y se implementa junto con su
    `crear_checkout`, no antes.
    """
    logger.warning(
        f"[billing] webhook de '{proveedor}' recibido y DESCARTADO: la "
        f"verificacion de firma de esa pasarela no esta implementada."
    )
    return JSONResponse(status_code=501, content={
        "error": "webhook_no_implementado",
        "mensaje": (
            "Este webhook no concede licencias porque todavia no verifica la "
            "firma de la pasarela. Implementar ambas cosas a la vez."
        ),
    })

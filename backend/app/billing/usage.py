# -*- coding: utf-8 -*-
"""
Contador de consumo por identidad, en Redis.

Decisiones que importan
-----------------------
**Se cuenta al aceptar, no al terminar.** La cuota existe para proteger la GPU,
y la GPU se ocupa cuando la tarea entra en la cola. Contar al terminar dejaria
encolar cien analisis de golpe.

**Falla abierto.** Si Redis no responde, se permite el analisis. Un contador
caido no es razon para dejar sin servicio a quien paga, y mucho menos para
romper la pagina entera: el riesgo de un abuso puntual es menor que el de una
caida total. Queda registrado en el log para que se note.

**La ventana es de calendario, no deslizante.** "5 al dia" se reinicia a
medianoche UTC, no 24 horas despues del primero. Es lo que la gente espera y
es mucho mas barato: una clave por dia con TTL, sin listas de marcas de tiempo.

**La identidad del plan gratuito es debil a proposito.** Un identificador de
dispositivo guardado en el navegador se borra vaciando la cache. Endurecerlo
-huella del navegador, bloqueo por IP- castigaria a universidades y oficinas
tras un NAT, que son parte del publico objetivo. La cuota gratuita disuade el
uso casual excesivo; no pretende ser infranqueable, y quien quiera saltarsela
lo hara. Para eso estan los planes de pago, que si tienen identidad fuerte.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from app.billing.plans import Plan

PREFIJO = "deepguard:uso"

# Margen sobre la ventana para que la clave no caduque justo en el limite.
_TTL_EXTRA_S = 3600


@dataclass(frozen=True)
class Consumo:
    """Lo gastado y lo que queda en cada ventana aplicable."""

    usados_dia: int
    usados_mes: int
    limite_dia: Optional[int]
    limite_mes: Optional[int]
    permitido: bool
    motivo: Optional[str] = None
    contador_disponible: bool = True

    @property
    def restantes_dia(self) -> Optional[int]:
        if self.limite_dia is None:
            return None
        return max(0, self.limite_dia - self.usados_dia)

    @property
    def restantes_mes(self) -> Optional[int]:
        if self.limite_mes is None:
            return None
        return max(0, self.limite_mes - self.usados_mes)

    def to_dict(self) -> dict:
        return {
            "usados_dia": self.usados_dia,
            "usados_mes": self.usados_mes,
            "limite_dia": self.limite_dia,
            "limite_mes": self.limite_mes,
            "restantes_dia": self.restantes_dia,
            "restantes_mes": self.restantes_mes,
            "permitido": self.permitido,
            "motivo": self.motivo,
            "contador_disponible": self.contador_disponible,
        }


def _cliente():
    """Cliente Redis, o None si no hay. Nunca lanza."""
    try:
        from app.config import make_redis_client, settings
        return make_redis_client(settings.REDIS_URL, socket_timeout=2,
                                 socket_connect_timeout=2)
    except Exception as e:
        logger.warning(f"[billing] contador sin Redis ({type(e).__name__}); "
                       f"se permite el analisis")
        return None


def _ventanas(ahora: Optional[datetime] = None) -> tuple[str, str]:
    a = ahora or datetime.now(timezone.utc)
    return a.strftime("%Y%m%d"), a.strftime("%Y%m")


def _claves(identidad: str) -> tuple[str, str]:
    dia, mes = _ventanas()
    return (f"{PREFIJO}:dia:{identidad}:{dia}",
            f"{PREFIJO}:mes:{identidad}:{mes}")


def consultar(identidad: str, plan: Plan) -> Consumo:
    """Cuanto lleva gastado esta identidad, sin consumir nada."""
    k_dia, k_mes = _claves(identidad)
    cli = _cliente()
    if cli is None:
        return Consumo(0, 0, plan.analisis_por_dia, plan.analisis_por_mes,
                       True, None, contador_disponible=False)
    try:
        v_dia, v_mes = cli.mget(k_dia, k_mes)
        usados_dia = int(v_dia or 0)
        usados_mes = int(v_mes or 0)
    except Exception as e:
        logger.warning(f"[billing] no se pudo leer el consumo "
                       f"({type(e).__name__}); se permite")
        return Consumo(0, 0, plan.analisis_por_dia, plan.analisis_por_mes,
                       True, None, contador_disponible=False)

    permitido, motivo = True, None
    if plan.analisis_por_dia is not None and usados_dia >= plan.analisis_por_dia:
        permitido, motivo = False, "cuota_diaria_agotada"
    elif plan.analisis_por_mes is not None and usados_mes >= plan.analisis_por_mes:
        permitido, motivo = False, "cuota_mensual_agotada"

    return Consumo(usados_dia, usados_mes, plan.analisis_por_dia,
                   plan.analisis_por_mes, permitido, motivo)


def consumir(identidad: str, plan: Plan) -> Consumo:
    """
    Comprueba y descuenta en una sola operacion.

    El incremento va por pipeline para que las dos ventanas se muevan juntas.
    No es atomico respecto de la comprobacion previa: dos peticiones
    simultaneas en el limite exacto pueden colarse ambas. Se acepta: el coste
    de un analisis de mas es trivial frente a montar un script Lua y su
    mantenimiento, y la cuota no es un control de seguridad.
    """
    estado = consultar(identidad, plan)
    if not estado.permitido:
        return estado

    cli = _cliente()
    if cli is None:
        return Consumo(estado.usados_dia, estado.usados_mes,
                       plan.analisis_por_dia, plan.analisis_por_mes,
                       True, None, contador_disponible=False)

    k_dia, k_mes = _claves(identidad)
    try:
        ahora = datetime.now(timezone.utc)
        fin_dia = ahora.replace(hour=23, minute=59, second=59)
        ttl_dia = int((fin_dia - ahora).total_seconds()) + _TTL_EXTRA_S
        # 32 dias cubre cualquier mes y el desfase de zona horaria.
        ttl_mes = 32 * 86400

        p = cli.pipeline()
        p.incr(k_dia)
        p.expire(k_dia, ttl_dia)
        p.incr(k_mes)
        p.expire(k_mes, ttl_mes)
        res = p.execute()
        usados_dia = int(res[0])
        usados_mes = int(res[2])
    except Exception as e:
        logger.warning(f"[billing] no se pudo descontar ({type(e).__name__}); "
                       f"se permite")
        return Consumo(estado.usados_dia, estado.usados_mes,
                       plan.analisis_por_dia, plan.analisis_por_mes,
                       True, None, contador_disponible=False)

    return Consumo(usados_dia, usados_mes, plan.analisis_por_dia,
                   plan.analisis_por_mes, True, None)

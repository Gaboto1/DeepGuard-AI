# -*- coding: utf-8 -*-
"""
Modelo de negocio de DeepScan: planes, cuotas, licencias y pasarelas.

Interruptor general
-------------------
`BILLING_ENABLED` decide si la cuota se APLICA. Viene en **false** por defecto,
y esa eleccion es deliberada: el modulo se escribio sin que nadie pudiera
probar la pagina en vivo, y un fallo en el conteo de cuotas se manifiesta
dejando a los usuarios sin servicio. Con el interruptor apagado todo el modulo
se puede consultar -la pagina de precios funciona, /billing/me responde- pero
nadie se queda fuera.

Para encenderlo hacen falta dos cosas en el entorno de la API:

    BILLING_ENABLED=true
    DEEPGUARD_BILLING_KEY=<64 hex>   # python -c "import secrets;print(secrets.token_hex(32))"

Sin la segunda, las licencias quedan deshabilitadas y todo el mundo es plan
gratuito, aunque la primera este puesta.
"""
import os


_VERDADEROS = {"1", "true", "si", "yes"}


def habilitado() -> bool:
    """
    True si la cuota debe aplicarse de verdad.

    Mira PRIMERO la variable de entorno del proceso y despues el `settings`.
    El orden importa en los dos sentidos:

    - La variable de entorno gana para que una prueba pueda encender y apagar
      la facturacion con monkeypatch sin tocar la configuracion global.
    - El `settings` hace falta porque pydantic carga backend/.env en el objeto
      de configuracion, NO en os.environ. Leyendo solo el entorno, poner
      BILLING_ENABLED=true en el .env no encendia nada y el modulo se quedaba
      apagado sin decir por que. Paso el 16 de noviembre de 2026.
    """
    bruto = os.getenv("BILLING_ENABLED")
    if bruto is not None and bruto.strip() != "":
        return bruto.strip().lower() in _VERDADEROS
    try:
        from app.config import settings
        return bool(getattr(settings, "BILLING_ENABLED", False))
    except Exception:
        return False

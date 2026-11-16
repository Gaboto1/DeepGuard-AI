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


def habilitado() -> bool:
    """True si la cuota debe aplicarse de verdad."""
    return os.getenv("BILLING_ENABLED", "").strip().lower() in {"1", "true", "si", "yes"}

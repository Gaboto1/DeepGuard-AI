# -*- coding: utf-8 -*-
"""
Una subida enorme se rechaza antes de leerla, y la configuracion no filtra
secretos al imprimirse.

La API cargaba el archivo entero en memoria y solo despues miraba su tamano,
con un limite de 500 MB frente a los 512 MB de RAM del plan gratuito de
Render: una sola peticion podia tumbarla. Auditoria del 17 nov 2026.
"""
import asyncio

import httpx

from app.config import settings
from app.main import app


def test_el_limite_cabe_en_la_ram_de_render():
    # Archivo + copia en Base64 (~4/3) deben caber holgadamente en 512 MB.
    assert settings.MAX_FILE_SIZE_MB * (1 + 4 / 3) < 400, settings.MAX_FILE_SIZE_MB


def test_se_rechaza_por_content_length_sin_leer_el_archivo():
    # Formulario valido y pequeno; la cabecera declara un tamano enorme. Se
    # debe rechazar sin llegar a leer el archivo.
    cuerpo = (
        b"--x\r\n"
        b'Content-Disposition: form-data; name="file"; filename="a.png"\r\n'
        b"Content-Type: image/png\r\n\r\n"
        b"abc\r\n--x--\r\n"
    )
    enorme = str(settings.max_file_size_bytes + 50 * 1_048_576)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://t") as c:
            return await c.post(
                "/api/v1/analyze", content=cuerpo,
                headers={"Content-Type": "multipart/form-data; boundary=x",
                         "Content-Length": enorme},
            )

    assert asyncio.run(run()).status_code == 413


def test_la_configuracion_no_muestra_secretos_al_imprimirse():
    texto = repr(settings)
    for campo in ("REDIS_URL", "REDIS_BACKEND", "DEEPGUARD_SIGNING_KEY",
                  "DEEPGUARD_BILLING_KEY"):
        assert campo not in texto, campo

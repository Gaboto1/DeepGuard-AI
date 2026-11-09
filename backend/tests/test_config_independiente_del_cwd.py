# -*- coding: utf-8 -*-
"""
La configuracion no debe depender del directorio de trabajo.

Por que existe esta prueba
--------------------------
`Settings.model_config` llevaba `{"env_file": ".env"}` con ruta relativa, y
pydantic la resuelve contra el **cwd**, no contra el archivo. Un guion lanzado
desde la raiz del proyecto no encontraba `backend/.env` y caia en los valores
por defecto de la clase: `REDIS_URL = "redis://localhost:6379/0"` en lugar del
broker de Upstash, y `DEEPGUARD_SIGNING_KEY = ""`.

El 9 de noviembre de 2026 eso hizo que `scripts/prueba_extremo_a_extremo.py`
encolara diez tareas en el Redis local —que estaba escuchando, de modo que no
hubo ningun error— donde ningun worker las consume. El guion se quedo esperando
resultados que no podian llegar, y la prueba que existe precisamente para
comprobar que la pagina responde no comprobaba nada. El fallo era silencioso en
las dos direcciones: ni el guion se queja, ni el worker ve tarea alguna.

La prueba lee el `env_file` declarado, no las credenciales: no necesita que
exista un `.env` para detectar la regresion, porque lo que verifica es que la
ruta este anclada al archivo.
"""
from pathlib import Path

import app.config as config_module


BACKEND = Path(config_module.__file__).resolve().parent.parent


def _env_file_declarado() -> Path:
    env = config_module.Settings.model_config.get("env_file")
    assert env, "Settings dejo de declarar env_file"
    assert not isinstance(env, (list, tuple)), (
        "env_file paso a ser una lista; esta prueba asume una sola ruta"
    )
    return Path(str(env))


def test_env_file_es_una_ruta_absoluta():
    """Una ruta relativa se resuelve contra el cwd y rompe segun desde donde
    se lance el proceso."""
    env = _env_file_declarado()
    assert env.is_absolute(), (
        f"env_file es relativo ({env}): pydantic lo resolvera contra el "
        "directorio de trabajo y la configuracion cambiara segun desde donde "
        "se lance el proceso"
    )


def test_env_file_apunta_a_la_carpeta_backend():
    """Donde vive el .env del proyecto, no a otra parte."""
    env = _env_file_declarado()
    assert env.parent == BACKEND, (
        f"env_file apunta a {env.parent}, no a {BACKEND}"
    )


def test_el_broker_por_defecto_sigue_siendo_localhost():
    """
    No es un deseo, es el motivo por el que la ruta debe ser absoluta: el valor
    por defecto es inofensivo en apariencia y catastrofico en la practica,
    porque localhost:6379 suele aceptar conexiones (docker) y entonces las
    tareas se publican sin error en un broker que nadie consume.

    Si alguien cambia este defecto por algo que falle al conectar, la prueba
    salta para que se revise si sigue haciendo falta esta guardia.
    """
    campo = config_module.Settings.model_fields["REDIS_URL"]
    assert campo.default == "redis://localhost:6379/0", (
        f"el defecto de REDIS_URL cambio a {campo.default!r}; revisar si la "
        "guardia del env_file absoluto sigue siendo necesaria"
    )

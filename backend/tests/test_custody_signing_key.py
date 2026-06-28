# -*- coding: utf-8 -*-
"""
Tests del gate de arranque (fail-fast) para DEEPGUARD_SIGNING_KEY.

custody_service.py valida la clave de firma HMAC al importarse. Estos tests
recargan el modulo con distintos valores de settings.DEEPGUARD_SIGNING_KEY /
settings.API_ONLY para confirmar que:
  - en modo worker (API_ONLY=False) una clave vacia o un placeholder
    conocido (los mismos valores de los .env.example / docker-compose.prod.yml)
    abortan el arranque con RuntimeError.
  - una clave real se acepta sin problemas.
  - en modo API_ONLY=True (Render) no se exige clave real porque no se
    generan sellos de custodia en la nube.
"""
import importlib

import pytest

import app.config as config_module


def _reload_custody(monkeypatch, signing_key, api_only):
    monkeypatch.setattr(config_module.settings, "DEEPGUARD_SIGNING_KEY", signing_key)
    monkeypatch.setattr(config_module.settings, "API_ONLY", api_only)
    monkeypatch.delenv("DEEPGUARD_SIGNING_KEY", raising=False)
    import app.services.custody_service as custody_module
    return importlib.reload(custody_module)


@pytest.fixture(autouse=True)
def _restore_module_state(monkeypatch):
    """Deja el modulo en un estado valido tras cada test (evita fugas entre tests)."""
    yield
    try:
        _reload_custody(monkeypatch, "a" * 64, api_only=False)
    except Exception:
        pass


def test_rechaza_placeholder_inseguro_en_modo_worker(monkeypatch):
    with pytest.raises(RuntimeError):
        _reload_custody(monkeypatch, "change-me-in-production", api_only=False)


def test_rechaza_placeholder_de_env_example_en_modo_worker(monkeypatch):
    with pytest.raises(RuntimeError):
        _reload_custody(monkeypatch, "cambia-esto-por-una-clave-aleatoria-larga", api_only=False)


def test_rechaza_clave_vacia_en_modo_worker(monkeypatch):
    with pytest.raises(RuntimeError):
        _reload_custody(monkeypatch, "", api_only=False)


def test_acepta_clave_real_en_modo_worker(monkeypatch):
    mod = _reload_custody(monkeypatch, "a" * 64, api_only=False)
    assert mod._SIGNING_KEY == b"a" * 64


def test_permite_clave_vacia_en_modo_api_only(monkeypatch):
    """En Render (API_ONLY=True) no se generan sellos -> no es critico exigir clave."""
    mod = _reload_custody(monkeypatch, "", api_only=True)
    assert mod._SIGNING_KEY  # usa placeholder interno, no lanza RuntimeError

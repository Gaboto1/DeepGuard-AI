# -*- coding: utf-8 -*-
"""
Pruebas del modelo de negocio: licencias, cuotas, identidad y pasarelas.

Lo que de verdad hay que proteger aqui no es que el catalogo tenga tres
planes, sino tres propiedades de las que depende que esto no sea un agujero:

1. Una licencia manipulada no concede nada.
2. Sin clave de firma no se emite ni se acepta ninguna licencia.
3. Si el contador de consumo falla, el usuario NO se queda sin servicio.

El resto de las pruebas cubre que las cuotas se apliquen como dicen los planes.
"""
import importlib

import pytest

from app.billing import identity, licenses, plans, providers, usage

CLAVE = "a" * 64          # 64 caracteres: supera el minimo de 32
CLAVE_CORTA = "b" * 10


class PeticionFalsa:
    """Lo minimo que `identity.resolver` necesita de una peticion."""

    def __init__(self, headers=None, ip="203.0.113.7"):
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}

        class _C:
            host = ip
        self.client = _C()


@pytest.fixture
def con_clave(monkeypatch):
    monkeypatch.setenv("DEEPGUARD_BILLING_KEY", CLAVE)
    monkeypatch.setattr(licenses.settings, "DEEPGUARD_BILLING_KEY", CLAVE,
                        raising=False)
    return CLAVE


# ─── Catalogo ────────────────────────────────────────────────────────────────

def test_el_plan_gratuito_es_el_de_partida():
    assert plans.PLAN_POR_DEFECTO.id == "gratis"
    assert plans.PLAN_POR_DEFECTO.precio_clp == 0


def test_un_plan_desconocido_degrada_a_gratuito_y_no_lanza():
    """Un token viejo con un plan retirado deja sin privilegios, no sin servicio."""
    assert plans.obtener("plan_que_no_existe").id == "gratis"
    assert plans.obtener(None).id == "gratis"


def test_ningun_plan_promete_analisis_ilimitados():
    """
    Con una sola GPU, 'ilimitado' seria una promesa incumplible. Todo plan de
    pago debe declarar un tope mensual.
    """
    for p in plans.PLANES.values():
        if p.precio_clp > 0:
            assert p.analisis_por_mes is not None, f"{p.id} no declara tope"


def test_los_planes_de_pago_dan_mas_prioridad_que_el_gratuito():
    assert plans.PRO.prioridad > plans.GRATIS.prioridad
    assert plans.PERICIAL.prioridad > plans.PRO.prioridad


# ─── Licencias: lo que no puede fallar ───────────────────────────────────────

def test_sin_clave_no_se_emite_ninguna_licencia(monkeypatch):
    monkeypatch.delenv("DEEPGUARD_BILLING_KEY", raising=False)
    monkeypatch.setattr(licenses.settings, "DEEPGUARD_BILLING_KEY", "",
                        raising=False)
    assert licenses.habilitado() is False
    with pytest.raises(licenses.LicenciaInvalida):
        licenses.emitir("alguien", "pericial")


def test_una_clave_corta_se_rechaza(monkeypatch):
    """Un HMAC que autoriza un cobro no se firma con diez caracteres."""
    monkeypatch.setenv("DEEPGUARD_BILLING_KEY", CLAVE_CORTA)
    monkeypatch.setattr(licenses.settings, "DEEPGUARD_BILLING_KEY",
                        CLAVE_CORTA, raising=False)
    assert licenses.habilitado() is False


def test_una_licencia_recien_emitida_verifica(con_clave):
    tok = licenses.emitir("perito@medio.cl", "pericial", dias=30)
    lic = licenses.verificar(tok)
    assert lic.plan == "pericial"
    assert lic.sub == "perito@medio.cl"
    assert lic.vigente


def test_una_licencia_manipulada_no_concede_nada(con_clave):
    """La propiedad central: sin la clave no se puede fabricar una licencia."""
    tok = licenses.emitir("x@y.cl", "pericial")
    cuerpo, firma = tok.split(".")
    for falsa in (
        cuerpo + "." + ("A" * len(firma)),      # firma inventada
        cuerpo[:-4] + "AAAA." + firma,          # payload alterado
        cuerpo,                                 # sin firma
        "",                                     # vacia
    ):
        with pytest.raises(licenses.LicenciaInvalida):
            licenses.verificar(falsa)


def test_una_licencia_de_otra_clave_no_vale(con_clave, monkeypatch):
    """Cambiar la clave del servidor invalida lo emitido: permite revocar."""
    tok = licenses.emitir("x@y.cl", "pro")
    otra = "z" * 64
    monkeypatch.setenv("DEEPGUARD_BILLING_KEY", otra)
    monkeypatch.setattr(licenses.settings, "DEEPGUARD_BILLING_KEY", otra,
                        raising=False)
    with pytest.raises(licenses.LicenciaInvalida):
        licenses.verificar(tok)


def test_una_licencia_caducada_se_rechaza(con_clave):
    tok = licenses.emitir("x@y.cl", "pro", dias=-1)
    with pytest.raises(licenses.LicenciaInvalida):
        licenses.verificar(tok)


# ─── Identidad ───────────────────────────────────────────────────────────────

def test_sin_licencia_se_es_anonimo_y_gratuito():
    ident = identity.resolver(PeticionFalsa())
    assert ident.es_suscriptor is False
    assert ident.plan.id == "gratis"
    assert ident.clave.startswith("anon:")


def test_la_identidad_anonima_no_guarda_la_ip_en_claro():
    """La IP es dato personal; para contar hasta cinco basta su hash."""
    ip = "198.51.100.23"
    ident = identity.resolver(PeticionFalsa(ip=ip))
    assert ip not in ident.clave


def test_dos_dispositivos_distintos_no_comparten_cuota():
    a = identity.resolver(PeticionFalsa({"X-DeepScan-Device": "aaa"}))
    b = identity.resolver(PeticionFalsa({"X-DeepScan-Device": "bbb"}))
    assert a.clave != b.clave


def test_se_respeta_x_forwarded_for():
    """
    Detras del balanceador de Render, sin esto todos los anonimos compartirian
    la IP del proxy y por tanto la cuota.
    """
    p = PeticionFalsa({"X-Forwarded-For": "203.0.113.9, 10.0.0.1"}, ip="10.0.0.1")
    q = PeticionFalsa({"X-Forwarded-For": "203.0.113.10, 10.0.0.1"}, ip="10.0.0.1")
    assert identity.resolver(p).clave != identity.resolver(q).clave


def test_una_licencia_valida_da_su_plan(con_clave):
    tok = licenses.emitir("cliente", "pericial")
    ident = identity.resolver(PeticionFalsa({"X-DeepScan-License": tok}))
    assert ident.es_suscriptor is True
    assert ident.plan.id == "pericial"
    assert ident.plan.acceso_api is True


def test_una_licencia_rota_degrada_a_gratuito_sin_romper(con_clave):
    """No se rechaza la peticion: se sigue pudiendo usar el plan gratuito."""
    ident = identity.resolver(PeticionFalsa({"X-DeepScan-License": "basura.x"}))
    assert ident.es_suscriptor is False
    assert ident.plan.id == "gratis"
    assert ident.motivo_rechazo


def test_tambien_se_acepta_authorization_bearer(con_clave):
    tok = licenses.emitir("cliente", "pro")
    ident = identity.resolver(PeticionFalsa({"Authorization": f"Bearer {tok}"}))
    assert ident.plan.id == "pro"


# ─── Consumo ─────────────────────────────────────────────────────────────────

def test_si_el_contador_no_responde_se_permite_el_analisis(monkeypatch):
    """
    Un Redis caido no puede dejar sin servicio a quien paga. Falla abierto, y
    lo declara para que la interfaz no mienta sobre el consumo.
    """
    monkeypatch.setattr(usage, "_cliente", lambda: None)
    c = usage.consultar("anon:abc", plans.GRATIS)
    assert c.permitido is True
    assert c.contador_disponible is False
    c2 = usage.consumir("anon:abc", plans.GRATIS)
    assert c2.permitido is True


def test_la_cuota_diaria_del_plan_gratuito_corta_al_llegar_al_tope(monkeypatch):
    estado = {"dia": plans.GRATIS.analisis_por_dia, "mes": 0}

    class ClienteFalso:
        def mget(self, k_dia, k_mes):
            return [str(estado["dia"]), str(estado["mes"])]

    monkeypatch.setattr(usage, "_cliente", lambda: ClienteFalso())
    c = usage.consultar("anon:tope", plans.GRATIS)
    assert c.permitido is False
    assert c.motivo == "cuota_diaria_agotada"
    assert c.restantes_dia == 0


def test_el_plan_de_pago_corta_por_cuota_mensual(monkeypatch):
    class ClienteFalso:
        def mget(self, k_dia, k_mes):
            return ["0", str(plans.PRO.analisis_por_mes)]

    monkeypatch.setattr(usage, "_cliente", lambda: ClienteFalso())
    c = usage.consultar("lic:abc", plans.PRO)
    assert c.permitido is False
    assert c.motivo == "cuota_mensual_agotada"


def test_el_plan_de_pago_no_tiene_cuota_diaria(monkeypatch):
    class ClienteFalso:
        def mget(self, k_dia, k_mes):
            return ["9999", "0"]

    monkeypatch.setattr(usage, "_cliente", lambda: ClienteFalso())
    c = usage.consultar("lic:abc", plans.PRO)
    assert c.permitido is True


# ─── Pasarelas ───────────────────────────────────────────────────────────────

def test_sin_credenciales_no_hay_pasarela_real(monkeypatch):
    for v in ("FLOW_API_KEY", "FLOW_SECRET_KEY", "MERCADOPAGO_ACCESS_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    assert providers.PasarelaFlow().disponible() is False
    assert providers.PasarelaMercadoPago().disponible() is False


def test_las_pasarelas_reales_no_cobran_a_medias(monkeypatch):
    """
    Mientras no esten implementadas deben lanzar, no devolver algo que parezca
    un cobro. Una integracion de pago a medias en una pagina publica puede
    aceptar dinero que nadie sabe devolver.
    """
    with pytest.raises(NotImplementedError):
        providers.PasarelaFlow().crear_checkout(plans.PRO, "x@y.cl")
    with pytest.raises(NotImplementedError):
        providers.PasarelaMercadoPago().crear_checkout(plans.PRO, "x@y.cl")


def test_la_pasarela_simulada_se_declara_simulada(con_clave):
    """Nadie debe poder creer que ha pagado."""
    ch = providers.PasarelaSimulada().crear_checkout(plans.PRO, "x@y.cl")
    assert ch.simulado is True
    assert "no se ha cobrado" in ch.mensaje.lower()
    assert licenses.verificar(ch.licencia).plan == "pro"


def test_el_plan_gratuito_no_emite_licencia_en_el_checkout(con_clave):
    ch = providers.PasarelaSimulada().crear_checkout(plans.GRATIS, "x@y.cl")
    assert ch.licencia is None


# ─── El interruptor general ──────────────────────────────────────────────────

def test_la_facturacion_viene_apagada_por_defecto(monkeypatch):
    """
    La propiedad mas importante de todo el modulo: recien clonado, DeepScan no
    le niega un analisis a nadie. La compuerta de /analyze consulta esto antes
    de hacer nada, de modo que con el interruptor apagado el endpoint se
    comporta exactamente como antes de que existiera la facturacion.
    """
    import app.billing as b
    monkeypatch.delenv("BILLING_ENABLED", raising=False)
    assert b.habilitado() is False


def test_el_interruptor_solo_se_enciende_con_valores_explicitos(monkeypatch):
    import app.billing as b
    for valor in ("true", "TRUE", "1", "si", "yes"):
        monkeypatch.setenv("BILLING_ENABLED", valor)
        assert b.habilitado() is True, valor
    for valor in ("false", "0", "no", "", "quizas"):
        monkeypatch.setenv("BILLING_ENABLED", valor)
        assert b.habilitado() is False, valor

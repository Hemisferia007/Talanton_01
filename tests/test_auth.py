"""Tests de autenticación.

Lo que se verifica acá no es "que ande el login": es que ninguna ruta quede
abierta. La app tiene datos de contacto de terceros y un token que manda mail
en nombre de la consultora.
"""

import pytest

from talanton import auth
from talanton.models import Usuario

from conftest import EMAIL_PRUEBA, PASSWORD_PRUEBA

# Toda ruta que exista y no esté en RUTAS_PUBLICAS tiene que exigir sesión.
RUTAS_PRIVADAS = [
    ("GET", "/"),
    ("GET", "/leads"),
    ("GET", "/leads/1"),
    ("GET", "/tablero"),
    ("GET", "/avisos"),
    ("GET", "/mi-empresa"),
    ("GET", "/conectar-gmail"),
    ("GET", "/oauth/google/callback"),
    ("GET", "/leads/1/redactar"),
    ("POST", "/leads/1/nota"),
    ("POST", "/leads/1/estado"),
    ("POST", "/leads/1/enviar"),
    ("POST", "/leads/1/respuesta"),
    ("POST", "/mi-empresa"),
    ("POST", "/recalcular"),
    ("POST", "/cuentas/1"),
    ("POST", "/cuentas/1/desconectar"),
]


# --- Hash --------------------------------------------------------------------


def test_el_hash_no_guarda_la_contrasena():
    h = auth.hashear("una-contrasena-larga")
    assert "una-contrasena-larga" not in h
    assert h.startswith("scrypt$")


def test_dos_hashes_de_la_misma_contrasena_son_distintos():
    """Salt por usuario: sin esto, dos personas con la misma clave se delatan."""
    assert auth.hashear("misma-contrasena") != auth.hashear("misma-contrasena")


def test_verificar_acepta_la_correcta_y_rechaza_el_resto():
    h = auth.hashear("la-correcta-123")
    assert auth.verificar("la-correcta-123", h)
    assert not auth.verificar("la-incorrecta", h)
    assert not auth.verificar("", h)


def test_un_hash_corrupto_no_rompe_ni_deja_pasar():
    for basura in ("", "cualquier-cosa", "scrypt$mal$formado", "md5$1$2$3$4$5"):
        assert not auth.verificar("lo-que-sea", basura)


# --- Usuarios ----------------------------------------------------------------


def test_no_se_permiten_contrasenas_cortas(session):
    with pytest.raises(ValueError, match="10 caracteres"):
        auth.crear_usuario(session, "a@b.com", "A", "corta")


def test_no_se_duplican_emails(session):
    auth.crear_usuario(session, "a@b.com", "A", "contrasena-larga")
    with pytest.raises(ValueError, match="Ya existe"):
        auth.crear_usuario(session, "A@B.com", "Otra", "contrasena-larga")


def test_el_email_se_normaliza(session):
    u = auth.crear_usuario(session, "  Jonatan@Talanton.COM.ar ", "J", "contrasena-larga")
    assert u.email == "jonatan@talanton.com.ar"
    assert auth.autenticar(session, "JONATAN@talanton.com.ar", "contrasena-larga") is not None


def test_autenticar_devuelve_none_con_credenciales_malas(session, usuario):
    assert auth.autenticar(session, EMAIL_PRUEBA, "otra-cosa-larga") is None
    assert auth.autenticar(session, "noexiste@x.com", PASSWORD_PRUEBA) is None


def test_un_usuario_inactivo_no_entra(session, usuario):
    usuario.activo = False
    session.flush()
    assert auth.autenticar(session, EMAIL_PRUEBA, PASSWORD_PRUEBA) is None


def test_autenticar_registra_el_ingreso(session, usuario):
    assert usuario.ultimo_ingreso is None
    auth.autenticar(session, EMAIL_PRUEBA, PASSWORD_PRUEBA)
    assert usuario.ultimo_ingreso is not None


# --- Protección de rutas -----------------------------------------------------


@pytest.mark.parametrize("metodo,ruta", RUTAS_PRIVADAS)
def test_sin_sesion_ninguna_ruta_responde(cliente_anonimo, metodo, ruta):
    r = cliente_anonimo.request(metodo, ruta, follow_redirects=False)
    assert r.status_code == 303, f"{metodo} {ruta} respondió {r.status_code} sin sesión"
    assert r.headers["location"].startswith("/login")


def test_la_api_del_tablero_responde_401_y_no_html(cliente_anonimo):
    """El JS espera JSON: mandarle el HTML del login lo haría fallar raro."""
    r = cliente_anonimo.post("/api/leads/1/mover", json={"estado": "reunion"})
    assert r.status_code == 401
    assert r.json()["error"]


def test_el_login_y_lo_estatico_son_publicos(cliente_anonimo):
    assert cliente_anonimo.get("/login").status_code == 200
    assert cliente_anonimo.get("/static/app.css").status_code == 200
    assert cliente_anonimo.get("/salud").json() == {"ok": True}


def test_el_login_guarda_adonde_iba(cliente_anonimo):
    from urllib.parse import parse_qs, urlparse

    r = cliente_anonimo.get("/leads/3", follow_redirects=False)
    destino = urlparse(r.headers["location"])
    assert destino.path == "/login"
    assert parse_qs(destino.query)["siguiente"] == ["/leads/3"]


def test_tras_entrar_vuelve_a_donde_iba(cliente_anonimo, usuario):
    r = cliente_anonimo.post(
        "/login",
        data={"email": EMAIL_PRUEBA, "password": PASSWORD_PRUEBA, "siguiente": "/avisos"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/avisos"


def test_no_se_puede_usar_el_login_como_redirect_abierto(cliente_anonimo, usuario):
    """Un 'siguiente' externo convertiría al login en trampolín de phishing."""
    for destino in ("https://sitio-malo.com", "//sitio-malo.com"):
        r = cliente_anonimo.post(
            "/login",
            data={"email": EMAIL_PRUEBA, "password": PASSWORD_PRUEBA, "siguiente": destino},
            follow_redirects=False,
        )
        assert r.headers["location"] == "/"


def test_credenciales_malas_dan_401_y_no_crean_sesion(cliente_anonimo, usuario):
    r = cliente_anonimo.post(
        "/login", data={"email": EMAIL_PRUEBA, "password": "mal"}, follow_redirects=False
    )
    assert r.status_code == 401
    assert cliente_anonimo.get("/", follow_redirects=False).status_code == 303


def test_salir_cierra_la_sesion(cliente):
    assert cliente.get("/", follow_redirects=False).status_code == 200
    cliente.post("/logout", follow_redirects=False)
    assert cliente.get("/", follow_redirects=False).status_code == 303


def test_dar_de_baja_al_usuario_corta_la_sesion_en_curso(cliente, session_con_demo):
    """No hay que esperar a que venza la cookie para sacar a alguien."""
    assert cliente.get("/", follow_redirects=False).status_code == 200

    usuario = session_con_demo.query(Usuario).filter_by(email=EMAIL_PRUEBA).one()
    usuario.activo = False
    session_con_demo.commit()

    assert cliente.get("/", follow_redirects=False).status_code == 303


def test_la_pagina_muestra_quien_esta_conectado(cliente):
    html = cliente.get("/").text
    assert "Usuaria de prueba" in html
    assert 'action="/logout"' in html


# --- Primer usuario desde el entorno -----------------------------------------


def test_el_admin_inicial_se_crea_si_no_hay_usuarios(session, monkeypatch):
    """En un PaaS no siempre hay consola para correr `cli usuario`."""
    monkeypatch.setattr("talanton.config.ADMIN_EMAIL", "jefa@talanton.com.ar")
    monkeypatch.setattr("talanton.config.ADMIN_PASSWORD", "una-clave-bien-larga")
    monkeypatch.setattr("talanton.config.ADMIN_NOMBRE", "Jefa")

    creado = auth.crear_admin_inicial(session)
    assert creado is not None
    assert auth.autenticar(session, "jefa@talanton.com.ar", "una-clave-bien-larga")


def test_el_admin_inicial_no_pisa_usuarios_existentes(session, usuario, monkeypatch):
    """Si ya hay gente, cambiar las variables no puede crear ni pisar nada."""
    monkeypatch.setattr("talanton.config.ADMIN_EMAIL", "intruso@ajeno.com")
    monkeypatch.setattr("talanton.config.ADMIN_PASSWORD", "otra-clave-bien-larga")

    assert auth.crear_admin_inicial(session) is None
    assert auth.autenticar(session, "intruso@ajeno.com", "otra-clave-bien-larga") is None


def test_sin_variables_no_se_crea_nada(session, monkeypatch):
    monkeypatch.setattr("talanton.config.ADMIN_EMAIL", "")
    monkeypatch.setattr("talanton.config.ADMIN_PASSWORD", "")
    assert auth.crear_admin_inicial(session) is None
    assert not auth.hay_usuarios(session)


def test_una_clave_inicial_corta_no_rompe_el_arranque(session, monkeypatch):
    """Mejor quedarse sin usuario que tumbar el servicio en el deploy."""
    monkeypatch.setattr("talanton.config.ADMIN_EMAIL", "a@b.com")
    monkeypatch.setattr("talanton.config.ADMIN_PASSWORD", "corta")
    assert auth.crear_admin_inicial(session) is None

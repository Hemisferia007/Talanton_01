"""Tests del arranque en un paso.

Lo que importa acá es que la cadena no se corte: cada tramo depende del
anterior, y un paso que falla no puede tirar abajo los que ya salieron bien.
La red nunca se toca — el sondeo y la ingesta se inyectan.
"""

import pytest
from sqlalchemy import select

from talanton import arranque
from talanton.ingest import fuentes as fuentes_db
from talanton.models import Empresa, Lead


LISTA = "Empresa,Dominio\nAndes Logística,andeslog.com.ar\nCerámica Litoral,ceramlitoral.com.ar"


@pytest.fixture()
def sin_red(monkeypatch):
    """Neutraliza los dos tramos que salen a internet."""
    monkeypatch.setattr(arranque, "_sondear", lambda session: 0)
    monkeypatch.setattr(arranque, "_ingerir", lambda session: 0)


def test_el_arranque_deja_leads_puntuados(session, sin_red):
    resultado = arranque.primer_arranque(session, LISTA)

    assert resultado.sirvio
    assert resultado.empresas == 2
    assert len(session.scalars(select(Empresa)).all()) == 2
    assert len(session.scalars(select(Lead)).all()) == 2


def test_el_arranque_deja_las_empresas_vigiladas(session, sin_red):
    """Sin esto no hay avisos mañana, y sin avisos no hay producto."""
    arranque.primer_arranque(session, LISTA)

    nombres = {o.nombre for o in fuentes_db.listar_objetivos(session)}
    assert nombres == {"Andes Logística", "Cerámica Litoral"}


def test_cuenta_los_pasos_en_castellano(session, sin_red):
    resultado = arranque.primer_arranque(session, LISTA)

    nombres = [p.nombre for p in resultado.pasos]
    assert "Empresas cargadas" in nombres
    assert "Búsqueda de sus avisos" in nombres
    assert "Avisos traídos" in nombres
    assert "Leads puntuados" in nombres
    # Sin resultados el texto tiene que decir qué pasa después, no dejar un cero.
    paso = next(p for p in resultado.pasos if p.nombre == "Búsqueda de sus avisos")
    assert "corrida diaria" in paso.detalle


def test_una_lista_ilegible_no_rompe_nada(session, sin_red):
    resultado = arranque.primer_arranque(session, "Telefono\n1234")

    assert resultado.sirvio is False
    assert resultado.error and "empresa" in resultado.error
    assert session.scalars(select(Empresa)).all() == []


def test_texto_vacio_avisa(session, sin_red):
    resultado = arranque.primer_arranque(session, "   ")
    assert resultado.sirvio is False
    assert resultado.error


def test_un_sondeo_que_revienta_no_frena_el_arranque(session, monkeypatch):
    """El sondeo sale a internet y es lo más frágil de la cadena. Que falle no
    puede impedir que las empresas queden cargadas."""
    def revienta(session):
        raise RuntimeError("se cayó la red")

    monkeypatch.setattr(arranque, "_ingerir", lambda session: 0)
    monkeypatch.setattr(fuentes_db, "sondear_objetivo", revienta)

    resultado = arranque.primer_arranque(session, LISTA)
    assert resultado.empresas == 2
    assert len(session.scalars(select(Lead)).all()) == 2


def test_un_enriquecimiento_que_falla_queda_marcado(session, monkeypatch):
    from talanton.enriquecer import servicio as mod_enriquecer

    monkeypatch.setattr(arranque, "_sondear", lambda session: 0)
    monkeypatch.setattr(arranque, "_ingerir", lambda session: 0)
    monkeypatch.setattr(
        mod_enriquecer, "correr", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("dns"))
    )

    resultado = arranque.primer_arranque(session, LISTA)
    assert resultado.empresas == 2
    paso = next(p for p in resultado.pasos if p.nombre == "Contactos encontrados")
    assert paso.ok is False


def test_la_lista_de_arranque_es_importable():
    """Si la lista que viene cargada no parsea, la primera pantalla que ve
    alguien nuevo le muestra un error."""
    from talanton import importar

    resultado = importar.analizar(arranque.LISTA_IT_ARGENTINA)
    assert resultado.total >= 40
    assert resultado.ignoradas == []
    assert all(f.empresa and f.dominio for f in resultado.filas)


# --- Web ---------------------------------------------------------------------


def test_la_pantalla_trae_la_lista_cargada(cliente):
    r = cliente.get("/empezar")
    assert r.status_code == 200
    assert "Baufest" in r.text
    assert "Cargar y buscar avisos" in r.text


@pytest.fixture()
def cliente_sin_datos(session, usuario):
    """Como `cliente`, pero sin los datos de demo: base realmente vacía."""
    from fastapi.testclient import TestClient

    from talanton.web.app import app
    from tests.conftest import EMAIL_PRUEBA, PASSWORD_PRUEBA

    c = TestClient(app)
    r = c.post(
        "/login",
        data={"email": EMAIL_PRUEBA, "password": PASSWORD_PRUEBA},
        follow_redirects=False,
    )
    assert r.status_code == 303
    return c


def test_el_panel_vacio_invita_a_empezar(cliente_sin_datos):
    """Con la base vacía, un panel lleno de ceros no le dice a nadie qué hacer."""
    r = cliente_sin_datos.get("/")
    assert "Todavía no hay leads" in r.text
    assert 'href="/empezar"' in r.text


def test_el_panel_con_datos_no_muestra_la_invitacion(cliente, session_con_demo):
    r = cliente.get("/")
    assert "Todavía no hay leads" not in r.text


def test_empezar_desde_la_web(cliente, session, monkeypatch):
    monkeypatch.setattr(arranque, "_sondear", lambda session: 0)
    monkeypatch.setattr(arranque, "_ingerir", lambda session: 0)

    r = cliente.post("/empezar", data={"datos": LISTA, "pais": "AR"})
    assert r.status_code == 200
    assert "Listo." in r.text
    assert "2 empresas cargadas" in r.text


def test_la_pantalla_esta_protegida(cliente_anonimo):
    r = cliente_anonimo.get("/empezar", follow_redirects=False)
    assert r.status_code == 303

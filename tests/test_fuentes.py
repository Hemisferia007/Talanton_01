"""Tests de la administración de fuentes desde la web."""

import pytest

from talanton.ingest import fuentes as fuentes_db
from talanton.models import Fuente, Objetivo


# --- Alta de objetivos -------------------------------------------------------


def test_agrega_empresas_desde_texto_libre(session):
    nuevos, repetidos = fuentes_db.agregar_objetivos(session, """
        Andes Logística, andeslogistica.com.ar
        Cerámica Litoral, ceramicalitoral.com.ar
        Grupo Sanitario del Plata
    """)
    session.commit()

    assert (nuevos, repetidos) == (3, 0)
    objetivos = fuentes_db.listar_objetivos(session)
    assert {o.nombre for o in objetivos} == {
        "Andes Logística", "Cerámica Litoral", "Grupo Sanitario del Plata"
    }
    sin_dominio = next(o for o in objetivos if o.nombre.startswith("Grupo"))
    assert sin_dominio.dominio is None


def test_ignora_lineas_vacias_y_comentarios(session):
    nuevos, _ = fuentes_db.agregar_objetivos(session, "# comentario\n\nAndes\n   \n")
    assert nuevos == 1


def test_no_duplica_la_misma_empresa(session):
    """El mismo nombre con distinta forma societaria es la misma empresa."""
    fuentes_db.agregar_objetivos(session, "Andes Logística S.R.L., andes.com.ar")
    nuevos, repetidos = fuentes_db.agregar_objetivos(session, "andes logistica srl")
    session.commit()

    assert (nuevos, repetidos) == (0, 1)
    assert len(fuentes_db.listar_objetivos(session)) == 1


def test_sumar_el_dominio_despues_reabre_el_sondeo(session):
    """Con dominio hay muchas más chances de encontrar el board."""
    fuentes_db.agregar_objetivos(session, "Andes Logística")
    objetivo = fuentes_db.listar_objetivos(session)[0]
    objetivo.revisado_en = __import__("talanton.models", fromlist=["ahora"]).ahora()
    objetivo.resultado = "sin_fuente"
    session.flush()

    fuentes_db.agregar_objetivos(session, "Andes Logística, andeslogistica.com.ar")
    session.commit()

    assert objetivo.dominio == "andeslogistica.com.ar"
    assert objetivo.pendiente, "con dominio nuevo hay que volver a sondear"


def test_acepta_separadores_distintos(session):
    nuevos, _ = fuentes_db.agregar_objetivos(session, "Andes; andes.com.ar\nFintecho\tfintecho.com.ar")
    session.commit()
    assert nuevos == 2
    assert all(o.dominio for o in fuentes_db.listar_objetivos(session))


# --- Fuentes -----------------------------------------------------------------


def test_alta_de_fuente_es_idempotente(session):
    assert fuentes_db.agregar_fuente_manual(
        session, tipo="greenhouse", identificador="andes", empresa="Andes"
    )
    assert not fuentes_db.agregar_fuente_manual(
        session, tipo="greenhouse", identificador="andes", empresa="Andes"
    )
    session.commit()
    assert len(fuentes_db.listar_fuentes(session)) == 1


def test_una_fuente_sin_conector_queda_inactiva(session):
    """El hallazgo no se pierde, pero no se intenta ingerir lo que no sabemos leer."""
    fuentes_db._guardar_fuente(
        session, tipo="ashby", identificador="demo", empresa="Demo", dominio=None
    )
    session.commit()
    fuente = fuentes_db.listar_fuentes(session)[0]
    assert not fuente.activa
    assert fuentes_db.listar_fuentes(session, solo_activas=True) == []


def test_solo_se_arman_conectores_de_tipos_conocidos(session):
    for tipo, ident in [
        ("greenhouse", "a"), ("lever", "b"),
        ("pagina_carrera", "https://x.com/empleos"), ("ashby", "c"),
    ]:
        fuentes_db._guardar_fuente(
            session, tipo=tipo, identificador=ident, empresa="Demo", dominio=None
        )
    session.commit()

    tipos = {f.tipo for f, _ in fuentes_db.conectores_desde_base(session)}
    assert tipos == {"greenhouse", "lever", "pagina_carrera"}


def test_la_semilla_solo_corre_con_la_tabla_vacia(session):
    cargadas = fuentes_db.sembrar_desde_archivo(session)
    session.commit()
    assert cargadas > 0
    # Segunda vez no hace nada, para no revivir fuentes borradas a mano.
    assert fuentes_db.sembrar_desde_archivo(session) == 0


def test_la_semilla_descarta_la_url_de_ejemplo(session):
    fuentes_db.sembrar_desde_archivo(session)
    session.commit()
    assert not any("ejemplo.com" in f.identificador for f in fuentes_db.listar_fuentes(session))


# --- Pantalla ----------------------------------------------------------------


def test_la_pantalla_responde(cliente):
    r = cliente.get("/fuentes")
    assert r.status_code == 200
    assert "De dónde salen los avisos" in r.text


def test_agregar_desde_la_web(cliente, session_con_demo):
    r = cliente.post(
        "/fuentes/objetivos",
        data={"lineas": "Andes Logística, andeslogistica.com.ar\nFintecho"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    session_con_demo.expire_all()
    assert len(fuentes_db.listar_objetivos(session_con_demo)) == 2


def test_alternar_una_fuente(cliente, session_con_demo):
    fuentes_db.agregar_fuente_manual(
        session_con_demo, tipo="greenhouse", identificador="andes", empresa="Andes"
    )
    session_con_demo.commit()
    fuente = fuentes_db.listar_fuentes(session_con_demo)[0]
    assert fuente.activa

    cliente.post(f"/fuentes/{fuente.id}/alternar", follow_redirects=False)
    session_con_demo.expire_all()
    assert not session_con_demo.get(Fuente, fuente.id).activa


def test_sondear_una_empresa_inexistente_da_404(cliente):
    assert cliente.post("/fuentes/objetivos/99999/sondear").status_code == 404


def test_la_pantalla_esta_protegida(cliente_anonimo):
    r = cliente_anonimo.get("/fuentes", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login")

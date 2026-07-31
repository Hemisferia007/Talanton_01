"""Tests de la cola de trabajo del panel.

Es la pantalla que se abre a la mañana, así que lo que importa no es que
muestre datos sino que cada fila tenga **una** acción posible y que ninguna
esté en dos montones a la vez.
"""

import pytest

from talanton import services
from talanton.models import Contacto, EstadoLead, ahora
from talanton.services import cola_de_trabajo, destinatario


def _lead(session, nombre, *, con_mail=True, estado=EstadoLead.NUEVO, score=50):
    from talanton.models import Empresa
    from talanton.normalize import normalizar_nombre_empresa

    empresa = Empresa(
        nombre=nombre,
        nombre_normalizado=normalizar_nombre_empresa(nombre),
        pais="AR",
        dotacion_estimada=120,
    )
    if con_mail:
        empresa.contactos.append(
            Contacto(nombre="Alguien", email=f"rrhh@{nombre.lower().replace(' ', '')}.com",
                     es_decisor=True)
        )
    session.add(empresa)
    session.flush()
    lead = services.asegurar_lead(session, empresa)
    lead.estado = estado
    lead.score = score
    session.flush()
    return lead


def test_para_escribir_solo_entran_los_que_tienen_mail(session):
    """Sin mail no hay nada que hacer en esa cola: es trabajo de otro tipo."""
    con = _lead(session, "Con Mail")
    sin = _lead(session, "Sin Mail", con_mail=False)
    session.commit()

    cola = cola_de_trabajo(session)
    assert [l.id for l in cola["escribir"]] == [con.id]
    assert [l.id for l in cola["sin_contacto"]] == [sin.id]


def test_un_contactado_reciente_espera_y_no_se_insiste(session):
    lead = _lead(session, "Reciente", estado=EstadoLead.CONTACTADO)
    lead.ultimo_contacto_en = ahora().replace(tzinfo=None)
    session.commit()

    cola = cola_de_trabajo(session)
    assert [l.id for l in cola["esperando"]] == [lead.id]
    assert cola["insistir"] == []


def test_a_los_cinco_dias_pasa_a_insistir(session):
    from datetime import timedelta

    lead = _lead(session, "Vencido", estado=EstadoLead.CONTACTADO)
    lead.ultimo_contacto_en = (ahora() - timedelta(days=services.DIAS_PARA_INSISTIR)).replace(
        tzinfo=None
    )
    session.commit()

    cola = cola_de_trabajo(session)
    assert [l.id for l in cola["insistir"]] == [lead.id]
    assert cola["esperando"] == []


def test_la_competencia_no_entra_en_ninguna_cola(session):
    """Aunque tenga mail y score: no es cliente, no hay nada que escribirle."""
    _lead(session, "Randstad Argentina")
    session.commit()

    cola = cola_de_trabajo(session)
    assert cola["escribir"] == []
    assert cola["sin_contacto"] == []


def test_se_escribe_primero_al_de_mayor_score(session):
    floja = _lead(session, "Floja", score=20)
    fuerte = _lead(session, "Fuerte", score=90)
    session.commit()

    cola = cola_de_trabajo(session)
    assert [l.id for l in cola["escribir"]] == [fuerte.id, floja.id]


def test_el_tope_no_esconde_el_total(session):
    """Si hay 30 para escribir y se muestran 15, el número tiene que decir 30:
    si no, parece que el trabajo se terminó."""
    for i in range(6):
        _lead(session, f"Empresa {i}")
    session.commit()

    cola = cola_de_trabajo(session, tope=2)
    assert len(cola["escribir"]) == 2
    assert cola["total_escribir"] == 6


def test_el_destinatario_es_el_decisor(session):
    lead = _lead(session, "Con Decisor", con_mail=False)
    lead.empresa.contactos.append(Contacto(nombre="Genérico", email="info@x.com"))
    lead.empresa.contactos.append(
        Contacto(nombre="La que decide", email="rrhh@x.com", es_decisor=True)
    )
    session.commit()

    assert destinatario(lead) == "rrhh@x.com"


def test_sin_decisor_se_usa_el_primero_con_mail(session):
    lead = _lead(session, "Sin Decisor", con_mail=False)
    lead.empresa.contactos.append(Contacto(nombre="Genérico", email="info@y.com"))
    session.commit()

    assert destinatario(lead) == "info@y.com"


# --- Web ---------------------------------------------------------------------


def test_el_panel_muestra_las_dos_colas(cliente, session_con_demo):
    html = cliente.get("/").text
    assert "Escribirles hoy" in html
    assert "Volver a escribirles" in html


def test_cada_fila_lleva_a_la_ventana_de_redaccion(cliente, session):
    _lead(session, "Para Escribir", score=80)
    session.commit()

    html = cliente.get("/").text
    assert "?redactar=1" in html


def test_insistir_abre_con_la_plantilla_de_seguimiento(cliente, session):
    from datetime import timedelta

    lead = _lead(session, "Vencido", estado=EstadoLead.CONTACTADO)
    lead.ultimo_contacto_en = (ahora() - timedelta(days=9)).replace(tzinfo=None)
    session.commit()

    html = cliente.get("/").text
    assert "plantilla=seguimiento" in html


def test_redactar_en_la_url_abre_la_ventana_sola(cliente, session_con_demo, cuenta_gmail):
    lead = services.listar_leads(session_con_demo)[0]
    html = cliente.get(f"/leads/{lead.id}?redactar=1").text
    assert 'data-abrir="1"' in html
    # Y vuelve al panel al enviar: el próximo mail del día está ahí.
    assert 'name="volver" value="panel"' in html


def test_sin_el_parametro_la_ventana_queda_cerrada(cliente, session_con_demo, cuenta_gmail):
    lead = services.listar_leads(session_con_demo)[0]
    html = cliente.get(f"/leads/{lead.id}").text
    assert 'data-abrir="0"' in html


@pytest.fixture()
def cuenta_gmail(session):
    """La ventana de redacción sólo se renderiza con una casilla conectada."""
    from datetime import datetime, timedelta, timezone

    from talanton.correo import cripto
    from talanton.models import CuentaGmail

    c = CuentaGmail(
        email="yo@talanton.com.ar",
        refresh_token_cifrado=cripto.cifrar("x"),
        access_token="t",
        access_token_expira=datetime.now(timezone.utc).replace(tzinfo=None)
        + timedelta(hours=1),
    )
    session.add(c)
    session.commit()
    return c

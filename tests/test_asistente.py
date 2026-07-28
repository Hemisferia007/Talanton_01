"""Tests del asistente. Nunca se toca la red: el cliente se inyecta.

Lo que más se testea acá no es "¿llama bien a la API?" sino **qué sale de
Talanton hacia afuera**: que el expediente lleve lo que hace falta para decidir
y no lleve emails ni teléfonos.
"""

import json

import pytest

from talanton.asistente import conviene, escribir, expediente
from talanton.asistente.cliente import ErrorAsistente
from talanton.models import (
    Contacto,
    Direccion,
    Empresa,
    EstadoLead,
    EstadoMensaje,
    Mensaje,
    Seniority,
    Vacante,
    Veredicto,
    ahora,
)
from talanton.services import asegurar_lead, recalcular_lead


class ClienteFalso:
    """Devuelve lo que se le programó y guarda lo que se le pidió."""

    modelo = "modelo-de-prueba"

    def __init__(self, respuesta: dict | None = None, error: Exception | None = None):
        self.respuesta = respuesta or {}
        self.error = error
        self.pedidos: list[dict] = []

    def preguntar(self, *, sistema, mensaje, esquema, esfuerzo="medium", max_tokens=8000):
        self.pedidos.append(
            {
                "sistema": sistema,
                "mensaje": mensaje,
                "esquema": esquema,
                "esfuerzo": esfuerzo,
            }
        )
        if self.error:
            raise self.error
        return self.respuesta

    @property
    def ultimo_mensaje(self) -> str:
        return self.pedidos[-1]["mensaje"]


OPINION_OK = {
    "veredicto": "contactar",
    "confianza": "alta",
    "motivos": ["Hace 90 días que buscan un Jefe de Depósito y ya la republicaron."],
    "reparos": ["No sabemos quién decide."],
    "que_decir": "Abrir por la búsqueda de Jefe de Depósito en Mendoza.",
    "a_quien": "Gerente de Operaciones",
}


@pytest.fixture()
def lead_con_busqueda(session):
    empresa = Empresa(
        nombre="Logística del Sur",
        nombre_normalizado="logistica del sur",
        dominio="logisticadelsur.com.ar",
        industria="Logística",
        dotacion_estimada=180,
        pais="AR",
        ciudad="Mendoza",
    )
    empresa.vacantes.append(
        Vacante(
            titulo="Jefe de Depósito",
            rol_normalizado="jefe de deposito",
            seniority=Seniority.JEFATURA,
            ubicacion="Mendoza",
            pais="AR",
            descripcion="Buscamos jefe de depósito con experiencia en WMS.",
            fuente="linkedin",
            external_id="ld-1",
            primera_vez_vista=ahora().date().replace(year=ahora().year - 1),
            reposteos=2,
        )
    )
    empresa.contactos.append(
        Contacto(
            nombre="Mariana Suárez",
            cargo="Gerenta de Operaciones",
            email="mariana@logisticadelsur.com.ar",
            telefono="+54 261 555-0000",
            es_decisor=True,
        )
    )
    session.add(empresa)
    session.flush()
    lead = asegurar_lead(session, empresa)
    recalcular_lead(session, lead)
    session.commit()
    return lead


# --- Expediente: qué sale de Talanton ----------------------------------------


def test_expediente_lleva_lo_necesario_para_decidir(session, lead_con_busqueda):
    texto = expediente.armar(session, lead_con_busqueda)

    assert "Logística del Sur" in texto
    assert "Jefe de Depósito" in texto
    assert "republicada 2" in texto
    assert "WMS" in texto  # el texto del aviso, que es lo que el score no mira
    assert "Mariana Suárez" in texto
    assert "Gerenta de Operaciones" in texto


def test_expediente_no_saca_datos_de_contacto(session, lead_con_busqueda):
    """La frontera de privacidad: para juzgar un lead no hacen falta emails."""
    texto = expediente.armar(session, lead_con_busqueda)

    assert "mariana@logisticadelsur.com.ar" not in texto
    assert "555-0000" not in texto
    assert "@" not in texto


def test_expediente_marca_las_fechas_aproximadas(session, lead_con_busqueda):
    vacante = lead_con_busqueda.empresa.vacantes[0]
    vacante.fecha_aproximada = True
    session.flush()

    assert "~" in expediente.armar(session, lead_con_busqueda)


def test_firma_ignora_el_dia_suelto_pero_no_los_hechos(session, lead_con_busqueda):
    original = expediente.firma(lead_con_busqueda)

    # Un día más no cambia nada: avisar por eso entrena a ignorar el aviso.
    vacante = lead_con_busqueda.empresa.vacantes[0]
    vacante.primera_vez_vista = vacante.primera_vez_vista.replace(
        day=max(1, vacante.primera_vez_vista.day - 1)
    )
    session.flush()
    assert expediente.firma(lead_con_busqueda) == original

    # Un mensaje nuevo sí.
    session.add(
        Mensaje(
            lead_id=lead_con_busqueda.id,
            para="alguien@empresa.com",
            asunto="Hola",
            cuerpo="Texto",
        )
    )
    session.flush()
    session.refresh(lead_con_busqueda)
    assert expediente.firma(lead_con_busqueda) != original


# --- Opinión -----------------------------------------------------------------


def test_evaluar_guarda_la_opinion(session, lead_con_busqueda):
    cliente = ClienteFalso(OPINION_OK)
    opinion = conviene.evaluar(session, lead_con_busqueda, cliente=cliente)
    session.commit()

    assert opinion.veredicto == Veredicto.CONTACTAR
    assert opinion.confianza == "alta"
    assert opinion.lista_motivos == OPINION_OK["motivos"]
    assert opinion.lista_reparos == OPINION_OK["reparos"]
    assert opinion.a_quien == "Gerente de Operaciones"
    assert opinion.modelo == "modelo-de-prueba"
    assert lead_con_busqueda.opinion is opinion


def test_evaluar_no_toca_el_score(session, lead_con_busqueda):
    """El score es determinístico y explicable; el asistente queda al lado."""
    antes = (
        lead_con_busqueda.score,
        lead_con_busqueda.razones,
        lead_con_busqueda.gancho,
    )
    conviene.evaluar(session, lead_con_busqueda, cliente=ClienteFalso(OPINION_OK))
    session.commit()

    assert (
        lead_con_busqueda.score,
        lead_con_busqueda.razones,
        lead_con_busqueda.gancho,
    ) == antes


def test_evaluar_pisa_la_opinion_anterior(session, lead_con_busqueda):
    conviene.evaluar(session, lead_con_busqueda, cliente=ClienteFalso(OPINION_OK))
    session.commit()

    segunda = dict(OPINION_OK, veredicto="descartar", motivos=["Es demasiado chica."])
    conviene.evaluar(session, lead_con_busqueda, cliente=ClienteFalso(segunda))
    session.commit()

    from sqlalchemy import func, select

    from talanton.models import Opinion

    assert session.scalar(select(func.count()).select_from(Opinion)) == 1
    assert lead_con_busqueda.opinion.veredicto == Veredicto.DESCARTAR


def test_veredicto_desconocido_no_rompe_la_base(session, lead_con_busqueda):
    cliente = ClienteFalso(dict(OPINION_OK, veredicto="tal vez"))
    with pytest.raises(ErrorAsistente):
        conviene.evaluar(session, lead_con_busqueda, cliente=cliente)


def test_desactualizada_cuando_el_lead_cambia(session, lead_con_busqueda):
    conviene.evaluar(session, lead_con_busqueda, cliente=ClienteFalso(OPINION_OK))
    session.commit()
    assert conviene.desactualizada(lead_con_busqueda) is False

    lead_con_busqueda.estado = EstadoLead.EN_CONVERSACION
    session.flush()
    assert conviene.desactualizada(lead_con_busqueda) is True


def test_el_esquema_de_opinion_cierra_la_forma(session, lead_con_busqueda):
    """Sin `additionalProperties: false` la respuesta puede traer cualquier cosa."""
    cliente = ClienteFalso(OPINION_OK)
    conviene.evaluar(session, lead_con_busqueda, cliente=cliente)
    esquema = cliente.pedidos[0]["esquema"]

    assert esquema["additionalProperties"] is False
    assert set(esquema["required"]) == set(esquema["properties"])
    assert esquema["properties"]["veredicto"]["enum"] == [v.value for v in Veredicto]


# --- Redacción ---------------------------------------------------------------


BORRADOR_OK = {
    "asunto": "Re: Jefe de Depósito",
    "cuerpo": "Hola Mariana,\n\nGracias por contestar.",
    "lectura": "Retomé que pidieron hablar en agosto.",
}


def test_borrador_sin_hilo_pide_el_primer_mail(session, lead_con_busqueda):
    cliente = ClienteFalso(BORRADOR_OK)
    resultado = escribir.borrador(session, lead_con_busqueda, cliente=cliente)

    assert resultado["respondiendo"] is False
    assert "primer mail" in cliente.ultimo_mensaje
    assert resultado["asunto"] == BORRADOR_OK["asunto"]


def test_borrador_con_respuesta_pide_contestarla(session, lead_con_busqueda):
    session.add(
        Mensaje(
            lead_id=lead_con_busqueda.id,
            direccion=Direccion.ENTRANTE,
            estado=EstadoMensaje.RECIBIDO,
            de="Mariana",
            para="jonatan@talanton.com.ar",
            asunto="Re: Jefe de Depósito",
            cuerpo="Nos interesa, pero lo vemos en agosto.",
        )
    )
    session.flush()
    session.refresh(lead_con_busqueda)

    cliente = ClienteFalso(BORRADOR_OK)
    resultado = escribir.borrador(session, lead_con_busqueda, cliente=cliente)

    assert resultado["respondiendo"] is True
    assert "Escribí la respuesta" in cliente.ultimo_mensaje
    # El hilo tiene que viajar, si no el borrador contesta a ciegas.
    assert "lo vemos en agosto" in cliente.ultimo_mensaje


def test_la_instruccion_del_comercial_viaja_con_prioridad(session, lead_con_busqueda):
    cliente = ClienteFalso(BORRADOR_OK)
    escribir.borrador(
        session, lead_con_busqueda, instruccion="proponerle el jueves", cliente=cliente
    )

    assert "proponerle el jueves" in cliente.ultimo_mensaje
    assert "tiene prioridad" in cliente.ultimo_mensaje


def test_borrador_no_guarda_nada(session, lead_con_busqueda):
    """Un borrador que se guarda solo es un mail que alguien va a mandar sin leer."""
    escribir.borrador(session, lead_con_busqueda, cliente=ClienteFalso(BORRADOR_OK))
    session.commit()
    session.refresh(lead_con_busqueda)

    assert lead_con_busqueda.mensajes == []


# --- Cliente: manejo de respuestas raras --------------------------------------


class RespuestaFalsa:
    def __init__(self, texto="", stop_reason="end_turn"):
        self.stop_reason = stop_reason
        self.content = [type("B", (), {"type": "text", "text": texto})()]


def _cliente_con(respuesta):
    from talanton.asistente import cliente as mod

    c = mod.Cliente.__new__(mod.Cliente)
    c.modelo = "modelo-de-prueba"
    c._sdk = type(
        "SDK", (), {"messages": type("M", (), {"create": lambda *a, **k: respuesta})()}
    )()
    return c


def test_refusal_no_se_confunde_con_una_respuesta(session):
    cliente = _cliente_con(RespuestaFalsa("", stop_reason="refusal"))
    with pytest.raises(ErrorAsistente, match="prefirió no responder"):
        cliente.preguntar(sistema="x", mensaje="y", esquema={})


def test_respuesta_cortada_avisa_en_vez_de_reventar_al_parsear(session):
    cliente = _cliente_con(RespuestaFalsa('{"veredicto": "cont', stop_reason="max_tokens"))
    with pytest.raises(ErrorAsistente, match="cortada"):
        cliente.preguntar(sistema="x", mensaje="y", esquema={})


def test_respuesta_valida_se_parsea(session):
    cliente = _cliente_con(RespuestaFalsa(json.dumps(OPINION_OK)))
    assert cliente.preguntar(sistema="x", mensaje="y", esquema={}) == OPINION_OK


# --- Web ---------------------------------------------------------------------


@pytest.fixture()
def asistente_prendido(monkeypatch):
    """Simula la clave cargada sin que exista ninguna clave real."""
    from talanton.asistente import cliente as mod

    monkeypatch.setattr(mod, "ANTHROPIC_API_KEY", "clave-de-prueba")
    return mod


def test_sin_clave_el_panel_no_aparece(cliente, session_con_demo):
    from talanton import services

    lead = services.listar_leads(session_con_demo)[0]
    assert "¿Conviene contactarlo?" not in cliente.get(f"/leads/{lead.id}").text


def test_con_clave_aparece_el_panel(cliente, session_con_demo, asistente_prendido):
    from talanton import services

    lead = services.listar_leads(session_con_demo)[0]
    r = cliente.get(f"/leads/{lead.id}")
    assert "¿Conviene contactarlo?" in r.text
    assert "Que lo lea el asistente" in r.text


def test_pedir_opinion_la_muestra_en_la_pantalla(
    cliente, session_con_demo, asistente_prendido, monkeypatch
):
    from talanton import services

    # `app.py` importa el módulo, no la función: parchear acá alcanza para la ruta.
    monkeypatch.setattr(conviene, "_cliente", lambda: ClienteFalso(OPINION_OK))
    lead = services.listar_leads(session_con_demo)[0]

    r = cliente.post(f"/leads/{lead.id}/opinion", follow_redirects=True)
    assert r.status_code == 200
    assert "Conviene contactarlo" in r.text
    assert OPINION_OK["motivos"][0] in r.text
    assert OPINION_OK["reparos"][0] in r.text


def test_error_del_asistente_se_muestra_sin_romper_la_pantalla(
    cliente, session_con_demo, asistente_prendido, monkeypatch
):
    from talanton import services

    monkeypatch.setattr(
        conviene,
        "_cliente",
        lambda: ClienteFalso(error=ErrorAsistente("La API está limitando el uso")),
    )
    lead = services.listar_leads(session_con_demo)[0]

    r = cliente.post(f"/leads/{lead.id}/opinion", follow_redirects=True)
    assert r.status_code == 200
    assert "La API está limitando el uso" in r.text


def test_redactar_con_asistente_devuelve_el_borrador(
    cliente, session_con_demo, asistente_prendido, monkeypatch
):
    from talanton import services

    falso = ClienteFalso(BORRADOR_OK)
    monkeypatch.setattr(escribir, "_cliente", lambda: falso)
    lead = services.listar_leads(session_con_demo)[0]

    r = cliente.post(
        f"/leads/{lead.id}/redactar-ia", json={"instruccion": "proponer el jueves"}
    )
    assert r.status_code == 200
    assert r.json()["cuerpo"] == BORRADOR_OK["cuerpo"]
    assert "proponer el jueves" in falso.ultimo_mensaje


def test_redactar_con_asistente_informa_el_error(
    cliente, session_con_demo, asistente_prendido, monkeypatch
):
    from talanton import services

    monkeypatch.setattr(
        escribir,
        "_cliente",
        lambda: ClienteFalso(error=ErrorAsistente("No se pudo llegar a la API")),
    )
    lead = services.listar_leads(session_con_demo)[0]

    r = cliente.post(f"/leads/{lead.id}/redactar-ia", json={})
    assert r.status_code == 502
    assert "No se pudo llegar a la API" in r.json()["error"]


def test_las_rutas_del_asistente_exigen_sesion(cliente_anonimo, session_con_demo):
    from talanton import services

    lead = services.listar_leads(session_con_demo)[0]
    for ruta in (f"/leads/{lead.id}/opinion", f"/leads/{lead.id}/redactar-ia"):
        r = cliente_anonimo.post(ruta, follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]

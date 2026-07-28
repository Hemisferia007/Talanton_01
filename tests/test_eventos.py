"""Tests de las señales de financiamiento.

El clasificador es la parte frágil: corre sobre texto libre de posts, que están
llenos de gente ofreciendo servicios de inversión. Preferimos perder señales
antes que llenar la cola de revisión con ruido, porque una cola que nadie mira
no sirve para nada.
"""

from datetime import date, timedelta

import pytest

from talanton.ingest import eventos as eventos_db
from talanton.ingest import posts
from talanton.models import Evento, TipoEvento, ahora
from talanton.services import upsert_empresa, upsert_vacante, fecha_hoy


# --- Clasificación -----------------------------------------------------------


@pytest.mark.parametrize("texto", [
    "Estamos felices de anunciar que cerramos nuestra ronda de inversión Serie A "
    "por USD 5 millones para seguir creciendo en la región.",
    "Levantamos US$2M en una ronda semilla liderada por fondos regionales.",
    "We just raised $10 million in our Series B to expand across Latin America.",
    "Cerramos una ronda pre-seed con inversores de la región.",
])
def test_detecta_financiamiento(texto):
    assert posts.clasificar(texto) == TipoEvento.FINANCIAMIENTO


@pytest.mark.parametrize("texto", [
    "Con mucha alegría abrimos nuestra nueva planta en Pilar, con capacidad para "
    "duplicar la producción actual del grupo.",
    "Inauguramos una nueva sede en Córdoba para atender la demanda del interior.",
    "We're opening a new office in Buenos Aires this quarter.",
])
def test_detecta_expansion(texto):
    assert posts.clasificar(texto) == TipoEvento.EXPANSION


@pytest.mark.parametrize("texto", [
    "Estamos contratando: buscamos perfiles técnicos para sumar al equipo de "
    "ingeniería en los próximos meses.",
    "Duplicamos el equipo este año y seguimos sumando gente al área comercial.",
])
def test_detecta_contratacion(texto):
    assert posts.clasificar(texto) == TipoEvento.CONTRATACION


@pytest.mark.parametrize("texto", [
    # El ruido más común: quien *ofrece* servicios, no quien recibió la plata.
    "Te ayudo a conseguir una ronda de inversión para tu startup. Contactame.",
    "Curso de finanzas: cómo levantar una ronda de inversión paso a paso.",
    "Webinar gratuito sobre rondas de inversión en LatAm.",
    "Tips para preparar tu pitch de Serie A",
])
def test_descarta_el_ruido_de_quien_ofrece_servicios(texto):
    assert posts.clasificar(texto) is None


@pytest.mark.parametrize("texto", [
    None, "", "corto",
    "Hoy fue un gran día en la oficina, gracias equipo por el esfuerzo de siempre.",
    "Reflexiones sobre liderazgo y cultura organizacional en tiempos de cambio.",
])
def test_un_post_cualquiera_no_es_senal(texto):
    assert posts.clasificar(texto) is None


def test_mencionar_inversion_sin_operacion_no_alcanza():
    """Sin verbo ni monto, cualquier post de marketing entraría."""
    assert posts.clasificar(
        "La inversión en tecnología es clave para el crecimiento de las empresas "
        "argentinas en el contexto actual del mercado regional."
    ) is None


# --- Empresa mencionada ------------------------------------------------------


def test_una_pagina_de_empresa_es_la_empresa():
    item = {"author": {"type": "company", "name": "Fintecho"}}
    assert posts.detectar_empresa(item, "texto") == "Fintecho"


def test_de_una_persona_se_toma_su_empresa():
    item = {"author": {"type": "person", "name": "Diego Ferrari", "companyName": "Fintecho"}}
    # Se guarda la empresa, no la persona: su dato no nos hace falta.
    assert posts.detectar_empresa(item, "texto") == "Fintecho"


def test_como_ultimo_recurso_busca_un_sufijo_societario():
    assert posts.detectar_empresa({}, "Felicitaciones a Andes Logística S.R.L. por la ronda") \
        == "Andes Logística S.R.L."


def test_sin_empresa_identificable_devuelve_none():
    assert posts.detectar_empresa({}, "cerramos la ronda, gracias a todos") is None


# --- Mapeo -------------------------------------------------------------------

HOY = date(2026, 7, 27)


def test_mapea_un_post_de_financiamiento():
    evento = posts.mapear({
        "text": "Cerramos nuestra ronda Serie A por USD 4 millones.",
        "author": {"type": "company", "name": "Fintecho"},
        "postedAt": "2026-07-01",
        "url": "https://linkedin.com/posts/1",
        "id": "post-1",
    }, hoy=HOY)

    assert evento.tipo == TipoEvento.FINANCIAMIENTO
    assert evento.empresa_mencionada == "Fintecho"
    assert evento.fecha == date(2026, 7, 1)
    assert evento.external_id == "post-1"
    assert "Fintecho" in evento.titulo


def test_un_post_sin_senal_no_se_mapea():
    assert posts.mapear({"text": "Buen día a todos, gracias por el apoyo de siempre."}) is None


def test_un_post_con_senal_pero_sin_empresa_se_descarta():
    """Sin empresa el evento no se puede vincular y sólo ensucia la cola."""
    assert posts.mapear({"text": "Cerramos nuestra ronda Serie A por USD 4 millones."}) is None


def test_una_fecha_relativa_queda_marcada():
    evento = posts.mapear({
        "text": "Levantamos una ronda semilla de US$1M.",
        "companyName": "Demo SA",
        "postedAt": "hace 3 semanas",
    }, hoy=HOY)
    assert evento.fecha_aproximada


# --- Persistencia ------------------------------------------------------------


def _crudo(empresa="Fintecho", tipo=TipoEvento.FINANCIAMIENTO, dias=10, ext="e1"):
    return posts.EventoCrudo(
        tipo=tipo, titulo=f"{tipo.etiqueta}: {empresa}",
        resumen="Cerramos la ronda.", empresa_mencionada=empresa,
        fecha=fecha_hoy() - timedelta(days=dias), fecha_aproximada=False,
        fuente="linkedin_posts", external_id=ext,
    )


def test_se_vincula_a_la_empresa_si_ya_esta_en_la_base(session):
    upsert_empresa(session, "Fintecho", dominio="fintecho.com.ar")
    session.commit()

    resumen = eventos_db.persistir_eventos(session, [_crudo()])
    assert (resumen.nuevos, resumen.vinculados) == (1, 1)


def test_una_empresa_desconocida_se_carga_como_objetivo(session):
    """Levantó plata y todavía no publicó nada: justo queremos estar mirando."""
    from talanton.ingest.fuentes import listar_objetivos

    resumen = eventos_db.persistir_eventos(session, [_crudo("Empresa Nueva SA")])
    assert resumen.objetivos_creados == 1
    assert any(o.nombre == "Empresa Nueva SA" for o in listar_objetivos(session))


def test_no_se_duplica_el_mismo_post(session):
    eventos_db.persistir_eventos(session, [_crudo()])
    resumen = eventos_db.persistir_eventos(session, [_crudo()])
    assert resumen.nuevos == 0


def test_las_senales_entran_sin_confirmar(session):
    eventos_db.persistir_eventos(session, [_crudo()])
    evento = session.query(Evento).one()
    assert evento.pendiente_revision
    assert not evento.vigente, "sin confirmar no puede pesar en el score"


# --- Efecto en el score ------------------------------------------------------


def _empresa_con_busqueda(session):
    empresa = upsert_empresa(session, "Fintecho", dominio="fintecho.com.ar", dotacion_estimada=60)
    upsert_vacante(
        session, empresa, titulo="Líder Técnico", fuente="t", external_id="v1",
        fecha_publicacion=fecha_hoy() - timedelta(days=50),
    )
    session.refresh(empresa)
    return empresa


def test_una_senal_sin_confirmar_no_mueve_el_score(session):
    from talanton.services import asegurar_lead, perfil, recalcular_lead

    empresa = _empresa_con_busqueda(session)
    lead = recalcular_lead(session, asegurar_lead(session, empresa), perfil(session))
    antes = lead.score
    session.commit()

    eventos_db.persistir_eventos(session, [_crudo()])
    session.refresh(empresa)
    recalcular_lead(session, lead, perfil(session))
    assert lead.score == antes


def test_confirmar_una_ronda_sube_capacidad_de_pago_y_urgencia(session):
    from talanton.services import asegurar_lead, perfil, recalcular_lead

    empresa = _empresa_con_busqueda(session)
    lead = recalcular_lead(session, asegurar_lead(session, empresa), perfil(session))
    pago_antes, urgencia_antes = lead.score_pago, lead.score_urgencia
    session.commit()

    eventos_db.persistir_eventos(session, [_crudo()])
    eventos_db.confirmar(session, session.query(Evento).one())
    session.refresh(lead)

    assert lead.score_pago > pago_antes
    # Ronda + búsquedas abiertas es la mejor combinación posible.
    assert lead.score_urgencia > urgencia_antes
    assert any("ronda" in r for r in lead.lista_razones)


def test_el_gancho_menciona_la_ronda(session):
    from talanton.services import asegurar_lead, perfil, recalcular_lead

    empresa = _empresa_con_busqueda(session)
    lead = recalcular_lead(session, asegurar_lead(session, empresa), perfil(session))
    session.commit()

    eventos_db.persistir_eventos(session, [_crudo()])
    eventos_db.confirmar(session, session.query(Evento).one())
    session.refresh(lead)
    assert "ronda" in (lead.gancho or "")


def test_una_ronda_vieja_deja_de_contar(session):
    """El efecto sobre la contratación dura unos meses, no para siempre."""
    empresa = _empresa_con_busqueda(session)
    eventos_db.persistir_eventos(session, [_crudo(dias=400)])
    evento = session.query(Evento).one()
    eventos_db.confirmar(session, evento)
    assert not evento.vigente


def test_descartar_una_senal_la_saca_del_score(session):
    from talanton.services import asegurar_lead, perfil, recalcular_lead

    empresa = _empresa_con_busqueda(session)
    lead = recalcular_lead(session, asegurar_lead(session, empresa), perfil(session))
    session.commit()

    eventos_db.persistir_eventos(session, [_crudo()])
    evento = session.query(Evento).one()
    eventos_db.confirmar(session, evento)
    session.refresh(lead)
    con_senal = lead.score_pago

    eventos_db.descartar(session, evento)
    session.refresh(lead)
    assert lead.score_pago < con_senal


# --- Pantalla ----------------------------------------------------------------


def test_la_cola_de_senales_responde(cliente):
    r = cliente.get("/senales")
    assert r.status_code == 200
    assert "Señales para revisar" in r.text


def test_la_cola_muestra_las_pendientes(cliente, session_con_demo):
    eventos_db.persistir_eventos(session_con_demo, [_crudo("Fintecho")])
    html = cliente.get("/senales").text
    assert "Fintecho" in html
    assert "Confirmar" in html


def test_confirmar_desde_la_web(cliente, session_con_demo):
    eventos_db.persistir_eventos(session_con_demo, [_crudo("Fintecho")])
    evento = session_con_demo.query(Evento).one()

    r = cliente.post(f"/senales/{evento.id}/confirmar", follow_redirects=False)
    assert r.status_code == 303
    session_con_demo.expire_all()
    assert session_con_demo.get(Evento, evento.id).confirmado


def test_descartar_desde_la_web(cliente, session_con_demo):
    eventos_db.persistir_eventos(session_con_demo, [_crudo("Fintecho")])
    evento = session_con_demo.query(Evento).one()

    cliente.post(f"/senales/{evento.id}/descartar", follow_redirects=False)
    session_con_demo.expire_all()
    assert session_con_demo.get(Evento, evento.id).descartado


def test_una_senal_inexistente_da_404(cliente):
    assert cliente.post("/senales/99999/confirmar").status_code == 404


def test_la_cola_esta_protegida(cliente_anonimo):
    r = cliente_anonimo.get("/senales", follow_redirects=False)
    assert r.status_code == 303

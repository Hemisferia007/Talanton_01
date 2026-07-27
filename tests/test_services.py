from datetime import timedelta

from talanton import services
from talanton.models import EstadoLead
from talanton.services import (
    asegurar_lead,
    cerrar_vacantes_no_vistas,
    fecha_hoy,
    mover_lead,
    upsert_empresa,
    upsert_vacante,
)


def test_upsert_empresa_no_duplica_por_sufijo_ni_dominio(session):
    a = upsert_empresa(session, "Andes Logística S.R.L.", dominio="andeslogistica.com.ar")
    b = upsert_empresa(session, "andes logistica srl")
    c = upsert_empresa(session, "Andes Logística", dominio="https://www.andeslogistica.com.ar")
    assert a.id == b.id == c.id


def test_upsert_empresa_no_pisa_datos_ya_cargados(session):
    empresa = upsert_empresa(session, "Fintecho", dominio="fintecho.com.ar", industria="Fintech")
    upsert_empresa(session, "Fintecho", dominio="fintecho.com.ar", industria="Otra cosa")
    assert empresa.industria == "Fintech"


def test_primera_vez_vista_no_se_pisa_en_corridas_sucesivas(session):
    """Es el dato que sostiene todo el cálculo de días abiertos."""
    empresa = upsert_empresa(session, "Demo SA", dominio="demo.com")
    hace_60 = fecha_hoy() - timedelta(days=60)
    vacante, nueva = upsert_vacante(
        session, empresa, titulo="Jefe de Obra", fuente="t", external_id="1", vista_el=hace_60
    )
    assert nueva
    original = vacante.primera_vez_vista

    vacante2, nueva2 = upsert_vacante(
        session, empresa, titulo="Jefe de Obra", fuente="t", external_id="1", vista_el=fecha_hoy()
    )
    assert not nueva2
    assert vacante2.id == vacante.id
    assert vacante2.primera_vez_vista == original
    assert vacante2.ultima_vez_vista == fecha_hoy()


def test_vacante_que_desaparece_se_cierra_y_al_volver_cuenta_reposteo(session):
    empresa = upsert_empresa(session, "Demo SA", dominio="demo.com")
    ayer = fecha_hoy() - timedelta(days=1)
    upsert_vacante(session, empresa, titulo="Contador Senior", fuente="t", external_id="9", vista_el=ayer)

    cerradas = cerrar_vacantes_no_vistas(session, "t", fecha_hoy())
    assert cerradas == 1

    vacante, nueva = upsert_vacante(
        session, empresa, titulo="Contador Senior", fuente="t", external_id="9", vista_el=fecha_hoy()
    )
    assert not nueva
    assert not vacante.cerrada
    assert vacante.reposteos == 1


def test_dias_abierta_congela_al_cerrar(session):
    empresa = upsert_empresa(session, "Demo SA", dominio="demo.com")
    vacante, _ = upsert_vacante(
        session,
        empresa,
        titulo="Analista",
        fuente="t",
        external_id="5",
        fecha_publicacion=fecha_hoy() - timedelta(days=100),
    )
    vacante.cerrada = True
    vacante.fecha_cierre = fecha_hoy() - timedelta(days=60)
    assert vacante.dias_abierta == 40


def test_mover_lead_registra_el_cambio_en_el_timeline(session):
    empresa = upsert_empresa(session, "Demo SA", dominio="demo.com")
    lead = asegurar_lead(session, empresa)
    mover_lead(session, lead, EstadoLead.CONTACTADO, autor="Jonatan")
    session.commit()

    assert lead.estado == EstadoLead.CONTACTADO
    assert lead.ultimo_contacto_en is not None
    assert any(a.tipo == "cambio_estado" for a in lead.actividades)


def test_asegurar_lead_es_idempotente(session):
    empresa = upsert_empresa(session, "Demo SA", dominio="demo.com")
    assert asegurar_lead(session, empresa).id == asegurar_lead(session, empresa).id


def test_tablero_cubre_todas_las_columnas(session_con_demo):
    columnas = services.tablero(session_con_demo)
    assert set(columnas) == set(EstadoLead)
    assert sum(len(v) for v in columnas.values()) == len(services.listar_leads(session_con_demo))


def test_solo_urgentes_filtra_por_45_dias(session_con_demo):
    urgentes = services.listar_vacantes(session_con_demo, solo_urgentes=True)
    assert urgentes
    assert all(v.dias_abierta >= 45 and not v.cerrada for v in urgentes)

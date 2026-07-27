from datetime import timedelta

from talanton import scoring, services
from talanton.services import fecha_hoy, upsert_empresa, upsert_vacante


def _empresa_con_vacante(session, dias_abierta, **kwargs):
    empresa = upsert_empresa(
        session,
        kwargs.pop("nombre", "Empresa Demo"),
        dominio=kwargs.pop("dominio", "demo.com.ar"),
        pais="AR",
        industria="Logística",
        dotacion_estimada=150,
    )
    upsert_vacante(
        session,
        empresa,
        titulo=kwargs.pop("titulo", "Jefe de Depósito"),
        fuente="test",
        external_id=kwargs.pop("external_id", "t-1"),
        fecha_publicacion=fecha_hoy() - timedelta(days=dias_abierta),
    )
    session.refresh(empresa)
    return empresa


def test_vacante_vieja_puntua_mas_que_reciente(session):
    perfil = services.perfil(session)
    reciente = _empresa_con_vacante(session, 5, nombre="Reciente SA", dominio="a.com", external_id="a")
    vieja = _empresa_con_vacante(session, 90, nombre="Vieja SA", dominio="b.com", external_id="b")

    assert scoring.calcular(vieja, perfil).urgencia > scoring.calcular(reciente, perfil).urgencia


def test_sin_vacantes_abiertas_no_hay_urgencia(session):
    perfil = services.perfil(session)
    empresa = upsert_empresa(session, "Sin Búsquedas SA", dominio="c.com", pais="AR")
    session.refresh(empresa)
    resultado = scoring.calcular(empresa, perfil)
    assert resultado.urgencia == 0
    assert resultado.gancho is None


def test_el_score_siempre_trae_razones(session):
    perfil = services.perfil(session)
    empresa = _empresa_con_vacante(session, 60)
    resultado = scoring.calcular(empresa, perfil)
    assert resultado.razones, "un score sin razones no lo puede usar el comercial"
    assert 0 <= resultado.total <= 100


def test_gancho_menciona_los_dias_reales(session):
    perfil = services.perfil(session)
    empresa = _empresa_con_vacante(session, 52)
    resultado = scoring.calcular(empresa, perfil)
    assert "52 días" in resultado.gancho


def test_lead_tomado_por_otra_consultora_baja_accesibilidad(session):
    perfil = services.perfil(session)
    empresa = _empresa_con_vacante(session, 60)
    antes = scoring.calcular(empresa, perfil).accesibilidad

    for vacante in empresa.vacantes:
        vacante.publicada_por_consultora = True
    session.flush()
    session.refresh(empresa)

    assert scoring.calcular(empresa, perfil).accesibilidad < antes


def test_pais_fuera_del_icp_baja_el_fit(session):
    perfil = services.perfil(session)
    perfil.paises_objetivo = "MX"
    session.flush()
    empresa = _empresa_con_vacante(session, 60)
    dentro = scoring.calcular(empresa, perfil).fit

    perfil.paises_objetivo = "AR"
    session.flush()
    assert scoring.calcular(empresa, perfil).fit > dentro

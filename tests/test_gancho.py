"""El gancho se le dice al cliente tal cual, así que no puede afirmar nada falso."""

from datetime import timedelta

from talanton import scoring, services
from talanton.services import fecha_hoy, upsert_empresa, upsert_vacante


def _empresa(session):
    return upsert_empresa(
        session, "Demo SA", dominio="demo.com.ar", pais="AR", dotacion_estimada=120
    )


def test_no_menciona_reposteo_de_otra_busqueda(session):
    """La empresa reposteó una vacante, pero no la que aparece en el gancho."""
    perfil = services.perfil(session)
    empresa = _empresa(session)

    vieja, _ = upsert_vacante(
        session,
        empresa,
        titulo="Líder Técnico Backend",
        fuente="t",
        external_id="1",
        fecha_publicacion=fecha_hoy() - timedelta(days=74),
    )
    reposteada, _ = upsert_vacante(
        session,
        empresa,
        titulo="Desarrollador Full Stack Semi Senior",
        fuente="t",
        external_id="2",
        fecha_publicacion=fecha_hoy() - timedelta(days=30),
    )
    reposteada.reposteos = 1
    session.flush()
    session.refresh(empresa)

    resultado = scoring.calcular(empresa, perfil)
    assert "Líder Técnico Backend" in resultado.gancho
    assert "republicaron" not in resultado.gancho
    # La señal sigue contando para el score, sólo no entra en el gancho.
    assert any("reposteo" in r for r in resultado.razones)


def test_menciona_reposteo_cuando_es_la_misma_busqueda(session):
    perfil = services.perfil(session)
    empresa = _empresa(session)
    vacante, _ = upsert_vacante(
        session,
        empresa,
        titulo="Jefe de Depósito",
        fuente="t",
        external_id="3",
        fecha_publicacion=fecha_hoy() - timedelta(days=92),
    )
    vacante.reposteos = 2
    session.flush()
    session.refresh(empresa)

    gancho = scoring.calcular(empresa, perfil).gancho
    assert "Jefe de Depósito" in gancho
    assert "republicaron" in gancho

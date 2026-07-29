from datetime import timedelta

import pytest

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


# --- Avisos perennes y proveedores -------------------------------------------
#
# Los dos falsos positivos que más daño hacen, porque los dos se trepan solos
# al tope del ranking: un buzón de CVs que nunca cierra acumula días para
# siempre, y una consultora que publica las vacantes de sus clientes parece la
# empresa más desesperada del mercado.


@pytest.mark.parametrize(
    "titulo",
    [
        "General Applications",
        "Any Other Talent? Apply!",
        "Candidatura espontánea",
        "Talent Pool",
        "Spontaneous Application",
        "Trabajá con nosotros",
        "No encontraste tu puesto?",
    ],
)
def test_los_buzones_de_cv_no_son_busquedas(titulo):
    from talanton.normalize import es_aviso_perenne

    assert es_aviso_perenne(titulo) is True


@pytest.mark.parametrize(
    "titulo",
    ["DevOps Engineer", "Jefe de Depósito", "Head of Sales", "Data Engineer Senior"],
)
def test_una_busqueda_real_no_se_confunde_con_un_buzon(titulo):
    from talanton.normalize import es_aviso_perenne

    assert es_aviso_perenne(titulo) is False


def test_un_aviso_perenne_no_cuenta_como_busqueda_abierta(session):
    """Estaba primero en el panel con 2192 días abiertos. No es una búsqueda
    que no se logra cerrar: es un buzón que nadie cierra nunca."""
    from datetime import timedelta

    from talanton.models import Empresa, Vacante, ahora
    from talanton.normalize import normalizar_nombre_empresa

    empresa = Empresa(nombre="Emi Labs", nombre_normalizado=normalizar_nombre_empresa("Emi Labs"))
    hace_seis_anios = ahora().date() - timedelta(days=2192)
    empresa.vacantes.append(
        Vacante(titulo="General Applications", rol_normalizado="general applications",
                fuente="greenhouse", external_id="g-1", primera_vez_vista=hace_seis_anios)
    )
    empresa.vacantes.append(
        Vacante(titulo="Back-end Engineer", rol_normalizado="backend engineer",
                fuente="greenhouse", external_id="g-2", primera_vez_vista=hace_seis_anios)
    )
    session.add(empresa)
    session.flush()

    abiertas = empresa.vacantes_abiertas
    assert [v.titulo for v in abiertas] == ["Back-end Engineer"]
    # No desaparece: se muestra aparte, marcado.
    assert [v.titulo for v in empresa.vacantes_perennes] == ["General Applications"]


def test_una_empresa_con_cientos_de_vacantes_es_un_proveedor(session):
    """Nadie con 200 empleados tiene 800 búsquedas propias abiertas."""
    from talanton.models import Empresa, Vacante
    from talanton.normalize import normalizar_nombre_empresa

    empresa = Empresa(
        nombre="Bluelight Consulting",
        nombre_normalizado=normalizar_nombre_empresa("Bluelight Consulting"),
    )
    for i in range(60):
        empresa.vacantes.append(
            Vacante(titulo=f"Puesto {i}", rol_normalizado=f"puesto {i}",
                    fuente="lever", external_id=f"l-{i}")
        )
    session.add(empresa)
    session.flush()

    assert empresa.parece_proveedor is True


def test_una_consultora_se_detecta_por_el_nombre(session):
    from talanton.models import Empresa
    from talanton.normalize import normalizar_nombre_empresa

    e = Empresa(nombre="Randstad Argentina",
                nombre_normalizado=normalizar_nombre_empresa("Randstad Argentina"))
    assert e.parece_proveedor is True


def test_un_proveedor_no_puntua_como_lead(session):
    """Es competencia, no cliente. Que publique mucho no lo vuelve caliente."""
    from talanton.models import Empresa, Vacante
    from talanton.normalize import normalizar_nombre_empresa
    from talanton.scoring import calcular
    from talanton.services import perfil

    empresa = Empresa(nombre="Staffing del Plata",
                      nombre_normalizado=normalizar_nombre_empresa("Staffing del Plata"),
                      pais="AR", dotacion_estimada=200)
    for i in range(50):
        empresa.vacantes.append(
            Vacante(titulo=f"Desarrollador {i}", rol_normalizado=f"developer {i}",
                    fuente="lever", external_id=f"s-{i}")
        )
    session.add(empresa)
    session.flush()

    resultado = calcular(empresa, perfil(session))
    assert resultado.accesibilidad <= 5
    assert any("competencia" in r for r in resultado.razones)

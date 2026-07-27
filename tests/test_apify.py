"""Tests del conector de Apify. Nunca se toca la red."""

from datetime import date, timedelta

import pytest

from talanton.ingest import apify
from talanton.ingest import fuentes as fuentes_db


# --- Antigüedad --------------------------------------------------------------

HOY = date(2026, 7, 27)


@pytest.mark.parametrize(
    "texto,dias,aprox",
    [
        ("hoy", 0, False),
        ("Today", 0, False),
        ("ayer", 1, False),
        ("hace 3 días", 3, False),
        ("3 days ago", 3, False),
        ("hace 2 semanas", 14, True),
        ("2 weeks ago", 14, True),
        ("hace 1 mes", 30, True),
        ("3 months ago", 90, True),
    ],
)
def test_interpreta_antiguedad_relativa(texto, dias, aprox):
    fecha, aproximada = apify.interpretar_antiguedad(texto, HOY)
    assert fecha == HOY - timedelta(days=dias)
    assert aproximada is aprox


def test_una_fecha_iso_no_es_aproximada():
    fecha, aproximada = apify.interpretar_antiguedad("2026-05-10T12:00:00Z", HOY)
    assert fecha == date(2026, 5, 10)
    assert not aproximada


def test_texto_que_no_se_entiende_no_inventa_fecha():
    for basura in (None, "", "cualquier cosa", "hace mucho"):
        fecha, aprox = apify.interpretar_antiguedad(basura, HOY)
        assert fecha is None and not aprox


def test_las_semanas_se_marcan_aproximadas_y_los_dias_no():
    """El número va en un mail al cliente: «hace 14 días» de un «2 semanas»
    tiene una semana de error y hay que decirlo."""
    _, por_semanas = apify.interpretar_antiguedad("hace 2 semanas", HOY)
    _, por_dias = apify.interpretar_antiguedad("hace 14 días", HOY)
    assert por_semanas
    assert not por_dias


# --- Mapeo -------------------------------------------------------------------


def test_mapea_un_resultado_tipico():
    item = {
        "title": "Jefe de Mantenimiento Industrial",
        "companyName": "Cerámica Litoral",
        "location": "Paraná, Entre Ríos, Argentina",
        "jobUrl": "https://www.linkedin.com/jobs/view/123",
        "postedAt": "2026-05-10",
        "descriptionText": "Buscamos jefe de mantenimiento.",
        "id": "123",
    }
    v = apify.mapear(item)
    assert v.titulo == "Jefe de Mantenimiento Industrial"
    assert v.empresa == "Cerámica Litoral"
    assert v.pais == "AR"
    assert v.external_id == "123"
    assert v.fecha_publicacion == date(2026, 5, 10)
    assert not v.fecha_aproximada


def test_tolera_otros_nombres_de_campo():
    """Cada actor de la tienda nombra los campos a su manera."""
    v = apify.mapear({
        "positionName": "Contador Senior",
        "company": "Agroexport Pampa",
        "formattedLocation": "Rosario, Argentina",
        "link": "https://x.com/1",
        "publishedAt": "hace 5 semanas",
    })
    assert v.titulo == "Contador Senior"
    assert v.empresa == "Agroexport Pampa"
    assert v.fecha_aproximada


def test_descarta_resultados_sin_titulo_o_empresa():
    assert apify.mapear({"title": "Sin empresa"}) is None
    assert apify.mapear({"companyName": "Sin título"}) is None
    assert apify.mapear({}) is None


def test_sin_id_genera_uno_estable():
    item = {"title": "Jefe", "companyName": "Demo", "location": "CABA"}
    assert apify.mapear(item).external_id == apify.mapear(item).external_id


def test_no_toma_linkedin_com_como_dominio_de_la_empresa():
    """linkedin.com/company/x no es el sitio de la empresa."""
    v = apify.mapear({
        "title": "Jefe", "companyName": "Demo",
        "companyUrl": "https://www.linkedin.com/company/demo",
    })
    assert v.empresa_dominio is None

    v2 = apify.mapear({
        "title": "Jefe", "companyName": "Demo",
        "companyUrl": "https://demo.com.ar",
    })
    assert v2.empresa_dominio == "demo.com.ar"


# --- Conector ----------------------------------------------------------------


class ClienteFalso:
    def __init__(self, resultados=None, falla=None):
        self.resultados = resultados or []
        self.falla = falla
        self.llamadas = []

    def correr_actor(self, actor, entrada):
        self.llamadas.append((actor, entrada))
        if self.falla:
            raise apify.ErrorApify(self.falla)
        return self.resultados


def test_la_busqueda_mapea_y_descarta_lo_inservible():
    cliente = ClienteFalso([
        {"title": "Jefe de Obra", "companyName": "Riobamba", "location": "Córdoba, Argentina"},
        {"title": "Sin empresa"},
        "esto no es un dict",
    ])
    busqueda = apify.BusquedaApify("u/actor", {"rows": 10}, cliente=cliente)
    vacantes = busqueda.fetch()

    assert len(vacantes) == 1
    assert vacantes[0].empresa == "Riobamba"
    assert cliente.llamadas == [("u/actor", {"rows": 10})]


def test_desde_configuracion_extrae_actor_y_pais():
    b = apify.desde_configuracion(
        '{"_actor": "u/linkedin", "_pais": "UY", "title": "contador", "rows": 50}',
        "Contadores Uruguay",
    )
    assert b.actor == "u/linkedin"
    assert b.pais == "UY"
    # Los parámetros internos no se le mandan al actor.
    assert b.configuracion == {"title": "contador", "rows": 50}


def test_configuracion_sin_actor_falla_claro():
    with pytest.raises(apify.ErrorApify, match="_actor"):
        apify.desde_configuracion('{"title": "contador"}')


def test_configuracion_que_no_es_json_falla_claro():
    with pytest.raises(apify.ErrorApify, match="JSON"):
        apify.desde_configuracion("{roto")


def test_sin_token_el_error_es_accionable(monkeypatch):
    monkeypatch.setattr("talanton.ingest.apify.APIFY_TOKEN", "")
    busqueda = apify.BusquedaApify("u/actor", {})
    with pytest.raises(apify.ErrorApify, match="TALANTON_APIFY_TOKEN"):
        busqueda.fetch()


# --- Alta como fuente --------------------------------------------------------


def test_alta_de_busqueda_valida_el_json_antes_de_guardar(session):
    with pytest.raises(apify.ErrorApify):
        fuentes_db.agregar_busqueda_linkedin(
            session, nombre="Rota", configuracion="{no es json"
        )
    assert fuentes_db.listar_fuentes(session) == []


def test_una_busqueda_valida_queda_activa(session):
    assert fuentes_db.agregar_busqueda_linkedin(
        session,
        nombre="Jefaturas Litoral",
        configuracion='{"_actor": "u/linkedin", "title": "jefe", "rows": 50}',
    )
    session.commit()

    fuente = fuentes_db.listar_fuentes(session)[0]
    assert fuente.tipo == "busqueda_linkedin"
    assert fuente.activa
    assert ("busqueda_linkedin" in {f.tipo for f, _ in fuentes_db.conectores_desde_base(session)})


def test_una_busqueda_rota_no_tumba_la_corrida(session):
    """Se guarda válida y después se corrompe a mano: la corrida la saltea."""
    fuentes_db.agregar_busqueda_linkedin(
        session, nombre="Demo", configuracion='{"_actor": "u/x", "rows": 1}'
    )
    session.commit()
    fuente = fuentes_db.listar_fuentes(session)[0]
    fuente.identificador = "{roto"
    session.flush()

    pares = fuentes_db.conectores_desde_base(session)
    assert pares == []
    assert fuente.ultimo_error


# --- Fecha aproximada en la vacante ------------------------------------------


def test_la_vacante_guarda_que_la_fecha_es_aproximada(session):
    from talanton.services import upsert_empresa, upsert_vacante

    empresa = upsert_empresa(session, "Demo SA", dominio="demo.com")
    vacante, _ = upsert_vacante(
        session, empresa,
        titulo="Jefe", fuente="linkedin", external_id="1",
        fecha_publicacion=date(2026, 5, 1), fecha_aproximada=True,
    )
    session.commit()
    assert vacante.fecha_aproximada


def test_la_pantalla_marca_los_dias_aproximados(cliente, session_con_demo):
    from talanton.models import Vacante

    vacante = session_con_demo.query(Vacante).filter_by(cerrada=False).first()
    vacante.fecha_aproximada = True
    session_con_demo.commit()

    html = cliente.get("/avisos").text
    assert f"~{vacante.dias_abierta} días" in html

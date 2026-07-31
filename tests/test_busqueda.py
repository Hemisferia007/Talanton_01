"""Búsqueda de empresas por segmento. Cero red: los portales son falsos.

Lo que se protege acá es lo que hace útil al producto: que no entre competencia,
que no entren avisos que nunca se cierran, y sobre todo que buscar dos veces la
misma empresa no pise el histórico —los días abiertos son *el* activo—.
"""

from datetime import timedelta

import pytest

from talanton import busqueda, services
from talanton.ingest.base import VacanteCruda
from talanton.ingest.portales import Segmento


class PortalFalso:
    """Devuelve lo que se le pase. Igual que el cliente falso de Apify."""

    def __init__(self, nombre, crudas, explota=False):
        self.nombre = nombre
        self._crudas = crudas
        self._explota = explota
        self.llamadas = 0

    def buscar(self, segmento):
        self.llamadas += 1
        if self._explota:
            raise RuntimeError("el portal no respondió")
        return list(self._crudas)


def aviso(empresa, titulo, *, dias=30, portal="portal-falso", ident=None, **extra):
    return VacanteCruda(
        empresa=empresa,
        titulo=titulo,
        fuente=portal,
        external_id=ident or f"{empresa}-{titulo}".lower().replace(" ", "-"),
        fuente_url=f"https://ejemplo.test/{(ident or titulo).lower().replace(' ', '-')}",
        ubicacion="Rosario, Santa Fe",
        pais="AR",
        fecha_publicacion=services.fecha_hoy() - timedelta(days=dias),
        **extra,
    )


# --- Exploración -------------------------------------------------------------


def test_explorar_no_toca_la_base(session):
    portal = PortalFalso("uno", [aviso("Metalúrgica Paraná", "Jefe de Producción")])

    exploracion = busqueda.explorar(session, Segmento(), portales=[portal])

    assert len(exploracion.hallazgos) == 1
    assert exploracion.hallazgos[0].empresa == "Metalúrgica Paraná"
    # Explorar es mirar, no guardar: la decisión es del usuario.
    assert services.metricas(session)["empresas"] == 0


def test_una_consultora_no_entra_como_lead(session):
    """Es competencia, no cliente. Es literalmente el pedido del usuario."""
    portal = PortalFalso(
        "uno",
        [
            aviso("Randstad Argentina", "Analista de Compras"),
            aviso("Metalúrgica Paraná", "Jefe de Producción"),
        ],
    )

    exploracion = busqueda.explorar(session, Segmento(), portales=[portal])

    assert [h.empresa for h in exploracion.hallazgos] == ["Metalúrgica Paraná"]
    assert exploracion.descartes[busqueda.DESCARTE_COMPETENCIA] == 1


def test_un_aviso_perenne_no_entra(session):
    """«Postulación espontánea» no se cierra nunca: acumularía días para siempre
    y encabezaría el ranking sin ser una búsqueda real."""
    portal = PortalFalso(
        "uno",
        [
            aviso("Frigorífico del Litoral", "Postulación espontánea", dias=800),
            aviso("Frigorífico del Litoral", "Supervisor de Planta"),
        ],
    )

    exploracion = busqueda.explorar(session, Segmento(), portales=[portal])

    assert [h.titulo for h in exploracion.hallazgos] == ["Supervisor de Planta"]
    assert exploracion.descartes[busqueda.DESCARTE_PERENNE] == 1


def test_lo_mas_viejo_va_primero(session):
    portal = PortalFalso(
        "uno",
        [
            aviso("Alfa SA", "Comprador", dias=5, ident="a"),
            aviso("Beta SRL", "Jefe de Depósito", dias=92, ident="b"),
            aviso("Gama SA", "Analista de Costos", dias=40, ident="c"),
        ],
    )

    exploracion = busqueda.explorar(session, Segmento(), portales=[portal])

    assert [h.dias_abierto for h in exploracion.hallazgos] == [92, 40, 5]


def test_un_portal_caido_no_frena_a_los_demas(session):
    bueno = PortalFalso("bueno", [aviso("Metalúrgica Paraná", "Jefe de Producción")])
    roto = PortalFalso("roto", [], explota=True)

    exploracion = busqueda.explorar(session, Segmento(), portales=[roto, bueno])

    assert len(exploracion.hallazgos) == 1
    assert exploracion.fallidos and "roto" in exploracion.fallidos[0]


def test_marca_las_empresas_que_ya_estaban(session):
    services.upsert_empresa(session, "Metalúrgica Paraná", pais="AR")
    session.flush()
    portal = PortalFalso("uno", [aviso("Metalurgica Parana SA", "Jefe de Producción")])

    exploracion = busqueda.explorar(session, Segmento(), portales=[portal])

    assert exploracion.hallazgos[0].ya_estaba
    assert exploracion.nuevas == 0


# --- Antigüedad --------------------------------------------------------------


def test_el_minimo_de_dias_lo_aplica_el_portal(session):
    """Y un aviso sin fecha queda afuera: el producto se apoya en poder decir el
    número, y suponerlo sería inventarlo."""
    from talanton.ingest.portales.base import aplicar_antiguedad

    viejo = aviso("Beta SRL", "Jefe de Depósito", dias=92)
    nuevo = aviso("Alfa SA", "Comprador", dias=3)
    sin_fecha = aviso("Gama SA", "Analista")
    sin_fecha.fecha_publicacion = None

    quedan = aplicar_antiguedad([viejo, nuevo, sin_fecha], 45)

    assert quedan == [viejo]


def test_sin_minimo_no_se_filtra_nada():
    from talanton.ingest.portales.base import aplicar_antiguedad

    sin_fecha = aviso("Gama SA", "Analista")
    sin_fecha.fecha_publicacion = None
    assert aplicar_antiguedad([sin_fecha], 0) == [sin_fecha]


# --- Traer -------------------------------------------------------------------


def test_traer_crea_empresa_vacante_y_lead_puntuado(session):
    portal = PortalFalso("uno", [aviso("Metalúrgica Paraná", "Jefe de Producción", dias=60)])
    exploracion = busqueda.explorar(session, Segmento(), portales=[portal])

    traida = busqueda.traer(session, exploracion.hallazgos)

    assert traida.empresas_nuevas == 1
    assert traida.vacantes_nuevas == 1
    lead = traida.leads[0]
    assert lead.empresa.nombre == "Metalúrgica Paraná"
    assert lead.score > 0
    # El gancho es lo que después va al mail: si no sale acá, el lead no sirve.
    assert lead.gancho


def test_traer_dos_veces_no_duplica_ni_pisa_el_historico(session):
    """La invariante del producto. `primera_vez_vista` es lo que permite decir
    «hace 92 días que buscan», y es lo único que no se puede improvisar."""
    portal = PortalFalso("uno", [aviso("Metalúrgica Paraná", "Jefe de Producción", dias=60)])

    primera = busqueda.traer(
        session, busqueda.explorar(session, Segmento(), portales=[portal]).hallazgos
    )
    vista_original = primera.leads[0].empresa.vacantes[0].primera_vez_vista

    segunda = busqueda.traer(
        session, busqueda.explorar(session, Segmento(), portales=[portal]).hallazgos
    )

    assert segunda.empresas_nuevas == 0
    assert segunda.empresas_actualizadas == 1
    assert segunda.vacantes_nuevas == 0
    assert segunda.vacantes_repetidas == 1
    assert services.metricas(session)["empresas"] == 1
    assert segunda.leads[0].empresa.vacantes[0].primera_vez_vista == vista_original


def test_los_leads_vuelven_de_mayor_a_menor_score(session):
    portal = PortalFalso(
        "uno",
        [
            aviso("Alfa SA", "Comprador", dias=2, ident="a"),
            aviso("Beta SRL", "Gerente de Operaciones", dias=120, ident="b"),
        ],
    )
    exploracion = busqueda.explorar(session, Segmento(), portales=[portal])

    traida = busqueda.traer(session, exploracion.hallazgos)

    scores = [lead.score for lead in traida.leads]
    assert scores == sorted(scores, reverse=True)


# --- Ida y vuelta por el formulario ------------------------------------------


def test_el_payload_sobrevive_al_formulario(session):
    portal = PortalFalso("uno", [aviso("Metalúrgica Paraná", "Jefe de Producción", dias=60)])
    original = busqueda.explorar(session, Segmento(), portales=[portal]).hallazgos[0]

    rehecho = busqueda.hallazgo_desde_payload(original.payload)

    assert rehecho is not None
    assert rehecho.empresa == original.empresa
    assert rehecho.titulo == original.titulo
    assert rehecho.dias_abierto == original.dias_abierto
    assert rehecho.cruda.external_id == original.cruda.external_id


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"e": "Alfa SA"},
        {"e": "Alfa SA", "t": "Comprador"},
        {"e": "", "t": "Comprador", "f": "uno", "i": "x"},
    ],
)
def test_un_payload_incompleto_no_guarda_nada(payload):
    assert busqueda.hallazgo_desde_payload(payload) is None


def test_no_se_puede_colar_una_consultora_por_el_formulario():
    """El payload viene del navegador: se vuelve a filtrar del lado del servidor."""
    colado = {
        "e": "Randstad Argentina",
        "t": "Analista de Compras",
        "f": "uno",
        "i": "x",
    }
    assert busqueda.hallazgo_desde_payload(colado) is None


# --- La pantalla -------------------------------------------------------------


def test_la_pantalla_ofrece_zonas_y_rubros_cerrados(cliente):
    """Nada de texto libre. Con Apollo ya aprendimos que escribir «Logística» a
    mano no matchea nada y la conclusión equivocada es que no hay empresas."""
    html = cliente.get("/buscar").text

    assert "Buscar empresas" in html
    assert 'name="zona"' in html and 'name="rubro"' in html
    assert "Córdoba" in html and "Logística y transporte" in html
    # El tramo de dotación sale del ICP, no se vuelve a preguntar.
    assert 'name="dotacion' not in html


def test_buscar_muestra_lo_encontrado_sin_guardarlo(cliente, monkeypatch):
    from talanton.ingest.portales.base import Resultado

    def portales_falsos(segmento, portales=None):
        return Resultado(
            crudas=[aviso("Metalúrgica Paraná", "Jefe de Producción", dias=92)],
            por_portal={"computrabajo": 1},
        )

    monkeypatch.setattr(busqueda, "buscar_en_portales", portales_falsos)

    html = cliente.post(
        "/buscar", data={"zona": "santa-fe", "rubro": "produccion", "dias_minimos": "45"}
    ).text

    assert "Metalúrgica Paraná" in html
    assert "92 días" in html
    assert "Traer como leads" in html


def test_traer_sin_tildar_nada_lo_dice(cliente):
    html = cliente.post("/buscar/traer", data={}).text

    assert "No tildaste ningún aviso" in html


def test_traer_desde_la_pantalla_deja_el_lead_creado(cliente, monkeypatch):
    import json

    from talanton.ingest.portales.base import Resultado

    monkeypatch.setattr(
        busqueda,
        "buscar_en_portales",
        lambda segmento, portales=None: Resultado(
            crudas=[aviso("Metalúrgica Paraná", "Jefe de Producción", dias=92)]
        ),
    )
    cliente.post("/buscar", data={"zona": "santa-fe"})

    payload = {
        "e": "Metalúrgica Paraná",
        "t": "Jefe de Producción",
        "f": "portal-falso",
        "i": "metalurgica-parana-jefe-de-produccion",
        "u": "https://ejemplo.test/jefe",
        "l": "Rosario, Santa Fe",
        "d": str(services.fecha_hoy() - timedelta(days=92)),
        "a": False,
    }
    html = cliente.post("/buscar/traer", data={"elegido": json.dumps(payload)}).text

    assert "Guardado" in html
    assert "Metalúrgica Paraná" in html
    # Y quedó de verdad en la base, no sólo en la pantalla.
    assert "Metalúrgica Paraná" in cliente.get("/leads").text

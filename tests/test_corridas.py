"""Tests del registro de corridas.

Lo que importa acá: que una corrida que no trae nada se vea distinta de un día
tranquilo. Enterarse dos meses después de que no se estaba juntando histórico
es el peor escenario, porque el histórico no se puede reconstruir.
"""

from datetime import timedelta

import pytest

from talanton import services
from talanton.ingest.base import VacanteCruda
from talanton.ingest.runner import correr
from talanton.models import CorridaIngesta, ahora


class ConectorFalso:
    def __init__(self, nombre="falso", crudas=None, falla=None):
        self.nombre = nombre
        self.board = "prueba"
        self._crudas = crudas or []
        self._falla = falla

    def fetch(self):
        if self._falla:
            raise RuntimeError(self._falla)
        return self._crudas


def _cruda(external_id="1"):
    return VacanteCruda(
        empresa="Andes SA",
        empresa_dominio="andes.com.ar",
        titulo="Jefe de Depósito",
        fuente="falso",
        external_id=external_id,
        pais="AR",
    )


def test_una_corrida_exitosa_queda_registrada(session):
    correr(session, [ConectorFalso(crudas=[_cruda("1"), _cruda("2")])])

    corrida = services.ultima_corrida(session)
    assert corrida is not None
    assert corrida.terminada_en is not None
    assert corrida.avisos_encontrados == 2
    assert corrida.avisos_nuevos == 2
    assert corrida.fuentes_ok == 1
    assert not corrida.hubo_problemas


def test_una_corrida_vacia_se_marca_como_problema(session):
    """Cero avisos casi siempre es configuración rota, no un día tranquilo."""
    correr(session, [ConectorFalso(crudas=[])])

    corrida = services.ultima_corrida(session)
    assert corrida.sin_resultados
    assert corrida.hubo_problemas


def test_una_fuente_caida_no_frena_la_corrida(session):
    correr(session, [
        ConectorFalso(nombre="rota", falla="502 del portal"),
        ConectorFalso(nombre="sana", crudas=[_cruda("3")]),
    ])

    corrida = services.ultima_corrida(session)
    assert corrida.fuentes_ok == 1
    assert corrida.fuentes_con_error == 1
    assert corrida.avisos_encontrados == 1
    assert any("502 del portal" in l for l in corrida.lineas_detalle)


def test_sin_fuentes_configuradas_lo_dice(session):
    """'No corrió' y 'corrió sin fuentes' tienen que poder distinguirse."""
    correr(session, [])

    corrida = services.ultima_corrida(session)
    assert corrida is not None
    assert any("fuentes.json" in l for l in corrida.lineas_detalle)


# --- Estado que ve el panel --------------------------------------------------


def test_sin_corridas_el_estado_es_nunca(session):
    assert services.estado_ingesta(session)["estado"] == "nunca"


def test_una_corrida_con_datos_da_estado_ok(session):
    correr(session, [ConectorFalso(crudas=[_cruda()])])
    assert services.estado_ingesta(session)["estado"] == "ok"


def test_una_corrida_vacia_da_estado_vacia(session):
    correr(session, [ConectorFalso(crudas=[])])
    estado = services.estado_ingesta(session)
    assert estado["estado"] == "vacia"
    assert "no encontró" in estado["mensaje"]


def test_todas_las_fuentes_rotas_da_estado_error(session):
    correr(session, [ConectorFalso(falla="timeout")])
    assert services.estado_ingesta(session)["estado"] == "error"


def test_una_fuente_rota_de_varias_da_estado_parcial(session):
    correr(session, [
        ConectorFalso(nombre="rota", falla="timeout"),
        ConectorFalso(nombre="sana", crudas=[_cruda()]),
    ])
    assert services.estado_ingesta(session)["estado"] == "parcial"


def test_una_corrida_vieja_se_marca_atrasada(session):
    """Si el cron dejó de dispararse, hay que verlo en el panel."""
    correr(session, [ConectorFalso(crudas=[_cruda()])])
    corrida = services.ultima_corrida(session)
    corrida.iniciada_en = ahora() - timedelta(days=3)
    corrida.terminada_en = ahora() - timedelta(days=3)
    session.commit()

    assert services.estado_ingesta(session)["estado"] == "atrasada"


def test_el_panel_avisa_cuando_la_ingesta_no_trae_nada(cliente, session_con_demo):
    correr(session_con_demo, [ConectorFalso(crudas=[])])
    html = cliente.get("/").text
    assert "no encontró ningún aviso" in html
    # Manda a la pantalla, no al archivo: las fuentes viven en la base y
    # `fuentes.json` se reparte vacío.
    assert 'href="/fuentes"' in html


def test_el_panel_no_molesta_cuando_todo_anda(cliente, session_con_demo):
    correr(session_con_demo, [ConectorFalso(crudas=[_cruda()])])
    html = cliente.get("/").text
    assert "no encontró ningún aviso" not in html

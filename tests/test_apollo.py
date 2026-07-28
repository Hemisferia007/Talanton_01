"""Tests de la búsqueda en Apollo. No se toca la red: el cliente se inyecta.

Lo que más importa acá es la separación de costos: buscar no puede destapar
emails ni consumir créditos, e importar sólo puede gastar por los contactos que
el usuario marcó.
"""

import json

import pytest
from sqlalchemy import select

from talanton.apollo import busqueda
from talanton.apollo.cliente import Persona, tramos_para
from talanton.models import Contacto, Empresa, EstadoLead, Lead


def _persona(**kw) -> Persona:
    base = dict(
        apollo_id="ap-1",
        nombre="Marina Quiroga",
        cargo="Gerenta de Recursos Humanos",
        email="email_not_unlocked@andeslogistica.com.ar",
        empresa="Andes Logística",
        dominio="andeslogistica.com.ar",
        industria="Logística",
        dotacion=180,
        ciudad="Mendoza",
        pais="Argentina",
    )
    base.update(kw)
    return Persona(**base)


class ApolloFalso:
    """Registra lo que se le pidió y devuelve lo programado."""

    def __init__(self, personas=None, email_revelado="marina@andeslogistica.com.ar"):
        self.personas = personas or []
        self.email_revelado = email_revelado
        self.busquedas: list[dict] = []
        self.revelados: list[str] = []

    def buscar_personas(self, **kw):
        from talanton.apollo.cliente import Resultado

        self.busquedas.append(kw)
        return Resultado(personas=list(self.personas), total=len(self.personas))

    def revelar_email(self, persona):
        self.revelados.append(persona.apollo_id)
        persona.email = self.email_revelado
        return persona


# --- Tramos de dotación ------------------------------------------------------


def test_los_tramos_se_solapan_con_el_rango_pedido():
    """Con 20-300 empleados, el tramo 11-20 también tiene empresas que sirven."""
    tramos = tramos_para(20, 300)
    assert "11,20" in tramos
    assert "201,500" in tramos
    assert "501,1000" not in tramos
    assert "1,10" not in tramos


def test_sin_rango_no_se_filtra_por_tamano():
    assert tramos_para(None, None) == []


def test_rango_abierto_por_arriba():
    assert "10001," in tramos_para(5000, None)


# --- Email tapado ------------------------------------------------------------


def test_un_email_tapado_no_cuenta_como_email():
    assert _persona().email_visible is False
    assert _persona(email="marina@andeslogistica.com.ar").email_visible is True


# --- Búsqueda ----------------------------------------------------------------


def test_buscar_traduce_el_pais_y_no_revela_nada(session):
    falso = ApolloFalso([_persona()])
    filtros = busqueda.Filtros(cargos=["Gerente de RRHH"], pais="AR", dotacion_min=20,
                               dotacion_max=300)
    busqueda.buscar(session, filtros, cliente=falso)

    pedido = falso.busquedas[0]
    # La base guarda «AR»; Apollo espera el nombre del país en inglés.
    assert pedido["paises"] == ["Argentina"]
    assert (pedido["dotacion_min"], pedido["dotacion_max"]) == (20, 300)
    assert falso.revelados == [], "buscar no puede gastar créditos"


def test_buscar_manda_los_cargos_sin_vacios(session):
    falso = ApolloFalso()
    busqueda.buscar(
        session, busqueda.Filtros(cargos=["Gerente de RRHH", "  ", ""]), cliente=falso
    )
    assert falso.busquedas[0]["cargos"] == ["Gerente de RRHH"]


# --- Importación -------------------------------------------------------------


def test_importar_revela_y_deja_el_lead_listo(session):
    falso = ApolloFalso([_persona()])
    resultado = busqueda.importar_personas(session, [_persona()], cliente=falso)

    assert falso.revelados == ["ap-1"]
    assert resultado.revelados == 1
    assert resultado.importacion.empresas_nuevas == 1

    empresa = session.scalar(select(Empresa).where(Empresa.nombre == "Andes Logística"))
    assert empresa.dominio == "andeslogistica.com.ar"
    assert empresa.dotacion_estimada == 180

    contacto = session.scalar(select(Contacto))
    assert contacto.email == "marina@andeslogistica.com.ar"
    assert contacto.es_decisor is True
    # Procedencia: sin esto un dato de contacto de un tercero no se puede defender.
    assert "apollo" in (contacto.fuente_url or "")

    lead = session.scalar(select(Lead))
    assert lead.estado == EstadoLead.NUEVO


def test_sin_revelar_no_se_gastan_creditos(session):
    falso = ApolloFalso([_persona()])
    resultado = busqueda.importar_personas(
        session, [_persona()], revelar=False, cliente=falso
    )

    assert falso.revelados == []
    assert resultado.revelados == 0
    assert resultado.sin_email == 1
    # La empresa y el nombre entran igual: sirven aunque falte el mail.
    assert session.scalar(select(Empresa)) is not None
    assert session.scalar(select(Contacto)).email is None


def test_un_email_ya_visible_no_se_vuelve_a_pagar(session):
    falso = ApolloFalso()
    busqueda.importar_personas(
        session, [_persona(email="marina@andeslogistica.com.ar")], cliente=falso
    )
    assert falso.revelados == []


def test_una_persona_sin_empresa_se_descarta(session):
    """El producto es la empresa: una persona suelta no es un lead."""
    falso = ApolloFalso()
    resultado = busqueda.importar_personas(session, [_persona(empresa="")], cliente=falso)

    assert resultado.importacion.total == 0
    assert resultado.fallidos and "empresa" in resultado.fallidos[0]
    assert session.scalar(select(Empresa)) is None


def test_un_revelado_que_falla_no_frena_al_resto(session):
    from talanton.apollo.cliente import ErrorApollo

    class Rota(ApolloFalso):
        def revelar_email(self, persona):
            if persona.apollo_id == "ap-1":
                raise ErrorApollo("se acabaron los créditos")
            return super().revelar_email(persona)

    falso = Rota()
    personas = [_persona(), _persona(apollo_id="ap-2", nombre="Sergio Almada",
                                     empresa="Cerámica Litoral",
                                     dominio="ceramicalitoral.com.ar")]
    resultado = busqueda.importar_personas(session, personas, cliente=falso)

    assert resultado.revelados == 1
    assert len(resultado.fallidos) == 1
    # Las dos empresas entran igual; la primera queda sin mail.
    assert resultado.importacion.total == 2


def test_importar_dos_veces_no_duplica_la_empresa(session):
    falso = ApolloFalso()
    busqueda.importar_personas(session, [_persona()], cliente=falso)
    segundo = busqueda.importar_personas(session, [_persona()], cliente=falso)

    assert segundo.importacion.empresas_existentes == 1
    assert len(session.scalars(select(Empresa)).all()) == 1


# --- Filtros desde el ICP ----------------------------------------------------


def test_los_filtros_arrancan_del_icp_cargado(session):
    from talanton.services import perfil

    p = perfil(session)
    p.industrias_objetivo = "Logística, Manufactura"
    p.dotacion_min = 30
    p.dotacion_max = 400
    session.flush()

    filtros = busqueda.filtros_iniciales(session)
    assert filtros.industrias == ["Logística", "Manufactura"]
    assert (filtros.dotacion_min, filtros.dotacion_max) == (30, 400)
    assert filtros.cargos == busqueda.CARGOS_POR_DEFECTO


# --- Web ---------------------------------------------------------------------


@pytest.fixture()
def apollo_prendido(monkeypatch):
    from talanton import config
    from talanton.apollo import cliente as mod
    from talanton.web import app as _

    monkeypatch.setattr(mod, "APOLLO_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(config, "APOLLO_API_KEY", "clave-de-prueba")
    return mod


def test_la_pantalla_avisa_si_falta_la_clave(cliente):
    r = cliente.get("/buscar")
    assert r.status_code == 200
    assert "TALANTON_APOLLO_API_KEY" in r.text


def test_la_busqueda_muestra_los_resultados(cliente, apollo_prendido, monkeypatch):
    falso = ApolloFalso([_persona()])
    monkeypatch.setattr(busqueda, "Cliente", lambda *a, **k: falso)

    r = cliente.post("/buscar", data={"cargos": "Gerente de RRHH", "pais": "AR"})
    assert r.status_code == 200
    assert "Marina Quiroga" in r.text
    assert "Andes Logística" in r.text
    # El email tapado se marca como tal, no se muestra como si fuera usable.
    assert "Tapado" in r.text
    assert ">email_not_unlocked" not in r.text

    # La fila viaja en el formulario como JSON. Tiene que sobrevivir el
    # round-trip: con comillas dobles en el atributo se corta en la primera.
    import re

    valores = re.findall(r"name=\"persona\"[^>]*value='([^']*)'", r.text)
    assert valores, "la fila no quedó embebida en el formulario"
    assert json.loads(valores[0])["nombre"] == "Marina Quiroga"


def test_el_error_de_apollo_se_muestra_en_pantalla(cliente, apollo_prendido, monkeypatch):
    from talanton.apollo.cliente import ErrorApollo

    def revienta(*a, **k):
        raise ErrorApollo("Apollo rechazó la clave")

    monkeypatch.setattr(busqueda, "buscar", revienta)
    r = cliente.post("/buscar", data={"cargos": "x", "pais": "AR"})
    assert r.status_code == 200
    assert "Apollo rechazó la clave" in r.text


def test_importar_sin_seleccion_avisa(cliente, apollo_prendido):
    r = cliente.post("/buscar/importar", data={"pais": "AR"})
    assert r.status_code == 200
    assert "No seleccionaste" in r.text


def test_importar_desde_la_pantalla(cliente, apollo_prendido, monkeypatch):
    falso = ApolloFalso()
    monkeypatch.setattr(busqueda, "Cliente", lambda *a, **k: falso)

    # Una empresa que no está en los datos de demo, para poder afirmar "nueva".
    persona = _persona(
        apollo_id="ap-9",
        nombre="Sergio Almada",
        empresa="Metalúrgica Paraná",
        dominio="metalurgicaparana.com.ar",
    )
    r = cliente.post(
        "/buscar/importar",
        data={"pais": "AR", "revelar": "1", "persona": json.dumps(persona.__dict__)},
    )
    assert r.status_code == 200
    assert "1 empresa nueva" in r.text
    assert "1 contacto cargado" in r.text
    assert falso.revelados == ["ap-9"]


def test_las_rutas_de_apollo_exigen_sesion(cliente_anonimo):
    for ruta in ("/buscar", "/buscar/importar"):
        r = cliente_anonimo.post(ruta, follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers["location"]

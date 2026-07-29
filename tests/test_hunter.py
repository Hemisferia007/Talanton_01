"""Tests de la búsqueda de contactos. No se toca la red: el cliente se inyecta.

Lo que más importa acá es no gastar búsquedas al pedo: el plan gratuito de
Hunter trae 25 por mes, y re-consultar empresas ya resueltas las quema en una
tarde.
"""

import pytest
from sqlalchemy import select

from talanton.enriquecer import contactos_hunter
from talanton.enriquecer.hunter import CONFIANZA_MINIMA, ErrorHunter, Hallazgo, Resultado
from talanton.models import Contacto, Empresa
from talanton.services import asegurar_lead, recalcular_lead


class HunterFalso:
    """Devuelve lo programado y registra qué dominios se consultaron."""

    def __init__(self, por_dominio=None, error=None):
        self.por_dominio = por_dominio or {}
        self.error = error
        self.consultados: list[str] = []

    def buscar_dominio(self, dominio, *, limite=10):
        self.consultados.append(dominio)
        if self.error:
            raise self.error
        return Resultado(dominio=dominio, hallazgos=list(self.por_dominio.get(dominio, [])))


def _empresa(session, nombre="Baufest", dominio="baufest.com"):
    from talanton.normalize import normalizar_nombre_empresa

    e = Empresa(
        nombre=nombre,
        nombre_normalizado=normalizar_nombre_empresa(nombre),
        dominio=dominio,
        pais="AR",
        dotacion_estimada=300,
    )
    session.add(e)
    session.flush()
    lead = asegurar_lead(session, e)
    recalcular_lead(session, lead)
    session.commit()
    return e


PERSONA = Hallazgo(
    email="mfernandez@baufest.com",
    nombre="Marcela Fernández",
    cargo="Gerenta de Recursos Humanos",
    departamento="hr",
    confianza=94,
    fuente_url="https://baufest.com/nosotros",
)
BUZON = Hallazgo(email="rrhh@baufest.com", cargo=None, departamento="hr", confianza=88)


# --- Persona contra buzón ----------------------------------------------------


def test_un_buzon_de_area_no_es_una_persona():
    assert BUZON.es_de_area is True
    assert PERSONA.es_de_area is False


def test_un_mail_con_nombre_pero_local_de_area_sigue_siendo_buzon():
    """«empleos@» con nombre cargado sigue sin ser alguien a quien saludar."""
    h = Hallazgo(email="empleos@baufest.com", nombre="Equipo Baufest", confianza=90)
    assert h.es_de_area is True


def test_las_personas_van_antes_que_los_buzones():
    r = Resultado(dominio="baufest.com", hallazgos=[BUZON, PERSONA])
    r.hallazgos.sort(key=lambda h: (h.es_de_area, -h.confianza))
    assert r.hallazgos[0] is PERSONA


# --- Guardado ----------------------------------------------------------------


def test_guarda_el_contacto_con_su_procedencia(session):
    empresa = _empresa(session)
    falso = HunterFalso({"baufest.com": [PERSONA]})

    nuevos, marco = contactos_hunter.buscar_una(session, empresa, cliente=falso)
    session.commit()

    assert nuevos == 1
    contacto = session.scalar(select(Contacto))
    assert contacto.email == "mfernandez@baufest.com"
    assert contacto.nombre == "Marcela Fernández"
    # La procedencia es lo que permite auditar y dar de baja a pedido.
    assert contacto.fuente_url == "https://baufest.com/nosotros"
    assert marco is True and contacto.es_decisor is True


def test_un_buzon_se_guarda_pero_no_como_decisor(session):
    """Sirve para escribir; llamarlo decisor le mentiría al score."""
    empresa = _empresa(session)
    contactos_hunter.buscar_una(session, empresa, cliente=HunterFalso({"baufest.com": [BUZON]}))
    session.commit()

    contacto = session.scalar(select(Contacto))
    assert contacto.email == "rrhh@baufest.com"
    assert contacto.es_decisor is False


def test_no_duplica_un_mail_que_ya_estaba(session):
    empresa = _empresa(session)
    falso = HunterFalso({"baufest.com": [PERSONA]})

    contactos_hunter.buscar_una(session, empresa, cliente=falso)
    session.commit()
    nuevos, _ = contactos_hunter.buscar_una(session, empresa, cliente=falso)
    session.commit()

    assert nuevos == 0
    assert len(session.scalars(select(Contacto)).all()) == 1


def test_encontrar_un_contacto_sube_el_score(session):
    """Accesibilidad es el 20% del score y depende de tener a quién escribirle."""
    empresa = _empresa(session)
    antes = empresa.lead.score

    contactos_hunter.buscar_una(session, empresa, cliente=HunterFalso({"baufest.com": [PERSONA]}))
    session.commit()
    session.refresh(empresa.lead)

    assert empresa.lead.score > antes


# --- No gastar búsquedas al pedo ---------------------------------------------


def test_no_consulta_empresas_que_ya_tienen_mail(session):
    empresa = _empresa(session)
    empresa.contactos.append(Contacto(nombre="Alguien", email="ya@baufest.com"))
    session.commit()

    falso = HunterFalso({"baufest.com": [PERSONA]})
    resumen = contactos_hunter.buscar_faltantes(session, cliente=falso)

    assert falso.consultados == []
    assert resumen.salteadas == 1
    assert resumen.empresas_consultadas == 0


def test_no_consulta_empresas_sin_dominio(session):
    _empresa(session, nombre="Sin Web", dominio=None)
    falso = HunterFalso()

    resumen = contactos_hunter.buscar_faltantes(session, cliente=falso)
    assert falso.consultados == []
    assert resumen.salteadas == 1


def test_respeta_el_tope_de_busquedas(session):
    """El plan gratuito trae 25 al mes: una corrida sobre 45 las quema todas."""
    for i in range(5):
        _empresa(session, nombre=f"Empresa {i}", dominio=f"empresa{i}.com")

    falso = HunterFalso()
    resumen = contactos_hunter.buscar_faltantes(session, limite=2, cliente=falso)

    assert len(falso.consultados) == 2
    assert resumen.empresas_consultadas == 2


def test_va_de_mayor_score_a_menor(session):
    """Si sólo alcanza para diez, que sean los diez que más valen."""
    floja = _empresa(session, nombre="Floja", dominio="floja.com")
    fuerte = _empresa(session, nombre="Fuerte", dominio="fuerte.com")
    fuerte.lead.score = 90
    floja.lead.score = 10
    session.commit()

    falso = HunterFalso()
    contactos_hunter.buscar_faltantes(session, limite=1, cliente=falso)
    assert falso.consultados == ["fuerte.com"]


def test_quedarse_sin_busquedas_corta_la_corrida(session):
    for i in range(3):
        _empresa(session, nombre=f"Empresa {i}", dominio=f"empresa{i}.com")

    falso = HunterFalso(error=ErrorHunter("Se acabaron las búsquedas del mes en Hunter."))
    resumen = contactos_hunter.buscar_faltantes(session, limite=10, cliente=falso)

    # Corta en la primera en vez de intentar las tres y fallar tres veces.
    assert len(falso.consultados) == 1
    assert resumen.error and "acabaron" in resumen.error


def test_una_falla_puntual_no_frena_al_resto(session):
    _empresa(session, nombre="Rota", dominio="rota.com")
    _empresa(session, nombre="Buena", dominio="buena.com")

    class Mixto(HunterFalso):
        def buscar_dominio(self, dominio, *, limite=10):
            self.consultados.append(dominio)
            if dominio == "rota.com":
                raise ErrorHunter("timeout")
            return Resultado(dominio=dominio, hallazgos=[PERSONA])

    falso = Mixto()
    resumen = contactos_hunter.buscar_faltantes(session, limite=10, cliente=falso)

    assert len(falso.consultados) == 2
    assert resumen.contactos_nuevos == 1
    assert any("Rota" in x for x in resumen.sin_resultados)


def test_sin_clave_no_revienta(session, monkeypatch):
    from talanton.enriquecer import hunter as mod

    monkeypatch.setattr(mod, "HUNTER_API_KEY", "")
    resumen = contactos_hunter.buscar_faltantes(session)
    assert resumen.error and "TALANTON_HUNTER_API_KEY" in resumen.error


# --- Confianza ---------------------------------------------------------------


def test_se_descartan_los_mails_de_baja_confianza(session, monkeypatch):
    """Un rebote cuesta reputación de dominio, que es cara de recuperar."""
    import httpx

    from talanton.enriquecer import hunter as mod

    payload = {
        "data": {
            "emails": [
                {"value": "dudoso@baufest.com", "confidence": CONFIANZA_MINIMA - 20,
                 "first_name": "X", "last_name": "Y"},
                {"value": "bueno@baufest.com", "confidence": 95,
                 "first_name": "Ana", "last_name": "Ruiz", "position": "HR Manager"},
            ]
        },
        "meta": {"results": 2},
    }
    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: httpx.Response(200, json=payload, request=httpx.Request("GET", "https://x"))
    )
    cliente = mod.Cliente(api_key="clave-de-prueba")
    resultado = cliente.buscar_dominio("baufest.com")

    assert [h.email for h in resultado.hallazgos] == ["bueno@baufest.com"]


def test_sin_dominio_avisa_en_vez_de_consultar():
    from talanton.enriquecer import hunter as mod

    cliente = mod.Cliente(api_key="clave-de-prueba")
    with pytest.raises(ErrorHunter, match="dominio"):
        cliente.buscar_dominio("")


# --- Web ---------------------------------------------------------------------


@pytest.fixture()
def hunter_prendido(monkeypatch):
    from talanton import config
    from talanton.enriquecer import hunter as mod

    monkeypatch.setattr(mod, "HUNTER_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(config, "HUNTER_API_KEY", "clave-de-prueba")


def test_sin_clave_no_aparece_el_boton(cliente):
    assert "Buscar contactos de RRHH" not in cliente.get("/leads").text


def test_con_clave_aparece_el_boton(cliente, hunter_prendido):
    assert "Buscar contactos de RRHH" in cliente.get("/leads").text


def test_buscar_en_masa_desde_la_web(cliente, session_con_demo, hunter_prendido, monkeypatch):
    falso = HunterFalso()
    monkeypatch.setattr(contactos_hunter, "Cliente", lambda *a, **k: falso)

    r = cliente.post("/contactos/buscar", data={"limite": "3"}, follow_redirects=True)
    assert r.status_code == 200
    assert "contactos nuevos" in r.text


def test_buscar_para_un_lead(cliente, session_con_demo, hunter_prendido, monkeypatch):
    from talanton import services

    lead = services.listar_leads(session_con_demo)[0]
    dominio = lead.empresa.dominio
    falso = HunterFalso({dominio: [PERSONA]} if dominio else {})
    monkeypatch.setattr(contactos_hunter, "Cliente", lambda *a, **k: falso)

    r = cliente.post(f"/leads/{lead.id}/contactos", follow_redirects=True)
    assert r.status_code == 200


def test_las_rutas_exigen_sesion(cliente_anonimo):
    r = cliente_anonimo.post("/contactos/buscar", follow_redirects=False)
    assert r.status_code == 303

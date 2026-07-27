"""Tests del enriquecimiento y del descubridor de fuentes."""

import pytest

from talanton.enriquecer import contactos, decisor
from talanton.enriquecer import servicio as enriquecer
from talanton.ingest.normalizar_slug import candidatos_de_slug
from talanton.services import upsert_empresa, upsert_vacante


# --- Extracción de emails ----------------------------------------------------


def test_extrae_emails_de_un_aviso():
    texto = "Enviar CV a rrhh@andeslogistica.com.ar o a marina.quiroga@andeslogistica.com.ar"
    hallados = contactos.extraer_emails(texto, "https://x.com/aviso")
    assert {h.direccion for h in hallados} == {
        "rrhh@andeslogistica.com.ar",
        "marina.quiroga@andeslogistica.com.ar",
    }
    assert all(h.fuente_url == "https://x.com/aviso" for h in hallados)


def test_descarta_ruido_que_parece_email():
    """Los sitios están llenos de strings con @ que no son contactos."""
    texto = "noreply@empresa.com no-reply@x.com foto@2x.png alguien@example.com"
    assert contactos.extraer_emails(texto) == []


def test_no_repite_el_mismo_email():
    texto = "rrhh@x.com.ar ... escribinos a RRHH@X.COM.AR"
    assert len(contactos.extraer_emails(texto)) == 1


def test_texto_vacio_no_rompe():
    assert contactos.extraer_emails(None) == []
    assert contactos.extraer_emails("") == []


def test_distingue_buzon_de_area_de_persona():
    area = contactos.EmailHallado("rrhh@empresa.com.ar")
    persona = contactos.EmailHallado("marina.quiroga@empresa.com.ar")
    assert area.es_de_area
    assert not persona.es_de_area


def test_deduce_el_nombre_solo_cuando_es_claro():
    """Se le va a escribir al cliente usando ese nombre: mejor None que inventar."""
    assert contactos.EmailHallado("marina.quiroga@x.com").nombre_probable == "Marina Quiroga"
    assert contactos.EmailHallado("mquiroga@x.com").nombre_probable is None
    assert contactos.EmailHallado("rrhh@x.com").nombre_probable is None
    assert contactos.EmailHallado("info@x.com").nombre_probable is None


def test_prefiere_a_la_persona_del_dominio_de_la_empresa():
    emails = [
        contactos.EmailHallado("info@otrositio.com"),
        contactos.EmailHallado("rrhh@empresa.com.ar"),
        contactos.EmailHallado("marina.quiroga@empresa.com.ar"),
    ]
    mejor = contactos.elegir_mejor(emails, "empresa.com.ar")
    assert mejor.direccion == "marina.quiroga@empresa.com.ar"


def test_sin_persona_elige_el_buzon_de_rrhh():
    emails = [
        contactos.EmailHallado("ventas@empresa.com.ar"),
        contactos.EmailHallado("rrhh@empresa.com.ar"),
    ]
    assert contactos.elegir_mejor(emails, "empresa.com.ar").direccion == "rrhh@empresa.com.ar"


def test_elegir_mejor_sin_candidatos():
    assert contactos.elegir_mejor([], "x.com") is None


# --- A quién apuntar ---------------------------------------------------------


@pytest.mark.parametrize(
    "dotacion,cargo_esperado",
    [
        (12, "Dueño"),
        (60, "Gerente de Administración"),
        (250, "Gerente de RRHH"),
        (900, "Talent Acquisition Manager"),
    ],
)
def test_el_objetivo_cambia_con_el_tamano(session, dotacion, cargo_esperado):
    """En una PyME decide el dueño; en una grande, quien lidera selección."""
    empresa = upsert_empresa(session, "Demo SA", dominio="demo.com.ar", dotacion_estimada=dotacion)
    assert decisor.objetivo_para(empresa).cargo_principal == cargo_esperado


def test_sin_dotacion_hay_un_objetivo_igual(session):
    empresa = upsert_empresa(session, "Sin Datos SA", dominio="sindatos.com")
    objetivo = decisor.objetivo_para(empresa)
    assert objetivo.cargos
    assert objetivo.buzones
    assert "Sin dotación" in objetivo.razon


def test_reconoce_un_cargo_de_decisor(session):
    empresa = upsert_empresa(session, "Media SA", dominio="media.com", dotacion_estimada=250)
    assert decisor.es_cargo_decisor("Gerenta de RRHH", empresa)
    assert decisor.es_cargo_decisor("Head of People", empresa)
    assert not decisor.es_cargo_decisor("Analista de Sistemas", empresa)
    assert not decisor.es_cargo_decisor(None, empresa)


# --- Corrida de enriquecimiento ----------------------------------------------


def _empresa_con_aviso(session, descripcion, **kwargs):
    empresa = upsert_empresa(
        session, kwargs.pop("nombre", "Andes SA"),
        dominio=kwargs.pop("dominio", "andes.com.ar"),
        dotacion_estimada=kwargs.pop("dotacion", 150),
    )
    upsert_vacante(
        session, empresa,
        titulo="Jefe de Depósito", fuente="test",
        external_id=kwargs.pop("external_id", "e-1"),
        descripcion=descripcion,
        fuente_url="https://andes.com.ar/empleos/1",
    )
    session.refresh(empresa)
    return empresa


def test_enriquecer_carga_el_contacto_del_aviso(session):
    empresa = _empresa_con_aviso(
        session, "Interesados enviar CV a marina.quiroga@andes.com.ar"
    )
    nuevos, marco = enriquecer.enriquecer_empresa(session, empresa, verificar_dns=False)
    session.commit()

    assert nuevos == 1
    assert marco
    contacto = empresa.contactos[0]
    assert contacto.email == "marina.quiroga@andes.com.ar"
    assert contacto.nombre == "Marina Quiroga"
    assert contacto.es_decisor
    # Trazabilidad: de dónde salió el dato, para poder auditarlo y borrarlo.
    assert contacto.fuente_url


def test_un_buzon_generico_no_se_marca_como_decisor(session):
    """Un buzón de área no decide nada: marcarlo inflaría el score."""
    empresa = _empresa_con_aviso(session, "Postulaciones a rrhh@andes.com.ar")
    nuevos, marco = enriquecer.enriquecer_empresa(session, empresa, verificar_dns=False)
    session.commit()

    assert nuevos == 1
    assert not marco
    contacto = empresa.contactos[0]
    assert not contacto.es_decisor
    # Pero sí queda anotado por quién pedir cuando contesten.
    assert "Gerente de RRHH" in contacto.cargo


def test_no_duplica_contactos_ya_cargados(session):
    empresa = _empresa_con_aviso(session, "CV a marina.quiroga@andes.com.ar")
    enriquecer.enriquecer_empresa(session, empresa, verificar_dns=False)
    session.commit()
    session.refresh(empresa)

    nuevos, _ = enriquecer.enriquecer_empresa(session, empresa, verificar_dns=False)
    assert nuevos == 0
    assert len(empresa.contactos) == 1


def test_un_aviso_sin_email_no_inventa_nada(session):
    empresa = _empresa_con_aviso(session, "Buscamos jefe de depósito con experiencia.")
    nuevos, marco = enriquecer.enriquecer_empresa(session, empresa, verificar_dns=False)
    assert (nuevos, marco) == (0, False)


def test_la_corrida_saltea_empresas_que_ya_tienen_decisor(session_con_demo):
    resumen = enriquecer.correr(session_con_demo, verificar_dns=False)
    # El seed ya carga decisores en varias empresas; esas no se tocan.
    from talanton.models import Empresa

    con_decisor = [
        e for e in session_con_demo.query(Empresa).all()
        if any(c.es_decisor for c in e.contactos)
    ]
    assert resumen.empresas_revisadas < len(con_decisor) + resumen.empresas_revisadas + 1


def test_enriquecer_recalcula_el_score(session):
    """Un decisor identificado sube el eje de accesibilidad."""
    empresa = _empresa_con_aviso(session, "CV a marina.quiroga@andes.com.ar")
    from talanton.services import asegurar_lead, recalcular_lead, perfil

    lead = asegurar_lead(session, empresa)
    recalcular_lead(session, lead, perfil(session))
    antes = lead.score_accesibilidad
    session.commit()

    enriquecer.correr(session, verificar_dns=False)
    session.refresh(lead)
    assert lead.score_accesibilidad > antes


# --- Slugs para el descubridor -----------------------------------------------


def test_el_dominio_manda_para_el_slug():
    slugs = candidatos_de_slug("Andes Logística S.R.L.", "andeslogistica.com.ar")
    assert slugs[0] == "andeslogistica"


def test_sin_dominio_usa_el_nombre_normalizado():
    slugs = candidatos_de_slug("Andes Logística S.R.L.")
    assert "andeslogistica" in slugs


def test_no_repite_candidatos():
    slugs = candidatos_de_slug("Fintecho", "fintecho.com.ar")
    assert len(slugs) == len(set(slugs))


def test_descarta_slugs_demasiado_cortos():
    """Un slug de dos letras pega contra cualquier board ajeno."""
    assert all(len(s) >= 3 for s in candidatos_de_slug("AB", "ab.com"))

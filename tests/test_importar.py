"""Tests del importador.

Es la vía más corta para empezar a trabajar, así que tiene que tragar lo que la
gente realmente pega: exportaciones de Excel, de Apollo, listas armadas a mano
con encabezados en inglés o sin encabezados.
"""

import pytest

from talanton import importar
from talanton.models import Empresa
from talanton.services import listar_leads


CON_ENCABEZADO = """Empresa,Dominio,Contacto,Cargo,Email
Andes Logística,andeslogistica.com.ar,Marina Quiroga,Gerenta de RRHH,mquiroga@andeslogistica.com.ar
Cerámica Litoral,ceramicalitoral.com.ar,Sergio Almada,Director de Planta,salmada@ceramicalitoral.com.ar"""


# --- Análisis ----------------------------------------------------------------


def test_lee_una_lista_con_encabezado():
    r = importar.analizar(CON_ENCABEZADO)
    assert r.total == 2
    assert r.filas[0].empresa == "Andes Logística"
    assert r.filas[0].email == "mquiroga@andeslogistica.com.ar"
    assert r.filas[0].cargo == "Gerenta de RRHH"


def test_lee_encabezados_en_ingles():
    """Una exportación de Apollo o Hunter viene en inglés."""
    r = importar.analizar(
        "Company,Website,Full Name,Job Title,Email Address\n"
        "Fintecho,fintecho.com.ar,Diego Ferrari,COO,diego@fintecho.com.ar"
    )
    assert r.filas[0].empresa == "Fintecho"
    assert r.filas[0].contacto == "Diego Ferrari"
    assert r.filas[0].email == "diego@fintecho.com.ar"


def test_sin_encabezado_asume_el_orden_documentado():
    r = importar.analizar("Andes Logística,andeslogistica.com.ar,Marina Quiroga")
    assert r.filas[0].empresa == "Andes Logística"
    assert r.filas[0].dominio == "andeslogistica.com.ar"
    assert r.filas[0].contacto == "Marina Quiroga"


@pytest.mark.parametrize("sep", [",", ";", "\t"])
def test_acepta_los_separadores_habituales(sep):
    """Excel en español exporta con punto y coma; copiar y pegar da tabulaciones."""
    texto = sep.join(["Empresa", "Dominio"]) + "\n" + sep.join(["Andes", "andes.com.ar"])
    r = importar.analizar(texto)
    assert r.filas[0].empresa == "Andes"
    assert r.filas[0].dominio == "andes.com.ar"


def test_ignora_lineas_en_blanco():
    r = importar.analizar("Empresa,Email\n\nAndes,a@b.com\n\n")
    assert r.total == 1


def test_una_fila_sin_empresa_se_reporta_y_no_frena_el_resto():
    r = importar.analizar("Empresa,Email\n,huerfano@x.com\nAndes,a@andes.com")
    assert r.total == 1
    assert any("sin nombre de empresa" in i for i in r.ignoradas)


def test_un_email_invalido_no_impide_importar_la_empresa():
    r = importar.analizar("Empresa,Email\nAndes,no-es-un-email")
    assert r.total == 1
    assert r.filas[0].email is None
    assert any("no es un email válido" in i for i in r.ignoradas)


def test_sin_columna_de_empresa_avisa_en_vez_de_adivinar():
    r = importar.analizar("Telefono,Notas\n1234,algo")
    assert r.total == 0
    assert any("columna de empresa" in i for i in r.ignoradas)


def test_texto_vacio_no_rompe():
    assert importar.analizar("").total == 0
    assert importar.analizar(None).total == 0


def test_deduce_el_dominio_del_email_si_falta():
    r = importar.analizar("Empresa,Email\nAndes,marina@andeslogistica.com.ar")
    assert r.filas[0].dominio == "andeslogistica.com.ar"


def test_interpreta_la_cantidad_de_empleados():
    r = importar.analizar("Empresa,Empleados\nAndes,140\nOtra,\"1.500\"")
    assert [f.dotacion for f in r.filas] == [140, 1500]


# --- Importación -------------------------------------------------------------


def test_importar_crea_empresas_contactos_y_leads(session):
    r = importar.importar(session, importar.analizar(CON_ENCABEZADO).filas)

    assert r.empresas_nuevas == 2
    assert r.contactos_nuevos == 2
    leads = listar_leads(session)
    assert len(leads) == 2
    assert all(l.empresa.contactos for l in leads)


def test_el_contacto_importado_queda_como_decisor(session):
    """Si alguien se tomó el trabajo de cargarlo, es con quien quiere hablar."""
    importar.importar(session, importar.analizar(CON_ENCABEZADO).filas)
    empresa = session.query(Empresa).filter_by(nombre="Andes Logística").one()
    assert empresa.contactos[0].es_decisor
    assert empresa.contactos[0].nombre == "Marina Quiroga"


def test_importar_dos_veces_no_duplica(session):
    filas = importar.analizar(CON_ENCABEZADO).filas
    importar.importar(session, filas)
    r = importar.importar(session, importar.analizar(CON_ENCABEZADO).filas)

    assert r.empresas_nuevas == 0
    assert r.empresas_existentes == 2
    assert r.contactos_nuevos == 0
    assert len(listar_leads(session)) == 2


def test_no_duplica_una_empresa_que_ya_estaba_por_otra_via(session_con_demo):
    """El seed ya tiene Andes Logística: importarla completa, no duplica."""
    r = importar.importar(
        session_con_demo,
        importar.analizar("Empresa,Email\nAndes Logistica SRL,nueva@andeslogistica.com.ar").filas,
    )
    assert r.empresas_nuevas == 0


def test_las_notas_quedan_como_proximo_paso(session):
    r = importar.importar(
        session,
        importar.analizar("Empresa,Notas\nAndes,Llamar al dueño en marzo").filas,
    )
    lead = listar_leads(session)[0]
    assert lead.proximo_paso == "Llamar al dueño en marzo"


def test_una_empresa_sin_contacto_igual_entra_como_lead(session):
    importar.importar(session, importar.analizar("Empresa\nAndes\nFintecho").filas)
    assert len(listar_leads(session)) == 2


def test_el_lead_importado_tiene_score(session):
    importar.importar(session, importar.analizar(CON_ENCABEZADO).filas)
    lead = listar_leads(session)[0]
    assert lead.score > 0
    assert lead.lista_razones


# --- Pantalla ----------------------------------------------------------------


def test_la_pantalla_responde(cliente):
    r = cliente.get("/importar")
    assert r.status_code == 200
    assert "Importar una lista" in r.text


def test_previsualizar_no_toca_la_base(cliente, session_con_demo):
    antes = len(listar_leads(session_con_demo))
    r = cliente.post("/importar", data={"datos": CON_ENCABEZADO, "accion": "previsualizar"})

    assert r.status_code == 200
    assert "Previsualización" in r.text
    assert "Marina Quiroga" in r.text
    session_con_demo.expire_all()
    assert len(listar_leads(session_con_demo)) == antes


def test_importar_desde_la_web(cliente, session_con_demo):
    r = cliente.post(
        "/importar",
        data={"datos": "Empresa,Email\nNueva Empresa SA,contacto@nuevaempresa.com",
              "accion": "importar", "pais": "AR"},
    )
    assert r.status_code == 200
    session_con_demo.expire_all()
    assert any(l.empresa.nombre == "Nueva Empresa SA" for l in listar_leads(session_con_demo))


def test_datos_ilegibles_muestran_el_error(cliente):
    r = cliente.post("/importar", data={"datos": "Telefono\n1234", "accion": "previsualizar"})
    assert "columna de empresa" in r.text


def test_la_pantalla_esta_protegida(cliente_anonimo):
    r = cliente_anonimo.get("/importar", follow_redirects=False)
    assert r.status_code == 303


# --- Exportación de Apollo ---------------------------------------------------
#
# Es el camino real para quien no tiene la API paga: se exporta desde la web de
# Apollo y se pega acá. Los encabezados son los que pone Apollo tal cual.

CSV_APOLLO = """First Name,Last Name,Title,Company,Email,Email Status,\
Corporate Phone,# Employees,Industry,Person Linkedin Url,Website,City,\
Company City,Company Country
Marina,Quiroga,Gerenta de RRHH,Andes Logística,mquiroga@andeslog.com.ar,verified,\
+54 261 555-0000,180,logistics & supply chain,https://linkedin.com/in/mquiroga,\
http://www.andeslog.com.ar,Godoy Cruz,Mendoza,Argentina"""


def test_el_csv_de_apollo_entra_completo():
    fila = importar.analizar(CSV_APOLLO).filas[0]

    assert fila.empresa == "Andes Logística"
    # Nombre y apellido vienen en columnas separadas y hay que volver a juntarlos:
    # sin esto el saludo del mail sale «Hola Marina,» a secas o directamente mal.
    assert fila.contacto == "Marina Quiroga"
    assert fila.cargo == "Gerenta de RRHH"
    assert fila.email == "mquiroga@andeslog.com.ar"
    assert fila.telefono == "+54 261 555-0000"
    assert fila.industria == "logistics & supply chain"
    assert fila.dominio == "andeslog.com.ar"


def test_el_encabezado_con_puntuacion_igual_se_reconoce():
    """Apollo titula la columna «# Employees»: sin limpiar la puntuación, la
    dotación se perdía en silencio y con ella el eje de capacidad de pago."""
    assert importar.analizar(CSV_APOLLO).filas[0].dotacion == 180


def test_gana_la_ciudad_de_la_empresa_sobre_la_de_la_persona():
    """La persona vive en Godoy Cruz, la empresa está en Mendoza. Importa la
    segunda: el lead es la empresa."""
    assert importar.analizar(CSV_APOLLO).filas[0].ciudad == "Mendoza"


def test_el_linkedin_queda_como_procedencia(session):
    """Un dato de contacto de un tercero sin procedencia no se puede defender."""
    from sqlalchemy import select

    from talanton.models import Contacto

    importar.importar(session, importar.analizar(CSV_APOLLO).filas)
    contacto = session.scalar(select(Contacto))
    assert contacto.fuente_url == "https://linkedin.com/in/mquiroga"


def test_sin_columna_de_linkedin_la_procedencia_sigue_siendo_manual():
    fila = importar.analizar("Empresa,Contacto\nAcme,Juan Pérez").filas[0]
    assert fila.procedencia == "importado a mano"


# --- Vigilancia --------------------------------------------------------------


def test_importar_deja_las_empresas_vigiladas(session):
    """Traer el contacto y no mirar sus avisos deja el trabajo por la mitad:
    la lista dice a quién escribirle, los avisos dicen cuándo."""
    from talanton.ingest import fuentes as fuentes_db

    filas = importar.analizar(
        "Empresa,Dominio\nAndes Logística,andeslog.com.ar\nCerámica Litoral,ceramlitoral.com.ar"
    ).filas
    resultado = importar.importar(session, filas)

    assert resultado.a_vigilar == 2
    objetivos = {o.nombre: o for o in fuentes_db.listar_objetivos(session)}
    assert set(objetivos) == {"Andes Logística", "Cerámica Litoral"}
    # El dominio sube mucho las chances de que el sondeo encuentre el board.
    assert objetivos["Andes Logística"].dominio == "andeslog.com.ar"


def test_se_puede_importar_sin_vigilar(session):
    from talanton.ingest import fuentes as fuentes_db

    filas = importar.analizar("Empresa\nAndes Logística").filas
    resultado = importar.importar(session, filas, vigilar=False)

    assert resultado.a_vigilar == 0
    assert fuentes_db.listar_objetivos(session) == []


def test_importar_dos_veces_no_duplica_el_objetivo(session):
    from talanton.ingest import fuentes as fuentes_db

    filas = importar.analizar("Empresa\nAndes Logística").filas
    importar.importar(session, filas)
    segundo = importar.importar(session, importar.analizar("Empresa\nAndes Logística").filas)

    assert segundo.a_vigilar == 0
    assert len(fuentes_db.listar_objetivos(session)) == 1


def test_la_pantalla_deja_vigilando(cliente, session_con_demo):
    from talanton.ingest import fuentes as fuentes_db

    cliente.post(
        "/importar",
        data={"datos": "Empresa,Dominio\nVigilada SA,vigilada.com.ar",
              "accion": "importar", "pais": "AR", "vigilar": "1"},
    )
    session_con_demo.expire_all()
    assert any(
        o.nombre == "Vigilada SA" for o in fuentes_db.listar_objetivos(session_con_demo)
    )

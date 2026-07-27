from talanton.ingest import jsonld
from talanton.ingest.ats import inferir_pais
from talanton.ingest.base import parsear_fecha
from talanton.ingest.runner import persistir
from talanton.services import listar_vacantes

HTML_CON_JSONLD = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "JobPosting",
  "title": "Jefe de Mantenimiento Industrial",
  "datePosted": "2026-04-02",
  "employmentType": "FULL_TIME",
  "description": "Buscamos jefe de mantenimiento para planta en Paran\\u00e1.",
  "identifier": {"@type": "PropertyValue", "value": "MANT-001"},
  "hiringOrganization": {"@type": "Organization", "name": "Cer\\u00e1mica Litoral"},
  "jobLocation": {
    "@type": "Place",
    "address": {"@type": "PostalAddress", "addressLocality": "Paran\\u00e1", "addressCountry": "Argentina"}
  }
}
</script>
</head><body></body></html>
"""

HTML_CON_GRAFO = """
<html><head>
<script type="application/ld+json">
{"@graph": [
  {"@type": "WebSite", "name": "Portal"},
  {"@type": ["JobPosting"], "title": "Contador Senior",
   "hiringOrganization": "Agroexport Pampa", "datePosted": "2026-05-10"}
]}
</script>
</head></html>
"""


def test_parsea_jobposting_de_jsonld():
    vacantes = jsonld.parsear_html(HTML_CON_JSONLD, "https://ceramicalitoral.com.ar/empleos")
    assert len(vacantes) == 1
    v = vacantes[0]
    assert v.titulo == "Jefe de Mantenimiento Industrial"
    assert v.empresa == "Cerámica Litoral"
    assert v.external_id == "MANT-001"
    assert v.pais == "AR"
    assert v.fecha_publicacion.isoformat() == "2026-04-02"


def test_parsea_jobposting_dentro_de_un_grafo():
    vacantes = jsonld.parsear_html(HTML_CON_GRAFO, "https://agroexportpampa.com/empleos")
    assert [v.titulo for v in vacantes] == ["Contador Senior"]
    assert vacantes[0].empresa == "Agroexport Pampa"


def test_sin_identifier_genera_un_id_estable():
    a = jsonld.parsear_html(HTML_CON_GRAFO, "https://x.com/empleos")[0]
    b = jsonld.parsear_html(HTML_CON_GRAFO, "https://x.com/empleos")[0]
    assert a.external_id == b.external_id


def test_html_sin_jsonld_no_rompe():
    assert jsonld.parsear_html("<html><body>nada</body></html>", "https://x.com") == []


def test_json_invalido_se_ignora():
    html = '<script type="application/ld+json">{roto</script>'
    assert jsonld.parsear_html(html, "https://x.com") == []


def test_inferir_pais():
    assert inferir_pais("Córdoba, Argentina") == "AR"
    assert inferir_pais("Montevideo") == "UY"
    assert inferir_pais("Remoto") is None
    assert inferir_pais(None) is None


def test_parsear_fecha_tolera_formatos():
    assert parsear_fecha("2026-04-02T10:00:00Z").isoformat() == "2026-04-02"
    assert parsear_fecha("02/04/2026").isoformat() == "2026-04-02"
    assert parsear_fecha("cualquier cosa") is None
    assert parsear_fecha(None) is None


def test_persistir_crea_empresa_vacante_y_lead(session):
    crudas = jsonld.parsear_html(HTML_CON_JSONLD, "https://ceramicalitoral.com.ar/empleos")
    resumen = persistir(session, crudas, "jsonld")
    session.commit()

    assert resumen.encontradas == 1
    assert resumen.nuevas == 1

    vacantes = listar_vacantes(session)
    assert len(vacantes) == 1
    lead = vacantes[0].empresa.lead
    assert lead is not None
    assert lead.score > 0
    assert any(a.tipo == "senal" for a in lead.actividades)


def test_segunda_corrida_no_duplica(session):
    crudas = jsonld.parsear_html(HTML_CON_JSONLD, "https://ceramicalitoral.com.ar/empleos")
    persistir(session, crudas, "jsonld")
    session.commit()
    resumen = persistir(session, crudas, "jsonld")
    session.commit()

    assert resumen.nuevas == 0
    assert len(listar_vacantes(session)) == 1

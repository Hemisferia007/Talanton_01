"""Conectores de los portales de empleo. Cero red: se parsea HTML de fixture.

Aclaración importante y honesta: este HTML es **una maqueta con la estructura
documentada de cada portal**, no una captura real. Los tests garantizan que el
mapeo a `VacanteCruda` es correcto y que los descartes funcionan; no garantizan
que los selectores le peguen al HTML que sirve el portal hoy. Eso se verifica la
primera vez que se corre contra el sitio de verdad, igual que pasó con Apify.
"""

import pytest

from talanton.ingest.portales import Segmento
from talanton.ingest.portales.base import Resultado, buscar_en_portales

from dom_falso import parsear


HTML_COMPUTRABAJO = """
<div class="box_lista">
  <article class="box_offer" data-id="123">
    <h2><a class="js-o-link" href="/ofertas-de-trabajo/oferta-de-trabajo-de-jefe-de-produccion-123">
      Jefe de Producción</a></h2>
    <a class="it-blank" href="/empresa/metalurgica-parana">Metalúrgica Paraná</a>
    <p class="fs16"><span>Rosario, Santa Fe</span></p>
    <p class="fs13">Hace 3 días</p>
  </article>
  <article class="box_offer" data-id="124">
    <h2><a class="js-o-link" href="/ofertas-de-trabajo/oferta-124">Analista de Compras</a></h2>
    <a class="it-blank" href="/empresa/x">Empresa Confidencial</a>
    <p class="fs16"><span>CABA</span></p>
    <p class="fs13">Hace 1 mes</p>
  </article>
</div>
"""


def test_computrabajo_mapea_los_campos_que_importan(monkeypatch):
    from talanton.ingest.portales import computrabajo

    monkeypatch.setattr(
        computrabajo, "traer_pagina", lambda *a, **k: parsear(HTML_COMPUTRABAJO)
    )

    crudas = computrabajo.Computrabajo().buscar(Segmento(zona="santa-fe"))

    assert len(crudas) == 1, "el aviso confidencial tiene que quedar afuera"
    cruda = crudas[0]
    assert cruda.empresa == "Metalúrgica Paraná"
    assert cruda.titulo == "Jefe de Producción"
    assert cruda.fuente == "computrabajo"
    assert cruda.pais == "AR"
    assert cruda.ubicacion == "Rosario, Santa Fe"
    assert cruda.fecha_publicacion is not None
    # «Hace 3 días» es un dato exacto; «hace 1 mes» no lo sería.
    assert not cruda.fecha_aproximada
    # La URL es el identificador natural y estable entre corridas.
    assert cruda.external_id.startswith("https://ar.computrabajo.com/")


def test_computrabajo_no_pide_navegador(monkeypatch):
    """Sirve HTML del servidor: si pidiera stealth no andaría sin `scrapling
    install`, que es justamente lo que lo hace el portal más confiable."""
    from talanton.ingest.portales import computrabajo

    pedidos = []

    def espia(url, timeout=30, stealth=False):
        pedidos.append(stealth)
        return parsear(HTML_COMPUTRABAJO)

    monkeypatch.setattr(computrabajo, "traer_pagina", espia)
    computrabajo.Computrabajo().buscar(Segmento())

    assert pedidos == [False]


@pytest.mark.parametrize(
    "zona,rubro,esperado",
    [
        ("santa-fe", "produccion", "/trabajo-de-produccion-en-santa-fe"),
        ("todo-el-pais", "logistica", "/trabajo-de-logistica"),
        ("cordoba", None, "/empleos-en-cordoba"),
        ("todo-el-pais", None, "/empleos"),
    ],
)
def test_computrabajo_arma_la_url_del_segmento(zona, rubro, esperado):
    from talanton.ingest.portales.computrabajo import Computrabajo

    url = Computrabajo().url(Segmento(zona=zona, rubro=rubro))

    assert url.endswith(esperado), url


def test_computrabajo_respeta_el_tope(monkeypatch):
    from talanton.ingest.portales import computrabajo

    muchos = HTML_COMPUTRABAJO.replace("</div>", "") + (
        """
    <article class="box_offer">
      <h2><a class="js-o-link" href="/o/%d">Puesto %d</a></h2>
      <a class="it-blank" href="/e/%d">Empresa %d</a>
      <p class="fs13">Hace 2 días</p>
    </article>
    """
        * 8
    ) % tuple(n for i in range(8) for n in (i, i, i, i))
    monkeypatch.setattr(computrabajo, "traer_pagina", lambda *a, **k: parsear(muchos + "</div>"))

    crudas = computrabajo.Computrabajo().buscar(Segmento(tope=3))

    assert len(crudas) <= 3


HTML_BUMERAN = """
<div id="listado-avisos">
  <div>
    <a href="/empleos/supervisor-de-planta-1116.html">
      <h2>Supervisor de Planta</h2>
      <h3></h3>
      <span class="sc-empresa">Frigorífico del Litoral</span>
      <span class="sc-ubicacion">San Nicolás, Buenos Aires</span>
      <span class="sc-fecha">Hace 2 semanas</span>
    </a>
  </div>
</div>
"""


def test_bumeran_mapea_y_marca_la_fecha_como_aproximada(monkeypatch):
    """«Hace 2 semanas» tiene una semana de error, y ese número termina en un
    mail al cliente: se guarda marcado para que en pantalla se vea con `~`."""
    from talanton.ingest.portales import bumeran

    monkeypatch.setattr(bumeran, "traer_pagina", lambda *a, **k: parsear(HTML_BUMERAN))

    crudas = bumeran.Bumeran().buscar(Segmento())

    assert len(crudas) == 1
    cruda = crudas[0]
    assert cruda.empresa == "Frigorífico del Litoral"
    assert cruda.titulo == "Supervisor de Planta"
    assert cruda.fuente == "bumeran"
    assert cruda.fecha_aproximada


def test_bumeran_pide_navegador(monkeypatch):
    """El listado lo arma React: sin navegador el HTML del servidor viene vacío."""
    from talanton.ingest.portales import bumeran

    pedidos = []

    def espia(url, timeout=30, stealth=False):
        pedidos.append(stealth)
        return parsear(HTML_BUMERAN)

    monkeypatch.setattr(bumeran, "traer_pagina", espia)
    bumeran.Bumeran().buscar(Segmento())

    assert pedidos == [True]


def test_zonajobs_es_el_mismo_portal_con_otro_dominio(monkeypatch):
    from talanton.ingest.portales import bumeran

    monkeypatch.setattr(bumeran, "traer_pagina", lambda *a, **k: parsear(HTML_BUMERAN))

    crudas = bumeran.ZonaJobs().buscar(Segmento())

    assert crudas[0].fuente == "zonajobs"
    assert crudas[0].fuente_url.startswith("https://www.zonajobs.com.ar/")


def test_bumeran_no_repite_el_mismo_aviso(monkeypatch):
    """Los selectores del listado se solapan —el contenedor y el link de adentro
    matchean los dos—, así que el mismo aviso puede venir dos veces."""
    from talanton.ingest.portales import bumeran

    monkeypatch.setattr(bumeran, "traer_pagina", lambda *a, **k: parsear(HTML_BUMERAN))

    crudas = bumeran.Bumeran().buscar(Segmento())

    assert len({c.external_id for c in crudas}) == len(crudas)


# --- Orquestación ------------------------------------------------------------


class PortalQueExplota:
    nombre = "roto"

    def buscar(self, segmento):
        raise RuntimeError("403")


class PortalQueAnda:
    nombre = "sano"

    def buscar(self, segmento):
        from talanton.ingest.base import VacanteCruda

        return [VacanteCruda(empresa="Alfa SA", titulo="Comprador", fuente="sano", external_id="a")]


def test_un_portal_caido_se_anota_pero_no_rompe_la_busqueda():
    resultado = buscar_en_portales(Segmento(), [PortalQueExplota(), PortalQueAnda()])

    assert isinstance(resultado, Resultado)
    assert resultado.por_portal == {"sano": 1}
    assert len(resultado.crudas) == 1
    assert resultado.fallidos == ["roto: 403"]

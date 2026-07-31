"""Computrabajo Argentina.

El portal con más volumen de PyME argentina y —lo que más importa acá— el único
de los tres que sirve **HTML del lado del servidor**. Eso significa que anda sin
navegador: alcanza con el fetcher liviano, así que funciona en Railway aunque no
esté instalado el browser de Scrapling.

Por eso va primero en la lista de portales: es el más barato de consultar y el
que más probablemente devuelva algo.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from ..base import VacanteCruda, traer_pagina
from .base import Segmento, aplicar_antiguedad, atributo_de, nodos, texto_de

log = logging.getLogger("talanton.portales")

BASE = "https://ar.computrabajo.com"

# Selectores concentrados acá arriba: cuando el portal cambie el HTML, se
# arregla en una línea en vez de perseguirlo por todo el archivo.
SEL_AVISO = "article.box_offer, article[data-id]"
SEL_TITULO = "h2 a, a.js-o-link"
SEL_EMPRESA = "a.it-blank, p.dFlex a, span.dIB"
SEL_UBICACION = "p.fs16 span, span.mr10"
SEL_ANTIGUEDAD = "p.fs13, span.dO"

# Cómo llamamos nosotros a cada zona → cómo la llama Computrabajo en la URL.
ZONAS = {
    "caba": "capital-federal",
    "gba": "buenos-aires",
    "cordoba": "cordoba",
    "santa-fe": "santa-fe",
    "mendoza": "mendoza",
    "tucuman": "tucuman",
    "neuquen": "neuquen",
    "salta": "salta",
    "entre-rios": "entre-rios",
    "chubut": "chubut",
}

# El rubro se consulta como palabra clave: la taxonomía propia del portal es
# enorme y cambia, y la búsqueda por texto es más estable.
RUBROS = {
    "produccion": "produccion",
    "logistica": "logistica",
    "mantenimiento": "mantenimiento",
    "construccion": "construccion",
    "agro": "agropecuario",
    "comercial": "ventas",
    "retail": "comercio",
    "administracion": "administracion",
    "rrhh": "recursos-humanos",
    "tecnologia": "sistemas",
    "salud": "salud",
    "gastronomia": "gastronomia",
}


class Computrabajo:
    nombre = "computrabajo"

    def url(self, segmento: Segmento) -> str:
        rubro = RUBROS.get(segmento.rubro or "")
        zona = ZONAS.get(segmento.zona)
        if rubro and zona:
            return f"{BASE}/trabajo-de-{rubro}-en-{zona}"
        if rubro:
            return f"{BASE}/trabajo-de-{rubro}"
        if zona:
            return f"{BASE}/empleos-en-{zona}"
        return f"{BASE}/empleos"

    def buscar(self, segmento: Segmento) -> list[VacanteCruda]:
        # `stealth=False`: es HTML del servidor y no hace falta navegador.
        pagina = traer_pagina(self.url(segmento), timeout=25, stealth=False)
        crudas = []
        for nodo in nodos(pagina, SEL_AVISO)[: segmento.tope]:
            cruda = self._mapear(nodo)
            if cruda is not None:
                crudas.append(cruda)
        return aplicar_antiguedad(crudas, segmento.dias_minimos)

    def _mapear(self, nodo) -> VacanteCruda | None:
        titulo = texto_de(nodo, SEL_TITULO)
        empresa = texto_de(nodo, SEL_EMPRESA)
        # Sin empresa el aviso no sirve: el lead es la empresa, no la vacante.
        # Computrabajo publica muchos avisos confidenciales y esos se descartan.
        if not titulo or not empresa or _es_confidencial(empresa):
            return None

        href = atributo_de(nodo, SEL_TITULO, "href")
        url = urljoin(BASE, href) if href else None
        fecha, aproximada = _antiguedad(texto_de(nodo, SEL_ANTIGUEDAD))

        return VacanteCruda(
            empresa=empresa,
            titulo=titulo,
            fuente=self.nombre,
            # La URL del aviso es el identificador natural y estable. Sin ella,
            # empresa + título alcanza para no duplicar entre corridas.
            external_id=_identificador(url, empresa, titulo),
            fuente_url=url,
            ubicacion=texto_de(nodo, SEL_UBICACION),
            pais="AR",
            fecha_publicacion=fecha,
            fecha_aproximada=aproximada,
        )


_CONFIDENCIALES = (
    "confidencial", "empresa importante", "importante empresa",
    "reconocida empresa", "empresa lider", "empresa del rubro",
)


def _es_confidencial(empresa: str) -> bool:
    """Un aviso sin nombre de empresa no es un lead: no hay a quién escribirle."""
    from ...normalize import sin_acentos

    limpio = sin_acentos(empresa).lower()
    return any(marca in limpio for marca in _CONFIDENCIALES)


def _identificador(url: str | None, empresa: str, titulo: str) -> str:
    if url:
        return re.sub(r"[?#].*$", "", url)[:200]
    from ...normalize import normalizar_nombre_empresa, normalizar_rol

    return f"{normalizar_nombre_empresa(empresa)}:{normalizar_rol(titulo)}"[:200]


def _antiguedad(texto: str | None):
    """«Hace 3 días», «Publicado hace 1 mes» → fecha, marcada como aproximada."""
    from ...avisos_manuales import interpretar_antiguedad

    return interpretar_antiguedad(texto)

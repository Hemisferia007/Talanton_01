"""Bumeran y ZonaJobs.

Son el mismo portal por dentro —la misma empresa, la misma plataforma— con dos
marcas y dos públicos: Bumeran tira más a puestos profesionales y ZonaJobs más
a operativos y comerciales. Por eso comparten todo el código salvo el dominio y
un par de slugs.

A diferencia de Computrabajo, arman el listado con JavaScript en el navegador.
El HTML que llega del servidor viene casi vacío, así que hace falta
`stealth=True`, que abre un navegador de verdad. Es más lento y más pesado —y
necesita `scrapling install` en la imagen—, pero es la única forma de ver los
avisos.

Consecuencia práctica: si el navegador no está instalado, estos dos portales
fallan y Computrabajo sigue andando. `buscar_en_portales()` está escrito
justamente para que eso no rompa la búsqueda entera.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from ..base import VacanteCruda, traer_pagina
from .base import Segmento, aplicar_antiguedad, atributo_de, nodos, texto_de

log = logging.getLogger("talanton.portales")

# Selectores juntos y arriba: cuando el portal cambie el DOM se arregla acá.
SEL_AVISO = "div[id^='listado-avisos'] > div"
SEL_TITULO = "h2, h3, [class*='titulo']"
SEL_EMPRESA = "[class*='empresa'], [class*='company']"
SEL_UBICACION = "[class*='ubicacion'], [class*='location']"
SEL_ANTIGUEDAD = "[class*='fecha'], [class*='date'], time"

# Zonas: clave interna -> slug del portal.
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

# Rubros como palabra clave y no como categoría del portal: la taxonomía propia
# de Bumeran tiene identificadores numéricos que cambian, y la búsqueda por
# texto sobrevive mejor a esos cambios.
RUBROS = {
    "produccion": "produccion",
    "logistica": "logistica",
    "mantenimiento": "mantenimiento",
    "construccion": "construccion",
    "agro": "agro",
    "comercial": "ventas",
    "retail": "comercio",
    "administracion": "administracion",
    "rrhh": "recursos-humanos",
    "tecnologia": "sistemas",
    "salud": "salud",
    "gastronomia": "gastronomia",
}


class _PortalJobint:
    """Lo común entre Bumeran y ZonaJobs. No se usa directo."""

    nombre = "jobint"
    base = ""

    def url(self, segmento: Segmento) -> str:
        rubro = RUBROS.get(segmento.rubro or "")
        zona = ZONAS.get(segmento.zona)
        if rubro and zona:
            return f"{self.base}/empleos-busqueda-{rubro}-en-{zona}.html"
        if rubro:
            return f"{self.base}/empleos-busqueda-{rubro}.html"
        if zona:
            return f"{self.base}/empleos-en-{zona}.html"
        return f"{self.base}/empleos.html"

    def buscar(self, segmento: Segmento) -> list[VacanteCruda]:
        # `stealth=True`: el listado lo arma React, el HTML del servidor viene
        # vacío. Sin navegador este portal no devuelve nada.
        pagina = traer_pagina(self.url(segmento), timeout=45, stealth=True)
        crudas = []
        vistos: set[str] = set()
        for nodo in nodos(pagina, SEL_AVISO):
            cruda = self._mapear(nodo)
            # Los selectores del listado se solapan (el contenedor y el link de
            # adentro matchean los dos), así que el mismo aviso puede venir dos
            # veces en la misma página.
            if cruda is None or cruda.external_id in vistos:
                continue
            vistos.add(cruda.external_id)
            crudas.append(cruda)
            if len(crudas) >= segmento.tope:
                break
        return aplicar_antiguedad(crudas, segmento.dias_minimos)

    def _mapear(self, nodo) -> VacanteCruda | None:
        titulo = texto_de(nodo, SEL_TITULO)
        empresa = texto_de(nodo, SEL_EMPRESA)
        # Sin nombre de empresa no hay lead: no hay a quién escribirle. Bumeran
        # publica muchos avisos confidenciales y esos no sirven.
        if not titulo or not empresa or _es_confidencial(empresa):
            return None

        href = atributo_de(nodo, "a", "href") or (
            nodo.attrib.get("href") if hasattr(nodo, "attrib") else None
        )
        url = urljoin(self.base, href) if href else None
        fecha, aproximada = _antiguedad(texto_de(nodo, SEL_ANTIGUEDAD))

        return VacanteCruda(
            empresa=empresa,
            titulo=titulo,
            fuente=self.nombre,
            external_id=_identificador(url, empresa, titulo),
            fuente_url=url,
            ubicacion=texto_de(nodo, SEL_UBICACION),
            pais="AR",
            fecha_publicacion=fecha,
            fecha_aproximada=aproximada,
        )


class Bumeran(_PortalJobint):
    nombre = "bumeran"
    base = "https://www.bumeran.com.ar"


class ZonaJobs(_PortalJobint):
    nombre = "zonajobs"
    base = "https://www.zonajobs.com.ar"


_CONFIDENCIALES = (
    "confidencial",
    "empresa importante",
    "importante empresa",
    "reconocida empresa",
    "empresa lider",
    "empresa del rubro",
    "empresa de primera linea",
)


def _es_confidencial(empresa: str) -> bool:
    from ...normalize import sin_acentos

    limpio = sin_acentos(empresa).lower()
    return any(marca in limpio for marca in _CONFIDENCIALES)


def _identificador(url: str | None, empresa: str, titulo: str) -> str:
    if url:
        return re.sub(r"[?#].*$", "", url)[:200]
    from ...normalize import normalizar_nombre_empresa, normalizar_rol

    return f"{normalizar_nombre_empresa(empresa)}:{normalizar_rol(titulo)}"[:200]


def _antiguedad(texto: str | None):
    from ...avisos_manuales import interpretar_antiguedad

    return interpretar_antiguedad(texto)

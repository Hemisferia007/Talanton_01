"""Parser de `schema.org/JobPosting` embebido en páginas de carrera.

El segundo carril más barato: la mayoría de los sitios corporativos ya publican
sus avisos con JSON-LD porque es lo que consume Google Jobs. Un solo parser
sirve para cientos de sitios distintos, sin selectores que mantener.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from .ats import inferir_pais
from .base import VacanteCruda, parsear_fecha, traer_pagina

NOMBRE = "jsonld"


def _aplanar(nodo: Any) -> Iterable[dict]:
    """Recorre grafos anidados (@graph, listas) buscando nodos JobPosting."""
    if isinstance(nodo, list):
        for item in nodo:
            yield from _aplanar(item)
    elif isinstance(nodo, dict):
        if "@graph" in nodo:
            yield from _aplanar(nodo["@graph"])
        tipo = nodo.get("@type")
        tipos = tipo if isinstance(tipo, list) else [tipo]
        if "JobPosting" in tipos:
            yield nodo


def _texto_ubicacion(nodo: dict) -> str | None:
    lugar = nodo.get("jobLocation")
    if isinstance(lugar, list):
        lugar = lugar[0] if lugar else None
    if not isinstance(lugar, dict):
        return None
    direccion = lugar.get("address")
    if isinstance(direccion, list):
        direccion = direccion[0] if direccion else None
    if isinstance(direccion, str):
        return direccion
    if not isinstance(direccion, dict):
        return None
    partes = [
        direccion.get("addressLocality"),
        direccion.get("addressRegion"),
        direccion.get("addressCountry")
        if isinstance(direccion.get("addressCountry"), str)
        else (direccion.get("addressCountry") or {}).get("name"),
    ]
    return ", ".join(p for p in partes if p) or None


def parsear_html(html_o_pagina, url: str, empresa_fallback: str | None = None) -> list[VacanteCruda]:
    """Extrae los JobPosting de una página ya descargada.

    Acepta el HTML crudo o una página de Scrapling, para poder testear sin red.
    """
    if isinstance(html_o_pagina, str):
        import re

        bloques = re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html_o_pagina,
            flags=re.DOTALL | re.IGNORECASE,
        )
    else:
        bloques = html_o_pagina.css('script[type="application/ld+json"]::text').getall()

    vacantes: list[VacanteCruda] = []
    for bloque in bloques:
        try:
            datos = json.loads(bloque)
        except json.JSONDecodeError:
            continue

        for nodo in _aplanar(datos):
            organizacion = nodo.get("hiringOrganization") or {}
            if isinstance(organizacion, str):
                organizacion = {"name": organizacion}
            empresa = organizacion.get("name") or empresa_fallback
            titulo = nodo.get("title")
            if not empresa or not titulo:
                continue

            identificador = nodo.get("identifier")
            if isinstance(identificador, dict):
                identificador = identificador.get("value")
            if not identificador:
                # Sin ID propio, generamos uno estable a partir de url+título para
                # que la próxima corrida reconozca el mismo aviso.
                identificador = hashlib.sha1(
                    f"{url}|{titulo}".encode()
                ).hexdigest()[:16]

            ubicacion = _texto_ubicacion(nodo)
            vacantes.append(
                VacanteCruda(
                    empresa=empresa,
                    empresa_dominio=organizacion.get("sameAs") or url,
                    titulo=titulo,
                    fuente=NOMBRE,
                    external_id=str(identificador),
                    fuente_url=nodo.get("url") or url,
                    ubicacion=ubicacion,
                    pais=inferir_pais(ubicacion),
                    modalidad=nodo.get("employmentType")
                    if isinstance(nodo.get("employmentType"), str)
                    else None,
                    descripcion=(nodo.get("description") or "")[:4000] or None,
                    fecha_publicacion=parsear_fecha(nodo.get("datePosted")),
                    empresa_industria=nodo.get("industry")
                    if isinstance(nodo.get("industry"), str)
                    else None,
                )
            )
    return vacantes


class PaginaDeCarrera:
    """Conector genérico para una página de carrera con JSON-LD."""

    nombre = NOMBRE

    def __init__(self, url: str, empresa: str | None = None, stealth: bool = False):
        self.url = url
        self.empresa = empresa
        self.stealth = stealth

    def fetch(self) -> list[VacanteCruda]:
        pagina = traer_pagina(self.url, stealth=self.stealth)
        return parsear_html(pagina, self.url, self.empresa)

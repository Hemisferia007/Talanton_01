"""Buscar los mails de contacto en el sitio de la empresa.

Es la vía gratis, ilimitada y de mejor procedencia que existe: la dirección
está publicada por la propia empresa, en su propia web, para que la contacten.
No hay intermediario, no hay base comprada y el origen del dato es la URL misma.

Hasta ahora el enriquecedor sólo leía el texto de los avisos que ya estaban en
la base. Eso deja afuera a toda empresa cuyos avisos no traen mail —la mayoría—
aunque tenga un `contacto@` visible en su home.

Acá entra Scrapling, que es para lo que está: parseo adaptativo de HTML que
cambia seguido. Si no está instalado se usa httpx y funciona igual para la
enorme mayoría de los sitios; el navegador stealth sólo hace falta en portales
con anti-bot, y una web institucional no lo es.

Dos límites deliberados:

- **Pocas páginas por empresa.** Cinco rutas probables, no un crawl. Buscamos
  una dirección de contacto, no espejar el sitio.
- **Sólo mails del dominio de la empresa.** El `hola@agenciaweb.com` del pie de
  página es de quien hizo el sitio, no de quien queremos contactar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urljoin

from . import contactos as mod_contactos

log = logging.getLogger("talanton.enriquecer")

# Dónde suele estar el mail, en orden de probabilidad. La home primero porque
# muchas PyMEs argentinas lo tienen en el pie y no tienen página de contacto.
RUTAS = ["/", "/contacto", "/contact", "/nosotros", "/about", "/equipo",
         "/trabaja-con-nosotros", "/careers"]

# Tope de páginas a visitar por empresa. Con cinco alcanza: si no apareció ahí,
# no está publicado, y seguir buscando es golpear un sitio ajeno de más.
TOPE_PAGINAS = 5
TIMEOUT = 12


@dataclass
class Resultado:
    dominio: str
    hallados: list = field(default_factory=list)
    paginas_leidas: int = 0
    error: str | None = None


def _traer(url: str) -> str | None:
    """Baja el HTML. Scrapling si está, httpx si no. Un fallo no es excepción:
    una empresa sin web o con el sitio caído es un caso normal, no un error."""
    try:
        from ..ingest.base import SCRAPLING_DISPONIBLE, Fetcher

        if SCRAPLING_DISPONIBLE:
            pagina = Fetcher.get(url, timeout=TIMEOUT)
            if pagina.status != 200:
                return None
            # `.html_content` trae el documento entero, que es donde está el
            # `mailto:` del pie — `.get_all_text()` se lo comería.
            return getattr(pagina, "html_content", None) or str(pagina)

        import httpx

        respuesta = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
        if respuesta.status_code != 200:
            return None
        return respuesta.text
    except Exception as exc:  # red, DNS, TLS, timeouts: todo es "no se pudo"
        log.debug("No se pudo leer %s: %s", url, exc)
        return None


def buscar(dominio: str, *, tope_paginas: int = TOPE_PAGINAS) -> Resultado:
    """Recorre unas pocas páginas del sitio y junta los mails del propio dominio."""
    dominio = (dominio or "").strip().lower()
    resultado = Resultado(dominio=dominio)
    if not dominio:
        resultado.error = "La empresa no tiene dominio cargado."
        return resultado

    base = f"https://{dominio}"
    vistos: set[str] = set()

    for ruta in RUTAS:
        if resultado.paginas_leidas >= tope_paginas:
            break
        url = urljoin(base, ruta)
        html = _traer(url)
        if html is None:
            continue
        resultado.paginas_leidas += 1

        for hallado in mod_contactos.extraer_emails(html, url):
            # Sólo del dominio de la empresa. El resto es de la agencia que hizo
            # el sitio, de un proveedor, o de una integración.
            if not _mismo_dominio(hallado.dominio, dominio):
                continue
            if hallado.direccion in vistos:
                continue
            vistos.add(hallado.direccion)
            resultado.hallados.append(hallado)

    if not resultado.paginas_leidas:
        resultado.error = f"No se pudo leer {dominio}. ¿El sitio está en línea?"
    return resultado


def _mismo_dominio(uno: str, otro: str) -> bool:
    """`rrhh@mail.empresa.com` cuenta como de `empresa.com`."""
    uno, otro = (uno or "").lower(), (otro or "").lower()
    if not uno or not otro:
        return False
    return uno == otro or uno.endswith("." + otro) or otro.endswith("." + uno)

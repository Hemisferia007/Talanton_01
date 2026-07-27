"""Contrato común de los conectores y capa de fetch.

Todos los conectores devuelven `VacanteCruda`. Así agregar una fuente es
incremental y aislado: no toca ni el scoring ni la web.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

# Scrapling es la capa de adquisición: parseo adaptativo (los portales cambian
# el DOM seguido) y sesiones stealth donde hace falta. Se importa de forma
# opcional para que la web y los tests corran sin las dependencias pesadas.
try:  # pragma: no cover - depende del entorno
    from scrapling.fetchers import Fetcher

    SCRAPLING_DISPONIBLE = True
except ImportError:  # pragma: no cover
    Fetcher = None  # type: ignore[assignment]
    SCRAPLING_DISPONIBLE = False


@dataclass
class VacanteCruda:
    """Aviso tal como lo devuelve una fuente, antes de normalizar."""

    empresa: str
    titulo: str
    fuente: str
    external_id: str
    fuente_url: str | None = None
    ubicacion: str | None = None
    pais: str | None = None
    modalidad: str | None = None
    descripcion: str | None = None
    fecha_publicacion: date | None = None
    # True cuando la fecha se dedujo de un texto tipo «hace 3 semanas»: tiene
    # varios días de error y no se puede citar como exacta.
    fecha_aproximada: bool = False
    # Datos firmográficos que la fuente pueda traer gratis.
    empresa_dominio: str | None = None
    empresa_industria: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Conector(Protocol):
    nombre: str

    def fetch(self) -> list[VacanteCruda]: ...


def traer_json(url: str, timeout: int = 30) -> Any:
    """GET que devuelve JSON. Usa Scrapling si está, httpx como fallback."""
    if SCRAPLING_DISPONIBLE:
        pagina = Fetcher.get(url, timeout=timeout)
        if pagina.status != 200:
            raise RuntimeError(f"{url} devolvió {pagina.status}")
        return pagina.json()

    import httpx

    respuesta = httpx.get(url, timeout=timeout, follow_redirects=True)
    respuesta.raise_for_status()
    return respuesta.json()


def traer_pagina(url: str, timeout: int = 30, stealth: bool = False):
    """Devuelve una página parseable de Scrapling.

    `stealth=True` sólo para los dominios que lo necesitan: es mucho más caro.
    """
    if not SCRAPLING_DISPONIBLE:  # pragma: no cover
        raise RuntimeError(
            "Este conector necesita Scrapling. Instalá con: "
            'pip install "scrapling[fetchers]" && scrapling install'
        )
    if stealth:
        from scrapling.fetchers import StealthyFetcher

        return StealthyFetcher.fetch(url, headless=True, timeout=timeout * 1000)
    return Fetcher.get(url, timeout=timeout)


def parsear_fecha(valor: str | None) -> date | None:
    """Tolerante con los formatos que devuelven las distintas fuentes."""
    if not valor:
        return None
    texto = str(valor).strip().replace("Z", "+00:00")
    from datetime import datetime

    for parser in (
        lambda t: datetime.fromisoformat(t).date(),
        lambda t: datetime.strptime(t[:10], "%Y-%m-%d").date(),
        lambda t: datetime.strptime(t[:10], "%d/%m/%Y").date(),
    ):
        try:
            return parser(texto)
        except (ValueError, TypeError):
            continue
    return None

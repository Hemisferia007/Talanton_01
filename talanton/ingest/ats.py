"""Conectores de ATS.

El carril más barato del pipeline: Greenhouse, Lever y compañía exponen JSON
público y estable, con fecha de publicación real y sin anti-bot. Es el 20% del
esfuerzo por el 60% de la señal limpia, así que se ataca primero.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

from .base import VacanteCruda, parsear_fecha, traer_json

# Pistas de ubicación para inferir el país cuando la fuente no lo declara.
_PISTAS_PAIS = {
    "AR": ["argentina", "buenos aires", "caba", "cordoba", "córdoba", "rosario", "mendoza"],
    "UY": ["uruguay", "montevideo"],
    "CL": ["chile", "santiago", "valparaiso", "valparaíso"],
    "MX": ["mexico", "méxico", "cdmx", "guadalajara", "monterrey"],
    "CO": ["colombia", "bogota", "bogotá", "medellin", "medellín"],
    "PE": ["peru", "perú", "lima"],
    "BR": ["brasil", "brazil", "sao paulo", "são paulo", "rio de janeiro"],
}


def inferir_pais(ubicacion: str | None) -> str | None:
    if not ubicacion:
        return None
    texto = ubicacion.lower()
    for codigo, pistas in _PISTAS_PAIS.items():
        if any(pista in texto for pista in pistas):
            return codigo
    return None


def _desde_epoch_ms(valor) -> date | None:
    """Lever devuelve `createdAt` como epoch en milisegundos."""
    if not isinstance(valor, (int, float)):
        return None
    return datetime.fromtimestamp(valor / 1000, tz=timezone.utc).date()


def _limpiar_html(html: str | None) -> str | None:
    if not html:
        return None
    texto = re.sub(r"<[^>]+>", " ", html)
    texto = re.sub(r"&nbsp;?", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()[:4000]


class Greenhouse:
    """https://boards-api.greenhouse.io/v1/boards/<board>/jobs"""

    nombre = "greenhouse"

    def __init__(self, board: str, empresa: str | None = None, dominio: str | None = None):
        self.board = board
        self.empresa = empresa or board
        self.dominio = dominio

    def fetch(self) -> list[VacanteCruda]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{self.board}/jobs?content=true"
        datos = traer_json(url)
        vacantes = []
        for puesto in datos.get("jobs", []):
            ubicacion = (puesto.get("location") or {}).get("name")
            vacantes.append(
                VacanteCruda(
                    empresa=self.empresa,
                    empresa_dominio=self.dominio,
                    titulo=puesto.get("title", ""),
                    fuente=self.nombre,
                    external_id=f"{self.board}:{puesto.get('id')}",
                    fuente_url=puesto.get("absolute_url"),
                    ubicacion=ubicacion,
                    pais=inferir_pais(ubicacion),
                    descripcion=_limpiar_html(puesto.get("content")),
                    fecha_publicacion=parsear_fecha(
                        puesto.get("first_published") or puesto.get("updated_at")
                    ),
                )
            )
        return vacantes


class Lever:
    """https://api.lever.co/v0/postings/<board>?mode=json"""

    nombre = "lever"

    def __init__(self, board: str, empresa: str | None = None, dominio: str | None = None):
        self.board = board
        self.empresa = empresa or board
        self.dominio = dominio

    def fetch(self) -> list[VacanteCruda]:
        url = f"https://api.lever.co/v0/postings/{self.board}?mode=json"
        datos = traer_json(url)
        vacantes = []
        for puesto in datos:
            categorias = puesto.get("categories") or {}
            ubicacion = categorias.get("location")
            vacantes.append(
                VacanteCruda(
                    empresa=self.empresa,
                    empresa_dominio=self.dominio,
                    titulo=puesto.get("text", ""),
                    fuente=self.nombre,
                    external_id=f"{self.board}:{puesto.get('id')}",
                    fuente_url=puesto.get("hostedUrl"),
                    ubicacion=ubicacion,
                    pais=inferir_pais(ubicacion),
                    modalidad=categorias.get("commitment"),
                    descripcion=_limpiar_html(puesto.get("descriptionPlain") or puesto.get("description")),
                    fecha_publicacion=_desde_epoch_ms(puesto.get("createdAt")),
                    empresa_industria=categorias.get("department"),
                )
            )
        return vacantes

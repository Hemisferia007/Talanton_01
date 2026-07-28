"""De una búsqueda en Apollo a leads cargados.

El camino es a propósito en dos pasos, con la plata en el medio:

    buscar → mirás la lista → elegís → revelás emails e importás

Buscar no cuesta créditos y no destapa emails. Revelar sí. Separarlo deja que
ajustes los filtros todas las veces que haga falta sin gastar nada, y que
después pagues sólo por los contactos que realmente vas a usar.

La persistencia no se reimplementa: las filas se traducen al mismo `Fila` que
usa el importador de listas, así una empresa que llega por Apollo y otra que
llega pegada de un Excel terminan idénticas en la base.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..importar import Fila, Resultado as ResultadoImportacion, importar
from ..models import PerfilConsultora
from ..services import perfil
from .cliente import Cliente, ErrorApollo, Persona

log = logging.getLogger("talanton.apollo")

# Quién firma el contrato de una búsqueda. No es quien la necesita: el gerente
# de operaciones sufre la vacante, pero el que contrata una consultora es RRHH
# —o el dueño, en una empresa donde RRHH no existe como área—.
CARGOS_POR_DEFECTO = [
    "Gerente de Recursos Humanos",
    "Jefe de Recursos Humanos",
    "Director de Recursos Humanos",
    "Human Resources Manager",
    "Head of People",
    "Talent Acquisition Manager",
    "Gerente General",
    "Owner",
]

# Apollo devuelve países en inglés; la base los guarda con código ISO.
_PAIS_APOLLO = {
    "AR": "Argentina",
    "UY": "Uruguay",
    "CL": "Chile",
    "MX": "Mexico",
    "CO": "Colombia",
    "PE": "Peru",
    "BR": "Brazil",
}


@dataclass
class Filtros:
    cargos: list[str] = field(default_factory=lambda: list(CARGOS_POR_DEFECTO))
    pais: str = "AR"
    industrias: list[str] = field(default_factory=list)
    dotacion_min: int | None = None
    dotacion_max: int | None = None
    pagina: int = 1
    por_pagina: int = 25

    @classmethod
    def desde_perfil(cls, p: PerfilConsultora, pais: str = "AR") -> "Filtros":
        """Arranca con el ICP ya cargado, para no volver a tipear lo mismo."""
        return cls(
            pais=pais,
            industrias=p.industrias,
            dotacion_min=p.dotacion_min,
            dotacion_max=p.dotacion_max,
        )


def buscar(session: Session, filtros: Filtros, cliente: Cliente | None = None):
    """Trae la lista para previsualizar. No consume créditos."""
    cli = cliente or Cliente()
    pais_apollo = _PAIS_APOLLO.get(filtros.pais.upper())
    return cli.buscar_personas(
        cargos=[c for c in filtros.cargos if c.strip()],
        paises=[pais_apollo] if pais_apollo else None,
        industrias=filtros.industrias or None,
        dotacion_min=filtros.dotacion_min,
        dotacion_max=filtros.dotacion_max,
        pagina=filtros.pagina,
        por_pagina=filtros.por_pagina,
    )


@dataclass
class ResultadoImportar:
    importacion: ResultadoImportacion
    revelados: int = 0
    sin_email: int = 0
    fallidos: list[str] = field(default_factory=list)


def importar_personas(
    session: Session,
    personas: list[Persona],
    *,
    pais: str = "AR",
    revelar: bool = True,
    cliente: Cliente | None = None,
) -> ResultadoImportar:
    """Revela los emails que falten y guarda todo como empresas, contactos y leads.

    **Cada revelado consume un crédito de Apollo.** Por eso `revelar` es un
    parámetro y no algo implícito: se puede importar la empresa y el nombre del
    decisor sin pagar, y buscar el mail después por otra vía.
    """
    cli = None
    if revelar and any(not p.email_visible for p in personas):
        cli = cliente or Cliente()

    resultado = ResultadoImportar(importacion=ResultadoImportacion())
    filas: list[Fila] = []

    for persona in personas:
        if not persona.empresa:
            # Sin empresa no hay lead: el producto es la empresa, no la persona.
            resultado.fallidos.append(f"{persona.nombre}: Apollo no trajo la empresa")
            continue

        if cli is not None and not persona.email_visible:
            try:
                cli.revelar_email(persona)
                if persona.email:
                    resultado.revelados += 1
            except ErrorApollo as exc:
                # Un revelado que falla no puede frenar la importación entera:
                # el resto de los contactos ya se pagaron.
                log.warning("No se pudo revelar %s: %s", persona.nombre, exc)
                resultado.fallidos.append(f"{persona.nombre}: {exc}")
                persona.email = None
        elif not persona.email_visible:
            persona.email = None

        if not persona.email:
            resultado.sin_email += 1

        filas.append(
            Fila(
                empresa=persona.empresa,
                dominio=persona.dominio,
                contacto=persona.nombre,
                cargo=persona.cargo,
                email=persona.email,
                industria=persona.industria,
                dotacion=persona.dotacion,
                ciudad=persona.ciudad,
                procedencia=persona.linkedin_url or f"apollo.io:{persona.apollo_id}",
            )
        )

    if filas:
        resultado.importacion = importar(session, filas, pais=pais)
    return resultado


def filtros_iniciales(session: Session, pais: str = "AR") -> Filtros:
    return Filtros.desde_perfil(perfil(session), pais=pais)

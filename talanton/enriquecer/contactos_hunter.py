"""Buscar contactos de RRHH y guardarlos como decisores.

Sobre `hunter.py`, que es sólo el transporte. Acá está la parte con criterio:
qué contacto se marca como decisor, cuál se descarta y cómo no gastar dos
búsquedas en la misma empresa.

La regla de gasto: **una empresa que ya tiene un contacto con mail no se vuelve
a buscar.** El plan gratuito trae 25 búsquedas por mes; quemarlas re-consultando
empresas ya resueltas es la forma más rápida de quedarse sin ninguna.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Contacto, Empresa, Lead
from ..services import asegurar_lead, perfil, recalcular_lead
from . import decisor
from .hunter import Cliente, ErrorHunter, Hallazgo

log = logging.getLogger("talanton.hunter")


@dataclass
class Resumen:
    empresas_consultadas: int = 0
    contactos_nuevos: int = 0
    decisores: int = 0
    sin_resultados: list[str] = field(default_factory=list)
    salteadas: int = 0
    restantes: int | None = None
    error: str | None = None


def _ya_tiene_mail(empresa: Empresa) -> bool:
    return any(c.email for c in empresa.contactos)


def buscar_una(
    session: Session, empresa: Empresa, cliente: Cliente | None = None
) -> tuple[int, bool]:
    """Busca los contactos de una empresa. Devuelve (nuevos, marcó_decisor).

    Gasta una búsqueda de Hunter. Quien llama decide si vale la pena.
    """
    cli = cliente or Cliente()
    resultado = cli.buscar_dominio(empresa.dominio or "")

    existentes = {(c.email or "").lower() for c in empresa.contactos if c.email}
    nuevos = 0
    marco_decisor = False

    # Las personas primero y el buzón de área después: si hay alguien con
    # nombre y cargo, es a esa persona a la que hay que escribirle.
    for hallazgo in resultado.personas + resultado.buzones:
        if hallazgo.email in existentes:
            continue

        # Sólo el primero, y sólo si es una persona con un cargo que decide.
        # Un `rrhh@` sirve para escribir, pero llamarlo decisor sería mentirle
        # al eje de accesibilidad del score.
        es_decisor = (
            not marco_decisor
            and not hallazgo.es_de_area
            and decisor.es_cargo_decisor(hallazgo.cargo, empresa)
        )

        empresa.contactos.append(
            Contacto(
                nombre=hallazgo.nombre or f"Contacto de {empresa.nombre}",
                cargo=hallazgo.cargo,
                email=hallazgo.email,
                es_decisor=es_decisor,
                fuente_url=hallazgo.fuente_url or f"hunter.io:{resultado.dominio}",
            )
        )
        existentes.add(hallazgo.email)
        nuevos += 1
        marco_decisor = marco_decisor or es_decisor

    if nuevos:
        session.flush()
        session.refresh(empresa)
        lead = asegurar_lead(session, empresa)
        recalcular_lead(session, lead, perfil(session))

    return nuevos, marco_decisor


def buscar_faltantes(
    session: Session,
    *,
    limite: int = 10,
    cliente: Cliente | None = None,
) -> Resumen:
    """Busca contactos para los leads que todavía no tienen ninguno con mail.

    `limite` es el tope de búsquedas a gastar en esta corrida. Existe porque el
    plan gratuito trae 25 por mes y una corrida sobre 45 empresas se las come
    todas de un saque.
    """
    resumen = Resumen()
    try:
        cli = cliente or Cliente()
    except ErrorHunter as exc:
        resumen.error = str(exc)
        return resumen

    leads = list(
        session.scalars(
            select(Lead)
            .join(Empresa, Lead.empresa_id == Empresa.id)
            .options(selectinload(Lead.empresa).selectinload(Empresa.contactos))
            .order_by(Lead.score.desc())
        ).all()
    )

    for lead in leads:
        if resumen.empresas_consultadas >= limite:
            break
        empresa = lead.empresa
        if not empresa.dominio or _ya_tiene_mail(empresa):
            resumen.salteadas += 1
            continue

        try:
            nuevos, marco = buscar_una(session, empresa, cliente=cli)
        except ErrorHunter as exc:
            # Sin búsquedas queda sin sentido seguir; cualquier otra falla es de
            # esta empresa y no puede frenar a las demás.
            log.warning("Hunter falló en %s: %s", empresa.nombre, exc)
            if "acabaron" in str(exc):
                resumen.error = str(exc)
                break
            resumen.sin_resultados.append(f"{empresa.nombre}: {exc}")
            continue

        resumen.empresas_consultadas += 1
        resumen.contactos_nuevos += nuevos
        resumen.decisores += 1 if marco else 0
        if not nuevos:
            resumen.sin_resultados.append(empresa.nombre)
        session.commit()

    session.commit()
    return resumen

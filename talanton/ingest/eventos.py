"""Persistencia de eventos y su vínculo con empresas."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Empresa, Evento, Objetivo
from ..normalize import normalizar_nombre_empresa
from ..services import asegurar_lead, perfil, recalcular_lead
from .posts import EventoCrudo

log = logging.getLogger("talanton.eventos")


@dataclass
class ResumenEventos:
    encontrados: int = 0
    nuevos: int = 0
    vinculados: int = 0
    objetivos_creados: int = 0


def _buscar_empresa(session: Session, nombre: str) -> Empresa | None:
    return session.scalar(
        select(Empresa).where(Empresa.nombre_normalizado == normalizar_nombre_empresa(nombre))
    )


def persistir_eventos(session: Session, crudos: list[EventoCrudo]) -> ResumenEventos:
    """Guarda los eventos y los vincula a la empresa cuando ya la conocemos.

    Si la empresa no está en la base, se la carga como objetivo a vigilar: una
    empresa que acaba de levantar plata todavía no publicó nada, y justamente
    queremos estar mirando cuando lo haga.
    """
    resumen = ResumenEventos(encontrados=len(crudos))
    p = perfil(session)

    for crudo in crudos:
        ya_esta = session.scalar(
            select(Evento).where(
                Evento.fuente == crudo.fuente, Evento.external_id == crudo.external_id
            )
        )
        if ya_esta:
            continue

        empresa = _buscar_empresa(session, crudo.empresa_mencionada or "")
        evento = Evento(
            empresa_id=empresa.id if empresa else None,
            tipo=crudo.tipo,
            titulo=crudo.titulo,
            resumen=crudo.resumen,
            empresa_mencionada=crudo.empresa_mencionada,
            fecha=crudo.fecha,
            fecha_aproximada=crudo.fecha_aproximada,
            fuente=crudo.fuente,
            fuente_url=crudo.fuente_url,
            external_id=crudo.external_id,
        )
        session.add(evento)
        resumen.nuevos += 1

        if empresa:
            resumen.vinculados += 1
        elif crudo.empresa_mencionada:
            if _asegurar_objetivo(session, crudo.empresa_mencionada):
                resumen.objetivos_creados += 1

    session.flush()

    # Los eventos nuevos entran sin confirmar, así que todavía no mueven el
    # score. El recálculo se dispara al confirmarlos.
    session.commit()
    return resumen


def _asegurar_objetivo(session: Session, nombre: str) -> bool:
    normalizado = normalizar_nombre_empresa(nombre)
    if session.scalar(select(Objetivo).where(Objetivo.nombre_normalizado == normalizado)):
        return False
    session.add(Objetivo(nombre=nombre, nombre_normalizado=normalizado))
    session.flush()
    return True


def pendientes(session: Session, limite: int = 100) -> list[Evento]:
    return list(
        session.scalars(
            select(Evento)
            .where(Evento.confirmado.is_(False), Evento.descartado.is_(False))
            .options(selectinload(Evento.empresa))
            .order_by(Evento.fecha.desc())
            .limit(limite)
        ).all()
    )


def confirmar(session: Session, evento: Evento) -> None:
    """Confirma el evento y lo hace pesar en el score de la empresa."""
    evento.confirmado = True
    evento.descartado = False

    if evento.empresa_id is None and evento.empresa_mencionada:
        empresa = _buscar_empresa(session, evento.empresa_mencionada)
        if empresa:
            evento.empresa_id = empresa.id

    session.flush()
    if evento.empresa:
        session.refresh(evento.empresa)
        lead = asegurar_lead(session, evento.empresa)
        recalcular_lead(session, lead, perfil(session))
    session.commit()


def descartar(session: Session, evento: Evento) -> None:
    evento.descartado = True
    evento.confirmado = False
    session.flush()
    if evento.empresa:
        session.refresh(evento.empresa)
        if evento.empresa.lead:
            recalcular_lead(session, evento.empresa.lead, perfil(session))
    session.commit()

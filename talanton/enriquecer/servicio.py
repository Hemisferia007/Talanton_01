"""Corrida de enriquecimiento sobre las empresas ya en la base."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Contacto, Empresa, Vacante
from ..services import perfil, recalcular_lead
from . import contactos as mod_contactos
from . import decisor
from . import sitio as mod_sitio

log = logging.getLogger("talanton.enriquecer")


@dataclass
class Resumen:
    empresas_revisadas: int = 0
    contactos_nuevos: int = 0
    decisores_marcados: int = 0
    dominios_muertos: int = 0


def _texto_de_las_vacantes(empresa: Empresa) -> tuple[str, str | None]:
    """Junta las descripciones de los avisos, con una URL de referencia."""
    partes = []
    fuente = None
    for v in empresa.vacantes:
        if v.descripcion:
            partes.append(v.descripcion)
            fuente = fuente or v.fuente_url
    return "\n".join(partes), fuente


def enriquecer_empresa(
    session: Session,
    empresa: Empresa,
    *,
    verificar_dns: bool = True,
    mirar_sitio: bool = True,
) -> tuple[int, bool]:
    """Busca contactos de la empresa. Devuelve (nuevos, marcó_decisor).

    Dos fuentes, en orden de calidad: el texto de sus propios avisos —donde la
    dirección está puesta para que le escriban por trabajo— y después el sitio
    web. Las dos son gratis y de procedencia auditable.
    """
    texto, fuente_url = _texto_de_las_vacantes(empresa)
    hallados = mod_contactos.extraer_emails(texto, fuente_url)

    # El sitio sólo si los avisos no alcanzaron: bajar cinco páginas de una web
    # ajena para confirmar un mail que ya tenemos es golpearla al pedo.
    if not hallados and mirar_sitio and empresa.dominio:
        hallados = mod_sitio.buscar(empresa.dominio).hallados

    if not hallados:
        return 0, False

    ya_tenemos = {c.email.lower() for c in empresa.contactos if c.email}
    objetivo = decisor.objetivo_para(empresa)
    nuevos = 0
    marco_decisor = False

    mejor = mod_contactos.elegir_mejor(hallados, empresa.dominio)

    for hallado in hallados:
        if hallado.direccion in ya_tenemos:
            continue

        if verificar_dns and mod_contactos.dominio_recibe_mail(hallado.dominio) is False:
            log.info("  descartado %s: el dominio no resuelve", hallado.direccion)
            continue

        nombre = hallado.nombre_probable
        if nombre:
            cargo = None
        else:
            # Buzón de área: el "cargo" es el área, y se deja anotado a quién
            # habría que pedirle hablar cuando contesten.
            nombre = f"Contacto de {empresa.nombre}"
            cargo = f"Buzón {hallado.usuario} — pedir por {objetivo.cargo_principal}"

        # Sólo el mejor candidato se marca decisor, y sólo si es una persona:
        # un buzón genérico no decide nada, y marcarlo inflaría el score de
        # accesibilidad con una señal que no es real.
        es_decisor = hallado is mejor and not hallado.es_de_area
        # Se agrega por la relación y no por la FK: así `empresa.contactos`
        # queda consistente en memoria y quien llame después ve el contacto
        # sin tener que refrescar la entidad.
        empresa.contactos.append(
            Contacto(
                nombre=nombre,
                cargo=cargo,
                email=hallado.direccion,
                es_decisor=es_decisor,
                fuente_url=hallado.fuente_url,
            )
        )
        nuevos += 1
        marco_decisor = marco_decisor or es_decisor

    session.flush()
    return nuevos, marco_decisor


def correr(session: Session, *, verificar_dns: bool = True, limite: int | None = None) -> Resumen:
    """Enriquece las empresas que todavía no tienen contacto cargado."""
    resumen = Resumen()
    consulta = (
        select(Empresa)
        .options(selectinload(Empresa.vacantes), selectinload(Empresa.contactos))
        .order_by(Empresa.id)
    )
    empresas = list(session.scalars(consulta).all())

    p = perfil(session)
    for empresa in empresas:
        if limite is not None and resumen.empresas_revisadas >= limite:
            break
        # Si ya hay un decisor identificado, no hay nada que agregar.
        if any(c.es_decisor for c in empresa.contactos):
            continue

        resumen.empresas_revisadas += 1
        nuevos, marco = enriquecer_empresa(session, empresa, verificar_dns=verificar_dns)
        resumen.contactos_nuevos += nuevos
        resumen.decisores_marcados += int(marco)

        if nuevos and empresa.lead:
            # Un contacto nuevo cambia el eje de accesibilidad del score.
            session.refresh(empresa)
            recalcular_lead(session, empresa.lead, p)

    session.commit()
    return resumen

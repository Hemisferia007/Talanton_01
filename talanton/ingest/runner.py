"""Corrida de ingesta: fetch -> normalizar -> persistir -> rescorear.

Se ejecuta una vez por día. Cada día que no corre es un día de histórico
perdido, y el histórico es el activo del producto.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..services import (
    asegurar_lead,
    cerrar_vacantes_no_vistas,
    fecha_hoy,
    recalcular_lead,
    perfil,
    registrar_actividad,
    upsert_empresa,
    upsert_vacante,
)
from .ats import Greenhouse, Lever
from .base import Conector, VacanteCruda
from .jsonld import PaginaDeCarrera

log = logging.getLogger("talanton.ingest")

ARCHIVO_FUENTES = BASE_DIR / "fuentes.json"


@dataclass
class Resumen:
    conector: str
    encontradas: int = 0
    nuevas: int = 0
    cerradas: int = 0
    error: str | None = None


def cargar_conectores(ruta: Path | None = None) -> list[Conector]:
    """Lee fuentes.json y arma los conectores declarados."""
    ruta = ruta or ARCHIVO_FUENTES
    if not ruta.exists():
        return []
    config = json.loads(ruta.read_text(encoding="utf-8"))
    conectores: list[Conector] = []
    for entrada in config.get("fuentes", []):
        tipo = entrada.get("tipo")
        if tipo == "greenhouse":
            conectores.append(
                Greenhouse(entrada["board"], entrada.get("empresa"), entrada.get("dominio"))
            )
        elif tipo == "lever":
            conectores.append(
                Lever(entrada["board"], entrada.get("empresa"), entrada.get("dominio"))
            )
        elif tipo == "pagina_carrera":
            conectores.append(
                PaginaDeCarrera(
                    entrada["url"], entrada.get("empresa"), entrada.get("stealth", False)
                )
            )
        else:
            log.warning("Tipo de fuente desconocido: %s", tipo)
    return conectores


def persistir(session: Session, crudas: list[VacanteCruda], fuente: str) -> Resumen:
    resumen = Resumen(conector=fuente, encontradas=len(crudas))
    hoy = fecha_hoy()
    p = perfil(session)
    leads_tocados = {}

    for cruda in crudas:
        if not cruda.titulo or not cruda.empresa:
            continue
        empresa = upsert_empresa(
            session,
            cruda.empresa,
            dominio=cruda.empresa_dominio,
            pais=cruda.pais,
            industria=cruda.empresa_industria,
        )
        vacante, es_nueva = upsert_vacante(
            session,
            empresa,
            titulo=cruda.titulo,
            fuente=cruda.fuente,
            external_id=cruda.external_id,
            fuente_url=cruda.fuente_url,
            ubicacion=cruda.ubicacion,
            pais=cruda.pais,
            modalidad=cruda.modalidad,
            descripcion=cruda.descripcion,
            fecha_publicacion=cruda.fecha_publicacion,
            vista_el=hoy,
        )
        lead = asegurar_lead(session, empresa)
        leads_tocados[lead.id] = lead
        if es_nueva:
            resumen.nuevas += 1
            registrar_actividad(
                session,
                lead,
                f"Nueva búsqueda detectada: «{vacante.titulo}» ({cruda.fuente})",
                tipo="senal",
            )

    resumen.cerradas = cerrar_vacantes_no_vistas(session, fuente, hoy)

    for lead in leads_tocados.values():
        session.refresh(lead.empresa)
        recalcular_lead(session, lead, p)

    return resumen


def correr(session: Session, conectores: list[Conector] | None = None) -> list[Resumen]:
    conectores = conectores if conectores is not None else cargar_conectores()
    resultados: list[Resumen] = []
    for conector in conectores:
        etiqueta = f"{conector.nombre}:{getattr(conector, 'board', getattr(conector, 'url', ''))}"
        try:
            crudas = conector.fetch()
        except Exception as exc:  # una fuente caída no debe frenar la corrida
            log.error("Falló %s: %s", etiqueta, exc)
            resultados.append(Resumen(conector=etiqueta, error=str(exc)))
            continue
        resumen = persistir(session, crudas, conector.nombre)
        resumen.conector = etiqueta
        session.commit()
        resultados.append(resumen)
        log.info(
            "%s: %s encontradas, %s nuevas, %s cerradas",
            etiqueta,
            resumen.encontradas,
            resumen.nuevas,
            resumen.cerradas,
        )
    return resultados

"""Fuentes y objetivos: alta, sondeo y armado de conectores.

La fuente de verdad es la base, no `fuentes.json`. El archivo queda sólo como
semilla para el primer arranque, así un despliegue nuevo no queda en blanco.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..config import BASE_DIR
from ..models import Fuente, Objetivo, ahora
from ..normalize import normalizar_dominio, normalizar_nombre_empresa
from .ats import Greenhouse, Lever
from .base import Conector
from .jsonld import PaginaDeCarrera

log = logging.getLogger("talanton.fuentes")

ARCHIVO_SEMILLA = BASE_DIR / "fuentes.json"

# Tipos que sabemos ingerir hoy. El descubridor puede encontrar más (Ashby,
# Recruitee, Workable): se guardan igual y quedan inactivos hasta que exista el
# conector, para no perder el hallazgo.
TIPOS_CON_CONECTOR = {
    "greenhouse", "lever", "pagina_carrera",
    "busqueda_linkedin", "busqueda_posts",
}


# --- Objetivos ---------------------------------------------------------------


def agregar_objetivos(session: Session, lineas: str) -> tuple[int, int]:
    """Carga empresas a vigilar desde texto libre, una por línea.

    Formato: `Nombre` o `Nombre, dominio.com.ar`. Devuelve (nuevos, repetidos).
    """
    nuevos = repetidos = 0
    for linea in (lineas or "").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue

        partes = [p.strip() for p in linea.replace(";", ",").replace("\t", ",").split(",", 1)]
        nombre = partes[0]
        dominio = normalizar_dominio(partes[1]) if len(partes) > 1 and partes[1] else None
        if not nombre:
            continue

        normalizado = normalizar_nombre_empresa(nombre)
        ya_esta = session.scalar(
            select(Objetivo).where(Objetivo.nombre_normalizado == normalizado)
        )
        if ya_esta:
            # Si antes no tenía dominio y ahora sí, se aprovecha: mejora mucho
            # las chances del sondeo.
            if dominio and not ya_esta.dominio:
                ya_esta.dominio = dominio
                ya_esta.revisado_en = None  # vale la pena volver a sondearlo
            repetidos += 1
            continue

        session.add(
            Objetivo(nombre=nombre, nombre_normalizado=normalizado, dominio=dominio)
        )
        nuevos += 1

    session.flush()
    return nuevos, repetidos


def objetivos_pendientes(session: Session, limite: int | None = None) -> list[Objetivo]:
    consulta = (
        select(Objetivo)
        .where(Objetivo.activo.is_(True), Objetivo.revisado_en.is_(None))
        .order_by(Objetivo.creado_en)
    )
    if limite:
        consulta = consulta.limit(limite)
    return list(session.scalars(consulta).all())


def listar_objetivos(session: Session) -> list[Objetivo]:
    return list(
        session.scalars(
            select(Objetivo)
            .options(selectinload(Objetivo.fuentes))
            .order_by(Objetivo.creado_en.desc())
        ).all()
    )


def sondear_objetivo(session: Session, objetivo: Objetivo, *, pausa: float = 0.4) -> int:
    """Busca fuentes para un objetivo y las guarda. Devuelve cuántas encontró."""
    from .descubridor import descubrir_una

    try:
        hallazgos, motivo = descubrir_una(objetivo.nombre, objetivo.dominio, pausa=pausa)
    except Exception as exc:
        log.warning("Falló el sondeo de %s: %s", objetivo.nombre, exc)
        objetivo.revisado_en = ahora()
        objetivo.resultado = "sin_fuente"
        objetivo.detalle = f"Error al sondear: {exc}"
        session.flush()
        return 0

    guardadas = 0
    for h in hallazgos:
        if _guardar_fuente(
            session,
            tipo=h.plataforma,
            identificador=h.slug_o_url,
            empresa=objetivo.nombre,
            dominio=objetivo.dominio,
            objetivo=objetivo,
        ):
            guardadas += 1

    objetivo.revisado_en = ahora()
    if hallazgos:
        objetivo.resultado = "ok"
        objetivo.detalle = "; ".join(
            f"{h.plataforma}/{h.slug_o_url} ({h.avisos} avisos)" for h in hallazgos
        )
    else:
        objetivo.resultado = "sin_fuente"
        objetivo.detalle = motivo or "no se encontró dónde publica"
    session.flush()
    return guardadas


def _guardar_fuente(
    session: Session,
    *,
    tipo: str,
    identificador: str,
    empresa: str,
    dominio: str | None,
    objetivo: Objetivo | None = None,
    stealth: bool = False,
) -> bool:
    """Alta idempotente. Devuelve True si la fuente es nueva."""
    existente = session.scalar(
        select(Fuente).where(Fuente.tipo == tipo, Fuente.identificador == identificador)
    )
    if existente:
        if objetivo and existente.objetivo_id is None:
            existente.objetivo_id = objetivo.id
        return False

    session.add(
        Fuente(
            objetivo=objetivo,
            tipo=tipo,
            identificador=identificador,
            empresa=empresa,
            dominio=dominio,
            stealth=stealth,
            # Si todavía no hay conector para ese tipo, se guarda inactiva:
            # el hallazgo no se pierde y se activa cuando exista el conector.
            activa=tipo in TIPOS_CON_CONECTOR,
        )
    )
    session.flush()
    return True


def agregar_busqueda_linkedin(
    session: Session, *, nombre: str, configuracion: str
) -> bool:
    """Guarda una búsqueda de LinkedIn como fuente.

    A diferencia del resto, no está atada a una empresa: es una consulta por
    rubro y ubicación que **descubre** empresas que todavía no están en la base.
    """
    from .apify import desde_configuracion  # valida el JSON antes de guardar

    desde_configuracion(configuracion, nombre)
    return _guardar_fuente(
        session,
        tipo="busqueda_linkedin",
        identificador=configuracion.strip(),
        empresa=nombre.strip(),
        dominio=None,
    )


def agregar_busqueda_posts(
    session: Session, *, nombre: str, configuracion: str
) -> bool:
    """Guarda una búsqueda de posts (rondas, expansión) como fuente."""
    from .posts import desde_configuracion

    desde_configuracion(configuracion, nombre)
    return _guardar_fuente(
        session,
        tipo="busqueda_posts",
        identificador=configuracion.strip(),
        empresa=nombre.strip(),
        dominio=None,
    )


def buscadores_de_posts(session: Session) -> list[tuple[Fuente, object]]:
    """Las búsquedas de posts van por separado: producen eventos, no vacantes."""
    from .posts import ErrorApify, desde_configuracion

    pares = []
    for fuente in listar_fuentes(session, solo_activas=True):
        if fuente.tipo != "busqueda_posts":
            continue
        try:
            pares.append((fuente, desde_configuracion(fuente.identificador, fuente.empresa)))
        except ErrorApify as exc:
            log.warning("Búsqueda de posts %s inválida: %s", fuente.empresa, exc)
            fuente.ultimo_error = str(exc)
    return pares


def agregar_fuente_manual(
    session: Session, *, tipo: str, identificador: str, empresa: str, dominio: str | None = None
) -> bool:
    return _guardar_fuente(
        session,
        tipo=tipo,
        identificador=identificador.strip(),
        empresa=empresa.strip(),
        dominio=normalizar_dominio(dominio),
    )


# --- Fuentes -----------------------------------------------------------------


def listar_fuentes(session: Session, *, solo_activas: bool = False) -> list[Fuente]:
    consulta = select(Fuente).order_by(Fuente.empresa, Fuente.tipo)
    if solo_activas:
        consulta = consulta.where(Fuente.activa.is_(True))
    return list(session.scalars(consulta).all())


def conectores_desde_base(session: Session) -> list[tuple[Fuente, Conector]]:
    """Arma los conectores de las fuentes activas que sabemos ingerir."""
    pares: list[tuple[Fuente, Conector]] = []
    for fuente in listar_fuentes(session, solo_activas=True):
        if fuente.tipo == "busqueda_posts":
            continue  # produce eventos, no vacantes: ver buscadores_de_posts()
        if fuente.tipo == "greenhouse":
            conector = Greenhouse(fuente.identificador, fuente.empresa, fuente.dominio)
        elif fuente.tipo == "lever":
            conector = Lever(fuente.identificador, fuente.empresa, fuente.dominio)
        elif fuente.tipo == "pagina_carrera":
            conector = PaginaDeCarrera(fuente.identificador, fuente.empresa, fuente.stealth)
        elif fuente.tipo == "busqueda_linkedin":
            from .apify import ErrorApify, desde_configuracion

            try:
                conector = desde_configuracion(fuente.identificador, fuente.empresa)
            except ErrorApify as exc:
                # Una búsqueda mal configurada no debe tumbar la corrida entera.
                log.warning("Búsqueda %s inválida: %s", fuente.empresa, exc)
                fuente.ultimo_error = str(exc)
                continue
        else:
            continue
        pares.append((fuente, conector))
    return pares


def sembrar_desde_archivo(session: Session, ruta: Path | None = None) -> int:
    """Carga fuentes.json la primera vez, para que un despliegue nuevo no arranque vacío."""
    if session.scalar(select(func.count()).select_from(Fuente)):
        return 0

    ruta = ruta or ARCHIVO_SEMILLA
    if not ruta.exists():
        return 0

    try:
        config = json.loads(ruta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("No se pudo leer %s: %s", ruta, exc)
        return 0

    cargadas = 0
    for entrada in config.get("fuentes", []):
        tipo = entrada.get("tipo")
        identificador = entrada.get("board") or entrada.get("url")
        if not tipo or not identificador:
            continue
        # El archivo de ejemplo trae una URL de muestra que no sirve de nada.
        if "ejemplo.com" in str(identificador):
            continue
        if _guardar_fuente(
            session,
            tipo=tipo,
            identificador=identificador,
            empresa=entrada.get("empresa") or identificador,
            dominio=entrada.get("dominio"),
            stealth=bool(entrada.get("stealth")),
        ):
            cargadas += 1

    session.flush()
    return cargadas

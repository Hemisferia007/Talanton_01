"""Buscar empresas por segmento.

El giro del producto. Hasta acá el flujo era: cargás una lista de empresas y
esperás a que publiquen. Pero conseguir esa lista *es* el problema que se vino a
resolver, así que el orden estaba al revés.

Ahora es: definís un segmento —zona, rubro, tamaño, antigüedad del aviso— y las
empresas que aparecen publicando **ya son leads con señal**. No hay que esperar
nada: una empresa que publica hoy está contratando hoy.

Dos pasos separados a propósito:

1. `explorar()` mira los portales y devuelve lo que encontró **sin tocar la
   base**. Se puede revisar en pantalla antes de decidir.
2. `traer()` persiste lo elegido con el mismo circuito de siempre
   (`upsert_empresa` → `upsert_vacante` → `asegurar_lead` → `recalcular_lead`),
   así una empresa que ya estaba no se duplica ni pierde su histórico.

Lo que se descarta acá y no en el scoring: consultoras de selección (son
competencia, no clientes) y avisos perennes tipo «Postulación espontánea», que
nunca se cierran y por eso acumulan días para siempre. El scoring ya los hunde,
pero conviene no ensuciar la base de entrada.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .ingest.base import VacanteCruda
from .ingest.portales import Segmento, buscar_en_portales
from .models import Empresa, Lead
from .normalize import es_aviso_perenne, es_competencia
from .services import (
    asegurar_lead,
    fecha_hoy,
    perfil,
    recalcular_lead,
    upsert_empresa,
    upsert_vacante,
)

log = logging.getLogger("talanton.busqueda")

# Motivos de descarte, en castellano, para poder contarlos y mostrarlos: si una
# búsqueda trae 40 avisos y entran 6, hay que poder explicar dónde fueron los 34.
DESCARTE_COMPETENCIA = "consultoras de selección"
DESCARTE_PERENNE = "avisos que nunca se cierran"
DESCARTE_SIN_EMPRESA = "avisos sin nombre de empresa"


@dataclass
class Hallazgo:
    """Un aviso encontrado, todavía sin guardar."""

    empresa: str
    titulo: str
    portal: str
    url: str | None = None
    ubicacion: str | None = None
    dias_abierto: int | None = None
    fecha_aproximada: bool = False
    # True si esa empresa ya está en la base: no es un descubrimiento, pero el
    # aviso puede ser nuevo y vale la pena traerlo igual.
    ya_estaba: bool = False
    cruda: VacanteCruda | None = None

    @property
    def antiguedad_texto(self) -> str:
        if self.dias_abierto is None:
            return "sin fecha"
        prefijo = "~" if self.fecha_aproximada else ""
        if self.dias_abierto == 0:
            return "publicado hoy"
        return f"{prefijo}{self.dias_abierto} día{'s' if self.dias_abierto != 1 else ''}"

    @property
    def payload(self) -> dict:
        """Lo mínimo para reconstruir el aviso en el POST siguiente.

        La pantalla explora primero y guarda después, en dos pedidos distintos.
        Volver a consultar los portales para guardar sería pagar dos veces lo
        más caro y —peor— arriesgarse a guardar algo distinto de lo que el
        usuario vio y eligió. Así viaja en el formulario.
        """
        c = self.cruda
        return {
            "e": self.empresa,
            "t": self.titulo,
            "f": self.portal,
            "i": c.external_id if c else "",
            "u": self.url,
            "l": self.ubicacion,
            "d": c.fecha_publicacion.isoformat() if c and c.fecha_publicacion else None,
            "a": self.fecha_aproximada,
        }


def hallazgo_desde_payload(datos: dict) -> Hallazgo | None:
    """Rehace un `Hallazgo` a partir de lo que mandó el formulario.

    Viene del navegador, así que se valida: sin empresa, título o identificador
    no se guarda nada.
    """
    from datetime import date

    empresa = (datos.get("e") or "").strip()
    titulo = (datos.get("t") or "").strip()
    fuente = (datos.get("f") or "").strip()
    external_id = (datos.get("i") or "").strip()
    if not empresa or not titulo or not fuente or not external_id:
        return None

    publicada = None
    if datos.get("d"):
        try:
            publicada = date.fromisoformat(str(datos["d"]))
        except ValueError:
            publicada = None

    cruda = VacanteCruda(
        empresa=empresa,
        titulo=titulo,
        fuente=fuente,
        external_id=external_id,
        fuente_url=datos.get("u") or None,
        ubicacion=datos.get("l") or None,
        pais="AR",
        fecha_publicacion=publicada,
        fecha_aproximada=bool(datos.get("a")),
    )
    # Se vuelve a filtrar: el payload viene del navegador y podría traer algo
    # que en la exploración se había descartado.
    if _descartar(cruda):
        return None

    dias = (fecha_hoy() - publicada).days if publicada else None
    return Hallazgo(
        empresa=empresa,
        titulo=titulo,
        portal=fuente,
        url=cruda.fuente_url,
        ubicacion=cruda.ubicacion,
        dias_abierto=dias,
        fecha_aproximada=cruda.fecha_aproximada,
        cruda=cruda,
    )


@dataclass
class Exploracion:
    hallazgos: list[Hallazgo] = field(default_factory=list)
    por_portal: dict[str, int] = field(default_factory=dict)
    descartes: dict[str, int] = field(default_factory=dict)
    fallidos: list[str] = field(default_factory=list)

    @property
    def empresas(self) -> int:
        return len({h.empresa.strip().lower() for h in self.hallazgos})

    @property
    def nuevas(self) -> int:
        return len(
            {h.empresa.strip().lower() for h in self.hallazgos if not h.ya_estaba}
        )


@dataclass
class Traida:
    """Qué quedó guardado después de traer los hallazgos."""

    empresas_nuevas: int = 0
    empresas_actualizadas: int = 0
    vacantes_nuevas: int = 0
    vacantes_repetidas: int = 0
    leads: list[Lead] = field(default_factory=list)


def _descartar(cruda: VacanteCruda) -> str | None:
    """Devuelve el motivo de descarte, o None si el aviso sirve."""
    if not (cruda.empresa or "").strip():
        return DESCARTE_SIN_EMPRESA
    if es_competencia(cruda.empresa, cruda.empresa_industria):
        return DESCARTE_COMPETENCIA
    if es_aviso_perenne(cruda.titulo, cruda.descripcion):
        return DESCARTE_PERENNE
    return None


def explorar(
    session: Session,
    segmento: Segmento,
    *,
    portales=None,
) -> Exploracion:
    """Consulta los portales y arma la lista para revisar. No escribe nada."""
    resultado = buscar_en_portales(segmento, portales)
    exploracion = Exploracion(
        por_portal=dict(resultado.por_portal), fallidos=list(resultado.fallidos)
    )

    hoy = fecha_hoy()
    conocidas = _empresas_conocidas(session)
    vistos: set[str] = set()

    for cruda in resultado.crudas:
        motivo = _descartar(cruda)
        if motivo:
            exploracion.descartes[motivo] = exploracion.descartes.get(motivo, 0) + 1
            continue
        # El mismo aviso puede venir de dos portales: se muestra una sola vez.
        clave = f"{cruda.fuente}:{cruda.external_id}"
        if clave in vistos:
            continue
        vistos.add(clave)

        dias = (
            (hoy - cruda.fecha_publicacion).days
            if cruda.fecha_publicacion is not None
            else None
        )
        exploracion.hallazgos.append(
            Hallazgo(
                empresa=cruda.empresa.strip(),
                titulo=cruda.titulo.strip(),
                portal=cruda.fuente,
                url=cruda.fuente_url,
                ubicacion=cruda.ubicacion,
                dias_abierto=dias,
                fecha_aproximada=cruda.fecha_aproximada,
                ya_estaba=_clave(cruda.empresa) in conocidas,
                cruda=cruda,
            )
        )

    # Lo más viejo primero: un aviso de 90 días es una búsqueda que la empresa
    # no está pudiendo cerrar sola, y ése es exactamente el lead que sirve.
    exploracion.hallazgos.sort(key=lambda h: (h.dias_abierto is None, -(h.dias_abierto or 0)))
    return exploracion


def traer(session: Session, hallazgos: list[Hallazgo]) -> Traida:
    """Guarda los hallazgos como empresas + vacantes + leads puntuados."""
    traida = Traida()
    p = perfil(session)
    tocadas: dict[int, Empresa] = {}

    for hallazgo in hallazgos:
        cruda = hallazgo.cruda
        if cruda is None:
            continue

        existia = _clave(cruda.empresa) in _empresas_conocidas(session)
        empresa = upsert_empresa(
            session,
            cruda.empresa,
            dominio=cruda.empresa_dominio,
            pais=cruda.pais or "AR",
            ciudad=cruda.ubicacion,
            industria=cruda.empresa_industria,
            dotacion_estimada=cruda.empresa_dotacion,
        )
        session.flush()
        if existia:
            traida.empresas_actualizadas += 1
        else:
            traida.empresas_nuevas += 1

        _, es_nueva = upsert_vacante(
            session,
            empresa,
            titulo=cruda.titulo,
            fuente=cruda.fuente,
            external_id=cruda.external_id,
            fuente_url=cruda.fuente_url,
            ubicacion=cruda.ubicacion,
            pais=cruda.pais or "AR",
            descripcion=cruda.descripcion,
            fecha_publicacion=cruda.fecha_publicacion,
            fecha_aproximada=cruda.fecha_aproximada,
        )
        if es_nueva:
            traida.vacantes_nuevas += 1
        else:
            traida.vacantes_repetidas += 1
        tocadas[empresa.id] = empresa

    session.flush()
    for empresa in tocadas.values():
        session.refresh(empresa)
        lead = asegurar_lead(session, empresa)
        recalcular_lead(session, lead, p)
        traida.leads.append(lead)

    # Mejor score arriba: es el orden en que conviene trabajarlos.
    traida.leads.sort(key=lambda lead: lead.score, reverse=True)
    return traida


def _clave(nombre: str) -> str:
    from .normalize import normalizar_nombre_empresa

    return normalizar_nombre_empresa(nombre)


def _empresas_conocidas(session: Session) -> set[str]:
    from sqlalchemy import select

    return set(session.scalars(select(Empresa.nombre_normalizado)).all())

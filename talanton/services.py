"""Operaciones de dominio sobre la base: upserts, recálculo de scores, kanban."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from . import normalize, scoring
from .models import (
    Actividad,
    CorridaIngesta,
    Empresa,
    EstadoLead,
    Lead,
    PerfilConsultora,
    Seniority,
    Vacante,
    ahora,
)


def perfil(session: Session) -> PerfilConsultora:
    p = session.scalar(select(PerfilConsultora).limit(1))
    if p is None:
        p = PerfilConsultora()
        session.add(p)
        session.flush()
    return p


# --- Empresas ----------------------------------------------------------------


def upsert_empresa(
    session: Session,
    nombre: str,
    *,
    dominio: str | None = None,
    pais: str | None = None,
    ciudad: str | None = None,
    industria: str | None = None,
    dotacion_estimada: int | None = None,
    sitio_web: str | None = None,
    linkedin_url: str | None = None,
) -> Empresa:
    """Busca por dominio y, si no hay, por nombre normalizado. Nunca duplica."""
    nombre_norm, dominio_norm = normalize.clave_empresa(nombre, dominio or sitio_web)

    empresa: Empresa | None = None
    if dominio_norm:
        empresa = session.scalar(select(Empresa).where(Empresa.dominio == dominio_norm))
    if empresa is None:
        empresa = session.scalar(
            select(Empresa).where(Empresa.nombre_normalizado == nombre_norm)
        )

    if empresa is None:
        empresa = Empresa(nombre=nombre.strip(), nombre_normalizado=nombre_norm)
        session.add(empresa)

    # Sólo completamos huecos: no pisamos datos ya curados a mano.
    if dominio_norm and not empresa.dominio:
        empresa.dominio = dominio_norm
    for campo, valor in (
        ("pais", pais),
        ("ciudad", ciudad),
        ("industria", industria),
        ("dotacion_estimada", dotacion_estimada),
        ("sitio_web", sitio_web),
        ("linkedin_url", linkedin_url),
    ):
        if valor is not None and getattr(empresa, campo) in (None, ""):
            setattr(empresa, campo, valor)

    session.flush()
    return empresa


# --- Vacantes ----------------------------------------------------------------


def upsert_vacante(
    session: Session,
    empresa: Empresa,
    *,
    titulo: str,
    fuente: str,
    external_id: str,
    fuente_url: str | None = None,
    ubicacion: str | None = None,
    pais: str | None = None,
    modalidad: str | None = None,
    descripcion: str | None = None,
    fecha_publicacion: date | None = None,
    vista_el: date | None = None,
) -> tuple[Vacante, bool]:
    """Registra una observación de la vacante. Devuelve (vacante, es_nueva).

    Nunca pisa `primera_vez_vista`: ese dato es el que permite calcular días
    abiertos, y es exactamente lo que ningún competidor puede improvisar.
    Si la vacante estaba cerrada y reaparece, cuenta como reposteo.
    """
    hoy = vista_el or ahora().date()
    vacante = session.scalar(
        select(Vacante).where(Vacante.fuente == fuente, Vacante.external_id == external_id)
    )
    es_nueva = vacante is None

    if vacante is None:
        vacante = Vacante(
            empresa_id=empresa.id,
            titulo=titulo.strip(),
            rol_normalizado=normalize.normalizar_rol(titulo),
            seniority=normalize.detectar_seniority(titulo),
            fuente=fuente,
            external_id=external_id,
            primera_vez_vista=fecha_publicacion or hoy,
        )
        session.add(vacante)
    elif vacante.cerrada:
        # Reapareció: la habían dado de baja y la volvieron a publicar.
        vacante.cerrada = False
        vacante.fecha_cierre = None
        vacante.reposteos += 1

    vacante.ultima_vez_vista = hoy
    vacante.titulo = titulo.strip()
    vacante.rol_normalizado = normalize.normalizar_rol(titulo)
    vacante.seniority = normalize.detectar_seniority(titulo)
    vacante.fuente_url = fuente_url or vacante.fuente_url
    vacante.ubicacion = ubicacion or vacante.ubicacion
    vacante.pais = pais or vacante.pais or empresa.pais
    vacante.modalidad = modalidad or vacante.modalidad
    vacante.descripcion = descripcion or vacante.descripcion
    if fecha_publicacion and not vacante.fecha_publicacion:
        vacante.fecha_publicacion = fecha_publicacion
    vacante.publicada_por_consultora = normalize.publicado_por_consultora(
        empresa.nombre, descripcion
    )

    session.flush()
    return vacante, es_nueva


def cerrar_vacantes_no_vistas(session: Session, fuente: str, corrida: date) -> int:
    """Un aviso que desapareció de la fuente es una búsqueda cerrada.

    Modelar el cierre importa tanto como la apertura: sin esto el sistema
    termina llamando a empresas que ya contrataron.
    """
    vacantes = session.scalars(
        select(Vacante).where(
            Vacante.fuente == fuente,
            Vacante.cerrada.is_(False),
            Vacante.ultima_vez_vista < corrida,
        )
    ).all()
    for v in vacantes:
        v.cerrada = True
        v.fecha_cierre = corrida
    session.flush()
    return len(vacantes)


# --- Leads -------------------------------------------------------------------


def _siguiente_orden(session: Session, estado: EstadoLead) -> int:
    maximo = session.scalar(select(func.max(Lead.orden)).where(Lead.estado == estado))
    return (maximo or 0) + 1


def asegurar_lead(session: Session, empresa: Empresa) -> Lead:
    lead = session.scalar(select(Lead).where(Lead.empresa_id == empresa.id))
    if lead is None:
        lead = Lead(empresa_id=empresa.id, orden=_siguiente_orden(session, EstadoLead.NUEVO))
        session.add(lead)
        session.flush()
    return lead


def recalcular_lead(session: Session, lead: Lead, p: PerfilConsultora | None = None) -> Lead:
    p = p or perfil(session)
    resultado = scoring.calcular(lead.empresa, p)
    lead.score = resultado.total
    lead.score_urgencia = resultado.urgencia
    lead.score_fit = resultado.fit
    lead.score_accesibilidad = resultado.accesibilidad
    lead.score_pago = resultado.pago
    lead.razones = resultado.razones_texto
    lead.gancho = resultado.gancho
    session.flush()
    return lead


def recalcular_todos(session: Session) -> int:
    p = perfil(session)
    leads = session.scalars(
        select(Lead).options(
            selectinload(Lead.empresa).selectinload(Empresa.vacantes),
            selectinload(Lead.empresa).selectinload(Empresa.contactos),
        )
    ).all()
    for lead in leads:
        recalcular_lead(session, lead, p)
    return len(leads)


def mover_lead(
    session: Session,
    lead: Lead,
    estado: EstadoLead,
    *,
    posicion: int | None = None,
    autor: str | None = None,
) -> Lead:
    anterior = lead.estado
    lead.estado = estado
    lead.orden = posicion if posicion is not None else _siguiente_orden(session, estado)
    lead.actualizado_en = ahora()
    if estado != EstadoLead.NUEVO and anterior == EstadoLead.NUEVO:
        lead.ultimo_contacto_en = ahora()
    if anterior != estado:
        session.add(
            Actividad(
                lead_id=lead.id,
                tipo="cambio_estado",
                detalle=f"{anterior.etiqueta} → {estado.etiqueta}",
                autor=autor,
            )
        )
    session.flush()
    return lead


def registrar_actividad(
    session: Session, lead: Lead, detalle: str, *, tipo: str = "nota", autor: str | None = None
) -> Actividad:
    actividad = Actividad(lead_id=lead.id, tipo=tipo, detalle=detalle, autor=autor)
    session.add(actividad)
    if tipo in ("contacto", "nota"):
        lead.ultimo_contacto_en = ahora()
    lead.actualizado_en = ahora()
    session.flush()
    return actividad


# --- Consultas para la web ---------------------------------------------------


def listar_leads(
    session: Session,
    *,
    q: str | None = None,
    estado: EstadoLead | None = None,
    score_min: float | None = None,
    pais: str | None = None,
    orden: str = "score",
) -> list[Lead]:
    consulta = (
        select(Lead)
        .join(Empresa)
        .options(
            selectinload(Lead.empresa).selectinload(Empresa.vacantes),
            selectinload(Lead.empresa).selectinload(Empresa.contactos),
        )
    )
    if q:
        patron = f"%{q.lower()}%"
        consulta = consulta.where(
            or_(
                func.lower(Empresa.nombre).like(patron),
                func.lower(Empresa.industria).like(patron),
                func.lower(Empresa.dominio).like(patron),
            )
        )
    if estado:
        consulta = consulta.where(Lead.estado == estado)
    if score_min is not None:
        consulta = consulta.where(Lead.score >= score_min)
    if pais:
        consulta = consulta.where(Empresa.pais == pais)

    if orden == "nombre":
        consulta = consulta.order_by(Empresa.nombre)
    elif orden == "reciente":
        consulta = consulta.order_by(Lead.actualizado_en.desc())
    else:
        consulta = consulta.order_by(Lead.score.desc())
    return list(session.scalars(consulta).all())


def tablero(session: Session) -> dict[EstadoLead, list[Lead]]:
    leads = session.scalars(
        select(Lead)
        .options(selectinload(Lead.empresa).selectinload(Empresa.vacantes))
        .order_by(Lead.orden, Lead.score.desc())
    ).all()
    columnas: dict[EstadoLead, list[Lead]] = {e: [] for e in EstadoLead}
    for lead in leads:
        columnas[lead.estado].append(lead)
    return columnas


def listar_vacantes(
    session: Session,
    *,
    q: str | None = None,
    solo_abiertas: bool = True,
    solo_urgentes: bool = False,
    pais: str | None = None,
    seniority: Seniority | None = None,
) -> list[Vacante]:
    consulta = select(Vacante).join(Empresa).options(selectinload(Vacante.empresa))
    if solo_abiertas:
        consulta = consulta.where(Vacante.cerrada.is_(False))
    if q:
        patron = f"%{q.lower()}%"
        consulta = consulta.where(
            or_(
                func.lower(Vacante.titulo).like(patron),
                func.lower(Empresa.nombre).like(patron),
            )
        )
    if pais:
        consulta = consulta.where(Vacante.pais == pais)
    if seniority:
        consulta = consulta.where(Vacante.seniority == seniority)

    vacantes = list(session.scalars(consulta).all())
    if solo_urgentes:
        vacantes = [v for v in vacantes if v.es_urgente]
    vacantes.sort(key=lambda v: v.dias_abierta, reverse=True)
    return vacantes


def metricas(session: Session) -> dict:
    total_leads = session.scalar(select(func.count()).select_from(Lead)) or 0
    abiertas = session.scalar(
        select(func.count()).select_from(Vacante).where(Vacante.cerrada.is_(False))
    ) or 0
    empresas = session.scalar(select(func.count()).select_from(Empresa)) or 0
    calientes = session.scalar(
        select(func.count()).select_from(Lead).where(Lead.score >= 70)
    ) or 0
    ganados = session.scalar(
        select(func.count()).select_from(Lead).where(Lead.estado == EstadoLead.GANADO)
    ) or 0
    en_curso = session.scalar(
        select(func.count())
        .select_from(Lead)
        .where(Lead.estado.notin_([EstadoLead.NUEVO, EstadoLead.GANADO, EstadoLead.PERDIDO]))
    ) or 0
    urgentes = len(
        [
            v
            for v in session.scalars(select(Vacante).where(Vacante.cerrada.is_(False))).all()
            if v.es_urgente
        ]
    )
    return {
        "leads": total_leads,
        "empresas": empresas,
        "vacantes_abiertas": abiertas,
        "vacantes_urgentes": urgentes,
        "leads_calientes": calientes,
        "leads_en_curso": en_curso,
        "leads_ganados": ganados,
    }


def fecha_hoy() -> date:
    return datetime.now(timezone.utc).date()


def ultima_corrida(session: Session) -> CorridaIngesta | None:
    return session.scalar(
        select(CorridaIngesta).order_by(CorridaIngesta.iniciada_en.desc()).limit(1)
    )


def estado_ingesta(session: Session) -> dict:
    """Resume si la ingesta está trayendo datos, para mostrarlo en el panel.

    El caso que importa detectar es el silencioso: el cron corre todos los
    días, no falla, y no trae nada porque las fuentes están mal configuradas.
    Desde afuera se ve igual que un día sin novedades.
    """
    corrida = ultima_corrida(session)
    if corrida is None:
        return {
            "estado": "nunca",
            "mensaje": "La ingesta todavía no corrió nunca.",
            "corrida": None,
            "horas": None,
        }

    referencia = corrida.terminada_en or corrida.iniciada_en
    horas = (ahora() - referencia.replace(tzinfo=timezone.utc)).total_seconds() / 3600

    if corrida.fuentes_con_error and not corrida.fuentes_ok:
        estado, mensaje = "error", "Todas las fuentes fallaron en la última corrida."
    elif corrida.sin_resultados:
        estado, mensaje = "vacia", "La última corrida no encontró ningún aviso."
    elif corrida.fuentes_con_error:
        estado = "parcial"
        mensaje = f"{corrida.fuentes_con_error} fuente(s) fallaron en la última corrida."
    elif horas > 36:
        estado, mensaje = "atrasada", "Hace más de un día y medio que no corre la ingesta."
    else:
        estado, mensaje = "ok", "La ingesta está trayendo datos."

    return {"estado": estado, "mensaje": mensaje, "corrida": corrida, "horas": horas}

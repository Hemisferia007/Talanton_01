"""Mini-CRM de Talanton: dashboard, leads, avisos y tablero kanban."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import services
from ..config import PAISES, PAIS_NOMBRE, SCORE_MINIMO_ALERTA
from ..db import db_dependency, init_db
from ..models import (
    ESTADOS_KANBAN,
    Empresa,
    EstadoLead,
    Lead,
    Seniority,
)

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="Talanton CRM", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


def _contexto(request: Request, **extra):
    base = {
        "request": request,
        "estados": ESTADOS_KANBAN,
        "paises": PAISES,
        "pais_nombre": PAIS_NOMBRE,
        "score_minimo": SCORE_MINIMO_ALERTA,
    }
    base.update(extra)
    return base


def _lead_o_404(session: Session, lead_id: int) -> Lead:
    lead = session.scalar(
        select(Lead)
        .where(Lead.id == lead_id)
        .options(
            selectinload(Lead.empresa).selectinload(Empresa.vacantes),
            selectinload(Lead.empresa).selectinload(Empresa.contactos),
            selectinload(Lead.actividades),
        )
    )
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    return lead


# --- Dashboard ---------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(db_dependency)):
    metricas = services.metricas(db)
    prioritarios = [
        lead
        for lead in services.listar_leads(db, score_min=SCORE_MINIMO_ALERTA)
        if lead.estado == EstadoLead.NUEVO
    ][:8]
    urgentes = services.listar_vacantes(db, solo_urgentes=True)[:8]
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        _contexto(
            request,
            perfil=services.perfil(db),
            metricas=metricas,
            prioritarios=prioritarios,
            urgentes=urgentes,
        ),
    )


# --- Leads -------------------------------------------------------------------


@app.get("/leads", response_class=HTMLResponse)
def leads(
    request: Request,
    q: str | None = None,
    estado: str | None = None,
    score_min: float | None = None,
    pais: str | None = None,
    orden: str = "score",
    db: Session = Depends(db_dependency),
):
    estado_enum = EstadoLead(estado) if estado else None
    resultados = services.listar_leads(
        db, q=q, estado=estado_enum, score_min=score_min, pais=pais, orden=orden
    )
    return templates.TemplateResponse(
        request,
        "leads.html",
        _contexto(
            request,
            leads=resultados,
            filtros={
                "q": q or "",
                "estado": estado or "",
                "score_min": score_min or "",
                "pais": pais or "",
                "orden": orden,
            },
        ),
    )


@app.get("/leads/{lead_id}", response_class=HTMLResponse)
def lead_detalle(request: Request, lead_id: int, db: Session = Depends(db_dependency)):
    lead = _lead_o_404(db, lead_id)
    vacantes = sorted(lead.empresa.vacantes, key=lambda v: (v.cerrada, -v.dias_abierta))
    return templates.TemplateResponse(
        request, "lead_detalle.html", _contexto(request, lead=lead, vacantes=vacantes)
    )


@app.post("/leads/{lead_id}/nota")
def agregar_nota(
    lead_id: int,
    detalle: str = Form(...),
    tipo: str = Form("nota"),
    db: Session = Depends(db_dependency),
):
    lead = _lead_o_404(db, lead_id)
    if detalle.strip():
        services.registrar_actividad(db, lead, detalle.strip(), tipo=tipo)
        db.commit()
    return RedirectResponse(f"/leads/{lead_id}", status_code=303)


@app.post("/leads/{lead_id}/estado")
def cambiar_estado(
    lead_id: int,
    estado: str = Form(...),
    proximo_paso: str | None = Form(None),
    responsable: str | None = Form(None),
    motivo_perdida: str | None = Form(None),
    db: Session = Depends(db_dependency),
):
    lead = _lead_o_404(db, lead_id)
    services.mover_lead(db, lead, EstadoLead(estado))
    lead.proximo_paso = (proximo_paso or "").strip() or None
    lead.responsable = (responsable or "").strip() or None
    lead.motivo_perdida = (motivo_perdida or "").strip() or None
    db.commit()
    return RedirectResponse(f"/leads/{lead_id}", status_code=303)


# --- Tablero kanban ----------------------------------------------------------


@app.get("/tablero", response_class=HTMLResponse)
def tablero(request: Request, db: Session = Depends(db_dependency)):
    columnas = services.tablero(db)
    return templates.TemplateResponse(
        request, "tablero.html", _contexto(request, columnas=columnas)
    )


@app.post("/api/leads/{lead_id}/mover")
async def mover(lead_id: int, request: Request, db: Session = Depends(db_dependency)):
    """Endpoint del drag & drop del kanban."""
    payload = await request.json()
    try:
        estado = EstadoLead(payload["estado"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=400, detail="Estado inválido")

    lead = _lead_o_404(db, lead_id)
    services.mover_lead(db, lead, estado, posicion=payload.get("posicion"))
    db.commit()
    return JSONResponse({"ok": True, "estado": estado.value, "etiqueta": estado.etiqueta})


# --- Avisos ------------------------------------------------------------------


@app.get("/avisos", response_class=HTMLResponse)
def avisos(
    request: Request,
    q: str | None = None,
    estado_aviso: str = "abiertas",
    pais: str | None = None,
    seniority: str | None = None,
    db: Session = Depends(db_dependency),
):
    vacantes = services.listar_vacantes(
        db,
        q=q,
        solo_abiertas=estado_aviso != "todas",
        solo_urgentes=estado_aviso == "urgentes",
        pais=pais,
        seniority=Seniority(seniority) if seniority else None,
    )
    return templates.TemplateResponse(
        request,
        "avisos.html",
        _contexto(
            request,
            vacantes=vacantes,
            seniorities=list(Seniority),
            filtros={
                "q": q or "",
                "estado_aviso": estado_aviso,
                "pais": pais or "",
                "seniority": seniority or "",
            },
        ),
    )


# --- Mi empresa --------------------------------------------------------------


@app.get("/mi-empresa", response_class=HTMLResponse)
def mi_empresa(request: Request, db: Session = Depends(db_dependency)):
    return templates.TemplateResponse(
        request,
        "mi_empresa.html",
        _contexto(
            request,
            perfil=services.perfil(db),
            metricas=services.metricas(db),
            seniorities=list(Seniority),
        ),
    )


@app.post("/mi-empresa")
def guardar_mi_empresa(
    nombre: str = Form(...),
    descripcion: str = Form(""),
    sitio_web: str = Form(""),
    email_contacto: str = Form(""),
    industrias_objetivo: str = Form(""),
    paises_objetivo: str = Form(""),
    dotacion_min: int = Form(20),
    dotacion_max: int = Form(2000),
    seniorities_objetivo: str = Form(""),
    fee_promedio: str = Form(""),
    db: Session = Depends(db_dependency),
):
    p = services.perfil(db)
    p.nombre = nombre.strip() or "Talanton"
    p.descripcion = descripcion.strip() or None
    p.sitio_web = sitio_web.strip() or None
    p.email_contacto = email_contacto.strip() or None
    p.industrias_objetivo = industrias_objetivo.strip()
    p.paises_objetivo = paises_objetivo.strip()
    p.dotacion_min = dotacion_min
    p.dotacion_max = dotacion_max
    p.seniorities_objetivo = seniorities_objetivo.strip()
    p.fee_promedio = int(fee_promedio) if fee_promedio.strip().isdigit() else None
    db.commit()
    # El ICP alimenta el eje de fit: si cambia, todos los scores cambian.
    services.recalcular_todos(db)
    db.commit()
    return RedirectResponse("/mi-empresa", status_code=303)


@app.post("/recalcular")
def recalcular(db: Session = Depends(db_dependency)):
    services.recalcular_todos(db)
    db.commit()
    return RedirectResponse("/", status_code=303)

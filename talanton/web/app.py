"""Mini-CRM de Talanton: dashboard, leads, avisos y tablero kanban."""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from starlette.middleware.sessions import SessionMiddleware

from .. import auth, services
from ..apollo import busqueda as apollo_busqueda
from ..apollo import cliente as apollo_cliente
from ..apollo import industrias as apollo_industrias
from ..apollo.cliente import ErrorApollo
from ..asistente import conviene as ia_conviene
from ..asistente import escribir as ia_escribir
from ..asistente.cliente import ErrorAsistente, disponible as asistente_disponible
from ..config import (
    COOKIES_SEGURAS,
    apify_configurado,
    apollo_configurado,
    LIMITE_ENVIOS_DIARIOS,
    PAISES,
    PAIS_NOMBRE,
    SCORE_MINIMO_ALERTA,
    SESSION_MAX_AGE,
    gmail_configurado,
    secreto_de_sesion,
    verificar_configuracion_de_produccion,
)
from ..correo import servicio as correo
from ..correo import gmail as api_gmail
from ..enriquecer import objetivo_para
from ..ingest import fuentes as fuentes_db
from ..db import db_dependency, init_db
from ..models import (
    ESTADOS_KANBAN,
    CuentaGmail,
    Empresa,
    EstadoLead,
    Evento,
    Fuente,
    Lead,
    Objetivo,
    Seniority,
    Usuario,
)

log_web = logging.getLogger("talanton.web")

COOKIE_ESTADO_OAUTH = "talanton_oauth_state"

# Lo único accesible sin sesión. Todo lo demás pasa por el middleware, así una
# ruta nueva queda protegida por omisión en vez de por acordarse.
RUTAS_PUBLICAS = ("/login", "/static", "/salud")

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Antes de aceptar tráfico: si falta un secreto de producción, que el
    # deploy falle acá y no en silencio semanas después.
    verificar_configuracion_de_produccion()
    init_db()
    yield


app = FastAPI(title="Talanton CRM", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


@app.middleware("http")
async def exigir_sesion(request: Request, call_next):
    if request.url.path.startswith(RUTAS_PUBLICAS):
        return await call_next(request)

    usuario = _usuario_de_sesion(request)
    if usuario is None:
        request.session.clear()
        # Las llamadas de la interfaz esperan JSON; devolverles el HTML del
        # login las haría fallar de forma confusa.
        if request.url.path.startswith("/api/"):
            return JSONResponse({"error": "Sesión expirada"}, status_code=401)
        from urllib.parse import quote

        destino = quote(request.url.path)
        return RedirectResponse(f"/login?siguiente={destino}", status_code=303)

    # Queda disponible para las plantillas sin repetir la consulta en cada ruta.
    request.state.usuario = usuario
    return await call_next(request)


# Se agrega DESPUÉS de exigir_sesion a propósito: en Starlette el último
# middleware registrado queda por fuera, y exigir_sesion necesita que
# request.session ya exista cuando corre.
app.add_middleware(
    SessionMiddleware,
    secret_key=secreto_de_sesion(),
    max_age=SESSION_MAX_AGE,
    same_site="lax",  # sobrevive la vuelta de Google en el OAuth
    https_only=COOKIES_SEGURAS,
)


def _usuario_de_sesion(request: Request) -> Usuario | None:
    """Resuelve el usuario de la cookie. Un usuario dado de baja pierde la
    sesión de inmediato, sin esperar a que la cookie venza."""
    uid = request.session.get("usuario_id")
    if not uid:
        return None
    from ..db import SessionLocal

    with SessionLocal() as db:
        usuario = db.get(Usuario, uid)
        return usuario if usuario and usuario.activo else None


# --- Login -------------------------------------------------------------------


@app.get("/salud")
def salud():
    """Para el health check del hosting."""
    return {"ok": True}


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, siguiente: str = "/", db: Session = Depends(db_dependency)):
    if request.session.get("usuario_id"):
        return RedirectResponse(siguiente, status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "siguiente": siguiente,
            "sin_usuarios": not auth.hay_usuarios(db),
            "error": None,
        },
    )


@app.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    siguiente: str = Form("/"),
    db: Session = Depends(db_dependency),
):
    usuario = auth.autenticar(db, email, password)
    if usuario is None:
        db.commit()
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "request": request,
                "siguiente": siguiente,
                "sin_usuarios": not auth.hay_usuarios(db),
                "error": "Email o contraseña incorrectos.",
            },
            status_code=401,
        )

    db.commit()
    # Sesión nueva al iniciar: evita fijación de sesión.
    request.session.clear()
    request.session["usuario_id"] = usuario.id
    # Sólo rutas internas: un "siguiente" con URL absoluta sería un redirect abierto.
    destino = siguiente if siguiente.startswith("/") and not siguiente.startswith("//") else "/"
    return RedirectResponse(destino, status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


def _contexto(request: Request, **extra):
    base = {
        "request": request,
        "usuario": getattr(request.state, "usuario", None),
        "estados": ESTADOS_KANBAN,
        "paises": PAISES,
        "pais_nombre": PAIS_NOMBRE,
        "score_minimo": SCORE_MINIMO_ALERTA,
        # Opciones ya armadas para los <select>: la plantilla no debería tener
        # que zipear listas para pintar un filtro.
        "opciones_estado": [("", "Todos")] + [(e.value, e.etiqueta) for e in ESTADOS_KANBAN],
        "opciones_pais": [("", "Todos")] + [(p, PAIS_NOMBRE[p]) for p in PAISES],
        "opciones_seniority": [("", "Todos")] + [(s.value, s.etiqueta) for s in Seniority],
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
            ingesta=services.estado_ingesta(db),
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
    cuentas = correo.listar_cuentas(db)
    return templates.TemplateResponse(
        request,
        "lead_detalle.html",
        _contexto(
            request,
            lead=lead,
            vacantes=vacantes,
            cuentas=cuentas,
            objetivo=objetivo_para(lead.empresa),
            # El borrador se arma acá para que el diálogo abra ya escrito, sin
            # esperar una llamada al servidor.
            redaccion=correo.borrador(db, lead, cuenta=cuentas[0] if cuentas else None),
            gmail_listo=gmail_configurado(),
            asistente_listo=asistente_disponible(),
            # Una opinión guardada contra un lead que ya cambió es peor que
            # ninguna: se muestra igual, pero avisada.
            opinion_vieja=ia_conviene.desactualizada(lead),
            enviado=request.query_params.get("enviado"),
            error_envio=request.query_params.get("error"),
        ),
    )


@app.post("/leads/{lead_id}/opinion")
def pedir_opinion(lead_id: int, db: Session = Depends(db_dependency)):
    """Le pide al asistente que lea el lead y diga si conviene contactarlo."""
    lead = _lead_o_404(db, lead_id)
    try:
        ia_conviene.evaluar(db, lead)
        db.commit()
    except ErrorAsistente as exc:
        from urllib.parse import quote

        return RedirectResponse(f"/leads/{lead_id}?error={quote(str(exc))}", status_code=303)
    return RedirectResponse(f"/leads/{lead_id}#t-opinion", status_code=303)


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


# --- Importar ----------------------------------------------------------------


@app.get("/importar", response_class=HTMLResponse)
def importar_form(request: Request):
    return templates.TemplateResponse(
        request,
        "importar.html",
        _contexto(request, previsualizacion=None, resultado=None, error=None, datos=""),
    )


@app.post("/importar", response_class=HTMLResponse)
def importar_lista(
    request: Request,
    datos: str = Form(...),
    pais: str = Form("AR"),
    accion: str = Form("previsualizar"),
    vigilar: str | None = Form(None),
    db: Session = Depends(db_dependency),
):
    """Previsualiza o importa. Nunca se carga a ciegas: primero se muestra cómo
    quedaron las columnas, porque una lista mal alineada ensucia toda la base."""
    from .. import importar as mod_importar

    analisis = mod_importar.analizar(datos)
    if not analisis.filas:
        return templates.TemplateResponse(
            request,
            "importar.html",
            _contexto(
                request,
                previsualizacion=analisis,
                resultado=None,
                datos=datos,
                error=(
                    analisis.ignoradas[0]
                    if analisis.ignoradas
                    else "No se reconoció ninguna fila."
                ),
            ),
        )

    if accion != "importar":
        return templates.TemplateResponse(
            request,
            "importar.html",
            _contexto(
                request, previsualizacion=analisis, resultado=None, datos=datos, error=None
            ),
        )

    resultado = mod_importar.importar(
        db, analisis.filas, pais=pais, vigilar=vigilar == "1"
    )
    return templates.TemplateResponse(
        request,
        "importar.html",
        _contexto(request, previsualizacion=None, resultado=resultado, datos="", error=None),
    )


# --- Buscar en Apollo --------------------------------------------------------


def _contexto_apollo(request: Request, db: Session, **extra):
    base = dict(
        apollo_listo=apollo_configurado(),
        cargos="\n".join(apollo_busqueda.CARGOS_POR_DEFECTO),
        pais="AR",
        dotacion_min="",
        dotacion_max="",
        industrias=[],
        palabras="",
        grupos_industria=apollo_industrias.agrupadas(),
        resultado=None,
        importado=None,
        error=None,
        diagnostico=None,
    )
    base.update(extra)
    return _contexto(request, **base)


@app.get("/buscar", response_class=HTMLResponse)
def buscar_form(request: Request, db: Session = Depends(db_dependency)):
    p = services.perfil(db)
    return templates.TemplateResponse(
        request,
        "buscar.html",
        _contexto_apollo(
            request,
            db,
            # El ICP está escrito en castellano; se traduce para que quede
            # marcado lo que corresponda en la lista.
            industrias=apollo_industrias.traducir_todas(p.industrias),
            dotacion_min=p.dotacion_min or "",
            dotacion_max=p.dotacion_max or "",
        ),
    )


@app.post("/buscar", response_class=HTMLResponse)
async def buscar_en_apollo(request: Request, db: Session = Depends(db_dependency)):
    """Previsualiza. No consume créditos y los emails vienen tapados."""
    formulario = await request.form()
    cargos = str(formulario.get("cargos") or "")
    pais = str(formulario.get("pais") or "AR")
    palabras = str(formulario.get("palabras") or "")
    dotacion_min = str(formulario.get("dotacion_min") or "")
    dotacion_max = str(formulario.get("dotacion_max") or "")
    # El `<select multiple>` manda una entrada por opción elegida.
    industrias = [str(x) for x in formulario.getlist("industrias") if str(x).strip()]

    filtros = apollo_busqueda.Filtros(
        cargos=[c.strip() for c in cargos.splitlines() if c.strip()],
        pais=pais,
        industrias=industrias + [p.strip() for p in palabras.split(",") if p.strip()],
        dotacion_min=_entero_o_none(dotacion_min),
        dotacion_max=_entero_o_none(dotacion_max),
        pagina=max(1, _entero_o_none(formulario.get("pagina")) or 1),
    )
    devolver = dict(
        cargos=cargos,
        pais=pais,
        industrias=industrias,
        palabras=palabras,
        dotacion_min=dotacion_min,
        dotacion_max=dotacion_max,
    )
    try:
        resultado = apollo_busqueda.buscar(db, filtros)
    except ErrorApollo as exc:
        return templates.TemplateResponse(
            request, "buscar.html", _contexto_apollo(request, db, error=str(exc), **devolver)
        )

    return templates.TemplateResponse(
        request,
        "buscar.html",
        _contexto_apollo(request, db, resultado=resultado, **devolver),
    )


@app.post("/buscar/probar", response_class=HTMLResponse)
def probar_apollo(request: Request, db: Session = Depends(db_dependency)):
    """Muestra qué contesta Apollo, sin traducir. Para cuando el mensaje de
    error no alcanza para saber si el problema es la clave o el plan."""
    try:
        info = apollo_cliente.Cliente().diagnostico()
    except ErrorApollo as exc:
        return templates.TemplateResponse(
            request, "buscar.html", _contexto_apollo(request, db, error=str(exc))
        )
    return templates.TemplateResponse(
        request, "buscar.html", _contexto_apollo(request, db, diagnostico=info)
    )


@app.post("/buscar/importar", response_class=HTMLResponse)
async def importar_de_apollo(
    request: Request, db: Session = Depends(db_dependency)
):
    """Importa los seleccionados. **Acá sí se gastan créditos**, uno por cada
    email que haya que destapar.

    Las personas viajan en el formulario en vez de volver a consultarse: repetir
    la búsqueda podría traer otro orden y terminar importando a otra gente.
    """
    formulario = await request.form()
    pais = str(formulario.get("pais") or "AR")
    revelar = formulario.get("revelar") == "1"
    seleccionadas = formulario.getlist("persona")

    personas = []
    for crudo in seleccionadas:
        try:
            personas.append(apollo_cliente.Persona(**json.loads(crudo)))
        except (ValueError, TypeError) as exc:
            log_web.warning("Fila de Apollo ilegible: %s", exc)

    if not personas:
        return templates.TemplateResponse(
            request,
            "buscar.html",
            _contexto_apollo(request, db, error="No seleccionaste ningún contacto."),
        )

    try:
        resultado = apollo_busqueda.importar_personas(
            db, personas, pais=pais, revelar=revelar,
            vigilar=formulario.get("vigilar") == "1",
        )
    except ErrorApollo as exc:
        return templates.TemplateResponse(
            request, "buscar.html", _contexto_apollo(request, db, error=str(exc))
        )

    return templates.TemplateResponse(
        request, "buscar.html", _contexto_apollo(request, db, importado=resultado)
    )


def _entero_o_none(valor: str) -> int | None:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


# --- Fuentes -----------------------------------------------------------------


@app.get("/fuentes", response_class=HTMLResponse)
def fuentes(
    request: Request,
    mensaje: str | None = None,
    error: str | None = None,
    db: Session = Depends(db_dependency),
):
    return templates.TemplateResponse(
        request,
        "fuentes.html",
        _contexto(
            request,
            objetivos=fuentes_db.listar_objetivos(db),
            fuentes=fuentes_db.listar_fuentes(db),
            apify_listo=apify_configurado(),
            mensaje=mensaje,
            error=error,
        ),
    )


@app.post("/fuentes/objetivos")
def agregar_objetivos(lineas: str = Form(...), db: Session = Depends(db_dependency)):
    nuevos, repetidos = fuentes_db.agregar_objetivos(db, lineas)
    db.commit()

    partes = []
    if nuevos:
        partes.append(f"{nuevos} empresa{'s' if nuevos != 1 else ''} agregada{'s' if nuevos != 1 else ''}")
    if repetidos:
        partes.append(f"{repetidos} ya estaba{'n' if repetidos != 1 else ''}")
    mensaje = ". ".join(partes) or "No se agregó nada"
    if nuevos:
        mensaje += ". Presioná «Buscar» en cada una, o esperá a la corrida de mañana."
    return _volver_a_fuentes(mensaje=mensaje)


@app.post("/fuentes/objetivos/{objetivo_id}/sondear")
def sondear_objetivo(objetivo_id: int, db: Session = Depends(db_dependency)):
    """Sondeo a demanda de una empresa.

    Es sincrónico y tarda unos segundos: son varias peticiones HTTP. Se hace de
    a una a propósito, para que la pantalla no se quede colgada.
    """
    objetivo = db.get(Objetivo, objetivo_id)
    if objetivo is None:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    encontradas = fuentes_db.sondear_objetivo(db, objetivo)
    db.commit()

    if encontradas:
        return _volver_a_fuentes(
            mensaje=f"{objetivo.nombre}: {encontradas} fuente(s) encontradas. {objetivo.detalle}"
        )
    return _volver_a_fuentes(
        error=(
            f"{objetivo.nombre}: no se encontró dónde publica. "
            "Puede que use sólo portales de empleo, o que el dominio no sea el correcto."
        )
    )


@app.post("/fuentes/busquedas")
def agregar_busqueda(
    nombre: str = Form(...),
    configuracion: str = Form(...),
    db: Session = Depends(db_dependency),
):
    """Alta de una búsqueda de LinkedIn vía Apify."""
    from ..ingest.apify import ErrorApify

    try:
        nueva = fuentes_db.agregar_busqueda_linkedin(
            db, nombre=nombre, configuracion=configuracion
        )
    except ErrorApify as exc:
        return _volver_a_fuentes(error=str(exc))

    db.commit()
    if not nueva:
        return _volver_a_fuentes(error="Esa búsqueda ya estaba cargada.")
    return _volver_a_fuentes(
        mensaje=f"Búsqueda «{nombre}» agregada. Corre en la próxima ingesta diaria."
    )


@app.post("/fuentes/posts")
def agregar_busqueda_posts(
    nombre: str = Form(...),
    configuracion: str = Form(...),
    db: Session = Depends(db_dependency),
):
    from ..ingest.apify import ErrorApify

    try:
        nueva = fuentes_db.agregar_busqueda_posts(
            db, nombre=nombre, configuracion=configuracion
        )
    except ErrorApify as exc:
        return _volver_a_fuentes(error=str(exc))

    db.commit()
    if not nueva:
        return _volver_a_fuentes(error="Esa búsqueda ya estaba cargada.")
    return _volver_a_fuentes(mensaje=f"Búsqueda de señales «{nombre}» agregada.")


@app.get("/senales", response_class=HTMLResponse)
def senales(request: Request, db: Session = Depends(db_dependency)):
    """Cola de revisión de señales de financiamiento y expansión."""
    from ..ingest import eventos as eventos_db

    return templates.TemplateResponse(
        request,
        "senales.html",
        _contexto(request, eventos=eventos_db.pendientes(db)),
    )


@app.post("/senales/{evento_id}/confirmar")
def confirmar_senal(evento_id: int, db: Session = Depends(db_dependency)):
    from ..ingest import eventos as eventos_db

    evento = db.get(Evento, evento_id)
    if evento is None:
        raise HTTPException(status_code=404, detail="Señal no encontrada")
    eventos_db.confirmar(db, evento)
    return RedirectResponse("/senales", status_code=303)


@app.post("/senales/{evento_id}/descartar")
def descartar_senal(evento_id: int, db: Session = Depends(db_dependency)):
    from ..ingest import eventos as eventos_db

    evento = db.get(Evento, evento_id)
    if evento is None:
        raise HTTPException(status_code=404, detail="Señal no encontrada")
    eventos_db.descartar(db, evento)
    return RedirectResponse("/senales", status_code=303)


@app.post("/fuentes/{fuente_id}/alternar")
def alternar_fuente(fuente_id: int, db: Session = Depends(db_dependency)):
    fuente = db.get(Fuente, fuente_id)
    if fuente is None:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    fuente.activa = not fuente.activa
    db.commit()
    estado = "activada" if fuente.activa else "desactivada"
    return _volver_a_fuentes(mensaje=f"{fuente.empresa} ({fuente.tipo}) {estado}.")


def _volver_a_fuentes(mensaje: str | None = None, error: str | None = None):
    from urllib.parse import urlencode

    parametros = {k: v for k, v in (("mensaje", mensaje), ("error", error)) if v}
    destino = "/fuentes" + (f"?{urlencode(parametros)}" if parametros else "")
    return RedirectResponse(destino, status_code=303)


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
            cuentas=correo.listar_cuentas(db),
            gmail_listo=gmail_configurado(),
            limite_diario=LIMITE_ENVIOS_DIARIOS,
            enviados_hoy={c.id: correo.enviados_hoy(db, c) for c in correo.listar_cuentas(db)},
            error_oauth=request.query_params.get("error"),
            conectada=request.query_params.get("conectada"),
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


# --- Gmail: conexión de la cuenta --------------------------------------------


@app.get("/conectar-gmail")
def conectar_gmail():
    """Manda a la persona al consent screen de Google."""
    if not gmail_configurado():
        raise HTTPException(
            status_code=503,
            detail="Falta configurar las credenciales de Google. Ver docs/gmail.md.",
        )
    # El state ata la vuelta de Google a este navegador: sin esto, un tercero
    # podría inducir la conexión de una cuenta que no es la del usuario.
    estado = secrets.token_urlsafe(24)
    respuesta = RedirectResponse(api_gmail.url_de_autorizacion(estado), status_code=307)
    respuesta.set_cookie(
        COOKIE_ESTADO_OAUTH, estado, httponly=True, samesite="lax", max_age=600
    )
    return respuesta


@app.get("/oauth/google/callback")
def callback_google(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(db_dependency),
):
    esperado = request.cookies.get(COOKIE_ESTADO_OAUTH)
    if error:
        return _volver_a_mi_empresa(f"Google devolvió un error: {error}")
    if not code or not state or not esperado or not secrets.compare_digest(state, esperado):
        return _volver_a_mi_empresa("La autorización no se pudo validar. Probá de nuevo.")

    try:
        credenciales = api_gmail.canjear_codigo(code)
        correo.guardar_cuenta(db, credenciales)
        db.commit()
    except (api_gmail.ErrorGmail, correo.ErrorEnvio) as exc:
        return _volver_a_mi_empresa(str(exc))

    respuesta = _volver_a_mi_empresa(None, conectada=credenciales.email)
    respuesta.delete_cookie(COOKIE_ESTADO_OAUTH)
    return respuesta


def _volver_a_mi_empresa(error: str | None, conectada: str | None = None):
    from urllib.parse import urlencode

    parametros = {}
    if error:
        parametros["error"] = error
    if conectada:
        parametros["conectada"] = conectada
    destino = "/mi-empresa" + (f"?{urlencode(parametros)}" if parametros else "")
    return RedirectResponse(destino, status_code=303)


@app.post("/cuentas/{cuenta_id}")
def guardar_cuenta(
    cuenta_id: int,
    nombre_remitente: str = Form(""),
    firma: str = Form(""),
    db: Session = Depends(db_dependency),
):
    cuenta = db.get(CuentaGmail, cuenta_id)
    if cuenta is None:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    cuenta.nombre_remitente = nombre_remitente.strip() or None
    cuenta.firma = firma.strip() or None
    db.commit()
    return RedirectResponse("/mi-empresa", status_code=303)


@app.post("/cuentas/{cuenta_id}/desconectar")
def desconectar_cuenta(cuenta_id: int, db: Session = Depends(db_dependency)):
    cuenta = db.get(CuentaGmail, cuenta_id)
    if cuenta is None:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    correo.desconectar(db, cuenta)
    db.commit()
    return RedirectResponse("/mi-empresa", status_code=303)


# --- Redacción y envío -------------------------------------------------------


@app.get("/leads/{lead_id}/redactar")
def redactar(
    lead_id: int,
    plantilla: str | None = None,
    cuenta_id: int | None = None,
    db: Session = Depends(db_dependency),
):
    """Devuelve el borrador para una plantilla. Lo consume el diálogo al vuelo."""
    lead = _lead_o_404(db, lead_id)
    cuenta = db.get(CuentaGmail, cuenta_id) if cuenta_id else None
    datos = correo.borrador(db, lead, clave=plantilla, cuenta=cuenta)
    return JSONResponse(
        {
            "plantilla": datos["plantilla"].clave,
            "para": datos["para"],
            "asunto": datos["asunto"],
            "cuerpo": datos["cuerpo"],
        }
    )


@app.post("/leads/{lead_id}/redactar-ia")
async def redactar_con_asistente(
    lead_id: int, request: Request, db: Session = Depends(db_dependency)
):
    """Borrador escrito por el asistente leyendo el hilo entero.

    Devuelve JSON y no guarda nada: cae en la ventana de redacción para que se
    edite y se mande —o no— como cualquier otro borrador.
    """
    lead = _lead_o_404(db, lead_id)
    crudo = await request.body()
    # El campo de instrucción es opcional, así que el cuerpo también.
    datos = json.loads(crudo) if crudo.strip() else {}
    try:
        return JSONResponse(
            ia_escribir.borrador(db, lead, instruccion=(datos or {}).get("instruccion"))
        )
    except ErrorAsistente as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)


@app.post("/leads/{lead_id}/enviar")
def enviar_mail(
    lead_id: int,
    cuenta_id: int = Form(...),
    para: str = Form(...),
    asunto: str = Form(...),
    cuerpo: str = Form(...),
    plantilla: str = Form(""),
    db: Session = Depends(db_dependency),
):
    lead = _lead_o_404(db, lead_id)
    cuenta = db.get(CuentaGmail, cuenta_id)
    if cuenta is None or not cuenta.activa:
        return RedirectResponse(
            f"/leads/{lead_id}?error=La+cuenta+de+Gmail+no+está+conectada", status_code=303
        )

    try:
        correo.enviar(
            db,
            lead,
            cuenta,
            para=para,
            asunto=asunto,
            cuerpo=cuerpo,
            plantilla=plantilla or None,
        )
        db.commit()
    except correo.ErrorEnvio as exc:
        db.commit()  # el intento fallido queda registrado
        from urllib.parse import quote

        return RedirectResponse(f"/leads/{lead_id}?error={quote(str(exc))}", status_code=303)

    return RedirectResponse(f"/leads/{lead_id}?enviado=1", status_code=303)


@app.post("/leads/{lead_id}/respuesta")
def registrar_respuesta(
    lead_id: int,
    cuerpo: str = Form(...),
    de: str = Form(""),
    asunto: str = Form(""),
    db: Session = Depends(db_dependency),
):
    """Suma al hilo una respuesta que llegó a la casilla.

    Hace falta porque el permiso `gmail.send` no deja leer la casilla.
    """
    lead = _lead_o_404(db, lead_id)
    try:
        correo.registrar_respuesta(
            db, lead, cuerpo=cuerpo, de=de.strip() or None, asunto=asunto.strip() or None
        )
        db.commit()
    except correo.ErrorEnvio as exc:
        from urllib.parse import quote

        return RedirectResponse(f"/leads/{lead_id}?error={quote(str(exc))}", status_code=303)
    return RedirectResponse(f"/leads/{lead_id}", status_code=303)


@app.post("/recalcular")
def recalcular(db: Session = Depends(db_dependency)):
    services.recalcular_todos(db)
    db.commit()
    return RedirectResponse("/", status_code=303)

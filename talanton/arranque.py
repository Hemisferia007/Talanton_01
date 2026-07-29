"""El primer arranque, en un solo paso.

Todo esto ya existía repartido en cuatro pantallas: importar, dar de alta los
objetivos, sondearlos, ingerir y enriquecer. Cada una tiene sentido por
separado cuando el sistema ya está andando, pero para empezar son cuatro
pantallas en el orden correcto, y equivocarse en el orden se paga con no ver
nada y no saber por qué.

Acá va todo encadenado: pegás una lista de empresas y al terminar tenés leads
con score, avisos y contactos. Lo que no se pueda hacer hoy —una empresa sin
board público, un dominio que no resuelve— queda anotado y lo resuelve la
corrida diaria.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import importar as mod_importar
from .enriquecer import servicio as mod_enriquecer
from .ingest import fuentes as fuentes_db
from .ingest import runner
from .models import Empresa, Lead, Vacante
from .services import recalcular_todos

log = logging.getLogger("talanton.arranque")

# Sondear una empresa son varios pedidos HTTP. Con 45 y una pausa corta la
# corrida tarda unos minutos, y quien apretó el botón está esperando.
TOPE_SONDEO = 60


@dataclass
class Paso:
    """Un tramo del arranque, contado en castellano para la pantalla."""

    nombre: str
    detalle: str
    ok: bool = True


@dataclass
class Resultado:
    pasos: list[Paso] = field(default_factory=list)
    empresas: int = 0
    con_fuente: int = 0
    avisos: int = 0
    urgentes: int = 0
    contactos: int = 0
    listos_para_escribir: int = 0
    error: str | None = None

    @property
    def sirvio(self) -> bool:
        return self.empresas > 0


def primer_arranque(session: Session, texto: str, *, pais: str = "AR") -> Resultado:
    """Importa, vigila, sondea, ingiere, enriquece y puntúa. En ese orden.

    El orden no es negociable: sin fuentes no hay avisos, sin avisos no hay de
    dónde sacar contactos, y sin contactos el score de accesibilidad se calcula
    sobre datos que todavía no llegaron.
    """
    resultado = Resultado()

    analisis = mod_importar.analizar(texto)
    if not analisis.filas:
        resultado.error = (
            analisis.ignoradas[0]
            if analisis.ignoradas
            else "No se reconoció ninguna empresa en lo que pegaste."
        )
        return resultado

    # 1. Empresas, contactos y leads.
    importacion = mod_importar.importar(session, analisis.filas, pais=pais, vigilar=True)
    resultado.empresas = importacion.total
    resultado.pasos.append(
        Paso(
            "Empresas cargadas",
            f"{importacion.empresas_nuevas} nuevas y "
            f"{importacion.empresas_existentes} que ya estaban.",
        )
    )

    # 2. Dónde publica cada una. Es el paso lento y el que más rinde.
    encontradas = _sondear(session)
    resultado.pasos.append(
        Paso(
            "Búsqueda de sus avisos",
            f"{encontradas} empresas publican en un portal que sabemos leer."
            if encontradas
            else "Ninguna tiene board público todavía. La corrida diaria "
            "sigue intentando y suma las que aparezcan.",
            ok=True,
        )
    )

    # 3. Traer los avisos que ya estén publicados.
    nuevos = _ingerir(session)
    resultado.pasos.append(
        Paso(
            "Avisos traídos",
            f"{nuevos} búsquedas abiertas detectadas hoy."
            if nuevos
            else "Ninguna tiene búsquedas abiertas en este momento. "
            "Cuando publiquen, el sistema las va a ver.",
        )
    )

    # 4. Sacar contactos de esos avisos.
    try:
        enriquecimiento = mod_enriquecer.correr(session)
        resultado.contactos = enriquecimiento.contactos_nuevos
        resultado.pasos.append(
            Paso(
                "Contactos encontrados",
                f"{enriquecimiento.contactos_nuevos} nuevos, "
                f"{enriquecimiento.decisores_marcados} identificados como decisor.",
            )
        )
    except Exception as exc:  # el enriquecimiento es lo más frágil de la cadena
        log.warning("Falló el enriquecimiento: %s", exc)
        resultado.pasos.append(
            Paso("Contactos encontrados", f"No se pudo completar: {exc}", ok=False)
        )

    # 5. Puntuar todo con los datos ya cargados.
    recalcular_todos(session)
    session.commit()

    _contar(session, resultado)
    resultado.pasos.append(
        Paso(
            "Leads puntuados",
            f"{resultado.listos_para_escribir} tienen mail y ya se les puede escribir.",
        )
    )
    return resultado


def _sondear(session: Session) -> int:
    """Resuelve los objetivos pendientes. Una falla suelta no frena al resto."""
    pendientes = fuentes_db.objetivos_pendientes(session, limite=TOPE_SONDEO)
    encontradas = 0
    for objetivo in pendientes:
        try:
            if fuentes_db.sondear_objetivo(session, objetivo):
                encontradas += 1
        except Exception as exc:  # pragma: no cover - depende de la red
            log.warning("Sondeo de %s falló: %s", objetivo.nombre, exc)
        session.commit()
    return encontradas


def _ingerir(session: Session) -> int:
    """Corre la ingesta sobre las fuentes recién descubiertas."""
    try:
        # `resolver=False`: los objetivos ya se sondearon en el paso anterior y
        # volver a hacerlo duplicaría la parte más lenta de todo el arranque.
        resumenes = runner.correr(session, resolver=False)
    except Exception as exc:  # pragma: no cover - depende de la red
        log.warning("Falló la ingesta del arranque: %s", exc)
        return 0
    return sum(r.nuevas for r in resumenes)


def _contar(session: Session, resultado: Resultado) -> None:
    resultado.con_fuente = len(
        [f for f in fuentes_db.listar_fuentes(session, solo_activas=True)]
    )
    abiertas = list(
        session.scalars(select(Vacante).where(Vacante.cerrada.is_(False))).all()
    )
    resultado.avisos = len(abiertas)
    resultado.urgentes = len([v for v in abiertas if v.es_urgente])

    leads = list(
        session.scalars(
            select(Lead).join(Empresa, Lead.empresa_id == Empresa.id)
        ).all()
    )
    resultado.listos_para_escribir = len(
        [l for l in leads if any(c.email for c in l.empresa.contactos)]
    )


# Lista de arranque para quien todavía no tiene ninguna. No pretende ser el
# mercado entero: es lo suficiente para que el histórico empiece a correr hoy
# en vez de la semana que viene.
LISTA_IT_ARGENTINA = """Empresa,Dominio,Ciudad,Industria
Baufest,baufest.com,Buenos Aires,IT Services
Santex,santexgroup.com,Córdoba,IT Services
Snoop Consulting,snoopconsulting.com,Buenos Aires,IT Services
Vates,vates.com,Córdoba,IT Services
Lagash,lagash.com,Buenos Aires,IT Services
Practia,practia.global,Buenos Aires,IT Services
Hexacta,hexacta.com,Buenos Aires,IT Services
Redbee,redbee.io,Buenos Aires,IT Services
RYZ Labs,ryzlabs.com,Buenos Aires,IT Services
Darwoft,darwoft.com,La Plata,IT Services
Eryx,eryx.co,Buenos Aires,IT Services
Xappia,xappia.com,Buenos Aires,IT Services
Intive,intive.com,Buenos Aires,IT Services
Nearsure,nearsure.com,Buenos Aires,IT Services
Aivo,aivo.co,Córdoba,Computer Software
Kunan,kunan.com.ar,Córdoba,IT Services
Bitsion,bitsion.com,Córdoba,IT Services
Evoltis,evoltis.com,Córdoba,IT Services
Xcapit,xcapit.com,Córdoba,Computer Software
Tuxdi,tuxdi.com,Buenos Aires,IT Services
Poincenot,poincenot.com,Buenos Aires,IT Services
Pomelo,pomelo.la,Buenos Aires,Fintech
Ripio,ripio.com,Buenos Aires,Fintech
Increase,increase.app,Buenos Aires,Fintech
Geopagos,geopagos.com,Buenos Aires,Fintech
Lemon,lemon.me,Buenos Aires,Fintech
Buenbit,buenbit.com,Buenos Aires,Fintech
Belo,belo.app,Buenos Aires,Fintech
N5,n5now.com,Buenos Aires,Fintech
Naranja X,naranjax.com,Córdoba,Fintech
Ualá,uala.com.ar,Buenos Aires,Fintech
Tiendanube,tiendanube.com,Buenos Aires,Computer Software
Etermax,etermax.com,Buenos Aires,Computer Software
Emi Labs,emilabs.ai,Buenos Aires,Computer Software
Satellogic,satellogic.com,Buenos Aires,Computer Software
Auravant,auravant.com,Buenos Aires,Computer Software
Nubimetrics,nubimetrics.com,Posadas,Computer Software
Mural,mural.co,Buenos Aires,Computer Software
Digital House,digitalhouse.com,Buenos Aires,Education Technology
Agrofy,agrofy.com.ar,Rosario,Computer Software
Ualabee,ualabee.com,Córdoba,Computer Software
Bunker DB,bunkerdb.com,Buenos Aires,Computer Software
Navent,navent.com,Buenos Aires,Computer Software
Bluelight Consulting,bluelightconsulting.com,La Plata,IT Services
Sooft Technology,sooft.com.ar,Córdoba,IT Services
"""

"""Cargar a mano un aviso que viste.

La ingesta automática sólo llega a donde hay un board público que sabemos leer.
Una parte grande del mercado argentino publica en LinkedIn y en ningún otro
lado, y para esas empresas el sistema se queda ciego justo cuando la señal está
a la vista: entrás al LinkedIn de la empresa y ves dos búsquedas abiertas.

Esto cierra ese hueco. No reemplaza a la ingesta —treinta segundos por aviso no
escala a doscientas empresas— pero para las diez que estás trabajando en serio
es la diferencia entre un lead con score 32 y sin nada que decir, y uno que
abre con «vi que hace un mes buscan Cloud Engineer».

Y lo importante: una vez cargado, **la vacante entra al mismo circuito que las
automáticas**. Cuenta días abiertos, cuenta para el reposteo si vuelve a
aparecer, pesa en el score y alimenta el gancho del mail.
"""

from __future__ import annotations

import logging
import re
from datetime import date

from sqlalchemy.orm import Session

from .models import Empresa, Vacante, ahora
from .normalize import normalizar_rol
from .services import asegurar_lead, fecha_hoy, perfil, recalcular_lead, upsert_vacante

log = logging.getLogger("talanton.avisos")

FUENTE = "manual"


class ErrorAviso(ValueError):
    """Problema al cargar el aviso, con un texto para mostrar en pantalla."""


def interpretar_antiguedad(texto: str | None, hoy: date | None = None) -> tuple[date | None, bool]:
    """«hace 6 días», «1 mes», «3 semanas» -> fecha. Devuelve (fecha, aproximada).

    Es el mismo criterio que usa el conector de LinkedIn, y por el mismo motivo:
    LinkedIn no publica la fecha exacta, publica «hace 1 mes». Ese número
    termina en un mail al cliente, así que la vacante queda marcada como
    aproximada y en pantalla se ve con un `~`.
    """
    from .ingest.apify import interpretar_antiguedad as _interpretar

    return _interpretar(texto, hoy)


def _external_id(empresa: Empresa, titulo: str, url: str | None) -> str:
    """Clave estable para que recargar el mismo aviso no lo duplique.

    Con URL se usa la URL. Sin URL, empresa + rol normalizado: así «DevOps
    Engineer» cargado hoy y «Ingeniero DevOps» cargado en dos meses cuentan como
    la misma búsqueda, que es lo que permite detectar el reposteo.
    """
    if url:
        return re.sub(r"[?#].*$", "", url.strip())[:200]
    return f"{empresa.id}:{normalizar_rol(titulo)}"[:200]


def cargar(
    session: Session,
    empresa: Empresa,
    *,
    titulo: str,
    antiguedad: str | None = None,
    ubicacion: str | None = None,
    url: str | None = None,
    descripcion: str | None = None,
) -> tuple[Vacante, bool]:
    """Registra el aviso y vuelve a puntuar el lead. Devuelve (vacante, es_nueva)."""
    titulo = (titulo or "").strip()
    if not titulo:
        raise ErrorAviso("Falta el título del puesto.")

    fecha, aproximada = interpretar_antiguedad(antiguedad, fecha_hoy())
    if antiguedad and antiguedad.strip() and fecha is None:
        raise ErrorAviso(
            f"No entendí «{antiguedad}». Escribilo como lo muestra el portal: "
            "«hace 6 días», «1 mes», «3 semanas»."
        )

    vacante, es_nueva = upsert_vacante(
        session,
        empresa,
        titulo=titulo,
        fuente=FUENTE,
        external_id=_external_id(empresa, titulo, url),
        fuente_url=(url or "").strip() or None,
        ubicacion=(ubicacion or "").strip() or None,
        pais=empresa.pais,
        descripcion=(descripcion or "").strip() or None,
        fecha_publicacion=fecha,
        fecha_aproximada=aproximada,
    )

    # `primera_vez_vista` la fija `upsert_vacante` con la fecha de hoy, pero acá
    # sabemos algo mejor: cuándo se publicó de verdad. Sin esto, un aviso que
    # lleva un mes abierto arrancaría en cero días y el mail diría «vi que están
    # buscando» en vez de «hace un mes que buscan», que es lo que convence.
    if es_nueva and fecha and fecha < vacante.primera_vez_vista:
        vacante.primera_vez_vista = fecha

    session.flush()
    session.refresh(empresa)
    lead = asegurar_lead(session, empresa)
    recalcular_lead(session, lead, perfil(session))
    return vacante, es_nueva


def cerrar(session: Session, vacante: Vacante) -> None:
    """Marca cerrado un aviso que ya no está publicado.

    No se borra: modelar el cierre importa tanto como la apertura. Si la misma
    búsqueda reaparece más adelante, cuenta como reposteo —reintentaron y
    volvieron a fallar—, que es la señal más fuerte que maneja el producto.
    """
    if vacante.cerrada:
        return
    vacante.cerrada = True
    vacante.fecha_cierre = fecha_hoy()
    session.flush()
    session.refresh(vacante.empresa)
    lead = asegurar_lead(session, vacante.empresa)
    recalcular_lead(session, lead, perfil(session))

"""Señales de financiamiento y expansión desde posts de LinkedIn.

Por qué vale la pena: una empresa que acaba de levantar una ronda tiene
presupuesto fresco y presión por crecer. En los tres a seis meses siguientes
casi siempre abre búsquedas, y llegar antes que se desespere es mucho mejor que
llegar cuando ya publicó el aviso doce veces.

Por qué es distinto a un aviso: un post es un hecho puntual, no un estado que
se estira. No tiene días abiertos. Y la detección sobre texto libre es
imprecisa, así que **nada pesa en el score hasta que una persona lo confirma** —
mandar un mail felicitando por una ronda que no existió es peor que no mandarlo.

Sólo se guarda la empresa mencionada. El autor del post es una persona y su
dato no nos hace falta para nada.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date

from ..models import TipoEvento
from ..normalize import sin_acentos
from .apify import ClienteApify, ErrorApify, interpretar_antiguedad
from .base import parsear_fecha

log = logging.getLogger("talanton.posts")


@dataclass
class EventoCrudo:
    tipo: TipoEvento
    titulo: str
    resumen: str | None
    empresa_mencionada: str | None
    fecha: date
    fecha_aproximada: bool
    fuente: str
    external_id: str
    fuente_url: str | None = None


# --- Clasificación -----------------------------------------------------------

# Se exige una señal fuerte: sin un verbo o monto de operación, cualquier post
# que diga "inversión" entra, y la mayoría son de marketing.
_FINANCIAMIENTO = [
    r"\blevantamos\b", r"\bcerramos\b.{0,30}\bronda\b", r"\brecaudamos\b",
    r"\bronda\s+(de\s+)?(inversi[oó]n|financiamiento|semilla|serie\s+[a-e])\b",
    r"\bserie\s+[a-e]\b", r"\bseed\s+round\b", r"\bpre-?seed\b",
    r"\braised\b.{0,20}\b(million|m\b|usd|\$)", r"\bsecured\b.{0,20}\bfunding\b",
    r"\bclosed\b.{0,20}\b(seed|series\s+[a-e])\b",
    r"\bfunding\s+round\b", r"\bnos\s+invirti[oó]\b",
    r"\bUS?\$\s?\d+\s*(m|mm|millones|million)\b",
]

_EXPANSION = [
    r"\bnueva\s+(planta|sede|oficina|sucursal|f[aá]brica)\b",
    r"\babrimos\b.{0,25}\b(oficina|planta|sede|sucursal)\b",
    r"\bdesembarca\b", r"\bllegamos\s+a\b.{0,20}\b(pa[ií]s|mercado)\b",
    r"\bexpansi[oó]n\s+(regional|internacional)\b",
    r"\bnew\s+(office|plant|facility|headquarters)\b",
    r"\bopening\s+(our|a)\s+new\b",
]

_CONTRATACION = [
    r"\bestamos\s+contratando\b", r"\bsumamos?\s+\d+\s+personas\b",
    r"\bwe'?re\s+hiring\b", r"\bnos\s+expandimos\s+y\s+buscamos\b",
    r"\bduplicamos\s+el\s+equipo\b", r"\bgrowing\s+(our\s+)?team\b",
    r"\bvamos\s+a\s+incorporar\b",
]

_PATRONES = [
    (TipoEvento.FINANCIAMIENTO, _FINANCIAMIENTO),
    (TipoEvento.EXPANSION, _EXPANSION),
    (TipoEvento.CONTRATACION, _CONTRATACION),
]

# Descarta el ruido más común: quien *ofrece* servicios de inversión, resúmenes
# de noticias de terceros y contenido educativo.
_RUIDO = [
    r"\bte\s+ayudo\s+a\b", r"\bcurso\b", r"\bwebinar\b", r"\bmasterclass\b",
    r"\bcont[aá]ctame\b", r"\bmi\s+servicio\b", r"\bconsultor[ií]a\s+gratis\b",
    r"\btips?\s+para\b", r"\bhilo\b.{0,10}\b\d+\b",
]


def clasificar(texto: str | None) -> TipoEvento | None:
    """Qué tipo de señal es el post, o None si no es ninguna.

    Preferimos perder señales antes que llenar la cola de revisión con ruido:
    una cola que nadie mira no sirve para nada.
    """
    if not texto or len(texto) < 30:
        return None

    limpio = sin_acentos(texto).lower()
    if any(re.search(p, limpio) for p in _RUIDO):
        return None

    for tipo, patrones in _PATRONES:
        if any(re.search(p, limpio) for p in patrones):
            return tipo
    return None


# --- Empresa mencionada ------------------------------------------------------

_SUFIJOS_LEGALES = r"(?:S\.?A\.?S?\.?|S\.?R\.?L\.?|Inc\.?|Ltd\.?|Corp\.?)"


def detectar_empresa(item: dict, texto: str | None) -> str | None:
    """De qué empresa habla el post.

    Orden: si lo publica una página de empresa, esa. Si lo publica una persona,
    la empresa donde trabaja. Como último recurso, una entidad con sufijo
    societario en el texto — sólo eso, porque cualquier heurística más suelta
    devuelve nombres de personas.
    """
    autor = item.get("author") or item.get("actor") or {}
    if isinstance(autor, dict):
        # Página de empresa: el propio autor es la empresa.
        if (autor.get("type") or autor.get("authorType") or "").lower() in ("company", "organization"):
            nombre = autor.get("name") or autor.get("title")
            if nombre:
                return str(nombre).strip()
        # Persona: su empresa actual.
        for clave in ("companyName", "company", "currentCompany", "occupation"):
            valor = autor.get(clave)
            if isinstance(valor, dict):
                valor = valor.get("name")
            if valor and len(str(valor).strip()) > 2:
                return str(valor).strip()

    for clave in ("companyName", "company", "organizationName"):
        valor = item.get(clave)
        if isinstance(valor, dict):
            valor = valor.get("name")
        if valor:
            return str(valor).strip()

    if texto:
        coincidencia = re.search(
            rf"\b([A-ZÁÉÍÓÚÑ][\w&.-]*(?:\s+[A-ZÁÉÍÓÚÑ][\w&.-]*){{0,2}})\s+{_SUFIJOS_LEGALES}",
            texto,
        )
        if coincidencia:
            return coincidencia.group(0).strip()

    return None


# --- Mapeo -------------------------------------------------------------------

_CLAVES_TEXTO = ("text", "content", "postText", "commentary", "description")
_CLAVES_FECHA = ("postedAt", "publishedAt", "date", "postedDate", "time", "createdAt")
_CLAVES_URL = ("url", "postUrl", "link", "permalink")
_CLAVES_ID = ("id", "postId", "urn", "activityUrn")


def _primero(item: dict, claves: tuple[str, ...]) -> str | None:
    for clave in claves:
        valor = item.get(clave)
        if isinstance(valor, dict):
            valor = valor.get("text") or valor.get("name") or valor.get("value")
        if valor not in (None, "", []):
            return str(valor).strip()
    return None


def mapear(item: dict, fuente: str = "linkedin_posts", hoy: date | None = None) -> EventoCrudo | None:
    texto = _primero(item, _CLAVES_TEXTO)
    tipo = clasificar(texto)
    if tipo is None:
        return None

    empresa = detectar_empresa(item, texto)
    if not empresa:
        # Sin empresa el evento no se puede vincular a nada y sólo ensucia.
        return None

    bruto_fecha = _primero(item, _CLAVES_FECHA)
    fecha = parsear_fecha(bruto_fecha)
    aproximada = False
    if fecha is None:
        fecha, aproximada = interpretar_antiguedad(bruto_fecha, hoy)
    if fecha is None:
        from ..services import fecha_hoy

        fecha, aproximada = (hoy or fecha_hoy()), True

    url = _primero(item, _CLAVES_URL)
    externo = _primero(item, _CLAVES_ID) or hashlib.sha1(
        f"{empresa}|{(texto or '')[:200]}".encode()
    ).hexdigest()[:16]

    resumen = re.sub(r"\s+", " ", texto or "").strip()
    return EventoCrudo(
        tipo=tipo,
        titulo=f"{tipo.etiqueta}: {empresa}",
        resumen=resumen[:1500],
        empresa_mencionada=empresa,
        fecha=fecha,
        fecha_aproximada=aproximada,
        fuente=fuente,
        external_id=str(externo),
        fuente_url=url,
    )


# --- Conector ----------------------------------------------------------------


class BusquedaPosts:
    """Búsqueda de posts que se corre en cada corrida diaria."""

    nombre = "linkedin_posts"

    def __init__(
        self,
        actor: str,
        configuracion: dict,
        etiqueta: str = "",
        cliente: ClienteApify | None = None,
    ):
        self.actor = actor
        self.configuracion = configuracion
        self.url = etiqueta or actor
        self._cliente = cliente

    @property
    def cliente(self) -> ClienteApify:
        if self._cliente:
            return self._cliente
        from ..config import APIFY_TOKEN

        if not APIFY_TOKEN:
            raise ErrorApify("Falta configurar TALANTON_APIFY_TOKEN. Ver docs/linkedin.md.")
        return ClienteApify(APIFY_TOKEN)

    def fetch_eventos(self) -> list[EventoCrudo]:
        crudos = self.cliente.correr_actor(self.actor, self.configuracion)
        eventos = []
        for item in crudos:
            if not isinstance(item, dict):
                continue
            evento = mapear(item, self.nombre)
            if evento:
                eventos.append(evento)

        log.info(
            "%s: %s posts, %s clasificados como señal",
            self.url, len(crudos), len(eventos),
        )
        return eventos

    def fetch(self):
        """Los posts no producen vacantes: la corrida los trata aparte."""
        return []


def desde_configuracion(texto: str, etiqueta: str = "") -> BusquedaPosts:
    import json

    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise ErrorApify(f"La configuración de la búsqueda no es JSON válido: {exc}") from exc

    actor = datos.pop("_actor", None)
    datos.pop("_pais", None)
    if not actor:
        raise ErrorApify("Falta «_actor» en la configuración de la búsqueda.")
    return BusquedaPosts(actor, datos, etiqueta=etiqueta)

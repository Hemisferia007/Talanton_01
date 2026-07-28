"""Conector de Apify, para portales que no exponen API pública.

Se usa principalmente para LinkedIn Jobs, que es la fuente más grande de avisos
en Argentina para empresas medianas y grandes, y la única que además **descubre
empresas nuevas**: el resto de los conectores sólo vigila empresas que ya
conocemos, y una búsqueda por rubro y ubicación trae las que todavía no están
en la base.

Dos reglas de uso, ver docs/linkedin.md:

1. **Nunca se le pasa una cookie de sesión propia al actor.** Hay actores que
   la piden para acceder a más datos; con eso el ban de cuenta deja de ser un
   riesgo del proveedor y pasa a ser tuyo. Sólo datos públicos, sin autenticar.
2. **Siempre con tope de resultados.** Apify cobra por uso y un actor mal
   configurado puede correr durante horas.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

from ..config import APIFY_TOKEN
from ..services import fecha_hoy
from .base import VacanteCruda, parsear_fecha

log = logging.getLogger("talanton.apify")

BASE_API = "https://api.apify.com/v2"


class ErrorApify(RuntimeError):
    """Falla al hablar con Apify. El mensaje es apto para mostrar en la UI."""


# --- Fechas ------------------------------------------------------------------

# LinkedIn suele devolver la antigüedad en texto relativo en vez de una fecha.
_UNIDADES = {
    "minut": 0, "minute": 0, "hora": 0, "hour": 0,
    "dia": 1, "día": 1, "day": 1,
    "semana": 7, "week": 7,
    "mes": 30, "month": 30,
    "año": 365, "ano": 365, "year": 365,
}


def interpretar_antiguedad(texto: str | None, hoy: date | None = None) -> tuple[date | None, bool]:
    """Convierte «hace 3 semanas» o «2 weeks ago» en una fecha.

    Devuelve (fecha, es_aproximada). Marcar la aproximación importa: ese número
    termina en un mail que se le manda al cliente, y decirle "hace 92 días"
    cuando en realidad son 85-99 es una forma barata de quedar mal.
    """
    if not texto:
        return None, False

    exacta = parsear_fecha(texto)
    if exacta:
        return exacta, False

    hoy = hoy or fecha_hoy()
    limpio = texto.lower().strip()

    if any(p in limpio for p in ("hoy", "today", "just now", "recién", "recien")):
        return hoy, False
    if any(p in limpio for p in ("ayer", "yesterday")):
        return hoy - timedelta(days=1), False

    coincidencia = re.search(r"(\d+)\s*\+?\s*([a-záéíóúñ]+)", limpio)
    if not coincidencia:
        return None, False

    cantidad = int(coincidencia.group(1))
    palabra = coincidencia.group(2)
    for prefijo, dias in _UNIDADES.items():
        if palabra.startswith(prefijo):
            return hoy - timedelta(days=cantidad * dias), dias > 1

    return None, False


# --- Mapeo de resultados -----------------------------------------------------

# Cada actor de la tienda nombra los campos a su manera. Se prueban los nombres
# habituales en vez de atarse a uno solo: cambiar de actor no debería obligar a
# tocar código.
_CLAVES = {
    "titulo": ("title", "jobTitle", "positionName", "position"),
    "empresa": ("companyName", "company", "companyTitle", "organization"),
    "ubicacion": ("location", "jobLocation", "formattedLocation", "place"),
    "url": ("jobUrl", "url", "link", "jobPostingUrl", "applyUrl"),
    "descripcion": ("descriptionText", "description", "jobDescription", "snippet"),
    "publicado": ("postedAt", "publishedAt", "postedTime", "listedAt",
                  "postedDate", "datePosted", "publishedDate"),
    "id": ("id", "jobId", "jobPostingId", "trackingId"),
    "empresa_url": ("companyWebsite", "companyUrl", "companyLinkedinUrl"),
    "modalidad": ("employmentType", "contractType", "workplaceType", "jobType"),
    # Con `scrapeCompany: true` varios actores suman datos de la empresa. La
    # dotación decide a qué cargo apuntar y pesa en capacidad de pago, así que
    # cuando viene gratis vale mucho más que estimarla después.
    "dotacion": ("employeeCount", "companySize", "staffCount", "employeesCount"),
    "industria": ("companyIndustry", "industry", "industries", "sector"),
}


def _numero(texto: str | None) -> int | None:
    """Saca la dotación de «1.001-5.000 empleados» o de un número suelto.

    Con un rango se toma el extremo inferior: es el dato que se puede afirmar.
    """
    if not texto:
        return None
    numeros = re.findall(r"\d[\d.,]*", str(texto))
    if not numeros:
        return None
    try:
        return int(numeros[0].replace(".", "").replace(",", ""))
    except ValueError:
        return None


def _primero(item: dict, campo: str) -> str | None:
    for clave in _CLAVES[campo]:
        valor = item.get(clave)
        if isinstance(valor, dict):
            valor = valor.get("name") or valor.get("text") or valor.get("value")
        if isinstance(valor, list) and valor:
            valor = valor[0]
        if valor not in (None, "", []):
            return str(valor).strip()
    return None


def _dominio_desde_url(url: str | None) -> str | None:
    """Sólo sirve si es el sitio propio: linkedin.com/company/x no es un dominio."""
    if not url or "linkedin.com" in url:
        return None
    from ..normalize import normalizar_dominio

    return normalizar_dominio(url)


def mapear(item: dict, fuente: str = "linkedin", pais_por_defecto: str | None = None) -> VacanteCruda | None:
    """Convierte un resultado del actor en VacanteCruda. None si no sirve."""
    titulo = _primero(item, "titulo")
    empresa = _primero(item, "empresa")
    if not titulo or not empresa:
        return None

    from .ats import inferir_pais

    ubicacion = _primero(item, "ubicacion")
    url = _primero(item, "url")
    publicado, aproximada = interpretar_antiguedad(_primero(item, "publicado"))

    externo = _primero(item, "id")
    if not externo:
        # Sin id propio se arma uno estable, para que la próxima corrida
        # reconozca el mismo aviso y no lo cuente como nuevo.
        import hashlib

        externo = hashlib.sha1(f"{empresa}|{titulo}|{ubicacion}".encode()).hexdigest()[:16]

    return VacanteCruda(
        empresa=empresa,
        empresa_dominio=_dominio_desde_url(_primero(item, "empresa_url")),
        titulo=titulo,
        fuente=fuente,
        external_id=str(externo),
        fuente_url=url,
        ubicacion=ubicacion,
        pais=inferir_pais(ubicacion) or pais_por_defecto,
        modalidad=_primero(item, "modalidad"),
        descripcion=(_primero(item, "descripcion") or "")[:4000] or None,
        fecha_publicacion=publicado,
        fecha_aproximada=aproximada,
        empresa_industria=_primero(item, "industria"),
        empresa_dotacion=_numero(_primero(item, "dotacion")),
    )


# --- Cliente -----------------------------------------------------------------


@dataclass
class ClienteApify:
    token: str
    espera_maxima: int = 600  # 10 minutos; un scrape de LinkedIn no es instantáneo
    intervalo: int = 10

    def correr_actor(self, actor: str, entrada: dict) -> list[dict]:
        """Dispara el actor, espera a que termine y devuelve los resultados."""
        run = self._iniciar(actor, entrada)
        run_id = run.get("id")
        dataset_id = (run.get("defaultDatasetId") or "")
        if not run_id or not dataset_id:
            raise ErrorApify("Apify no devolvió el identificador de la corrida.")

        estado = self._esperar(run_id)
        if estado != "SUCCEEDED":
            raise ErrorApify(
                f"El actor terminó en estado {estado}. Revisá la corrida en Apify."
            )
        return self._resultados(dataset_id)

    def _iniciar(self, actor: str, entrada: dict) -> dict:
        # El actor se identifica como usuario~nombre; la barra hay que escaparla.
        ruta = actor.replace("/", "~")
        try:
            r = httpx.post(
                f"{BASE_API}/acts/{ruta}/runs",
                params={"token": self.token},
                json=entrada,
                timeout=60,
            )
        except httpx.HTTPError as exc:
            raise ErrorApify(f"No se pudo contactar a Apify: {exc}") from exc

        if r.status_code == 401:
            raise ErrorApify("El token de Apify no es válido.")
        if r.status_code == 404:
            raise ErrorApify(f"No existe el actor «{actor}» o no tenés acceso.")
        if r.status_code >= 400:
            raise ErrorApify(f"Apify devolvió {r.status_code}: {r.text[:200]}")
        return r.json().get("data", {})

    def _esperar(self, run_id: str) -> str:
        limite = time.time() + self.espera_maxima
        while time.time() < limite:
            try:
                r = httpx.get(
                    f"{BASE_API}/actor-runs/{run_id}",
                    params={"token": self.token},
                    timeout=30,
                )
                estado = r.json().get("data", {}).get("status", "")
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("Error consultando la corrida %s: %s", run_id, exc)
                estado = ""

            if estado in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                return estado
            time.sleep(self.intervalo)

        # No se aborta la corrida: puede terminar sola y quedar disponible para
        # la próxima. Sí se corta nuestra espera.
        raise ErrorApify(
            f"El actor sigue corriendo después de {self.espera_maxima}s. "
            "Bajá el tope de resultados o revisalo en Apify."
        )

    def _resultados(self, dataset_id: str) -> list[dict]:
        try:
            r = httpx.get(
                f"{BASE_API}/datasets/{dataset_id}/items",
                params={"token": self.token, "clean": "true", "format": "json"},
                timeout=120,
            )
            r.raise_for_status()
            datos = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ErrorApify(f"No se pudieron leer los resultados: {exc}") from exc
        return datos if isinstance(datos, list) else []


# --- Conector ----------------------------------------------------------------


class BusquedaApify:
    """Una búsqueda guardada que se corre en cada corrida diaria.

    `configuracion` es el JSON de entrada del actor, tal cual lo documenta su
    página en la tienda de Apify. Se guarda como texto para no atarse al
    esquema de ningún actor en particular.
    """

    nombre = "linkedin"

    def __init__(
        self,
        actor: str,
        configuracion: dict,
        etiqueta: str = "",
        pais: str | None = "AR",
        cliente: ClienteApify | None = None,
    ):
        self.actor = actor
        self.configuracion = configuracion
        self.url = etiqueta or actor
        self.pais = pais
        self._cliente = cliente

    @property
    def cliente(self) -> ClienteApify:
        if self._cliente:
            return self._cliente
        if not APIFY_TOKEN:
            raise ErrorApify(
                "Falta configurar TALANTON_APIFY_TOKEN. Ver docs/linkedin.md."
            )
        return ClienteApify(APIFY_TOKEN)

    def fetch(self) -> list[VacanteCruda]:
        crudos = self.cliente.correr_actor(self.actor, self.configuracion)
        vacantes = []
        for item in crudos:
            if not isinstance(item, dict):
                continue
            vacante = mapear(item, self.nombre, self.pais)
            if vacante:
                vacantes.append(vacante)

        log.info(
            "%s: %s resultados del actor, %s avisos utilizables",
            self.url, len(crudos), len(vacantes),
        )
        return vacantes


def desde_configuracion(texto: str, etiqueta: str = "") -> BusquedaApify:
    """Arma la búsqueda desde el JSON guardado en la fuente."""
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise ErrorApify(f"La configuración de la búsqueda no es JSON válido: {exc}") from exc

    actor = datos.pop("_actor", None)
    pais = datos.pop("_pais", "AR")
    if not actor:
        raise ErrorApify("Falta «_actor» en la configuración de la búsqueda.")
    return BusquedaApify(actor, datos, etiqueta=etiqueta, pais=pais)

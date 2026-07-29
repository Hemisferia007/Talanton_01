"""Hunter.io: encontrar a la persona de RRHH de una empresa, con su mail.

Es la pieza que faltaba. Talanton sabía detectar **cuándo** una empresa
necesita una consultora, pero para escribirle hace falta saber **a quién**, y
eso hasta ahora dependía de que el mail estuviera en el texto de un aviso.

Hunter busca sobre el dominio de la empresa —`baufest.com`— y devuelve las
direcciones que encontró publicadas, con nombre, cargo y **de qué páginas las
sacó**. Esa última parte es la que lo hace usable: cada contacto queda con su
procedencia, que es lo que permite auditarlo y darlo de baja a pedido.

Dos cosas que lo hacen preferible a Apollo para empezar:

- **La API anda en el plan gratuito** (25 búsquedas por mes). La de Apollo no.
- Filtra por **departamento**: se le pide `hr` y devuelve gente de RRHH, no el
  contacto de prensa ni el de ventas.

Lo que no hace: inventar. Si una empresa no tiene mails publicados, Hunter no
devuelve nada, y eso es correcto — es preferible a un `nombre.apellido@` armado
por patrón que rebota y te ensucia la reputación del dominio.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from ..config import HUNTER_API_KEY

log = logging.getLogger("talanton.hunter")

BASE_API = "https://api.hunter.io/v2"
TIMEOUT = 30.0

# Qué departamentos pedirle. `hr` es el que compra el servicio; `executive`
# entra porque en una empresa chica no hay área de RRHH y decide el dueño.
DEPARTAMENTOS = "hr,executive"

# Por debajo de esto el mail es más probable que rebote que que llegue, y un
# rebote cuesta reputación de dominio, que es cara de recuperar.
CONFIANZA_MINIMA = 50


class ErrorHunter(RuntimeError):
    """Falla al hablar con Hunter, con un texto para mostrar en pantalla."""


@dataclass
class Hallazgo:
    email: str
    nombre: str | None = None
    cargo: str | None = None
    departamento: str | None = None
    seniority: str | None = None
    confianza: int = 0
    # De dónde lo sacó Hunter. Sin esto el contacto no se puede defender.
    fuente_url: str | None = None

    @property
    def es_de_area(self) -> bool:
        """`rrhh@empresa.com` no es una persona: es un buzón."""
        local = self.email.split("@")[0].lower()
        return not self.nombre or local in _BUZONES

    @property
    def etiqueta(self) -> str:
        return f"{self.nombre or self.email} — {self.cargo or 'sin cargo'}"


_BUZONES = {
    "rrhh", "rh", "hr", "info", "contacto", "contact", "hola", "hello",
    "empleos", "jobs", "trabajo", "careers", "cv", "seleccion", "talento",
    "talent", "people", "recruiting", "reclutamiento", "administracion",
}


@dataclass
class Resultado:
    dominio: str
    hallazgos: list[Hallazgo] = field(default_factory=list)
    # Cuántas búsquedas le quedan a la cuenta este mes. Se muestra en pantalla:
    # gastar 25 sin darse cuenta es fácil.
    restantes: int | None = None

    @property
    def personas(self) -> list[Hallazgo]:
        return [h for h in self.hallazgos if not h.es_de_area]

    @property
    def buzones(self) -> list[Hallazgo]:
        return [h for h in self.hallazgos if h.es_de_area]


def configurado() -> bool:
    return bool(HUNTER_API_KEY)


class Cliente:
    """Envuelve la API. Se inyecta en los tests para no tocar la red."""

    def __init__(self, api_key: str | None = None):
        clave = api_key or HUNTER_API_KEY
        if not clave:
            raise ErrorHunter(
                "Falta la clave de Hunter. Cargá TALANTON_HUNTER_API_KEY en las "
                "variables del servicio — ver docs/contactos.md."
            )
        self._clave = clave

    def _get(self, ruta: str, params: dict) -> dict:
        try:
            respuesta = httpx.get(
                f"{BASE_API}/{ruta}",
                params={**params, "api_key": self._clave},
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise ErrorHunter(f"No se pudo llegar a Hunter: {exc}") from exc

        if respuesta.status_code == 401:
            raise ErrorHunter("Hunter rechazó la clave. Revisá TALANTON_HUNTER_API_KEY.")
        if respuesta.status_code == 429:
            raise ErrorHunter(
                "Se acabaron las búsquedas del mes en Hunter. El plan gratuito trae 25."
            )
        if respuesta.status_code >= 400:
            raise ErrorHunter(f"Hunter respondió {respuesta.status_code}: {_detalle(respuesta)}")

        try:
            return respuesta.json()
        except ValueError as exc:
            raise ErrorHunter("Hunter devolvió una respuesta que no es JSON.") from exc

    def buscar_dominio(self, dominio: str, *, limite: int = 10) -> Resultado:
        """Busca contactos de RRHH y dirección en un dominio. Gasta una búsqueda."""
        dominio = (dominio or "").strip().lower()
        if not dominio:
            raise ErrorHunter("La empresa no tiene dominio cargado, no hay dónde buscar.")

        datos = self._get(
            "domain-search",
            {"domain": dominio, "department": DEPARTAMENTOS, "limit": limite},
        )
        cuerpo = datos.get("data") or {}
        resultado = Resultado(dominio=dominio, restantes=_restantes(datos))

        for bruto in cuerpo.get("emails") or []:
            email = (bruto.get("value") or "").strip().lower()
            if not email or "@" not in email:
                continue
            confianza = _entero(bruto.get("confidence")) or 0
            if confianza < CONFIANZA_MINIMA:
                continue
            nombre = " ".join(
                x for x in (bruto.get("first_name"), bruto.get("last_name")) if x
            ).strip()
            fuentes = bruto.get("sources") or []
            resultado.hallazgos.append(
                Hallazgo(
                    email=email,
                    nombre=nombre or None,
                    cargo=(bruto.get("position") or "").strip() or None,
                    departamento=bruto.get("department"),
                    seniority=bruto.get("seniority"),
                    confianza=confianza,
                    fuente_url=(fuentes[0].get("uri") if fuentes else None),
                )
            )

        # Los de más confianza primero: es el orden en que conviene escribirles.
        resultado.hallazgos.sort(key=lambda h: (h.es_de_area, -h.confianza))
        return resultado

    def saldo(self) -> dict:
        """Cuántas búsquedas quedan. No gasta ninguna."""
        datos = self._get("account", {})
        cuenta = datos.get("data") or {}
        uso = (cuenta.get("requests") or {}).get("searches") or {}
        return {
            "plan": cuenta.get("plan_name"),
            "usadas": _entero(uso.get("used")) or 0,
            "disponibles": _entero(uso.get("available")),
        }


def _restantes(datos: dict) -> int | None:
    meta = datos.get("meta") or {}
    return _entero(meta.get("results"))


def _entero(valor) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _detalle(respuesta: httpx.Response) -> str:
    try:
        datos = respuesta.json()
    except ValueError:
        return respuesta.text[:200]
    errores = datos.get("errors") or []
    if errores:
        return str(errores[0].get("details") or errores[0])[:300]
    return str(datos)[:200]

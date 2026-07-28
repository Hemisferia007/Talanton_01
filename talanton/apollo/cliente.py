"""Cliente REST de Apollo.io.

Apollo tiene dos operaciones distintas y conviene no confundirlas, porque
cuestan cosas distintas:

1. **Buscar** (`mixed_people/search`) devuelve personas con nombre, cargo y
   empresa, pero **el email viene tapado** (`email_not_unlocked@dominio.com`).
   Sirve para ver a quién estás por traer antes de gastar nada.
2. **Revelar** (`people/match`) destapa el email de una persona puntual y
   **consume un crédito de la cuenta**.

Por eso en Talanton son dos pasos separados con un botón cada uno: primero mirás
la lista, después decidís por cuáles pagás. Un buscador que gasta créditos al
apretar «buscar» se come el plan del mes en una tarde de pruebas.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from ..config import APOLLO_API_KEY

log = logging.getLogger("talanton.apollo")

BASE_API = "https://api.apollo.io/api/v1"

# Apollo corta por minuto, por hora y por día. Un timeout largo es preferible a
# reintentar: reintentar una búsqueda que ya salió cuenta doble.
TIMEOUT = 45.0

# Tramos de dotación tal como los espera la API. No son libres: mandar
# "50,180" devuelve 422.
TRAMOS_DOTACION = [
    "1,10", "11,20", "21,50", "51,100", "101,200",
    "201,500", "501,1000", "1001,2000", "2001,5000",
    "5001,10000", "10001,",
]

# Un email tapado no es un email: Apollo devuelve este literal cuando el
# registro existe pero todavía no lo desbloqueaste.
_TAPADO = "email_not_unlocked"


class ErrorApollo(RuntimeError):
    """Falla al hablar con Apollo, con un texto apto para mostrar en pantalla."""


@dataclass
class Persona:
    """Una persona tal como la devuelve Apollo, ya aplanada."""

    apollo_id: str
    nombre: str
    cargo: str | None = None
    email: str | None = None
    linkedin_url: str | None = None
    empresa: str = ""
    dominio: str | None = None
    industria: str | None = None
    dotacion: int | None = None
    ciudad: str | None = None
    pais: str | None = None

    @property
    def email_visible(self) -> bool:
        return bool(self.email and _TAPADO not in self.email)


@dataclass
class Resultado:
    personas: list[Persona] = field(default_factory=list)
    total: int = 0
    pagina: int = 1
    paginas: int = 1


def configurado() -> bool:
    return bool(APOLLO_API_KEY)


def tramos_para(minimo: int | None, maximo: int | None) -> list[str]:
    """Traduce un rango libre de empleados a los tramos que acepta Apollo.

    Se toman los tramos que se solapan con el rango pedido, no los que caen
    enteros adentro: con dotación 20-300, el tramo 11-20 y el 201-500 también
    tienen empresas que sirven.
    """
    if minimo is None and maximo is None:
        return []
    bajo = minimo if minimo is not None else 0
    alto = maximo if maximo is not None else 10**9

    elegidos = []
    for tramo in TRAMOS_DOTACION:
        desde_txt, hasta_txt = tramo.split(",")
        desde = int(desde_txt)
        hasta = int(hasta_txt) if hasta_txt else 10**9
        if desde <= alto and hasta >= bajo:
            elegidos.append(tramo)
    return elegidos


class Cliente:
    """Envuelve la API. Se inyecta en los tests para no tocar la red."""

    def __init__(self, api_key: str | None = None):
        clave = api_key or APOLLO_API_KEY
        if not clave:
            raise ErrorApollo(
                "Falta la clave de Apollo. Cargá TALANTON_APOLLO_API_KEY en las "
                "variables del servicio — ver docs/apollo.md."
            )
        self._clave = clave

    # --- Transporte ----------------------------------------------------------

    def _post(self, ruta: str, cuerpo: dict) -> dict:
        try:
            respuesta = httpx.post(
                f"{BASE_API}/{ruta}",
                json=cuerpo,
                headers={
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                    # Apollo migró del `api_key` en el body a este header. El
                    # body sigue funcionando pero deja la clave en logs de
                    # proxies; el header no.
                    "x-api-key": self._clave,
                },
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise ErrorApollo(f"No se pudo llegar a Apollo: {exc}") from exc

        if respuesta.status_code in (401, 403):
            raise ErrorApollo(
                "Apollo rechazó la clave. Revisá que sea una API key vigente y que "
                "el plan tenga acceso a la API."
            )
        if respuesta.status_code == 422:
            raise ErrorApollo(
                f"Apollo rechazó los filtros de la búsqueda: {_detalle(respuesta)}"
            )
        if respuesta.status_code == 429:
            raise ErrorApollo(
                "Apollo está limitando por volumen (tope por minuto, hora o día). "
                "Esperá un rato antes de volver a buscar."
            )
        if respuesta.status_code >= 400:
            raise ErrorApollo(
                f"Apollo respondió {respuesta.status_code}: {_detalle(respuesta)}"
            )

        try:
            return respuesta.json()
        except ValueError as exc:
            raise ErrorApollo("Apollo devolvió una respuesta que no es JSON.") from exc

    # --- Operaciones ---------------------------------------------------------

    def buscar_personas(
        self,
        *,
        cargos: list[str],
        paises: list[str] | None = None,
        industrias: list[str] | None = None,
        dotacion_min: int | None = None,
        dotacion_max: int | None = None,
        pagina: int = 1,
        por_pagina: int = 25,
    ) -> Resultado:
        """Busca decisores. **No consume créditos ni destapa emails.**"""
        cuerpo: dict = {
            "page": max(1, pagina),
            # Apollo tope 100. Más que eso no es una página, son varias.
            "per_page": max(1, min(100, por_pagina)),
        }
        if cargos:
            cuerpo["person_titles"] = cargos
        if paises:
            # Por ubicación de la *empresa*, no de la persona: nos interesa
            # dónde está la operación que contrata, no dónde vive el gerente.
            cuerpo["organization_locations"] = paises
        if industrias:
            cuerpo["q_organization_keyword_tags"] = industrias
        tramos = tramos_para(dotacion_min, dotacion_max)
        if tramos:
            cuerpo["organization_num_employees_ranges"] = tramos

        datos = self._post("mixed_people/search", cuerpo)
        paginacion = datos.get("pagination") or {}
        return Resultado(
            personas=[_persona(p) for p in (datos.get("people") or []) if p],
            total=_entero(paginacion.get("total_entries")) or 0,
            pagina=_entero(paginacion.get("page")) or pagina,
            paginas=_entero(paginacion.get("total_pages")) or 1,
        )

    def revelar_email(self, persona: Persona) -> Persona:
        """Destapa el email de una persona. **Consume un crédito.**

        Si Apollo no lo tiene, devuelve la persona sin email en vez de fallar:
        que falte un mail no puede tirar abajo la importación de los otros.
        """
        cuerpo: dict = {"reveal_personal_emails": False}
        if persona.apollo_id:
            cuerpo["id"] = persona.apollo_id
        else:
            cuerpo["name"] = persona.nombre
            if persona.dominio:
                cuerpo["domain"] = persona.dominio

        datos = self._post("people/match", cuerpo)
        encontrada = datos.get("person") or {}
        email = (encontrada.get("email") or "").strip().lower()
        if email and _TAPADO not in email:
            persona.email = email
        else:
            persona.email = None
        return persona


# --- Mapeo -------------------------------------------------------------------


def _persona(bruto: dict) -> Persona:
    """Aplana la respuesta. Tolerante a propósito: Apollo cambia campos seguido
    y prefiero un contacto sin industria que una excepción a mitad de página."""
    org = bruto.get("organization") or bruto.get("account") or {}
    nombre = (bruto.get("name") or "").strip()
    if not nombre:
        nombre = " ".join(
            x for x in (bruto.get("first_name"), bruto.get("last_name")) if x
        ).strip()

    email = (bruto.get("email") or "").strip().lower() or None

    return Persona(
        apollo_id=str(bruto.get("id") or ""),
        nombre=nombre or "Sin nombre",
        cargo=(bruto.get("title") or "").strip() or None,
        email=email,
        linkedin_url=bruto.get("linkedin_url"),
        empresa=(org.get("name") or "").strip(),
        dominio=_dominio(org),
        industria=(org.get("industry") or "").strip() or None,
        dotacion=_entero(org.get("estimated_num_employees")),
        ciudad=(org.get("city") or bruto.get("city") or "").strip() or None,
        pais=(org.get("country") or bruto.get("country") or "").strip() or None,
    )


def _dominio(org: dict) -> str | None:
    from ..normalize import normalizar_dominio

    return normalizar_dominio(org.get("primary_domain") or org.get("website_url"))


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
    for clave in ("error", "error_message", "message", "errors"):
        if datos.get(clave):
            return str(datos[clave])[:300]
    return str(datos)[:200]

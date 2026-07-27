"""Descubridor de fuentes.

El problema práctico de arrancar: sabés qué empresas te interesan, pero no en
qué ATS publican. Probar a mano `boards-api.greenhouse.io/v1/boards/<slug>`
para cada candidata y cada plataforma es inviable.

Esto lo automatiza: le pasás nombres y dominios, sondea las plataformas más
usadas, y escribe un `fuentes.json` con las que respondieron de verdad. Lo que
no encuentra queda listado aparte, para atacarlo por página de carrera.

Sólo hace peticiones GET a endpoints públicos de listado de empleos —los mismos
que sirven los sitios de carreras— y con pausa entre pedidos.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .base import traer_json, traer_pagina
from .jsonld import parsear_html
from .normalizar_slug import candidatos_de_slug

log = logging.getLogger("talanton.descubridor")

# Cada plataforma, con la URL de su API pública y cómo saber si el board existe.
PLATAFORMAS = {
    "greenhouse": {
        "url": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
        "existe": lambda d: isinstance(d, dict) and "jobs" in d,
        "cantidad": lambda d: len(d.get("jobs", [])),
    },
    "lever": {
        "url": "https://api.lever.co/v0/postings/{slug}?mode=json",
        "existe": lambda d: isinstance(d, list),
        "cantidad": lambda d: len(d),
    },
    "ashby": {
        "url": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
        "existe": lambda d: isinstance(d, dict) and "jobs" in d,
        "cantidad": lambda d: len(d.get("jobs", [])),
    },
    "recruitee": {
        "url": "https://{slug}.recruitee.com/api/offers/",
        "existe": lambda d: isinstance(d, dict) and "offers" in d,
        "cantidad": lambda d: len(d.get("offers", [])),
    },
    "workable": {
        "url": "https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true",
        "existe": lambda d: isinstance(d, dict) and "jobs" in d,
        "cantidad": lambda d: len(d.get("jobs", [])),
    },
}

# Rutas habituales de páginas de carrera en sitios argentinos.
RUTAS_CARRERA = [
    "/trabaja-con-nosotros",
    "/trabajaconnosotros",
    "/empleos",
    "/carreras",
    "/careers",
    "/jobs",
    "/sumate",
    "/unite",
    "/rrhh",
    "/postulate",
]


@dataclass
class Hallazgo:
    empresa: str
    dominio: str | None
    plataforma: str
    slug_o_url: str
    avisos: int

    def como_fuente(self) -> dict:
        if self.plataforma == "pagina_carrera":
            return {
                "tipo": "pagina_carrera",
                "url": self.slug_o_url,
                "empresa": self.empresa,
                "stealth": False,
            }
        return {
            "tipo": self.plataforma,
            "board": self.slug_o_url,
            "empresa": self.empresa,
            "dominio": self.dominio,
        }


@dataclass
class Reporte:
    encontradas: list[Hallazgo] = field(default_factory=list)
    sin_suerte: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)

    @property
    def total_avisos(self) -> int:
        return sum(h.avisos for h in self.encontradas)


def _sondear_plataforma(plataforma: str, slug: str) -> int | None:
    """Devuelve la cantidad de avisos si el board existe, None si no.

    Un board que existe pero está vacío devuelve 0, que es distinto de None:
    la empresa usa la plataforma, hoy no está buscando. Vale la pena seguirla
    igual — mañana publica y queremos verlo el día uno.
    """
    config = PLATAFORMAS[plataforma]
    try:
        datos = traer_json(config["url"].format(slug=slug), timeout=15)
    except Exception:
        return None
    if not config["existe"](datos):
        return None
    return config["cantidad"](datos)


def _sondear_pagina_carrera(dominio: str, empresa: str) -> Hallazgo | None:
    """Busca JSON-LD de JobPosting en las rutas habituales del sitio."""
    for ruta in RUTAS_CARRERA:
        url = f"https://{dominio}{ruta}"
        try:
            pagina = traer_pagina(url, timeout=15)
        except Exception:
            continue
        try:
            vacantes = parsear_html(pagina, url, empresa)
        except Exception:
            continue
        if vacantes:
            return Hallazgo(empresa, dominio, "pagina_carrera", url, len(vacantes))
    return None


def descubrir_una(
    empresa: str,
    dominio: str | None = None,
    *,
    pausa: float = 0.5,
    probar_pagina: bool = True,
) -> tuple[list[Hallazgo], str | None]:
    """Sondea todas las plataformas para una empresa.

    Devuelve (hallazgos, motivo_si_no_hubo). Puede haber más de un hallazgo:
    algunas empresas migraron de ATS y dejaron el board viejo publicado.
    """
    hallazgos: list[Hallazgo] = []
    slugs = candidatos_de_slug(empresa, dominio)

    for plataforma in PLATAFORMAS:
        for slug in slugs:
            cantidad = _sondear_plataforma(plataforma, slug)
            time.sleep(pausa)
            if cantidad is None:
                continue
            log.info("  %s → %s/%s (%s avisos)", empresa, plataforma, slug, cantidad)
            hallazgos.append(Hallazgo(empresa, dominio, plataforma, slug, cantidad))
            break  # con un slug que funciona alcanza para esta plataforma

    if not hallazgos and probar_pagina and dominio:
        hallazgo = _sondear_pagina_carrera(dominio, empresa)
        if hallazgo:
            log.info("  %s → página de carrera con JSON-LD (%s avisos)", empresa, hallazgo.avisos)
            hallazgos.append(hallazgo)

    if hallazgos:
        return hallazgos, None
    return [], "no publica en ningún ATS conocido ni expone JSON-LD"


def descubrir(
    empresas: list[tuple[str, str | None]], *, pausa: float = 0.5, probar_pagina: bool = True
) -> Reporte:
    reporte = Reporte()
    for i, (empresa, dominio) in enumerate(empresas, 1):
        log.info("[%s/%s] %s", i, len(empresas), empresa)
        try:
            hallazgos, motivo = descubrir_una(
                empresa, dominio, pausa=pausa, probar_pagina=probar_pagina
            )
        except Exception as exc:  # una empresa rota no frena el barrido
            reporte.errores.append(f"{empresa}: {exc}")
            continue
        if hallazgos:
            reporte.encontradas.extend(hallazgos)
        else:
            reporte.sin_suerte.append(f"{empresa} — {motivo}")
    return reporte


def leer_empresas(ruta: Path) -> list[tuple[str, str | None]]:
    """Lee un archivo con una empresa por línea: `Nombre, dominio.com.ar`.

    El dominio es opcional pero ayuda mucho: mejora los slugs candidatos y
    habilita el sondeo de la página de carrera.
    """
    empresas: list[tuple[str, str | None]] = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        partes = [p.strip() for p in re.split(r"[,;\t]", linea, maxsplit=1)]
        nombre = partes[0]
        dominio = partes[1] if len(partes) > 1 and partes[1] else None
        if nombre:
            empresas.append((nombre, dominio))
    return empresas


def escribir_fuentes(reporte: Reporte, ruta: Path, *, fusionar: bool = True) -> int:
    """Escribe fuentes.json. Con `fusionar`, conserva lo que ya estaba.

    Fusionar es el default a propósito: el archivo se edita a mano seguido, y
    un descubrimiento nuevo no debería borrar una fuente afinada a mano.
    """
    existentes: list[dict] = []
    if fusionar and ruta.exists():
        try:
            existentes = json.loads(ruta.read_text(encoding="utf-8")).get("fuentes", [])
        except (json.JSONDecodeError, OSError):
            log.warning("No se pudo leer %s, se reescribe entero", ruta)

    def clave(f: dict) -> tuple:
        return (f.get("tipo"), f.get("board") or f.get("url"))

    por_clave = {clave(f): f for f in existentes if f.get("tipo") != "pagina_carrera" or f.get("url")}
    nuevas = 0
    for hallazgo in reporte.encontradas:
        fuente = hallazgo.como_fuente()
        if clave(fuente) not in por_clave:
            nuevas += 1
        por_clave[clave(fuente)] = fuente

    contenido = {
        "_comentario": (
            "Fuentes de la corrida diaria. Generado por `cli descubrir`; se puede "
            "editar a mano y el descubridor respeta lo que ya está."
        ),
        "fuentes": list(por_clave.values()),
    }
    ruta.write_text(json.dumps(contenido, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return nuevas

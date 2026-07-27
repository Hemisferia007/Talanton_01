"""Extracción y validación de emails de contacto.

De dónde salen: del propio aviso y de la página de carrera de la empresa. Son
datos que la empresa publicó **para que la contacten por trabajo**, que es
exactamente para lo que los usamos. No se compran bases ni se scrapea LinkedIn:
en LatAm la calidad de las bases compradas es mala, los rebotes altos, y el
origen del dato no es auditable si alguien reclama por sus datos personales.

La verificación es por MX (¿el dominio puede recibir mail?). No se hace
verificación SMTP dirigida: es poco confiable, muchos servidores responden que
sí a todo, y el patrón de conexiones te puede terminar en listas de bloqueo,
que es justo lo que el tope de envíos diarios está cuidando.
"""

from __future__ import annotations

import logging
import re
import socket
from dataclasses import dataclass

log = logging.getLogger("talanton.enriquecer")

# Deliberadamente conservador: preferimos perder un email raro antes que
# guardar basura que después rebota y ensucia la reputación del dominio.
_RE_EMAIL = re.compile(
    r"\b[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,}\b"
)

# Emails que aparecen en los sitios pero no sirven para contactar a nadie.
_DESCARTABLES = (
    "noreply",
    "no-reply",
    "nepd",
    "donotreply",
    "example.com",
    "sentry.io",
    "wixpress",
    "@2x",
    ".png",
    ".jpg",
    ".webp",
)

# Prefijos que indican un buzón de área, no de una persona.
_BUZONES_DE_AREA = {
    "rrhh", "recursoshumanos", "recursos.humanos", "hr", "people", "talento",
    "seleccion", "empleos", "jobs", "careers", "postulaciones", "cv",
    "info", "contacto", "contact", "hola", "ventas", "administracion",
    "admin", "soporte", "comercial", "prensa", "marketing",
}


@dataclass
class EmailHallado:
    direccion: str
    fuente_url: str | None = None

    @property
    def dominio(self) -> str:
        return self.direccion.rsplit("@", 1)[1].lower()

    @property
    def usuario(self) -> str:
        return self.direccion.split("@", 1)[0].lower()

    @property
    def es_de_area(self) -> bool:
        """Un buzón de área (rrhh@) llega a alguien, pero no a una persona.

        Sirve para un primer contacto y no para el segundo: por eso el score de
        accesibilidad los cuenta menos que un decisor con nombre.
        """
        limpio = re.sub(r"[._-]", "", self.usuario)
        return limpio in {re.sub(r"[._-]", "", b) for b in _BUZONES_DE_AREA}

    @property
    def nombre_probable(self) -> str | None:
        """De juan.perez@empresa.com deduce 'Juan Perez'.

        Sólo cuando el patrón es claro: no vale inventar un nombre a partir de
        jperez@ porque después se le escribe con ese nombre al cliente.
        """
        if self.es_de_area:
            return None
        partes = re.split(r"[._-]", self.usuario)
        partes = [p for p in partes if p.isalpha() and len(p) >= 3]
        if len(partes) < 2:
            return None
        return " ".join(p.capitalize() for p in partes[:2])


def extraer_emails(texto: str | None, fuente_url: str | None = None) -> list[EmailHallado]:
    """Saca los emails de un texto, sin repetidos y sin basura."""
    if not texto:
        return []

    vistos: set[str] = set()
    hallados: list[EmailHallado] = []
    for bruto in _RE_EMAIL.findall(texto):
        direccion = bruto.strip().strip(".").lower()
        if any(d in direccion for d in _DESCARTABLES):
            continue
        if direccion in vistos:
            continue
        vistos.add(direccion)
        hallados.append(EmailHallado(direccion, fuente_url))
    return hallados


def dominio_recibe_mail(dominio: str, timeout: float = 5.0) -> bool | None:
    """¿El dominio tiene MX o A? None si no se pudo determinar.

    Devolver None y no False cuando falla la consulta es importante: un timeout
    de DNS no es prueba de que el dominio esté muerto, y descartar un contacto
    bueno por eso es peor que quedarse con la duda.
    """
    try:
        socket.setdefaulttimeout(timeout)
        # Sin dependencia de DNS: si el dominio resuelve, casi siempre recibe
        # mail. La verificación MX estricta necesitaría dnspython.
        try:
            import dns.resolver  # type: ignore

            respuesta = dns.resolver.resolve(dominio, "MX", lifetime=timeout)
            return len(respuesta) > 0
        except ImportError:
            socket.getaddrinfo(dominio, None)
            return True
    except (socket.gaierror, socket.timeout, OSError):
        return False
    except Exception as exc:
        log.debug("No se pudo verificar %s: %s", dominio, exc)
        return None
    finally:
        socket.setdefaulttimeout(None)


def elegir_mejor(emails: list[EmailHallado], dominio_empresa: str | None) -> EmailHallado | None:
    """El más útil para un primer contacto.

    Orden: persona en el dominio de la empresa > buzón de RRHH en el dominio >
    cualquiera del dominio > el resto. Un email personal en el dominio propio
    es lo que más chance tiene de que conteste alguien con capacidad de decidir.
    """
    if not emails:
        return None

    def puntaje(e: EmailHallado) -> tuple:
        del_dominio = bool(dominio_empresa and e.dominio.endswith(dominio_empresa.lower()))
        es_rrhh = re.sub(r"[._-]", "", e.usuario) in {
            "rrhh", "recursoshumanos", "seleccion", "empleos", "talento", "hr", "people"
        }
        return (del_dominio, not e.es_de_area, es_rrhh)

    return max(emails, key=puntaje)

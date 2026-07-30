"""Editar a mano la ficha de una empresa: contactos y datos firmográficos.

Todo esto se podía cargar por importación o por Hunter, pero no a mano, y a
mano es como llega la mitad de la información real: alguien te pasa el mail del
gerente por WhatsApp, ves el LinkedIn del director, te enterás de que la empresa
tiene 300 personas y no 80.

Sin un formulario, ese dato se pierde o termina en un Excel paralelo — que es
exactamente el problema que el CRM venía a resolver.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .models import Contacto, Empresa
from .normalize import normalizar_dominio
from .services import asegurar_lead, perfil, recalcular_lead

log = logging.getLogger("talanton.fichas")


class ErrorFicha(ValueError):
    """Dato inválido, con un texto para mostrar en pantalla."""


def _repuntuar(session: Session, empresa: Empresa) -> None:
    session.flush()
    session.refresh(empresa)
    recalcular_lead(session, asegurar_lead(session, empresa), perfil(session))


def agregar_contacto(
    session: Session,
    empresa: Empresa,
    *,
    nombre: str,
    cargo: str | None = None,
    email: str | None = None,
    telefono: str | None = None,
    linkedin_url: str | None = None,
    es_decisor: bool = False,
    procedencia: str | None = None,
) -> Contacto:
    """Carga un contacto y vuelve a puntuar el lead."""
    nombre = (nombre or "").strip()
    if not nombre:
        raise ErrorFicha("Falta el nombre del contacto.")

    email = (email or "").strip().lower() or None
    if email and "@" not in email:
        raise ErrorFicha(f"«{email}» no parece un email válido.")

    if email and any((c.email or "").lower() == email for c in empresa.contactos):
        raise ErrorFicha(f"{email} ya está cargado en esta empresa.")

    # Un solo decisor por empresa: si se marca uno nuevo, el anterior deja de
    # serlo. Dos decisores es lo mismo que ninguno a la hora de saber a quién
    # escribirle.
    if es_decisor:
        for otro in empresa.contactos:
            otro.es_decisor = False

    contacto = Contacto(
        nombre=nombre,
        cargo=(cargo or "").strip() or None,
        email=email,
        telefono=(telefono or "").strip() or None,
        linkedin_url=(linkedin_url or "").strip() or None,
        es_decisor=es_decisor,
        # Sin procedencia un dato de contacto de un tercero no se puede
        # defender; «cargado a mano» es una respuesta válida y auditable.
        fuente_url=(procedencia or "").strip() or "cargado a mano",
    )
    empresa.contactos.append(contacto)
    _repuntuar(session, empresa)
    return contacto


def marcar_decisor(session: Session, empresa: Empresa, contacto_id: int) -> None:
    """Mueve la marca de decisor a otro contacto ya cargado."""
    if not any(c.id == contacto_id for c in empresa.contactos):
        raise ErrorFicha("Ese contacto no es de esta empresa.")
    for c in empresa.contactos:
        c.es_decisor = c.id == contacto_id
    _repuntuar(session, empresa)


def borrar_contacto(session: Session, empresa: Empresa, contacto_id: int) -> None:
    """Borra un contacto. Hace falta de verdad: si alguien pide la baja de sus
    datos, tiene que poder hacerse desde la pantalla y en el momento."""
    contacto = next((c for c in empresa.contactos if c.id == contacto_id), None)
    if contacto is None:
        raise ErrorFicha("Ese contacto no es de esta empresa.")
    empresa.contactos.remove(contacto)
    session.delete(contacto)
    _repuntuar(session, empresa)


def actualizar_empresa(
    session: Session,
    empresa: Empresa,
    *,
    dominio: str | None = None,
    industria: str | None = None,
    dotacion: str | None = None,
    ciudad: str | None = None,
    tiene_equipo_ta: bool | None = None,
) -> Empresa:
    """Corrige los datos firmográficos, que son el 40% del score.

    La dotación pesa en capacidad de pago y decide a qué cargo apuntar; la
    industria alimenta el fit contra el ICP. Con esos dos en «Sin datos» el
    score de una empresa no dice mucho.
    """
    if dominio is not None:
        nuevo = normalizar_dominio(dominio) if dominio.strip() else None
        if nuevo and nuevo != empresa.dominio:
            from sqlalchemy import select

            ocupado = session.scalar(
                select(Empresa).where(Empresa.dominio == nuevo, Empresa.id != empresa.id)
            )
            if ocupado is not None:
                raise ErrorFicha(
                    f"El dominio {nuevo} ya está en «{ocupado.nombre}». "
                    "Si son la misma empresa, quedó duplicada."
                )
        empresa.dominio = nuevo

    if industria is not None:
        empresa.industria = industria.strip() or None
    if ciudad is not None:
        empresa.ciudad = ciudad.strip() or None
    if tiene_equipo_ta is not None:
        empresa.tiene_equipo_ta = tiene_equipo_ta

    if dotacion is not None:
        texto = dotacion.strip()
        if not texto:
            empresa.dotacion_estimada = None
        else:
            try:
                valor = int(texto.replace(".", "").replace(",", ""))
            except ValueError as exc:
                raise ErrorFicha(f"«{texto}» no es un número de empleados.") from exc
            if valor < 1:
                raise ErrorFicha("La dotación tiene que ser mayor a cero.")
            empresa.dotacion_estimada = valor

    _repuntuar(session, empresa)
    return empresa

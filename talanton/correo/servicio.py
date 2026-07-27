"""Orquestación del envío: cuentas, borradores y el efecto sobre el lead.

Mandar un mail no es sólo un POST a Gmail: tiene que quedar en el timeline del
lead, marcar la fecha de contacto y mover el estado. Si eso no pasa solo, el
comercial termina llevando el seguimiento en su cabeza.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import LIMITE_ENVIOS_DIARIOS
from ..models import (
    CuentaGmail,
    Direccion,
    EstadoLead,
    EstadoMensaje,
    Lead,
    Mensaje,
    ahora,
)
from ..services import mover_lead, perfil, registrar_actividad
from . import cripto, gmail, plantillas

log = logging.getLogger("talanton.correo")


class ErrorEnvio(RuntimeError):
    """Problema al enviar, con un mensaje que se le puede mostrar al usuario."""


# --- Cuentas -----------------------------------------------------------------


def guardar_cuenta(session: Session, credenciales: gmail.Credenciales) -> CuentaGmail:
    if not credenciales.email:
        raise ErrorEnvio("Google no devolvió el email de la cuenta.")

    cuenta = session.scalar(
        select(CuentaGmail).where(CuentaGmail.email == credenciales.email)
    )
    if cuenta is None:
        cuenta = CuentaGmail(email=credenciales.email)
        session.add(cuenta)

    cuenta.refresh_token_cifrado = cripto.cifrar(credenciales.refresh_token or "")
    cuenta.access_token = credenciales.access_token
    cuenta.access_token_expira = credenciales.expira_en.replace(tzinfo=None)
    cuenta.activa = True
    cuenta.ultimo_error = None
    session.flush()
    return cuenta


def listar_cuentas(session: Session) -> list[CuentaGmail]:
    return list(
        session.scalars(
            select(CuentaGmail).where(CuentaGmail.activa.is_(True)).order_by(CuentaGmail.email)
        ).all()
    )


def desconectar(session: Session, cuenta: CuentaGmail) -> None:
    """Revoca en Google y borra el token de nuestro lado.

    Los mensajes ya enviados se conservan: son el historial del lead.
    """
    try:
        gmail.revocar(cripto.descifrar(cuenta.refresh_token_cifrado))
    except (ValueError, gmail.ErrorGmail) as exc:
        log.warning("Revocación best-effort falló para %s: %s", cuenta.email, exc)

    for mensaje in cuenta.mensajes:
        mensaje.cuenta_id = None
    cuenta.activa = False
    cuenta.refresh_token_cifrado = ""
    cuenta.access_token = None
    session.flush()


def _access_token_vigente(session: Session, cuenta: CuentaGmail) -> str:
    """Devuelve un access token usable, renovándolo si está por vencer."""
    margen = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=2)
    if cuenta.access_token and cuenta.access_token_expira and cuenta.access_token_expira > margen:
        return cuenta.access_token

    if not cuenta.refresh_token_cifrado:
        raise ErrorEnvio(f"La cuenta {cuenta.email} está desconectada. Volvé a conectarla.")

    try:
        nuevas = gmail.refrescar(cripto.descifrar(cuenta.refresh_token_cifrado))
    except (ValueError, gmail.ErrorGmail) as exc:
        cuenta.ultimo_error = str(exc)
        session.flush()
        raise ErrorEnvio(str(exc)) from exc

    cuenta.access_token = nuevas.access_token
    cuenta.access_token_expira = nuevas.expira_en.replace(tzinfo=None)
    session.flush()
    return nuevas.access_token


def enviados_hoy(session: Session, cuenta: CuentaGmail) -> int:
    inicio = ahora().replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        session.scalar(
            select(func.count())
            .select_from(Mensaje)
            .where(
                Mensaje.cuenta_id == cuenta.id,
                Mensaje.estado == EstadoMensaje.ENVIADO,
                Mensaje.enviado_en >= inicio,
            )
        )
        or 0
    )


# --- Redacción ---------------------------------------------------------------


def contexto_de(session: Session, lead: Lead, cuenta: CuentaGmail | None = None):
    p = perfil(session)
    firma = (cuenta.firma if cuenta and cuenta.firma else None) or p.nombre
    return plantillas.construir_contexto(lead, consultora=p.nombre, firma=firma)


def borrador(
    session: Session, lead: Lead, clave: str | None = None, cuenta: CuentaGmail | None = None
) -> dict:
    """Devuelve el mail prellenado y las plantillas que aplican a este lead."""
    contexto = contexto_de(session, lead, cuenta)
    opciones = plantillas.disponibles(contexto)
    elegida = plantillas.por_clave(clave) if clave else None
    if elegida is None or elegida not in opciones:
        elegida = opciones[0]

    asunto, cuerpo = plantillas.redactar(elegida, contexto)
    destinatario = contexto.contacto.email if contexto.contacto else ""
    return {
        "plantilla": elegida,
        "opciones": opciones,
        "para": destinatario or "",
        "asunto": asunto,
        "cuerpo": cuerpo,
        "contacto": contexto.contacto,
    }


# --- Envío -------------------------------------------------------------------


def enviar(
    session: Session,
    lead: Lead,
    cuenta: CuentaGmail,
    *,
    para: str,
    asunto: str,
    cuerpo: str,
    plantilla: str | None = None,
    autor: str | None = None,
    cliente=gmail,
) -> Mensaje:
    """Manda el mail y deja el rastro en el lead.

    `cliente` se inyecta para poder testear sin tocar la red.
    """
    para = (para or "").strip()
    if "@" not in para:
        raise ErrorEnvio("Falta una dirección de destino válida.")
    if not asunto.strip():
        raise ErrorEnvio("El asunto no puede quedar vacío.")

    usados = enviados_hoy(session, cuenta)
    if usados >= LIMITE_ENVIOS_DIARIOS:
        raise ErrorEnvio(
            f"{cuenta.email} ya mandó {usados} mails hoy, el tope configurado es "
            f"{LIMITE_ENVIOS_DIARIOS}. El límite existe para no quemar la reputación "
            "del dominio."
        )

    mensaje = Mensaje(
        lead_id=lead.id,
        cuenta_id=cuenta.id,
        para=para,
        asunto=asunto.strip(),
        cuerpo=cuerpo,
        plantilla=plantilla,
    )
    session.add(mensaje)
    session.flush()

    token = _access_token_vigente(session, cuenta)
    try:
        resultado = cliente.enviar(
            token,
            de=cuenta.email,
            nombre_de=cuenta.nombre_remitente,
            para=para,
            asunto=asunto.strip(),
            cuerpo=cuerpo,
        )
    except gmail.ErrorGmail as exc:
        # El mensaje fallido queda guardado: sirve para reintentar y para saber
        # que se intentó contactar.
        mensaje.estado = EstadoMensaje.ERROR
        mensaje.error = str(exc)
        cuenta.ultimo_error = str(exc)
        session.flush()
        raise ErrorEnvio(str(exc)) from exc

    mensaje.estado = EstadoMensaje.ENVIADO
    mensaje.enviado_en = ahora()
    mensaje.gmail_message_id = resultado.get("id")
    mensaje.gmail_thread_id = resultado.get("threadId")
    cuenta.ultimo_error = None

    registrar_actividad(
        session,
        lead,
        f"Mail enviado a {para}: «{mensaje.asunto}»",
        tipo="contacto",
        autor=autor or cuenta.email,
    )
    # Un lead al que ya le escribimos no puede seguir figurando como nuevo.
    if lead.estado == EstadoLead.NUEVO:
        mover_lead(session, lead, EstadoLead.CONTACTADO, autor=autor or cuenta.email)

    session.flush()
    return mensaje


def registrar_respuesta(
    session: Session,
    lead: Lead,
    *,
    cuerpo: str,
    de: str | None = None,
    asunto: str | None = None,
    autor: str | None = None,
) -> Mensaje:
    """Suma al hilo una respuesta del cliente.

    Con el permiso `gmail.send` no podemos leer la casilla, así que las
    respuestas se pegan a mano. El hilo se guarda con la misma forma que
    tendría si las trajera la API: cuando se sume `gmail.readonly`, cambia de
    dónde salen los datos, no cómo se muestran.
    """
    cuerpo = (cuerpo or "").strip()
    if not cuerpo:
        raise ErrorEnvio("La respuesta no puede quedar vacía.")

    ultimo_saliente = next(
        (m for m in reversed(lead.mensajes) if m.direccion == Direccion.SALIENTE), None
    )
    if not de:
        contacto = next((c for c in lead.empresa.contactos if c.email), None)
        de = (ultimo_saliente.para if ultimo_saliente else None) or (
            contacto.email if contacto else lead.empresa.nombre
        )

    mensaje = Mensaje(
        lead_id=lead.id,
        direccion=Direccion.ENTRANTE,
        estado=EstadoMensaje.RECIBIDO,
        de=de,
        para=ultimo_saliente.cuenta.email if ultimo_saliente and ultimo_saliente.cuenta else "",
        asunto=(asunto or "").strip()
        or (f"Re: {ultimo_saliente.asunto}" if ultimo_saliente else "Respuesta"),
        cuerpo=cuerpo,
        enviado_en=ahora(),
        gmail_thread_id=ultimo_saliente.gmail_thread_id if ultimo_saliente else None,
    )
    session.add(mensaje)

    registrar_actividad(
        session, lead, f"Respondió {de}", tipo="contacto", autor=autor
    )
    # Que respondan es la señal más fuerte del embudo: el lead deja de estar
    # en "le escribimos y veremos".
    if lead.estado in (EstadoLead.NUEVO, EstadoLead.CONTACTADO):
        mover_lead(session, lead, EstadoLead.EN_CONVERSACION, autor=autor)

    session.flush()
    return mensaje

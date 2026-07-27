"""Cliente de Gmail: OAuth2 y envío.

Se habla directo con la API REST en vez de usar el SDK de Google: son tres
endpoints, se ve exactamente qué se manda, y evita arrastrar tres dependencias
pesadas para una función.

Permiso pedido: `gmail.send`. Deja mandar en nombre de la persona, no leer su
casilla. Si más adelante se quiere detectar respuestas hará falta sumar
`gmail.readonly`, que es un scope restringido y exige verificación de Google
salvo que la app sea interna del Workspace.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr
from urllib.parse import urlencode

import httpx

from ..config import (
    GMAIL_SCOPES,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    OAUTH_REDIRECT_URI,
)

log = logging.getLogger("talanton.correo")

URL_AUTORIZACION = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKEN = "https://oauth2.googleapis.com/token"
URL_ENVIO = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
URL_REVOCAR = "https://oauth2.googleapis.com/revoke"


class ErrorGmail(RuntimeError):
    """Falla al hablar con Google. El mensaje es apto para mostrar en la UI."""


@dataclass
class Credenciales:
    access_token: str
    expira_en: datetime
    refresh_token: str | None = None
    email: str | None = None


def url_de_autorizacion(estado: str) -> str:
    """Primer paso: adónde mandar a la persona para que autorice.

    `access_type=offline` + `prompt=consent` son los que garantizan que Google
    devuelva un refresh token; sin ellos sólo llega un access token de una hora
    y habría que reconectar la cuenta todos los días.
    """
    if not GOOGLE_CLIENT_ID:
        raise ErrorGmail(
            "Falta configurar TALANTON_GOOGLE_CLIENT_ID. Ver docs/gmail.md."
        )
    parametros = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": GMAIL_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": estado,
    }
    return f"{URL_AUTORIZACION}?{urlencode(parametros)}"


def _email_del_id_token(id_token: str | None) -> str | None:
    """Lee el email del id_token.

    No se valida la firma a propósito: el token viene del endpoint de Google
    por TLS en respuesta directa a nuestro request, no de un tercero.
    """
    if not id_token:
        return None
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("email")
    except (IndexError, ValueError, json.JSONDecodeError):
        return None


def _pedir_token(datos: dict) -> dict:
    try:
        respuesta = httpx.post(URL_TOKEN, data=datos, timeout=30)
    except httpx.HTTPError as exc:
        raise ErrorGmail(f"No se pudo contactar a Google: {exc}") from exc

    if respuesta.status_code != 200:
        detalle = respuesta.json().get("error_description") if respuesta.text else ""
        raise ErrorGmail(f"Google rechazó la credencial: {detalle or respuesta.text[:200]}")
    return respuesta.json()


def canjear_codigo(codigo: str) -> Credenciales:
    """Segundo paso: el código de la vuelta del consent screen por tokens."""
    datos = _pedir_token(
        {
            "code": codigo,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    )
    if not datos.get("refresh_token"):
        raise ErrorGmail(
            "Google no devolvió refresh token. Suele pasar cuando la cuenta ya "
            "había autorizado la app: revocá el acceso en "
            "https://myaccount.google.com/permissions y volvé a conectar."
        )
    return Credenciales(
        access_token=datos["access_token"],
        refresh_token=datos["refresh_token"],
        expira_en=datetime.now(timezone.utc) + timedelta(seconds=datos.get("expires_in", 3600)),
        email=_email_del_id_token(datos.get("id_token")),
    )


def refrescar(refresh_token: str) -> Credenciales:
    datos = _pedir_token(
        {
            "refresh_token": refresh_token,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "grant_type": "refresh_token",
        }
    )
    return Credenciales(
        access_token=datos["access_token"],
        expira_en=datetime.now(timezone.utc) + timedelta(seconds=datos.get("expires_in", 3600)),
    )


def armar_mime(
    *, de: str, nombre_de: str | None, para: str, asunto: str, cuerpo: str
) -> str:
    """Arma el MIME y lo codifica como espera la API (base64 URL-safe)."""
    mensaje = EmailMessage()
    mensaje["To"] = para
    mensaje["From"] = formataddr((nombre_de, de)) if nombre_de else de
    mensaje["Subject"] = asunto
    mensaje.set_content(cuerpo)
    return base64.urlsafe_b64encode(mensaje.as_bytes()).decode()


def enviar(
    access_token: str,
    *,
    de: str,
    nombre_de: str | None,
    para: str,
    asunto: str,
    cuerpo: str,
) -> dict:
    """Manda el mail. Devuelve el id de mensaje y de hilo que asigna Gmail."""
    crudo = armar_mime(de=de, nombre_de=nombre_de, para=para, asunto=asunto, cuerpo=cuerpo)
    try:
        respuesta = httpx.post(
            URL_ENVIO,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": crudo},
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise ErrorGmail(f"No se pudo contactar a Gmail: {exc}") from exc

    if respuesta.status_code == 401:
        raise ErrorGmail("El permiso de Gmail expiró. Reconectá la cuenta.")
    if respuesta.status_code == 403:
        raise ErrorGmail(
            "Gmail rechazó el envío (403). Suele ser el límite diario de la cuenta "
            "o un permiso faltante."
        )
    if respuesta.status_code != 200:
        raise ErrorGmail(f"Gmail devolvió {respuesta.status_code}: {respuesta.text[:200]}")

    datos = respuesta.json()
    return {"id": datos.get("id"), "threadId": datos.get("threadId")}


def revocar(token: str) -> None:
    """Mejor esfuerzo: si falla, igual borramos la cuenta de nuestro lado."""
    try:
        httpx.post(URL_REVOCAR, data={"token": token}, timeout=15)
    except httpx.HTTPError as exc:
        log.warning("No se pudo revocar el token en Google: %s", exc)

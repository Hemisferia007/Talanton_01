"""Cifrado de los refresh tokens.

Un refresh token de Gmail es una credencial de larga vida: con él se manda mail
en nombre de la persona hasta que lo revoque. No puede quedar en texto plano en
un SQLite que alguien copia junto con un backup.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from ..config import DATA_DIR, SECRET_KEY

log = logging.getLogger("talanton.correo")

ARCHIVO_CLAVE = DATA_DIR / "secret.key"


def _clave() -> bytes:
    """Toma la clave del entorno o genera una en disco, sólo legible por el dueño."""
    if SECRET_KEY:
        return SECRET_KEY.encode()

    if ARCHIVO_CLAVE.exists():
        return ARCHIVO_CLAVE.read_bytes().strip()

    clave = Fernet.generate_key()
    ARCHIVO_CLAVE.write_bytes(clave)
    os.chmod(ARCHIVO_CLAVE, 0o600)
    log.warning(
        "Clave de cifrado generada en %s. Para desplegar en varios procesos o "
        "máquinas, pasala por TALANTON_SECRET_KEY.",
        ARCHIVO_CLAVE,
    )
    return clave


def cifrar(texto: str) -> str:
    return Fernet(_clave()).encrypt(texto.encode()).decode()


def descifrar(texto: str) -> str:
    """Devuelve el valor original. Lanza ValueError si la clave no corresponde."""
    try:
        return Fernet(_clave()).decrypt(texto.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise ValueError(
            "No se pudo descifrar el token: la clave cambió o el dato está corrupto. "
            "Hay que volver a conectar la cuenta de Gmail."
        ) from exc


def borrar_clave_local() -> None:
    """Sólo para tests: fuerza que la próxima llamada genere una clave nueva."""
    Path(ARCHIVO_CLAVE).unlink(missing_ok=True)

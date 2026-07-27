"""Autenticación.

Hash con `hashlib.scrypt` de la biblioteca estándar: es memory-hard, está
recomendado por OWASP y evita sumar una dependencia sólo para esto. Los
parámetros van dentro del hash, así que se pueden endurecer más adelante sin
invalidar las contraseñas ya guardadas.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Usuario, ahora

log = logging.getLogger("talanton.auth")

# Parámetros de scrypt. N=2^15 tarda ~100ms por verificación en hardware
# modesto: suficiente para frenar fuerza bruta sin que el login se note lento.
_N = 2**15
_R = 8
_P = 1
_LARGO = 32
# scrypt necesita 128 * N * r * p bytes ≈ 32 MiB con estos parámetros, justo el
# tope que OpenSSL aplica por defecto. Sin subirlo, la derivación falla.
_MAXMEM = 128 * 1024 * 1024


def hashear(password: str) -> str:
    salt = secrets.token_bytes(16)
    derivado = hashlib.scrypt(
        password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_LARGO, maxmem=_MAXMEM
    )
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${derivado.hex()}"


def verificar(password: str, hash_guardado: str) -> bool:
    try:
        algoritmo, n, r, p, salt_hex, esperado_hex = hash_guardado.split("$")
        if algoritmo != "scrypt":
            return False
        derivado = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(esperado_hex) // 2,
            maxmem=_MAXMEM,
        )
    except (ValueError, TypeError):
        return False
    # Comparación en tiempo constante: una comparación normal filtra
    # información sobre el hash a través del tiempo de respuesta.
    return hmac.compare_digest(derivado.hex(), esperado_hex)


def crear_usuario(session: Session, email: str, nombre: str, password: str) -> Usuario:
    email = email.strip().lower()
    if len(password) < 10:
        raise ValueError("La contraseña tiene que tener al menos 10 caracteres.")
    if session.scalar(select(Usuario).where(Usuario.email == email)):
        raise ValueError(f"Ya existe un usuario con el email {email}.")

    usuario = Usuario(email=email, nombre=nombre.strip() or email, password_hash=hashear(password))
    session.add(usuario)
    session.flush()
    return usuario


def cambiar_password(session: Session, usuario: Usuario, password: str) -> None:
    if len(password) < 10:
        raise ValueError("La contraseña tiene que tener al menos 10 caracteres.")
    usuario.password_hash = hashear(password)
    session.flush()


def autenticar(session: Session, email: str, password: str) -> Usuario | None:
    """Devuelve el usuario si las credenciales son válidas, None si no.

    No distingue entre "no existe" y "contraseña incorrecta": esa diferencia
    le sirve a quien quiere enumerar cuentas, a nadie más.
    """
    usuario = session.scalar(
        select(Usuario).where(Usuario.email == email.strip().lower())
    )
    if usuario is None or not usuario.activo:
        # Se hashea igual para que el tiempo de respuesta no delate si el
        # usuario existe.
        hashear(password)
        return None
    if not verificar(password, usuario.password_hash):
        return None

    usuario.ultimo_ingreso = ahora()
    session.flush()
    return usuario


def hay_usuarios(session: Session) -> bool:
    return bool(session.scalar(select(func.count()).select_from(Usuario)))


def crear_admin_inicial(session: Session) -> Usuario | None:
    """Crea el primer usuario desde variables de entorno, si no hay ninguno.

    Existe porque en un PaaS no siempre hay una consola a mano. Sólo actúa con
    la tabla vacía: si ya hay usuarios, cambiar las variables no puede crear
    uno nuevo ni pisar contraseñas.
    """
    from .config import ADMIN_EMAIL, ADMIN_NOMBRE, ADMIN_PASSWORD

    if not (ADMIN_EMAIL and ADMIN_PASSWORD) or hay_usuarios(session):
        return None

    try:
        usuario = crear_usuario(
            session, ADMIN_EMAIL, ADMIN_NOMBRE or ADMIN_EMAIL, ADMIN_PASSWORD
        )
    except ValueError as exc:
        log.error("No se pudo crear el usuario inicial: %s", exc)
        return None

    session.commit()
    log.warning(
        "Usuario inicial %s creado desde el entorno. Borrá TALANTON_ADMIN_EMAIL "
        "y TALANTON_ADMIN_PASSWORD ahora que ya podés entrar.",
        usuario.email,
    )
    return usuario

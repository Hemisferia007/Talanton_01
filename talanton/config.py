"""Configuración de la aplicación."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("TALANTON_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("TALANTON_DATABASE_URL", f"sqlite:///{DATA_DIR / 'talanton.db'}")

# Mercados en los que opera la consultora. Determina qué conectores corren y
# cómo se normalizan las ubicaciones.
PAISES = ["AR", "UY", "CL", "MX", "CO", "PE", "BR"]
PAIS_NOMBRE = {
    "AR": "Argentina",
    "UY": "Uruguay",
    "CL": "Chile",
    "MX": "México",
    "CO": "Colombia",
    "PE": "Perú",
    "BR": "Brasil",
}

# Umbral a partir del cual un lead entra en la cola de trabajo del comercial.
SCORE_MINIMO_ALERTA = 60

# --- Gmail -------------------------------------------------------------------
# Credenciales del proyecto de Google Cloud. Ver docs/gmail.md para el alta.
GOOGLE_CLIENT_ID = os.getenv("TALANTON_GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("TALANTON_GOOGLE_CLIENT_SECRET", "")
OAUTH_REDIRECT_URI = os.getenv(
    "TALANTON_OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/oauth/google/callback"
)
# `gmail.send` es el permiso mínimo: deja mandar, no leer la casilla.
GMAIL_SCOPES = "https://www.googleapis.com/auth/gmail.send openid email"

# Clave para cifrar los refresh tokens en la base. Si no viene por entorno se
# genera una en data/ con permisos 600 — ver correo/cripto.py.
SECRET_KEY = os.getenv("TALANTON_SECRET_KEY", "")

# --- Apify ---------------------------------------------------------------
# Para portales sin API pública, sobre todo LinkedIn Jobs. Ver docs/linkedin.md.
APIFY_TOKEN = os.getenv("TALANTON_APIFY_TOKEN", "")


def apify_configurado() -> bool:
    return bool(APIFY_TOKEN)


# --- Hunter.io ---------------------------------------------------------------
# Busca la persona de RRHH de una empresa a partir de su dominio. A diferencia
# de Apollo, la API anda en el plan gratuito (25 búsquedas por mes).
HUNTER_API_KEY = os.getenv("TALANTON_HUNTER_API_KEY", "")


def hunter_configurado() -> bool:
    return bool(HUNTER_API_KEY)


# --- Apollo ------------------------------------------------------------------
# Base de empresas y decisores. Buscar es gratis; revelar un email consume un
# crédito de la cuenta. Ver docs/apollo.md.
APOLLO_API_KEY = os.getenv("TALANTON_APOLLO_API_KEY", "")


def apollo_configurado() -> bool:
    return bool(APOLLO_API_KEY)


# --- Asistente (Claude) ------------------------------------------------------
# Lee el lead y opina si conviene contactarlo, y redacta respuestas dentro del
# hilo. Es opcional: sin clave, la app funciona igual y los botones no aparecen.
ANTHROPIC_API_KEY = os.getenv("TALANTON_ANTHROPIC_API_KEY", "") or os.getenv(
    "ANTHROPIC_API_KEY", ""
)
# Cada lectura de un lead cuesta unos centavos. `claude-sonnet-5` sale bastante
# menos y alcanza para leads simples; para decidir si vale la pena una búsqueda
# difícil conviene el de arriba. Ver docs/asistente.md.
ASISTENTE_MODELO = os.getenv("TALANTON_ASISTENTE_MODELO", "claude-opus-5")


def asistente_configurado() -> bool:
    return bool(ANTHROPIC_API_KEY)


# --- Sesiones ----------------------------------------------------------------
# Firma la cookie de sesión. Si cambia, se cierran todas las sesiones abiertas.
SESSION_SECRET = os.getenv("TALANTON_SESSION_SECRET", "")
# Duración de la sesión. Una jornada larga: se entra a la mañana y no molesta.
SESSION_MAX_AGE = int(os.getenv("TALANTON_SESSION_MAX_AGE", str(12 * 3600)))
# En producción la cookie tiene que viajar sólo por HTTPS.
COOKIES_SEGURAS = os.getenv("TALANTON_COOKIES_SEGURAS", "").lower() in ("1", "true", "si")

# Tope diario de envíos por cuenta. Gmail corta en 500 (cuentas gratuitas) y
# 2000 (Workspace); quedarse bien por debajo protege la reputación del dominio.
LIMITE_ENVIOS_DIARIOS = int(os.getenv("TALANTON_LIMITE_ENVIOS_DIARIOS", "40"))

# --- Primer usuario ----------------------------------------------------------
# En un PaaS no siempre hay consola para correr `cli usuario`. Si estas dos
# variables están y la tabla de usuarios está vacía, se crea el primer usuario
# al arrancar. Conviene borrarlas apenas se pudo entrar.
ADMIN_EMAIL = os.getenv("TALANTON_ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.getenv("TALANTON_ADMIN_PASSWORD", "")
ADMIN_NOMBRE = os.getenv("TALANTON_ADMIN_NOMBRE", "")


def gmail_configurado() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def verificar_configuracion_de_produccion() -> None:
    """Falla el arranque si falta algo que después rompe de forma silenciosa.

    `COOKIES_SEGURAS` se toma como señal de "esto está en producción". Sin un
    secreto de sesión fijo, cada reinicio genera uno nuevo y desloguea a todo
    el mundo sin ningún error visible; sin clave de cifrado estable, los
    tokens de Gmail guardados dejan de poder descifrarse.
    """
    if not COOKIES_SEGURAS:
        return

    faltantes = []
    if not SESSION_SECRET:
        faltantes.append("TALANTON_SESSION_SECRET")
    if not SECRET_KEY:
        faltantes.append("TALANTON_SECRET_KEY")

    if faltantes:
        raise RuntimeError(
            "Faltan variables obligatorias en producción: "
            + ", ".join(faltantes)
            + ". Generalas con los comandos de .env.ejemplo y cargalas en el "
            "entorno del servicio. Ver docs/despliegue.md."
        )


def secreto_de_sesion() -> str:
    """Devuelve el secreto de sesión, generando uno efímero si falta.

    En desarrollo alcanza con uno al vuelo: sólo implica que reiniciar el
    servidor cierra las sesiones. En producción hay que fijarlo por entorno,
    porque con varios procesos cada uno tendría el suyo y nadie quedaría logueado.
    """
    if SESSION_SECRET:
        return SESSION_SECRET
    if SECRET_KEY:
        return SECRET_KEY
    import secrets as _secrets

    return _secrets.token_urlsafe(32)

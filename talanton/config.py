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

# Tope diario de envíos por cuenta. Gmail corta en 500 (cuentas gratuitas) y
# 2000 (Workspace); quedarse bien por debajo protege la reputación del dominio.
LIMITE_ENVIOS_DIARIOS = int(os.getenv("TALANTON_LIMITE_ENVIOS_DIARIOS", "40"))

def gmail_configurado() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

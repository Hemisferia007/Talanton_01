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

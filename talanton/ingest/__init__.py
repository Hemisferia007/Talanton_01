"""Capa de ingesta. Tres carriles, del más barato al más caro:

1. APIs de ATS (`ats.py`) — JSON público y estable, sin anti-bot.
2. JSON-LD en páginas de carrera (`jsonld.py`) — un parser para cientos de sitios.
3. Portales HTML — requiere Scrapling con selectores adaptativos y stealth.
"""

from .base import Conector, VacanteCruda

__all__ = ["Conector", "VacanteCruda"]

"""Asistente: lee un lead con Claude y opina, o redacta el próximo mail.

Es una capa opcional sobre el CRM. Sin clave de API la app funciona igual y los
botones no aparecen: lo que decide a quién contactar sigue siendo el score
determinístico, que el comercial puede explicarle al cliente sin decir "lo dijo
la inteligencia artificial".
"""

from . import conviene, escribir, expediente
from .cliente import Cliente, ErrorAsistente, disponible, motivo_no_disponible

__all__ = [
    "Cliente",
    "ErrorAsistente",
    "disponible",
    "motivo_no_disponible",
    "conviene",
    "escribir",
    "expediente",
]

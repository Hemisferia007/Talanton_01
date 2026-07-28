"""Apollo.io: buscar empresas y decisores, y traerlos como leads.

Dos pasos separados a propósito, porque cuestan distinto: **buscar es gratis y
no destapa emails; revelar consume créditos**. Ver `cliente.py`.
"""

from . import busqueda, cliente
from .cliente import Cliente, ErrorApollo, Persona, configurado

__all__ = ["busqueda", "cliente", "Cliente", "ErrorApollo", "Persona", "configurado"]

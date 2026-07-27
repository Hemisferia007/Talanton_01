"""Normalización y deduplicación.

Es el punto más subestimado del pipeline: si el comercial ve la misma empresa
seis veces con seis nombres distintos, deja de abrir la herramienta. Y sin
normalizar el rol, las señales de reposteo y recurrencia directamente no existen.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

from .models import Seniority

# Sufijos societarios de AR y LatAm que no aportan a la identidad de la empresa.
_SUFIJOS_SOCIETARIOS = [
    "sociedad anonima",
    "sociedad de responsabilidad limitada",
    "s a s",
    "s r l",
    "s a",
    "sas",
    "srl",
    "sa",
    "spa",
    "ltda",
    "limitada",
    "cia",
    "y cia",
    "inc",
    "llc",
    "corp",
    "ltd",
    "gmbh",
    "bv",
    "eireli",
    "me",
]

_DOMINIOS_GENERICOS = {
    "gmail.com",
    "hotmail.com",
    "outlook.com",
    "yahoo.com",
    "yahoo.com.ar",
    "live.com",
    "icloud.com",
}


def sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


def normalizar_nombre_empresa(nombre: str) -> str:
    """'Grupo Logístico del Sur S.R.L.' -> 'grupo logistico del sur'."""
    texto = sin_acentos(nombre or "").lower()
    texto = re.sub(r"[^\w\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    for sufijo in sorted(_SUFIJOS_SOCIETARIOS, key=len, reverse=True):
        if texto.endswith(" " + sufijo):
            texto = texto[: -len(sufijo)].strip()
    return texto


def normalizar_dominio(valor: str | None) -> str | None:
    """Extrae el dominio raíz de una URL o email. None si es genérico."""
    if not valor:
        return None
    valor = valor.strip().lower()
    if "@" in valor:
        dominio = valor.rsplit("@", 1)[1]
    else:
        if "//" not in valor:
            valor = "https://" + valor
        dominio = urlparse(valor).netloc
    dominio = dominio.split(":")[0]
    if dominio.startswith("www."):
        dominio = dominio[4:]
    if not dominio or "." not in dominio or dominio in _DOMINIOS_GENERICOS:
        return None
    return dominio


def clave_empresa(nombre: str, dominio: str | None = None) -> tuple[str, str | None]:
    """Devuelve (nombre_normalizado, dominio) para deduplicar.

    El dominio manda cuando existe; el nombre normalizado es el fallback.
    """
    return normalizar_nombre_empresa(nombre), normalizar_dominio(dominio)


# --- Roles -------------------------------------------------------------------

_SENIORITY_PATRONES: list[tuple[Seniority, list[str]]] = [
    (
        Seniority.DIRECCION,
        ["director", "directora", "chief", "cto", "cfo", "ceo", "coo", "cmo", "vp",
         "vicepresidente", "head of", "country manager"],
    ),
    (
        Seniority.JEFATURA,
        ["gerente", "jefe", "jefa", "manager", "lider", "leader", "supervisor",
         "supervisora", "coordinador", "coordinadora", "responsable de"],
    ),
    (Seniority.SENIOR, ["senior", "sr", "especialista", "experto"]),
    (Seniority.SEMI_SENIOR, ["semi senior", "semisenior", "ssr", "semi sr"]),
    (Seniority.JUNIOR, ["junior", "jr", "trainee", "pasante", "practicante", "becario"]),
]

# Se evalúa de patrón más largo a más corto: "semi senior" tiene que ganarle a
# "senior", que está contenido en él. Sin este orden, todo Semi Senior se
# clasifica como Senior y los reposteos dejan de matchear.
_SENIORITY_ORDENADOS: list[tuple[Seniority, str]] = sorted(
    ((nivel, patron) for nivel, patrones in _SENIORITY_PATRONES for patron in patrones),
    key=lambda par: len(par[1]),
    reverse=True,
)

# El orden importa: se evalúa de más específico a menos.
_ALIAS_ROL: list[tuple[str, str]] = [
    (r"\bfull ?stack\b", "full stack"),
    (r"\bfront ?end\b", "frontend"),
    (r"\bback ?end\b", "backend"),
    (r"\b(desarrollador|desarrolladora|programador|programadora|dev|developer)\b", "developer"),
    (r"\b(ingeniero|ingeniera|engineer)\b", "engineer"),
    (r"\b(contador|contadora|accountant)\b", "contador"),
    (r"\b(vendedor|vendedora|ejecutivo comercial|ejecutiva comercial|sales rep)\b", "comercial"),
    (r"\b(analista funcional)\b", "analista funcional"),
    (r"\b(analista|analyst)\b", "analista"),
    (r"\b(recursos humanos|rrhh|hr|people|talent acquisition|ta)\b", "rrhh"),
    (r"\b(data scientist|cientifico de datos|cientifica de datos)\b", "data scientist"),
    (r"\b(qa|quality assurance|tester)\b", "qa"),
]

_RUIDO_ROL = [
    r"\(.*?\)",
    r"\[.*?\]",
    r"\b(remoto|remote|hibrido|presencial|home office|full time|part time)\b",
    r"\b(buenos aires|caba|cordoba|rosario|mendoza|montevideo|santiago|bogota|lima|ciudad de mexico|cdmx)\b",
    r"\b(argentina|uruguay|chile|mexico|colombia|peru|brasil|latam)\b",
    r"\bm/f\b|\bh/m\b",
]


def detectar_seniority(titulo: str) -> Seniority:
    texto = f" {sin_acentos(titulo or '').lower()} "
    texto = re.sub(r"[^\w\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    for nivel, patron in _SENIORITY_ORDENADOS:
        if f" {patron} " in texto:
            return nivel
    return Seniority.INDEFINIDO


def normalizar_rol(titulo: str) -> str:
    """'Programador Full-Stack Semi Senior (Remoto)' -> 'developer full stack'.

    Quita seniority, ubicación y modalidad para que el mismo puesto publicado
    con distintas redacciones colapse a una sola clave.
    """
    texto = sin_acentos(titulo or "").lower()
    for patron in _RUIDO_ROL:
        texto = re.sub(patron, " ", texto)
    texto = re.sub(r"[^\w\s]", " ", texto)

    for patron, canonico in _ALIAS_ROL:
        texto = re.sub(patron, canonico, texto)

    # El seniority va en su propio campo, no en la clave del rol. También acá
    # el orden por longitud importa: si se quita "senior" primero, "semi senior"
    # deja un "semi" huérfano que rompe el match contra la variante con "Ssr".
    for _, patron in _SENIORITY_ORDENADOS:
        texto = re.sub(rf"\b{re.escape(patron)}\b", " ", texto)

    texto = re.sub(r"\b(de|del|la|el|los|las|y|en|para|con|un|una)\b", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()

    # Orden alfabético de tokens: "full stack developer" == "developer full stack".
    tokens = sorted(set(texto.split()))
    return " ".join(tokens)


_MARCAS_CONSULTORA = [
    "consultora", "consulting", "selecci", "headhunt", "recruit", "staffing",
    "randstad", "adecco", "manpower", "bayton", "gi group", "hays", "michael page",
    "robert half", "korn ferry", "talent search", "importante empresa",
    "reconocida empresa", "empresa lider del rubro", "nuestro cliente",
]


def publicado_por_consultora(nombre_empresa: str, descripcion: str | None = None) -> bool:
    """Si el aviso ya lo publica una consultora, el lead está tomado.

    El caso más común en portales de AR es el aviso confidencial: no dice la
    empresa, dice 'Importante empresa del rubro' o 'nuestro cliente'.
    """
    texto = sin_acentos(f"{nombre_empresa} {descripcion or ''}").lower()
    return any(marca in texto for marca in _MARCAS_CONSULTORA)

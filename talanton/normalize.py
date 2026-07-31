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
        ["director", "directora", "chief", "cto", "cfo", "ceo", "coo", "cmo", "cio",
         "cpo", "ciso", "vp", "vicepresidente", "head of", "country manager",
         "founder", "cofounder", "socio", "socia"],
    ),
    (
        Seniority.JEFATURA,
        ["gerente", "jefe", "jefa", "manager", "lider", "leader", "supervisor",
         "supervisora", "coordinador", "coordinadora", "responsable de",
         # En IT la jefatura casi nunca dice "jefe": dice "lead". Sin esto, un
         # Tech Lead —de los puestos más difíciles y mejor pagos que existen—
         # caía en INDEFINIDO y pesaba menos que un analista junior.
         "lead", "tech lead", "team lead", "scrum master"],
    ),
    # Staff y Principal están por encima de Senior en la carrera técnica, pero
    # son roles individuales, no de conducción. Van acá y no en jefatura: es más
    # honesto y de todos modos matchean un ICP que apunta a "senior".
    # "specialist" tiene que estar junto a "especialista": si se saca uno y el
    # otro no, «Especialista en Ciberseguridad» y «Cybersecurity Specialist»
    # quedan como roles distintos.
    (Seniority.SENIOR, ["senior", "sr", "especialista", "specialist", "experto",
                        "staff", "principal", "arquitecto", "arquitecta",
                        "architect"]),
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

# El orden importa: se evalúa de arriba hacia abajo y cada regla pisa el texto,
# así que **lo compuesto va antes que lo genérico**. Si `ingeniero -> engineer`
# corriera primero, «Ingeniero de Datos» ya sería «engineer de datos» y la regla
# de data engineer no lo alcanzaría nunca: quedaría como un rol distinto de
# «Data Engineer» y el reposteo entre los dos se volvería invisible. El reposteo
# es la señal más fuerte del producto, así que este orden no es cosmético.
_ALIAS_ROL: list[tuple[str, str]] = [
    # --- Compuestos: consumen el sustantivo genérico que llevan adentro ---
    (r"\b(data engineer|ingeniero de datos|ingeniera de datos)\b", "data engineer"),
    (r"\b(data scientist|cientifico de datos|cientifica de datos)\b", "data scientist"),
    (r"\b(sre|site reliability engineer|site reliability)\b", "sre"),
    # Las dos formas del compuesto, porque el orden de las palabras cambia entre
    # idiomas: «DevOps Engineer» y «Ingeniero DevOps» son el mismo puesto.
    (r"\b(devops engineer|ingeniero devops|ingeniera devops|devops|dev ops)\b", "devops"),
    (r"\b(product owner|product manager)\b", "product"),
    (r"\b(analista funcional)\b", "analista funcional"),
    (r"\b(ciberseguridad|cybersecurity|seguridad informatica|infosec)\b", "seguridad"),
    (r"\b(soporte|helpdesk|help desk|mesa de ayuda|service desk)\b", "soporte"),
    (r"\b(infraestructura|infrastructure|cloud|sysadmin)\b", "infraestructura"),
    (r"\b(ux|ui|ux ui|disenador ux|disenadora ux)\b", "ux"),
    # --- Modificadores de stack ---
    (r"\bfull ?stack\b", "full stack"),
    (r"\bfront ?end\b", "frontend"),
    (r"\bback ?end\b", "backend"),
    # --- Genéricos ---
    (r"\b(desarrollador|desarrolladora|programador|programadora|dev|developer)\b", "developer"),
    (r"\b(ingeniero|ingeniera|engineer)\b", "engineer"),
    (r"\b(contador|contadora|accountant)\b", "contador"),
    (r"\b(vendedor|vendedora|ejecutivo comercial|ejecutiva comercial|sales rep)\b", "comercial"),
    (r"\b(analista|analyst)\b", "analista"),
    (r"\b(recursos humanos|rrhh|hr|people|talent acquisition)\b", "rrhh"),
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


# Competencia directa: consultoras de selección, headhunting y staffing de RRHH.
# No son clientes y nunca lo van a ser.
#
# Cuidado con «consulting» a secas: «Bluelight Consulting» y «Snoop Consulting»
# son consultoras de *software*, y esas sí son clientes —contratan gente todo el
# tiempo y no siempre pueden—. Sólo entra cuando el texto habla de personas.
_MARCAS_COMPETENCIA = [
    "consultora de recursos humanos", "consultora de rrhh", "consultora de personal",
    "seleccion de personal", "busqueda y seleccion", "capital humano",
    "headhunt", "head hunt", "recruiting", "recruitment", "reclutamiento",
    "staffing", "talent solutions", "talent search", "rrhh consultora",
    "randstad", "adecco", "manpower", "bayton", "gi group", "hays",
    "michael page", "robert half", "korn ferry", "spencer stuart", "egon zehnder",
]

# Marcas de que el aviso lo publica un intermediario y esconde al cliente final.
# Es sobre el aviso, no sobre la empresa: cualquiera puede publicar así.
_AVISO_CIEGO = [
    "importante empresa", "reconocida empresa", "empresa lider del rubro",
    "nuestro cliente", "our client", "empresa confidencial", "cliente confidencial",
]

_MARCAS_CONSULTORA = _MARCAS_COMPETENCIA + _AVISO_CIEGO


def es_competencia(nombre_empresa: str, industria: str | None = None) -> bool:
    """Si la empresa hace lo mismo que nosotros: seleccionar personal para otros.

    Se mira el nombre y la industria, no la descripción de sus avisos: una
    empresa de software puede pedir «experiencia en reclutamiento» para su
    propio equipo de RRHH sin ser competencia.
    """
    texto = sin_acentos(f"{nombre_empresa} {industria or ''}").lower()
    return any(marca in texto for marca in _MARCAS_COMPETENCIA)


# Avisos que nunca se cierran porque no son búsquedas: son buzones de CV. Una
# empresa los deja publicados para siempre, así que acumulan días abiertos sin
# parar y terminan arriba de todo en el ranking justo por no ser una búsqueda
# real. Es el peor falso positivo posible: llamar a alguien por un aviso de hace
# seis años quema la credibilidad en la primera frase.
_AVISOS_PERENNES = [
    "general application", "spontaneous application", "open application",
    "candidatura espontanea", "postulacion espontanea", "autocandidatura",
    "talent pool", "talent community", "talent network", "banco de talento",
    "base de datos", "any other talent", "other talent", "future opportunities",
    "futuras oportunidades", "otras posiciones", "otras oportunidades",
    "no encontraste", "didn t find", "didn't find", "none of the above",
    "trabaja con nosotros", "work with us", "join our team", "sumate al equipo",
    "envianos tu cv", "send us your cv", "envia tu cv", "postulate aca",
    "generico", "generica", "spontaneous",
]


def es_aviso_perenne(titulo: str, descripcion: str | None = None) -> bool:
    """Si el aviso es un buzón de CVs permanente y no una búsqueda concreta.

    Se mira sobre todo el título: la descripción de un aviso real puede decir
    «sumate al equipo» de puro entusiasmo, pero un aviso que se **llama**
    «General Applications» no es una vacante que la empresa no logra cerrar.
    """
    limpio = sin_acentos(titulo or "").lower()
    if any(marca in limpio for marca in _AVISOS_PERENNES):
        return True
    # Un título de una sola palabra genérica tampoco es una búsqueda.
    return limpio.strip() in {"talento", "talent", "candidatos", "candidates", "cv"}


def publicado_por_consultora(nombre_empresa: str, descripcion: str | None = None) -> bool:
    """Si el aviso ya lo publica una consultora, el lead está tomado.

    El caso más común en portales de AR es el aviso confidencial: no dice la
    empresa, dice 'Importante empresa del rubro' o 'nuestro cliente'.
    """
    texto = sin_acentos(f"{nombre_empresa} {descripcion or ''}").lower()
    return any(marca in texto for marca in _MARCAS_CONSULTORA)

"""Importador de listas de empresas y contactos.

La vía más corta para empezar a trabajar: cualquier lista que ya tengas —un
Excel de clientes viejos, una exportación de Apollo, contactos de una feria—
entra acá y queda como leads listos para el tablero.

Es deliberadamente tolerante con el formato: la gente pega lo que tiene, no lo
que el sistema pide. Reconoce encabezados en español e inglés, separadores por
coma, punto y coma o tabulación, y funciona igual sin encabezados.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .models import Contacto, Empresa
from .normalize import normalizar_dominio, sin_acentos
from .services import asegurar_lead, perfil, recalcular_lead, upsert_empresa

log = logging.getLogger("talanton.importar")

# Nombres de columna que aceptamos para cada campo. Se comparan sin acentos,
# sin mayúsculas y sin puntuación: quien exporta de Excel no va a normalizar
# nada, y Apollo titula una columna «# Employees».
#
# El orden dentro de cada tupla importa: gana el primero que aparece en el
# archivo, así que los nombres más específicos van primero. «Company City» tiene
# que ganarle a «City» cuando están las dos, porque la ciudad que nos importa es
# la de la empresa, no la de la persona.
_COLUMNAS = {
    "empresa": ("empresa", "company", "compania", "razon social", "cliente",
                "organizacion", "account", "company name", "nombre empresa",
                "company name for emails"),
    "dominio": ("dominio", "domain", "web", "sitio", "sitio web", "website",
                "url", "pagina"),
    "contacto": ("contacto", "nombre completo", "nombre", "name", "full name",
                 "first name", "persona", "referente"),
    # Apollo y la mayoría de los CRMs parten el nombre en dos columnas. Sin
    # esto, un contacto exportado queda como «Marina» a secas y el saludo del
    # mail sale cortado.
    "apellido": ("apellido", "apellidos", "last name", "surname", "family name"),
    "cargo": ("cargo", "puesto", "title", "job title", "position", "rol"),
    "email": ("email", "e-mail", "mail", "correo", "email address",
              "correo electronico", "work email"),
    "telefono": ("telefono", "phone", "tel", "celular", "mobile", "whatsapp",
                 "corporate phone", "work direct phone", "mobile phone",
                 "company phone"),
    "industria": ("industria", "rubro", "industry", "sector"),
    "dotacion": ("dotacion", "empleados", "employees", "headcount", "size",
                 "tamano", "employee count", "num employees",
                 "number of employees"),
    "ciudad": ("company city", "ciudad", "city", "localidad", "ubicacion",
               "location"),
    # Sirve como procedencia auditable del contacto, que es justo lo que a una
    # lista comprada le falta.
    "linkedin": ("person linkedin url", "linkedin", "linkedin url",
                 "perfil linkedin"),
    "notas": ("notas", "notes", "comentarios", "observaciones"),
}


@dataclass
class Fila:
    empresa: str
    dominio: str | None = None
    contacto: str | None = None
    cargo: str | None = None
    email: str | None = None
    telefono: str | None = None
    industria: str | None = None
    dotacion: int | None = None
    ciudad: str | None = None
    notas: str | None = None
    # De dónde salió el contacto. Queda guardado en `Contacto.fuente_url` para
    # poder auditarlo y borrarlo a pedido: sin procedencia, un dato de contacto
    # de un tercero no se puede defender.
    procedencia: str = "importado a mano"

    @property
    def tiene_contacto(self) -> bool:
        return bool(self.email or self.contacto)


@dataclass
class Resultado:
    filas: list[Fila] = field(default_factory=list)
    empresas_nuevas: int = 0
    empresas_existentes: int = 0
    contactos_nuevos: int = 0
    ignoradas: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.filas)


def _clave(texto: str) -> str:
    """Deja el encabezado comparable: sin acentos, sin mayúsculas y sin
    puntuación. `# Employees` y `E-mail` tienen que caer en `employees` y
    `email`, si no la columna se pierde en silencio."""
    limpio = sin_acentos(texto or "").lower()
    limpio = re.sub(r"[^a-z0-9]+", " ", limpio)
    return limpio.strip()


# Los alias también se normalizan, para compararlos contra lo mismo.
_ALIAS = {campo: [_clave(a) for a in alias] for campo, alias in _COLUMNAS.items()}


def _mapear_encabezados(cabecera: list[str]) -> dict[str, int]:
    """Qué columna del archivo corresponde a cada campo nuestro.

    Recorre por campo y no por columna, así el orden de preferencia de los
    alias manda: con «City» y «Company City» presentes, gana la de la empresa.
    """
    posiciones: dict[str, int] = {}
    limpias = [_clave(c) for c in cabecera]
    tomadas: set[int] = set()

    for campo, alias in _ALIAS.items():
        for nombre in alias:
            for i, limpia in enumerate(limpias):
                if limpia == nombre and i not in tomadas:
                    posiciones[campo] = i
                    tomadas.add(i)
                    break
            if campo in posiciones:
                break
    return posiciones


def _hay_encabezado(cabecera: list[str]) -> bool:
    """Sin encabezado reconocible se asume orden: empresa, dominio, contacto…

    Dos reconocidas alcanzan. Pero también cuenta el caso de que **todas** lo
    sean, que cubre la lista de una sola columna —lo más habitual que alguien
    pega: nombres de empresa y nada más—. Sin esto, «Empresa» se tomaba como si
    fuera una empresa llamada así.
    """
    posiciones = _mapear_encabezados(cabecera)
    if len(posiciones) >= 2:
        return True
    return bool(posiciones) and len(posiciones) == len(cabecera)


_ORDEN_POR_DEFECTO = ["empresa", "dominio", "contacto", "cargo", "email", "telefono"]


def _detectar_separador(texto: str) -> str:
    primera = texto.splitlines()[0] if texto.splitlines() else ""
    for sep in ("\t", ";", ","):
        if sep in primera:
            return sep
    return ","


def _entero(valor: str | None) -> int | None:
    if not valor:
        return None
    import re

    numeros = re.findall(r"\d[\d.,]*", str(valor))
    if not numeros:
        return None
    try:
        return int(numeros[0].replace(".", "").replace(",", ""))
    except ValueError:
        return None


def analizar(texto: str) -> Resultado:
    """Interpreta el texto pegado y devuelve las filas, sin tocar la base.

    Separar el análisis del guardado permite mostrar una previsualización: nadie
    debería cargar 300 filas a ciegas y descubrir después que las columnas
    estaban corridas.
    """
    resultado = Resultado()
    texto = (texto or "").strip()
    if not texto:
        return resultado

    lector = csv.reader(io.StringIO(texto), delimiter=_detectar_separador(texto))
    filas = [f for f in lector if any((c or "").strip() for c in f)]
    if not filas:
        return resultado

    if _hay_encabezado(filas[0]):
        posiciones = _mapear_encabezados(filas[0])
        cuerpo = filas[1:]
    else:
        posiciones = {campo: i for i, campo in enumerate(_ORDEN_POR_DEFECTO)}
        cuerpo = filas

    if "empresa" not in posiciones:
        resultado.ignoradas.append(
            "No se encontró la columna de empresa. Poné un encabezado «Empresa» "
            "o dejá la empresa en la primera columna."
        )
        return resultado

    for numero, fila in enumerate(cuerpo, start=1):
        def celda(campo: str) -> str | None:
            i = posiciones.get(campo)
            if i is None or i >= len(fila):
                return None
            valor = (fila[i] or "").strip()
            return valor or None

        nombre = celda("empresa")
        if not nombre:
            resultado.ignoradas.append(f"Fila {numero}: sin nombre de empresa")
            continue

        email = (celda("email") or "").lower() or None
        if email and "@" not in email:
            # Un email inválido se descarta pero la empresa se importa igual.
            resultado.ignoradas.append(f"Fila {numero}: «{email}» no es un email válido")
            email = None

        # Nombre y apellido en columnas separadas es lo normal en cualquier
        # exportación de CRM; acá se vuelven a juntar.
        persona = " ".join(
            x for x in (celda("contacto"), celda("apellido")) if x
        ).strip() or None

        linkedin = celda("linkedin")
        resultado.filas.append(
            Fila(
                empresa=nombre,
                dominio=normalizar_dominio(celda("dominio") or email),
                contacto=persona,
                cargo=celda("cargo"),
                email=email,
                telefono=celda("telefono"),
                industria=celda("industria"),
                dotacion=_entero(celda("dotacion")),
                ciudad=celda("ciudad"),
                notas=celda("notas"),
                procedencia=linkedin or "importado a mano",
            )
        )

    return resultado


def importar(session: Session, filas: list[Fila], *, pais: str = "AR") -> Resultado:
    """Guarda las filas como empresas, contactos y leads."""
    resultado = Resultado(filas=filas)
    p = perfil(session)

    for fila in filas:
        ya_existia = _existe(session, fila)
        empresa = upsert_empresa(
            session,
            fila.empresa,
            dominio=fila.dominio,
            pais=pais,
            ciudad=fila.ciudad,
            industria=fila.industria,
            dotacion_estimada=fila.dotacion,
        )
        if ya_existia:
            resultado.empresas_existentes += 1
        else:
            resultado.empresas_nuevas += 1

        if _agregar_contacto(empresa, fila):
            resultado.contactos_nuevos += 1

        session.flush()
        session.refresh(empresa)
        lead = asegurar_lead(session, empresa)
        if fila.notas and not lead.proximo_paso:
            lead.proximo_paso = fila.notas[:300]
        recalcular_lead(session, lead, p)

    session.commit()
    return resultado


def _existe(session: Session, fila: Fila) -> bool:
    from sqlalchemy import select

    from .normalize import normalizar_nombre_empresa

    if fila.dominio:
        if session.scalar(select(Empresa).where(Empresa.dominio == fila.dominio)):
            return True
    return bool(
        session.scalar(
            select(Empresa).where(
                Empresa.nombre_normalizado == normalizar_nombre_empresa(fila.empresa)
            )
        )
    )


def _agregar_contacto(empresa: Empresa, fila: Fila) -> bool:
    if not fila.tiene_contacto:
        return False

    ya_estan = {(c.email or "").lower() for c in empresa.contactos if c.email}
    if fila.email and fila.email in ya_estan:
        return False

    # Un contacto importado a mano se asume decisor: si alguien se tomó el
    # trabajo de cargarlo, es con quien quiere hablar.
    empresa.contactos.append(
        Contacto(
            nombre=fila.contacto or f"Contacto de {empresa.nombre}",
            cargo=fila.cargo,
            email=fila.email,
            telefono=fila.telefono,
            es_decisor=True,
            fuente_url=fila.procedencia,
        )
    )
    return True

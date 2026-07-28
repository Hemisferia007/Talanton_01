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
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .models import Contacto, Empresa
from .normalize import normalizar_dominio, sin_acentos
from .services import asegurar_lead, perfil, recalcular_lead, upsert_empresa

log = logging.getLogger("talanton.importar")

# Nombres de columna que aceptamos para cada campo. Se comparan sin acentos ni
# mayúsculas: quien exporta de Excel no va a normalizar nada.
_COLUMNAS = {
    "empresa": ("empresa", "company", "compania", "razon social", "cliente",
                "organizacion", "account", "company name", "nombre empresa"),
    "dominio": ("dominio", "domain", "web", "sitio", "sitio web", "website",
                "url", "pagina"),
    "contacto": ("contacto", "nombre", "name", "full name", "first name",
                 "nombre completo", "persona", "referente"),
    "cargo": ("cargo", "puesto", "title", "job title", "position", "rol"),
    "email": ("email", "e-mail", "mail", "correo", "email address",
              "correo electronico"),
    "telefono": ("telefono", "phone", "tel", "celular", "mobile", "whatsapp"),
    "industria": ("industria", "rubro", "industry", "sector"),
    "dotacion": ("dotacion", "empleados", "employees", "headcount", "size",
                 "tamano", "employee count"),
    "ciudad": ("ciudad", "city", "localidad", "ubicacion", "location"),
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
    return sin_acentos(texto or "").strip().lower().replace("_", " ")


def _mapear_encabezados(cabecera: list[str]) -> dict[str, int]:
    """Qué columna del archivo corresponde a cada campo nuestro."""
    posiciones: dict[str, int] = {}
    for i, celda in enumerate(cabecera):
        limpia = _clave(celda)
        for campo, alias in _COLUMNAS.items():
            if campo in posiciones:
                continue
            if limpia in alias:
                posiciones[campo] = i
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

        resultado.filas.append(
            Fila(
                empresa=nombre,
                dominio=normalizar_dominio(celda("dominio") or email),
                contacto=celda("contacto"),
                cargo=celda("cargo"),
                email=email,
                telefono=celda("telefono"),
                industria=celda("industria"),
                dotacion=_entero(celda("dotacion")),
                ciudad=celda("ciudad"),
                notas=celda("notas"),
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

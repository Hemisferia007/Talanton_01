"""A quién apuntar en cada empresa.

La regla es de oficio comercial, no técnica: en una PyME de 15 personas el que
decide contratar una consultora es el dueño; en una de 400 es Recursos Humanos,
y escribirle al dueño te hace quedar como el que saltea a su equipo.

Esto no adivina nombres. Define **qué cargo buscar**, que es lo que convierte
"tengo que conseguir el contacto" en una tarea concreta de diez minutos.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Empresa


@dataclass
class Objetivo:
    cargos: list[str]
    razon: str
    # Emails genéricos que suelen funcionar en empresas de este tamaño.
    buzones: list[str]

    @property
    def cargo_principal(self) -> str:
        return self.cargos[0]


# Los tramos salen de cómo se organiza la función de RRHH según la dotación.
# Debajo de ~25 personas rara vez hay alguien dedicado; arriba de ~500 casi
# siempre hay un equipo de selección propio y el interlocutor cambia otra vez.
_TRAMOS = [
    (
        25,
        Objetivo(
            cargos=["Dueño", "Socio", "CEO", "Fundador", "Director General"],
            razon="Menos de 25 personas: no hay RRHH dedicado, decide el dueño.",
            buzones=["info", "contacto", "administracion"],
        ),
    ),
    (
        100,
        Objetivo(
            cargos=["Gerente de Administración", "Jefe de RRHH", "Dueño", "Director"],
            razon="Entre 25 y 100: RRHH suele colgar de Administración.",
            buzones=["rrhh", "recursoshumanos", "administracion", "info"],
        ),
    ),
    (
        500,
        Objetivo(
            cargos=["Gerente de RRHH", "HR Business Partner", "Head of People"],
            razon="Entre 100 y 500: hay RRHH propio, y es quien contrata consultoras.",
            buzones=["rrhh", "recursoshumanos", "seleccion", "empleos"],
        ),
    ),
]

_GRANDE = Objetivo(
    cargos=["Talent Acquisition Manager", "Head of Talent", "Gerente de Selección"],
    razon=(
        "Más de 500: hay equipo de selección interno. El interlocutor es quien "
        "lidera adquisición de talento, no RRHH generalista."
    ),
    buzones=["seleccion", "talento", "empleos", "rrhh"],
)

_SIN_DATOS = Objetivo(
    cargos=["Gerente de RRHH", "Dueño", "Director"],
    razon="Sin dotación estimada: apuntar a RRHH y al dueño en paralelo.",
    buzones=["rrhh", "info", "contacto"],
)


def objetivo_para(empresa: Empresa) -> Objetivo:
    dotacion = empresa.dotacion_estimada
    if dotacion is None:
        return _SIN_DATOS
    for tope, objetivo in _TRAMOS:
        if dotacion < tope:
            return objetivo
    return _GRANDE


def es_cargo_decisor(cargo: str | None, empresa: Empresa) -> bool:
    """Si un cargo cargado a mano corresponde al decisor de esta empresa."""
    if not cargo:
        return False
    from ..normalize import sin_acentos

    texto = sin_acentos(cargo).lower()
    objetivo = objetivo_para(empresa)
    for esperado in objetivo.cargos:
        # Basta con que compartan la palabra fuerte: "Gerenta de RRHH" tiene
        # que matchear con "Gerente de RRHH".
        clave = sin_acentos(esperado).lower().split()[0][:5]
        if clave and clave in texto:
            return True
    return any(p in texto for p in ("rrhh", "recursos humanos", "people", "talent", "dueñ", "duen"))

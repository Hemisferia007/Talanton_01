"""Plantillas de primer contacto, derivadas de la señal concreta.

La regla: el mail arranca por algo que la empresa reconoce como cierto sobre sí
misma —una búsqueda puntual, con su nombre y sus días— y recién después dice
quiénes somos. Un mail que abre con "somos una consultora líder" no se lee.

Todo es texto plano y corto. Nada de HTML, imágenes ni tracking pixels: son
justo las señales que mandan un mail frío a spam.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..models import Contacto, Lead, Vacante


@dataclass
class Contexto:
    lead: Lead
    empresa: str
    contacto: Contacto | None
    vacante: Vacante | None
    abiertas: list[Vacante]
    consultora: str
    firma: str

    @property
    def saludo(self) -> str:
        if self.contacto and self.contacto.nombre:
            return f"Hola {self.contacto.nombre.split()[0]},"
        return "Hola, buen día:"

    @property
    def dias(self) -> int:
        return self.vacante.dias_abierta if self.vacante else 0


@dataclass
class Plantilla:
    clave: str
    nombre: str
    descripcion: str
    aplica: Callable[[Contexto], bool]
    asunto: Callable[[Contexto], str]
    cuerpo: Callable[[Contexto], str]


def _cierre(c: Contexto) -> str:
    return f"\n\nSaludos,\n{c.firma}" if c.firma else "\n\nSaludos,"


BUSQUEDA_ESTIRADA = Plantilla(
    clave="busqueda_estirada",
    nombre="Búsqueda que se estiró",
    descripcion="Para cuando hay una vacante abierta hace más de 30 días.",
    aplica=lambda c: c.vacante is not None and c.dias >= 30,
    asunto=lambda c: f"{c.vacante.titulo} — hace {c.dias} días",
    cuerpo=lambda c: f"""{c.saludo}

Vi que en {c.empresa} están buscando {c.vacante.titulo}\
{f' en {c.vacante.ubicacion}' if c.vacante.ubicacion else ''} desde hace {c.dias} días\
{', y que ya republicaron el aviso' if c.vacante.reposteos else ''}.

Es un perfil que solemos cubrir. Si te sirve, en una llamada de quince minutos \
te cuento cómo lo encararíamos y qué plazo real manejamos para una búsqueda así.

¿Te queda cómodo esta semana?{_cierre(c)}""",
)


VOLUMEN = Plantilla(
    clave="volumen",
    nombre="Varias búsquedas a la vez",
    descripcion="Para cuando hay tres o más vacantes abiertas en simultáneo.",
    aplica=lambda c: len(c.abiertas) >= 3,
    asunto=lambda c: f"Las {len(c.abiertas)} búsquedas abiertas de {c.empresa}",
    cuerpo=lambda c: f"""{c.saludo}

Vi que en {c.empresa} tienen {len(c.abiertas)} búsquedas abiertas al mismo tiempo:

{chr(10).join('· ' + v.titulo + (f' ({v.dias_abierta} días)' if v.dias_abierta else '') for v in c.abiertas[:5])}

Llevar todo eso en paralelo con el equipo interno suele ser lo que hace que \
alguna se estire. Podemos tomar las que más te compliquen y dejarte el resto \
liberado.

¿Charlamos quince minutos esta semana?{_cierre(c)}""",
)


ROTACION = Plantilla(
    clave="rotacion",
    nombre="Puesto que se repite",
    descripcion="Para cuando el mismo rol ya se había buscado antes.",
    aplica=lambda c: c.vacante is not None
    and any(
        v.cerrada and v.rol_normalizado == c.vacante.rol_normalizado
        for v in c.lead.empresa.vacantes
    ),
    asunto=lambda c: f"{c.vacante.titulo}, otra vez",
    cuerpo=lambda c: f"""{c.saludo}

Vi que en {c.empresa} volvieron a abrir la búsqueda de {c.vacante.titulo}. \
Es un puesto que ya habían cubierto antes.

Cuando una posición se repite en poco tiempo, el problema casi nunca es la \
falta de candidatos: es el perfil, el proceso o la propuesta. Nos pasa seguido \
y sabemos dónde mirar.

Si querés lo revisamos juntos en una llamada corta, sin compromiso.{_cierre(c)}""",
)


PRESENTACION = Plantilla(
    clave="presentacion",
    nombre="Presentación general",
    descripcion="El fallback cuando no hay una señal fuerte para usar.",
    aplica=lambda c: True,
    asunto=lambda c: f"Selección de perfiles para {c.empresa}",
    cuerpo=lambda c: f"""{c.saludo}

Te escribo de {c.consultora}. Trabajamos en selección de perfiles para empresas \
como {c.empresa}, sobre todo en las búsquedas que se complican con el equipo interno.

Si tenés alguna posición abierta que se esté estirando, con gusto te cuento cómo \
la encararíamos.

¿Te sirve una llamada de quince minutos?{_cierre(c)}""",
)


SEGUIMIENTO = Plantilla(
    clave="seguimiento",
    nombre="Seguimiento",
    descripcion="Para insistir sin repetir el primer mail.",
    aplica=lambda c: c.lead.ultimo_contacto_en is not None,
    asunto=lambda c: f"Sigo por acá — {c.empresa}",
    cuerpo=lambda c: f"""{c.saludo}

Te escribí hace unos días por \
{f'la búsqueda de {c.vacante.titulo}' if c.vacante else 'las búsquedas abiertas'} \
y quizá se te traspapeló.

Si no es el momento, decímelo y no insisto. Y si el tema lo lleva otra persona, \
te agradezco si me la pasás.{_cierre(c)}""",
)


TODAS = [BUSQUEDA_ESTIRADA, ROTACION, VOLUMEN, SEGUIMIENTO, PRESENTACION]


def construir_contexto(lead: Lead, consultora: str, firma: str) -> Contexto:
    abiertas = sorted(
        lead.empresa.vacantes_abiertas, key=lambda v: v.dias_abierta, reverse=True
    )
    decisores = [c for c in lead.empresa.contactos if c.es_decisor]
    contacto = (decisores or lead.empresa.contactos or [None])[0]
    return Contexto(
        lead=lead,
        empresa=lead.empresa.nombre,
        contacto=contacto,
        vacante=abiertas[0] if abiertas else None,
        abiertas=abiertas,
        consultora=consultora,
        firma=firma,
    )


def disponibles(contexto: Contexto) -> list[Plantilla]:
    """Las que aplican al lead, en orden de fuerza de la señal.

    PRESENTACION siempre aplica, así que la lista nunca queda vacía.
    """
    return [p for p in TODAS if p.aplica(contexto)]


def redactar(plantilla: Plantilla, contexto: Contexto) -> tuple[str, str]:
    return plantilla.asunto(contexto), plantilla.cuerpo(contexto)


def por_clave(clave: str) -> Plantilla | None:
    return next((p for p in TODAS if p.clave == clave), None)

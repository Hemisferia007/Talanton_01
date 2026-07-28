"""«¿Conviene contactarlo?» — la lectura del asistente sobre un lead.

Complementa al score, no lo reemplaza. El score mira números —días abiertos,
dotación, cantidad de búsquedas— y por eso es explicable y estable. Lo que no
puede mirar es el texto: un aviso que pide diez años de experiencia por un
sueldo de junior, una respuesta que dice «lo vemos el año que viene», una
descripción de la que se deduce que ya trabajan con otra consultora.

Ahí es donde este módulo agrega algo. Y por eso el veredicto más valioso suele
ser «no conviene»: el costo real de una herramienta de leads no son los mails
que manda sino las semanas que el comercial gasta en empresas que nunca iban a
comprar.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..config import ASISTENTE_MODELO
from ..models import Lead, Opinion, Veredicto, ahora
from . import expediente
from .cliente import Cliente, ErrorAsistente

log = logging.getLogger("talanton.asistente")

SISTEMA = """\
Sos el asistente comercial de una consultora de selección de personal que trabaja \
en Argentina y LatAm. Tu trabajo es leer la ficha de una empresa y decir si vale \
la pena que el comercial le dedique tiempo.

El negocio, en una línea: la consultora cobra por cubrir búsquedas que la empresa \
no logra cerrar sola. Un buen lead no es una empresa grande ni una empresa \
simpática: es una empresa con una búsqueda abierta que se le está estirando y con \
plata para tercerizarla.

Cómo juzgar:

- Una búsqueda de más de 45 días, republicada, o un mismo puesto que ya se buscó \
antes, es la señal más fuerte que existe. Sin ninguna búsqueda abierta, el \
veredicto casi siempre es «esperar».
- Un perfil difícil (senior, jefatura, dirección, nicho técnico, interior del \
país) vale mucho más que uno que se cubre publicando un aviso.
- Un aviso publicado por otra consultora significa que el mandato ya está dado: \
llegamos tarde, salvo que además tengan otras búsquedas propias.
- Una empresa con equipo interno de selección grande resiste más, pero no está \
descartada: suele tercerizar justo los puestos que su equipo no cubre.
- Si respondieron que no, que no es el momento, o que ya tienen proveedor, eso \
pesa más que cualquier señal del aviso.
- Una empresa demasiado chica para pagar un fee, o de una industria fuera del \
cliente ideal, es «descartar» aunque tenga búsquedas abiertas.

Reglas de honestidad, que son la parte importante:

- Usá **sólo** lo que dice la ficha. No inventes rondas de inversión, nombres, \
sueldos ni cosas que la empresa "seguramente" hace.
- Si la ficha tiene poca información, decilo y poné confianza «baja». Es mucho \
más útil que un veredicto seguro apoyado en nada.
- Los días marcados con `~` son aproximados. Si los mencionás, decí "hace unos \
dos meses", nunca un número exacto.
- «No conviene» y «todavía no» son respuestas correctas y esperadas. No busques \
justificar un contacto que no se sostiene.

Escribí en español rioplatense, tuteando de vos, en frases cortas. Cada motivo y \
cada reparo tiene que ser algo concreto de esta empresa, no una generalidad que \
sirva para cualquiera.\
"""

ESQUEMA = {
    "type": "object",
    "properties": {
        "veredicto": {
            "type": "string",
            "enum": ["contactar", "esperar", "descartar"],
            "description": (
                "contactar: hay una señal concreta y ahora es el momento. "
                "esperar: puede llegar a servir pero hoy no hay razón para escribir. "
                "descartar: no es cliente de esta consultora."
            ),
        },
        "confianza": {
            "type": "string",
            "enum": ["alta", "media", "baja"],
            "description": "Cuánta información real había en la ficha para decidir.",
        },
        "motivos": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 4,
            "description": "Hechos de esta empresa a favor de contactarla, una frase cada uno.",
        },
        "reparos": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 4,
            "description": "Lo que juega en contra o lo que falta saber. Puede ir vacío.",
        },
        "que_decir": {
            "type": "string",
            "description": (
                "Por dónde abrir la conversación, en una o dos frases, apoyado en "
                "algo que la empresa reconozca como cierto sobre sí misma. Vacío si "
                "el veredicto es descartar."
            ),
        },
        "a_quien": {
            "type": "string",
            "description": (
                "Cargo al que conviene apuntar en esta empresa según su tamaño. "
                "Vacío si ya hay un decisor identificado."
            ),
        },
    },
    "required": ["veredicto", "confianza", "motivos", "reparos", "que_decir", "a_quien"],
    "additionalProperties": False,
}


def evaluar(session: Session, lead: Lead, cliente: Cliente | None = None) -> Opinion:
    """Pide la lectura y la guarda pisando la anterior.

    No hace `commit`: quien llama decide cuándo cerrar la transacción.
    """
    cli = cliente or _cliente()
    datos = cli.preguntar(
        sistema=SISTEMA,
        mensaje=(
            "Ficha del lead:\n\n"
            + expediente.armar(session, lead)
            + "\n\n¿Conviene que el comercial le dedique tiempo a esta empresa?"
        ),
        esquema=ESQUEMA,
        esfuerzo="medium",
    )

    try:
        veredicto = Veredicto(str(datos.get("veredicto", "")).strip().lower())
    except ValueError as exc:  # pragma: no cover - lo evita el enum del esquema
        raise ErrorAsistente(
            f"El asistente devolvió un veredicto desconocido: {datos.get('veredicto')!r}"
        ) from exc

    opinion = lead.opinion or Opinion(lead_id=lead.id)
    opinion.veredicto = veredicto
    opinion.confianza = str(datos.get("confianza") or "media").strip().lower()
    opinion.motivos = "\n".join(_lineas(datos.get("motivos")))
    opinion.reparos = "\n".join(_lineas(datos.get("reparos")))
    opinion.que_decir = (datos.get("que_decir") or "").strip() or None
    opinion.a_quien = (datos.get("a_quien") or "").strip()[:200] or None
    opinion.modelo = getattr(cli, "modelo", ASISTENTE_MODELO)
    opinion.firma_contexto = expediente.firma(lead)
    opinion.creada_en = ahora()

    if lead.opinion is None:
        session.add(opinion)
        lead.opinion = opinion
    session.flush()
    return opinion


def desactualizada(lead: Lead) -> bool:
    """¿El lead cambió desde que se pidió la opinión?"""
    if lead.opinion is None:
        return False
    return lead.opinion.firma_contexto != expediente.firma(lead)


def _lineas(valor) -> list[str]:
    if not isinstance(valor, list):
        return []
    return [str(x).strip() for x in valor if str(x).strip()]


def _cliente() -> Cliente:
    from .cliente import por_defecto

    return por_defecto()

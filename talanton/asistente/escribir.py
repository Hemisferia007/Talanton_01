"""Redacción asistida dentro del hilo.

Las plantillas de `correo/plantillas.py` siguen siendo el camino principal para
el primer mail: son determinísticas, salen instantáneas y no cuestan nada. Este
módulo es para lo que una plantilla no puede hacer —contestar lo que la empresa
efectivamente escribió— y para el primer mail cuando el aviso dice algo puntual
que vale la pena usar.

El borrador **nunca se manda solo**. Cae en la ventana de redacción, editable,
igual que el de plantilla. Un mail que sale sin que nadie lo lea es la forma más
rápida de quemar un dominio.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..models import Direccion, Lead
from . import expediente
from .cliente import Cliente

log = logging.getLogger("talanton.asistente")

SISTEMA = """\
Escribís mails comerciales para una consultora de selección de personal en \
Argentina. Te dan la ficha de una empresa y el hilo de mails que hubo hasta \
ahora, y devolvés el borrador del próximo mail.

Cómo tiene que ser el mail:

- Texto plano. Sin HTML, sin viñetas decorativas, sin firma armada: la firma la \
agrega el sistema.
- Corto. Menos de 120 palabras. Si no entra, es que sobra.
- Abre por algo que la empresa reconoce como cierto sobre sí misma —una búsqueda \
puntual con su nombre, algo que ellos mismos dijeron en el hilo—, no por quiénes \
somos.
- Un solo pedido concreto al final. Una llamada corta, una respuesta puntual, \
nada de "quedo a disposición para lo que necesites".
- Español rioplatense, de vos, tono de colega. Ni solemne ni gracioso.

Prohibido, porque es lo que hace que un mail frío no se lea:
- "Espero que estés muy bien", "me pongo en contacto", "somos una consultora líder".
- Adjetivos sobre nosotros mismos.
- Inventar datos: sueldos, nombres, rondas de inversión, cantidad de candidatos \
que tenemos. Si no está en la ficha, no existe.
- Dar por cierto un número marcado con `~`. Esos son aproximados: decí "hace unos \
dos meses" en vez de "hace 92 días".

Si en el hilo hay una respuesta de la empresa, el mail tiene que contestarla de \
verdad: retomá lo que dijeron con sus palabras antes de proponer nada. Si \
dijeron que no o que no es el momento, no insistas — escribí algo breve que \
cierre bien y deje la puerta abierta.\
"""

ESQUEMA = {
    "type": "object",
    "properties": {
        "asunto": {
            "type": "string",
            "description": (
                "Asunto corto y concreto, sin signos de exclamación. Si es respuesta "
                "dentro de un hilo, mantené el asunto anterior con «Re:»."
            ),
        },
        "cuerpo": {
            "type": "string",
            "description": "El mail completo en texto plano, sin firma.",
        },
        "lectura": {
            "type": "string",
            "description": (
                "Una frase para el comercial —no para el cliente— explicando en qué "
                "te apoyaste para escribirlo así."
            ),
        },
    },
    "required": ["asunto", "cuerpo", "lectura"],
    "additionalProperties": False,
}


def borrador(
    session: Session,
    lead: Lead,
    *,
    instruccion: str | None = None,
    cliente: Cliente | None = None,
) -> dict:
    """Devuelve `{asunto, cuerpo, lectura, respondiendo}` para la ventana."""
    cli = cliente or _cliente()

    entrante = next(
        (m for m in reversed(lead.mensajes) if m.direccion == Direccion.ENTRANTE), None
    )
    if entrante is not None:
        pedido = (
            f"La empresa nos contestó el {entrante.fecha.strftime('%d/%m/%Y')}. "
            "Escribí la respuesta a ese mensaje."
        )
    elif lead.mensajes:
        pedido = (
            "Ya les escribimos y todavía no contestaron. Escribí un seguimiento "
            "que no repita el mail anterior."
        )
    else:
        pedido = "Nunca los contactamos. Escribí el primer mail."

    if instruccion and instruccion.strip():
        # Lo que el comercial quiere decir manda sobre el criterio del modelo:
        # él sabe cosas del cliente que no están en la base.
        pedido += f"\n\nIndicación del comercial, tiene prioridad: {instruccion.strip()}"

    datos = cli.preguntar(
        sistema=SISTEMA,
        mensaje="Ficha del lead:\n\n" + expediente.armar(session, lead) + "\n\n" + pedido,
        esquema=ESQUEMA,
        esfuerzo="medium",
    )

    return {
        "asunto": (datos.get("asunto") or "").strip(),
        "cuerpo": (datos.get("cuerpo") or "").strip(),
        "lectura": (datos.get("lectura") or "").strip(),
        "respondiendo": entrante is not None,
    }


def _cliente() -> Cliente:
    from .cliente import por_defecto

    return por_defecto()

"""Acceso a la API de Claude.

Único punto donde el proyecto sabe que del otro lado hay un modelo: el resto del
paquete pide "esta pregunta con esta forma de respuesta" y recibe un dict.

Dos decisiones que valen la explicación:

- **Salida estructurada, no texto libre.** Se pide `output_config.format` con un
  JSON Schema, así la respuesta entra directo a la base sin parsear prosa. Un
  asistente que a veces devuelve viñetas y a veces un párrafo es imposible de
  mostrar en una pantalla.
- **El SDK es opcional.** Sin `anthropic` instalado o sin clave, la app levanta
  igual y los botones no aparecen. Es una función de más, no un requisito.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache

from ..config import ANTHROPIC_API_KEY, ASISTENTE_MODELO

log = logging.getLogger("talanton.asistente")

try:  # pragma: no cover - depende del entorno
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None


class ErrorAsistente(RuntimeError):
    """Falla con un texto que se le puede mostrar al comercial tal cual."""


def disponible() -> bool:
    return bool(anthropic and ANTHROPIC_API_KEY)


def motivo_no_disponible() -> str:
    if anthropic is None:
        return (
            "Falta instalar el SDK de Anthropic: agregá `anthropic` a las "
            "dependencias del servicio."
        )
    if not ANTHROPIC_API_KEY:
        return (
            "Falta la clave de la API. Cargá TALANTON_ANTHROPIC_API_KEY en las "
            "variables del servicio — ver docs/asistente.md."
        )
    return ""


class Cliente:
    """Envuelve al SDK. Se inyecta en los tests para no tocar la red."""

    def __init__(self, api_key: str | None = None, modelo: str | None = None):
        if anthropic is None:  # pragma: no cover
            raise ErrorAsistente(motivo_no_disponible())
        clave = api_key or ANTHROPIC_API_KEY
        if not clave:
            raise ErrorAsistente(motivo_no_disponible())
        self.modelo = modelo or ASISTENTE_MODELO
        # 90 segundos: con thinking adaptativo una lectura larga puede pasar el
        # minuto, y quien apretó el botón está mirando la pantalla.
        self._sdk = anthropic.Anthropic(api_key=clave, timeout=90.0)

    def preguntar(
        self,
        *,
        sistema: str,
        mensaje: str,
        esquema: dict,
        esfuerzo: str = "medium",
        max_tokens: int = 8000,
    ) -> dict:
        """Devuelve la respuesta ya validada contra `esquema`."""
        try:
            respuesta = self._sdk.messages.create(
                model=self.modelo,
                max_tokens=max_tokens,
                system=sistema,
                messages=[{"role": "user", "content": mensaje}],
                thinking={"type": "adaptive"},
                output_config={
                    "effort": esfuerzo,
                    "format": {"type": "json_schema", "schema": esquema},
                },
            )
        except anthropic.AuthenticationError as exc:
            raise ErrorAsistente(
                "La clave de la API de Anthropic no es válida o venció."
            ) from exc
        except anthropic.PermissionDeniedError as exc:
            raise ErrorAsistente(
                "La clave no tiene permiso para usar este modelo. Revisá el plan "
                "de la cuenta."
            ) from exc
        except anthropic.NotFoundError as exc:
            raise ErrorAsistente(
                f"El modelo «{self.modelo}» no existe o no está habilitado en la cuenta."
            ) from exc
        except anthropic.RateLimitError as exc:
            raise ErrorAsistente(
                "La API está limitando el uso por volumen. Probá de nuevo en un minuto."
            ) from exc
        except anthropic.BadRequestError as exc:
            # Casi siempre es nuestro: un esquema mal armado o un parámetro que
            # el modelo no acepta. Que se vea el detalle en el log.
            log.warning("Pedido rechazado por la API: %s", exc)
            raise ErrorAsistente(f"La API rechazó el pedido: {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise ErrorAsistente(
                "No se pudo llegar a la API de Anthropic. Puede ser la red del servidor."
            ) from exc
        except anthropic.APIStatusError as exc:
            raise ErrorAsistente(
                f"La API respondió con error {exc.status_code}. Probá de nuevo."
            ) from exc

        if respuesta.stop_reason == "refusal":
            raise ErrorAsistente(
                "El modelo prefirió no responder sobre este lead. Si el aviso "
                "tiene texto raro, probá de nuevo después de revisarlo."
            )
        if respuesta.stop_reason == "max_tokens":
            # El JSON quedó cortado: parsearlo daría un error mucho más confuso.
            raise ErrorAsistente(
                "La respuesta quedó cortada por longitud. Probá con un lead con "
                "menos avisos o menos mensajes en el hilo."
            )

        texto = next((b.text for b in respuesta.content if b.type == "text"), "")
        if not texto.strip():
            raise ErrorAsistente("La API devolvió una respuesta vacía.")
        try:
            return json.loads(texto)
        except json.JSONDecodeError as exc:  # pragma: no cover - lo evita el esquema
            log.warning("Respuesta no parseable: %r", texto[:400])
            raise ErrorAsistente("La respuesta no vino en el formato esperado.") from exc


@lru_cache(maxsize=1)
def por_defecto() -> Cliente:
    """El cliente compartido. Se arma una sola vez y reusa la conexión."""
    return Cliente()

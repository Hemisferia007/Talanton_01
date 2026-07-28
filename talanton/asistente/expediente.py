"""Qué ve el asistente de un lead.

Este módulo es la frontera de privacidad del proyecto: **todo lo que sale de
Talanton hacia la API pasa por acá y nada más**. Por eso se arma a mano en vez
de serializar los modelos: un `to_dict()` genérico manda emails, teléfonos y
tokens el día que alguien agrega una columna.

Lo que se manda:

- Datos de empresa (nombre, industria, dotación, país) y de sus avisos, que son
  públicos por definición: la empresa los publicó para que la contacten.
- Nombre y cargo de los contactos, para poder saludar y para razonar sobre a
  quién apuntar. **No van emails ni teléfonos**: para juzgar si conviene
  escribirle no hacen falta, y para saludar tampoco.
- El hilo con la empresa, que es el que hay que leer para contestar.

Lo que no sale nunca: direcciones de correo, teléfonos, credenciales, ni datos
de otras empresas de la base.
"""

from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from ..models import Direccion, Lead, PerfilConsultora, TipoEvento
from ..services import perfil

# Los avisos vienen con la descripción entera y son la parte más cara del
# expediente. Los primeros párrafos son los que dicen algo: el resto suele ser
# "somos una empresa líder" y el bloque de diversidad.
_TOPE_DESCRIPCION = 1200
_TOPE_MENSAJE = 1500
_TOPE_MENSAJES = 12
_TOPE_VACANTES = 12


def _recortar(texto: str | None, tope: int) -> str:
    limpio = " ".join((texto or "").split())
    if len(limpio) <= tope:
        return limpio
    return limpio[:tope].rsplit(" ", 1)[0] + "…"


def _dias(vacante) -> str:
    """El `~` no es decorativo: ese número puede terminar en un mail al cliente."""
    marca = "~" if vacante.fecha_aproximada else ""
    return f"{marca}{vacante.dias_abierta} días"


def _bloque_consultora(p: PerfilConsultora) -> list[str]:
    lineas = [f"Consultora: {p.nombre}"]
    if p.descripcion:
        lineas.append(f"Qué hace: {_recortar(p.descripcion, 600)}")
    lineas.append(
        "Cliente ideal: "
        + (", ".join(p.industrias) if p.industrias else "cualquier industria")
        + f"; dotación entre {p.dotacion_min} y {p.dotacion_max}"
        + f"; países {', '.join(p.paises) if p.paises else 'sin preferencia'}"
        + f"; perfiles {', '.join(p.seniorities) if p.seniorities else 'de cualquier nivel'}"
    )
    if p.fee_promedio:
        lineas.append(f"Fee promedio de una búsqueda: {p.fee_promedio}")
    return lineas


def _bloque_empresa(lead: Lead) -> list[str]:
    e = lead.empresa
    lineas = [
        "",
        f"EMPRESA: {e.nombre}",
        f"Industria: {e.industria or 'desconocida'}",
        f"Dotación: {e.tamano_etiqueta}",
        f"Ubicación: {', '.join(x for x in (e.ciudad, e.pais) if x) or 'desconocida'}",
    ]
    if e.tiene_equipo_ta:
        lineas.append(
            "Tiene equipo interno de selección (compite con nosotros por el mandato)."
        )
    return lineas


def _bloque_vacantes(lead: Lead) -> list[str]:
    abiertas = sorted(
        lead.empresa.vacantes_abiertas, key=lambda v: v.dias_abierta, reverse=True
    )
    cerradas = [v for v in lead.empresa.vacantes if v.cerrada]

    lineas = ["", f"BÚSQUEDAS ABIERTAS ({len(abiertas)}):"]
    if not abiertas:
        lineas.append("Ninguna detectada. La empresa entró por otra vía.")
    for v in abiertas[:_TOPE_VACANTES]:
        detalle = [
            f"- {v.titulo} ({v.seniority.etiqueta})",
            f"en {v.ubicacion or 'ubicación no informada'}",
            f"abierta hace {_dias(v)}",
        ]
        if v.reposteos:
            detalle.append(f"republicada {v.reposteos} vez/veces")
        if v.publicada_por_consultora:
            detalle.append("publicada por otra consultora")
        lineas.append(", ".join(detalle) + f" [fuente: {v.fuente}]")
        if v.descripcion:
            lineas.append(f"  Texto del aviso: {_recortar(v.descripcion, _TOPE_DESCRIPCION)}")

    if cerradas:
        lineas.append("")
        lineas.append(f"BÚSQUEDAS YA CERRADAS ({len(cerradas)}), por si se repiten:")
        for v in cerradas[:6]:
            lineas.append(f"- {v.titulo} (cerrada el {v.fecha_cierre or 'sin fecha'})")
    return lineas


def _bloque_senales(lead: Lead) -> list[str]:
    vigentes = [e for e in lead.empresa.eventos_vigentes]
    if not vigentes:
        return []
    lineas = ["", "HECHOS CONFIRMADOS A MANO (ya revisados, se pueden mencionar):"]
    for ev in vigentes:
        etiqueta = "ronda de inversión" if ev.tipo == TipoEvento.FINANCIAMIENTO else ev.tipo.etiqueta
        lineas.append(f"- {etiqueta}, hace {ev.dias_desde} días: {_recortar(ev.titulo, 300)}")
    return lineas


def _bloque_contactos(lead: Lead) -> list[str]:
    contactos = lead.empresa.contactos
    lineas = ["", "CONTACTOS CONOCIDOS:"]
    if not contactos:
        lineas.append("Ninguno. Todavía no sabemos con quién hablar.")
        return lineas
    for c in contactos[:8]:
        marca = " — es el decisor" if c.es_decisor else ""
        lineas.append(f"- {c.nombre}, {c.cargo or 'cargo desconocido'}{marca}")
    return lineas


def _bloque_score(lead: Lead) -> list[str]:
    lineas = [
        "",
        "LO QUE YA CALCULÓ EL SISTEMA (score determinístico, 0 a 100):",
        f"Total {lead.score:.0f} — urgencia {lead.score_urgencia:.0f}, "
        f"fit {lead.score_fit:.0f}, accesibilidad {lead.score_accesibilidad:.0f}, "
        f"capacidad de pago {lead.score_pago:.0f}.",
    ]
    lineas += [f"- {r}" for r in lead.lista_razones]
    return lineas


def _bloque_comercial(lead: Lead) -> list[str]:
    lineas = ["", "ESTADO COMERCIAL:", f"Etapa: {lead.estado.etiqueta}"]
    if lead.dias_sin_contacto is not None:
        lineas.append(f"Último contacto hace {lead.dias_sin_contacto} días.")
    else:
        lineas.append("Nunca lo contactamos.")
    if lead.proximo_paso:
        lineas.append(f"Próximo paso anotado: {lead.proximo_paso}")
    if lead.motivo_perdida:
        lineas.append(f"Motivo de pérdida anotado: {lead.motivo_perdida}")

    notas = [a for a in lead.actividades if a.tipo == "nota"][:5]
    if notas:
        lineas.append("Notas del comercial, de la más nueva a la más vieja:")
        lineas += [f"- {_recortar(a.detalle, 400)}" for a in notas]
    return lineas


def _bloque_hilo(lead: Lead) -> list[str]:
    mensajes = lead.mensajes[-_TOPE_MENSAJES:]
    lineas = ["", "CONVERSACIÓN POR MAIL:"]
    if not mensajes:
        lineas.append("Todavía no hay intercambio.")
        return lineas
    for m in mensajes:
        quien = "ELLOS" if m.direccion == Direccion.ENTRANTE else "NOSOTROS"
        lineas.append(
            f"[{quien}, {m.fecha.strftime('%d/%m/%Y')}] {m.asunto}\n"
            f"{_recortar(m.cuerpo, _TOPE_MENSAJE)}"
        )
    return lineas


def armar(session: Session, lead: Lead) -> str:
    """El expediente completo, en texto plano."""
    p = perfil(session)
    lineas: list[str] = _bloque_consultora(p)
    lineas += _bloque_empresa(lead)
    lineas += _bloque_vacantes(lead)
    lineas += _bloque_senales(lead)
    lineas += _bloque_contactos(lead)
    lineas += _bloque_score(lead)
    lineas += _bloque_comercial(lead)
    lineas += _bloque_hilo(lead)
    return "\n".join(lineas)


def firma(lead: Lead) -> str:
    """Huella de los hechos que podrían cambiar el veredicto.

    No entra el número exacto de días abiertos: que un aviso pase de 61 a 62
    días no cambia nada, y avisar «esto cambió» por eso todos los días entrena
    a ignorar el aviso. Sí entran los saltos de tramo, los mensajes nuevos y los
    cambios de etapa.
    """
    abiertas = lead.empresa.vacantes_abiertas
    partes = [
        str(len(abiertas)),
        # Tramos de 15 días: el salto importa, el día suelto no.
        str(max((v.dias_abierta // 15 for v in abiertas), default=0)),
        str(sum(v.reposteos for v in abiertas)),
        str(len(lead.mensajes)),
        str(len(lead.empresa.eventos_vigentes)),
        str(len([c for c in lead.empresa.contactos if c.es_decisor])),
        lead.estado.value,
    ]
    return hashlib.sha1("|".join(partes).encode()).hexdigest()[:16]

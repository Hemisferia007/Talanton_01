"""Vocabulario compartido de los portales y orquestación de la búsqueda.

Las zonas y los rubros son **listas cerradas** a propósito. Con Apollo ya
aprendimos que un campo de texto libre es una trampa: quien busca escribe
«Logística», el portal espera otra cosa, no matchea nada y la conclusión
equivocada es que no hay empresas de logística. Acá cada opción que se muestra
en castellano tiene su traducción al slug que espera cada portal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Protocol

from ..base import VacanteCruda

log = logging.getLogger("talanton.portales")

# Provincias y regiones, con el slug que usa cada portal. El valor es la clave
# interna; cada conector lo traduce a su propia URL.
ZONAS: list[tuple[str, str]] = [
    ("caba", "Ciudad de Buenos Aires"),
    ("gba", "GBA / Provincia de Buenos Aires"),
    ("cordoba", "Córdoba"),
    ("santa-fe", "Santa Fe / Rosario"),
    ("mendoza", "Mendoza"),
    ("tucuman", "Tucumán"),
    ("neuquen", "Neuquén / Río Negro"),
    ("salta", "Salta / Jujuy"),
    ("entre-rios", "Entre Ríos"),
    ("chubut", "Chubut / Santa Cruz"),
    ("todo-el-pais", "Todo el país"),
]

# Rubros pensados para una consultora de selección en Argentina: los que
# compran búsquedas de mando medio, no las ~200 categorías de cada portal.
RUBROS: list[tuple[str, str]] = [
    ("produccion", "Producción y manufactura"),
    ("logistica", "Logística y transporte"),
    ("mantenimiento", "Mantenimiento e ingeniería"),
    ("construccion", "Construcción"),
    ("agro", "Agro y alimentos"),
    ("comercial", "Comercial y ventas"),
    ("retail", "Retail y consumo masivo"),
    ("administracion", "Administración y finanzas"),
    ("rrhh", "Recursos humanos"),
    ("tecnologia", "Tecnología y sistemas"),
    ("salud", "Salud"),
    ("gastronomia", "Gastronomía y hotelería"),
]

_ETIQUETA_ZONA = dict(ZONAS)
_ETIQUETA_RUBRO = dict(RUBROS)


@dataclass
class Segmento:
    """Qué buscar. Es lo que el usuario define en pantalla."""

    zona: str = "todo-el-pais"
    rubro: str | None = None
    # Antigüedad mínima del aviso. Es *la* señal del producto: una búsqueda de
    # más de 45 días es una que la empresa no está pudiendo cerrar sola.
    dias_minimos: int = 0
    tope: int = 60

    @property
    def zona_etiqueta(self) -> str:
        return _ETIQUETA_ZONA.get(self.zona, self.zona)

    @property
    def rubro_etiqueta(self) -> str | None:
        return _ETIQUETA_RUBRO.get(self.rubro) if self.rubro else None


class Portal(Protocol):
    nombre: str

    def buscar(self, segmento: Segmento) -> list[VacanteCruda]: ...


@dataclass
class Resultado:
    crudas: list[VacanteCruda] = field(default_factory=list)
    por_portal: dict[str, int] = field(default_factory=dict)
    fallidos: list[str] = field(default_factory=list)


def _portales() -> list[Portal]:
    # Import perezoso: cada conector arrastra su propio parseo y no hace falta
    # cargarlos todos para, por ejemplo, correr los tests del scoring.
    from .bumeran import Bumeran, ZonaJobs
    from .computrabajo import Computrabajo

    return [Computrabajo(), Bumeran(), ZonaJobs()]


def buscar_en_portales(
    segmento: Segmento, portales: list[Portal] | None = None
) -> Resultado:
    """Consulta todos los portales. Uno caído no frena a los demás."""
    resultado = Resultado()
    for portal in portales if portales is not None else _portales():
        try:
            crudas = portal.buscar(segmento)
        except Exception as exc:  # red, HTML cambiado, anti-bot: todo es "no vino"
            log.warning("Portal %s falló: %s", portal.nombre, exc)
            resultado.fallidos.append(f"{portal.nombre}: {exc}")
            continue
        resultado.por_portal[portal.nombre] = len(crudas)
        resultado.crudas.extend(crudas)
    return resultado


def texto_de(nodo, selector: str) -> str | None:
    """Saca el texto de un selector, tolerando que no exista.

    Los portales cambian el HTML seguido: que falte un campo secundario no
    puede tirar abajo el aviso entero.
    """
    try:
        encontrado = nodo.css_first(selector)
    except Exception:
        return None
    if encontrado is None:
        return None
    texto = getattr(encontrado, "text", None) or str(encontrado)
    return " ".join(str(texto).split()) or None


def atributo_de(nodo, selector: str, atributo: str) -> str | None:
    try:
        encontrado = nodo.css_first(selector)
    except Exception:
        return None
    if encontrado is None:
        return None
    valor = encontrado.attrib.get(atributo) if hasattr(encontrado, "attrib") else None
    return str(valor).strip() if valor else None


def nodos(pagina, selector: str) -> list:
    try:
        return list(pagina.css(selector))
    except Exception:
        return []


def aplicar_antiguedad(
    crudas: list[VacanteCruda], dias_minimos: int
) -> list[VacanteCruda]:
    """Deja sólo los avisos con al menos `dias_minimos` publicados.

    Se filtra acá y no en el portal porque no todos permiten pedir «más viejo
    que N días» —casi todos ofrecen lo contrario, «de los últimos N»—.
    """
    if dias_minimos <= 0:
        return crudas
    from ...services import fecha_hoy

    hoy = fecha_hoy()
    quedan = []
    for cruda in crudas:
        if cruda.fecha_publicacion is None:
            # Sin fecha no se puede afirmar que sea vieja, y el producto se
            # apoya en poder decir el número. Mejor perderlo que inventarlo.
            continue
        if (hoy - cruda.fecha_publicacion).days >= dias_minimos:
            quedan.append(cruda)
    return quedan


PORTALES: Callable[[], list[Portal]] = _portales

"""Motor de scoring.

Cuatro ejes ponderados, cada uno con sus razones en texto. La regla que gobierna
todo el módulo: un score que el comercial no puede explicarle al cliente no se
usa. Por eso cada punto sumado deja una frase que lo justifica.

Todo lo numérico es determinístico. Si más adelante entra un LLM, entra como
generador de features (clasificar seniority, resumir contexto), nunca como
decisor del score.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .models import Empresa, PerfilConsultora, Seniority, TipoEvento

PESOS = {
    "urgencia": 0.40,
    "fit": 0.25,
    "accesibilidad": 0.20,
    "pago": 0.15,
}

# Umbrales de días abiertos. El de 45 es el que marca "la búsqueda propia falló".
DIAS_TIBIO = 30
DIAS_CALIENTE = 45
DIAS_DESESPERADO = 75

_SENIORITY_VALOR = {
    Seniority.JUNIOR: 1,
    Seniority.SEMI_SENIOR: 2,
    Seniority.SENIOR: 3,
    Seniority.JEFATURA: 4,
    Seniority.DIRECCION: 5,
    Seniority.INDEFINIDO: 2,
}


@dataclass
class Resultado:
    total: float = 0.0
    urgencia: float = 0.0
    fit: float = 0.0
    accesibilidad: float = 0.0
    pago: float = 0.0
    razones: list[str] = field(default_factory=list)
    gancho: str | None = None

    @property
    def razones_texto(self) -> str:
        return "\n".join(self.razones)


def _acotar(valor: float) -> float:
    return max(0.0, min(100.0, valor))


def _urgencia(empresa: Empresa) -> tuple[float, list[str], str | None]:
    abiertas = empresa.vacantes_abiertas
    if not abiertas:
        return 0.0, ["Sin búsquedas abiertas detectadas"], None

    razones: list[str] = []
    puntos = 0.0
    gancho: str | None = None

    # Señal 1: la vacante más vieja todavía abierta.
    mas_vieja = max(abiertas, key=lambda v: v.dias_abierta)
    dias = mas_vieja.dias_abierta
    if dias >= DIAS_DESESPERADO:
        puntos += 55
        razones.append(f"«{mas_vieja.titulo}» lleva {dias} días abierta — la búsqueda propia falló")
    elif dias >= DIAS_CALIENTE:
        puntos += 45
        razones.append(f"«{mas_vieja.titulo}» lleva {dias} días abierta")
    elif dias >= DIAS_TIBIO:
        puntos += 25
        razones.append(f"«{mas_vieja.titulo}» lleva {dias} días abierta")
    else:
        puntos += 8
        razones.append(f"Búsqueda reciente: «{mas_vieja.titulo}» ({dias} días)")

    if dias >= DIAS_TIBIO:
        gancho = (
            f"Vi que hace {dias} días están buscando {mas_vieja.titulo}"
            f"{' en ' + mas_vieja.ubicacion if mas_vieja.ubicacion else ''}."
        )

    # Señal 2: reintentaron y volvieron a fallar.
    reposteos = sum(v.reposteos for v in abiertas)
    if reposteos:
        puntos += min(20, 10 * reposteos)
        razones.append(
            f"{reposteos} reposteo{'s' if reposteos > 1 else ''} del mismo puesto: "
            "reintentaron sin éxito"
        )
        # Sólo si republicaron *esta* búsqueda: el gancho se le dice al cliente
        # tal cual, así que no puede atribuirle un reposteo que no ocurrió.
        if gancho and mas_vieja.reposteos:
            gancho += " Ya la republicaron, así que imagino que no está siendo fácil."

    # Señal 4: volumen simultáneo.
    if len(abiertas) >= 5:
        puntos += 20
        razones.append(f"{len(abiertas)} búsquedas abiertas en simultáneo: equipo desbordado")
    elif len(abiertas) >= 3:
        puntos += 12
        razones.append(f"{len(abiertas)} búsquedas abiertas en simultáneo")

    # Señal 3: el mismo rol ya se buscó y se cerró antes -> rotación.
    roles_cerrados = Counter(v.rol_normalizado for v in empresa.vacantes if v.cerrada)
    recurrentes = [v for v in abiertas if roles_cerrados.get(v.rol_normalizado)]
    if recurrentes:
        puntos += 15
        razones.append(
            f"«{recurrentes[0].titulo}» ya se había buscado antes: problema de rotación"
        )

    # La combinación es lo que vale: plata fresca y búsquedas abiertas al mismo
    # tiempo significa que están contratando en serio y con presupuesto.
    rondas = [e for e in empresa.eventos_vigentes if e.tipo == TipoEvento.FINANCIAMIENTO]
    if rondas and abiertas:
        puntos += 15
        razones.append("Levantó una ronda y ya está buscando: contrata en serio")
        if gancho:
            gancho += " Vi que además cerraron una ronda hace poco."

    return _acotar(puntos), razones, gancho


def _fit(empresa: Empresa, perfil: PerfilConsultora) -> tuple[float, list[str]]:
    razones: list[str] = []
    puntos = 0.0

    paises = perfil.paises
    if not paises or (empresa.pais and empresa.pais in paises):
        puntos += 30
        if empresa.pais:
            razones.append(f"Opera en {empresa.pais}, dentro del mercado objetivo")
    else:
        razones.append(f"Fuera del mercado objetivo ({empresa.pais or 'país desconocido'})")

    industrias = [i.lower() for i in perfil.industrias]
    if not industrias:
        puntos += 20
    elif empresa.industria and empresa.industria.lower() in industrias:
        puntos += 25
        razones.append(f"Industria {empresa.industria}: está en el ICP")

    dotacion = empresa.dotacion_estimada
    if dotacion is None:
        # Menos que antes y con la razón a la vista: una dotación desconocida
        # regalaba puntos en silencio, y como casi ninguna empresa importada
        # trae el dato, terminaba emparejando a todas por arriba.
        puntos += 5
        razones.append("Falta la dotación: cargala para que el score signifique algo")
    elif perfil.dotacion_min <= dotacion <= perfil.dotacion_max:
        puntos += 20
        razones.append(f"Dotación estimada de {dotacion} personas: tamaño objetivo")
    elif dotacion > perfil.dotacion_max:
        razones.append(
            f"Con {dotacion} empleados es más grande que tu cliente ideal: "
            "a ese tamaño hay equipo de selección propio y proveedores ya elegidos"
        )
    else:
        razones.append(f"Con {dotacion} empleados es más chica que tu cliente ideal")

    objetivos = {s.lower() for s in perfil.seniorities}
    abiertas = empresa.vacantes_abiertas
    calzan = [v for v in abiertas if v.seniority.value in objetivos]
    if calzan:
        puntos += 25
        razones.append(
            f"{len(calzan)} de {len(abiertas)} búsquedas son del seniority que cubrimos mejor"
        )

    return _acotar(puntos), razones


def _accesibilidad(empresa: Empresa) -> tuple[float, list[str]]:
    razones: list[str] = []
    puntos = 0.0

    # Antes que nada: si la empresa es una consultora, una staffing o una
    # fábrica que revende gente, no es un cliente — es competencia. Publicar
    # ochocientas búsquedas no la vuelve un lead caliente, la delata.
    if empresa.parece_proveedor:
        return 5.0, [
            "Parece una consultora o proveedora de personal, no una empresa "
            "que contrate para sí: es competencia, no cliente"
        ]

    tiene_ta, motivo = empresa.equipo_ta
    if not tiene_ta:
        puntos += 40
        razones.append("Sin equipo de selección interno: terceriza sí o sí")
    else:
        puntos += 10
        razones.append(f"Tiene reclutamiento interno ({motivo}): hay que justificar el valor")

    abiertas = empresa.vacantes_abiertas
    tomadas = [v for v in abiertas if v.publicada_por_consultora]
    if abiertas and len(tomadas) == len(abiertas):
        razones.append("Todas sus búsquedas ya las publica una consultora: lead tomado")
    elif tomadas:
        puntos += 15
        razones.append(f"{len(tomadas)} de {len(abiertas)} búsquedas ya están con otra consultora")
    else:
        puntos += 35
        razones.append("Publica sus búsquedas de forma directa, sin consultora")

    decisores = [c for c in empresa.contactos if c.es_decisor]
    if decisores:
        puntos += 25
        contacto = decisores[0]
        razones.append(f"Decisor identificado: {contacto.nombre} ({contacto.cargo or 'sin cargo'})")
    elif empresa.contactos:
        puntos += 10
        razones.append("Hay contactos cargados, falta identificar al decisor")
    else:
        razones.append("Sin contacto identificado todavía")

    return _acotar(puntos), razones


def _capacidad_pago(empresa: Empresa) -> tuple[float, list[str]]:
    razones: list[str] = []
    puntos = 0.0

    # Una ronda reciente es la mejor evidencia de capacidad de pago que existe:
    # mucho más directa que inferirla de la dotación. Sólo cuentan los eventos
    # confirmados a mano — ver ingest/posts.py.
    rondas = [
        e for e in empresa.eventos_vigentes if e.tipo == TipoEvento.FINANCIAMIENTO
    ]
    if rondas:
        reciente = min(rondas, key=lambda e: e.dias_desde)
        puntos += 30
        razones.append(
            f"Levantó una ronda hace {reciente.dias_desde} días: presupuesto fresco"
        )

    expansiones = [
        e for e in empresa.eventos_vigentes if e.tipo == TipoEvento.EXPANSION
    ]
    if expansiones:
        puntos += 10
        razones.append("Anunció expansión: suele venir con contrataciones")

    dotacion = empresa.dotacion_estimada or 0
    if dotacion >= 500:
        puntos += 45
    elif dotacion >= 100:
        puntos += 40
    elif dotacion >= 25:
        puntos += 30
    elif dotacion > 0:
        puntos += 15
    else:
        puntos += 15

    abiertas = empresa.vacantes_abiertas
    if abiertas:
        nivel = max(_SENIORITY_VALOR[v.seniority] for v in abiertas)
        puntos += nivel * 8
        if nivel >= 4:
            razones.append("Busca perfiles de jefatura o dirección: fee alto")
        elif nivel == 3:
            razones.append("Busca perfiles senior: ticket medio-alto")
        puntos += min(15, 5 * len(abiertas))

    return _acotar(puntos), razones


def calcular(empresa: Empresa, perfil: PerfilConsultora) -> Resultado:
    urgencia, r_urgencia, gancho = _urgencia(empresa)
    fit, r_fit = _fit(empresa, perfil)
    accesibilidad, r_acc = _accesibilidad(empresa)
    pago, r_pago = _capacidad_pago(empresa)

    total = (
        urgencia * PESOS["urgencia"]
        + fit * PESOS["fit"]
        + accesibilidad * PESOS["accesibilidad"]
        + pago * PESOS["pago"]
    )

    return Resultado(
        total=round(total, 1),
        urgencia=round(urgencia, 1),
        fit=round(fit, 1),
        accesibilidad=round(accesibilidad, 1),
        pago=round(pago, 1),
        # Las de urgencia primero: son las que mueven la aguja comercial.
        razones=r_urgencia + r_fit + r_acc + r_pago,
        gancho=gancho,
    )

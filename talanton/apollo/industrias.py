"""Las industrias que entiende Apollo, con nombre en castellano.

Apollo filtra por palabras clave **en inglés y de su propio vocabulario**. Un
campo de texto libre parece flexible pero es una trampa: escribís «Logística»,
la API no matchea nada, y la conclusión equivocada es que Apollo no tiene
empresas de logística en Argentina.

Por eso la lista es cerrada y curada. No están las ~150 industrias de Apollo:
están las que le compran a una consultora de selección en Argentina y LatAm.
Para lo que falte queda el campo de palabras clave libres.

`traducir()` además mapea lo que ya está escrito en castellano —el ICP de la
pantalla Mi empresa, por ejemplo— sin que haya que volver a cargarlo en inglés.
"""

from __future__ import annotations

from ..normalize import sin_acentos

# (grupo, valor que espera Apollo, etiqueta que se muestra)
INDUSTRIAS: list[tuple[str, str, str]] = [
    ("Industria y producción", "manufacturing", "Manufactura"),
    ("Industria y producción", "machinery", "Maquinaria"),
    ("Industria y producción", "automotive", "Automotriz"),
    ("Industria y producción", "electrical/electronic manufacturing", "Electrónica y eléctrica"),
    ("Industria y producción", "mechanical or industrial engineering", "Ingeniería industrial"),
    ("Industria y producción", "chemicals", "Química"),
    ("Industria y producción", "plastics", "Plásticos"),
    ("Industria y producción", "packaging & containers", "Packaging y envases"),
    ("Industria y producción", "textiles", "Textil"),
    ("Industria y producción", "paper & forest products", "Papel y madera"),
    ("Industria y producción", "building materials", "Materiales de construcción"),
    ("Industria y producción", "mining & metals", "Minería y metalurgia"),
    ("Industria y producción", "oil & energy", "Petróleo y energía"),
    ("Industria y producción", "utilities", "Servicios públicos"),
    ("Industria y producción", "pharmaceuticals", "Farmacéutica"),

    ("Agro y alimentos", "farming", "Agropecuario"),
    ("Agro y alimentos", "ranching", "Ganadería"),
    ("Agro y alimentos", "food production", "Producción de alimentos"),
    ("Agro y alimentos", "food & beverages", "Alimentos y bebidas"),
    ("Agro y alimentos", "wine & spirits", "Vitivinícola"),

    ("Logística y transporte", "logistics & supply chain", "Logística y supply chain"),
    ("Logística y transporte", "transportation/trucking/railroad", "Transporte y ferrocarril"),
    ("Logística y transporte", "warehousing", "Almacenamiento"),
    ("Logística y transporte", "maritime", "Marítimo y puertos"),
    ("Logística y transporte", "import & export", "Comercio exterior"),
    ("Logística y transporte", "airlines/aviation", "Aviación"),

    ("Comercio", "retail", "Retail"),
    ("Comercio", "wholesale", "Mayorista y distribución"),
    ("Comercio", "supermarkets", "Supermercados"),
    ("Comercio", "consumer goods", "Consumo masivo"),
    ("Comercio", "apparel & fashion", "Indumentaria"),

    ("Construcción e inmobiliario", "construction", "Construcción"),
    ("Construcción e inmobiliario", "civil engineering", "Ingeniería civil"),
    ("Construcción e inmobiliario", "architecture & planning", "Arquitectura"),
    ("Construcción e inmobiliario", "real estate", "Inmobiliario"),

    ("Servicios y finanzas", "financial services", "Servicios financieros"),
    ("Servicios y finanzas", "banking", "Banca"),
    ("Servicios y finanzas", "insurance", "Seguros"),
    ("Servicios y finanzas", "accounting", "Contabilidad y auditoría"),
    ("Servicios y finanzas", "management consulting", "Consultoría"),
    ("Servicios y finanzas", "legal services", "Servicios legales"),
    ("Servicios y finanzas", "facilities services", "Servicios generales y facility"),
    ("Servicios y finanzas", "security & investigations", "Seguridad privada"),

    ("Tecnología", "information technology & services", "IT y servicios"),
    ("Tecnología", "computer software", "Software"),
    ("Tecnología", "internet", "Internet"),
    ("Tecnología", "telecommunications", "Telecomunicaciones"),
    ("Tecnología", "computer & network security", "Ciberseguridad"),

    ("Salud y educación", "hospital & health care", "Salud"),
    ("Salud y educación", "medical devices", "Dispositivos médicos"),
    ("Salud y educación", "biotechnology", "Biotecnología"),
    ("Salud y educación", "education management", "Educación"),
    ("Salud y educación", "higher education", "Educación superior"),

    ("Hotelería y turismo", "hospitality", "Hotelería"),
    ("Hotelería y turismo", "restaurants", "Gastronomía"),
    ("Hotelería y turismo", "leisure, travel & tourism", "Turismo"),
]

VALORES = {valor for _, valor, _ in INDUSTRIAS}


def agrupadas() -> list[tuple[str, list[tuple[str, str]]]]:
    """Para pintar el `<select>` con `<optgroup>`, respetando el orden de arriba."""
    grupos: list[tuple[str, list[tuple[str, str]]]] = []
    for grupo, valor, etiqueta in INDUSTRIAS:
        if not grupos or grupos[-1][0] != grupo:
            grupos.append((grupo, []))
        grupos[-1][1].append((valor, etiqueta))
    return grupos


def _clave(texto: str) -> str:
    return sin_acentos(texto or "").strip().lower()


# Sinónimos: cómo lo escribe la gente → cómo lo llama Apollo. Cubre lo que ya
# está cargado en el ICP y lo que uno tipea sin pensar.
_SINONIMOS = {
    "logistica": "logistics & supply chain",
    "transporte": "transportation/trucking/railroad",
    "deposito": "warehousing",
    "almacenamiento": "warehousing",
    "manufactura": "manufacturing",
    "industria": "manufacturing",
    "industrial": "manufacturing",
    "metalurgica": "mining & metals",
    "metalurgia": "mining & metals",
    "mineria": "mining & metals",
    "energia": "oil & energy",
    "petroleo": "oil & energy",
    "agro": "farming",
    "agropecuario": "farming",
    "agricultura": "farming",
    "campo": "farming",
    "alimentos": "food & beverages",
    "alimenticia": "food & beverages",
    "bebidas": "food & beverages",
    "vitivinicola": "wine & spirits",
    "bodega": "wine & spirits",
    "construccion": "construction",
    "inmobiliaria": "real estate",
    "inmobiliario": "real estate",
    "comercio": "retail",
    "retail": "retail",
    "supermercado": "supermarkets",
    "supermercados": "supermarkets",
    "consumo masivo": "consumer goods",
    "indumentaria": "apparel & fashion",
    "textil": "textiles",
    "salud": "hospital & health care",
    "clinica": "hospital & health care",
    "farmaceutica": "pharmaceuticals",
    "laboratorio": "pharmaceuticals",
    "educacion": "education management",
    "tecnologia": "information technology & services",
    "sistemas": "information technology & services",
    "software": "computer software",
    "informatica": "information technology & services",
    "telecomunicaciones": "telecommunications",
    "banco": "banking",
    "banca": "banking",
    "finanzas": "financial services",
    "seguros": "insurance",
    "consultoria": "management consulting",
    "estudio contable": "accounting",
    "contabilidad": "accounting",
    "legales": "legal services",
    "seguridad": "security & investigations",
    "hoteleria": "hospitality",
    "hotel": "hospitality",
    "gastronomia": "restaurants",
    "restaurante": "restaurants",
    "turismo": "leisure, travel & tourism",
    "quimica": "chemicals",
    "plasticos": "plastics",
    "packaging": "packaging & containers",
    "envases": "packaging & containers",
    "automotriz": "automotive",
    "autopartes": "automotive",
    "maquinaria": "machinery",
    "electronica": "electrical/electronic manufacturing",
    "papel": "paper & forest products",
    "madera": "paper & forest products",
}

# Las etiquetas visibles también sirven como entrada: quien copia «Logística y
# supply chain» de la lista espera que funcione.
_POR_ETIQUETA = {_clave(etiqueta): valor for _, valor, etiqueta in INDUSTRIAS}


def traducir(texto: str) -> str:
    """Lleva un nombre de industria a lo que espera Apollo.

    Si no lo reconoce devuelve el texto en minúsculas: Apollo hace coincidencia
    por palabra clave, así que un término desconocido puede llegar a servir, y
    descartarlo en silencio sería peor que mandarlo.
    """
    clave = _clave(texto)
    if not clave:
        return ""
    if clave in VALORES:
        return clave
    if clave in _POR_ETIQUETA:
        return _POR_ETIQUETA[clave]
    if clave in _SINONIMOS:
        return _SINONIMOS[clave]
    return clave


def traducir_todas(textos: list[str]) -> list[str]:
    """Traduce y deduplica, conservando el orden en que se eligieron."""
    salida: list[str] = []
    for texto in textos:
        valor = traducir(texto)
        if valor and valor not in salida:
            salida.append(valor)
    return salida

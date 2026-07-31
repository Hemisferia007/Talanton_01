"""Un DOM mínimo para probar los conectores de portales sin instalar Scrapling.

Scrapling es opcional —la web y el resto de los tests corren sin él— pero los
conectores lo necesitan para parsear. Antes que saltear esos tests, se implementa
acá el pedacito de interfaz que los conectores usan: `css`, `css_first`, `.text`
y `.attrib`, más el subconjunto de CSS que aparece en los selectores.

Qué prueba esto y qué no: prueba que el **mapeo** a `VacanteCruda` es correcto y
que los selectores le pegan a la estructura documentada de cada portal. No prueba
—no puede— que esa estructura sea la que el portal sirve hoy. Eso se verifica la
primera vez contra el sitio real.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

_VACIOS = {"br", "img", "input", "meta", "link", "hr"}


class Nodo:
    def __init__(self, tag: str, attrib: dict[str, str] | None = None):
        self.tag = tag
        self.attrib = dict(attrib or {})
        self.hijos: list["Nodo"] = []
        self.texto_propio: list[str] = []

    # --- Interfaz que usan los conectores ------------------------------------

    @property
    def text(self) -> str:
        partes = list(self.texto_propio)
        for hijo in self.hijos:
            partes.append(hijo.text)
        return " ".join(p for p in partes if p.strip())

    def css(self, selector: str) -> list["Nodo"]:
        encontrados: list[Nodo] = []
        for parte in selector.split(","):
            for nodo in self._buscar(parte.strip()):
                if nodo not in encontrados:
                    encontrados.append(nodo)
        return encontrados

    def css_first(self, selector: str) -> "Nodo | None":
        encontrados = self.css(selector)
        return encontrados[0] if encontrados else None

    # --- Motor ---------------------------------------------------------------

    def _descendientes(self):
        for hijo in self.hijos:
            yield hijo
            yield from hijo._descendientes()

    def _buscar(self, selector: str) -> list["Nodo"]:
        # `a > b` es hijo directo; `a b`, descendiente. Alcanza con eso.
        if ">" in selector:
            izq, der = (p.strip() for p in selector.split(">", 1))
            return [
                hijo
                for padre in self._buscar(izq)
                for hijo in padre.hijos
                if _matchea(hijo, der)
            ]
        partes = selector.split()
        if len(partes) > 1:
            actuales = self._buscar(partes[0])
            for parte in partes[1:]:
                actuales = [
                    nieto
                    for nodo in actuales
                    for nieto in nodo._descendientes()
                    if _matchea(nieto, parte)
                ]
            return actuales
        return [n for n in self._descendientes() if _matchea(n, selector)]


_ATRIBUTO = re.compile(r"\[([\w-]+)(?:([\^\*\$]?=)['\"]?([^'\"\]]*)['\"]?)?\]")


def _matchea(nodo: Nodo, simple: str) -> bool:
    if not simple or simple == "*":
        return True

    resto = simple
    for bruto in _ATRIBUTO.finditer(simple):
        nombre, operador, valor = bruto.groups()
        actual = nodo.attrib.get(nombre)
        if actual is None:
            return False
        if operador == "=" and actual != valor:
            return False
        if operador == "^=" and not actual.startswith(valor):
            return False
        if operador == "*=" and valor not in actual:
            return False
        if operador == "$=" and not actual.endswith(valor):
            return False
    resto = _ATRIBUTO.sub("", resto)

    clases = resto.split(".")
    tag = clases[0]
    if tag and nodo.tag != tag:
        return False
    propias = (nodo.attrib.get("class") or "").split()
    return all(c in propias for c in clases[1:] if c)


class _Armador(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.raiz = Nodo("#raiz")
        self.pila = [self.raiz]

    def handle_starttag(self, tag, attrs):
        nodo = Nodo(tag, dict(attrs))
        self.pila[-1].hijos.append(nodo)
        if tag not in _VACIOS:
            self.pila.append(nodo)

    def handle_endtag(self, tag):
        for i in range(len(self.pila) - 1, 0, -1):
            if self.pila[i].tag == tag:
                del self.pila[i:]
                return

    def handle_data(self, data):
        if data.strip():
            self.pila[-1].texto_propio.append(data.strip())


def parsear(html: str) -> Nodo:
    armador = _Armador()
    armador.feed(html)
    armador.close()
    return armador.raiz

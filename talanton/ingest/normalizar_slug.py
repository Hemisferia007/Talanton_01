"""Candidatos de slug para sondear boards de ATS.

Las empresas rara vez usan su razón social como identificador de board:
"Andes Logística S.R.L." con dominio andeslogistica.com.ar publica en
`andeslogistica`, y a veces en `andes`. Como sondear es barato (un GET que
devuelve 404 al toque), conviene probar varias formas antes de darla por
perdida — pero en orden de probabilidad, no a lo bruto.
"""

from __future__ import annotations

import re

from ..normalize import normalizar_nombre_empresa, sin_acentos


def _limpiar(texto: str) -> str:
    texto = sin_acentos(texto or "").lower()
    return re.sub(r"[^a-z0-9]", "", texto)


def candidatos_de_slug(empresa: str, dominio: str | None = None) -> list[str]:
    """Devuelve slugs a probar, del más probable al menos, sin repetidos.

    El dominio manda cuando existe: una empresa que tiene andeslogistica.com.ar
    casi siempre usa `andeslogistica` como slug.
    """
    candidatos: list[str] = []

    if dominio:
        # El label principal del dominio, sin www ni el TLD.
        etiqueta = dominio.lower().removeprefix("www.").split(".")[0]
        candidatos.append(_limpiar(etiqueta))
        # Con guiones, que algunas plataformas prefieren.
        candidatos.append(re.sub(r"[^a-z0-9]+", "-", sin_acentos(etiqueta).lower()).strip("-"))

    normalizado = normalizar_nombre_empresa(empresa)
    candidatos.append(_limpiar(normalizado))
    candidatos.append(re.sub(r"\s+", "-", normalizado))

    # Sólo la primera palabra: "Grupo Sanitario del Plata" → "grupo".
    # Va último porque es el más ambiguo y puede pegarle a otra empresa.
    primera = normalizado.split(" ")[0] if normalizado else ""
    if len(primera) >= 4:
        candidatos.append(_limpiar(primera))

    vistos: set[str] = set()
    unicos = []
    for c in candidatos:
        if c and len(c) >= 3 and c not in vistos:
            vistos.add(c)
            unicos.append(c)
    return unicos
